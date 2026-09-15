"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

캠프 로스터와 이슈 어휘집 둘 다 디스크를 읽는 참조 데이터라 실제 파일에
의존하면 그 파일이 바뀔 때마다 이 테스트의 손 검산이 깨진다 — `calc.
ISSUE_LEXICON_PATH`를 tmp_path의 시험용 어휘집으로, `camps_covering_district`
를 가짜 로스터로 몽키패치한다(candidate_mention_share의 테스트와 같은 방식).
"""

from datetime import datetime

import pytest
import yaml

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.camp.models import Candidate, Roster
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

from .. import analyzer as analyzer_module
from .. import calc
from ..analyzer import Analyzer

DISTRICT_ID = "seoul_songpa_gap"

META = AnalyzerMeta.model_validate(
    {
        "id": "issue_candidate_matrix",
        "name": "시험용",
        "inputs": ["news_article"],
        "outputs": ["issue_candidate_matrix"],
        "geo_level": "sigungu",
        "config": {
            "default_district": DISTRICT_ID,
            "common": {"window_weeks": 3},
            "districts": {DISTRICT_ID: {}},
        },
    }
)

OURS = Candidate(name="김철수", party="국민의힘", lineage="conservative")
OPPONENT = Candidate(name="이영희", party="더불어민주당", lineage="progressive")
ONE_ROSTER = [Roster(ours=OURS, opponents=[OPPONENT])]

DAY = datetime(2026, 8, 30, 9, 0, tzinfo=KST)


def _sigungu_code() -> str:
    return resolve_district(DISTRICT_ID).sigungu_codes[0]


def _article(n: int, title: str, persons: list[str]) -> Record:
    return Record(
        kind="news_article",
        collector_id="fake_naver_news",
        source_name="시험 출처",
        source_url=f"https://example.test/{n}",
        source_license="api_tos",
        observed_at=DAY,
        observed_precision="minute",
        geo_level="sigungu",
        geo_code=_sigungu_code(),
        geo_name="송파구",
        confidence=0.9,
        natural_key=f"https://example.test/{n}",
        payload={
            "title": title,
            "publisher": "시험일보",
            "published_at": DAY.isoformat(),
            "url": f"https://example.test/{n}",
            "summary": "요약.",
            "mentioned_persons": persons,
        },
    )


def make_inputs() -> list[Record]:
    return [
        _article(0, "재건축 이슈, 김철수 언급", ["김철수"]),
        _article(1, "재건축 이슈, 이영희도", ["이영희"]),
        _article(2, "재건축 관련, 김철수와 이영희 모두", ["김철수", "이영희"]),
        _article(3, "트램 개통, 김철수", ["김철수"]),
        _article(4, "재건축 뉴스, 후보 언급 없음", []),
        _article(5, "동네 부고 소식", ["김철수"]),  # 카테고리 매칭 자체가 없다
    ]


@pytest.fixture(autouse=True)
def test_lexicon(tmp_path, monkeypatch):
    path = tmp_path / "issue_lexicon.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": "test-1",
                "categories": [
                    {"key": "redevelopment", "label": "재건축", "keywords": ["재건축"]},
                    {"key": "transit", "label": "교통", "keywords": ["트램"]},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(calc, "ISSUE_LEXICON_PATH", path)


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
    for r in run():
        assert r.derived_from, "derived_from 이 비었다"
        assert len(set(r.derived_from)) == len(r.derived_from), "derived_from 에 중복이 있다"


def test_confidence_is_not_certain():
    for r in run():
        assert r.confidence < 1.0


def test_observed_at_points_at_the_input_not_the_run():
    inputs = make_inputs()
    latest_input = max(r.observed_at for r in inputs)
    for r in run():
        assert r.observed_at <= latest_input


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    ids_a = [r.record_id for r in run()]
    ids_b = [r.record_id for r in run()]
    assert ids_a == ids_b


def test_empty_input_is_an_error():
    with pytest.raises(AnalyzeError):
        list(Analyzer(meta=META).compute([]))


def test_no_covering_camp_is_an_error():
    original = analyzer_module.camps_covering_district
    analyzer_module.camps_covering_district = lambda district_id, **kw: []
    try:
        with pytest.raises(AnalyzeError):
            list(Analyzer(meta=META).compute(make_inputs()))
    finally:
        analyzer_module.camps_covering_district = original


def test_no_qualifying_categories_is_rejected():
    """이슈와 후보가 동시에 안 걸리면 격리(현실적으로는 격리율 100%라 전체
    실패다) — 조용히 빈 매트릭스를 내지 않는다."""
    articles = [_article(0, "동네 부고 소식", ["김철수"])]  # 카테고리 매칭 없음
    original = analyzer_module.camps_covering_district
    analyzer_module.camps_covering_district = lambda district_id, **kw: ONE_ROSTER
    try:
        results = list(Analyzer(meta=META).compute(articles))
    finally:
        analyzer_module.camps_covering_district = original
    assert len(results) == 1
    assert isinstance(results[0], Rejected)


# --- 변별력 ---------------------------------------------------------------------


def test_output_discriminates_between_categories_and_candidates():
    """모든 셀이 같은 값이면 그 지표는 아무것도 말하지 않는다 (docs/30-analysis-spec.md §9)."""
    payload = run()[0].payload
    article_counts = {c["category"]: c["article_count"] for c in payload["categories"]}
    assert len(set(article_counts.values())) > 1, f"모든 카테고리가 같은 값이다: {article_counts}"


# --- 계산 정확성 (손으로 검산 가능한 축소판) --------------------------------------


def test_matrix_matches_hand_calculation():
    payload = run()[0].payload
    by_cat = {c["category"]: c for c in payload["categories"]}

    assert list(by_cat) == ["redevelopment", "transit"]  # article_count 내림차순

    redevelopment = by_cat["redevelopment"]
    assert redevelopment["article_count"] == 4  # 기사 0,1,2,4 (부고는 매칭 자체가 없다)
    hits = {h["name"]: h for h in redevelopment["candidates"]}
    assert hits["김철수"]["count"] == 2  # 기사 0, 2
    assert hits["이영희"]["count"] == 2  # 기사 1, 2
    assert hits["김철수"]["share_of_category"] == 50.0
    assert hits["김철수"]["is_ours"] is True
    assert hits["이영희"]["is_ours"] is False

    transit = by_cat["transit"]
    assert transit["article_count"] == 1  # 기사 3
    assert transit["candidates"][0]["name"] == "김철수"
    assert transit["candidates"][0]["count"] == 1
    assert transit["candidates"][0]["share_of_category"] == 100.0

    # 근거는 카테고리+후보가 동시에 걸린 기사만: 0,1,2,3 (부고 제외, 후보없는 재건축 제외)
    assert len(run()[0].derived_from) == 4
