"""`_queries()` — 지명·후보·정당 검색어 조합과 범위 좁히기 (P-006).

fetch() 는 네트워크가 필요하지만 `_queries()` 자체는 순수하다(로스터·정당 조회만
monkeypatch 하면 됨). `parse()` fixture 테스트(test_parse.py)와 별개로 여기서는
"어떤 검색어가 실제로 API 에 나가는가"만 본다.
"""

from __future__ import annotations

import pytest

from .. import collector as collector_mod
from ..collector import Collector


@pytest.fixture(autouse=True)
def _stub_lookups(monkeypatch):
    monkeypatch.setattr(
        collector_mod,
        "candidate_queries_for_district",
        lambda district_id: [{"id": "cand-aaaa", "q": "김철수 가당"}],
    )
    monkeypatch.setattr(
        collector_mod,
        "party_queries_for_geo",
        lambda geo_name: [
            {"id": "party-bbbb", "q": f"가당 {geo_name}"},
            {"id": "party-bbbb-alone", "q": "가당"},
        ],
    )


def test_default_scope_includes_geo_candidate_and_party_queries(monkeypatch):
    monkeypatch.delenv(collector_mod.ENV_QUERY_SCOPE, raising=False)
    ids = {q["id"] for q in Collector()._queries()}

    assert "songpa-gu" in ids, "손입력 지명 검색어는 그대로 남아야 한다"
    assert "cand-aaaa" in ids
    assert "party-bbbb" in ids and "party-bbbb-alone" in ids


def test_candidates_scope_skips_geo_and_party_queries(monkeypatch):
    monkeypatch.setenv(collector_mod.ENV_QUERY_SCOPE, collector_mod.SCOPE_CANDIDATES)
    queries = Collector()._queries()

    assert queries == [{"id": "cand-aaaa", "q": "김철수 가당"}]


def test_candidates_scope_with_no_camp_is_an_empty_list(monkeypatch):
    monkeypatch.setattr(collector_mod, "candidate_queries_for_district", lambda district_id: [])
    monkeypatch.setenv(collector_mod.ENV_QUERY_SCOPE, collector_mod.SCOPE_CANDIDATES)

    assert Collector()._queries() == []


def test_an_unknown_scope_value_falls_back_to_all(monkeypatch):
    """오타·미지정 값은 조용히 전체 범위로 돈다 — 검색어가 0개가 되어 아무것도
    안 받는 것보다 과다 수집이 안전한 실패 방향이다."""
    monkeypatch.setenv(collector_mod.ENV_QUERY_SCOPE, "오타")
    ids = {q["id"] for q in Collector()._queries()}
    assert "songpa-gu" in ids
