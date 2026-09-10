"""타깃 우선순위의 순수 계산. 레코드도 파일도 모르는 함수들.

전부 결정론적이다 — 난수·시계 없음. 정규화는 **선거구·계열 그룹 안에서만** 한다
(전국 공통 흐름은 입력 지표에서 이미 상쇄됐다, docs/30-analysis-spec.md §9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Row:
    """한 행정동 × 계열의 원시 요인. `fill_indices` 가 지수를 채운다."""

    geo_code: str
    geo_name: str
    election_type: str
    as_of: str
    observed_at: datetime
    """이 행정동 segment_profile 의 observed_at. 파생 레코드가 그대로 물려받는다."""
    population_total: int
    swing: float
    """conservative 시계열 최댓값 − 최솟값 (%p). segment_profile.swing 그대로."""
    margin: float
    """최신 회차 |보수 − 진보| 격차 (%p). 작을수록 경합."""
    conservative_share: float
    progressive_share: float
    deficit: float | None
    """max(0, -mean_gap). turnout_gap 입력이 없으면 None."""
    evidence: list[str]
    has_turnout: bool

    # fill_indices 가 채운다
    size_index: float = 0.0
    volatility_index: float = 0.0
    competitiveness_index: float = 0.0
    turnout_headroom: float = 0.0
    attention_score: float = 0.0
    rank: int = 0
    group_size: int = 0
    segment_note: str = ""

    _debug: dict = field(default_factory=dict)


def minmax(value: float, lo: float, hi: float) -> float:
    """[lo, hi] 를 0~100 으로. 구간이 0이면(모든 값이 같으면) 50 — 중립.

    n≈9 에서 한 그룹의 값이 전부 같은 일이 실제로 생긴다. 그때 그 요인은 순위에
    기여하지 않아야 하므로 전원 50 을 준다 (변별력 0 이라는 신호이기도 하다).
    """
    if hi - lo <= 0:
        return 50.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def fill_indices(rows: list[Row], weights: dict[str, float]) -> None:
    """그룹(같은 선거구·계열) 안에서 네 지수를 정규화하고 attention_score·rank·note 를 채운다.

    rows 를 제자리에서 수정한다. weights 는 size/volatility/competitiveness/turnout_headroom
    네 키의 합이 1.0 이어야 한다.
    """
    if not rows:
        return

    pops = [float(r.population_total) for r in rows]
    swings = [r.swing for r in rows]
    margins = [r.margin for r in rows]
    deficits = [r.deficit for r in rows if r.deficit is not None]

    p_lo, p_hi = min(pops), max(pops)
    s_lo, s_hi = min(swings), max(swings)
    m_lo, m_hi = min(margins), max(margins)
    d_lo, d_hi = (min(deficits), max(deficits)) if deficits else (0.0, 0.0)

    for r in rows:
        r.size_index = minmax(float(r.population_total), p_lo, p_hi)
        r.volatility_index = minmax(r.swing, s_lo, s_hi)
        # 격차가 작을수록 경합 → 뒤집는다.
        r.competitiveness_index = 100.0 - minmax(r.margin, m_lo, m_hi)
        # turnout_gap 입력이 없는 동은 동원 여유를 0 으로 둔다 — 여유가 있다는 근거가
        # 없다. (없다 ≠ 0 이지만, 우선순위를 부풀리지 않는 쪽으로.)
        r.turnout_headroom = minmax(r.deficit, d_lo, d_hi) if r.deficit is not None else 0.0

        r.attention_score = (
            weights["size"] * r.size_index
            + weights["volatility"] * r.volatility_index
            + weights["competitiveness"] * r.competitiveness_index
            + weights["turnout_headroom"] * r.turnout_headroom
        )
        r._debug = {
            "pop_range": (p_lo, p_hi),
            "swing_range": (s_lo, s_hi),
            "margin_range": (m_lo, m_hi),
            "deficit_range": (d_lo, d_hi),
        }

    # 순위: attention_score 내림차순, 동점은 geo_code 로 갈라 결정론 유지.
    order = sorted(rows, key=lambda r: (-r.attention_score, r.geo_code))
    for i, r in enumerate(order, start=1):
        r.rank = i
        r.group_size = len(rows)


def classify(r: Row, cuts: dict[str, float]) -> str:
    """중립 유형 라벨. 순서가 곧 우선순위 — 먼저 맞는 것을 준다.

    렌즈(우리 진영)는 안 씌운다. "battleground"는 어느 편이 봐도 battleground 다.

      swing_battleground : 변동성도 높고 접전이다 — 설득이 표를 바꾼다
      mobilization_target: 투표율 여유가 크고 어느 정도 접전 — 동원이 표를 만든다
      safe              : 한쪽이 확실히 앞선다 (접전 아님)
      persuasion_ground : 접전이지만 변동성·GOTV 여지가 지렛대가 아니다 — 막판·공중전
      low_stakes        : 그 밖. 접전도 아니고 변동성·여유도 없다
    """
    vol_hi = cuts["volatility_hi"]
    comp_hi = cuts["competitiveness_hi"]
    comp_mid = cuts["competitiveness_mid"]
    comp_lo = cuts["competitiveness_lo"]
    turn_hi = cuts["turnout_headroom_hi"]

    if r.volatility_index >= vol_hi and r.competitiveness_index >= comp_hi:
        return "swing_battleground"
    if r.has_turnout and r.turnout_headroom >= turn_hi and r.competitiveness_index >= comp_mid:
        return "mobilization_target"
    if r.competitiveness_index < comp_lo:
        return "safe"
    if r.competitiveness_index >= comp_hi:
        return "persuasion_ground"
    return "low_stakes"
