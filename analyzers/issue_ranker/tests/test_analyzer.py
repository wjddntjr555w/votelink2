"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

축소판: 6주 × 2~3 카테고리 키워드 기사 + 키워드 없는 기사(unclassified) + 다른
시군구 1건 + confidence 미달 1건. 어휘집은 임시 파일로 갈아끼운다 — 저장소 어휘집을
고쳐도 이 테스트는 흔들리지 않아야 한다. 선거구는 실제 seoul_songpa_gap 을 쓴다
(resolve_district 가 기본 경로를 읽으므로).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.models import KST, Record
from votelink.reference import issue_lexicon as lex

from ..analyzer import Analyzer

META = AnalyzerMeta.model_validate(
    {
        "id": "issue_ranker",
        "name": "시험용",
        "inputs": ["news_article"],
        "outputs": ["local_issue"],
        "geo_level": "sigungu",
        "config": {
            "default_district": "seoul_songpa_gap",
            "districts": {"seoul_songpa_gap": {}},
            "common": {
                "min_confidence": 0.7,
                "window_weeks": 12,
                "half_life_weeks": 2,
                "trend_rising_ratio": 1.3,
                "trend_falling_ratio": 0.77,
                "backfill_distortion_ratio": 3.0,
                "top_places_n": 5,
                "sample_headlines_limit": 3,
            },
        },
    }
)

SIGUNGU = "1171000000"  # seoul_songpa_gap 의 시군구 코드

TEST_LEXICON = (
    'version: "test-1"\n'
    "categories:\n"
    "  - { key: transit, label: 교통, keywords: [트램, 9호선] }\n"
    "  - { key: redevelopment, label: 재건축, keywords: [재건축] }\n"
    "  - { key: safety, label: 안전, keywords: [싱크홀] }\n"
)


@pytest.fixture(autouse=True)
def _test_lexicon(tmp_path, monkeypatch):
    path = tmp_path / "issue_lexicon.yaml"
    path.write_text(TEST_LEXICON, encoding="utf-8")
    monkeypatch.setattr(lex, "LEXICON_PATH", path)
    lex.reset_cache()
    yield
    lex.reset_cache()


def article(
    day: str, *, title: str, ident: str, conf: float = 0.7, geo: str = SIGUNGU, places=("송파구",)
) -> Record:
    dt = datetime.fromisoformat(day).replace(tzinfo=KST)
    url = f"https://news.test/{ident}"
    return Record(
        kind="news_article",
        collector_id="naver_news",
        source_name="네이버",
        source_url=url,
        source_license="api_tos",
        observed_at=dt,
        observed_precision="minute",
        ingested_at=datetime(2026, 9, 1, tzinfo=KST),
        geo_level="sigungu",
        geo_code=geo,
        geo_name="서울 송파구",
        confidence=conf,
        natural_key=url,
        payload={
            "title": title,
            "publisher": "news.test",
            "published_at": dt.isoformat(),
            "url": url,
            "summary": "요약.",
            "mentioned_places": list(places),
            "mentioned_persons": [],
        },
    )


