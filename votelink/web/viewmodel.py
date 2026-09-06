"""레코드를 화면 조각으로. **순수 함수만 있다.**

같은 (정책, 프로파일)이면 같은 화면이 나온다 — 디스크도 시계도 난수도 쓰지 않는다.
`parse()`(L1)·`compute()`(L2)와 같은 자리다 (`docs/40-webapp-spec.md §2`).

여기서 지키는 계약이 하나 있다. **`gap_* = None` 을 0으로 만들지 않는다.**
계약 주석("'차이가 없다'와 '모른다'는 다르다")을 UI가 무너뜨리는 경로가 넷이라 넷 다 막는다:
숫자는 `—`, 색은 칠하지 않고 해칭, 집계는 분모를 노출, 선 그래프는 끊는다 (`§8`).
그래서 템플릿에 `float | None` 을 넘기지 않고 `GapCell` 을 넘긴다 —
**None 을 0 으로 포맷할 수 있는 경로가 템플릿에 존재하지 않는다.**
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from votelink.contract.enums import AgeBand, Camp, ElectionType, Trend
from votelink.contract.payloads import LeanPoint
from votelink.reference.compliance import Policy, ReviewStatus, Verdict, review_with
from votelink.reference.districts import District
from votelink.web.loader import (
    ComparisonProfiles,
    DistrictNews,
    DistrictProfiles,
    EmdProfile,
    LoadDiagnostics,
    NationProfiles,
    NewsDiagnostics,
    NewsItem,
    SkippedDistrict,
)
from votelink.web.shapes import ShapeSet

UNKNOWN_TEXT = "—"
"""값 없음. 빈칸은 렌더 버그와 구분이 안 되고, `0.0` 은 거짓말이다."""

UNKNOWN_FILL = "url(#hatch)"
"""색이 아니라 무늬. 발산 스케일에서 중립색은 0.0과 화면상 완전히 같아진다."""

CAMP_ORDER: tuple[Camp, ...] = (Camp.PROGRESSIVE, Camp.CENTRIST, Camp.CONSERVATIVE, Camp.OTHER)
CAMP_LABELS = {
    Camp.PROGRESSIVE: "진보",
    Camp.CENTRIST: "중도",
    Camp.CONSERVATIVE: "보수",
    Camp.OTHER: "기타",
}
TREND_LABELS = {
    Trend.CONSERVATIVE_SHIFT: "보수 이동",
    Trend.STABLE: "정체",
    Trend.PROGRESSIVE_SHIFT: "진보 이동",
}
TREND_NOTE = (Trend.__doc__ or "").strip()
"""추세 판정의 설명문. **계약 독스트링이 유일한 출처다.**

`meta.yaml` 의 `trend_threshold` 같은 L2 내부 값을 화면에 쓰지 않는다.
"""

GAP_LEVELS = ("district", "sigungu", "sido", "nation")

ELECTION_TYPE_LABELS: dict[ElectionType, str] = {
    ElectionType.PRESIDENTIAL: "대선",
    ElectionType.NATIONAL_ASSEMBLY: "총선",
    ElectionType.LOCAL: "지방선거",
    ElectionType.BY_ELECTION: "재보궐",
}
DEFAULT_ELECTION_TYPE = ElectionType.PRESIDENTIAL


def resolve_election_type(raw: str | None) -> ElectionType:
    """모르는 값은 기본값으로 떨어뜨린다 (sort/metric 폴백과 같은 관용)."""
    try:
        return ElectionType(raw) if raw else DEFAULT_ELECTION_TYPE
    except ValueError:
        return DEFAULT_ELECTION_TYPE


def election_type_choices() -> list[tuple[str, str]]:
    """(값, 라벨) 목록. 스위처 UI 가 쓴다 — 데이터 유무와 무관하게 4종 전부.

    "데이터 없음"과 "종류 없음"을 같게 만들지 않는다 (§8 정신).
    """
    return [(t.value, ELECTION_TYPE_LABELS[t]) for t in ElectionType]


_STATUS_SEVERITY = {
    ReviewStatus.CLEARED: 0,
    ReviewStatus.UNREVIEWED: 1,
    ReviewStatus.BLOCKED: 2,
}


# --- 편차 셀 ---------------------------------------------------------------------


class GapCell(BaseModel):
    """상위 단위 대비 보수 득표율 편차 한 칸. **None 과 0.0 이 절대 같아 보이지 않는다.**"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float | None
    text: str
    known: bool
    css_class: str
    title: str

    @classmethod
    def of(cls, value: float | None, label: str = "상위 단위") -> GapCell:
        if value is None:
            return cls(
                value=None,
                text=UNKNOWN_TEXT,
                known=False,
                css_class="gap gap--unknown",
                title=f"{label} 기준선 레코드가 없어 계산할 수 없다",
            )
        sign = "pos" if value > 0 else "neg" if value < 0 else "zero"
        return cls(
            value=value,
            text=f"{value:+.1f}",
            known=True,
            css_class=f"gap gap--{sign}",
            title=f"{label} 대비 보수 득표율 {value:+.2f}%p",
        )


