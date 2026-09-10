"""공통 데이터 계약의 열거형.

이 값들을 바꾸는 것은 계약 변경이다. docs/10-data-contract.md 를 함께 수정한다.
"""

from enum import StrEnum


class RecordKind(StrEnum):
    """레코드 본문(payload)의 종류. 분석기는 이 값으로 분기한다."""

    ELECTION_RESULT = "election_result"
    POPULATION = "population"
    NEWS_ARTICLE = "news_article"
    POLL = "poll"
    POI = "poi"
    FOOT_TRAFFIC = "foot_traffic"
    CANDIDATE = "candidate"
    LOCAL_ISSUE = "local_issue"
    SEGMENT_PROFILE = "segment_profile"
    NEWS_PULSE = "news_pulse"
    TURNOUT_GAP = "turnout_gap"
    TARGET_PRIORITY = "target_priority"


class GeoLevel(StrEnum):
    """레코드가 고정된 행정구역 단위."""

    NATION = "nation"
    SIDO = "sido"
    SIGUNGU = "sigungu"
    EMD = "emd"
    POINT = "point"
    NONE = "none"


class SourceLicense(StrEnum):
    """출처의 이용 조건. 저장·재배포 가능 범위를 결정한다."""

    PUBLIC_OPEN = "public_open"
    API_TOS = "api_tos"
    CRAWL_PUBLIC = "crawl_public"
    RESTRICTED = "restricted"


class ObservedPrecision(StrEnum):
    """observed_at 의 유효 자릿수. 월 단위 통계를 일 단위로 착각하지 않기 위함."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    MINUTE = "minute"


class AgeBand(StrEnum):
    """10년 단위 고정. 출처마다 5세/10세 단위가 다르므로 수집기가 재집계한다."""

    A00_09 = "0-9"
    A10_19 = "10-19"
    A20_29 = "20-29"
    A30_39 = "30-39"
    A40_49 = "40-49"
    A50_59 = "50-59"
    A60_69 = "60-69"
    A70_79 = "70-79"
    A80_PLUS = "80+"


class Sex(StrEnum):
    MALE = "M"
    FEMALE = "F"


class ElectionType(StrEnum):
    NATIONAL_ASSEMBLY = "national_assembly"
    PRESIDENTIAL = "presidential"
    LOCAL = "local"
    BY_ELECTION = "by_election"


class Camp(StrEnum):
    """정치 진영. 회차마다 정당명이 달라 시계열 비교를 하려면 공통 축이 필요하다.

    **분류 기준은 '당의 이념'이 아니라 '그 후보 득표층의 이념 위치'다.**
    매핑은 코드가 아니라 data/shared/reference/party_lineage.yaml 에 있다 — 정치적 판단이라
    눈에 보여야 하고, 이견이 있으면 그 파일만 고쳐 재분석할 수 있어야 한다.

    3분류로 뭉개지 않는 이유: 2017년 안철수 22.2% + 유승민 8.8%, 2025년 이준석 9.8%
    같은 중도표를 OTHER 로 넣으면 그 해 보수 지지가 실제보다 붕괴한 것처럼 보인다.
    """

    CONSERVATIVE = "conservative"
    PROGRESSIVE = "progressive"
    CENTRIST = "centrist"
    OTHER = "other"


class Trend(StrEnum):
    """성향 이동 방향. **지역구 평균 대비 편차**의 기울기로 판정한다.

    절대 득표율의 기울기가 아니다. 최근 3회(2017 탄핵 저점 → 2022 → 2025)로 절대
    기울기를 재면 송파갑 9개 동이 전부 CONSERVATIVE_SHIFT 로 나와 변별력이 0이 된다.
    편차를 쓰면 전국 공통 흐름이 상쇄되고 동별 상대 이동만 남는다.
    """

    CONSERVATIVE_SHIFT = "conservative_shift"
    STABLE = "stable"
    PROGRESSIVE_SHIFT = "progressive_shift"


class IssueTrend(StrEnum):
    """이슈 언급량의 방향. 창 안에서 최근 절반 합 vs 이전 절반 합의 비로 판정한다.

    절대 언급량이 아니라 창 안 상대 변화다. 모든 카테고리가 같은 값이면 정보량이
    0이므로(docs/30-analysis-spec.md §9) 임계값은 issue_ranker 의 meta.yaml config 에
    두고 구현 시 실측으로 민감도를 확인한다.
    """

    RISING = "rising"
    FLAT = "flat"
    FALLING = "falling"
