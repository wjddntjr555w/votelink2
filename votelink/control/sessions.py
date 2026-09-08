"""세션. 제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §8.

토큰은 `secrets.token_urlsafe` 로 만들어 쿠키에 넣고, **해시만 DB 에 둔다.** 원문을
저장하지 않으므로 DB 가 새도 남의 세션을 탈취할 수 없다.

조회로 검증하니 서명 쿠키가 필요 없다 — `itsdangerous` 의존성이 사라진다. 그리고
세션이 DB 에 있으므로 **강제 종료가 공짜로 따라온다.** 2FA 를 두지 않기로 한
결정(공유 계정에서는 시드도 공유된다)의 보완책이 이것이다.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from votelink.contract.models import KST
from votelink.control.db import connect, now

IDLE_TTL = timedelta(hours=12)
"""유휴 만료. 요청마다 연장된다.

캠프는 하루 종일 쓰는 도구라 짧으면 방해가 된다. 근거가 강한 값은 아니다 —
운영하며 조정한다 (P-002 §14).
"""

COOKIE_NAME = "votelink_session"


@dataclass(frozen=True)
class Session:
    account_id: int
    created_at: str
    expires_at: str
    ip: str | None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _expiry(at: datetime | None = None) -> str:
    return ((at or datetime.now(KST)) + IDLE_TTL).isoformat(timespec="seconds")


def start(
    account_id: int,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    path: Path | None = None,
) -> str:
    """세션을 열고 **원문 토큰**을 돌려준다. 이 값이 쿠키로 나간다."""
    token = secrets.token_urlsafe(32)
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, account_id, created_at, expires_at, ip, user_agent) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_hash(token), account_id, now(), _expiry(), ip, (user_agent or "")[:300]),
        )
    return token


def resolve(token: str | None, *, path: Path | None = None) -> Session | None:
    """토큰 → 세션. 만료됐으면 지우고 None.

    만료를 조회 시점에 정리한다 — 별도 청소 작업을 두지 않아도 죽은 세션이 쌓이지 않는다.
    """
    if not token:
        return None
    digest = _hash(token)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT account_id, created_at, expires_at, ip FROM sessions WHERE token_hash = ?",
            (digest,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
            return None
        # 유휴 연장. 쓰는 동안에는 끊기지 않는다.
        conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (_expiry(), digest))
        return Session(
            account_id=row["account_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            ip=row["ip"],
        )


def end(token: str | None, *, path: Path | None = None) -> None:
    if token:
        with connect(path) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def end_all(account_id: int, *, path: Path | None = None) -> int:
    """그 계정의 세션을 전부 끊는다. **운영자의 강제 로그아웃.**

    비밀번호가 샜을 때 쓸 수 있는 유일한 즉시 대응이다 (P-002 §14).
    """
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))
        return cur.rowcount


def active_count(account_id: int, *, path: Path | None = None) -> int:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE account_id = ? AND expires_at > ?",
            (account_id, now()),
        ).fetchone()
    return row["n"]
