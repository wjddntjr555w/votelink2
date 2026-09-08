"""캠프 설정 파일의 스키마 — `camp.yaml` · `election.yaml` · `candidates.yaml`.

제안서: `docs/proposals/P-001-camp-data-isolation.md` §7·§8.

**축이 둘이다.** 캠프는 선거가 끝나도 남고, 선거는 주기로 그 안에 들어간다.
가르는 기준은 하나 — 다음 선거에 바뀔 수 있으면 주기별이다. 구청장에 나갔다가
다음엔 시의원에 나갈 수 있고 당적도 바뀐다. 그래서 관할도 진영도 주기별이다.

이 모델들은 **파일의 모양만 안다.** 관할 행정동이 실재하는지 같은 참조 검증은
`loader.py` 가 한다 — 검증에 `districts.yaml` 을 읽어야 하고, 모델이 I/O 를 하면
테스트에서 떼어낼 수 없기 때문이다.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from votelink.contract.enums import Camp, ElectionType
from votelink.contract.models import GEO_CODE_DIGITS


class Office(StrEnum):
    """후보가 노리는 직위.

    `ElectionType`(계약 enum)은 "어느 선거 계열인가"만 말한다. 지방선거 하나에
    다섯 직위가 들어 있어서 계열만으로는 캠프를 특정할 수 없다 — 서울시장 후보와
    송파구의원 후보는 같은 `local` 이지만 관할도 상대도 전혀 다르다.

    레코드에는 들어가지 않는다. 캠프 설정에만 사는 값이라 계약이 아니라 여기 둔다.
    """

    PRESIDENT = "president"  # 대통령
    NATIONAL_ASSEMBLY = "national_assembly"  # 국회의원
    METRO_HEAD = "metro_head"  # 광역단체장 (시·도지사)
    BASIC_HEAD = "basic_head"  # 기초단체장 (시장·군수·구청장)
    METRO_COUNCIL = "metro_council"  # 광역의원
    BASIC_COUNCIL = "basic_council"  # 기초의원
    EDUCATION = "education"  # 교육감


LOCAL_OFFICES = frozenset(
    {
        Office.METRO_HEAD,
        Office.BASIC_HEAD,
        Office.METRO_COUNCIL,
        Office.BASIC_COUNCIL,
        Office.EDUCATION,
    }
)

_OFFICES_BY_TYPE: dict[ElectionType, frozenset[Office]] = {
    ElectionType.PRESIDENTIAL: frozenset({Office.PRESIDENT}),
    ElectionType.NATIONAL_ASSEMBLY: frozenset({Office.NATIONAL_ASSEMBLY}),
    ElectionType.LOCAL: LOCAL_OFFICES,
    # 재보궐은 어느 직위든 될 수 있다.
    ElectionType.BY_ELECTION: frozenset(Office),
}


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CampInfo(_Node):
    """`camp.yaml` — 영속. 선거가 끝나도 남는 것만 둔다."""

    camp_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    """경로 세그먼트가 되므로 소문자·숫자·하이픈만. `data/camps/<camp_id>/` 다."""

    candidate_name: str = Field(min_length=1)
    created_at: dt.date


class Election(_Node):
    type: ElectionType
    """계약의 `ElectionType` 을 그대로 쓴다.

    `assembly` 같은 별칭을 두지 않는다 — 레코드의 `election_type` 과 이 값이 같아야
    렌즈가 `voter_profile`·`turnout_gap` 을 이 캠프의 계열로 걸러낼 수 있다.
    별칭을 하나 두는 순간 두 곳이 어긋날 자리가 생긴다.
    """

    office: Office
    date: dt.date | None = None
    """선거일. **모르면 null 로 둔다.**

    임의 날짜로 채우지 않는다. 여론조사 공표 금지기간(§108)처럼 기간에 의존하는
    판정은 이 값 없이 계산할 수 없고, 그런 항목은 전부 `unreviewed` 로 떨어진다
    (`compliance.yaml` 의 `election_day` 와 같은 규약).
    """

    @model_validator(mode="after")
    def _office_matches_type(self):
        allowed = _OFFICES_BY_TYPE[self.type]
        if self.office not in allowed:
            raise ValueError(
                f"선거 계열 '{self.type}' 에 직위 '{self.office}' 는 올 수 없다. "
                f"가능한 값: {sorted(o.value for o in allowed)}"
            )
        return self


class Territory(_Node):
    """관할. **참조가 아니라 실체다.**

    확정된 행정동 코드 목록이 진실이고, `preset` 은 그것을 무엇으로 채웠는지의
    기록일 뿐이다(감사용). 이 한 수로 캠프 관할이 국회의원 선거구 모델에서 분리된다 —
    기초의원 선거구(가/나/다)는 `districts.yaml` 에 아예 없고, 구청장은 국회의원
    선거구 셋을 아우른다. 그것을 자료구조로 일반화하려 들면 끝이 없다 (P-001 §6).
    """

    preset: str | None = None
    emd_codes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_codes(self):
        bad = [c for c in self.emd_codes if not (c.isdigit() and len(c) == GEO_CODE_DIGITS)]
        if bad:
            raise ValueError(f"행정동코드는 숫자 {GEO_CODE_DIGITS}자리여야 한다: {bad}")
        if len(self.emd_codes) != len(set(self.emd_codes)):
            dupes = sorted({c for c in self.emd_codes if self.emd_codes.count(c) > 1})
            raise ValueError(f"같은 행정동코드가 두 번 들어 있다: {dupes}")
        return self


class Cycle(_Node):
    """`cycles/<cycle_id>/election.yaml` — 주기별."""

    election: Election
    lineage: Camp
    """우리 진영. **렌즈다.**

    `party_lineage.yaml` 의 4축과 같은 값이라, 이 한 줄이면 기존 동별 `camp_share`
    가 그 즉시 우세/열세로 읽힌다. 데이터 복제도 재수집도 없다 (P-001 §5).
    """

    territory: Territory
    legal_reviewer: str | None = None
    """법률 검토자. `compliance.review.yaml` 의 서명 주체다.

    **시스템은 이 서명을 보증하지 않는다** — 캠프당 계정이 하나라 그 이름이 그
    사람인지 확인할 수 없다. 사람이 적는 자유 문자열이다 (P-002 §7).
    """


class Candidate(_Node):
    """후보 1명. **공개 출처 필드만.**

    선관위 후보자정보·언론 보도로 확인 가능한 것에 한한다. 사적 정보·미확인 소문은
    어떤 경우에도 넣지 않는다 (`docs/new_process.md` — 뒷조사 금지).
    절대규칙 3 은 유권자 개인을 겨냥한다. 후보는 공인이고, 공개된 공적 기록에
    한해 별개 축으로 허용된다.
    """

    name: str = Field(min_length=1)
    party: str = Field(min_length=1)
    lineage: Camp
    incumbent: bool = False
    note: str | None = None
    """진영을 그렇게 판단한 근거. 무소속·신당처럼 자명하지 않을 때 적는다.

    `party_lineage.yaml` 이 판단 근거를 파일 안에 적어두는 관례를 그대로 따른다.
    """


class Roster(_Node):
    """`cycles/<cycle_id>/candidates.yaml` — 우리 1명 + 상대 N명."""

    ours: Candidate
    opponents: list[Candidate] = Field(default_factory=list)
    """후보 확정 전이면 비어 있어도 된다.

    **미기입을 `other` 로 자동 강등하지 않는다.** `party_lineage.yaml:26` 과 같은
    이유다 — 조용히 other 로 떨어뜨리면 '분류 누락'과 '실제 군소후보'를 구분할 수
    없게 된다.
    """

    @model_validator(mode="after")
    def _no_duplicate_names(self):
        names = [self.ours.name] + [o.name for o in self.opponents]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"같은 후보가 두 번 들어 있다: {dupes}")
        return self
