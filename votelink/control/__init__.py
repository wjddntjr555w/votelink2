"""control plane — 계정·세션·승인·감사.

제안서: `docs/proposals/P-002-auth-and-camp-approval.md`.

**data plane 과 갈라져 있다.** 여기는 운영 상태(`data/control.db`)이고, 분석 코퍼스는
`data/shared/records/*.jsonl` 이다 (P-001). 목적도 수명도 다르다.

이 패키지는 웹을 모른다 — 의존이 한 방향이다. 웹이 이것을 쓴다.
"""

from votelink.control import accounts, audit, jobs, sessions, signup
from votelink.control.accounts import Account, AccountError, Role, Status
from votelink.control.db import CONTROL_DB, connect, init
from votelink.control.sessions import COOKIE_NAME, Session
from votelink.control.signup import SignupError

__all__ = [
    "CONTROL_DB",
    "COOKIE_NAME",
    "Account",
    "AccountError",
    "Role",
    "Session",
    "SignupError",
    "Status",
    "accounts",
    "audit",
    "connect",
    "init",
    "jobs",
    "sessions",
    "signup",
]
