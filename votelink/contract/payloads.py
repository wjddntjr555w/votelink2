"""kind별 본문(payload) 스키마.

봉투는 모든 레코드가 같지만 본문은 kind마다 다르다. 새 kind를 추가하려면
여기에 모델을 만들고 PAYLOAD_MODELS 에 등록한다 (= 계약 변경, 사용자 승인 필요).

extra="forbid": 정의되지 않은 키를 거부한다. 수집기가 임의 필드를 흘리거나
해석 결과(sentiment 등)를 본문에 섞는 것을 막기 위함이다.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from votelink.contract.enums import AgeBand, Camp, ElectionType, RecordKind, Sex, Trend


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- election_result ---------------------------------------------------------


class CandidateVotes(_Payload):
    party: str
    candidate: str
    votes: int = Field(ge=0)


class ElectionResultPayload(_Payload):
    election_id: str
    election_type: ElectionType
    district_name: str
    precinct: str | None = None  # 투표소 단위. None이면 동 전체 집계
    eligible_voters: int = Field(ge=0)
    total_votes: int = Field(ge=0)
    results: list[CandidateVotes] = Field(min_length=1)
    invalid_votes: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_vote_accounting(self):
        if self.total_votes > self.eligible_voters:
            raise ValueError(
                f"투표수({self.total_votes})가 선거인수({self.eligible_voters})보다 많다"
            )
        counted = sum(r.votes for r in self.results) + self.invalid_votes
        if counted != self.total_votes:
            raise ValueError(
                f"득표 합계({counted})가 투표수({self.total_votes})와 맞지 않는다. "
                "출처 파싱이 틀렸거나 후보가 누락됐다"
            )
        return self


# --- population --------------------------------------------------------------


class PopulationCell(_Payload):
    age_band: AgeBand
    sex: Sex
    count: int = Field(ge=0)


class PopulationPayload(_Payload):
    reference_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    breakdown: list[PopulationCell] = Field(min_length=1)
    total: int = Field(ge=0)
    households: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_total_and_uniqueness(self):
        keys = [(c.age_band, c.sex) for c in self.breakdown]
        if len(keys) != len(set(keys)):
            raise ValueError("breakdown 에 (연령대, 성별) 조합이 중복됐다")
        summed = sum(c.count for c in self.breakdown)
        if summed != self.total:
            raise ValueError(f"breakdown 합({summed})이 total({self.total})과 다르다")
        return self


# --- news_article ------------------------------------------------------------


class NewsArticlePayload(_Payload):
    title: str
    publisher: str
    published_at: str  # 봉투의 observed_at 과 같은 값. 원문 표기 보존용
    url: str
    summary: str = Field(max_length=600)  # 3문장 이내. 원문 전문이 아니다
    full_text_stored: bool = False
    mentioned_places: list[str] = Field(default_factory=list)
    mentioned_persons: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    # sentiment / issue_category 같은 해석 필드를 여기 두지 않는다.
    # 해석은 L2가 derived_from 을 채운 별도 레코드로 만든다. extra="forbid" 가 이를 강제한다.


# --- segment_profile (L2 파생) -------------------------------------------------
#
# **단위 규약: 이 payload 의 비율은 전부 퍼센트(%)다.** camp_share 합 = 100.0,
# swing·gap 은 %p. 사람이 JSON 을 직접 읽는 일이 많아 0.033 보다 3.3 이 낫다.
# 예외는 sex_ratio 하나이며 그건 백분율이 아니라 남/여 비다.

_PCT_TOLERANCE = 0.01
"""부동소수 합산 오차 허용치 (%). 9개 셀을 더하면 마지막 자리가 흔들린다."""


class LeanPoint(_Payload):
    """한 선거에서 이 지역의 진영별 득표 구성."""

    election_id: str
    election_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    election_type: ElectionType
    camp_share: dict[Camp, float]
    """진영별 득표 %. 분모는 유효투표수(투표수 − 무효표)다.

    선거인수로 나누지 않는다 — 그러면 투표율 변화가 성향 변화로 오독된다.
    """
    turnout: float = Field(ge=0.0, le=100.0, description="투표수 / 선거인수 (%)")

    # 상위 단위 대비 편차 (%p). 기준선 레코드가 아직 없으면 None 이다.
    # None 을 0.0 으로 채우지 않는다 — '차이가 없다'와 '모른다'는 다르다.
    gap_district: float | None = None
    gap_sigungu: float | None = None
    gap_sido: float | None = None
    gap_nation: float | None = None

    @model_validator(mode="after")
    def _check_shares(self):
        missing = set(Camp) - set(self.camp_share)
        if missing:
            raise ValueError(
                f"camp_share 에 빠진 진영이 있다: {sorted(missing)}. "
                "득표가 없어도 0.0 을 넣는다 — 웹앱이 키 존재를 가정한다"
            )
        if any(v < 0 for v in self.camp_share.values()):
            raise ValueError(f"camp_share 에 음수가 있다: {self.camp_share}")
        total = sum(self.camp_share.values())
        if abs(total - 100.0) > _PCT_TOLERANCE:
            raise ValueError(
                f"camp_share 합이 {total:.4f} 로 100 이 아니다 ({self.election_id}). "
                "party_lineage 매핑이 일부 후보를 놓쳤거나 분모가 틀렸다"
            )
        return self


class SegmentProfilePayload(_Payload):
    """읍면동 유권자 프로파일. 제안서: docs/proposals/A-001-voter-profile.md"""

    profile_type: str = Field(min_length=1, description="어느 분석기가 만들었나")
    as_of: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="분석 기준월")

    lean_series: list[LeanPoint] = Field(min_length=1, description="오래된 선거 순")
    swing: float = Field(ge=0.0, description="conservative 시계열의 최댓값 − 최솟값 (%p)")
    trend: Trend

    age_mix: dict[AgeBand, float] = Field(description="연령대별 비중 %")
    sex_ratio: float = Field(gt=0, description="남/여 비. 백분율이 아니다")
    population_total: int = Field(ge=0)
    population_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def _check_series_order(self):
        ids = [p.election_id for p in self.lean_series]
        if len(ids) != len(set(ids)):
            raise ValueError(f"lean_series 에 같은 선거가 두 번 있다: {ids}")
        dates = [p.election_date for p in self.lean_series]
        if dates != sorted(dates):
            raise ValueError(
                f"lean_series 가 시간순이 아니다: {dates}. "
                "trend 와 swing 이 순서에 의존하므로 정렬은 계약이다"
            )
        return self

    @model_validator(mode="after")
    def _check_swing_matches_series(self):
        """swing 이 시계열에서 실제로 유도되는지 본다.

        ElectionResultPayload 가 득표 합계를 대조하는 것과 같은 정신이다 —
        계산 버그는 그럴듯한 숫자로 나오기 때문에 불변식으로만 잡힌다.
        """
        con = [p.camp_share[Camp.CONSERVATIVE] for p in self.lean_series]
        expected = max(con) - min(con)
        if abs(expected - self.swing) > _PCT_TOLERANCE:
            raise ValueError(
                f"swing({self.swing:.4f})이 lean_series 에서 계산한 값"
                f"({expected:.4f})과 다르다. 계산 버그이거나 시계열이 잘렸다"
            )
        return self

    @model_validator(mode="after")
    def _check_age_mix(self):
        missing = set(AgeBand) - set(self.age_mix)
        if missing:
            raise ValueError(f"age_mix 에 빠진 연령대가 있다: {sorted(missing)}")
        total = sum(self.age_mix.values())
        if abs(total - 100.0) > _PCT_TOLERANCE:
            raise ValueError(f"age_mix 합이 {total:.4f} 로 100 이 아니다")
        return self


PAYLOAD_MODELS: dict[RecordKind, type[_Payload]] = {
    RecordKind.ELECTION_RESULT: ElectionResultPayload,
    RecordKind.POPULATION: PopulationPayload,
    RecordKind.NEWS_ARTICLE: NewsArticlePayload,
    RecordKind.SEGMENT_PROFILE: SegmentProfilePayload,
}
"""kind → 본문 모델. 여기 없는 kind는 아직 구현되지 않은 것이며 Record 생성이 거부된다."""