def make_inputs() -> list[Record]:
    recs: list[Record] = []
    # transit: 최근으로 갈수록 늘어난다 (rising). 6주.
    recs += [article("2026-07-06", title="위례선 트램 논의", ident="t1")]
    recs += [article("2026-07-27", title="트램 노선 확정", ident="t2")]
    recs += [
        article("2026-08-10", title="9호선 연장 착공", ident="t3"),
        article("2026-08-10", title="트램 예산 편성", ident="t4"),
    ]
    recs += [
        article("2026-08-17", title="트램 개통 목표", ident="t5", places=("잠실", "송파구")),
        article("2026-08-17", title="9호선 혼잡 대책", ident="t6"),
        article("2026-08-17", title="트램 정거장 위치", ident="t7"),
    ]
    # redevelopment: 초반에 몰려 있다 (falling).
    recs += [
        article("2026-07-06", title="가락시영 재건축 총회", ident="r1"),
        article("2026-07-06", title="잠실 재건축 속도", ident="r2"),
        article("2026-07-13", title="재건축 안전진단 통과", ident="r3"),
    ]
    recs += [article("2026-08-17", title="재건축 분담금 갈등", ident="r4")]
    # safety: 한 주만. + 멀티 카테고리(트램+싱크홀).
    recs += [article("2026-08-10", title="공사장 싱크홀 발생", ident="s1")]
    recs += [article("2026-08-17", title="트램 공사 중 싱크홀 우려", ident="s2")]
    # unclassified: 스포츠·연예. 키워드 없음.
    recs += [
        article("2026-08-17", title="잠실야구장 삼성 라이온즈 경기", ident="u1"),
        article("2026-08-17", title="롯데월드타워 콘서트 성황", ident="u2"),
        article("2026-08-10", title="서울패션위크 개막", ident="u3"),
    ]
    # 잡음: 다른 시군구 + confidence 미달
    recs += [article("2026-08-17", title="강남 트램 재건축", ident="x1", geo="1168000000")]
    recs += [article("2026-08-17", title="송파 트램 재건축 루머", ident="x2", conf=0.5)]
    return recs


