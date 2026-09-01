"""공통 데이터 계약 검증.

여기 있는 테스트는 명세서(docs/10-data-contract.md)의 각 규칙과 1:1로 대응한다.
규칙을 바꾸려면 문서와 이 테스트를 함께 고친다.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from votelink.contract import KST, Record, load_record, make_record_id

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=KST)


def news(**over):
    base = dict(
        kind="news_article",
        collector_id="naver_news",
        source_name="네이버 뉴스",
        source_url="https://n.news.naver.com/article/1",
        source_license="api_tos",
        observed_at=datetime(2026, 8, 30, 14, 20, tzinfo=KST),
        observed_precision="minute",
        ingested_at=NOW,
        geo_level="emd",
        geo_code="3230040",
        geo_name="풍납1동",
        confidence=1.0,
        natural_key="https://n.news.naver.com/article/1",
        payload={
            "title": "송파 재건축 논의 본격화",
            "publisher": "가상일보",
            "published_at": "2026-08-30T14:20:00+09:00",
            "url": "https://n.news.naver.com/article/1",
            "summary": "요약 세 문장 이내.",
        },
    )
    base.update(over)
    return base


# --- record_id: 멱등성 ---------------------------------------------------------


def test_record_id_is_deterministic():
    a = Record(**news())
    b = Record(**news())
    assert a.record_id == b.record_id
    assert len(a.record_id) == 16


def test_record_id_differs_by_natural_key():
    a = Record(**news())
    b = Record(**news(natural_key="다른 기사"))
    assert a.record_id != b.record_id


def test_natural_key_is_not_serialized():
    """natural_key 는 계산용 입력일 뿐 봉투 필드가 아니다."""
    dumped = Record(**news()).model_dump()
    assert "natural_key" not in dumped
    assert dumped["record_id"]


def test_stored_record_round_trips_without_natural_key():
    dumped = Record(**news()).model_dump(mode="json")
    assert Record.model_validate(dumped).record_id == dumped["record_id"]


def test_record_id_or_natural_key_required():
    payload = news()
    payload.pop("natural_key")
    with pytest.raises(ValidationError, match="natural_key"):
        Record(**payload)


# --- 시각 ----------------------------------------------------------------------


def test_naive_datetime_is_treated_as_kst():
    r = Record(**news(observed_at=datetime(2026, 8, 30, 14, 20)))
    assert r.observed_at.utcoffset() == timedelta(hours=9)


def test_observed_at_cannot_be_after_ingested_at():
    """2020년 총선 데이터를 오늘 수집하면 두 값이 다르다. 뒤집히면 혼동한 것이다."""
    with pytest.raises(ValidationError, match="미래"):
        Record(**news(observed_at=NOW + timedelta(days=1)))


# --- 지리 앵커 -----------------------------------------------------------------


def test_geo_code_cannot_be_null_when_level_requires_it():
    """매핑 실패를 null 로 넘기지 않는다 — 그 동네가 통째로 전략에서 빠진다."""
    with pytest.raises(ValidationError, match="geo_code 가 없다"):
        Record(**news(geo_code=None))


def test_geo_code_digit_count_is_enforced():
    with pytest.raises(ValidationError, match="7자리"):
        Record(**news(geo_code="32300"))


def test_point_level_uses_containing_emd_code():
    """지점 데이터도 조인 가능해야 하므로 포함 행정동 코드를 갖는다."""
    r = Record(**news(geo_level="point"))
    assert len(r.geo_code) == 7


def test_nation_level_must_not_have_geo_code():
    with pytest.raises(ValidationError, match="geo_code 가 있다"):
        Record(**news(geo_level="nation"))


def test_geo_name_required_with_code():
    with pytest.raises(ValidationError, match="geo_name"):
        Record(**news(geo_name=None))


# --- payload 검증 --------------------------------------------------------------


def test_unknown_payload_field_is_rejected():
    """수집기가 해석 결과를 본문에 섞는 것을 막는다."""
    p = news()
    p["payload"]["sentiment"] = -0.4
    with pytest.raises(ValidationError):
        Record(**p)


def test_election_result_vote_accounting():
    def election(results, invalid, total=1000, eligible=1500):
        return dict(
            kind="election_result",
            collector_id="nec_election_result",
            source_name="중앙선거관리위원회",
            source_license="public_open",
            observed_at=datetime(2024, 4, 10, tzinfo=KST),
            observed_precision="day",
            ingested_at=NOW,
            geo_level="emd",
            geo_code="3230040",
            geo_name="풍납1동",
            confidence=1.0,
            natural_key="2024-04-10|11710530",
            payload={
                "election_id": "2024-04-10-national-assembly",
                "election_type": "national_assembly",
                "district_name": "서울 송파구 갑",
                "eligible_voters": eligible,
                "total_votes": total,
                "results": results,
                "invalid_votes": invalid,
            },
        )

    ok = [
        {"party": "A당", "candidate": "홍길동", "votes": 600},
        {"party": "B당", "candidate": "김철수", "votes": 390},
    ]
    assert Record(**election(ok, invalid=10))

    with pytest.raises(ValidationError, match="맞지 않는다"):
        Record(**election(ok, invalid=0))

    with pytest.raises(ValidationError, match="선거인수"):
        Record(**election(ok, invalid=10, eligible=500))


def test_population_breakdown_must_sum_to_total():
    def pop(breakdown, total):
        return dict(
            kind="population",
            collector_id="mois_population",
            source_name="행정안전부",
            source_license="public_open",
            observed_at=datetime(2026, 8, 1, tzinfo=KST),
            observed_precision="month",
            ingested_at=NOW,
            geo_level="emd",
            geo_code="3230040",
            geo_name="풍납1동",
            confidence=1.0,
            natural_key="2026-08|11710530",
            payload={"reference_month": "2026-08", "breakdown": breakdown, "total": total},
        )

    cells = [
        {"age_band": "20-29", "sex": "M", "count": 100},
        {"age_band": "20-29", "sex": "F", "count": 110},
    ]
    assert Record(**pop(cells, 210))

    with pytest.raises(ValidationError, match="total"):
        Record(**pop(cells, 999))

    with pytest.raises(ValidationError, match="중복"):
        Record(**pop(cells + [cells[0]], 310))


# --- 저작권 가드 ---------------------------------------------------------------


def test_news_fulltext_blocked_for_non_open_license():
    p = news()
    p["payload"]["full_text_stored"] = True
    with pytest.raises(ValidationError, match="전문은 저장할 수 없다"):
        Record(**p)


def test_news_fulltext_allowed_for_public_open():
    p = news(source_license="public_open")
    p["payload"]["full_text_stored"] = True
    assert Record(**p)


# --- 파생 레코드 ---------------------------------------------------------------


def test_derived_from_must_hold_valid_ids():
    with pytest.raises(ValidationError, match="잘못된 record_id"):
        Record(**news(derived_from=["짧음"]))


def test_derived_from_tracks_evidence():
    src = Record(**news())
    derived = Record(**news(derived_from=[src.record_id], natural_key="derived-1"))
    assert derived.derived_from == [src.record_id]


# --- 전방 호환 (§7) ------------------------------------------------------------


def test_load_record_skips_unknown_kind():
    raw = Record(**news()).model_dump(mode="json")
    raw["kind"] = "vibe_check"
    assert load_record(raw) is None


def test_load_record_skips_higher_schema_version():
    raw = Record(**news()).model_dump(mode="json")
    raw["schema_version"] = "2.0"
    assert load_record(raw) is None


def test_load_record_accepts_current():
    raw = Record(**news()).model_dump(mode="json")
    assert load_record(raw).kind == "news_article"


def test_make_record_id_rejects_empty_natural_key():
    with pytest.raises(ValueError, match="natural_key"):
        make_record_id("news_article", "c", "")
