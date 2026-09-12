"""디스크에서 읽는다. **여기가 L3의 유일한 부작용 지점이다.**

`fetch()`(L1)·`load()`(L2)와 같은 자리이며, 뒤따르는 `viewmodel.py` 는 순수 함수다
(`docs/40-webapp-spec.md §2`).

읽을 것을 고르는 방식은 **화이트리스트**다 (`§5`). 블랙리스트로 시험 데이터 이름을
프로덕션 코드에 굽지 않는다 — 다음 주엔 다른 이름일 것이다.

1. `iter_records(kinds=[SEGMENT_PROFILE])` — kind 를 반드시 준다
2. `District.contains(geo_code)` — 위생 조치가 아니라 원래 맞는 동작이다. 앱은 선거구 하나를 본다
3. `(profile_type, geo_code)` 별 최신 `as_of` 하나 — §6
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError, computed_field

from votelink.contract.enums import ElectionType, RecordKind
from votelink.contract.models import Record
from votelink.contract.payloads import (
    LocalIssuePayload,
    NewsArticlePayload,
    NewsPulsePayload,
    SegmentProfilePayload,
)
from votelink.reference.districts import District, load_districts, resolve_district
from votelink.store import count_records, iter_records
from votelink.web.settings import WebSettings

DEFAULT_ELECTION_TYPE = ElectionType.PRESIDENTIAL


class AmbiguousDistrict(LookupError):
    """선거구가 둘 이상인데 무엇을 보여줄지 지정되지 않았다.

    조용히 첫 번째를 고르지 않는다 — 옆 지역구를 보여주면서 맞다고 우기는 화면이 된다.
    """


class EmdProfile(BaseModel):
    """행정동 하나의 프로파일. 봉투와 **타입이 있는** 본문을 함께 들고 다닌다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: Record
    payload: SegmentProfilePayload

    @property
    def geo_code(self) -> str:
        return self.record.geo_code

    @property
    def geo_name(self) -> str:
        return self.record.geo_name


