"""재집계 로직 검증.

여기서 쓰는 데이터는 **합성 데이터**다. 출처 응답 형식을 흉내낸 것이 아니라
'통·반 행을 행정동으로 접는 산수'만 검증한다.
실제 응답 형식 검증은 test_parse.py 가 하며, 그쪽은 실제 fixture를 요구한다.
"""

import pytest

from collectors.mois_population.aggregate import (
    SourceFieldMissing,
    _to_int,
    aggregate_rows,
)


def row(sido="서울특별시", sigungu="송파구", emd="풍납1동", total=None, **ages):
    """모든 연령·성별 칸을 0으로 채운 행을 만들고 ages 로 덮어쓴다."""
    labels = [
        "만0~9세",
        "만10~19세",
        "만20~29세",
        "만30~39세",
        "만40~49세",
        "만50~59세",
        "만60~69세",
        "만70~79세",
        "만80~89세",
        "만90~99세",
        "만100세이상",
    ]
    data = {"시도명": sido, "시군구명": sigungu, "행정동명": emd}
    for label in labels:
        for suffix in ("남자", "여자"):
            data[f"{label}{suffix}"] = 0
    data.update(ages)
    data["총인구수"] = sum(_to_int(v) for k, v in data.items() if k.endswith(("남자", "여자")))
    if total is not None:
        data["총인구수"] = total
    return data


def test_rows_of_same_emd_are_folded():
    """통·반이 여러 행으로 쪼개져 와도 행정동 하나로 합쳐진다."""
    aggs = aggregate_rows(
        [
            row(**{"만20~29세남자": 100}),
            row(**{"만20~29세남자": 50}),
        ]
    )
    assert len(aggs) == 1
    assert aggs[0].rows == 2
    assert aggs[0].cells[("20-29", "M")] == 150


def test_different_emds_are_separated():
    aggs = aggregate_rows([row(emd="풍납1동"), row(emd="풍납2동")])
    assert [a.emd for a in aggs] == ["풍납1동", "풍납2동"]


def test_over_80_is_folded_into_one_band():
    """출처는 80대/90대/100세이상을 나누지만 계약은 80+ 하나다."""
    aggs = aggregate_rows([row(**{"만80~89세여자": 30, "만90~99세여자": 8, "만100세이상여자": 2})])
    assert aggs[0].cells[("80+", "F")] == 40


def test_full_name_is_the_geo_lookup_key():
    assert aggregate_rows([row()])[0].full_name == "서울특별시 송파구 풍납1동"


def test_breakdown_keeps_zero_cells():
    """0명인 칸과 '데이터 없음'은 다르다. 9개 구간 × 2성별 = 18칸이 항상 나온다."""
    cells = aggregate_rows([row()])[0].breakdown()
    assert len(cells) == 18


def test_comma_separated_numbers_are_parsed():
    aggs = aggregate_rows([row(**{"만30~39세남자": "1,234"})])
    assert aggs[0].cells[("30-39", "M")] == 1234


def test_total_mismatch_is_detected():
    """연령 필드를 하나라도 놓치면 합이 안 맞고, 그 레코드는 격리된다."""
    agg = aggregate_rows([row(**{"만40~49세남자": 100}, total=999)])[0]
    with pytest.raises(ValueError, match="다르다"):
        agg.check_total()


def test_missing_source_field_is_explicit():
    broken = row()
    del broken["만50~59세여자"]
    with pytest.raises(SourceFieldMissing, match="만50~59세여자"):
        aggregate_rows([broken])


def test_aggregation_is_order_independent():
    a = aggregate_rows([row(emd="가동"), row(emd="나동")])
    b = aggregate_rows([row(emd="나동"), row(emd="가동")])
    assert [x.emd for x in a] == [x.emd for x in b]


def test_admm_code_is_taken_from_the_row():
    """출처가 코드를 주면 이름으로 되돌려 찾지 않는다."""
    aggs = aggregate_rows([dict(row(), admmCd="3230040")])
    assert aggs[0].admm_code == "3230040"


def test_rows_group_by_code_even_if_name_spelling_differs():
    """표기가 흔들려도 코드가 같으면 같은 행정동이다."""
    aggs = aggregate_rows(
        [
            dict(row(emd="풍납1동", **{"만20~29세남자": 10}), admmCd="3230040"),
            dict(row(emd="풍납제1동", **{"만20~29세남자": 5}), admmCd="3230040"),
        ]
    )
    assert len(aggs) == 1
    assert aggs[0].cells[("20-29", "M")] == 15


def test_missing_code_falls_back_to_name_grouping():
    aggs = aggregate_rows([row(emd="풍납1동"), row(emd="풍납2동")])
    assert [a.admm_code for a in aggs] == ["", ""]
    assert len(aggs) == 2
