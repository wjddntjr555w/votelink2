"""control plane 의 저장소 — `data/control.db` (SQLite).

제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §4·§5.

**data plane 과 갈라 둔다.**

    control plane   data/control.db                  계정·세션·승인·감사. 운영 상태
    data plane      data/shared/records/*.jsonl      분석 코퍼스 (P-001)

`docs/11-storage.md` 는 SQLite 도입 시점을 "건수가 자릿수로 커질 때"로 적어뒀다. 인증은
**양이 아니라 동시성**으로 그 시점을 앞당긴다 — 동시 로그인·세션 갱신은 파일 락으로
감당할 일이 아니다. 그렇다고 레코드까지 옮기지는 않는다. 목적도 수명도 다르다.

`docs/00-overview.md` 가 예고한 `data/votelink.db` 라는 이름을 쓰지 않는다. 그 이름은
레코드 질의 계층 몫으로 남겨둔다.

**L3 는 레코드를 쓰지 않는다** (`votelink/web/__init__.py`). 여기는 레코드가 아니다 —
`data/shared/records/` 밖이고, `tests/test_web.py::test_serving_never_writes` 가 계속
통과한다는 사실이 그 규칙이 지켜졌다는 증거다.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from votelink.contract.models import KST
from votelink.store import DATA_DIR

CONTROL_DB = DATA_DIR / "control.db"
"""운영 상태의 단일 파일. `.gitignore` 의 `data/*.db` 가 이미 막고 있다."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL,
  camp_id       TEXT,
  status        TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS signup_requests (
  id              INTEGER PRIMARY KEY,
  account_id      INTEGER NOT NULL REFERENCES accounts(id),
  candidate_name  TEXT NOT NULL,
  contact         TEXT NOT NULL,
  wanted_election TEXT,
  status          TEXT NOT NULL,
  requested_at    TEXT NOT NULL,
  decided_at      TEXT,
  decided_by      INTEGER REFERENCES accounts(id),
  note            TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ip         TEXT,
  user_agent TEXT
);

-- account_id 에 외래키를 걸지 않는다. P-002 §5 초안은 걸어 뒀으나 감사 로그에는
-- 맞지 않는다 — 이건 **이력**이고, 이력은 현재 상태에 묶이면 안 된다.
-- 계정이 지워지거나 id 가 어긋나면 그 계정의 흔적이 통째로 사라지거나 기록 자체가
-- 실패하는데, "유출이 없었다"를 증명해야 하는 표에서 그건 최악이다 (P-001 §10).
CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY,
  at         TEXT NOT NULL,
  account_id INTEGER,
  camp_id    TEXT,
  action     TEXT NOT NULL,
  target     TEXT,
  detail     TEXT,
  ip         TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
CREATE INDEX IF NOT EXISTS idx_audit_camp ON audit_log(camp_id);
"""


def now() -> str:
    """KST ISO 문자열. 저장소의 모든 시각이 한국 현지시각 기준이다 (계약 §2)."""
    return datetime.now(KST).isoformat(timespec="seconds")


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """열고 쓰고 닫는다. **연결을 전역에 들지 않는다.**

    모듈 전역 연결은 요청별 상태를 담을 수 없고 스레드 경계를 넘는다 — `store.py` 의
    모듈 상수 경로를 걷어낸 것과 같은 이유다 (`P-001` §10).

    `PRAGMA foreign_keys` 는 SQLite 가 연결마다 꺼진 채로 시작하므로 매번 켠다.
    """
    target = path or CONTROL_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # 동시 읽기 중 쓰기를 막지 않는다. 운영자 화면과 캠프 열람이 겹친다.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
    finally:
        conn.close()


def init(path: Path | None = None) -> Path:
    """스키마를 만든다. 여러 번 불러도 안전하다."""
    target = path or CONTROL_DB
    with connect(target) as conn:
        conn.executescript(SCHEMA)
    return target


def exists(path: Path | None = None) -> bool:
    return (path or CONTROL_DB).exists()