class GapSummary(BaseModel):
    """편차 평균. **분모를 함께 보여준다** — 모르는 회차를 평균에서 조용히 빼지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mean: float | None
    known: int
    total: int
    text: str

    @classmethod
    def of(cls, values: Sequence[float | None]) -> GapSummary:
        known = [v for v in values if v is not None]
        total = len(values)
        if not known:
            return cls(
                mean=None, known=0, total=total, text=f"{UNKNOWN_TEXT} ({total}회 중 0회 기준)"
            )
        mean = sum(known) / len(known)
        return cls(
            mean=mean,
            known=len(known),
            total=total,
            text=f"{mean:+.1f}%p ({total}회 중 {len(known)}회 기준)",
        )


# --- 스파크라인 -------------------------------------------------------------------


class SparkDot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cx: float
    cy: float
    title: str


class Sparkline(BaseModel):
    """인라인 SVG 꺾은선. **None 은 점을 찍지 않고 선을 끊는다.**

    앞뒤를 이으면 없는 데이터를 보간한 게 된다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    segments: list[str] = Field(default_factory=list)
    """`<polyline points="...">` 값. 끊긴 구간마다 하나."""
    dots: list[SparkDot] = Field(default_factory=list)
    width: float
    height: float
    y_min: float
    y_max: float
    breaks: int = 0
    """값이 없어 건너뛴 점의 개수."""

    @property
    def is_empty(self) -> bool:
        return not self.dots


def sparkline(
    values: Sequence[float | None],
    labels: Sequence[str],
    *,
    width: float = 120.0,
    height: float = 28.0,
) -> Sparkline:
    known = [v for v in values if v is not None]
    lo, hi = (min(known), max(known)) if known else (0.0, 1.0)
    span = (hi - lo) or 1.0
    step = width / max(len(values) - 1, 1)

    def y_of(v: float) -> float:
        return round(height - (v - lo) / span * height, 1)

    segments: list[str] = []
    dots: list[SparkDot] = []
    run: list[str] = []
    for index, value in enumerate(values):
        if value is None:
            if len(run) >= 2:
                segments.append(" ".join(run))
            run = []
            continue
        x = round(index * step, 1)
        y = y_of(value)
        run.append(f"{x},{y}")
        label = labels[index] if index < len(labels) else ""
        dots.append(SparkDot(cx=x, cy=y, title=f"{label} {value:.1f}"))
    if len(run) >= 2:
        segments.append(" ".join(run))

    return Sparkline(
        segments=segments,
        dots=dots,
        width=width,
        height=height,
        y_min=lo,
        y_max=hi,
        breaks=sum(1 for v in values if v is None),
    )


# --- 카드 조각 -------------------------------------------------------------------


class BarSlice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    camp: Camp
    label: str
    pct: float
    offset: float
    css_class: str


class AgeBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    band: AgeBand
    pct: float
    height_pct: float


def camp_bar(point: LeanPoint) -> list[BarSlice]:
    """진영 구성 누적 막대. 계약(`_check_shares`)이 4개 키를 전부 보장한다."""
    slices: list[BarSlice] = []
    offset = 0.0
    for camp in CAMP_ORDER:
        pct = point.camp_share[camp]
        slices.append(
            BarSlice(
                camp=camp,
                label=CAMP_LABELS[camp],
                pct=pct,
                offset=offset,
                css_class=f"camp camp--{camp.value}",
            )
        )
        offset += pct
    return slices


def age_bars(age_mix: dict[AgeBand, float]) -> list[AgeBar]:
    peak = max(age_mix.values()) or 1.0
    return [
        AgeBar(band=band, pct=age_mix[band], height_pct=round(age_mix[band] / peak * 100, 1))
        for band in AgeBand
        if band in age_mix
    ]


def gap_labels(district: District) -> dict[str, str]:
    """편차 기준이 되는 상위 단위의 **실제 이름**. 코드에 박지 않는다."""
    return {
        "district": district.name,
        "sigungu": district.sigungu,
        "sido": district.sido,
        "nation": "전국",
    }


