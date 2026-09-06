"""순수 계산 검증. 여기 있는 함수는 레코드도 파일도 모른다."""

from __future__ import annotations

from datetime import date

import pytest

from votelink.contract.enums import IssueTrend

from ..calc import (
    Article,
    build_window,
    classify,
    is_backfill_distorted,
    match_terms,
    recency_score,
    sample_headlines,
    top_places,
    trend_of,
    week_counts_all,
    week_counts_for,
    week_start_of,
)

CATS = [
    ("transit", ("트램", "9호선")),
    ("redevelopment", ("재건축",)),
]


def art(week: str, *, title="", places=(), url="u", published="2026-01-01T00:00:00+09:00", cats=()):
    return Article(
        week_start=date.fromisoformat(week),
        title=title,
        summary="",
        published_at=published,
        url=url,
        places=tuple(places),
        record_id=url,
        categories=tuple(cats),
    )


def test_week_start_of_is_monday():
    assert week_start_of(date(2026, 9, 6)) == date(2026, 8, 31)  # 일요일 → 그 주 월요일
    assert week_start_of(date(2026, 8, 31)).weekday() == 0


def test_match_terms_is_substring_and_sorted():
    assert match_terms("위례선 트램과 9호선", ["9호선", "트램", "버스"]) == ["9호선", "트램"]
    assert match_terms("교통 없음", ["트램"]) == []


def test_classify_multi_category():
    assert classify("트램 옆 재건축", "", CATS) == ("redevelopment", "transit")


def test_classify_empty_when_no_keyword():
    assert classify("잠실야구장 경기", "삼성 라이온즈", CATS) == ()


def test_classify_reads_title_and_summary():
    assert classify("동네 소식", "9호선 연장 확정", CATS) == ("transit",)


# --- 최근성 -------------------------------------------------------------------


def test_recency_score_weights_recent_double():
    # 반감기 2주: 가장 최근 주 가중 1, 2주 전 0.5.
    assert recency_score([0, 0, 1], half_life_weeks=2) == pytest.approx(1.0)
    assert recency_score([1, 0, 0], half_life_weeks=2) == pytest.approx(0.5)
    assert recency_score([2, 0, 2], half_life_weeks=2) == pytest.approx(2.0 * 0.5 + 2.0)


def test_recency_score_zero_for_empty():
    assert recency_score([], half_life_weeks=4) == 0.0
    assert recency_score([0, 0, 0], half_life_weeks=4) == 0.0


# --- 추세 -------------------------------------------------------------------


def test_trend_uses_share_not_absolute_volume():
    # 전체 분류량이 백필로 뒷주에 몰려 있어도(총계 1,1,1,10,10,10), 카테고리 비중이
    # 그대로면 flat 이어야 한다 — 절대량이면 전부 rising 으로 나온다.
    total = [1, 1, 1, 10, 10, 10]
    flat_cat = [1, 1, 1, 10, 10, 10]  # 항상 100%
    assert trend_of(flat_cat, total, rising_ratio=1.3, falling_ratio=0.77) == IssueTrend.FLAT
    # 비중이 실제로 커진 카테고리만 rising
    rising_cat = [0, 0, 0, 8, 9, 10]
    assert trend_of(rising_cat, total, rising_ratio=1.3, falling_ratio=0.77) == IssueTrend.RISING
    # 비중이 줄어든 카테고리는 falling
    falling_cat = [1, 1, 1, 1, 0, 0]
    assert trend_of(falling_cat, total, rising_ratio=1.3, falling_ratio=0.77) == IssueTrend.FALLING


def test_trend_prior_zero_is_rising_only_if_recent_positive():
    total = [1, 1, 1, 1, 2, 3]
    assert (
        trend_of([0, 0, 0, 0, 1, 2], total, rising_ratio=1.3, falling_ratio=0.77)
        == IssueTrend.RISING
    )
    assert (
        trend_of([0, 0, 0, 0, 0, 0], total, rising_ratio=1.3, falling_ratio=0.77) == IssueTrend.FLAT
    )


def test_trend_empty_is_flat():
    assert trend_of([], [], rising_ratio=1.3, falling_ratio=0.77) == IssueTrend.FLAT


# --- 창 -------------------------------------------------------------------


def test_build_window_truncates_to_last_n_weeks():
    arts = [art("2026-07-06"), art("2026-07-13"), art("2026-07-20"), art("2026-07-27")]
    w = build_window(arts, window_weeks=2)
    assert w.weeks == [date(2026, 7, 20), date(2026, 7, 27)]
    assert len(w.kept) == 2


def test_build_window_fills_empty_weeks():
    arts = [art("2026-07-06"), art("2026-07-27")]  # 가운데 2주 비어 있음
    w = build_window(arts, window_weeks=99)
    assert w.weeks == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20), date(2026, 7, 27)]


def test_build_window_empty_input():
    w = build_window([], window_weeks=12)
    assert w.weeks == [] and w.kept == [] and w.index == {}


def test_week_counts_for_category():
    arts = [
        art("2026-07-06", cats=("transit",)),
        art("2026-07-06", cats=("transit", "redevelopment")),
        art("2026-07-13", cats=("redevelopment",)),
    ]
    w = build_window(arts, window_weeks=99)
    assert week_counts_for("transit", w) == [2, 0]
    assert week_counts_for("redevelopment", w) == [1, 1]
    assert week_counts_all(w) == [2, 1]


# --- top_places / headlines -------------------------------------------------


def test_top_places_deterministic_tiebreak():
    arts = [
        art("2026-07-06", places=("잠실", "송파구")),
        art("2026-07-06", places=("잠실",)),
        art("2026-07-06", places=("가락동",)),
    ]
    tp = top_places(arts, top_n=5)
    assert tp[0] == {"term": "잠실", "count": 2}
    # 동점(가락동 1, 송파구 1) 은 이름 오름차순
    assert [t["term"] for t in tp[1:]] == ["가락동", "송파구"]


def test_sample_headlines_order_and_cap():
    arts = [
        art("2026-07-06", title="옛날", published="2026-07-01T00:00:00+09:00", url="a"),
        art("2026-07-06", title="최신", published="2026-07-20T00:00:00+09:00", url="b"),
        art("2026-07-06", title="중간", published="2026-07-10T00:00:00+09:00", url="c"),
        art("2026-07-06", title="여분", published="2026-07-05T00:00:00+09:00", url="d"),
    ]
    # published_at 내림차순 상위 3: 최신(07-20) · 중간(07-10) · 여분(07-05)
    assert sample_headlines(arts, limit=3) == ["최신", "중간", "여분"]


def test_sample_headlines_dedups_titles():
    arts = [
        art("2026-07-06", title="같은 제목", published="2026-07-20T00:00:00+09:00", url="a"),
        art("2026-07-06", title="같은 제목", published="2026-07-19T00:00:00+09:00", url="b"),
        art("2026-07-06", title="다른 제목", published="2026-07-18T00:00:00+09:00", url="c"),
    ]
    assert sample_headlines(arts, limit=3) == ["같은 제목", "다른 제목"]


# --- backfill -------------------------------------------------------------------


def test_is_backfill_distorted():
    assert is_backfill_distorted([1, 1, 1, 1, 20], ratio=3.0) is True
    assert is_backfill_distorted([5, 6, 5, 6, 7], ratio=3.0) is False
    # 비어있는 주가 많으면(유효 주 3 미만) 판정하지 않는다
    assert is_backfill_distorted([0, 0, 10], ratio=3.0) is False
