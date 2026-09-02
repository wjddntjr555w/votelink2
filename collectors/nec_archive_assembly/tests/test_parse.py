"""parse()는 순수 함수이므로 네트워크 없이 fixture로 검증한다.

fixture 는 실제 아카이브 응답의 **부분집합**이다 (합성이 아니다).

    sample_raw.json         18대(2008) 서울.xls 의 '송파구갑' 시트 그대로 —
                             정당\\n후보 병합 없이 정당행+후보행이 분리된 정적 모드
    sample_raw_modern.json  22대(2024) 전국 파일에서 '강남구갑'+'송파구갑' 블록만
                             발췌 — 옆 지역구가 있어야 district_col 필터가
                             실제로 검증되고, block_start 모드(후보 이름이
                             지역구 블록 첫 행에만 있음)를 검증한다
"""

import json
from pathlib import Path

import pytest

from votelink.collect.base import RawBatch, Rejected
from votelink.contract.models import Record

from ..collector import Collector

FIXTURES = Path(__file__).parent / "fixtures"

CASES = [
    ("sample_raw.json", "2008-04-09-national_assembly", 3),
    ("sample_raw_modern.json", "2024-04-10-national_assembly", 3),
]

pytestmark = pytest.mark.skipif(
    not (FIXTURES / "sample_raw.json").exists(),
    reason="fixture 가 없다. `uv run votelink collect nec_archive_assembly --capture-fixture`",
)


def _parse(filename: str):
    body = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    results = list(Collector().parse(RawBatch(collector_id=Collector.id, body=body)))
    rejected = [r for r in results if isinstance(r, Rejected)]
    records = [r for r in results if not isinstance(r, Rejected)]
    return records, rejected


@pytest.mark.parametrize("filename,election_id,n_candidates", CASES)
def test_parse_produces_valid_records(filename, election_id, n_candidates):
    records, rejected = _parse(filename)

    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    assert len(records) == 9, "송파갑은 행정동 9개다"
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.geo_code is not None
        assert r.observed_at <= r.ingested_at
        assert r.derived_from == [], "원천 수집기는 파생 레코드를 만들지 않는다"
        assert r.payload["election_id"] == election_id
        assert r.payload["election_type"] == "national_assembly"
        assert r.payload["precinct"] is None
        assert len(r.payload["results"]) == n_candidates


@pytest.mark.parametrize("filename,_eid,_n", CASES)
def test_parse_is_deterministic(filename, _eid, _n):
    a = [r.record_id for r in _parse(filename)[0]]
    b = [r.record_id for r in _parse(filename)[0]]
    assert a == b


def test_modern_fixture_filters_out_the_neighbouring_district():
    """fixture 에는 강남구갑이 들어 있다. 격리 0이어야 한다 — 대상이 아닐 뿐 오류가 아니다."""
    records, rejected = _parse("sample_raw_modern.json")
    assert not rejected
    assert all(r.geo_name != "삼성동" for r in records)  # 강남구갑 동이 안 섞였다


def test_modern_fixture_uses_songpa_candidates_not_gangnams():
    """22대는 후보 이름이 지역구 블록 첫 행에만 있다 — 강남구갑 후보가 섞이면
    이 검증이 잡는다 (block_start 모드의 핵심 위험)."""
    records, _ = _parse("sample_raw_modern.json")
    candidates = {c["candidate"] for r in records for c in r.payload["results"]}
    assert candidates == {"조재희", "박정훈", "송재열"}


def test_two_eras_agree_on_geo_codes():
    """2008년과 2024년, 16년 차이가 나는 두 파일이 같은 geo_code 집합을 내야 한다."""
    old = {r.geo_code for r in _parse("sample_raw.json")[0]}
    new = {r.geo_code for r in _parse("sample_raw_modern.json")[0]}
    assert old == new
