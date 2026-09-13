"""parse()는 순수 함수이므로 네트워크 없이 fixture로 검증한다.

fixture 가 없으면 skip 된다. 합성 데이터로 대신하지 않는다 —
skip 은 "이 수집기는 아직 미검증"이라는 정직한 신호다 (docs/20-collector-spec.md §7).
"""

import json
from pathlib import Path

import pytest

from votelink.collect import RawBatch, Rejected
from votelink.contract.models import Record

from .. import collector as collector_mod
from ..collector import CONFIDENCE_PERSON, Collector

FIXTURE = Path(__file__).parent / "fixtures" / "sample_raw.json"
PERSON_ONLY_FIXTURE = Path(__file__).parent / "fixtures" / "sample_raw_person_only.json"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason=(
        "실제 응답 fixture 가 없다. NAVER_CLIENT_ID/SECRET 발급 후 "
        "`uv run votelink collect naver_news --capture-fixture` 로 받아라"
    ),
)


@pytest.fixture(autouse=True)
def _no_live_roster_or_party_lookups(monkeypatch):
    """실제 `data/camps/`·`data/shared/reference/news_parties.yaml` 을 건드리지 않는다.

    이 파일의 회귀 테스트는 로스터·정당 목록이 비어 있는 상태를 기준으로 한다 —
    실제 데이터가 나중에 바뀌어도 이 테스트들의 결과가 흔들리면 안 된다. 로스터가
    실제로 반영되는 시나리오는 아래 person-only 테스트가 monkeypatch 로 따로 본다.
    """
    monkeypatch.setattr(collector_mod, "person_terms_for_district", lambda *a, **k: [])
    monkeypatch.setattr(collector_mod, "party_queries_for_geo", lambda *a, **k: [])


def _batch() -> RawBatch:
    return RawBatch(collector_id=Collector.id, body=json.loads(FIXTURE.read_text(encoding="utf-8")))


def _person_only_batch() -> RawBatch:
    body = json.loads(PERSON_ONLY_FIXTURE.read_text(encoding="utf-8"))
    return RawBatch(collector_id=Collector.id, body=body)


def test_parse_produces_valid_records():
    results = list(Collector().parse(_batch()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    records = [r for r in results if not isinstance(r, Rejected)]

    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    assert records, "fixture에서 레코드가 하나도 안 나왔다"
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.geo_code is not None, "geo_code는 null일 수 없다"
        assert r.observed_at <= r.ingested_at, "데이터 시점이 수집 시점보다 미래다"
        assert r.derived_from == [], "원천 수집기는 파생 레코드를 만들지 않는다"


def test_parse_is_deterministic():
    ids_a = [r.record_id for r in Collector().parse(_batch()) if not isinstance(r, Rejected)]
    ids_b = [r.record_id for r in Collector().parse(_batch()) if not isinstance(r, Rejected)]
    assert ids_a == ids_b, "같은 입력에 record_id가 달라지면 멱등성이 깨진다"


def test_never_stores_full_text():
    """api_tos 출처의 원문 전문 저장은 계약이 막지만, 수집기가 먼저 지켜야 한다."""
    for r in Collector().parse(_batch()):
        if not isinstance(r, Rejected):
            assert r.payload["full_text_stored"] is False
            assert len(r.payload["summary"]) <= 600


def test_geo_is_sigungu_not_emd():
    """기사를 행정동에 귀속시키지 않는다 — 그건 추정이고 L2 의 일이다."""
    for r in Collector().parse(_batch()):
        if not isinstance(r, Rejected):
            assert r.geo_level == "sigungu"
            assert r.payload["topics"] == [], "주제 분류는 L1 이 하지 않는다"


# --- 캠프 로스터 반영 (P-006) ------------------------------------------------------
#
# 지명 없이 후보 실명만 걸리는 기사는 기존 스코프 필터(_mentions_region)라면 폐기됐다.
# person_terms 도 범위 판정 근거로 인정하는 _in_scope 확장이 없으면 이 기능 전체가
# 무의미하므로, 그 확장이 실제로 동작하는지를 이 테스트가 본다.


def test_person_only_article_is_not_discarded(monkeypatch):
    monkeypatch.setattr(collector_mod, "person_terms_for_district", lambda *a, **k: ["김철수"])

    results = list(Collector().parse(_person_only_batch()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    records = [r for r in results if not isinstance(r, Rejected)]

    assert not rejected, "지명이 없어도 후보명이 걸리면 필터로 버려지면 안 된다"
    assert len(records) == 1
    assert records[0].confidence == CONFIDENCE_PERSON
    assert records[0].payload["mentioned_persons"] == ["김철수"]
    assert records[0].payload["mentioned_places"] == []


def test_person_only_article_is_discarded_without_a_roster_match(monkeypatch):
    """후보명이 매칭 사전에 없으면 여전히 필터로 버려져야 한다(노이즈 방지)."""
    monkeypatch.setattr(collector_mod, "person_terms_for_district", lambda *a, **k: [])

    results = list(Collector().parse(_person_only_batch()))
    assert results == []
