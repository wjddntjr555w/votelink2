"""이슈 분류 + 주 단위 최근성·추세. **순수 함수. 레코드도 파일도 시계도 모른다.**

분류는 어휘집 substring 매칭이다 (형태소 분석도 NER 도 아니다) — `collectors/naver_news/
text.py:match_terms` 와 같은 방식을 여기 다시 구현한다. L1 과 L2 는 서로의 코드를
import 하지 않는다 (`docs/00-overview.md §3`). "현재 주"는 입력에서 파생하며
`datetime.now()` 를 쓰지 않는다 — 쓰면 재실행마다 최근성·추세가 달라진다.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from votelink.contract.enums import IssueTrend

# (category_key, keywords) 쌍. calc 는 어휘집 모델을 모르고 이 튜플만 받는다.
CategoryKeywords = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class Article:
    week_start: date
    """그 기사 발행일이 속한 주의 월요일."""
    title: str
    summary: str
    published_at: str  # 원본 ISO 문자열. 헤드라인 정렬 키
    url: str  # 헤드라인 동점 tiebreak (오름차순)
    places: tuple[str, ...]  # payload.mentioned_places
    record_id: str
    categories: tuple[str, ...]  # classify() 결과. 빈 튜플이면 unclassified


@dataclass(frozen=True)
class Window:
    weeks: list[date]  # 오래된 주 → 최근 주. window_weeks 로 잘린 뒤
    kept: list[Article]  # weeks 범위 안의 기사만
    index: dict[date, int]  # week_start → weeks 안 위치


def week_start_of(d: date) -> date:
    """그 날짜가 속한 주의 월요일 (그레고리력, ISO 주와 같은 경계)."""
    return d - timedelta(days=d.weekday())


def _week_range(lo: date, hi: date) -> list[date]:
    """lo~hi 사이 모든 주의 월요일. 기사 없는 주도 채운다 — 빈 주를 건너뛰면
    최근성·추세의 분모가 조용히 달라진다."""
    weeks: list[date] = []
    cur = lo
    while cur <= hi:
        weeks.append(cur)
        cur += timedelta(days=7)
    return weeks


def match_terms(text: str, terms: Iterable[str]) -> list[str]:
    """사전에 있는 표현이 문자열로 등장하는지만 본다.

    형태소 분석도 개체명 인식도 아니다. 사전 밖의 표현은 잡히지 않으며, 그게
    의도다 — 사전에 없는 것을 추측하는 순간 그건 해석이다 (naver_news/text.py 와 동일).
    """
    return sorted({t for t in terms if t and t in text})


def classify(title: str, summary: str, categories: Sequence[CategoryKeywords]) -> tuple[str, ...]:
    """`title + " " + summary` 에 카테고리 keyword 가 substring 으로 하나라도 있으면
    그 카테고리 key. 여러 카테고리에 걸리면 전부 (비배타). 정렬해 반환 (결정적)."""
    haystack = f"{title} {summary}"
    hit = {key for key, keywords in categories if any(k in haystack for k in keywords)}
    return tuple(sorted(hit))


def build_window(articles: list[Article], *, window_weeks: int) -> Window:
    """기사들을 주 그리드에 놓고 마지막 window_weeks 주만 남긴다. news_pulse 의
    `folded[-window_weeks:]` 와 같은 정신 — 첫 백필의 성긴 꼬리를 자른다."""
    if not articles:
        return Window(weeks=[], kept=[], index={})
    by_week = {a.week_start for a in articles}
    weeks = _week_range(min(by_week), max(by_week))[-window_weeks:]
    keep = set(weeks)
    kept = [a for a in articles if a.week_start in keep]
    return Window(weeks=weeks, kept=kept, index={w: i for i, w in enumerate(weeks)})


def week_counts_for(category: str, window: Window) -> list[int]:
    """그 카테고리로 분류된 기사의 주별 수. 오래된 주 → 최근 주."""
    counts = [0] * len(window.weeks)
    for a in window.kept:
        if category in a.categories:
            counts[window.index[a.week_start]] += 1
    return counts


def week_counts_all(window: Window) -> list[int]:
    """창 안 전체 기사의 주별 수 (backfill 왜곡 판정용)."""
    counts = [0] * len(window.weeks)
    for a in window.kept:
        counts[window.index[a.week_start]] += 1
    return counts


def week_counts_classified(window: Window) -> list[int]:
    """창 안에서 **어느 카테고리든 하나라도 걸린** 기사의 주별 수. trend 의 분모다 —
    카테고리 count 를 이걸로 나누면 백필이 모든 카테고리를 함께 부풀린 효과가 상쇄된다."""
    counts = [0] * len(window.weeks)
    for a in window.kept:
        if a.categories:
            counts[window.index[a.week_start]] += 1
    return counts


def recency_score(week_counts: Sequence[int], *, half_life_weeks: float) -> float:
    """Σ 주별 기사 수 × 0.5 ** (최근으로부터의 주차 / half_life_weeks).

    가장 최근 주의 가중치는 1. half_life_weeks 주 전의 기사는 절반으로 센다.
    """
    n = len(week_counts)
    if n == 0:
        return 0.0
    return sum(c * 0.5 ** ((n - 1 - i) / half_life_weeks) for i, c in enumerate(week_counts))


def trend_of(
    cat_counts: Sequence[int],
    total_counts: Sequence[int],
    *,
    rising_ratio: float,
    falling_ratio: float,
) -> IssueTrend:
    """이 카테고리가 **분류된 기사 중 차지하는 비중**이 최근 절반에서 이전 절반보다
    얼마나 커졌나. 절대량이 아니라 비중을 쓰는 이유: 첫 백필은 모든 카테고리의 절대량을
    함께 부풀려서, 절대량으로 재면 전 카테고리가 rising 으로 나와 변별력이 0이 된다
    (voter_profile 이 절대 기울기 → 지역구 편차로 바꾼 것과 같은 교훈, §9).
    """
    n = len(cat_counts)
    if n == 0:
        return IssueTrend.FLAT
    split = math.ceil(n / 2)
    cat_recent = sum(cat_counts[n - split :])
    cat_prior = sum(cat_counts[: n - split])
    tot_recent = sum(total_counts[n - split :])
    tot_prior = sum(total_counts[: n - split])
    recent_share = cat_recent / tot_recent if tot_recent else 0.0
    prior_share = cat_prior / tot_prior if tot_prior else 0.0
    if prior_share == 0.0:
        return IssueTrend.RISING if recent_share > 0.0 else IssueTrend.FLAT
    ratio = recent_share / prior_share
    if ratio >= rising_ratio:
        return IssueTrend.RISING
    if ratio <= falling_ratio:
        return IssueTrend.FALLING
    return IssueTrend.FLAT


def top_places(articles: Sequence[Article], *, top_n: int) -> list[dict]:
    """이 카테고리 기사들의 mentioned_places 누적 상위. 동점은 이름 오름차순 (결정적).
    반환 dict 는 TermCount payload 모양."""
    counter: Counter[str] = Counter()
    for a in articles:
        counter.update(a.places)
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [{"term": term, "count": n} for term, n in ordered]


def sample_headlines(articles: Sequence[Article], *, limit: int = 3) -> list[str]:
    """대표 헤드라인. published_at 내림차순, 동점은 url 오름차순. 제목 중복은 접는다.
    원문 title 을 그대로 쓴다 (본문이 아니다)."""
    ordered = sorted(articles, key=lambda a: a.url)
    ordered = sorted(ordered, key=lambda a: a.published_at, reverse=True)
    out: list[str] = []
    for a in ordered:
        if a.title not in out:
            out.append(a.title)
        if len(out) >= limit:
            break
    return out


def is_backfill_distorted(counts: Sequence[int], *, ratio: float) -> bool:
    """가장 최근 주가 창 중앙값의 `ratio` 배를 넘으면 True. 검색 API 상한이 최근
    주로 기사를 몰아넣은 상태를 잡는다 (news_pulse 와 같은 판정)."""
    nonzero = [c for c in counts if c > 0]
    if len(nonzero) < 3:
        return False
    median = statistics.median(counts)
    return median > 0 and counts[-1] > median * ratio
