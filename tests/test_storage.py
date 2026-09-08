"""저장 레이아웃 — raw 는 불변이다."""

from datetime import timedelta

from tests.conftest import NOW, make_record
from votelink.collect import storage
from votelink.collect.base import RawBatch, Rejected


def batch(**over):
    base = dict(collector_id="fake_collector", body={"a": 1}, batch_key="b1", fetched_at=NOW)
    base.update(over)
    return RawBatch(**base)


def test_raw_round_trips(space):
    storage.write_raw(batch(), space)
    got = list(storage.iter_raw("fake_collector", space))
    assert len(got) == 1
    assert got[0].body == {"a": 1}


def test_raw_is_never_overwritten(space):
    """같은 배치를 두 번 저장해도 앞의 원본이 사라지지 않는다."""
    first = storage.write_raw(batch(), space)
    second = storage.write_raw(batch(fetched_at=NOW + timedelta(seconds=5)), space)
    assert first != second
    assert first.exists() and second.exists()
    assert len(list(storage.iter_raw("fake_collector", space))) == 2


def test_iter_raw_filters_by_since(space):
    storage.write_raw(batch(fetched_at=NOW - timedelta(days=2)), space)
    storage.write_raw(batch(fetched_at=NOW), space)
    got = list(storage.iter_raw("fake_collector", space, since=NOW - timedelta(hours=1)))
    assert len(got) == 1


def test_iter_raw_on_missing_collector_is_empty(space):
    assert list(storage.iter_raw("nope", space)) == []


def test_records_append_and_ids(space):
    storage.append_records("fake_collector", [make_record(1), make_record(2)], space)
    storage.append_records("fake_collector", [make_record(3)], space)
    ids = storage.existing_record_ids("fake_collector", space)
    assert len(ids) == 3
    assert make_record(1).record_id in ids


def test_rejected_keeps_reason(space):
    path = storage.append_rejected(
        "fake_collector", [Rejected(reason="ValueError: 깨짐", raw_item={"x": 1})], NOW, space
    )
    assert "깨짐" in path.read_text(encoding="utf-8")
