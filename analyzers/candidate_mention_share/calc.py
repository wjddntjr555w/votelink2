"""순수 계산. 레코드도 파일도 모른다 — 날짜·이름·개수만 다룬다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta


def week_start(dt: datetime) -> date:
    """ISO 월요일 시작 날짜."""
    d = dt.date()
    return d - timedelta(days=d.weekday())


def recent_weeks(latest: date, window_weeks: int) -> list[date]:
    """`latest`가 속한 주부터 거슬러 `window_weeks`개, 오래된 주 순."""
    latest_week = latest - timedelta(days=latest.weekday())
    return [latest_week - timedelta(weeks=i) for i in range(window_weeks - 1, -1, -1)]


@dataclass
class CandidateInfo:
    """로스터 후보 1명 + 이 district 안에서 is_ours 인지."""

    name: str
    party: str
    lineage: str
    is_ours: bool


def merge_rosters(rosters: list) -> list[CandidateInfo]:
    """여러 캠프 로스터를 하나의 후보 목록으로 합친다.

    로스터 등장 순서를 보존한다(각 로스터는 ours 먼저, opponents는 candidates.yaml
    순). 같은 이름이 여러 로스터에 나오면 첫 등장의 party/lineage를 쓰고, 그중
    하나라도 ours 면 is_ours=True 로 합친다 — 한 district 를 여러 캠프가 관할할
    때(P-001) 서로의 "우리 후보"가 다를 수 있어서다.
    """
    order: list[str] = []
    seen: dict[str, tuple[str, str]] = {}
    ours: dict[str, bool] = {}
    for roster in rosters:
        for cand, is_ours in [(roster.ours, True)] + [(o, False) for o in roster.opponents]:
            if cand.name not in seen:
                order.append(cand.name)
                seen[cand.name] = (cand.party, cand.lineage)
            ours[cand.name] = ours.get(cand.name, False) or is_ours
    return [
        CandidateInfo(name=name, party=seen[name][0], lineage=seen[name][1], is_ours=ours[name])
        for name in order
    ]


@dataclass
class WeekTally:
    week: date
    count: int = 0
    record_ids: list[str] = field(default_factory=list)


def tally_weeks(
    weeks: list[date], matches: list[tuple[date, str]]
) -> tuple[list[WeekTally], list[str]]:
    """`matches`(주 시작일, record_id) 를 `weeks` 그리드에 집계한다.

    반환: (주별 집계, 실제로 쓰인 record_id 전부 — derived_from 용, 중복 제거)
    """
    by_week = {w: WeekTally(week=w) for w in weeks}
    used: list[str] = []
    seen_ids: set[str] = set()
    for wk, record_id in matches:
        tally = by_week.get(wk)
        if tally is None:
            continue  # window 밖 주
        tally.count += 1
        tally.record_ids.append(record_id)
        if record_id not in seen_ids:
            seen_ids.add(record_id)
            used.append(record_id)
    return [by_week[w] for w in weeks], used


def share_pct(count: int, week_total: int) -> float | None:
    """그 주 등록 후보 전체 언급 합 대비 %. 분모 0이면 None."""
    if week_total == 0:
        return None
    return round(count / week_total * 100, 1)


def wow_change_pct(count: int, prev_count: int) -> float | None:
    """전주 대비 건수 변화율 %. 전주 0이면 None(0에서 어떤 수로 가도 무한대)."""
    if prev_count == 0:
        return None
    return round((count - prev_count) / prev_count * 100, 1)


def is_backfill_distorted(week_counts: list[int], ratio_threshold: float) -> bool:
    """news_pulse 와 같은 휴리스틱: 최근 주가 창 중앙값의 ratio_threshold 배를 넘으면 True.

    0으로만 채워진 창(첫 주부터 관측)은 왜곡을 판단할 근거가 없으니 False.
    """
    if not week_counts or week_counts[-1] == 0:
        return False
    sorted_counts = sorted(week_counts)
    n = len(sorted_counts)
    median = (
        sorted_counts[n // 2] if n % 2 else (sorted_counts[n // 2 - 1] + sorted_counts[n // 2]) / 2
    )
    if median == 0:
        return False
    return week_counts[-1] > median * ratio_threshold