class LoadDiagnostics(BaseModel):
    """무엇을 읽고 무엇을 숨겼는가. **화면에 그대로 나간다.**

    9가 10이 되거나 8이 되는 일을 조용히 넘기지 않기 위해서다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    read: int = 0
    """`segment_profile` 로 읽은 총 건수."""
    outside_district: int = 0
    other_election_type: int = 0
    """요청한 선거 계열이 아니라 건너뛴 건수. 섞인 파일을 조용히 뭉개지 않는다."""
    superseded: int = 0
    """더 최신 `as_of` 에 밀린 과거 분석. 버그가 아니라 의도된 보존이다."""
    rejected: int = 0
    """본문이 계약을 위반해 건너뛴 건수. 정상이면 0이다."""
    loaded: int = 0
    expected: int = 0
    """선거구 정의가 말하는 행정동 수."""
    missing_codes: list[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_complete(self) -> bool:
        return self.loaded == self.expected and not self.missing_codes


class DistrictProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district: District
    election_type: ElectionType = DEFAULT_ELECTION_TYPE
    profiles: list[EmdProfile]
    """`geo_code` 오름차순."""
    diagnostics: LoadDiagnostics


class NationProfiles(BaseModel):
    """전국 전체 동. `District.contains` 필터를 의도적으로 건너뛴다 —
    전국은 선거구 하나가 아니다 (§5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    election_type: ElectionType = DEFAULT_ELECTION_TYPE
    profiles: list[EmdProfile]
    diagnostics: LoadDiagnostics


class SkippedDistrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_id: str
    district_name: str
    reason: str
    fix: str


class ComparisonProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    election_type: ElectionType = DEFAULT_ELECTION_TYPE
    rows: list[DistrictProfiles]
    """프로파일이 하나라도 있는 선거구. 정의 순서."""
    skipped: list[SkippedDistrict]
    """프로파일 0건이라 뺀 선거구 — 왜 뺐는지 함께."""


def pick_district(settings: WebSettings, district_id: str | None = None) -> District:
    """어느 선거구를 보여줄 것인가.

    `analyzers/voter_profile/meta.yaml` 의 `config.district` 를 읽지 않는다 — L2의 내부
    상태이고, 읽는 순간 계층 무지가 깨진다. 새 설정 파일도 만들지 않는다(값이 중복된다).

    우선순위: 요청이 지정한 `district_id` > `settings.district_id`(기본 선거구) >
    정의된 선거구가 정확히 하나면 그것. 둘 이상인데 아무것도 안 골랐으면 실패한다 —
    조용히 첫 번째를 고르면 옆 지역구를 보여주면서 맞다고 우기는 화면이 된다.
    """
    chosen = district_id or settings.district_id
    if chosen:
        return resolve_district(chosen, settings.districts_path)
    table = load_districts(settings.districts_path)
    if len(table) == 1:
        return next(iter(table.values()))
    raise AmbiguousDistrict(
        f"선거구가 {len(table)}개 정의돼 있다: {sorted(table)}. "
        "URL(/d/<선거구>/) 이나 --district 로 무엇을 볼지 지정하라 (임의로 고르지 않는다)"
    )


def available_districts(settings: WebSettings, lens=None) -> list[tuple[str, str]]:
    """(id, name) 목록. 내비게이션의 선거구 전환 UI 가 쓴다. `geo_code` 오름차순이 아니라
    정의 순서를 지킨다 (districts.yaml 이 의도한 순서).

    **렌즈가 있으면 그 캠프의 관할과 겹치는 것만 낸다.** 미들웨어가 이미 관할 밖을
    403 으로 막으므로(P-002 §9), 목록에 남겨 두면 눌러도 거부되는 항목만 늘어난다.
    보안이 아니라 정직함의 문제다 — 선거구 정의는 어차피 공개 참조 데이터다.
    관할이 비어 있으면(진영 중립 보기) 전부 낸다.
    """
    table = load_districts(settings.districts_path)
    rows = [(d.id, d.name) for d in table.values()]
    if lens is None or not lens.territory:
        return rows
    return [(d.id, d.name) for d in table.values() if lens.territory & set(d.emd_codes)]


def _dedup_newest(
    records: Iterable[Record],
    *,
    election_type: ElectionType,
    within: Callable[[str], bool],
) -> tuple[list[EmdProfile], dict[str, int]]:
    """읽기·검증·필터·dedup 을 한 자리에. `within` 이 선거구 소속 필터
    (`/nation` 은 항상 True). 필터 4겹: kind → within → election_type →
    `(profile_type, election_type, geo_code)` 별 최신 `as_of`."""
    read = outside = other = rejected = superseded = 0
    newest: dict[tuple[str, str, str], EmdProfile] = {}

    for record in records:
        read += 1
        if not within(record.geo_code):
            outside += 1
            continue
        try:
            payload = SegmentProfilePayload.model_validate(record.payload)
        except ValidationError:
            # 이미 저장 시점에 검증된 값이라 여기 오면 안 된다. 그래도 한 건 때문에
            # 나머지를 잃지 않는다 — L1·L2 의 항목 격리와 같은 정신이다.
            rejected += 1
            continue
        if payload.election_type != election_type:
            other += 1
            continue

        key = (payload.profile_type, payload.election_type.value, record.geo_code)
        current = newest.get(key)
        if current is None:
            newest[key] = EmdProfile(record=record, payload=payload)
            continue
        superseded += 1
        if payload.as_of > current.payload.as_of:
            newest[key] = EmdProfile(record=record, payload=payload)

    profiles = sorted(newest.values(), key=lambda p: p.geo_code)
    return profiles, {
        "read": read,
        "outside_district": outside,
        "other_election_type": other,
        "rejected": rejected,
        "superseded": superseded,
    }


def load_profiles(
    settings: WebSettings,
    district_id: str | None = None,
    *,
    election_type: ElectionType = DEFAULT_ELECTION_TYPE,
) -> DistrictProfiles:
    district = pick_district(settings, district_id)
    codes = set(district.emd_codes)
    profiles, counters = _dedup_newest(
        iter_records([RecordKind.SEGMENT_PROFILE], space=settings.space),
        election_type=election_type,
        within=district.contains,
    )
    loaded_codes = {p.geo_code for p in profiles}

    return DistrictProfiles(
        district=district,
        election_type=election_type,
        profiles=profiles,
        diagnostics=LoadDiagnostics(
            **counters,
            loaded=len(profiles),
            expected=len(codes),
            missing_codes=sorted(codes - loaded_codes),
        ),
    )


def load_comparison(
    settings: WebSettings, *, election_type: ElectionType = DEFAULT_ELECTION_TYPE
) -> ComparisonProfiles:
    """정의된 모든 선거구를 훑어 각각 로드. 프로파일 0건인 선거구는 사유와 함께 뺀다.

    성능: N선거구 × 전체 레코드 스캔 = O(N·R). 48×9 규모라 무의미하다 (§13 — 커지면
    SQLite). 역인덱스는 지금 만들지 않는다.
    """
    rows: list[DistrictProfiles] = []
    skipped: list[SkippedDistrict] = []
    for district in load_districts(settings.districts_path).values():
        dp = load_profiles(settings, district.id, election_type=election_type)
        if dp.profiles:
            rows.append(dp)
            continue
        no_codes = not district.emd_codes
        skipped.append(
            SkippedDistrict(
                district_id=district.id,
                district_name=district.name,
                reason=(
                    "행정동코드 미확정 (districts.yaml)"
                    if no_codes
                    else "분석 결과 0건 — voter_profile 미실행"
                ),
                fix=(
                    "data/shared/reference/districts.yaml 의 emd[].code 를 채운다"
                    if no_codes
                    else f"uv run votelink analyze voter_profile --district {district.id}"
                ),
            )
        )
    return ComparisonProfiles(election_type=election_type, rows=rows, skipped=skipped)


def load_all_emd(
    settings: WebSettings, *, election_type: ElectionType = DEFAULT_ELECTION_TYPE
) -> NationProfiles:
    profiles, counters = _dedup_newest(
        iter_records([RecordKind.SEGMENT_PROFILE], space=settings.space),
        election_type=election_type,
        within=lambda _code: True,  # 전국: 선거구 소속 필터를 의도적으로 건너뛴다
    )
    return NationProfiles(
        election_type=election_type,
        profiles=profiles,
        diagnostics=LoadDiagnostics(
            **counters,
            loaded=len(profiles),
            # 전국은 "있어야 할 수"의 분모가 없다. 표시 N곳이 곧 전부다.
            expected=len(profiles),
        ),
    )


# --- 뉴스 (news_article) -----------------------------------------------------
#
# `segment_profile` 과 다른 점 둘: (1) election_type 축이 없다 — 기사는 선거
# 계열에 속하지 않는다. (2) `as_of` dedup 이 없다 — L1 이 정규화한 URL 을
# natural_key 로 써서 record_id 가 이미 유일하다. 그래서 로더가 훨씬 짧다.
#
# 선거구 소속 필터: 기사의 geo_level 은 sigungu(예: 1171000000)라 emd 코드
# 목록으로 매칭하는 `District.contains` 가 안 잡는다. 대신 그 선거구 행정동
# 코드들의 시군구 코드(<4자리>000000)와 대조한다 — 두 시군구에 걸친 선거구
# (중구성동구 을)면 양쪽 다 받는다.


class NewsItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: Record
    payload: NewsArticlePayload


class NewsDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    read: int = 0
    outside_district: int = 0
    rejected: int = 0
    """본문이 계약을 위반해 건너뛴 건수. 정상이면 0."""
    duplicate: int = 0
    """같은 record_id 가 두 번 — 저장이 정상이면 0."""
    shown: int = 0


class DistrictNews(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district: District
    items: list[NewsItem]
    """`observed_at` 내림차순 (최신 먼저)."""
    diagnostics: NewsDiagnostics


def _sigungu_codes(district: District) -> set[str]:
    return set(district.sigungu_codes)


def load_news(settings: WebSettings, district_id: str | None = None) -> DistrictNews:
    district = pick_district(settings, district_id)
    wanted = _sigungu_codes(district)

    total = count_records([RecordKind.NEWS_ARTICLE], space=settings.space)
    rejected = duplicate = 0
    seen: set[str] = set()
    items: list[NewsItem] = []

    # geo 필터를 iter_records 로 밀어 넣는다 — 관심 밖 시군구 기사를 Record 로
    # 만들기 전에 부분문자열로 쳐낸다 (naver_news.jsonl 은 수만 줄이다). 남는
    # 것만 여기서 계약 검증한다.
    for record in iter_records([RecordKind.NEWS_ARTICLE], geo_codes=wanted, space=settings.space):
        if record.record_id in seen:
            duplicate += 1
            continue
        try:
            payload = NewsArticlePayload.model_validate(record.payload)
        except ValidationError:
            rejected += 1
            continue
        seen.add(record.record_id)
        items.append(NewsItem(record=record, payload=payload))

    items.sort(key=lambda it: it.record.observed_at, reverse=True)
    return DistrictNews(
        district=district,
        items=items,
        diagnostics=NewsDiagnostics(
            read=total,
            # 전체에서 이 선거구 것(표시·중복·격리)을 뺀 나머지가 '선거구 밖'이다.
            outside_district=total - len(items) - duplicate - rejected,
            rejected=rejected,
            duplicate=duplicate,
            shown=len(items),
        ),
    )


# --- 뉴스 펄스 (news_pulse, L2 파생) ----------------------------------------
#
# 선거구당 레코드 1건. as_of(연-월)가 여럿이면 최신 하나만 — segment_profile 의
# as_of dedup 과 같은 정신이되 축이 (geo_code) 하나뿐이라 훨씬 짧다.


class NewsPulse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: Record
    payload: NewsPulsePayload


def load_news_pulse(settings: WebSettings, district_id: str | None = None) -> NewsPulse | None:
    district = pick_district(settings, district_id)
    wanted = _sigungu_codes(district)

    best: NewsPulse | None = None
    for record in iter_records([RecordKind.NEWS_PULSE], space=settings.space):
        if record.geo_code not in wanted:
            continue
        try:
            payload = NewsPulsePayload.model_validate(record.payload)
        except ValidationError:
            continue
        if best is None or payload.as_of > best.payload.as_of:
            best = NewsPulse(record=record, payload=payload)
    return best


# --- 이슈 보드 (local_issue, L2 파생) -------------------------------------------
#
# 선거구당 레코드 1건. as_of(연-월)가 여럿이면 최신 하나만 — load_news_pulse 와 동형.


class LocalIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: Record
    payload: LocalIssuePayload


def load_local_issue(settings: WebSettings, district_id: str | None = None) -> LocalIssue | None:
    district = pick_district(settings, district_id)
    wanted = _sigungu_codes(district)

    best: LocalIssue | None = None
    for record in iter_records([RecordKind.LOCAL_ISSUE], space=settings.space):
        if record.geo_code not in wanted:
            continue
        try:
            payload = LocalIssuePayload.model_validate(record.payload)
        except ValidationError:
            continue
        if best is None or payload.as_of > best.payload.as_of:
            best = LocalIssue(record=record, payload=payload)
    return best
