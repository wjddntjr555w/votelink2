"""레이아웃 해석은 응답 형식과 무관한 순수 로직이라 합성 데이터로 검증한다
(docs/20-collector-spec.md §7). 실제 파일 검증은 test_parse.py 가 fixture 로 한다.
"""

import pytest

from ..rows import (
    EmdRow,
    Layout,
    candidate_columns,
    check_arithmetic,
    iter_emd_rows,
    normalize_emd,
    strip_disambiguation,
    to_int,
)

# 신형(18~21대) 축소판: '정당\n후보' 한 칸, 병합셀, 투표구명 빈칸
MODERN = Layout(
    sgg=1,
    emd=2,
    precinct=3,
    eligible=4,
    votes=5,
    candidate_from=6,
    total=8,
    invalid=9,
    party_row=1,
    candidate_row=1,
    data_from=2,
)
MODERN_GRID = [
    [
        "시도명",
        "구시군명",
        "읍면동명",
        "투표구명",
        "선거인수",
        "투표수",
        "후보자별 득표수",
        "",
        "",
        "무효투표수",
    ],
    ["", "", "", "", "", "", "가당\n김갑", "나당\n이을", "계", ""],
    ["서울특별시", "송파구", "합계", "", "300", "200", "120", "70", "190", "10"],
    ["서울특별시", "송파구", "관외사전투표", "", "20", "20", "12", "7", "19", "1"],
    ["서울특별시", "", "풍납1동", "", "100", "80", "50", "25", "75", "5"],  # 구시군 병합셀
    [
        "서울특별시",
        "",
        "풍납1동",
        "풍납1동제1투",
        "40",
        "30",
        "20",
        "9",
        "29",
        "1",
    ],  # 투표구 → 버림
    ["서울특별시", "", "잠실4동", "", "200", "120", "70", "45", "115", "5"],
    [
        "서울특별시",
        "강남구",
        "역삼1동",
        "",
        "500",
        "400",
        "200",
        "190",
        "390",
        "10",
    ],  # 다른 구 → 버림
]

# 구형(14·15대) 축소판: 정당/후보 별도 행, 투표구 열 없음, '제N동' 표기
LEGACY = Layout(
    sgg=1,
    emd=2,
    precinct=None,
    eligible=3,
    votes=5,
    candidate_from=7,
    total=9,
    invalid=10,
    party_row=2,
    candidate_row=3,
    data_from=4,
)
LEGACY_GRID = [
    [
        "시도명",
        "구시군명",
        "읍면동명",
        "선거인수",
        "부재자수",
        "투표자수",
        "부재자투표자수",
        "유효투표수",
        "",
        "",
        "무효투표수",
    ],
    ["", "", "", "", "", "", "", "후보자별 득표수", "", "계", ""],
    ["", "", "", "", "", "", "", "가당", "나당", "", ""],
    ["", "", "", "", "", "", "", "김갑", "이을", "", ""],
    ["서울", "송파구", "소계", "300", "0", "200", "0", "", "120", "70", "10"],
    ["서울", "송파구", "풍납제1동", "100", "0", "80", "0", "", "50", "25", "5"],
    ["서울", "송파구", "잠실제4동", "200", "0", "120", "0", "", "70", "45", "5"],
]

GAP = {"풍납1동", "잠실4동"}


class TestNormalizeEmd:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("풍납제1동", "풍납1동"),
            ("잠실제4동", "잠실4동"),
            ("풍납1동", "풍납1동"),
            ("오륜동", "오륜동"),
        ],
    )
    def test_je_dong_is_stripped(self, raw, expected):
        assert normalize_emd(raw) == expected

    def test_only_trailing_form_changes(self):
        # '제'가 동 번호 앞이 아닌 곳에 있으면 건드리지 않는다.
        assert normalize_emd("제주동") == "제주동"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("종로1·2·3·4가동", "종로1.2.3.4가동"),
            ("종로1.2.3.4가동", "종로1.2.3.4가동"),
            ("금호2·3가동", "금호2.3가동"),
        ],
    )
    def test_middle_dot_and_period_normalize_the_same(self, raw, expected):
        # D-001 로 districts.yaml 이 '.'(MOIS 표기)로 정정됐는데 선관위 원본은
        # '·' 를 쓴다. 둘 다 같은 값으로 접혀야 한다 — 어느 쪽도 '표준'으로
        # 가정하지 않는다.
        assert normalize_emd(raw) == expected

    def test_je_dong_and_dot_normalize_together(self):
        # districts.yaml(MOIS 표기)이 '창신제1동' 인데 선관위 원본은 '창신1동' 이다.
        assert normalize_emd("창신제1동") == normalize_emd("창신1동") == "창신1동"


