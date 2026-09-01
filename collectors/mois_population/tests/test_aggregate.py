"""재집계 로직 검증.

필드명은 실제 API 응답(2026-09-01 확인)에서 가져왔다. 여기서 쓰는 값 자체는
합성 데이터지만, 필드 '이름'은 실제와 같다 — '산수'만 검증하고, 실제 응답이
이 형태와 맞는지는 test_parse.py 가 실제 fixture로 검증한다.
"""

import pytest

from collectors.mois_population.aggregate import (
    SourceFieldMissing,
    _to_int,
    aggregate_rows,
    source_field,
)

AGE_STARTS = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)


def row(sido="서울특별시", sigungu="송파구", emd="풍납1동", total=None, admm_code=None, **ages):
    """모든 연령·성별 칸을 0으로 채운 행을 만들고 ages 로 덮어쓴다.

    ages 는 source_field() 가 만드는 실제 필드명으로 덮어쓴다
    (예: row(male20AgeNmprCnt=10)).
    """
    from votelink.contract.enums import Sex

    data = {"ctpvNm": sido, "sggNm": sigungu, "dongNm": emd}
    for sex in Sex:
        for age in AGE_STARTS:
            data[source_field(sex, age)] = 0
    data.update(ages)
    if admm_code is not None:
        data["admmCd"] = admm_code
    data["totNmprCnt"] = sum(_to_int(v) for k, v in data.items() if k.endswith("AgeNmprCnt"))
    if total is not None:
        data["totNmprCnt"] = total
    return data


def test_rows_of_same_emd_are_folded():
    """통·반이 여러 행으로 쪼개져 와도 행정동 하나로 합쳐진다."""
    aggs = aggregate_rows([row(male20AgeNmprCnt=100), row(male20AgeNmprCnt=50)])
    assert len(aggs) == 1
    assert aggs[0].rows == 2
    assert aggs[0].cells[("20-29", "M")] == 150


def test_different_emds_are_separated():
    aggs = aggregate_rows([row(emd="풍납1동"), row(emd="풍납2동")])
    assert [a.emd for a in aggs] == ["풍납1동", "풍납2동"]


def test_over_80_is_folded_into_one_band():
    """출처는 80/90/100세를 나누지만 계약은 80+ 하나다."""
    aggs = aggregate_rows([row(feml80AgeNmprCnt=30, feml90AgeNmprCnt=8, feml100AgeNmprCnt=2)])
    assert aggs[0].cells[("80+", "F")] == 40


def test_full_name_is_the_geo_lookup_key():
    assert aggregate_rows([row()])[0].full_name == "서울특별시 송파구 풍납1동"


def test_breakdown_keeps_zero_cells():
    """0명인 칸과 '데이터 없음'은 다르다. 9개 구간 × 2성별 = 18칸이 항상 나온다."""
    cells = aggregate_rows([row()])[0].breakdown()
    assert len(cells) == 18


def test_comma_separated_numbers_are_parsed():
    aggs = aggregate_rows([row(male30AgeNmprCnt="1,234")])
    assert aggs[0].cells[("30-39", "M")] == 1234


def test_total_mismatch_is_detected():
    """연령 필드를 하나라도 놓치면 합이 안 맞고, 그 레코드는 격리된다."""
    agg = aggregate_rows([row(male40AgeNmprCnt=100, total=999)])[0]
    with pytest.raises(ValueError, match="다르다"):
        agg.check_total()


def test_missing_source_field_is_explicit():
    broken = row()
    del broken["feml50AgeNmprCnt"]
    with pytest.raises(SourceFieldMissing, match="feml50AgeNmprCnt"):
        aggregate_rows([broken])


def test_aggregation_is_order_independent():
    a = aggregate_rows([row(emd="가동"), row(emd="나동")])
    b = aggregate_rows([row(emd="나동"), row(emd="가동")])
    assert [x.emd for x in a] == [x.emd for x in b]


def test_admm_code_is_taken_from_the_row():
    """출처가 코드를 주면 이름으로 되돌려 찾지 않는다."""
    aggs = aggregate_rows([row(admm_code="1171010300")])
    assert aggs[0].admm_code == "1171010300"


def test_rows_group_by_code_even_if_name_spelling_differs():
    """표기가 흔들려도 코드가 같으면 같은 행정동이다."""
    aggs = aggregate_rows(
        [
            row(emd="풍납1동", male20AgeNmprCnt=10, admm_code="1171010300"),
            row(emd="풍납제1동", male20AgeNmprCnt=5, admm_code="1171010300"),
        ]
    )
    assert len(aggs) == 1
    assert aggs[0].cells[("20-29", "M")] == 15


def test_missing_code_falls_back_to_name_grouping():
    aggs = aggregate_rows([row(emd="풍납1동"), row(emd="풍납2동")])
    assert [a.admm_code for a in aggs] == ["", ""]
    assert len(aggs) == 2
