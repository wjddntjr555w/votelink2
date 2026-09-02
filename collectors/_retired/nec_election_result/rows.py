"""CSV 행 → 행정동별 집계. 순수 함수만 둔다 (파일·네트워크 없음).

선관위 개표결과 CSV는 세로로 긴 형태다. 한 행이 (투표구 × 항목) 하나를 담고,
`후보자` 컬럼에 후보명과 집계항목명이 **섞여** 들어온다.

    시도명 | 선거구명 | 법정읍면동명 | 투표구명   | 후보자              | 득표수
    서울   | 송파구갑 | 풍납1동      | 풍납1동제1투 | 선거인수            | 2,481
    서울   | 송파구갑 | 풍납1동      | 풍납1동제1투 | 투표수              | 1,702
    서울   | 송파구갑 | 풍납1동      | 풍납1동제1투 | 더불어민주당 조재희  |   812
    서울   | 송파구갑 | 풍납1동      | 풍납1동제1투 | 국민의힘 박정훈      |   848
    서울   | 송파구갑 | 풍납1동      | 풍납1동제1투 | 무효 투표수          |    42

그래서 하는 일은 둘이다.
  1. 투표구 행을 행정동으로 접는다 (동 소계 행이 없어 이중계상 위험이 없다 — 실제 확인함)
  2. `후보자` 값이 집계항목명이면 집계로, 아니면 후보 득표로 가른다

컬럼명은 파일마다 다르므로(총선 `법정읍면동명` / 대선 `읍면동명`) 이름을 박지 않고
meta.yaml 의 후보군에서 고른다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

_NUM_RE = re.compile(r"[,\s]")


class ColumnMissing(KeyError):
    """기대한 컬럼이 파일에 없다. 출처 형식이 바뀌었다."""


def to_int(value: object) -> int:
    """'1,234' 처럼 콤마가 섞인 숫자 문자열을 int 로 만든다."""
    if value is None or value == "":
        return 0
    return int(_NUM_RE.sub("", str(value)))


def pick_column(header: Iterable[str], candidates: Iterable[str], role: str) -> str:
    """후보 이름들 중 실제로 파일에 있는 첫 컬럼을 고른다."""
    header = list(header)
    for name in candidates:
        if name in header:
            return name
    raise ColumnMissing(
        f"'{role}' 컬럼을 찾지 못했다. 후보: {list(candidates)} / 파일 컬럼: {header}"
    )


def split_party(label: str) -> tuple[str, str]:
    """'더불어민주당 조재희' -> ('더불어민주당', '조재희'). 무소속도 같은 형태다.

    정당명에는 공백이 없다(확인함). 첫 공백만 나눠서 이름 쪽 공백은 보존한다.
    """
    party, _, candidate = label.partition(" ")
    if not candidate:
        raise ValueError(f"'정당 후보명' 형태가 아니다: {label!r}")
    return party.strip(), candidate.strip()


@dataclass
class EmdTally:
    """행정동 하나의 개표 집계."""

    emd: str
    eligible_voters: int = 0
    total_votes: int = 0
    invalid_votes: int = 0
    abstained: int = 0
    candidates: dict[str, int] = field(default_factory=dict)

    def results(self) -> list[dict[str, object]]:
        """계약의 payload.results 형태로. 득표 많은 순으로 안정 정렬한다."""
        rows = [
            {"party": p, "candidate": c, "votes": v}
            for label, v in self.candidates.items()
            for p, c in [split_party(label)]
        ]
        return sorted(rows, key=lambda r: (-r["votes"], r["candidate"]))

    def check(self) -> None:
        """계약이 강제하는 산식을 미리 확인해 어느 동이 왜 틀렸는지 알려준다.

        계약 모델도 같은 검증을 하지만, 거기서 터지면 '합계가 안 맞는다'까지만 나온다.
        여기서 먼저 보면 어느 행정동인지가 메시지에 남는다.
        """
        counted = sum(self.candidates.values()) + self.invalid_votes
        if counted != self.total_votes:
            raise ValueError(
                f"{self.emd}: 후보 득표합+무효({counted}) != 투표수({self.total_votes})"
            )
        if self.total_votes + self.abstained != self.eligible_voters:
            raise ValueError(
                f"{self.emd}: 투표수+기권({self.total_votes + self.abstained}) "
                f"!= 선거인수({self.eligible_voters})"
            )


def tally_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    emd_col: str,
    item_col: str,
    count_col: str,
    keep: set[str],
    agg_items: Mapping[str, str],
) -> dict[str, EmdTally]:
    """투표구 행들을 행정동별 집계로 접는다.

    keep 에 없는 행정동은 **버린다.** 거소·선상투표, 관외사전투표, 국외부재자투표처럼
    행정동이 아닌 항목이 같은 컬럼에 섞여 오는데, 이들은 오류가 아니라 대상이 아닐 뿐이라
    격리하지 않는다 (격리하면 격리율이 임계를 넘어 수집 전체가 실패한다).
    """
    by_item = {label: attr for attr, label in agg_items.items()}
    tallies: dict[str, EmdTally] = {}

    for row in rows:
        emd = (row.get(emd_col) or "").strip()
        if emd not in keep:
            continue
        tally = tallies.get(emd) or tallies.setdefault(emd, EmdTally(emd=emd))
        label = (row.get(item_col) or "").strip()
        count = to_int(row.get(count_col))
        attr = by_item.get(label)
        if attr:
            setattr(tally, attr, getattr(tally, attr) + count)
        elif label:
            tally.candidates[label] = tally.candidates.get(label, 0) + count

    return tallies
