"""주 단위 접기 + 급증 판정. **순수 함수. 레코드도 파일도 시계도 모른다.**

입력은 (주 시작일, 언론사, 동·지명 직접 언급 여부) 세 값뿐이고, 출력은
`NewsWeekPoint` 에 그대로 들어갈 dict 다. "현재 주"는 입력에서 파생하며
`datetime.now()` 를 쓰지 않는다 — 쓰면 재실행마다 급증 판정이 바뀐다.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Article:
    week_start: date
    """그 기사 발행일이 속한 주의 월요일."""
    publisher: str
    district_specific: bool
    record_id: str


def week_start_of(d: date) -> date:
    """그 날짜가 속한 주의 월요일 (그레고리력, ISO 주와 같은 경계)."""
    return d - timedelta(days=d.weekday())


def _week_range(lo: date, hi: date) -> list[date]:
    """lo~hi 사이 모든 주의 월요일. 기사 없는 주도 0 으로 채운다 —
    빈 주를 건너뛰면 급증 판정의 분모가 조용히 달라진다."""
    weeks: list[date] = []
    cur = lo
    while cur <= hi:
        weeks.append(cur)
        cur += timedelta(days=7)
    return weeks


def fold_weeks(
    articles: list[Article],
    *,
    history_weeks: int,
    min_history_weeks: int,
    spike_z_threshold: float,
) -> list[dict]:
    """기사들을 주별로 접는다. 반환 dict 는 NewsWeekPoint 필드 + `_record_ids`
    (분석기가 derived_from 에 쓰고 payload 에는 넣지 않는다)."""
    if not articles:
        return []

    by_week: dict[date, list[Article]] = {}
    for a in articles:
        by_week.setdefault(a.week_start, []).append(a)

    weeks = _week_range(min(by_week), max(by_week))
    counts = [len(by_week.get(w, [])) for w in weeks]

    points: list[dict] = []
    for i, w in enumerate(weeks):
        bucket = by_week.get(w, [])
        n = len(bucket)
        pubs = Counter(a.publisher for a in bucket)
        top_share = (max(pubs.values()) / n * 100.0) if n else 0.0

        history = counts[max(0, i - history_weeks) : i]
        z: float | None = None
        if len(history) >= min_history_weeks:
            sd = statistics.stdev(history)
            if sd > 0:
                z = (n - statistics.fmean(history)) / sd
        spike = z is not None and z >= spike_z_threshold

        points.append(
            {
                "week_start": w.isoformat(),
                "article_count": n,
                "district_specific_count": sum(1 for a in bucket if a.district_specific),
                "publisher_count": len(pubs),
                "top_publisher_share": round(top_share, 2),
                "spike": spike,
                "spike_z": None if z is None else round(z, 2),
                "_record_ids": sorted(a.record_id for a in bucket),
            }
        )
    return points


def is_backfill_distorted(counts: list[int], *, ratio: float) -> bool:
    """가장 최근 주가 창 중앙값의 `ratio` 배를 넘으면 True. 검색 API 상한이
    최근 주로 기사를 몰아넣은 상태를 잡는다."""
    nonzero = [c for c in counts if c > 0]
    if len(nonzero) < 3:
        return False
    median = statistics.median(counts)
    return median > 0 and counts[-1] > median * ratio
