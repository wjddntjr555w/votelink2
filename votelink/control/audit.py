"""감사 로그. 제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §10.

**경쟁 캠프를 제한 없이 받기로 했으므로 이건 선택이 아니라 필수다** (P-001 §10).
같은 선거구의 여당·야당 후보 데이터가 한 서버에 공존할 수 있고, 그러면
"유출이 없었다"를 증명할 수단이 있어야 한다.

**한계를 알고 쓴다.** 캠프당 계정이 1개라 로그는 "이 캠프의 누군가"까지만 말한다.
캠프 *간* 경계는 추적되지만 캠프 *내부* 행위자는 특정되지 않는다 (P-002 §7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from votelink.control.db import connect, now


@dataclass(frozen=True)
class Entry:
    id: int
    at: str
    account_id: int | None
    camp_id: str | None
    action: str
    target: str | None
    detail: dict
    ip: str | None


def log(
    action: str,
    *,
    account_id: int | None = None,
    camp_id: str | None = None,
    target: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    path: Path | None = None,
) -> None:
    """한 줄 남긴다. **실패해도 요청을 죽이지 않는다.**

    감사 로그를 못 써서 화면이 안 뜨면 사용자는 이유를 알 수 없고, 그건 로그가
    없는 것보다 나쁘다. 대신 조용히 삼키지 않고 stderr 로 드러낸다.
    """
    try:
        with connect(path) as conn:
            conn.execute(
                "INSERT INTO audit_log (at, account_id, camp_id, action, target, detail, ip) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now(),
                    account_id,
                    camp_id,
                    action,
                    target,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                    ip,
                ),
            )
    except Exception as exc:  # noqa: BLE001 - 감사 실패가 서비스를 죽이면 안 된다
        import sys

        print(f"[감사 기록 실패] {action}: {exc}", file=sys.stderr)


def recent(
    *,
    limit: int = 200,
    camp_id: str | None = None,
    account_id: int | None = None,
    path: Path | None = None,
) -> list[Entry]:
    sql = "SELECT * FROM audit_log"
    where, args = [], []
    if camp_id is not None:
        where.append("camp_id = ?")
        args.append(camp_id)
    if account_id is not None:
        where.append("account_id = ?")
        args.append(account_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    with connect(path) as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [
        Entry(
            id=r["id"],
            at=r["at"],
            account_id=r["account_id"],
            camp_id=r["camp_id"],
            action=r["action"],
            target=r["target"],
            detail=json.loads(r["detail"]) if r["detail"] else {},
            ip=r["ip"],
        )
        for r in rows
    ]
