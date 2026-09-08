"""투표율 편차의 순수 계산. 레코드도 파일도 모른다.

제안서: docs/proposals/A-004-turnout-gap.md
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tally:
    """한 동, 한 회차의 개표 집계. `election_result` payload 에서 뽑아온 것."""

    election_id: str
    geo_code: str
    geo_name: str
    eligible_voters: int
    total_votes: int

    @property
    def turnout(self) -> float:
        if self.eligible_voters <= 0:
            raise ValueError(f"{self.geo_name}({self.election_id}): 선거인수가 0 이하다")
        return self.total_votes / self.eligible_voters


def baseline_turnout(tallies: list[Tally]) -> float:
    """한 회차의 선거구 전체 투표율.

    **동별 투표율의 단순 평균이 아니라 가중 합이다.** 인구가 다른 동을 같은 무게로
    세면 작은 동이 기준선을 흔든다 — 선거구 전체 투표율은 정의상 총 투표수 / 총 선거인수다.
    """
    eligible = sum(t.eligible_voters for t in tallies)
    if eligible <= 0:
        raise ValueError("선거인수 합이 0이다")
    return sum(t.total_votes for t in tallies) / eligible


def slope(values: list[float]) -> float:
    """회차 순번(0,1,2...)에 대한 최소제곱 기울기. 편차가 벌어지는지 좁혀지는지.

    2개 미만이면 0.0 — 기울기를 말할 수 없다. 회차 간격이 균등하지 않지만(대선 5년,
    총선 4년) 순번을 쓰는 이유는 "몇 번째 선거인가"가 관심사이지 경과 연수가 아니기
    때문이다. 균등 간격 가정을 넣으면 보궐 회차가 들어올 때 의미가 흔들린다.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom == 0:
        return 0.0
    return sum((i - mean_x) * (y - mean_y) for i, y in enumerate(values)) / denom


def election_date(election_id: str) -> str:
    """`2025-06-03-presidential` → `2025-06-03`.

    `election_id` 는 선거일 + 계열로 만들어진다(`nec_archive`). 앞 10자를 그대로 쓰되
    모양이 다르면 조용히 넘어가지 않고 터뜨린다 — 날짜가 틀리면 시계열 정렬이 무너진다.
    """
    head = election_id[:10]
    parts = head.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"election_id 에서 날짜를 읽을 수 없다: {election_id!r}")
    return head
