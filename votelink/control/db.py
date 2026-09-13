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

-- 운영자 화면에서 누른 수집·분석 실행 (P-003 §4). CLI 를 subprocess 로 감싸기만
-- 한다 — 격리율 임계·--dry-run 같은 규칙은 전부 CLI 에 있고 여기서 다시 구현하지
-- 않는다. 웹 프로세스가 죽으면 실행 중이던 행이 고아로 남는다 — 재시작 시
-- `jobs.reap_orphans` 가 그런 행을 failed 로 정리한다(완벽하지 않지만 운영자가
-- 다시 누르면 된다. §4).
--
-- `started_by` 에 외래키를 걸지 않는다 — audit_log 와 같은 이유다(위 주석). 이건
-- 실행 **이력**이고, 계정이 지워지거나 id 가 어긋나도 "누가 언제 무엇을 돌렸다"는
-- 기록 자체는 남아야 한다.
CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,        -- 'collect' | 'analyze'
  target      TEXT NOT NULL,        -- collector_id / analyzer_id
  args        TEXT NOT NULL,        -- JSON 목록. CLI 인자 그대로 (실행한 명령과 정확히 같다)
  note        TEXT,                 -- 화면 표시용 부가 설명(예: "후보 검색어만"). 실행엔 안 쓰인다
  status      TEXT NOT NULL,        -- 'running' | 'done' | 'failed'
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  exit_code   INTEGER,
  log_path    TEXT,
  started_by  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
CREATE INDEX IF NOT EXISTS idx_audit_camp ON audit_log(camp_id);
CREATE INDEX IF NOT EXISTS idx_jobs_started_at ON jobs(started_at);
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
    """스키마를 만든다. 여러 번 불러도 안전하다.

    **`CREATE TABLE IF NOT EXISTS` 는 이미 있는 테이블에 새 컬럼을 추가하지
    않는다.** `jobs` 가 생긴 뒤 `note` 컬럼이 나중에 추가됐다 — 이 함수를 먼저
    돌려본 적 있는 기존 `control.db` 는 새 코드가 참조하는 컬럼이 없어 다음
    쓰기·읽기에서 그대로 터진다. 그래서 스키마를 만든 다음 부족한 컬럼을
    `ALTER TABLE` 로 메운다. 새 컬럼이 생길 때마다 이 표에 한 줄 추가한다.
    """
    target = path or CONTROL_DB
    with connect(target) as conn:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn, "jobs", [("note", "TEXT")])
    return target


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def exists(path: Path | None = None) -> bool:
    return (path or CONTROL_DB).exists()