class TestStripDisambiguation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("중구(서울)", "중구"),
            ("송파구", "송파구"),  # 전국에 하나뿐인 이름은 괄호가 안 붙는다
            ("강서구(부산)", "강서구"),
        ],
    )
    def test_strips_trailing_parenthetical(self, raw, expected):
        # 2002년(16대) 파일은 전국에 겹치는 시군구명(중구 등)에 '(시도명)'을 붙여
        # 구분한다 — 송파구처럼 유일한 이름에서는 나타나지 않아 47개 선거구로
        # 넓히기 전까지 드러나지 않았다 (D-002).
        assert strip_disambiguation(raw) == expected


class TestToInt:
    @pytest.mark.parametrize(
        "raw,expected", [("17,729", 17729), ("17729.0", 17729), ("", 0), ("  42 ", 42)]
    )
    def test_source_number_formats(self, raw, expected):
        assert to_int(raw) == expected


class TestCandidateColumns:
    def test_party_and_name_in_one_cell(self):
        assert candidate_columns(MODERN_GRID, MODERN) == [("가당", "김갑"), ("나당", "이을")]

    def test_party_and_name_in_separate_rows(self):
        assert candidate_columns(LEGACY_GRID, LEGACY) == [("가당", "김갑"), ("나당", "이을")]

    def test_empty_candidate_name_is_a_layout_error(self):
        broken = Layout(**{**MODERN.__dict__, "total": 9})  # '계' 열까지 후보로 잘못 잡음
        with pytest.raises(ValueError, match="어긋났다"):
            candidate_columns(MODERN_GRID, broken)


class TestIterEmdRows:
    def _names(self, grid, layout):
        return [
            r.emd_name for r in iter_emd_rows(grid, layout, sigungu_match="송파", emd_names=GAP)
        ]

    def test_modern_keeps_only_dong_totals(self):
        assert self._names(MODERN_GRID, MODERN) == ["풍납1동", "잠실4동"]

    def test_legacy_normalizes_names(self):
        assert self._names(LEGACY_GRID, LEGACY) == ["풍납1동", "잠실4동"]

    def test_forward_fill_carries_merged_sigungu(self):
        # 풍납1동·잠실4동 행은 구시군명이 비어 있다. 앞 값을 못 이으면 0건이 된다.
        assert len(self._names(MODERN_GRID, MODERN)) == 2

    def test_other_sigungu_is_dropped(self):
        assert "역삼1동" not in self._names(MODERN_GRID, MODERN)

    def test_precinct_rows_are_dropped(self):
        rows = list(iter_emd_rows(MODERN_GRID, MODERN, sigungu_match="송파", emd_names=GAP))
        assert len(rows) == 2, "투표구 행이 동 행과 함께 들어오면 득표가 두 배가 된다"

    def test_non_dong_rows_are_filtered_not_quarantined(self):
        # 관외사전투표·합계는 emd_names 에 없어 조용히 걸러진다. 예외가 아니다.
        assert self._names(MODERN_GRID, MODERN) == ["풍납1동", "잠실4동"]

    def test_values_are_parsed(self):
        row = next(iter_emd_rows(MODERN_GRID, MODERN, sigungu_match="송파", emd_names=GAP))
        assert (row.eligible_voters, row.total_votes, row.invalid_votes) == (100, 80, 5)
        assert row.votes == [50, 25]

    def test_marker_set_is_configurable(self):
        # 19대는 동 합계 행의 투표구명이 '합계'다. 마커에서 빼면 안 잡혀야 한다.
        rows = list(
            iter_emd_rows(
                MODERN_GRID, MODERN, sigungu_match="송파", emd_names=GAP, total_markers=("소계",)
            )
        )
        assert rows == []


class TestCheckArithmetic:
    def _row(self, **kw):
        base = dict(
            emd_name="풍납1동",
            eligible_voters=100,
            total_votes=80,
            counted_votes=75,
            invalid_votes=5,
            results=[("가당", "김갑"), ("나당", "이을")],
            votes=[50, 25],
        )
        return EmdRow(**{**base, **kw})

    def test_consistent_row_passes(self):
        check_arithmetic(self._row())

    def test_sum_mismatch_points_at_layout(self):
        # 열이 밀리면 여기서 잡힌다. 계약의 합계 검증만으로는 못 잡는 경우가 있다.
        with pytest.raises(ValueError, match="어긋났을"):
            check_arithmetic(self._row(votes=[50, 30]))

    def test_invalid_votes_mismatch_is_caught(self):
        with pytest.raises(ValueError, match="맞지 않는다"):
            check_arithmetic(self._row(invalid_votes=9))