def run() -> list[Record]:
    results = list(Analyzer(meta=META).compute(make_inputs()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    return results


# --- 계약 -----------------------------------------------------------------------


def test_output_records_are_valid():
    records = run()
    assert len(records) == 1, "선거구당 local_issue 는 1건이다"
    r = records[0]
    Record.model_validate(r.model_dump())
    assert r.collector_id == "issue_ranker"
    assert r.kind.value == "local_issue"
    assert r.geo_code == SIGUNGU
    assert r.geo_level.value == "sigungu"


def test_confidence_is_fixed_half():
    assert run()[0].confidence == 0.5


def test_observed_at_points_at_input_not_run():
    latest = max(
        x.observed_at for x in make_inputs() if x.geo_code == SIGUNGU and x.confidence >= 0.7
    )
    assert run()[0].observed_at == latest


def test_low_confidence_and_other_sigungu_excluded():
    r = run()[0]
    inputs = {x.record_id: x for x in make_inputs()}
    for rid in r.derived_from:
        assert inputs[rid].geo_code == SIGUNGU
        assert inputs[rid].confidence >= 0.7
    # x1(강남), x2(conf 0.5) 는 빠졌다 → 분류됐다면 transit/redevelopment 수가 부풀었을 것
    assert r.payload["total_articles"] == len(r.derived_from)


def test_evidence_includes_unclassified():
    """분류 실패도 '이 표본을 봤다'는 근거다 — derived_from 에 들어간다."""
    r = run()[0]
    assert r.payload["unclassified_count"] == 3  # u1, u2, u3
    # total = 분류 + 미분류. derived_from 은 그 전부.
    classified_ids = len(r.derived_from) - r.payload["unclassified_count"]
    assert classified_ids > 0


# --- 불변식 -------------------------------------------------------------------


def test_invariant_holds():
    p = run()[0].payload
    summed = sum(i["article_count"] for i in p["issues"])
    assert summed + p["unclassified_count"] >= p["total_articles"]


def test_window_truncated_to_config():
    p = run()[0].payload
    assert p["window_weeks"] == 12
    assert p["total_articles"] == len(run()[0].derived_from)


# --- 분류 -------------------------------------------------------------------


def test_multi_category_article_counted_in_all():
    """s2('트램 공사 중 싱크홀') 는 transit 과 safety 양쪽에 센다 — share 합 > 100 가능."""
    p = run()[0].payload
    by_cat = {i["category"]: i for i in p["issues"]}
    assert "transit" in by_cat and "safety" in by_cat
    # s2 가 양쪽에 잡혔으므로 카테고리 기사 수 합 > 분류된 고유 기사 수
    classified_unique = p["total_articles"] - p["unclassified_count"]
    assert sum(i["article_count"] for i in p["issues"]) > classified_unique
    assert sum(i["share"] for i in p["issues"]) > 100.0


def test_issues_sorted_by_recency_then_category():
    issues = run()[0].payload["issues"]
    keys = [(-i["recency_score"], i["category"]) for i in issues]
    assert keys == sorted(keys)


def test_sample_headlines_are_original_titles_max_3():
    issues = run()[0].payload["issues"]
    for i in issues:
        assert len(i["sample_headlines"]) <= 3
    transit = next(i for i in issues if i["category"] == "transit")
    # 원문 title 그대로. 가장 최근 주(2026-08-17)의 제목이 앞에 온다.
    assert (
        "트램 개통 목표" in transit["sample_headlines"]
        or "9호선 혼잡 대책" in transit["sample_headlines"]
    )


def test_top_places_are_counted():
    transit = next(i for i in run()[0].payload["issues"] if i["category"] == "transit")
    terms = {t["term"] for t in transit["top_places"]}
    assert "송파구" in terms


# --- 추세 (변별력, §9) ------------------------------------------------------


def test_issue_trends_discriminate():
    """transit 는 rising, redevelopment 는 falling — 전 카테고리가 같은 값이면 정보량 0."""
    by_cat = {i["category"]: i["trend"] for i in run()[0].payload["issues"]}
    assert by_cat["transit"] == "rising"
    assert by_cat["redevelopment"] == "falling"
    assert len(set(by_cat.values())) > 1


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    assert [r.record_id for r in run()] == [r.record_id for r in run()]
    # payload 도 동일해야 한다 (dict 순서 포함)
    import json

    a = json.dumps(run()[0].payload, ensure_ascii=False, sort_keys=False)
    b = json.dumps(run()[0].payload, ensure_ascii=False, sort_keys=False)
    assert a == b


# --- 실패 처리 ---------------------------------------------------------------


def test_empty_input_is_an_error():
    with pytest.raises(AnalyzeError):
        list(Analyzer(meta=META).compute([]))


def test_all_below_confidence_is_an_error():
    lows = [article("2026-08-17", title="트램", ident=f"l{i}", conf=0.5) for i in range(3)]
    with pytest.raises(AnalyzeError):
        list(Analyzer(meta=META).compute(lows))


def test_missing_lexicon_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(lex, "LEXICON_PATH", tmp_path / "does-not-exist.yaml")
    lex.reset_cache()
    with pytest.raises(AnalyzeError, match="어휘집"):
        list(Analyzer(meta=META).compute(make_inputs()))


def test_broken_article_isolated_under_5pct(monkeypatch):
    """분류 중 한 기사에서 예외가 나도 격리되고 나머지는 산출된다 (5% 미만)."""
    import analyzers.issue_ranker.analyzer as mod

    real = mod.classify

    def flaky(title, summary, cats):
        if title == "위례선 트램 논의":
            raise RuntimeError("boom")
        return real(title, summary, cats)

    monkeypatch.setattr(mod, "classify", flaky)
    # 표본을 늘려 1건 격리가 5% 미만이 되게 한다 (실제 입력은 8천 건이라 문제없다).
    pad = [article("2026-08-10", title=f"잠실야구장 경기 {i}", ident=f"pad{i}") for i in range(12)]
    results = list(Analyzer(meta=META).compute(make_inputs() + pad))
    issues = [r for r in results if isinstance(r, Record)]
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert len(issues) == 1
    assert len(rejected) == 1


def test_high_isolation_rate_fails_the_run(monkeypatch):
    """격리율이 5% 를 넘으면 유효분도 저장하지 않는다 — 자체 검사가 authoritative."""
    import analyzers.issue_ranker.analyzer as mod

    def always_break(*_a):
        raise RuntimeError("x")

    monkeypatch.setattr(mod, "classify", always_break)
    with pytest.raises(AnalyzeError, match="격리율"):
        list(Analyzer(meta=META).compute(make_inputs()))
