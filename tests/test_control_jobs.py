"""운영자 화면의 수집·분석 실행 — 첫 백그라운드 작업 (P-003 §4).

**로직을 이중화하지 않는다** 원칙에 따라 이 모듈은 CLI 를 subprocess 로 감싸기만
한다. 그래서 여기서 보는 것은 그 감싸기 자체다 — 상태가 running→done/failed 로
바뀌는지, 같은 대상은 겹쳐 돌지 못하는지, 재시작 뒤 고아가 정리되는지.

실제 `votelink.cli` 를 부르면 느리고 결정적이지 않으므로 `jobs._command` 를
monkeypatch 해 매우 짧은 파이썬 프로세스로 대체한다 — DB 에 기록되는 kind/target/
args 는 실제 호출과 무관하게 그대로 검증할 수 있다.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from votelink import control
from votelink.control import jobs


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "control.db"
    control.init(path)
    monkeypatch.setattr(jobs, "LOG_DIR", tmp_path / "job-logs")
    return path


@pytest.fixture(autouse=True)
def _isolated_running_registry():
    """`jobs._running` 은 모듈 전역이고 db 경로를 모른다 — 실제로는 control.db 가
    하나뿐이라 문제가 안 되지만, 테스트마다 다른 tmp db 를 쓰므로 앞 테스트가 남긴
    항목이 뒤 테스트의 db 에 잘못 반영되지 않도록 매 테스트 전후로 비운다."""
    jobs._running.clear()
    yield
    for proc, log_file in jobs._running.values():
        proc.kill()
        proc.wait()
        log_file.close()
    jobs._running.clear()


@pytest.fixture(autouse=True)
def _fast_commands(monkeypatch):
    """실제 CLI 대신 즉시 끝나는 파이썬 한 줄로 대체한다."""

    def fake_command(kind, target, args):
        if "--slow" in args:
            return [sys.executable, "-c", "import time; time.sleep(5)"]
        exit_code = "1" if "--fail" in args else "0"
        return [sys.executable, "-c", f"import sys; sys.exit({exit_code})"]

    monkeypatch.setattr(jobs, "_command", fake_command)


def _wait_until_finished(job_id, path, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get(job_id, path)
        if job.status != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"작업 {job_id} 이 시간 안에 끝나지 않았다")


def test_a_job_starts_running_and_records_its_args(db):
    job = jobs.start("collect", "naver_news", ["--all-districts"], 1, path=db)
    assert job.status == "running"
    assert job.args == ["--all-districts"]
    assert job.target == "naver_news"
    assert job.started_by == 1


def test_a_successful_job_becomes_done(db):
    job = jobs.start("collect", "naver_news", [], 1, path=db)
    finished = _wait_until_finished(job.id, db)
    assert finished.status == "done"
    assert finished.exit_code == 0
    assert finished.finished_at is not None


def test_a_failing_job_becomes_failed(db):
    job = jobs.start("collect", "naver_news", ["--fail"], 1, path=db)
    finished = _wait_until_finished(job.id, db)
    assert finished.status == "failed"
    assert finished.exit_code == 1


def test_the_same_target_cannot_run_twice_at_once(db):
    jobs.start("collect", "naver_news", ["--all-districts"], 1, path=db)
    with pytest.raises(jobs.JobError, match="이미 실행 중"):
        jobs.start("collect", "naver_news", ["--district", "seoul_songpa_gap"], 1, path=db)


def test_a_different_target_can_run_concurrently(db):
    jobs.start("collect", "naver_news", ["--all-districts"], 1, path=db)
    other = jobs.start("collect", "mois_population", ["--all-districts"], 1, path=db)
    assert other.status == "running"


def test_finishing_frees_the_target_for_a_new_run(db):
    job = jobs.start("collect", "naver_news", [], 1, path=db)
    _wait_until_finished(job.id, db)
    again = jobs.start("collect", "naver_news", [], 1, path=db)
    assert again.status == "running"


def test_recent_lists_jobs_by_target(db):
    jobs.start("collect", "naver_news", [], 1, path=db)
    jobs.start("collect", "mois_population", [], 1, path=db)
    only_news = jobs.recent(kind="collect", target="naver_news", path=db)
    assert [j.target for j in only_news] == ["naver_news"]


def test_note_is_stored_but_does_not_affect_the_command(db, monkeypatch):
    """`note` 는 화면 표시용일 뿐이다 — 실제 실행되는 명령과는 무관하다."""
    seen_args = []
    monkeypatch.setattr(
        jobs,
        "_command",
        lambda kind, target, args: (seen_args.append(args), [sys.executable, "-c", "pass"])[1],
    )
    job = jobs.start(
        "collect", "naver_news", ["--district", "seoul_songpa_gap"], 1, path=db, note="후보만"
    )
    assert job.note == "후보만"
    assert seen_args == [["--district", "seoul_songpa_gap"]]


def test_env_is_merged_over_the_parent_environment(db, monkeypatch):
    """`.env` 시크릿은 그대로 상속되고, 준 값만 얹힌다."""
    captured = {}
    real_popen = subprocess.Popen

    def spy_popen(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy_popen)
    monkeypatch.setenv("NAVER_CLIENT_ID", "parent-value")

    jobs.start(
        "collect",
        "naver_news",
        [],
        1,
        path=db,
        env={"NAVER_NEWS_QUERY_SCOPE": "candidates"},
    )

    assert captured["env"]["NAVER_CLIENT_ID"] == "parent-value"
    assert captured["env"]["NAVER_NEWS_QUERY_SCOPE"] == "candidates"


def test_reap_orphans_fails_stale_running_rows(db):
    """새 프로세스는 이전 생애의 running 행을 모른다 — 전부 고아로 정리한다."""
    job = jobs.start("collect", "naver_news", ["--slow"], 1, path=db)
    # 이 프로세스가 방금 시작한 작업이라 아직 running 이 정상이다.
    assert jobs.get(job.id, db).status == "running"

    # "재시작"을 흉내낸다: 메모리 핸들을 지워서 이 프로세스가 더 이상 그 작업을 모르게 한다.
    proc, log_file = jobs._running.pop(job.id)

    try:
        reaped = jobs.reap_orphans(db)
        assert reaped == 1
        assert jobs.get(job.id, db).status == "failed"
    finally:
        proc.kill()
        proc.wait()
        log_file.close()
