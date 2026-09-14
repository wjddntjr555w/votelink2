"""kind별 본문(payload) 스키마.

봉투는 모든 레코드가 같지만 본문은 kind마다 다르다. 새 kind를 추가하려면
여기에 모델을 만들고 PAYLOAD_MODELS 에 등록한다 (= 계약 변경, 사용자 승인 필요).

extra="forbid": 정의되지 않은 키를 거부한다. 수집기가 임의 필드를 흘리거나
해석 결과(sentiment 등)를 본문에 섞는 것을 막기 위함이다.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from votelink.contract.enums import (
    AgeBand,
    Camp,
    ElectionType,
    IssueTrend,
    RecordKind,
    Sex,
    Trend,
)


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
    election_type: ElectionType
    """이 프로파일이 근거한 선거 계열. 한 레코드는 한 종류만 담는다 —
    대선과 총선은 편차의 의미가 달라 같은 시계열에 섞지 않는다.
    lean_series 의 모든 point 가 이 값과 일치한다 (_check_series_type)."""

    lean_series: list[LeanPoint] = Field(min_length=1, description="오래된 선거 순")
    swing: float = Field(ge=0.0, description="conservative 시계열의 최댓값 − 최솟값 (%p)")
    trend: Trend

    age_mix: dict[AgeBand, float] = Field(description="연령대별 비중 %")
    sex_ratio: float = Field(gt=0, description="남/여 비. 백분율이 아니다")
    population_total: int = Field(ge=0)
    population_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def _check_series_type(self):
        """레코드 하나는 한 선거 계열만 담는다. 종류가 섞이면 swing/trend 의
        의미가 무너진다 (docs/proposals/A-001)."""
        mixed = {p.election_type for p in self.lean_series} - {self.election_type}
        if mixed:
            raise ValueError(
                f"lean_series 에 election_type={self.election_type} 이 아닌 point 가 있다: "
                f"{sorted(m.value for m in mixed)}"
            )
        return self

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


# --- news_pulse (L2 파생) ---------------------------------------------------
#
# **단위 규약: 비율은 퍼센트(%)다** (segment_profile 과 같다). top_publisher_share
# 는 0~100. z-score 는 표준편차 배수라 단위가 없다.
#
# 기사를 행정동에 귀속시키지 않으므로 geo_level 은 sigungu 고정이고, 선거구당
# 레코드 1건이다. 제안서: docs/proposals/A-002-news-pulse.md


class TermCount(_Payload):
    """누적 언급 빈도 한 줄. (지명|인물|언론사, 건수)."""

    term: str = Field(min_length=1)
    count: int = Field(ge=1)


class NewsWeekPoint(_Payload):
    """한 주(ISO 월요일 시작)의 뉴스량 집계."""

    week_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    article_count: int = Field(ge=0)
    district_specific_count: int = Field(ge=0, description="confidence>=0.9 로 매칭된 기사 수")
    publisher_count: int = Field(ge=0, description="고유 언론사(도메인) 수")
    top_publisher_share: float = Field(ge=0.0, le=100.0, description="최다 언론사 비중 %")
    spike: bool
    spike_z: float | None = None
    """직전 history 창 대비 z-score. 창이 min_history_weeks 미만이거나 표준편차 0이면 None.
    None 을 0 으로 채우지 않는다 — '평상'과 '판정 불가'는 다르다."""

    @model_validator(mode="after")
    def _check_counts(self):
        if self.district_specific_count > self.article_count:
            raise ValueError(
                f"district_specific_count({self.district_specific_count})이 "
                f"article_count({self.article_count})보다 크다 ({self.week_start})"
            )
        if self.article_count == 0 and self.publisher_count != 0:
            raise ValueError(
                f"기사 0인데 언론사 수가 {self.publisher_count} 다 ({self.week_start})"
            )
        if self.spike and self.spike_z is None:
            raise ValueError(f"spike=True 인데 spike_z 가 None 이다 ({self.week_start})")
        return self


class NewsPulsePayload(_Payload):
    """선거구 뉴스 펄스 — news_article 을 주 단위로 접은 것. 양과 분포만 센다.
    어떤 기사가 실제 지역 이슈인지 가려내는 일은 별도 분석기(issue_ranker)의 몫이다."""

    as_of: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="가장 최근 기사의 연-월")
    window_weeks: int = Field(ge=1, description="weekly 에 담은 주 수")
    weekly: list[NewsWeekPoint] = Field(min_length=1, description="오래된 주 순")
    total_articles: int = Field(ge=0)
    top_places: list[TermCount] = Field(default_factory=list)
    top_persons: list[TermCount] = Field(default_factory=list)
    top_publishers: list[TermCount] = Field(default_factory=list)
    backfill_distorted: bool = Field(
        default=False,
        description="첫 백필의 API 상한(검색어당 1,000건) 때문에 최근으로 갈수록 "
        "기사량이 부풀어 있으면 True. 이때 spike 판정은 신뢰하지 않는다",
    )

    @model_validator(mode="after")
    def _check_series(self):
        starts = [w.week_start for w in self.weekly]
        if starts != sorted(starts):
            raise ValueError(f"weekly 가 시간순이 아니다: {starts}")
        if len(starts) != len(set(starts)):
            raise ValueError(f"weekly 에 같은 주가 두 번 있다: {starts}")
        if len(self.weekly) > self.window_weeks:
            raise ValueError(
                f"weekly 가 {len(self.weekly)}주로 window_weeks({self.window_weeks})를 넘는다"
            )
        summed = sum(w.article_count for w in self.weekly)
        if summed != self.total_articles:
            raise ValueError(
                f"total_articles({self.total_articles})가 weekly 합({summed})과 다르다. "
                "창을 자를 때 total 을 같이 줄이지 않았다"
            )
        return self


# --- local_issue (L2 파생) --------------------------------------------------
#
# news_article 을 어휘집(data/shared/reference/issue_lexicon.yaml)으로 분류해 언급 빈도·
# 최근성으로 세운 지역 현안 랭킹. news_pulse 가 "얼마나"를 답한다면 이건 "무엇을".
# LLM 을 쓰지 않는다 — 순수 substring 매칭이라 재현 가능하다. 감성·유불리는
# 판정하지 않는다 (그건 별도 분석기). 선거구당 레코드 1건, geo_level 은 sigungu 고정.
# 제안서: docs/proposals/A-003-issue-ranker.md


class IssueRank(_Payload):
    """이슈 카테고리 한 줄. issues 는 recency_score 내림차순, 동점은 category 오름차순."""

    category: str = Field(min_length=1, description="issue_lexicon.yaml 의 key")
    label: str = Field(min_length=1, description="사람이 읽는 이름")
    article_count: int = Field(ge=0, description="window 안에서 이 카테고리로 분류된 기사 수")
    share: float = Field(
        ge=0.0,
        description="분류된 기사 중 비중 %. 한 기사가 여러 카테고리에 걸리므로(비배타) "
        "합이 100 을 넘을 수 있다 — le 제약을 두지 않는다",
    )
    recency_score: float = Field(ge=0.0, description="주별 기사 수 × 지수감쇠 합")
    trend: IssueTrend
    top_places: list[TermCount] = Field(default_factory=list)
    sample_headlines: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="대표 헤드라인 최대 3 (published_at 내림차순, 원문 title). 본문 아님",
    )


class LocalIssuePayload(_Payload):
    """선거구 이슈 랭킹 — news_article 을 어휘집으로 분류한 파생 집계.
    어떤 기사가 우리에게 유리/불리한지는 판정하지 않는다."""

    as_of: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="가장 최근 기사의 연-월. 분석 실행 시각이 아니다",
    )
    window_weeks: int = Field(ge=1, description="접은 주 수")
    total_articles: int = Field(
        ge=0, description="window 안 · confidence 임계 이상의 분류 대상 기사 수"
    )
    issues: list[IssueRank] = Field(
        default_factory=list, description="recency_score 내림차순, 동점 category 오름차순"
    )
    unclassified_count: int = Field(
        ge=0, description="어느 카테고리에도 안 걸린 기사 수. 크면 어휘집 보강 신호 (투명성 지표)"
    )
    lexicon_version: str = Field(
        min_length=1,
        description="사용한 issue_lexicon.yaml 의 version. 어휘집이 곧 편집 판단이라 재현성용",
    )
    backfill_distorted: bool = Field(
        default=False,
        description="첫 백필의 검색 API 상한 때문에 최근 주가 부풀어 있으면 True. "
        "이때 최근성·추세는 신뢰하지 않는다 (news_pulse 와 같은 플래그)",
    )

    @model_validator(mode="after")
    def _check_invariant(self):
        summed = sum(i.article_count for i in self.issues)
        # 비배타 분류라 중복이 있어 등호가 아니라 >=. 미달이면 창 자르기·분류에서 기사가 샜다.
        if summed + self.unclassified_count < self.total_articles:
            raise ValueError(
                f"sum(article_count)={summed} + unclassified={self.unclassified_count} < "
                f"total_articles={self.total_articles}. 창 자르기·분류에서 기사가 샜다"
            )
        return self

    @model_validator(mode="after")
    def _check_order_and_uniqueness(self):
        cats = [i.category for i in self.issues]
        if len(cats) != len(set(cats)):
            raise ValueError(f"issues 에 같은 category 가 두 번 있다: {cats}")
        keys = [(-i.recency_score, i.category) for i in self.issues]
        if keys != sorted(keys):
            raise ValueError(
                "issues 가 recency_score 내림차순·category 오름차순이 아니다. 정렬은 계약이다"
            )
        return self


# --- turnout_gap (파생) -------------------------------------------------------


class TurnoutPoint(_Payload):
    """한 회차의 이 동 투표율과 기준선. 제안서: docs/proposals/A-004-turnout-gap.md"""

    election_id: str = Field(min_length=1)
    turnout: float = Field(ge=0, le=1, description="이 동의 투표율")
    baseline: float = Field(ge=0, le=1, description="같은 회차 선거구 전체 투표율")
    gap: float = Field(description="turnout − baseline. 음수면 평균보다 낮다")
    eligible_voters: int = Field(ge=0)
    total_votes: int = Field(ge=0)


class TurnoutGapPayload(_Payload):
    """읍면동 투표율 편차. 제안서: docs/proposals/A-004-turnout-gap.md

    "누구를 찍는가"가 아니라 "투표장에 가는가"를 답한다. 성향이 우리 쪽인데
    투표율이 낮은 동은 설득 대상이 아니라 동원 대상이고, 둘은 다른 자원을 쓴다.
    """

    election_type: ElectionType
    """이 편차가 근거한 선거 계열. 대선과 총선은 투표율 수준이 근본적으로 달라
    (2008 총선 42% vs 1992 대선 82%) 같은 시계열에 섞지 않는다."""

    emd_name: str = Field(min_length=1)
    points: list[TurnoutPoint] = Field(min_length=1, description="오래된 회차 순")
    latest_gap: float = Field(description="최근 회차의 편차")
    mean_gap: float = Field(description="전 회차 평균 편차")
    gap_slope: float = Field(description="회차당 편차 변화량. 양수면 격차가 벌어지는 중")
    below_baseline: bool = Field(description="mean_gap < 0. GOTV 후보군")
    elections_used: int = Field(ge=1)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="최근 회차 선거일")


# --- target_priority (파생) ---------------------------------------------------
#
# **단위 규약: 지수는 전부 0~100 이고 선거구 내 정규화된 값이다** (min-max). 절대 크기가
# 아니라 "이 선거구 안에서 상대적으로 어느 위치인가"를 말한다. 그래서 다른 선거구의
# target_priority 레코드와 지수를 직접 비교하면 안 된다.
# 제안서: docs/proposals/A-005-target-priority.md
#
# 이 분석기는 **진영 중립**이다. "우리 동원 대상이냐 설득 대상이냐"는 캠프 렌즈가 L3 에서
# 정한다 (P-001). 여기서는 어느 편이 봐도 같은 요인과 그 블렌드만 낸다.


class TargetPriorityPayload(_Payload):
    """행정동 × 선거계열의 자원배분 우선순위.

    제안서: docs/proposals/A-005-target-priority.md
    """

    as_of: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="segment_profile 의 분석 기준월"
    )
    election_type: ElectionType
    """이 우선순위가 근거한 선거 계열. 대선과 총선은 경합·투표율의 의미가 달라 섞지 않는다."""

    size_index: float = Field(ge=0.0, le=100.0, description="선거구 내 인구 규모 (min-max)")
    volatility_index: float = Field(ge=0.0, le=100.0, description="swing 정규화 — 설득 여지")
    competitiveness_index: float = Field(
        ge=0.0, le=100.0, description="최신 회차 |보수−진보| 격차가 작을수록 높음"
    )
    turnout_headroom: float = Field(
        ge=0.0, le=100.0, description="max(0, -mean_gap) 정규화 — 동원 여유. 입력 없으면 0"
    )
    attention_score: float = Field(ge=0.0, le=100.0, description="위 넷의 가중 블렌드. 렌즈 무관")
    rank: int = Field(ge=1, description="선거구·계열 내 attention_score 내림차순 순위 (1=최우선)")
    group_size: int = Field(ge=1, description="이 선거구·계열의 동 수 (rank 분모)")
    segment_note: str = Field(
        min_length=1,
        description=(
            "중립 유형 (렌즈 무관): swing_battleground / mobilization_target / "
            "persuasion_ground / safe / low_stakes"
        ),
    )

    conservative_share: float = Field(ge=0.0, le=100.0, description="최신 회차 보수 진영 득표 %")
    progressive_share: float = Field(ge=0.0, le=100.0, description="최신 회차 진보 진영 득표 %")
    population_total: int = Field(ge=0)
    has_turnout_input: bool = Field(
        description="turnout_gap 입력이 있었나. False 면 confidence 하향"
    )

    @model_validator(mode="after")
    def _rank_within_group(self):
        if self.rank > self.group_size:
            raise ValueError(f"rank({self.rank})가 group_size({self.group_size})를 넘는다")
        return self


# --- candidate_mention_share (파생) --------------------------------------------
#
# 선거구 등록 후보(우리 + 상대)별 주간 뉴스 언급 비교. news_pulse 가 "이 선거구에
# 뉴스가 얼마나 있나"를 답한다면 이건 "그중 누가 언급됐나"를 답한다. 감성·논조는
# 판정하지 않는다 — 순수 카운팅. 정당 단위 집계는 범위 밖(후보 단위만).
# 제안서: docs/proposals/A-006-candidate-mention-share.md


class CandidateWeekPoint(_Payload):
    """한 후보의 한 주(ISO 월요일 시작) 언급 집계."""

    week_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    article_count: int = Field(ge=0)
    share_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="그 주 등록 후보 전체 언급 합 대비 %. 분모(전체 합) 0이면 None",
    )
    wow_change_pct: float | None = Field(
        default=None,
        description="전주 대비 건수 변화율 %. 전주 건수가 0이면 None(0에서 어떤 수로 가도 무한대)",
    )


class CandidateMentionSeries(_Payload):
    """한 후보의 로스터 정보 + 주간 언급 시계열."""

    name: str = Field(min_length=1)
    party: str = Field(min_length=1)
    lineage: Camp
    is_ours: bool
    weekly: list[CandidateWeekPoint] = Field(min_length=1, description="오래된 주 순")
    total_articles: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_series(self):
        starts = [w.week_start for w in self.weekly]
        if starts != sorted(starts):
            raise ValueError(f"{self.name} weekly 가 시간순이 아니다: {starts}")
        if len(starts) != len(set(starts)):
            raise ValueError(f"{self.name} weekly 에 같은 주가 두 번 있다: {starts}")
        summed = sum(w.article_count for w in self.weekly)
        if summed != self.total_articles:
            raise ValueError(
                f"{self.name} total_articles({self.total_articles})가 weekly 합({summed})과 다르다"
            )
        return self


class CandidateMentionSharePayload(_Payload):
    """선거구 등록 후보별 주간 뉴스 언급 비교. 제안서: docs/proposals/A-006"""

    as_of: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="가장 최근 매칭 기사의 연-월"
    )
    window_weeks: int = Field(ge=1, description="news_pulse 와 비교 가능하도록 같은 값을 쓴다")
    candidates: list[CandidateMentionSeries] = Field(
        min_length=1, description="ours 1명 먼저, opponents 는 candidates.yaml 순"
    )
    total_articles: int = Field(ge=0)
    backfill_distorted: bool = Field(
        default=False,
        description="첫 백필의 검색 API 상한 때문에 최근 주가 부풀어 있으면 True "
        "(news_pulse 와 같은 플래그)",
    )

    @model_validator(mode="after")
    def _check_at_least_one_ours(self):
        # 한 district 를 여러 캠프가 관할할 수 있어(P-001) is_ours=True 가 여럿일
        # 수 있다 — "정확히 1명"으로 강제하지 않는다. 아예 없으면 캠프 매핑이 샌
        # 것이니 그건 잡는다.
        if not any(c.is_ours for c in self.candidates):
            raise ValueError("candidates 안에 is_ours=True 인 후보가 하나도 없다")
        return self

    @model_validator(mode="after")
    def _check_total(self):
        summed = sum(c.total_articles for c in self.candidates)
        if summed != self.total_articles:
            raise ValueError(
                f"total_articles({self.total_articles})가 candidates 합({summed})과 다르다"
            )
        return self


PAYLOAD_MODELS: dict[RecordKind, type[_Payload]] = {
    RecordKind.ELECTION_RESULT: ElectionResultPayload,
    RecordKind.POPULATION: PopulationPayload,
    RecordKind.NEWS_ARTICLE: NewsArticlePayload,
    RecordKind.SEGMENT_PROFILE: SegmentProfilePayload,
    RecordKind.NEWS_PULSE: NewsPulsePayload,
    RecordKind.LOCAL_ISSUE: LocalIssuePayload,
    RecordKind.TURNOUT_GAP: TurnoutGapPayload,
    RecordKind.TARGET_PRIORITY: TargetPriorityPayload,
    RecordKind.CANDIDATE_MENTION_SHARE: CandidateMentionSharePayload,
}
"""kind → 본문 모델. 여기 없는 kind는 아직 구현되지 않은 것이며 Record 생성이 거부된다."""
