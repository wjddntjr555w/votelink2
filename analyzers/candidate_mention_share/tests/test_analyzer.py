"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

캠프 로스터만 예외다 — `camps_covering_district`(디스크를 읽는다)를 모듈
심볼 자체를 몽키패치해 가짜 로스터로 바꾼다. 실제 candidates.yaml 구조와
같은 pydantic 모델(Roster/Candidate)을 그대로 쓰므로 계약은 실제와 같다.
"""

from datetime import datetime

import pytest

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.camp.models import Candidate, Roster
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

from .. import analyzer as analyzer_module
from ..analyzer import Analyzer

DISTRICT_ID = "seoul_songpa_gap"
"""실제 참조 데이터(districts.yaml)를 쓴다 — conftest 의 _no_real_data_dir 가
records/rejected 만 격리하고 reference/ 는 실제 파일을 그대로 쓴다."""

META = AnalyzerMeta.model_validate(
    {
        "id": "candidate_mention_share",
        "name": "시험용",
        "inputs": ["news_article"],
        "outputs": ["candidate_mention_share"],
        "geo_level": "sigungu",
        "config": {
            "default_district": DISTRICT_ID,
            "common": {"window_weeks": 3, "backfill_distortion_ratio": 3.0},
            "districts": {DISTRICT_ID: {}},
        },
    }
)

OURS = Candidate(name="김철수", party="국민의힘", lineage="conservative")
OPPONENT = Candidate(name="이영희", party="더불어민주당", lineage="progressive")
ONE_ROSTER = [Roster(ours=OURS, opponents=[OPPONENT])]

# 오래된 주부터: week0 1건(김철수만) · week1 4건(김철수2 · 이영희2) · week2 4건(김철수3 · 이영희1)
WEEK0 = datetime(2026, 6, 16, 9, 0, tzinfo=KST)
WEEK1 = datetime(2026, 6, 23, 9, 0, tzinfo=KST)
WEEK2 = datetime(2026, 6, 30, 9, 0, tzinfo=KST)


def _sigungu_code() -> str:
    return resolve_district(DISTRICT_ID).sigungu_codes[0]


def _article(n: int, when: datetime, persons: list[str]) -> Record:
    return Record(
        kind="news_article",
        collector_id="fake_naver_news",
        source_name="시험 출처",
        source_url=f"https://example.test/{n}",
        source_license="api_tos",
        observed_at=when,
        observed_precision="minute",
        geo_level="sigungu",
        geo_code=_sigungu_code(),
        geo_name="송파구",
        confidence=0.9,
        natural_key=f"https://example.test/{n}",
        payload={
            "title": f"기사 {n}",
            "publisher": "시험일보",
            "published_at": when.isoformat(),
            "url": f"https://example.test/{n}",
            "summary": "요약.",
            "mentioned_persons": persons,
        },
    )


def make_inputs() -> list[Record]:
    articles = [_article(0, WEEK0, ["김철수"])]
    articles += [_article(i, WEEK1, ["김철수"]) for i in (1, 2)]
    articles += [_article(i, WEEK1, ["이영희"]) for i in (3, 4)]
    articles += [_article(i, WEEK2, ["김철수"]) for i in (5, 6, 7)]
    articles += [_article(8, WEEK2, ["이영희"])]
    return articles


def run(rosters: list[Roster] = ONE_ROSTER) -> list[Record]:
    original = analyzer_module.camps_covering_district
    analyzer_module.camps_covering_district = lambda district_id, **kw: rosters
    try:
        results = list(Analyzer(meta=META).compute(make_inputs()))
    finally:
        analyzer_module.camps_covering_district = original
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    return results


# --- 계약 -----------------------------------------------------------------------


def test_output_records_are_valid():
    records = run()
    assert records, "입력이 있는데 산출이 하나도 없다"
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.collector_id == Analyzer.id, "파생 레코드의 collector_id 는 분석기 id 다"
        assert r.geo_code is not None, "geo_code 는 null 일 수 없다"


def test_evidence_is_recorded():
    """근거를 못 대는 결론은 실패로 간주한다."""
    for r in run():
        assert r.derived_from, "derived_from 이 비었다"
        assert len(set(r.derived_from)) == len(r.derived_from), "derived_from 에 중복이 있다"


def test_confidence_is_not_certain():
    """실측이 아니라 파생이다. 1.0 은 줄 수 없다."""
    for r in run():
        assert r.confidence < 1.0


def test_observed_at_points_at_the_input_not_the_run():
    """분석을 언제 돌렸는지가 아니라 데이터가 언제를 가리키는지를 담는다."""
    inputs = make_inputs()
    latest_input = max(r.observed_at for r in inputs)
    for r in run():
        assert r.observed_at <= latest_input


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    """같은 입력에 record_id 가 달라지면 멱등성이 깨진다 — upsert 가 교체 대신 누적한다."""
    ids_a = [r.record_id for r in run()]
    ids_b = [r.record_id for r in run()]
    assert ids_a == ids_b


def test_empty_input_is_an_error():
    """빈 산출물을 조용히 내지 않는다."""
    with pytest.raises(AnalyzeError):
        list(Analyzer(meta=META).compute([]))


def test_no_covering_camp_is_an_error():
    """로스터 없이는 후보를 특정할 수 없다 — 캠프 미등록 district 는 명시적으로 멈춘다."""
    original = analyzer_module.camps_covering_district
    analyzer_module.camps_covering_district = lambda district_id, **kw: []
    try:
        with pytest.raises(AnalyzeError):
            list(Analyzer(meta=META).compute(make_inputs()))
    finally:
        analyzer_module.camps_covering_district = original


# --- 변별력 ---------------------------------------------------------------------


def test_output_discriminates_between_candidates():
    """모든 후보가 같은 값이면 그 지표는 아무것도 말하지 않는다 (docs/30-analysis-spec.md §9).

    이 분석기는 선거구당 레코드 1건이라 "단위"는 동이 아니라 후보다 —
    candidates[].total_articles 가 후보마다 달라야 한다.
    """
    payload = run()[0].payload
    totals = {c["name"]: c["total_articles"] for c in payload["candidates"]}
    assert len(set(totals.values())) > 1, f"모든 후보가 같은 값이다: {totals}"


# --- 계산 정확성 (손으로 검산 가능한 축소판) --------------------------------------


def test_weekly_counts_and_share_match_hand_calculation():
    payload = run()[0].payload
    by_name = {c["name"]: c for c in payload["candidates"]}

    ours = by_name["김철수"]
    assert [w["article_count"] for w in ours["weekly"]] == [1, 2, 3]
    assert ours["total_articles"] == 6
    # week0: 1/1 · week1: 2/4 · week2: 3/4
    assert [w["share_pct"] for w in ours["weekly"]] == [100.0, 50.0, 75.0]
    # week0 은 첫 관측이라 전주 비교가 없다
    assert ours["weekly"][0]["wow_change_pct"] is None
    assert ours["weekly"][1]["wow_change_pct"] == 100.0  # (2-1)/1
    assert ours["weekly"][2]["wow_change_pct"] == 50.0  # (3-2)/2

    opp = by_name["이영희"]
    assert [w["article_count"] for w in opp["weekly"]] == [0, 2, 1]
    assert opp["total_articles"] == 3
    assert [w["share_pct"] for w in opp["weekly"]] == [0.0, 50.0, 25.0]
    assert opp["weekly"][0]["wow_change_pct"] is None
    # 전주(week0) 건수가 0이면 변화율은 정의되지 않는다(0에서 어디로 가도 무한대)
    assert opp["weekly"][1]["wow_change_pct"] is None
    assert opp["weekly"][2]["wow_change_pct"] == -50.0  # (1-2)/2

    assert payload["total_articles"] == 9  # 1 + 4 + 4


def test_ours_flag_is_preserved():
    payload = run()[0].payload
    by_name = {c["name"]: c["is_ours"] for c in payload["candidates"]}
    assert by_name == {"김철수": True, "이영희": False}
