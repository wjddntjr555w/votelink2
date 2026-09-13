"""운영자 화면에서 누른 수집·분석 실행 — 첫 백그라운드 작업.

제안서: `docs/proposals/P-003-operator-console.md` §4.

**CLI 를 subprocess 로 감싸기만 한다.** 격리율 5% 초과 시 커밋 안 함, `--dry-run`
같은 규칙은 전부 `votelink.cli` 에 이미 있다. 여기서 다시 구현하면 둘이 갈라진다.

**큐·워커·재시도는 없다.** 운영자 1명이 쓰는 화면이고 동시에 여러 수집을 돌릴
이유가 없다. 같은 대상이 이미 실행 중이면 새 실행을 거부하는 정도로 충분하다.

**진행 중인 프로세스 핸들은 이 웹 프로세스의 메모리에만 있다.** 웹 프로세스가
재시작되면 그 핸들이 사라지므로, DB 에 `running` 으로 남은 행은 이 프로세스가
시작한 적 없는 고아다 — `reap_orphans()` 가 기동 시 그런 행을 `failed` 로 정리한다
(완벽하지 않지만 운영자가 다시 누르면 된다, §4).

로그는 파일에 쌓는다. **화면은 상태(running/done/failed)와 종료 코드만 보여주고
로그 본문은 노출하지 않는다** — 수집기가 URL 에 API 키를 붙이면 로그에 그대로
남을 수 있어서다(§6). 로그 파일 자체는 운영자가 서버에서 직접 확인한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from votelink.control.db import connect, now
from votelink.store import DATA_DIR

LOG_DIR = DATA_DIR / "logs" / "jobs"

_lock = threading.Lock()
# job id -> (Popen, 로그 파일 핸들). 이 프로세스가 시작한 작업만 여기 있다.
_running: dict[int, tuple[subprocess.Popen, object]] = {}


class JobError(RuntimeError):
    """같은 대상이 이미 실행 중이다."""


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    target: str
    args: list[str]
    note: str | None
    status: str
    started_at: str
    finished_at: str | None
    exit_code: int | None
    log_path: str | None
    started_by: int | None


def _row_to_job(row) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        target=row["target"],
        args=json.loads(row["args"]),
        note=row["note"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        log_path=row["log_path"],
        started_by=row["started_by"],
    )


def _sync_running(path: Path | None = None) -> None:
    """메모리에 든 프로세스 중 끝난 것을 DB 에 반영한다. 조회 때마다 부른다.

    폴링 스레드를 따로 두지 않는다 — 화면이 몇 초 간격으로 다시 물어보는 것으로
    충분하고, 운영자 1명이 쓰는 화면에 백그라운드 스레드를 더할 이유가 없다.
    """
    with _lock:
        finished = [jid for jid, (proc, _) in _running.items() if proc.poll() is not None]
        for jid in finished:
            proc, log_file = _running.pop(jid)
            log_file.close()
            status = "done" if proc.returncode == 0 else "failed"
            with connect(path) as conn:
                conn.execute(
                    "UPDATE jobs SET status = ?, finished_at = ?, exit_code = ? WHERE id = ?",
                    (status, now(), proc.returncode, jid),
                )


def is_running(kind: str, target: str, path: Path | None = None) -> bool:
    _sync_running(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE kind = ? AND target = ? AND status = 'running' LIMIT 1",
            (kind, target),
        ).fetchone()
    return row is not None


def _command(kind: str, target: str, args: list[str]) -> list[str]:
    """실행할 명령. 테스트가 이 함수만 monkeypatch 해서 실제 CLI 를 부르지 않고도
    성공/실패 시나리오를 짧고 결정적으로 재현한다."""
    return [sys.executable, "-m", "votelink.cli", kind, target, *args]


def start(
    kind: str,
    target: str,
    args: list[str],
    started_by: int | None,
    *,
    path: Path | None = None,
    log_dir: Path | None = None,
    env: dict[str, str] | None = None,
    note: str | None = None,
) -> Job:
    """`python -m votelink.cli <kind> <target> <args...>` 를 백그라운드로 띄운다.

    같은 (kind, target)이 이미 실행 중이면 거부한다 — 겹쳐 돌리면 같은 raw 를
    두 프로세스가 동시에 쓰는 경쟁이 생긴다. `log_dir` 주입은 테스트용이다 —
    안 주면 실제 로그 디렉터리(`data/logs/jobs/`)에 쓴다.

    `env` 는 부모(웹 프로세스) 환경 위에 **덮어써서** 자식에게 넘긴다 — `.env`의
    시크릿(NAVER_CLIENT_ID 등)은 그대로 상속되고, 여기 준 값만 얹힌다. 실행할
    명령의 일부가 아닌 부가 동작(예: naver_news 의 검색어 범위)을 CLI 인자를
    새로 만들지 않고 이 방식으로 전달한다 — 이미 시크릿도 같은 통로(환경변수)를
    쓴다.

    `note` 는 `args` 만으로는 구분 안 되는 실행을 화면에서 설명하는 부가 문구다
    (예: "후보 검색어만"). **실제 실행에는 전혀 영향을 주지 않는다** — 실행되는
    명령은 어디까지나 `kind`/`target`/`args` 세 개뿐이다.
    """
    if is_running(kind, target, path):
        raise JobError(f"'{target}' {kind} 가 이미 실행 중이다")

    target_dir = log_dir or LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = target_dir / f"{kind}-{target}-{stamp}.log"
    log_file = log_path.open("wb")

    cmd = _command(kind, target, args)
    proc_env = {**os.environ, **env} if env else None
    proc = subprocess.Popen(
        cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=Path.cwd(), env=proc_env
    )

    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (kind, target, args, note, status, started_at, log_path, started_by) "
            "VALUES (?, ?, ?, ?, 'running', ?, ?, ?)",
            (kind, target, json.dumps(args), note, now(), str(log_path), started_by),
        )
        job_id = cur.lastrowid

    with _lock:
        _running[job_id] = (proc, log_file)

    return get(job_id, path)  # type: ignore[return-value]


def get(job_id: int, path: Path | None = None) -> Job | None:
    _sync_running(path)
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def recent(
    *,
    kind: str | None = None,
    target: str | None = None,
    limit: int = 20,
    path: Path | None = None,
) -> list[Job]:
    _sync_running(path)
    sql = "SELECT * FROM jobs"
    where, values = [], []
    if kind is not None:
        where.append("kind = ?")
        values.append(kind)
    if target is not None:
        where.append("target = ?")
        values.append(target)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    values.append(limit)
    with connect(path) as conn:
        rows = conn.execute(sql, tuple(values)).fetchall()
    return [_row_to_job(r) for r in rows]


def reap_orphans(path: Path | None = None) -> int:
    """기동 시 한 번 부른다. 이 프로세스가 모르는 `running` 행은 전부 고아다.

    새로 뜬 프로세스의 `_running` 은 항상 비어 있으므로, 이 시점에 `running` 인
    행은 예외 없이 이전 프로세스 생애에서 남은 것이다.
    """
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'failed', finished_at = ? WHERE status = 'running'",
            (now(),),
        )
        return cur.rowcount