class EmdCard(BaseModel):
    """행정동 한 곳 = 카드 한 장. 제안서 A-001의 설계다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geo_code: str
    geo_name: str
    latest_election_id: str
    latest_election_date: str
    election_count: int
    camp_bar: list[BarSlice]
    turnout: float
    swing: float
    trend: Trend
    trend_label: str
    gaps: dict[str, GapCell]
    """최근 선거의 편차 4종."""
    gap_coverage: dict[str, GapSummary]
    """단위별 **시계열 전체**의 편차 요약. 어느 단위의 기준선이 몇 회 비었는지 여기서 드러난다.

    최근 선거만 보여주면 과거 회차의 결측이 화면 어디에도 안 나타난다 — 실제로
    2002년 시도 기준선이 그런 상태다.
    """
    gap_summary: GapSummary
    gap_summary_label: str = "지역구"
    """gap_summary 가 어느 단위 대비인지. 템플릿이 "지역구"를 박아 쓰지 않게."""
    conservative_spark: Sparkline
    gap_spark: Sparkline
    age_bars: list[AgeBar]
    sex_ratio: float
    sex_ratio_text: str
    population_total: int
    confidence: float
    missing_gaps: int
    evidence_count: int
    evidence_ids: list[str]
    verdict: Verdict


def build_card(
    profile: EmdProfile,
    labels: dict[str, str],
    policy: Policy,
    *,
    levels: Sequence[str] = GAP_LEVELS,
    primary: str = "district",
) -> EmdCard:
    """`labels` 는 편차 기준 단위의 이름 dict (`gap_labels(district)` 또는 `{"nation": "전국"}`).
    `levels` 는 이 카드가 보여줄 편차 단위, `primary` 는 요약·스파크라인의 기준 단위."""
    payload = profile.payload
    series = payload.lean_series
    latest = series[-1]
    election_ids = [p.election_id for p in series]

    return EmdCard(
        geo_code=profile.geo_code,
        geo_name=profile.geo_name,
        latest_election_id=latest.election_id,
        latest_election_date=latest.election_date,
        election_count=len(series),
        camp_bar=camp_bar(latest),
        turnout=latest.turnout,
        swing=payload.swing,
        trend=payload.trend,
        trend_label=TREND_LABELS[payload.trend],
        gaps={
            level: GapCell.of(getattr(latest, f"gap_{level}"), labels.get(level, level))
            for level in levels
        },
        gap_coverage={
            level: GapSummary.of([getattr(p, f"gap_{level}") for p in series]) for level in levels
        },
        gap_summary=GapSummary.of([getattr(p, f"gap_{primary}") for p in series]),
        gap_summary_label=labels.get(primary, primary),
        conservative_spark=sparkline(
            [p.camp_share[Camp.CONSERVATIVE] for p in series], election_ids
        ),
        gap_spark=sparkline([getattr(p, f"gap_{primary}") for p in series], election_ids),
        age_bars=age_bars(payload.age_mix),
        sex_ratio=payload.sex_ratio,
        # 이 payload 의 유일한 비-퍼센트 값이다. % 를 붙이지 않는다.
        sex_ratio_text=f"{payload.sex_ratio:.2f}",
        population_total=payload.population_total,
        confidence=profile.record.confidence,
        missing_gaps=sum(
            1 for p in series for level in levels if getattr(p, f"gap_{level}") is None
        ),
        evidence_count=len(profile.record.derived_from),
        evidence_ids=list(profile.record.derived_from),
        verdict=review_with(policy, profile.record),
    )


# --- 집계 카드 -----------------------------------------------------------------
#
# 여러 동을 하나로 묶어 본다 (선거구 종합 / 전국 종합). **원시 득표수가 파생 레코드에
# 없어** camp_share·turnout 집계는 인구·투표율 가중 근사다 — approx 배지로 표시한다.
# 인구 구성(age·sex)은 인구가 정확한 가중치라 정확하고, 인구 합도 정확하다.


class AggregateCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    member_count: int
    camp_bar: list[BarSlice]
    turnout: float
    turnout_known: int
    turnout_total: int
    swing: float
    trend_mix: dict[Trend, int]
    """멤버 동들의 추세 분포. 단일 추세로 뭉개지 않는다 — 그러려면 L2 임계값을 화면에서
    읽어야 하는데 그건 계층 무지를 깬다 (§7)."""
    age_bars: list[AgeBar]
    sex_ratio: float
    sex_ratio_text: str
    population_total: int
    gaps: dict[str, GapSummary]
    """단위별로 멤버 동들의 최근 선거 편차를 요약 (분모 노출)."""
    conservative_spark: Sparkline
    gap_spark: Sparkline
    approx: bool
    approx_reason: str
    verdict: Verdict | None = None

    @property
    def trend_mix_text(self) -> str:
        parts = [f"{TREND_LABELS[t]} {n}" for t, n in self.trend_mix.items() if n]
        return " · ".join(parts) or UNKNOWN_TEXT


_APPROX_REASON = (
    "진영 구성·투표율은 동별 인구·투표율 가중 근사다 (원시 득표수가 파생 레코드에 없다)"
)


def _weighted_camp(rows: Sequence[tuple[LeanPoint, float]]) -> dict[Camp, float]:
    """rows = (point, voters). 투표자 수 가중 평균 후 100 으로 정규화."""
    wsum = sum(w for _, w in rows) or 1.0
    raw = {c: sum(pt.camp_share[c] * w for pt, w in rows) / wsum for c in Camp}
    total = sum(raw.values()) or 1.0
    return {c: v * 100.0 / total for c, v in raw.items()}


def aggregate_profiles(
    profiles: Sequence[EmdProfile],
    *,
    label: str,
    policy: Policy,
    levels: Sequence[str] = GAP_LEVELS,
    primary: str = "district",
) -> AggregateCard | None:
    """동 프로파일 여러 개 → 집계 카드 하나. 빈 입력이면 None."""
    profiles = list(profiles)
    if not profiles:
        return None

    dates: dict[str, str] = {}
    for p in profiles:
        for pt in p.payload.lean_series:
            dates[pt.election_id] = pt.election_date
    election_ids = sorted(dates, key=lambda e: dates[e])
    etype = profiles[0].payload.election_type

    con_series: list[float | None] = []
    gap_series: list[float | None] = []
    latest_point: LeanPoint | None = None
    latest_turnout = 0.0
    turnout_known = 0

    for eid in election_ids:
        rows = [
            (pt, p.payload.population_total)
            for p in profiles
            for pt in p.payload.lean_series
            if pt.election_id == eid
        ]
        if not rows:
            con_series.append(None)
            gap_series.append(None)
            continue
        voters = [pop * pt.turnout / 100.0 for pt, pop in rows]
        camp = _weighted_camp([(pt, w) for (pt, _), w in zip(rows, voters, strict=True)])
        popsum = sum(pop for _, pop in rows) or 1
        turnout = sum(pt.turnout * pop for pt, pop in rows) / popsum
        con_series.append(camp[Camp.CONSERVATIVE])

        known = [
            (getattr(pt, f"gap_{primary}"), w)
            for (pt, _), w in zip(rows, voters, strict=True)
            if getattr(pt, f"gap_{primary}") is not None
        ]
        gap_series.append(
            sum(g * w for g, w in known) / (sum(w for _, w in known) or 1.0) if known else None
        )

        latest_point = LeanPoint(
            election_id=eid,
            election_date=dates[eid],
            election_type=etype,
            camp_share=camp,
            turnout=min(turnout, 100.0),
        )
        latest_turnout = turnout
        turnout_known = len(rows)

    assert latest_point is not None  # election_ids 는 비지 않는다 (profiles 가 비지 않음)

    con_known = [c for c in con_series if c is not None]
    age_agg = _weighted_age(profiles)
    males, females = _sex_split(profiles)

    return AggregateCard(
        label=label,
        member_count=len(profiles),
        camp_bar=camp_bar(latest_point),
        turnout=latest_turnout,
        turnout_known=turnout_known,
        turnout_total=len(profiles),
        swing=(max(con_known) - min(con_known)) if con_known else 0.0,
        trend_mix=_trend_mix(profiles),
        age_bars=age_bars(age_agg),
        sex_ratio=(males / females) if females else 0.0,
        sex_ratio_text=f"{(males / females):.2f}" if females else UNKNOWN_TEXT,
        population_total=sum(p.payload.population_total for p in profiles),
        gaps={
            level: GapSummary.of(
                [getattr(p.payload.lean_series[-1], f"gap_{level}") for p in profiles]
            )
            for level in levels
        },
        conservative_spark=sparkline(con_series, election_ids),
        gap_spark=sparkline(gap_series, election_ids),
        approx=True,
        approx_reason=_APPROX_REASON,
        verdict=worst_verdict([review_with(policy, p.record) for p in profiles]),
    )


def _weighted_age(profiles: Sequence[EmdProfile]) -> dict[AgeBand, float]:
    popsum = sum(p.payload.population_total for p in profiles) or 1
    return {
        band: sum(p.payload.age_mix.get(band, 0.0) * p.payload.population_total for p in profiles)
        / popsum
        for band in AgeBand
    }


def _sex_split(profiles: Sequence[EmdProfile]) -> tuple[float, float]:
    """성비 + 인구로 남/여 인원을 복원해 합산 (정확)."""
    males = females = 0.0
    for p in profiles:
        r = p.payload.sex_ratio
        pop = p.payload.population_total
        females += pop / (1 + r)
        males += pop * r / (1 + r)
    return males, females


def _trend_mix(profiles: Sequence[EmdProfile]) -> dict[Trend, int]:
    counts = dict.fromkeys(Trend, 0)
    for p in profiles:
        counts[p.payload.trend] += 1
    return counts


# --- 대시보드 --------------------------------------------------------------------

SORTS = {
    "code": "행정동코드",
    "swing": "스윙 큰 순",
    "gap": "편차 높은 순",
    "turnout": "투표율 높은 순",
}


def sort_cards(cards: Sequence[EmdCard], key: str) -> list[EmdCard]:
    """모르는 키는 기본값으로 떨어뜨린다. 정렬 때문에 화면이 죽지 않게."""
    if key == "swing":
        return sorted(cards, key=lambda c: -c.swing)
    if key == "turnout":
        return sorted(cards, key=lambda c: -c.turnout)
    if key == "gap":
        # 값 없음은 뒤로. 0.0 과 섞이지 않게 known 을 1차 키로 쓴다.
        # 전국 화면 카드는 gaps 에 "nation" 키만 있다 — 있는 첫 단위를 쓴다.
        def gap_key(c: EmdCard) -> tuple[bool, float]:
            cell = next(iter(c.gaps.values()), None)
            if cell is None:
                return (True, 0.0)
            return (not cell.known, -(cell.value or 0.0))

        return sorted(cards, key=gap_key)
    return sorted(cards, key=lambda c: c.geo_code)


class DistrictView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_name: str
    cards: list[EmdCard]
    diagnostics: LoadDiagnostics
    sort: str
    gap_labels: dict[str, str] = Field(default_factory=dict)
    """편차 기준이 되는 상위 단위의 실제 이름. 템플릿이 "서울시"를 박아 쓰지 않게."""
    sorts: dict[str, str] = Field(default_factory=lambda: dict(SORTS))
    trend_note: str = TREND_NOTE

    election_type: str = DEFAULT_ELECTION_TYPE.value
    election_type_label: str = ELECTION_TYPE_LABELS[DEFAULT_ELECTION_TYPE]
    election_types: list[tuple[str, str]] = Field(default_factory=election_type_choices)
    summary_card: AggregateCard | None = None
    """이 선거구 전체를 한 장으로 묶은 집계 (근사). 카드가 없으면 None."""

    population_total: int = 0
    population_months: list[str] = Field(default_factory=list)
    as_of_months: list[str] = Field(default_factory=list)
    latest_election_id: str = ""
    latest_election_date: str = ""
    source_names: list[str] = Field(default_factory=list)
    source_licenses: list[str] = Field(default_factory=list)
    missing_gaps: int = 0
    verdict: Verdict | None = None
    """카드들 중 **가장 무거운** 상태. 헤더가 실상을 축소해 말하지 않게 한다."""

    @property
    def is_empty(self) -> bool:
        return not self.cards

    @property
    def coverage_text(self) -> str:
        """ "9 / 9". 둘 다 보여준다 — 다르면 결측이다."""
        return f"{self.diagnostics.loaded} / {self.diagnostics.expected}"

    @property
    def population_month_text(self) -> str:
        return " · ".join(self.population_months) or UNKNOWN_TEXT


def worst_verdict(verdicts: Sequence[Verdict]) -> Verdict | None:
    """가장 무거운 판정. 하나라도 blocked 면 헤더도 blocked 다 (fail-closed)."""
    if not verdicts:
        return None
    return max(verdicts, key=lambda v: _STATUS_SEVERITY[v.status])


def build_view(
    profiles: DistrictProfiles,
    policy: Policy,
    *,
    sort: str = "code",
    election_type: ElectionType = DEFAULT_ELECTION_TYPE,
) -> DistrictView:
    district = profiles.district
    labels = gap_labels(district)
    cards = [build_card(p, labels, policy) for p in profiles.profiles]
    ordered = sort_cards(cards, sort)
    latest = cards[0] if cards else None

    return DistrictView(
        district_name=district.name,
        cards=ordered,
        diagnostics=profiles.diagnostics,
        sort=sort if sort in SORTS else "code",
        gap_labels=labels,
        election_type=election_type.value,
        election_type_label=ELECTION_TYPE_LABELS[election_type],
        summary_card=aggregate_profiles(
            profiles.profiles, label=f"{district.name} 종합", policy=policy
        ),
        population_total=sum(c.population_total for c in cards),
        population_months=sorted({p.payload.population_month for p in profiles.profiles}),
        as_of_months=sorted({p.payload.as_of for p in profiles.profiles}),
        latest_election_id=latest.latest_election_id if latest else "",
        latest_election_date=latest.latest_election_date if latest else "",
        source_names=sorted({p.record.source_name for p in profiles.profiles}),
        source_licenses=sorted({p.record.source_license for p in profiles.profiles}),
        missing_gaps=sum(c.missing_gaps for c in cards),
        verdict=worst_verdict([c.verdict for c in cards]),
    )


# --- 선거구 비교 --------------------------------------------------------------------

COMPARE_SORTS = {
    "name": "선거구명",
    "conservative": "보수 득표 높은 순",
    "gap_nation": "전국 대비 편차",
    "turnout": "투표율 높은 순",
    "swing": "스윙 큰 순",
}


class ComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_id: str
    district_name: str
    agg: AggregateCard
    loaded: int
    expected: int

    @property
    def coverage_text(self) -> str:
        return f"{self.loaded} / {self.expected}"


class ComparisonView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: list[ComparisonRow]
    skipped: list[SkippedDistrict]
    sort: str
    sorts: dict[str, str] = Field(default_factory=lambda: dict(COMPARE_SORTS))
    gap_labels: dict[str, str] = Field(default_factory=lambda: {"nation": "전국"})
    election_type: str = DEFAULT_ELECTION_TYPE.value
    election_type_label: str = ELECTION_TYPE_LABELS[DEFAULT_ELECTION_TYPE]
    election_types: list[tuple[str, str]] = Field(default_factory=election_type_choices)
    verdict: Verdict | None = None

    @property
    def is_empty(self) -> bool:
        return not self.rows


def _row_conservative(row: ComparisonRow) -> float:
    return next((s.pct for s in row.agg.camp_bar if s.camp is Camp.CONSERVATIVE), 0.0)


def _sort_comparison(rows: Sequence[ComparisonRow], key: str) -> list[ComparisonRow]:
    if key == "conservative":
        return sorted(rows, key=lambda r: -_row_conservative(r))
    if key == "turnout":
        return sorted(rows, key=lambda r: -r.agg.turnout)
    if key == "swing":
        return sorted(rows, key=lambda r: -r.agg.swing)
    if key == "gap_nation":
        # 값 없음은 뒤로.
        return sorted(
            rows,
            key=lambda r: (
                r.agg.gaps["nation"].mean is None,
                -(r.agg.gaps["nation"].mean or 0.0),
            ),
        )
    return sorted(rows, key=lambda r: r.district_name)


def build_comparison(
    comparison: ComparisonProfiles, policy: Policy, *, sort: str = "name"
) -> ComparisonView:
    rows: list[ComparisonRow] = []
    for dp in comparison.rows:
        agg = aggregate_profiles(
            dp.profiles,
            label=dp.district.name,
            policy=policy,
            levels=("nation",),
            primary="nation",
        )
        if agg is None:  # comparison.rows 는 비지 않은 것만 담지만 방어적으로
            continue
        rows.append(
            ComparisonRow(
                district_id=dp.district.id,
                district_name=dp.district.name,
                agg=agg,
                loaded=dp.diagnostics.loaded,
                expected=dp.diagnostics.expected,
            )
        )
    ordered = _sort_comparison(rows, sort)
    etype = comparison.election_type

    return ComparisonView(
        rows=ordered,
        skipped=list(comparison.skipped),
        sort=sort if sort in COMPARE_SORTS else "name",
        election_type=etype.value,
        election_type_label=ELECTION_TYPE_LABELS[etype],
        verdict=worst_verdict([r.agg.verdict for r in rows if r.agg.verdict]),
    )


# --- 전국 전체 동 ----------------------------------------------------------------


class NationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cards: list[EmdCard]
    summary_card: AggregateCard | None
    diagnostics: LoadDiagnostics
    sort: str
    sorts: dict[str, str] = Field(default_factory=lambda: dict(SORTS))
    gap_labels: dict[str, str] = Field(default_factory=lambda: {"nation": "전국"})
    trend_note: str = TREND_NOTE
    election_type: str = DEFAULT_ELECTION_TYPE.value
    election_type_label: str = ELECTION_TYPE_LABELS[DEFAULT_ELECTION_TYPE]
    election_types: list[tuple[str, str]] = Field(default_factory=election_type_choices)

    population_total: int = 0
    as_of_months: list[str] = Field(default_factory=list)
    latest_election_id: str = ""
    latest_election_date: str = ""
    source_names: list[str] = Field(default_factory=list)
    source_licenses: list[str] = Field(default_factory=list)
    verdict: Verdict | None = None

    @property
    def is_empty(self) -> bool:
        return not self.cards

    @property
    def shown_text(self) -> str:
        """전국은 "있어야 할 수"의 분모가 없다. 표시한 곳 수만 정직하게 적는다."""
        return f"표시 {self.diagnostics.loaded}곳"


def build_nation_view(nation: NationProfiles, policy: Policy, *, sort: str = "code") -> NationView:
    labels = {"nation": "전국"}
    cards = [
        build_card(p, labels, policy, levels=("nation",), primary="nation") for p in nation.profiles
    ]
    ordered = sort_cards(cards, sort)
    latest = cards[0] if cards else None
    etype = nation.election_type

    return NationView(
        cards=ordered,
        summary_card=aggregate_profiles(
            nation.profiles,
            label="전국 종합",
            policy=policy,
            levels=("nation",),
            primary="nation",
        ),
        diagnostics=nation.diagnostics,
        sort=sort if sort in SORTS else "code",
        election_type=etype.value,
        election_type_label=ELECTION_TYPE_LABELS[etype],
        population_total=sum(c.population_total for c in cards),
        as_of_months=sorted({p.payload.as_of for p in nation.profiles}),
        latest_election_id=latest.latest_election_id if latest else "",
        latest_election_date=latest.latest_election_date if latest else "",
        source_names=sorted({p.record.source_name for p in nation.profiles}),
        source_licenses=sorted({p.record.source_license for p in nation.profiles}),
        verdict=worst_verdict([c.verdict for c in cards]),
    )


# --- 뉴스 원문 목록 --------------------------------------------------------------
#
# 분석기가 없는 화면이다. L1 이 수집한 `news_article` 레코드를 표로 늘어놓고
# 원문 링크로만 보낸다 — 본문 전문은 저장하지 않는다(계약). 여기서 하는 "판단"은
# 정렬과 집계(언론사 분포·지명 빈도)뿐이고, 어떤 기사가 실제로 이 지역구
# 이슈인지 가려내는 일은 L2(issue_ranker)의 몫이다 (제안서 C-003).

NEWS_SORTS = {
    "date": "최신순",
    "publisher": "언론사순",
    "confidence": "지역 관련도순",
}

NEWS_SCOPES = {
    "all": "전체",
    "district": "동·지명 직접만",
}

NEWS_LIMIT = 200
"""한 화면에 그리는 최대 행 수. 첫 수집만으로도 8천 건이라 전부 그리면 페이지가
수 MB 가 된다. 넘으면 잘라 그리고 몇 건 중 몇 건인지 항상 같이 보여준다 (§8)."""

# 검색어가 행정동·통칭을 직접 때렸을 때 L1 이 매기는 신뢰도. 그 아래는 구 단위
# 매칭이다. 상수는 collectors/naver_news 의 CONFIDENCE_DISTRICT 와 같은 값이지만
# L3 가 L1 을 import 하지 않으므로 여기에 다시 적는다 (바뀌면 같이 고친다).
DISTRICT_CONFIDENCE = 0.9


class NewsRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    publisher: str
    published_at: str
    """원본 ISO 문자열. 정렬·감사용."""
    date_label: str
    """ "2026-09-06 14:15". 사람이 읽는 표기."""
    url: str
    places: list[str]
    persons: list[str]
    confidence: float
    is_district_specific: bool
    """행정동·통칭을 직접 언급했는가 (confidence >= 0.9). 구 단위만이면 False."""


def _date_label(published_at: str) -> str:
    """ISO 문자열에서 "YYYY-MM-DD HH:MM" 만. 파싱 실패하면 원본 그대로 (시계를
    쓰지 않는다 — 순수 함수)."""
    head = published_at[:16]
    if len(head) == 16 and head[10] == "T":
        return head.replace("T", " ")
    return published_at


def _news_row(item: NewsItem) -> NewsRow:
    p = item.payload
    conf = item.record.confidence
    return NewsRow(
        title=p.title,
        publisher=p.publisher,
        published_at=p.published_at,
        date_label=_date_label(p.published_at),
        url=p.url,
        places=list(p.mentioned_places),
        persons=list(p.mentioned_persons),
        confidence=conf,
        is_district_specific=conf >= DISTRICT_CONFIDENCE,
    )


def _sort_news(rows: Sequence[NewsRow], key: str) -> list[NewsRow]:
    """모르는 키는 최신순으로 떨어뜨린다."""
    if key == "publisher":
        return sorted(rows, key=lambda r: (r.publisher, _neg_time(r.published_at)))
    if key == "confidence":
        return sorted(rows, key=lambda r: (-r.confidence, _neg_time(r.published_at)))
    return sorted(rows, key=lambda r: _neg_time(r.published_at))


def _neg_time(published_at: str) -> str:
    """내림차순 정렬용 키. ISO 문자열은 사전순 = 시간순이라 부호를 못 붙인다.
    각 문자를 뒤집어 역순 문자열을 만든다."""
    return "".join(chr(0x10FFFF - ord(c)) for c in published_at)


def _tally(values: Sequence[str], *, top: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]


class NewsView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_name: str
    rows: list[NewsRow]
    """스코프·정렬·상한을 모두 적용한 뒤. 화면에 실제로 그려지는 것."""
    diagnostics: NewsDiagnostics
    sort: str
    sorts: dict[str, str] = Field(default_factory=lambda: dict(NEWS_SORTS))
    scope: str = "all"
    scopes: dict[str, str] = Field(default_factory=lambda: dict(NEWS_SCOPES))

    matched: int = 0
    """스코프를 적용한 뒤, 상한을 적용하기 전 건수."""
    limit: int = NEWS_LIMIT
    district_specific_count: int = 0
    """행정동·통칭을 직접 언급한 기사 수 (confidence >= 0.9). **스코프와 무관하게 전체 기준.**"""
    sigungu_only_count: int = 0
    """구 단위 매칭만 된 기사 수. **스코프와 무관하게 전체 기준.**"""
    top_publishers: list[tuple[str, int]] = Field(default_factory=list)
    top_places: list[tuple[str, int]] = Field(default_factory=list)
    top_persons: list[tuple[str, int]] = Field(default_factory=list)
    date_from: str = ""
    date_to: str = ""
    verdict: Verdict | None = None

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def nothing_collected(self) -> bool:
        """수집 자체가 0건. 스코프를 걸어서 0건인 것과 구분한다."""
        return self.diagnostics.shown == 0

    @property
    def truncated(self) -> bool:
        return self.matched > len(self.rows)

    @property
    def shown_text(self) -> str:
        """ "8229건 중 200건 표시". 잘렸으면 잘렸다고 말한다."""
        if self.truncated:
            return f"{self.matched}건 중 {len(self.rows)}건 표시"
        return f"{len(self.rows)}건"

    @property
    def coverage_text(self) -> str:
        """ "동·지명 직접 12건 / 구 단위만 30건". 둘을 갈라 보여준다 —
        구 단위 매칭은 스포츠·연예 기사가 섞인다 (meta.yaml)."""
        return (
            f"동·지명 직접 {self.district_specific_count}건 / 구 단위만 {self.sigungu_only_count}건"
        )

    @property
    def date_range_text(self) -> str:
        if not self.date_from:
            return UNKNOWN_TEXT
        if self.date_from == self.date_to:
            return self.date_from
        return f"{self.date_from} ~ {self.date_to}"


def build_news_view(
    news: DistrictNews,
    policy: Policy,
    *,
    sort: str = "date",
    scope: str = "all",
    limit: int = NEWS_LIMIT,
) -> NewsView:
    sort = sort if sort in NEWS_SORTS else "date"
    scope = scope if scope in NEWS_SCOPES else "all"
    limit = max(1, limit)

    rows = [_news_row(it) for it in news.items]
    dates = sorted(r.date_label for r in rows)

    scoped = [r for r in rows if r.is_district_specific] if scope == "district" else rows
    ordered = _sort_news(scoped, sort)[:limit]

    return NewsView(
        district_name=news.district.name,
        rows=ordered,
        diagnostics=news.diagnostics,
        sort=sort,
        scope=scope,
        matched=len(scoped),
        limit=limit,
        # 관련도 요약은 스코프와 무관하게 항상 전체 기준 — 스코프를 걸어도 분모가 흔들리지 않게.
        district_specific_count=sum(1 for r in rows if r.is_district_specific),
        sigungu_only_count=sum(1 for r in rows if not r.is_district_specific),
        top_publishers=_tally([r.publisher for r in scoped], top=8),
        top_places=_tally([pl for r in scoped for pl in r.places], top=10),
        top_persons=_tally([pn for r in scoped for pn in r.persons], top=10),
        date_from=dates[0] if dates else "",
        date_to=dates[-1] if dates else "",
        # 모든 기사가 같은 kind(news_article)라 판정이 동일하다. 첫 건으로 대표한다.
        verdict=review_with(policy, news.items[0].record) if news.items else None,
    )


# --- 지도 -----------------------------------------------------------------------


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    scale: str
    """`divergent`(중심이 있다) 또는 `sequential`."""
    unit: str
    signed: bool = False
    """부호를 붙일 것인가. 편차만 참이다 — 투표율 82%를 `+82%` 로 쓰면 틀린 표기가 된다."""


METRICS: dict[str, Metric] = {
    "gap_district": Metric(
        key="gap_district",
        label="지역구 대비 보수 편차",
        scale="divergent",
        unit="%p",
        signed=True,
    ),
    "conservative": Metric(
        key="conservative", label="보수 득표율 (최근 선거)", scale="divergent", unit="%"
    ),
    "swing": Metric(key="swing", label="스윙 폭", scale="sequential", unit="%p"),
    "turnout": Metric(key="turnout", label="투표율 (최근 선거)", scale="sequential", unit="%"),
}


def fmt(value: float, metric: Metric, digits: int = 1) -> str:
    return f"{value:+.{digits}f}" if metric.signed else f"{value:.{digits}f}"


DEFAULT_METRIC = "gap_district"

_DIVERGENT_CENTER = {"gap_district": 0.0, "conservative": 50.0}
"""발산 스케일의 중심. 보수 득표율은 50%가 중립이지 0%가 아니다."""


def metric_value(card: EmdCard, key: str) -> float | None:
    if key == "gap_district":
        return card.gaps["district"].value
    if key == "conservative":
        return next((s.pct for s in card.camp_bar if s.camp is Camp.CONSERVATIVE), None)
    if key == "swing":
        return card.swing
    if key == "turnout":
        return card.turnout
    return None


class MapCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geo_code: str
    geo_name: str
    svg_path: str
    label_x: float
    label_y: float
    value: float | None
    text: str
    fill: str
    css_class: str
    title: str


class LegendStop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    fill: str


class MapView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: Metric
    metrics: dict[str, Metric] = Field(default_factory=lambda: dict(METRICS))
    cells: list[MapCell] = Field(default_factory=list)
    view_box: str = ""
    is_real_boundary: bool = False
    v_min: float | None = None
    v_max: float | None = None
    known: int = 0
    total: int = 0
    legend: list[LegendStop] = Field(default_factory=list)
    verdict: Verdict | None = None

    @property
    def has_unknown(self) -> bool:
        return self.known < self.total

    @property
    def range_text(self) -> str:
        """범례에 **실제 min/max 와 분모**를 적는다. 색만 보여주면 크기를 알 수 없다."""
        if self.v_min is None or self.v_max is None:
            return f"{UNKNOWN_TEXT} ({self.total}곳 중 0곳)"
        lo = fmt(self.v_min, self.metric)
        hi = fmt(self.v_max, self.metric)
        return f"{lo} ~ {hi}{self.metric.unit} ({self.total}곳 중 {self.known}곳)"


def divergent_fill(value: float, extent: float) -> str:
    """중심에서 멀수록 진해진다. 보수 쪽은 빨강, 진보 쪽은 파랑."""
    if extent <= 0:
        return "hsl(0 0% 93%)"
    t = max(-1.0, min(1.0, value / extent))
    hue = 8 if t > 0 else 220
    return f"hsl({hue} {20 + abs(t) * 55:.0f}% {94 - abs(t) * 46:.0f}%)"


def sequential_fill(value: float, lo: float, hi: float) -> str:
    if hi <= lo:
        return "hsl(265 25% 90%)"
    t = (value - lo) / (hi - lo)
    return f"hsl(265 {25 + t * 40:.0f}% {94 - t * 48:.0f}%)"


def build_map(view: DistrictView, shapes: ShapeSet, *, metric_key: str = DEFAULT_METRIC) -> MapView:
    metric = METRICS.get(metric_key) or METRICS[DEFAULT_METRIC]
    by_code = {c.geo_code: c for c in view.cards}

    values = {
        shape.geo_code: metric_value(by_code[shape.geo_code], metric.key)
        for shape in shapes.shapes
        if shape.geo_code in by_code
    }
    known = [v for v in values.values() if v is not None]
    lo, hi = (min(known), max(known)) if known else (None, None)

    center = _DIVERGENT_CENTER.get(metric.key, 0.0)
    extent = max((abs(v - center) for v in known), default=0.0)

    cells = []
    for shape in shapes.shapes:
        value = values.get(shape.geo_code)
        if value is None:
            fill, css, text = UNKNOWN_FILL, "cell cell--unknown", UNKNOWN_TEXT
            title = f"{shape.geo_name} — 값이 없다"
        else:
            if metric.scale == "divergent":
                fill = divergent_fill(value - center, extent)
            else:
                fill = sequential_fill(value, lo, hi)
            css = "cell"
            text = fmt(value, metric)
            title = f"{shape.geo_name} {fmt(value, metric, 2)}{metric.unit}"
        cells.append(
            MapCell(
                geo_code=shape.geo_code,
                geo_name=shape.geo_name,
                svg_path=shape.svg_path,
                label_x=shape.label_x,
                label_y=shape.label_y,
                value=value,
                text=text,
                fill=fill,
                css_class=css,
                title=title,
            )
        )

    return MapView(
        metric=metric,
        cells=cells,
        view_box=shapes.view_box,
        is_real_boundary=shapes.is_real_boundary,
        v_min=lo,
        v_max=hi,
        known=len(known),
        total=len(shapes.shapes),
        legend=_legend(metric, lo, hi, center, extent, unknown=len(known) < len(cells)),
        verdict=view.verdict,
    )


def _legend(
    metric: Metric,
    lo: float | None,
    hi: float | None,
    center: float,
    extent: float,
    *,
    unknown: bool,
) -> list[LegendStop]:
    """값 없음은 **별도 항목**이다. 색 눈금 어딘가에 끼워 넣으면 수치처럼 읽힌다."""
    stops: list[LegendStop] = []
    if lo is not None and hi is not None:
        for v in (lo, (lo + hi) / 2, hi):
            stops.append(
                LegendStop(
                    label=f"{fmt(v, metric)}{metric.unit}",
                    fill=(
                        divergent_fill(v - center, extent)
                        if metric.scale == "divergent"
                        else sequential_fill(v, lo, hi)
                    ),
                )
            )
    if unknown or lo is None:
        stops.append(LegendStop(label=f"{UNKNOWN_TEXT} 값 없음", fill=UNKNOWN_FILL))
    return stops
