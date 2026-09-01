"""kind별 본문(payload) 스키마.

봉투는 모든 레코드가 같지만 본문은 kind마다 다르다. 새 kind를 추가하려면
여기에 모델을 만들고 PAYLOAD_MODELS 에 등록한다 (= 계약 변경, 사용자 승인 필요).

extra="forbid": 정의되지 않은 키를 거부한다. 수집기가 임의 필드를 흘리거나
해석 결과(sentiment 등)를 본문에 섞는 것을 막기 위함이다.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from votelink.contract.enums import AgeBand, ElectionType, RecordKind, Sex


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


PAYLOAD_MODELS: dict[RecordKind, type[_Payload]] = {
    RecordKind.ELECTION_RESULT: ElectionResultPayload,
    RecordKind.POPULATION: PopulationPayload,
    RecordKind.NEWS_ARTICLE: NewsArticlePayload,
}
"""kind → 본문 모델. 여기 없는 kind는 아직 구현되지 않은 것이며 Record 생성이 거부된다."""
