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

from votelink.contract.enums import AgeBand, Camp, Trend
from votelink.contract.payloads import LeanPoint
from votelink.reference.compliance import Policy, ReviewStatus, Verdict, review_with
from votelink.reference.districts import District
from votelink.web.loader import DistrictProfiles, EmdProfile, LoadDiagnostics
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
    gap_summary: GapSummary
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


def build_card(profile: EmdProfile, district: District, policy: Policy) -> EmdCard:
    payload = profile.payload
    series = payload.lean_series
    latest = series[-1]
    labels = gap_labels(district)
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
            level: GapCell.of(getattr(latest, f"gap_{level}"), labels[level])
            for level in GAP_LEVELS
        },
        gap_summary=GapSummary.of([p.gap_district for p in series]),
        conservative_spark=sparkline(
            [p.camp_share[Camp.CONSERVATIVE] for p in series], election_ids
        ),
        gap_spark=sparkline([p.gap_district for p in series], election_ids),
        age_bars=age_bars(payload.age_mix),
        sex_ratio=payload.sex_ratio,
        # 이 payload 의 유일한 비-퍼센트 값이다. % 를 붙이지 않는다.
        sex_ratio_text=f"{payload.sex_ratio:.2f}",
        population_total=payload.population_total,
        confidence=profile.record.confidence,
        missing_gaps=sum(
            1 for p in series for level in GAP_LEVELS if getattr(p, f"gap_{level}") is None
        ),
        evidence_count=len(profile.record.derived_from),
        evidence_ids=list(profile.record.derived_from),
        verdict=review_with(policy, profile.record),
    )


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
        return sorted(
            cards,
            key=lambda c: (not c.gaps["district"].known, -(c.gaps["district"].value or 0.0)),
        )
    return sorted(cards, key=lambda c: c.geo_code)


class DistrictView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_name: str
    cards: list[EmdCard]
    diagnostics: LoadDiagnostics
    sort: str
    sorts: dict[str, str] = Field(default_factory=lambda: dict(SORTS))
    trend_note: str = TREND_NOTE

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


def build_view(profiles: DistrictProfiles, policy: Policy, *, sort: str = "code") -> DistrictView:
    district = profiles.district
    cards = [build_card(p, district, policy) for p in profiles.profiles]
    ordered = sort_cards(cards, sort)
    latest = cards[0] if cards else None

    return DistrictView(
        district_name=district.name,
        cards=ordered,
        diagnostics=profiles.diagnostics,
        sort=sort if sort in SORTS else "code",
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
