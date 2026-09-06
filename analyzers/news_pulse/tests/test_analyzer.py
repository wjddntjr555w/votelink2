"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

축소판 입력: 6주 × 몇 개 언론사. 검증하려는 성질(주별 접기·창 자르기·급증 판정·
멱등)은 그대로 남는다. 선거구는 실제 참조 데이터의 seoul_songpa_gap 을 쓴다
(resolve_district 가 기본 경로를 읽으므로).
"""

from __future__ import annotations

from datetime import datetime

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.models import KST, Record

from ..analyzer import Analyzer

META = AnalyzerMeta.model_validate(
    {
        "id": "news_pulse",
        "name": "시험용",
        "inputs": ["news_article"],
        "outputs": ["news_pulse"],
        "geo_level": "sigungu",
        "config": {
            "default_district": "seoul_songpa_gap",
            "districts": {"seoul_songpa_gap": {}},
            "common": {
                "window_weeks": 4,
                "history_weeks": 2,
                "min_history_weeks": 2,
                "spike_z_threshold": 2.0,
                "backfill_distortion_ratio": 3.0,
            },
        },
    }
)

SIGUNGU = "1171000000"  # seoul_songpa_gap 의 시군구 코드


def article(day: str, publisher: str, *, n: int, conf: float = 0.7) -> list[Record]:
    """그 날짜에 같은 언론사 기사 n건."""
    dt = datetime.fromisoformat(day).replace(tzinfo=KST)
    out = []
    for i in range(n):
        url = f"https://{publisher}.test/{day}/{i}"
        out.append(
            Record(
                kind="news_article",
                collector_id="naver_news",
                source_name="네이버",
                source_url=url,
                source_license="api_tos",
                observed_at=dt,
                observed_precision="minute",
                ingested_at=datetime(2026, 9, 1, tzinfo=KST),
                geo_level="sigungu",
                geo_code=SIGUNGU,
                geo_name="서울 송파구",
                confidence=conf,
                natural_key=url,
                payload={
                    "title": f"{publisher} {day} {i}",
                    "publisher": publisher,
                    "published_at": dt.isoformat(),
                    "url": url,
                    "summary": "요약.",
                    "mentioned_places": ["송파구", "잠실"],
                    "mentioned_persons": [],
                },
            )
        )
    return out


def make_inputs() -> list[Record]:
    """6주. 마지막 주에 급증(직전 2주 평균 대비 큰 폭)을 심는다."""
    recs: list[Record] = []
    recs += article("2026-07-06", "hani", n=2)  # 1주차
    recs += article("2026-07-13", "chosun", n=3)  # 2
    recs += article("2026-07-20", "hani", n=2)  # 3
    recs += article("2026-07-27", "kbs", n=2)  # 4
    recs += article("2026-08-03", "hani", n=2)  # 5
    recs += article("2026-08-10", "chosun", n=1)  # 6 (직전 창 = 2,2 → 평균 2)
    recs += article("2026-08-17", "hani", n=1, conf=0.9)
    recs += article("2026-08-17", "chosun", n=1)
    recs += article("2026-08-17", "kbs", n=1)
    recs += article("2026-08-17", "mbc", n=1)
    recs += article("2026-08-17", "ytn", n=10)  # 7주차 급증: 14건 vs 직전 2,1
    # 잡음: 다른 시군구 기사는 무시돼야 한다
    recs += [
        Record(
            kind="news_article",
            collector_id="naver_news",
            source_name="네이버",
            source_url="https://x.test/other",
            source_license="api_tos",
            observed_at=datetime(2026, 8, 17, tzinfo=KST),
            observed_precision="minute",
            ingested_at=datetime(2026, 9, 1, tzinfo=KST),
            geo_level="sigungu",
            geo_code="1168000000",  # 강남구
            geo_name="서울 강남구",
            confidence=0.7,
            natural_key="https://x.test/other",
            payload={
                "title": "옆 동네",
                "publisher": "hani",
                "published_at": "2026-08-17T00:00:00+09:00",
                "url": "https://x.test/other",
                "summary": "s",
                "mentioned_places": [],
                "mentioned_persons": [],
            },
        )
    ]
    return recs


def run() -> list[Record]:
    results = list(Analyzer(meta=META).compute(make_inputs()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    return results


# --- 계약 -----------------------------------------------------------------------


def test_output_records_are_valid():
    records = run()
    assert len(records) == 1, "선거구당 news_pulse 는 1건이다"
    r = records[0]
    Record.model_validate(r.model_dump())
    assert r.collector_id == Analyzer.id
    assert r.geo_code == SIGUNGU
    assert r.geo_level.value == "sigungu"


def test_evidence_is_recorded():
    for r in run():
        assert r.derived_from
        assert len(set(r.derived_from)) == len(r.derived_from)


def test_confidence_is_not_certain():
    for r in run():
        assert r.confidence < 1.0


def test_observed_at_points_at_the_input_not_the_run():
    latest_input = max(r.observed_at for r in make_inputs())
    for r in run():
        assert r.observed_at <= latest_input


def test_other_sigungu_articles_are_excluded():
    r = run()[0]
    # 강남구 기사가 derived_from 에 없다
    inputs = {x.record_id: x for x in make_inputs()}
    assert all(inputs[rid].geo_code == SIGUNGU for rid in r.derived_from)


# --- 창 자르기 ----------------------------------------------------------------


def test_window_is_truncated_to_config():
    r = run()[0]
    assert r.payload["window_weeks"] == 4
    assert len(r.payload["weekly"]) == 4
    # total_articles 는 남긴 4주 합과 일치한다 (불변식)
    assert r.payload["total_articles"] == sum(w["article_count"] for w in r.payload["weekly"])
    # 잘린 앞 주는 derived_from 에서도 빠진다
    assert r.payload["total_articles"] == len(r.derived_from)


# --- 급증 판정 --------------------------------------------------------------------


def test_last_week_flagged_as_spike():
    weekly = run()[0].payload["weekly"]
    assert weekly[-1]["spike"] is True
    assert weekly[-1]["spike_z"] is not None
    # 급증이 아닌 주도 있어야 한다 (전부 spike 면 지표가 무의미)
    assert any(w["spike"] is False for w in weekly)


def test_early_week_without_enough_history_has_no_z():
    """min_history_weeks=2 라 첫 주는 직전 창이 비어 z 를 못 낸다."""
    all_weekly = list(Analyzer(meta=_wide_meta()).compute(make_inputs()))[0].payload["weekly"]
    assert all_weekly[0]["spike_z"] is None
    assert all_weekly[0]["spike"] is False


def _wide_meta() -> AnalyzerMeta:
    data = META.model_dump()
    data["config"]["common"]["window_weeks"] = 99  # 자르지 않고 전 주를 본다
    return AnalyzerMeta.model_validate(data)


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    ids_a = [r.record_id for r in run()]
    ids_b = [r.record_id for r in run()]
    assert ids_a == ids_b


def test_empty_input_is_an_error():
    try:
        list(Analyzer(meta=META).compute([]))
    except AnalyzeError:
        return
    raise AssertionError("입력 0건인데 AnalyzeError 가 나지 않았다")


# --- 변별력 ---------------------------------------------------------------------


def test_weekly_counts_discriminate():
    """모든 주가 같은 기사 수면 계열이 아무것도 말하지 않는다 (30-analysis-spec §9).
    단일 산출이라 단위 간이 아니라 주 간 변별을 본다."""
    weekly = run()[0].payload["weekly"]
    counts = {w["article_count"] for w in weekly}
    assert len(counts) > 1, f"모든 주가 같은 기사 수다: {weekly}"
