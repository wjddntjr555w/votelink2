"""parse()는 순수 함수이므로 네트워크 없이 fixture로 검증한다.

fixture 는 실제 아카이브 응답의 **부분집합**이다 (합성이 아니다).
전국 격자에서 송파구·강남구 행만 남겼다 — 옆 구가 들어 있어야 시군구 필터가
실제로 검증된다. 레이아웃 두 계열을 각각 남겼다:

    sample_raw.json         제14대(1992) — 정당/후보 별도 행, 투표구 열 없음, '제N동' 표기
    sample_raw_modern.json  제21대(2025) — '정당\\n후보' 한 칸, 병합셀, 사전투표 노이즈 행
"""

import json
from pathlib import Path

import pytest

from votelink.collect import RawBatch, Rejected
from votelink.contract.models import Record

from ..collector import Collector

FIXTURES = Path(__file__).parent / "fixtures"
CASES = [
    ("sample_raw.json", "1992-12-18-presidential", 8),
    ("sample_raw_modern.json", "2025-06-03-presidential", 5),
]

pytestmark = pytest.mark.skipif(
    not (FIXTURES / "sample_raw.json").exists(),
    reason="fixture 가 없다. `uv run votelink collect nec_archive --capture-fixture` 로 받아라",
)


def _parse(filename: str):
    body = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))["body"]
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
        assert r.geo_code is not None, "geo_code는 null일 수 없다"
        assert r.observed_at <= r.ingested_at, "데이터 시점이 수집 시점보다 미래다"
        assert r.derived_from == [], "원천 수집기는 파생 레코드를 만들지 않는다"
        assert r.payload["election_id"] == election_id
        assert len(r.payload["results"]) == n_candidates


@pytest.mark.parametrize("filename,_eid,_n", CASES)
def test_parse_is_deterministic(filename, _eid, _n):
    a = [r.record_id for r in _parse(filename)[0]]
    b = [r.record_id for r in _parse(filename)[0]]
    assert a == b, "같은 입력에 record_id가 달라지면 멱등성이 깨진다"


@pytest.mark.parametrize("filename,_eid,_n", CASES)
def test_neighbouring_sigungu_is_filtered_not_quarantined(filename, _eid, _n):
    """fixture 에는 강남구가 들어 있다. 격리 0이어야 한다 — 대상이 아닐 뿐 오류가 아니다."""
    records, rejected = _parse(filename)
    assert not rejected
    assert {r.geo_name for r in records} == {
        "풍납1동",
        "풍납2동",
        "방이1동",
        "방이2동",
        "오륜동",
        "송파1동",
        "송파2동",
        "잠실4동",
        "잠실6동",
    }


@pytest.mark.parametrize("filename,_eid,_n", CASES)
def test_emd_level_only(filename, _eid, _n):
    """투표구 행이 섞이면 득표가 두 배가 된다. 동 단위만 받는다."""
    records, _ = _parse(filename)
    assert all(r.payload["precinct"] is None for r in records)
    assert all(r.geo_level == "emd" for r in records)
    assert len({r.geo_code for r in records}) == 9, "같은 동이 두 번 들어왔다"


def test_old_and_new_layouts_agree_on_geo_codes():
    """33년 차이가 나는 두 파일이 같은 geo_code 집합을 내야 한다.

    '제N동' 정규화가 깨지면 여기서 드러난다. 시계열 분석이 성립하는 전제다.
    """
    old = {r.geo_code for r in _parse("sample_raw.json")[0]}
    new = {r.geo_code for r in _parse("sample_raw_modern.json")[0]}
    assert old == new
