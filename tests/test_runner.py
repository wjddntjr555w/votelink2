"""수집 실행기 — 부분 실패를 조용히 넘기지 않는다 (docs/20-collector-spec.md §6)."""

from tests.conftest import FakeCollector
from votelink.collect import runner, storage


def items(good: int, bad: int = 0):
    return [{"n": i} for i in range(good)] + ["깨진 항목"] * bad


def test_happy_path_writes_records(space):
    report = runner.run(FakeCollector(items(5)), space=space)
    assert not report.failed
    assert (report.accepted, report.rejected, report.written) == (5, 0, 5)
    assert len(storage.existing_record_ids("fake_collector", space)) == 5


def test_one_bad_item_does_not_kill_the_batch(space):
    """100건 중 3건이 깨졌을 때 나머지 97건이 사라지면 안 된다."""
    report = runner.run(FakeCollector(items(39, bad=1)), space=space)
    assert (report.accepted, report.rejected) == (39, 1)
    assert not report.failed
    assert report.written == 39


def test_reject_rate_over_threshold_blocks_valid_records(space):
    """격리율이 임계를 넘으면 유효분도 커밋하지 않는다."""
    report = runner.run(FakeCollector(items(8, bad=2)), space=space)
    assert report.failed
    assert "격리율" in report.failure_reason
    assert report.written == 0
    assert storage.existing_record_ids("fake_collector", space) == set()


def test_rejected_items_are_quarantined_with_reason(space):
    runner.run(FakeCollector(items(8, bad=2)), space=space)
    path = space.rejected / "fake_collector"
    body = "\n".join(p.read_text(encoding="utf-8") for p in path.glob("*.jsonl"))
    assert "dict 가 아니다" in body


def test_reject_reasons_are_grouped(space):
    report = runner.run(FakeCollector(items(8, bad=2)), space=space)
    assert sum(report.reject_reasons.values()) == 2
    assert "격리 사유" in report.summary()


def test_raw_is_saved_even_when_every_record_fails(space):
    """파서가 전부 틀려도 원본은 남아야 --reparse 로 복구된다."""
    runner.run(FakeCollector(items(0, bad=3)), space=space)
    assert list(storage.iter_raw("fake_collector", space))


def test_dry_run_writes_nothing(space):
    report = runner.run(FakeCollector(items(5)), dry_run=True, space=space)
    assert report.accepted == 5
    assert report.written == 0
    assert not (space.raw).exists()
    assert not (space.records).exists()


def test_reparse_does_not_touch_the_network(space):
    runner.run(FakeCollector(items(5)), space=space)

    again = FakeCollector(items(5))
    report = runner.run(again, reparse=True, space=space)
    assert again.fetch_calls == 0
    assert report.parsed == 5


def test_reparse_after_fixing_parser_recovers_records(space):
    """수집 때는 전부 격리됐지만, 파서를 고친 뒤 재파싱하면 살아난다."""
    broken = runner.run(FakeCollector(items(0, bad=4)), space=space)
    assert broken.written == 0

    fixed = FakeCollector(items(4))
    fixed.parse = lambda raw: fixed.map_items(  # 고쳐진 파서를 흉내낸다
        [{"n": i} for i in range(4)], FakeCollector._to_record
    )
    report = runner.run(fixed, reparse=True, space=space)
    assert report.accepted == 4


def test_second_run_skips_already_stored_records(space):
    runner.run(FakeCollector(items(5)), space=space)
    report = runner.run(FakeCollector(items(5)), space=space)
    assert report.duplicates == 5
    assert report.written == 0
    assert len(storage.existing_record_ids("fake_collector", space)) == 5


def test_duplicates_within_one_run_are_collapsed(space):
    report = runner.run(FakeCollector([{"n": 1}, {"n": 1}, {"n": 2}]), space=space)
    assert (report.accepted, report.duplicates) == (2, 1)


def test_reparse_does_not_duplicate_records_on_disk(space):
    """--reparse 를 반복 실행해도 같은 record_id 가 두 줄로 쌓이면 안 된다 (D-007)."""
    runner.run(FakeCollector(items(5)), space=space)
    runner.run(FakeCollector(items(5)), reparse=True, space=space)
    runner.run(FakeCollector(items(5)), reparse=True, space=space)

    lines = space.record_file("fake_collector").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert len(storage.existing_record_ids("fake_collector", space)) == 5


def test_reparse_replaces_changed_payload_without_duplicating(space):
    """파싱 로직이 바뀌어도 같은 record_id 는 한 줄로 남고 새 값으로 교체된다 (D-007)."""
    from tests.conftest import make_record

    runner.run(FakeCollector(items(3)), space=space)

    changed = FakeCollector(items(3))
    changed.parse = lambda raw: changed.map_items(
        raw.body["items"],
        lambda item: make_record(
            item["n"],
            payload={
                "title": f"수정된 기사 {item['n']}",
                "publisher": "가상일보",
                "published_at": "2026-08-30T14:20:00+09:00",
                "url": f"https://example.test/{item['n']}",
                "summary": "요약.",
            },
        ),
    )
    runner.run(changed, reparse=True, space=space)

    lines = space.record_file("fake_collector").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all("수정된 기사" in line for line in lines)


def test_reparse_preserves_records_this_runs_raw_does_not_cover(space):
    """다른 실행(예: 다른 선거구)이 채운 record_id 는 이번 reparse 로 지워지면 안 된다.

    한 owner_id 파일을 여러 선거구가 공유하는 수집기(naver_news 등, `docs/11-storage.md
    §2`)에서, --district 없이 reparse 하면 이 실행의 raw 만 다시 읽는다. 파일 전체를
    이 실행 결과로 덮어쓰면 raw 에 없는 다른 선거구 기여분이 사라진다 (D-007 실사고).
    """
    from tests.conftest import make_record
    from votelink.store import append_records

    runner.run(FakeCollector(items(2)), space=space)

    foreign = make_record(99, natural_key="https://example.test/foreign")
    append_records("fake_collector", [foreign], space)

    runner.run(FakeCollector(items(2)), reparse=True, space=space)

    ids = storage.existing_record_ids("fake_collector", space)
    assert foreign.record_id in ids
    assert len(ids) == 3
