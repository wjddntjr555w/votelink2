"""가입 신청과 승인. 제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §6.

    신청 →  signup_requests 행 + status='pending' 계정
    승인 →  camps/<camp_id>/camp.yaml **골격만** (디스크에 캠프 공간이 생긴다)
    온보딩 → cycles/<id>/election.yaml · candidates.yaml (캠프가 웹에서 채운다)

**승인이 DB↔디스크 인계점이다.** 승인 전에는 캠프 공간이 존재하지 않는다.
신청을 가볍게 받는 이유는 영업 문턱이고, 정확한 관할·진영은 승인 후에 받는다 —
그래야 캠프가 아직 확정하지 못한 값을 억지로 적지 않는다.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from votelink.camp.models import CampInfo
from votelink.camp.scaffold import ScaffoldError, write_camp
from votelink.control import accounts as acc
from votelink.control.db import connect, now


class SignupError(ValueError):
    """신청하거나 승인할 수 없는 상태."""


@dataclass(frozen=True)
class Request:
    id: int
    account_id: int
    candidate_name: str
    contact: str
    wanted_election: str | None
    status: str
    requested_at: str
    decided_at: str | None
    decided_by: int | None
    note: str | None

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"


def suggest_camp_id(candidate_name: str, email: str) -> str:
    """`camp_id` 후보. 경로 세그먼트가 되므로 소문자·숫자·하이픈만 (`CampInfo` 가 강제).

    한글 이름은 경로에 쓰지 않는다 — 파일시스템·URL·로그에서 인코딩이 제각각이라
    "같은 캠프인데 다른 문자열"이 생긴다. 이메일 로컬파트를 뼈대로 쓴다.
    """
    stem = re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-")
    return stem or "camp"


def request(
    email: str,
    password: str,
    candidate_name: str,
    contact: str,
    wanted_election: str | None = None,
    *,
    path: Path | None = None,
) -> Request:
    """가입 신청. 계정은 `pending` 으로 만들어진다 — `/pending` 외에는 아무것도 못 본다."""
    for label, value in (("후보 이름", candidate_name), ("연락처", contact)):
        if not (value or "").strip():
            raise SignupError(f"{label} 가 비었다")

    account = acc.create(email, password, role=acc.Role.CAMP, status=acc.Status.PENDING, path=path)
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO signup_requests "
            "(account_id, candidate_name, contact, wanted_election, status, requested_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (account.id, candidate_name.strip(), contact.strip(), wanted_election, now()),
        )
        return _get(conn, cur.lastrowid)


def _get(conn, request_id: int) -> Request:
    row = conn.execute("SELECT * FROM signup_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise SignupError(f"신청 {request_id} 이 없다")
    return Request(**dict(row))


def get(request_id: int, *, path: Path | None = None) -> Request:
    with connect(path) as conn:
        return _get(conn, request_id)


def for_account(account_id: int, *, path: Path | None = None) -> Request | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM signup_requests WHERE account_id = ? ORDER BY id DESC LIMIT 1",
            (account_id,),
        ).fetchone()
    return Request(**dict(row)) if row else None


def pending(*, path: Path | None = None) -> list[Request]:
    """승인 큐. 운영자가 본다."""
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM signup_requests WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    return [Request(**dict(r)) for r in rows]


def approve(
    request_id: int,
    operator_id: int,
    *,
    camp_id: str | None = None,
    note: str | None = None,
    path: Path | None = None,
    camps_root: Path | None = None,
) -> str:
    """승인하고 **디스크에 캠프 공간을 만든다**. 만들어진 `camp_id` 를 돌려준다.

    캠프 공간을 먼저 만들고 DB 를 고친다 — 순서가 반대면 "승인됐는데 공간이 없는"
    계정이 생기고, 그 계정은 로그인해도 갈 곳이 없다. 공간만 남고 승인이 실패하면
    다음 승인 때 `ScaffoldError` 로 드러나 사람이 알아챈다.
    """
    req = get(request_id, path=path)
    if not req.is_pending:
        raise SignupError(f"신청 {request_id} 은 이미 '{req.status}' 다")

    account = acc.get(req.account_id, path=path)
    cid = camp_id or suggest_camp_id(req.candidate_name, account.email)

    info = CampInfo(camp_id=cid, candidate_name=req.candidate_name, created_at=dt.date.today())
    try:
        write_camp(info, camps_root)
    except ScaffoldError as exc:
        raise SignupError(f"캠프 공간을 만들 수 없다: {exc}") from exc

    with connect(path) as conn:
        conn.execute(
            "UPDATE signup_requests SET status='approved', decided_at=?, decided_by=?, note=? "
            "WHERE id = ?",
            (now(), operator_id, note, request_id),
        )
        conn.execute(
            "UPDATE accounts SET status = ?, camp_id = ? WHERE id = ?",
            (acc.Status.ACTIVE.value, cid, req.account_id),
        )
    return cid


def reject(request_id: int, operator_id: int, *, note: str, path: Path | None = None) -> None:
    """거절. **사유를 반드시 적는다** — 신청자가 무엇을 고쳐야 하는지 알아야 한다."""
    if not (note or "").strip():
        raise SignupError("거절 사유가 비었다. 신청자가 무엇을 고쳐야 하는지 알 수 없다")
    req = get(request_id, path=path)
    if not req.is_pending:
        raise SignupError(f"신청 {request_id} 은 이미 '{req.status}' 다")
    with connect(path) as conn:
        conn.execute(
            "UPDATE signup_requests SET status='rejected', decided_at=?, decided_by=?, note=? "
            "WHERE id = ?",
            (now(), operator_id, note, request_id),
        )
        conn.execute(
            "UPDATE accounts SET status = ? WHERE id = ?",
            (acc.Status.SUSPENDED.value, req.account_id),
        )
