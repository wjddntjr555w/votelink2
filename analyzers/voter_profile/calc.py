"""순수 계산. 레코드도 파일도 모르고, 숫자만 다룬다.

여기 있는 함수는 전부 결정론이다. 같은 입력이면 같은 출력이 나온다 —
`compute` 가 순수 함수여야 한다는 규약(docs/30-analysis-spec.md)이 여기서 지켜진다.

**단위 규약: 비율은 전부 퍼센트(%)다.** payload 와 같다.
"""

from __future__ import annotations

from collections.abc import Sequence

from votelink.contract.enums import AgeBand, Camp, Trend


class CampTally:
    """한 선거·한 지역의 진영별 득표 집계."""

    __slots__ = ("valid", "votes")

    def __init__(self) -> None:
        self.votes: dict[Camp, int] = dict.fromkeys(Camp, 0)
        self.valid = 0

    def add(self, camp: Camp, votes: int) -> None:
        self.votes[camp] += votes
        self.valid += votes

    def merge(self, other: CampTally) -> None:
        for camp, v in other.votes.items():
            self.votes[camp] += v
        self.valid += other.valid

    def share(self) -> dict[Camp, float]:
        """진영별 득표 %. 분모는 유효투표수다.

        선거인수로 나누지 않는다 — 그러면 투표율 변화가 성향 변화로 오독된다.
        """
        if self.valid <= 0:
            raise ValueError("유효투표수가 0이다. 득표율을 낼 수 없다")
        return {camp: v * 100.0 / self.valid for camp, v in self.votes.items()}

    @property
    def conservative_pct(self) -> float:
        return self.votes[Camp.CONSERVATIVE] * 100.0 / self.valid


def slope(values: Sequence[float]) -> float:
    """최소제곱 직선의 기울기 (단위: 값/회).

    x 는 0,1,2… 즉 '몇 번째 선거인가'다. 실제 연도 간격을 쓰지 않는 이유:
    대선 주기가 5년으로 일정하고, 총선이 섞이면 간격이 의미를 잃기 때문이다.
    """
    n = len(values)
    if n < 2:
        raise ValueError(f"기울기를 내려면 점이 2개 이상 필요하다 (받은 것: {n})")
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den


def classify_trend(gaps: Sequence[float], *, threshold: float, window: int) -> Trend:
    """**지역구 편차** 시계열에서 성향 이동 방향을 판정한다.

    절대 득표율이 아니라 편차를 받는 이유 (실측):
    최근 3회가 2017(탄핵 직후 보수 저점) → 2022 → 2025 라 절대 기울기로는
    송파갑 9개 동이 **전부** conservative_shift 로 나온다. 동별 차이를 말해야 하는
    지표가 9/9 같은 값이면 정보량이 0이다. 지역구 평균을 빼면 전국 공통 흐름이
    상쇄되고 동별 상대 이동만 남는다.
    """
    recent = list(gaps)[-window:]
    if len(recent) < 2:
        return Trend.STABLE
    s = slope(recent)
    if s > threshold:
        return Trend.CONSERVATIVE_SHIFT
    if s < -threshold:
        return Trend.PROGRESSIVE_SHIFT
    return Trend.STABLE


def swing_of(conservative_pcts: Sequence[float]) -> float:
    """보수 득표율 시계열의 진폭 (%p).

    표준편차가 아니라 최댓값−최솟값을 쓴다. 8점짜리 표본에서 표준편차는 해석하기
    어렵고, 캠프가 알고 싶은 것은 '이 동이 얼마나 흔들리는가'의 폭이다.
    여기서는 편차가 아니라 **절대값**이 맞다 — 스윙보터 규모는 전국 흐름에 함께
    흔들리는 것까지 포함해야 실제 크기가 나온다.
    """
    if not conservative_pcts:
        raise ValueError("빈 시계열의 진폭은 정의되지 않는다")
    return max(conservative_pcts) - min(conservative_pcts)


def age_mix_of(breakdown: list[dict]) -> tuple[dict[AgeBand, float], float, int]:
    """population payload 의 breakdown -> (연령대별 %, 남/여 비, 총원).

    출처가 특정 연령대를 아예 빼고 주는 경우가 있어 **없는 구간은 0.0 으로 채운다**
    (payload 계약이 모든 AgeBand 키를 요구한다).
    """
    by_age: dict[AgeBand, int] = dict.fromkeys(AgeBand, 0)
    male = female = 0
    for cell in breakdown:
        band = AgeBand(cell["age_band"])
        count = int(cell["count"])
        by_age[band] += count
        if cell["sex"] == "M":
            male += count
        else:
            female += count

    total = male + female
    if total <= 0:
        raise ValueError("인구 총원이 0이다. 프로파일을 만들 수 없다")
    if female <= 0:
        raise ValueError("여성 인구가 0이다. 성비를 낼 수 없다")

    mix = {band: n * 100.0 / total for band, n in by_age.items()}
    return mix, male / female, total
