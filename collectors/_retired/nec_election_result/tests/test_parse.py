"""실제 CSV로 parse 를 검증한다.

fixture 가 없으면 이 수집기는 아직 미검증이다. 합성 데이터로 대신하지 않는다.

    uv run votelink collect nec_election_result --capture-fixture
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from collectors._retired.nec_election_result.collector import Collector
from votelink.collect import RawBatch, Rejected
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record

FIXTURE = Path(__file__).parent / "fixtures" / "sample_raw.json"
META_PATH = Path(__file__).resolve().parents[1] / "meta.yaml"

# fixture 는 fetch 가 내놓은 첫 배치 = 첫 선거(2024 총선)의 CSV 전문이다.
BATCH_KEY = "2024-04-10-national-assembly|sample.csv"


def _collector() -> Collector:
    return Collector(meta=CollectorMeta.load(META_PATH))


def _batch() -> RawBatch:
    return RawBatch(
        collector_id=Collector.id,
        body=json.loads(FIXTURE.read_text("utf-8")),
        batch_key=BATCH_KEY,
    )


needs_fixture = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="실제 CSV fixture 가 없다 — `--capture-fixture` 로 받아라 (docs/SETUP.md §4)",
)


# --- 실제 응답 검증 -----------------------------------------------------------


@pytest.fixture
def results():
    return list(_collector().parse(_batch()))


@needs_fixture
def test_no_items_are_rejected(results):
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목: {[r.short_reason for r in rejected][:5]}"


@needs_fixture
def test_one_record_per_target_dong(results):
    records = [r for r in results if isinstance(r, Record)]
    assert len(records) == 9, "송파갑 행정동 9개가 정확히 한 번씩 나와야 한다"
    codes = [r.geo_code for r in records]
    assert len(set(codes)) == 9, "같은 행정동이 두 번 나왔다 — 투표구 합산이 안 됐다"
    for code in codes:
        assert code and code.startswith("1171") and len(code) == 10


@needs_fixture
def test_records_satisfy_the_contract(results):
    """계약 모델이 득표합+무효==투표수 를 강제한다. 여기 통과 = 파싱이 맞다."""
    records = [r for r in results if isinstance(r, Record)]
    for r in records:
        Record.model_validate(r.model_dump())
        p = r.payload
        assert p["precinct"] is None
        assert p["election_type"] == "national_assembly"
        assert sum(c["votes"] for c in p["results"]) + p["invalid_votes"] == p["total_votes"]
        assert 0 < p["total_votes"] <= p["eligible_voters"]
        assert r.observed_at == datetime(2024, 4, 10, tzinfo=KST)
        assert r.observed_at <= r.ingested_at
        assert r.derived_from == []


@needs_fixture
def test_candidates_are_split_into_party_and_name(results):
    """'더불어민주당 조재희' 를 정당/후보로 가른다. 수집기는 해석하지 않고 원문을 보존한다."""
    records = [r for r in results if isinstance(r, Record)]
    parties = {c["party"] for r in records for c in r.payload["results"]}
    names = {c["candidate"] for r in records for c in r.payload["results"]}
    assert "더불어민주당" in parties and "국민의힘" in parties
    assert not any(" " in p for p in parties), f"정당명에 공백이 남았다: {parties}"
    assert all(names), "후보명이 비었다"


@needs_fixture
def test_out_of_district_rows_are_dropped_not_rejected(results):
    """관외사전투표·거소투표는 행정동이 아니다. 오류가 아니라 대상이 아닐 뿐이므로 버린다.

    격리로 처리하면 격리율이 임계(5%)를 넘어 수집 전체가 실패한다.
    """
    assert len(results) == 9, "대상 외 항목이 격리로 새어 나왔다"


@needs_fixture
def test_parse_is_deterministic():
    def ids():
        return [r.record_id for r in _collector().parse(_batch()) if isinstance(r, Record)]

    assert ids() == ids()
