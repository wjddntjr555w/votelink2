"""통·반 단위 응답을 행정동 × 10년 연령대 × 성별로 재집계한다.

원 데이터는 통/반까지 쪼개져 있고 연령은 10세 단위 11구간(0,10,...,100)으로
남녀 각각 나온다. 계약은 행정동 단위 10년 구간(80세 이상은 하나로 합침)을
요구하므로 여기서 접는다.

필드명은 실제 API 응답(2026-09-01 확인, admmCd=1111054000/종로구 삼청동 조회)
에서 그대로 가져왔다. 이 모듈은 순수 함수만 담는다 (네트워크·파일 접근 없음).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from votelink.contract.enums import AgeBand, Sex

# --- 출처 필드명 -------------------------------------------------------------
# 실제 응답 필드명이 다르면 **여기만** 고친다. 파싱 로직은 건드리지 않는다.

FIELD_SIDO = "ctpvNm"
FIELD_SIGUNGU = "sggNm"
FIELD_EMD = "dongNm"
FIELD_TOTAL = "totNmprCnt"

# 응답이 행정동코드를 주면 그것을 geo_code 로 쓴다 (이름으로 되돌려 찾지 않는다).
# 실제 응답의 필드명은 admmCd. 다른 데이터셋을 위해 후보를 여럿 둔다.
FIELD_ADMM_CODE_CANDIDATES = ("admmCd", "행정기관코드", "행정구역코드", "adm_cd", "admCd")

SEX_FIELD_PREFIX: dict[Sex, str] = {Sex.MALE: "male", Sex.FEMALE: "feml"}

# 계약의 10년 구간 -> 출처의 연령 구간(10세 단위 시작 나이).
# 응답은 0,10,20,...,100 총 11구간을 준다. 80세 이상은 세 구간(80/90/100)을 하나로 접는다.
AGE_BAND_SOURCE: dict[AgeBand, tuple[int, ...]] = {
    AgeBand.A00_09: (0,),
    AgeBand.A10_19: (10,),
    AgeBand.A20_29: (20,),
    AgeBand.A30_39: (30,),
    AgeBand.A40_49: (40,),
    AgeBand.A50_59: (50,),
    AgeBand.A60_69: (60,),
    AgeBand.A70_79: (70,),
    AgeBand.A80_PLUS: (80, 90, 100),
}


def source_field(sex: Sex, age_start: int) -> str:
    """예: (MALE, 20) -> 'male20AgeNmprCnt'."""
    return f"{SEX_FIELD_PREFIX[sex]}{age_start}AgeNmprCnt"


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


def find_admm_code(row: dict[str, Any]) -> str:
    """행에서 행정동코드를 찾는다. 없으면 빈 문자열 (이름 매핑으로 넘어간다)."""
    for field in FIELD_ADMM_CODE_CANDIDATES:
        value = str(row.get(field, "")).strip()
        if value:
            return value
    return ""


class EmdAggregate:
    """행정동 하나의 집계 결과."""

    def __init__(self, sido: str, sigungu: str, emd: str, admm_code: str = "") -> None:
        self.sido = sido
        self.sigungu = sigungu
        self.emd = emd
        self.admm_code = admm_code
        self.cells: dict[tuple[AgeBand, Sex], int] = defaultdict(int)
        self.reported_total = 0
        self.rows = 0

    @property
    def full_name(self) -> str:
        """'서울특별시 송파구 풍납1동'. 행정동코드 매핑의 조회 키(코드가 없을 때만 씀)."""
        return " ".join(part for part in (self.sido, self.sigungu, self.emd) if part)

    @property
    def breakdown_total(self) -> int:
        return sum(self.cells.values())

    def add_row(self, row: dict[str, Any]) -> None:
        self.rows += 1
        if not self.admm_code:
            self.admm_code = find_admm_code(row)
        self.reported_total += _to_int(row.get(FIELD_TOTAL))
        for band, ages in AGE_BAND_SOURCE.items():
            for sex in Sex:
                for age in ages:
                    self.cells[(band, sex)] += _to_int(_require(row, source_field(sex, age)))

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
    """통·반 행들을 행정동 단위로 접는다. 입력 순서와 무관하게 같은 결과를 낸다.

    행정동코드가 있으면 그것으로 묶는다 — 이름은 표기가 흔들리지만 코드는 안 흔들린다.
    """
    groups: dict[str, EmdAggregate] = {}
    for row in rows:
        names = (
            str(_require(row, FIELD_SIDO)).strip(),
            str(_require(row, FIELD_SIGUNGU)).strip(),
            str(_require(row, FIELD_EMD)).strip(),
        )
        code = find_admm_code(row)
        key = code or "|".join(names)
        if key not in groups:
            groups[key] = EmdAggregate(*names, admm_code=code)
        groups[key].add_row(row)
    return [groups[k] for k in sorted(groups, key=lambda k: groups[k].full_name)]
