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

from pydantic import BaseModel, ConfigDict, Field, computed_field

from votelink.contract.enums import AgeBand, Camp, ElectionType, IssueTrend, Trend
from votelink.contract.payloads import LeanPoint
from votelink.reference.compliance import Compliance, ReviewStatus, Verdict, review_with
from votelink.reference.districts import District
from votelink.web.lens import Lens
from votelink.web.loader import (
    CandidateMentionShare,
    ComparisonProfiles,
    DistrictNews,
    DistrictProfiles,
    EmdProfile,
    LoadDiagnostics,
    LocalIssue,
    NationProfiles,
    NewsDiagnostics,
    NewsItem,
    NewsPulse,
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


class Sparkline(BaseModel):
    """Chart.js 라인 차트에 그대로 먹이는 데이터셋. **None 은 점을 찍지 않고 선을 끊는다**

    (템플릿에서 Chart.js `spanGaps: false` + 데이터포인트 `null` 로 재현한다).
    좌표 계산은 여기서 끝난다 — 템플릿은 여전히 산술을 하지 않는다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    labels: list[str] = Field(default_factory=list)
    values: list[float | None] = Field(default_factory=list)
    y_min: float
    y_max: float
    breaks: int = 0
    """값이 없어 건너뛴 점의 개수."""

    @property
    def is_empty(self) -> bool:
        return all(v is None for v in self.values)


def sparkline(values: Sequence[float | None], labels: Sequence[str]) -> Sparkline:
    known = [v for v in values if v is not None]
    lo, hi = (min(known), max(known)) if known else (0.0, 1.0)
    return Sparkline(
        labels=list(labels),
        values=list(values),
        y_min=lo,
        y_max=hi,
        breaks=sum(1 for v in values if v is None),
    )


def _recent_change(values: Sequence[float | None]) -> float | None:
    """가장 최근 두 **알려진** 값의 차 — "직전 조사 대비" 숫자.

    선거가 1회뿐이거나 최근 두 회차 중 하나가 결측이면 None(모른다)이다.
    비교 대상을 건너뛰어 이어붙이지 않는다 — 스파크라인이 선을 끊는 것과 같은 정신(§8).
    """
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return None
    return known[-1] - known[-2]


# --- 카드 조각 -------------------------------------------------------------------


class BarSlice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    camp: Camp
    label: str
    pct: float
    offset: float
    css_class: str
    ours: bool = False
    """렌즈가 있을 때 이 조각이 우리 진영인가 (`P-001` §5). 렌즈가 없으면 전부 False."""


class AgeBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    band: AgeBand
    pct: float
    height_pct: float


def camp_bar(point: LeanPoint, lens: Lens | None = None) -> list[BarSlice]:
    """진영 구성 누적 막대. 계약(`_check_shares`)이 4개 키를 전부 보장한다.

    렌즈를 주면 우리 진영 조각에 표시가 붙는다. **숫자는 바뀌지 않는다** — 같은
    공용 계산 결과를 읽는 방식만 달라진다 (`P-001` §5).
    """
    slices: list[BarSlice] = []
    offset = 0.0
    for camp in CAMP_ORDER:
        pct = point.camp_share[camp]
        ours = lens is not None and lens.is_ours(camp)
        slices.append(
            BarSlice(
                camp=camp,
                label=CAMP_LABELS[camp],
                pct=pct,
                offset=offset,
                css_class=f"camp camp--{camp.value}" + (" camp--ours" if ours else ""),
                ours=ours,
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


class LensRead(BaseModel):
    """공용 숫자를 캠프 관점으로 읽은 것. **원래 숫자를 바꾸지 않는다.**

    `ours` 는 우리 진영 득표, `theirs` 는 나머지 전부다. 나머지를 한 덩어리로 세는
    이유: 이 시스템은 개별 상대 후보의 득표를 모른다 — `party_lineage.yaml` 이
    후보를 진영으로 환원한 뒤의 값만 있다. "가장 큰 상대 진영"을 따로 세면 3자
    구도에서 오해를 부른다(중도가 크면 보수가 약한 것처럼 보인다).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ours: float
    theirs: float
    lead: float
    """ours − theirs (%p). 음수면 열세다."""

    in_territory: bool = True
    """이 동이 캠프 관할인가. 관할 밖 동도 보여주되 그 사실을 표시한다."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ahead(self) -> bool:
        return self.lead > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lead_text(self) -> str:
        return f"{self.lead:+.1f}%p"

    @classmethod
    def of(cls, point: LeanPoint, lens: Lens, geo_code: str | None = None) -> LensRead:
        ours = point.camp_share[lens.lineage]
        theirs = sum(v for c, v in point.camp_share.items() if c is not lens.lineage)
        return cls(
            ours=ours,
            theirs=theirs,
            lead=ours - theirs,
            in_territory=lens.covers(geo_code),
        )


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
    recent_change: GapCell
    """직전 조사(선거) 대비 보수 득표율 변화. 선거가 1회뿐이면 모른다(None) — GapCell 이
    0과 절대 같아 보이지 않게 한다. **진영 판단이 아니라 크기 표시다** — camp 색으로
    "어느 방향"만 말하고, 좋다/나쁘다 채색은 렌즈가 있을 때만 별도로 한다."""
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
    lens_read: LensRead | None = None
    """렌즈가 있을 때만 채워진다. 없으면 카드는 지금까지처럼 진영 중립이다."""


def build_card(
    profile: EmdProfile,
    labels: dict[str, str],
    compliance: Compliance,
    *,
    levels: Sequence[str] = GAP_LEVELS,
    primary: str = "district",
    lens: Lens | None = None,
) -> EmdCard:
    """`labels` 는 편차 기준 단위의 이름 dict (`gap_labels(district)` 또는 `{"nation": "전국"}`).
    `levels` 는 이 카드가 보여줄 편차 단위, `primary` 는 요약·스파크라인의 기준 단위."""
    payload = profile.payload
    series = payload.lean_series
    latest = series[-1]
    election_ids = [p.election_id for p in series]
    con_values = [p.camp_share[Camp.CONSERVATIVE] for p in series]

    return EmdCard(
        geo_code=profile.geo_code,
        geo_name=profile.geo_name,
        latest_election_id=latest.election_id,
        latest_election_date=latest.election_date,
        election_count=len(series),
        camp_bar=camp_bar(latest, lens),
        lens_read=LensRead.of(latest, lens, profile.geo_code) if lens else None,
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
        recent_change=GapCell.of(_recent_change(con_values), "직전 조사"),
        conservative_spark=sparkline(con_values, election_ids),
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
        verdict=review_with(compliance, profile.record),
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
    lens_read: LensRead | None = None
    """렌즈가 있을 때만. 집계 자체가 근사라 이 읽기도 근사다 (`approx` 배지 참조)."""
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
    recent_change: GapCell
    """직전 조사 대비 보수 득표율 변화(가중 근사 시계열 기준).
    `EmdCard.recent_change` 와 같은 정신."""
    conservative_spark: Sparkline
    progressive_spark: Sparkline
    """"최근 판세 변화" 차트의 두 번째 선. 보수와 같은 시계열, 진보 득표율 기준."""
    centrist_spark: Sparkline
    """세 번째 선(중도). "최근 N회 조사 기준" 패널이 보수·진보·중도 3행을 보이는 데 쓴다."""
    turnout_spark: Sparkline
    """투표 의향(투표율) 시계열 — 트렌드 차트의 "투표 의향" 탭용."""
    gap_spark: Sparkline
    camp_recent_change: dict[str, GapCell]
    """진영별(`Camp.value` 키) 직전 조사 대비 변화. `recent_change`(보수 전용, 하위호환)와
    같은 계산을 보수·진보·중도 전부에 적용한 것 — "최근 N회 조사 기준" 패널의 델타 열.
    `Camp` enum이 아니라 `str` 로 키를 두는 이유: 템플릿(Jinja) 전역에 enum이 없어서
    `camp.value` 문자열로 찾는 편이 더 안전하다."""
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
    compliance: Compliance,
    levels: Sequence[str] = GAP_LEVELS,
    primary: str = "district",
    lens: Lens | None = None,
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
    prog_series: list[float | None] = []
    centrist_series: list[float | None] = []
    gap_series: list[float | None] = []
    turnout_series: list[float | None] = []
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
            prog_series.append(None)
            centrist_series.append(None)
            gap_series.append(None)
            turnout_series.append(None)
            continue
        voters = [pop * pt.turnout / 100.0 for pt, pop in rows]
        camp = _weighted_camp([(pt, w) for (pt, _), w in zip(rows, voters, strict=True)])
        popsum = sum(pop for _, pop in rows) or 1
        turnout = sum(pt.turnout * pop for pt, pop in rows) / popsum
        con_series.append(camp[Camp.CONSERVATIVE])
        prog_series.append(camp[Camp.PROGRESSIVE])
        centrist_series.append(camp[Camp.CENTRIST])
        turnout_series.append(min(turnout, 100.0))

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
        camp_bar=camp_bar(latest_point, lens),
        # 집계 카드의 렌즈 읽기도 근사다 — camp_share 자체가 가중 근사이기 때문이다
        # (approx 배지가 그 사실을 이미 말한다). 관할 판정은 동 단위가 아니라 생략한다.
        lens_read=LensRead.of(latest_point, lens) if lens else None,
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
        recent_change=GapCell.of(_recent_change(con_series), "직전 조사"),
        conservative_spark=sparkline(con_series, election_ids),
        progressive_spark=sparkline(prog_series, election_ids),
        centrist_spark=sparkline(centrist_series, election_ids),
        turnout_spark=sparkline(turnout_series, election_ids),
        gap_spark=sparkline(gap_series, election_ids),
        camp_recent_change={
            Camp.CONSERVATIVE.value: GapCell.of(_recent_change(con_series), "직전 조사"),
            Camp.PROGRESSIVE.value: GapCell.of(_recent_change(prog_series), "직전 조사"),
            Camp.CENTRIST.value: GapCell.of(_recent_change(centrist_series), "직전 조사"),
        },
        approx=True,
        approx_reason=_APPROX_REASON,
        verdict=worst_verdict([review_with(compliance, p.record) for p in profiles]),
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


# --- 상황 요약 (대시보드 상단) -----------------------------------------------------
#
# "상황실" 헤더가 읽을 큰 숫자 몇 개. 전부 이미 계산된 필드(camp_bar·turnout·
# recent_change)를 다시 포장할 뿐이다 — 새로운 통계를 만들지 않는다.


class Situation(BaseModel):
    """대시보드 최상단 큰 숫자들. `AggregateCard` 를 읽는 방식만 바꾼다 — 값은 그대로다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    leading_label: str
    """"보수 우세" 또는(렌즈가 있으면) "○○ 캠프 우세/열세"."""
    leading_lead_text: str
    leading_css_class: str
    """색은 판단이 아니라 신호다: 렌즈가 없으면 진영색(`text-camp--*`, 어느 쪽도 아님),
    렌즈가 있으면 우세/열세 신호색(`text-lens--ahead/behind`, 진영색이 아니다)."""
    leading_pct_text: str
    turnout_text: str
    recent_change: GapCell
    avg_confidence_text: str
    watch_count: int


def build_situation(
    summary: AggregateCard | None,
    watch_count: int,
    avg_confidence: float,
    lens: Lens | None = None,
) -> Situation | None:
    if summary is None:
        return None

    if lens and summary.lens_read:
        lr = summary.lens_read
        leading_label = f"{lens.label} 캠프 {'우세' if lr.ahead else '열세'}"
        leading_lead_text = lr.lead_text
        leading_css_class = "text-lens--ahead" if lr.ahead else "text-lens--behind"
        leading_pct_text = f"{lr.ours:.1f}%"
    else:
        ordered = sorted(summary.camp_bar, key=lambda s: -s.pct)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else top
        leading_label = f"{top.label} 우세"
        leading_lead_text = f"{top.pct - second.pct:+.1f}%p"
        leading_css_class = f"text-camp--{top.camp.value}"
        leading_pct_text = f"{top.pct:.1f}%"

    return Situation(
        leading_label=leading_label,
        leading_lead_text=leading_lead_text,
        leading_css_class=leading_css_class,
        leading_pct_text=leading_pct_text,
        turnout_text=f"{summary.turnout:.1f}%",
        recent_change=summary.recent_change,
        avg_confidence_text=f"{avg_confidence:.2f}",
        watch_count=watch_count,
    )


# --- 지역별 상태 배지 (지역별 판세 표) ---------------------------------------------
#
# "주의/강세/안정" 3단계. 새 판정을 만드는 게 아니라 이미 있는 두 값
# (watchlist 소속 여부, gap_district 크기)을 사람이 읽는 배지로 옮길 뿐이다.

STRONG_GAP_THRESHOLD = 10.0
"""이 %p 를 넘으면 "강세" 배지. 표시용 문턱값이라 여기 한 곳에만 둔다."""


class RegionStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    css_class: str


def build_region_status(
    cards: Sequence[EmdCard], watch_codes: Sequence[str]
) -> dict[str, RegionStatus]:
    watch = set(watch_codes)
    result: dict[str, RegionStatus] = {}
    for c in cards:
        cell = c.gaps.get("district")
        value = cell.value if cell is not None and cell.known else None
        if c.geo_code in watch:
            # "주의"는 진영과 무관한 신호다 — 변동이 컸다는 뜻이지 어느 진영에 나쁘다는
            # 뜻이 아니다. 색도 진영색이 아니라 경고색(text-warn)을 쓴다.
            result[c.geo_code] = RegionStatus(label="주의", css_class="text-warn")
        elif value is not None and value >= STRONG_GAP_THRESHOLD:
            result[c.geo_code] = RegionStatus(label="강세", css_class="text-camp--conservative")
        elif value is not None and value <= -STRONG_GAP_THRESHOLD:
            result[c.geo_code] = RegionStatus(label="강세", css_class="text-camp--progressive")
        else:
            result[c.geo_code] = RegionStatus(label="안정", css_class="")
    return result


CONTESTED_MARGIN = 5.0
"""1·2위 진영 점유율 차이가 이 %p 이내면 "경합"(지역별 판세 표의 필터 탭용)."""


def region_category(cards: Sequence[EmdCard]) -> dict[str, str]:
    """지역별 판세 표의 필터 탭(전체/보수 우세/진보 우세/경합) 값.

    새 판정이 아니라 이미 계산된 `camp_bar`(진영별 점유율)를 다시 읽을 뿐이다.
    표시(필터링)는 클라이언트 JS가 하고, 서버는 어느 범주인지만 계산해 둔다.
    """
    result: dict[str, str] = {}
    for c in cards:
        ordered = sorted(c.camp_bar, key=lambda s: -s.pct)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else top
        if top.pct - second.pct <= CONTESTED_MARGIN:
            result[c.geo_code] = "contested"
        else:
            result[c.geo_code] = top.camp.value
    return result


# --- 후보자 비교 -------------------------------------------------------------------
#
# 렌즈(캠프 관점)와 로스터(후보 이름·정당)가 둘 다 있을 때만 만든다. 사진·인지도·
# 호감도는 수집하지 않는 값이라 만들지 않는다 — 있는 데이터(지지율·최근 변화·
# 지역 강세)만 비교한다.


class CandidateComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ours_name: str
    ours_party: str | None
    theirs_name: str
    support_ours: float
    support_theirs: float
    recent_change_ours: GapCell
    recent_change_theirs: GapCell
    strong_regions_ours: int
    strong_regions_theirs: int
    """`lens_read.ahead` 인 동의 수 대 나머지. 관할 밖 동도 그대로 센다(§ EmdCard.lens_read
    가 이미 `in_territory` 로 그 사실을 표시하지, 여기서 다시 거르지 않는다)."""


def build_candidate_comparison(
    lens: Lens,
    opponent_name: str,
    cards: Sequence[EmdCard],
    summary: AggregateCard | None,
) -> CandidateComparison | None:
    if summary is None or summary.lens_read is None:
        return None
    lr = summary.lens_read
    theirs_camp_change = summary.camp_recent_change
    # "상대"는 우리 진영을 뺀 전부라(P-001 §5), 상대 진영 하나만 짚을 수 없다.
    # 그래서 "상대 변화"는 우리 진영 변화의 반대 부호로 근사하지 않고, 안 다루는
    # 게 정직하다 — 대신 "우리" 변화만 정확히 보여준다.
    ours_change = theirs_camp_change.get(lens.lineage.value, GapCell.of(None, "직전 조사"))
    strong_ours = sum(1 for c in cards if c.lens_read and c.lens_read.ahead)
    strong_theirs = sum(1 for c in cards if c.lens_read and not c.lens_read.ahead)
    return CandidateComparison(
        ours_name=lens.label,
        ours_party=lens.party,
        theirs_name=opponent_name,
        support_ours=lr.ours,
        support_theirs=lr.theirs,
        recent_change_ours=ours_change,
        recent_change_theirs=GapCell.of(None, "직전 조사"),
        strong_regions_ours=strong_ours,
        strong_regions_theirs=strong_theirs,
    )


# --- 주의 지역 (watchlist) ---------------------------------------------------------


def build_watchlist(cards: Sequence[EmdCard], *, top: int = 3) -> list[EmdCard]:
    """변동이 가장 큰 동을 추린다. **최근 조사 대비 변화가 없으면(선거 1회뿐) 편차
    크기로 대신한다** — 데이터가 얕다고 "볼 게 없다"고 조용히 넘기지 않는다."""
    with_change = [c for c in cards if c.recent_change.known]
    if with_change:
        return sorted(with_change, key=lambda c: -abs(c.recent_change.value or 0.0))[:top]
    known_gap = [c for c in cards if c.gaps.get("district") and c.gaps["district"].known]
    return sorted(known_gap, key=lambda c: -abs(c.gaps["district"].value or 0.0))[:top]


# --- 캠페인 인사이트 ---------------------------------------------------------------
#
# 이미 계산된 숫자를 사람이 읽는 문장으로 옮길 뿐이다. **새 통계·판정을 만들지
# 않는다** — 그건 L2(분석기)의 일이고, 여기서 하면 계층 무지(00-overview.md §3)가
# 깨진다. 데이터가 뒷받침하지 않는 문장(예: 연령별 투표 의향 추세처럼 시계열이
# 없는 값)은 만들지 않는다.


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tone: str
    """"warn" 또는 "note" — 중요도 신호일 뿐 진영 판단이 아니다."""
    icon: str
    title: str
    detail: str


def build_insights(
    cards: Sequence[EmdCard],
    summary: AggregateCard | None,
    watchlist: Sequence[EmdCard],
    diagnostics: LoadDiagnostics,
    avg_confidence: float,
) -> list[Insight]:
    insights: list[Insight] = []

    if summary is not None and summary.recent_change.known:
        change = summary.recent_change.value or 0.0
        direction = "상승" if change > 0 else "하락" if change < 0 else "변화 없음"
        insights.append(
            Insight(
                tone="note",
                icon="▲" if change > 0 else "▼" if change < 0 else "●",
                title=f"보수 득표율 직전 조사 대비 {direction}",
                detail=f"{summary.label} 집계에서 {change:+.1f}%p 움직였다.",
            )
        )

    if watchlist:
        top = watchlist[0]
        cell = top.gaps.get("district")
        detail = (
            f"직전 조사 대비 {top.recent_change.text}%p 움직였다."
            if top.recent_change.known
            else (
                f"{top.gap_summary_label} 평균 대비 편차 {cell.text}%p 로 가장 크다."
                if cell is not None
                else "가장 큰 변동을 보인 동이다."
            )
        )
        insights.append(
            Insight(tone="warn", icon="⚠", title=f"{top.geo_name} 변동 주의", detail=detail)
        )

    if not diagnostics.is_complete:
        insights.append(
            Insight(
                tone="warn",
                icon="⚠",
                title="행정동 데이터 결측",
                detail=(
                    f"행정동 {diagnostics.expected}곳 중 {diagnostics.loaded}곳만 분석 결과가 있다."
                ),
            )
        )

    if avg_confidence and avg_confidence < 0.8:
        insights.append(
            Insight(
                tone="note",
                icon="●",
                title="분석 신뢰도가 낮다",
                detail=f"평균 신뢰도 {avg_confidence:.2f} — 기준선 결측이 있을 수 있다.",
            )
        )

    return insights


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
    situation: Situation | None = None
    """상단 "판세" 헤더의 큰 숫자들. `summary_card` 를 읽는 방식만 바꾼다."""
    watchlist: list[EmdCard] = Field(default_factory=list)
    """변동이 가장 큰 동 상위 몇 곳 — `build_watchlist()`. `cards` 의 부분집합이라
    새 데이터를 만들지 않는다."""
    region_status: dict[str, RegionStatus] = Field(default_factory=dict)
    """지역별 판세 표의 상태 배지. `geo_code` 로 찾는다."""
    region_category: dict[str, str] = Field(default_factory=dict)
    """지역별 판세 표의 필터 탭(전체/보수 우세/진보 우세/경합) 값. `geo_code` 로 찾는다."""
    insights: list[Insight] = Field(default_factory=list)
    avg_confidence: float = 0.0
    """카드 신뢰도의 단순 평균. `population_total` 처럼 이미 있는 필드들의 집계다."""

    lens: Lens | None = None
    """어느 캠프의 눈으로 보는가 (`P-001` §5). `None` 이면 진영 중립."""

    last_updated: str = ""
    """이 화면이 읽은 레코드 중 가장 최근 `ingested_at` (KST, 분 단위).

    호스팅에서는 운영자가 매일 수집하므로 캠프가 어제 본 숫자가 오늘 달라질 수 있다.
    **왜 달라졌는지**(참조 데이터 변경 등)는 변경이 일어나는 곳에서만 붙일 수 있어
    P-003(운영자 콘솔)의 몫이다. 여기서는 언제 바뀌었는지까지 말한다 (`P-001` §11).
    """

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

    # `@computed_field` — Jinja(`view.is_empty`)와 JSON API(`/api/d/{id}`) 양쪽에서
    # 같은 값을 봐야 한다. 평범한 `@property` 는 `.model_dump()`에 안 잡힌다
    # (Verdict.shows_content 도 같은 이유로 일부러 그대로 뒀다 — 프런트가
    # `status !== "blocked"` 로 다시 계산한다. 이 셋은 화면이 직접 여러 곳에서
    # 읽어야 해서 다르게 판단했다).
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_empty(self) -> bool:
        return not self.cards

    @computed_field  # type: ignore[prop-decorator]
    @property
    def coverage_text(self) -> str:
        """ "9 / 9". 둘 다 보여준다 — 다르면 결측이다."""
        return f"{self.diagnostics.loaded} / {self.diagnostics.expected}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def population_month_text(self) -> str:
        return " · ".join(self.population_months) or UNKNOWN_TEXT


def worst_verdict(verdicts: Sequence[Verdict]) -> Verdict | None:
    """가장 무거운 판정. 하나라도 blocked 면 헤더도 blocked 다 (fail-closed)."""
    if not verdicts:
        return None
    return max(verdicts, key=lambda v: _STATUS_SEVERITY[v.status])


def last_ingested(profiles: Sequence[EmdProfile]) -> str:
    """읽은 레코드 중 가장 최근 수집 시각. 없으면 빈 문자열."""
    stamps = [p.record.ingested_at for p in profiles]
    return max(stamps).strftime("%Y-%m-%d %H:%M") if stamps else ""


def build_view(
    profiles: DistrictProfiles,
    compliance: Compliance,
    *,
    sort: str = "code",
    election_type: ElectionType = DEFAULT_ELECTION_TYPE,
    lens: Lens | None = None,
) -> DistrictView:
    district = profiles.district
    labels = gap_labels(district)
    cards = [build_card(p, labels, compliance, lens=lens) for p in profiles.profiles]
    ordered = sort_cards(cards, sort)
    latest = cards[0] if cards else None
    summary_card = aggregate_profiles(
        profiles.profiles, label=f"{district.name} 종합", compliance=compliance, lens=lens
    )
    avg_confidence = sum(c.confidence for c in cards) / len(cards) if cards else 0.0
    watchlist = build_watchlist(cards)

    return DistrictView(
        district_name=district.name,
        cards=ordered,
        diagnostics=profiles.diagnostics,
        sort=sort if sort in SORTS else "code",
        gap_labels=labels,
        election_type=election_type.value,
        election_type_label=ELECTION_TYPE_LABELS[election_type],
        summary_card=summary_card,
        situation=build_situation(summary_card, len(watchlist), avg_confidence, lens),
        watchlist=watchlist,
        region_status=build_region_status(cards, [c.geo_code for c in watchlist]),
        region_category=region_category(cards),
        insights=build_insights(
            cards, summary_card, watchlist, profiles.diagnostics, avg_confidence
        ),
        avg_confidence=avg_confidence,
        population_total=sum(c.population_total for c in cards),
        population_months=sorted({p.payload.population_month for p in profiles.profiles}),
        as_of_months=sorted({p.payload.as_of for p in profiles.profiles}),
        latest_election_id=latest.latest_election_id if latest else "",
        latest_election_date=latest.latest_election_date if latest else "",
        source_names=sorted({p.record.source_name for p in profiles.profiles}),
        source_licenses=sorted({p.record.source_license for p in profiles.profiles}),
        missing_gaps=sum(c.missing_gaps for c in cards),
        verdict=worst_verdict([c.verdict for c in cards]),
        lens=lens,
        last_updated=last_ingested(profiles.profiles),
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
    comparison: ComparisonProfiles,
    compliance: Compliance,
    *,
    sort: str = "name",
    lens: Lens | None = None,
) -> ComparisonView:
    rows: list[ComparisonRow] = []
    for dp in comparison.rows:
        agg = aggregate_profiles(
            dp.profiles,
            label=dp.district.name,
            compliance=compliance,
            levels=("nation",),
            primary="nation",
            lens=lens,
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


def build_nation_view(
    nation: NationProfiles, compliance: Compliance, *, sort: str = "code", lens: Lens | None = None
) -> NationView:
    labels = {"nation": "전국"}
    cards = [
        build_card(p, labels, compliance, levels=("nation",), primary="nation", lens=lens)
        for p in nation.profiles
    ]
    ordered = sort_cards(cards, sort)
    latest = cards[0] if cards else None
    etype = nation.election_type

    return NationView(
        cards=ordered,
        summary_card=aggregate_profiles(
            nation.profiles,
            label="전국 종합",
            compliance=compliance,
            levels=("nation",),
            primary="nation",
            lens=lens,
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
    "oldest": "오래된순",
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
    summary: str
    """출처가 준 3문장 스니펫. 표에는 안 그리지만 키워드 검색이 여기까지 훑는다 —
    지명·현안어가 제목보다 요약에 더 자주 있다 (예: "트램"은 제목 0건·요약 수백 건)."""
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
        summary=p.summary,
        places=list(p.mentioned_places),
        persons=list(p.mentioned_persons),
        confidence=conf,
        is_district_specific=conf >= DISTRICT_CONFIDENCE,
    )


def _sort_news(rows: Sequence[NewsRow], key: str) -> list[NewsRow]:
    """모르는 키는 최신순으로 떨어뜨린다."""
    if key == "oldest":
        return sorted(rows, key=lambda r: r.published_at)
    if key == "publisher":
        return sorted(rows, key=lambda r: (r.publisher, _neg_time(r.published_at)))
    if key == "confidence":
        return sorted(rows, key=lambda r: (-r.confidence, _neg_time(r.published_at)))
    return sorted(rows, key=lambda r: _neg_time(r.published_at))


def _news_matches(row: NewsRow, needle: str) -> bool:
    """제목·언론사·언급 지명·인물 어디든 부분 문자열로 들어 있으면 참.
    형태소 분석이 아니라 substring 이다 (naver_news/text.py:match_terms 와 같은 정신)."""
    if not needle:
        return True
    hay = " ".join([row.title, row.summary, row.publisher, *row.places, *row.persons])
    return needle in hay


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
    query: str = ""
    """키워드 검색어 (있으면). 제목·언론사·언급 지명·인물에 substring 매칭."""

    matched: int = 0
    """검색·스코프를 적용한 뒤, 상한을 적용하기 전 건수."""
    limit: int = NEWS_LIMIT
    district_specific_count: int = 0
    """행정동·통칭을 직접 언급한 기사 수 (confidence >= 0.9). 검색어를 적용한 뒤,
    **스코프와는 무관한** 전체 기준 (스코프를 좁혀도 분모가 흔들리지 않게)."""
    sigungu_only_count: int = 0
    """구 단위 매칭만 된 기사 수. 검색어 적용 뒤, **스코프와는 무관한** 전체 기준."""
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
    compliance: Compliance,
    *,
    sort: str = "date",
    scope: str = "all",
    query: str = "",
    limit: int = NEWS_LIMIT,
) -> NewsView:
    sort = sort if sort in NEWS_SORTS else "date"
    scope = scope if scope in NEWS_SCOPES else "all"
    query = query.strip()
    limit = max(1, limit)

    all_rows = [_news_row(it) for it in news.items]
    # 검색어 먼저. 그 다음 스코프. 요약 집계·분모는 '검색 결과' 기준으로 본다 —
    # 검색은 스코프보다 앞선 필터이고, 무엇을 찾는 중인지가 화면의 주제가 되기 때문이다.
    rows = [r for r in all_rows if _news_matches(r, query)]
    dates = sorted(r.date_label for r in rows)

    scoped = [r for r in rows if r.is_district_specific] if scope == "district" else rows
    ordered = _sort_news(scoped, sort)[:limit]

    return NewsView(
        district_name=news.district.name,
        rows=ordered,
        diagnostics=news.diagnostics,
        sort=sort,
        scope=scope,
        query=query,
        matched=len(scoped),
        limit=limit,
        # 관련도 요약은 (검색 뒤) 스코프와 무관하게 — 스코프를 걸어도 분모가 흔들리지 않게.
        district_specific_count=sum(1 for r in rows if r.is_district_specific),
        sigungu_only_count=sum(1 for r in rows if not r.is_district_specific),
        top_publishers=_tally([r.publisher for r in scoped], top=8),
        top_places=_tally([pl for r in scoped for pl in r.places], top=10),
        top_persons=_tally([pn for r in scoped for pn in r.persons], top=10),
        date_from=dates[0] if dates else "",
        date_to=dates[-1] if dates else "",
        # 모든 기사가 같은 kind(news_article)라 판정이 동일하다. 첫 건으로 대표한다.
        verdict=review_with(compliance, news.items[0].record) if news.items else None,
    )


# --- 뉴스 펄스 카드 (대시보드) ------------------------------------------------
#
# news_pulse 레코드 1건 → 카드 한 장. 주별 기사량 막대 + 최근 주 급증 여부 +
# 상위 언론사·지명. spike 판정은 news_pulse 가 계산한 값을 그대로 쓴다 —
# L3 는 L2 임계값을 다시 읽지 않는다 (계층 무지).


class PulseBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: str
    count: int
    district_specific: int
    height_pct: float
    """창 내 최대 주 대비 높이 %. 0건이면 0 — 막대를 아예 안 그린다."""
    spike: bool
    title: str


class PulseCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: str
    window_weeks: int
    total_articles: int
    bars: list[PulseBar]
    latest_count: int
    latest_district_specific: int
    latest_spike: bool
    latest_z_text: str
    """ "z +2.8" 또는 "판정 불가" (히스토리 부족)."""
    spike_weeks: int
    backfill_distorted: bool
    top_publishers: list[tuple[str, int]] = Field(default_factory=list)
    top_places: list[tuple[str, int]] = Field(default_factory=list)
    top_persons: list[tuple[str, int]] = Field(default_factory=list)
    verdict: Verdict | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def latest_week(self) -> str:
        return self.bars[-1].week_start if self.bars else UNKNOWN_TEXT


def build_pulse_card(pulse: NewsPulse | None, compliance: Compliance) -> PulseCard | None:
    if pulse is None:
        return None
    p = pulse.payload
    weekly = p.weekly
    peak = max((w.article_count for w in weekly), default=0) or 1

    bars = [
        PulseBar(
            week_start=w.week_start,
            count=w.article_count,
            district_specific=w.district_specific_count,
            height_pct=round(w.article_count / peak * 100, 1),
            spike=w.spike,
            title=(
                f"{w.week_start} — {w.article_count}건"
                f" (동·지명 직접 {w.district_specific_count})"
                + (f" · 급증 z{w.spike_z:+.1f}" if w.spike and w.spike_z is not None else "")
            ),
        )
        for w in weekly
    ]
    last = weekly[-1]
    return PulseCard(
        as_of=p.as_of,
        window_weeks=p.window_weeks,
        total_articles=p.total_articles,
        bars=bars,
        latest_count=last.article_count,
        latest_district_specific=last.district_specific_count,
        latest_spike=last.spike,
        latest_z_text=(f"z {last.spike_z:+.1f}" if last.spike_z is not None else "판정 불가"),
        spike_weeks=sum(1 for w in weekly if w.spike),
        backfill_distorted=p.backfill_distorted,
        top_publishers=[(t.term, t.count) for t in p.top_publishers],
        top_places=[(t.term, t.count) for t in p.top_places],
        top_persons=[(t.term, t.count) for t in p.top_persons],
        verdict=review_with(compliance, pulse.record),
    )


# --- 이슈 보드 카드 (대시보드) ------------------------------------------------
#
# local_issue 레코드 1건 → 카드 한 장. 상위 카테고리를 recency_score 막대로,
# trend 는 issue_ranker 가 계산한 값을 그대로 쓴다 (L3 는 L2 임계값을 다시 읽지 않는다).
# unclassified 를 숨기지 않는다 — 비율이 크면 어휘집 보강 신호다.

ISSUE_TREND_LABELS = {
    IssueTrend.RISING: "↑ 뜨는",
    IssueTrend.FLAT: "→ 유지",
    IssueTrend.FALLING: "↓ 지는",
}

ISSUE_BOARD_TOP_N = 6
"""카드에 세우는 카테고리 수. payload 는 이미 recency_score 내림차순이다."""


class IssueBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    label: str
    article_count: int
    share: float
    recency_score: float
    trend: IssueTrend
    trend_label: str
    width_pct: float
    """창 내 최대 recency_score 대비 막대 폭 %."""
    headlines: list[str]
    places: list[tuple[str, int]]
    title: str
    """막대 hover 텍스트."""


class IssueBoardCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: str
    window_weeks: int
    total_articles: int
    unclassified_count: int
    unclassified_pct: float
    lexicon_version: str
    backfill_distorted: bool
    bars: list[IssueBar]
    verdict: Verdict | None = None


def build_issue_board(issue: LocalIssue | None, compliance: Compliance) -> IssueBoardCard | None:
    if issue is None:
        return None
    p = issue.payload
    top = p.issues[:ISSUE_BOARD_TOP_N]
    peak = max((i.recency_score for i in top), default=0.0) or 1.0

    bars = [
        IssueBar(
            category=i.category,
            label=i.label,
            article_count=i.article_count,
            share=i.share,
            recency_score=i.recency_score,
            trend=i.trend,
            trend_label=ISSUE_TREND_LABELS[i.trend],
            width_pct=round(i.recency_score / peak * 100, 1),
            headlines=list(i.sample_headlines),
            places=[(t.term, t.count) for t in i.top_places],
            title=(
                f"{i.label} — 기사 {i.article_count}건 · 분류분의 {i.share:.0f}% · "
                f"{ISSUE_TREND_LABELS[i.trend]}"
            ),
        )
        for i in top
    ]
    return IssueBoardCard(
        as_of=p.as_of,
        window_weeks=p.window_weeks,
        total_articles=p.total_articles,
        unclassified_count=p.unclassified_count,
        unclassified_pct=(
            round(p.unclassified_count * 100.0 / p.total_articles, 1) if p.total_articles else 0.0
        ),
        lexicon_version=p.lexicon_version,
        backfill_distorted=p.backfill_distorted,
        bars=bars,
        verdict=review_with(compliance, issue.record),
    )


# --- 후보 언급 비교 카드 (대시보드) ---------------------------------------------
#
# candidate_mention_share 레코드 1건 → 카드 한 장. news_pulse/local_issue 카드와
# 같은 정신이다 — 분석기가 이미 계산한 share_pct/wow_change_pct 를 그대로 옮겨
# 그린다(L3 는 계산하지 않는다). 진영색은 `lineage` 로 입힌다.
# 제안서: docs/proposals/A-006-candidate-mention-share.md


class CandidateWeekBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: str
    count: int
    height_pct: float
    """이 카드 안 모든 후보·모든 주를 통틀어 최댓값 대비 %. 후보 간 막대 높이가
    서로 비교 가능해야 하므로 후보별 최댓값이 아니라 카드 전체 최댓값을 쓴다."""
    share_pct: float | None
    wow_change_pct: float | None
    title: str


class CandidateSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    party: str
    lineage: Camp
    lineage_label: str
    is_ours: bool
    total_articles: int
    latest_count: int
    latest_share_pct: float | None
    latest_wow_change_pct: float | None
    bars: list[CandidateWeekBar]


class CandidateMentionHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    week_start: str
    wow_change_pct: float
    direction: str
    """`up` 또는 `down`."""
    text: str


class CandidateMentionCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: str
    window_weeks: int
    total_articles: int
    backfill_distorted: bool
    candidates: list[CandidateSeries]
    highlight: CandidateMentionHighlight | None
    verdict: Verdict | None = None


def build_candidate_mention_card(
    cms: CandidateMentionShare | None, compliance: Compliance
) -> CandidateMentionCard | None:
    if cms is None:
        return None
    p = cms.payload
    peak = max((w.article_count for c in p.candidates for w in c.weekly), default=0) or 1

    series: list[CandidateSeries] = []
    for c in p.candidates:
        bars = [
            CandidateWeekBar(
                week_start=w.week_start,
                count=w.article_count,
                height_pct=round(w.article_count / peak * 100, 1),
                share_pct=w.share_pct,
                wow_change_pct=w.wow_change_pct,
                title=(
                    f"{w.week_start} — {c.name} {w.article_count}건"
                    + (f" · 점유 {w.share_pct:.0f}%" if w.share_pct is not None else "")
                ),
            )
            for w in c.weekly
        ]
        last = c.weekly[-1]
        series.append(
            CandidateSeries(
                name=c.name,
                party=c.party,
                lineage=c.lineage,
                lineage_label=CAMP_LABELS[c.lineage],
                is_ours=c.is_ours,
                total_articles=c.total_articles,
                latest_count=last.article_count,
                latest_share_pct=last.share_pct,
                latest_wow_change_pct=last.wow_change_pct,
                bars=bars,
            )
        )

    # 급변 하이라이트: 카드 전체에서 |wow_change_pct| 가 가장 큰 (후보, 주) 하나.
    # None(전주 0건이라 정의 안 됨)은 후보 대상에서 제외한다.
    biggest: tuple[str, float, str] | None = None
    for c in p.candidates:
        for w in c.weekly:
            if w.wow_change_pct is None:
                continue
            if biggest is None or abs(w.wow_change_pct) > abs(biggest[1]):
                biggest = (c.name, w.wow_change_pct, w.week_start)

    highlight = None
    if biggest is not None:
        name, pct, week = biggest
        direction = "up" if pct > 0 else "down"
        verb = "급증" if direction == "up" else "급감"
        highlight = CandidateMentionHighlight(
            name=name,
            week_start=week,
            wow_change_pct=pct,
            direction=direction,
            text=f"{name} 언급 {abs(pct):.0f}% {verb} ({week} 주)",
        )

    return CandidateMentionCard(
        as_of=p.as_of,
        window_weeks=p.window_weeks,
        total_articles=p.total_articles,
        backfill_distorted=p.backfill_distorted,
        candidates=series,
        highlight=highlight,
        verdict=review_with(compliance, cms.record),
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
