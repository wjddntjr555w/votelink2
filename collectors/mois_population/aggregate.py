"""통·반 단위 응답을 행정동 × 10년 연령대 × 성별로 재집계한다.

원 데이터는 통/반까지 쪼개져 있고 연령은 만0~9세 …
만100세이상까지 나온다. 계약은 행정동 단위 10년 구간을 요구하므로 여기서 접는다.

이 모듈은 순수 함수만 담는다 (네트워크·파일 접근 없음).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from votelink.contract.enums import AgeBand, Sex

# --- 출처 필드명 -------------------------------------------------------------
# 실제 응답 필드명이 다르면 **여기만** 고친다. 파싱 로직은 건드리지 않는다.

FIELD_SIDO = "시도명"
FIELD_SIGUNGU = "시군구명"
FIELD_EMD = "행정동명"
FIELD_TOTAL = "총인구수"

SEX_SUFFIX: dict[Sex, str] = {Sex.MALE: "남자", Sex.FEMALE: "여자"}

# 계약의 10년 구간 -> 출처의 연령 구간 라벨(들).
# 80세 이상은 출처가 세 구간으로 쪼개 놓았으므로 하나로 접는다.
AGE_BAND_SOURCE: dict[AgeBand, tuple[str, ...]] = {
    AgeBand.A00_09: ("만0~9세",),
    AgeBand.A10_19: ("만10~19세",),
    AgeBand.A20_29: ("만20~29세",),
    AgeBand.A30_39: ("만30~39세",),
    AgeBand.A40_49: ("만40~49세",),
    AgeBand.A50_59: ("만50~59세",),
    AgeBand.A60_69: ("만60~69세",),
    AgeBand.A70_79: ("만70~79세",),
    AgeBand.A80_PLUS: ("만80~89세", "만90~99세", "만100세이상"),
}


class SourceFieldMissing(KeyError):
    """응답에 기대한 필드가 없다. 출처 형식이 바뀌었거나 매핑이 틀렸다."""


def _to_int(value: Any) -> int:
    """'1,234' / '' / None / 1234 를 모두 정수로."""
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value
    return int(str(value).replace(",", "").strip())


def _require(row: dict[str, Any], field: str) -> Any:
    if field not in row:
        raise SourceFieldMissing(
            f"응답에 '{field}' 필드가 없다. 있는 필드: {', '.join(list(row)[:12])}"
        )
    return row[field]


class EmdAggregate:
    """행정동 하나의 집계 결과."""

    def __init__(self, sido: str, sigungu: str, emd: str) -> None:
        self.sido = sido
        self.sigungu = sigungu
        self.emd = emd
        self.cells: dict[tuple[AgeBand, Sex], int] = defaultdict(int)
        self.reported_total = 0
        self.rows = 0

    @property
    def full_name(self) -> str:
        """'서울특별시 송파구 풍납1동'. 행정동코드 매핑의 조회 키."""
        return " ".join(part for part in (self.sido, self.sigungu, self.emd) if part)

    @property
    def breakdown_total(self) -> int:
        return sum(self.cells.values())

    def add_row(self, row: dict[str, Any]) -> None:
        self.rows += 1
        self.reported_total += _to_int(row.get(FIELD_TOTAL))
        for band, labels in AGE_BAND_SOURCE.items():
            for sex, suffix in SEX_SUFFIX.items():
                for label in labels:
                    self.cells[(band, sex)] += _to_int(_require(row, f"{label}{suffix}"))

    def breakdown(self) -> list[dict[str, Any]]:
        """계약의 breakdown 형태. 0인 칸도 남긴다 (없는 것과 0은 다르다)."""
        return [
            {"age_band": str(band), "sex": str(sex), "count": self.cells[(band, sex)]}
            for band in AgeBand
            for sex in Sex
        ]

    def check_total(self) -> None:
        """출처가 말하는 총인구와 연령별 합이 다르면 파싱이 틀린 것이다."""
        if self.reported_total and self.reported_total != self.breakdown_total:
            raise ValueError(
                f"{self.full_name}: 총인구수({self.reported_total})와 "
                f"연령별 합({self.breakdown_total})이 다르다. "
                "연령 구간 필드명이 누락됐을 가능성이 높다"
            )


def aggregate_rows(rows: list[dict[str, Any]]) -> list[EmdAggregate]:
    """통·반 행들을 행정동 단위로 접는다. 입력 순서와 무관하게 같은 결과를 낸다."""
    groups: dict[tuple[str, str, str], EmdAggregate] = {}
    for row in rows:
        key = (
            str(_require(row, FIELD_SIDO)).strip(),
            str(_require(row, FIELD_SIGUNGU)).strip(),
            str(_require(row, FIELD_EMD)).strip(),
        )
        if key not in groups:
            groups[key] = EmdAggregate(*key)
        groups[key].add_row(row)
    return [groups[k] for k in sorted(groups)]
