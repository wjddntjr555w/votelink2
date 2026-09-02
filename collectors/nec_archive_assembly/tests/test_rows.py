"""레이아웃 해석은 응답 형식과 무관한 순수 로직이라 합성 데이터로 검증한다.

대선(nec_archive)과 가장 다른 지점 두 개를 특히 다룬다:
1. 후보 열 폭이 지역구마다 달라 `계` 라벨로 동적으로 찾는다
2. 22대(block_start 모드)는 후보 이름이 지역구 블록의 첫 행에만 있다
"""

import pytest

from ..rows import (
    DistrictRow,
    Layout,
    candidate_columns,
    check_arithmetic,
    find_total_column,
    iter_district_rows,
    normalize_emd,
)

EMD_NAMES = {"풍납1동", "잠실6동"}

# --- 18~21대 유형: 파일/시트가 이미 지역구 하나. 정당\n후보 병합, 패딩 없음 ---
STATIC = Layout(emd=0, precinct=1, eligible=2, votes=3, candidate_from=4, label_row=1, data_from=2)
STATIC_GRID = [
    ["읍면동명", "투표구명", "선거인수", "투표수", "", "", ""],
    ["", "", "", "", "가당\n김갑", "나당\n이을", "계"],
    ["풍납1동", "소계", "100", "80", "50", "25", "75"],
    ["풍납1동", "관내사전투표", "20", "20", "12", "7", "19"],  # 투표구 → 버림
    ["잠실6동", "소계", "200", "120", "70", "45", "115"],
]

# --- 22대 유형: 전국 단일 파일. district_col 로 걸러내고, 후보 이름은 지역구
#     블록 첫 행에만 있다. 패딩된 빈 후보 슬롯이 있다 ---
BLOCK_START = Layout(
    emd=3,
    precinct=4,
    eligible=5,
    votes=6,
    candidate_from=7,
    label_row=0,  # 파일 전체 공용 헤더 (행 0)
    data_from=1,
    district_col=1,
    candidate_from_block_start=True,
)
BLOCK_START_GRID = [
    ["시도", "선거구명", "구", "동", "타입", "선거인수", "투표수", "", "", "계", "무효"],
    ["서울", "강남구갑", "강남구", "", "", "", "", "김강남", "", "999", "0"],  # 다른 지역구
    ["", "", "", "삼성동", "소계", "999", "999", "999", "", "999", "0"],
    ["서울", "송파구갑", "송파구", "", "", "", "", "가당\n김갑", "나당\n이을", "", ""],
    ["", "", "", "풍납1동", "소계", "100", "80", "50", "25", "75", "0"],
    ["", "", "", "풍납1동", "제1투", "40", "30", "20", "9", "29", "1"],  # 투표구 → 버림
    ["", "", "", "잠실6동", "소계", "200", "120", "70", "45", "115", "5"],
]


class TestFindTotalColumn:
    def test_finds_the_label(self):
        assert find_total_column(["a", "b", "계"], 0, "계") == 2

    def test_missing_label_is_an_error(self):
        with pytest.raises(ValueError, match="라벨을 못 찾았다"):
            find_total_column(["a", "b"], 0, "계")


class TestCandidateColumnsStatic:
    def test_reads_merged_party_candidate(self):
        total = find_total_column(STATIC_GRID[1], 4, "계")
        cols = candidate_columns(STATIC_GRID, STATIC, total, name_row=1)
        assert cols == [("가당", "김갑"), ("나당", "이을")]

    def test_offset_row_reads_names_separately(self):
        """18대: 정당 행과 후보 이름 행이 분리돼 있다."""
        layout = Layout(
            emd=0,
            precinct=1,
            eligible=2,
            votes=3,
            candidate_from=4,
            label_row=1,
            candidate_name_row_offset=1,
            data_from=3,
        )
        grid = [
            ["읍면동명", "투표구명", "선거인수", "투표수", "", "", ""],
            ["", "", "", "", "통합민주당", "한나라당", "계"],
            ["", "", "", "", "정직", "박영아", ""],
        ]
        total = find_total_column(grid[1], 4, "계")
        cols = candidate_columns(grid, layout, total, name_row=1)
        assert cols == [("통합민주당", "정직"), ("한나라당", "박영아")]


class TestCandidateColumnsPadding:
    """22대처럼 최대 후보 수에 맞춰 열을 넉넉히 두고 빈 슬롯을 남기는 파일."""

    def test_blank_slots_are_skipped(self):
        row = ["가당\n김갑", "나당\n이을", "", "", "계"]
        layout = Layout(
            emd=0, precinct=1, eligible=2, votes=3, candidate_from=0, label_row=0, data_from=1
        )
        total = find_total_column(row, 0, "계")
        cols = candidate_columns([row], layout, total, name_row=0)
        assert cols == [("가당", "김갑"), ("나당", "이을")]


class TestIterDistrictRowsStatic:
    def test_extracts_only_emd_totals(self):
        rows = list(
            iter_district_rows(STATIC_GRID, STATIC, emd_names=EMD_NAMES, district_name=None)
        )
        assert [r.emd_name for r in rows] == ["풍납1동", "잠실6동"]
        assert rows[0].eligible_voters == 100
        assert rows[0].votes == [50, 25]
        assert rows[0].counted_votes == 75

    def test_precinct_rows_are_excluded(self):
        """투표구 행이 섞이면 득표가 두 배가 된다."""
        rows = list(
            iter_district_rows(STATIC_GRID, STATIC, emd_names=EMD_NAMES, district_name=None)
        )
        assert len(rows) == 2  # 관내사전투표 행이 안 들어왔다


class TestIterDistrictRowsBlockStart:
    def test_district_col_filters_to_target(self):
        """다른 지역구(강남구갑)가 섞여 있어도 격리 없이 걸러진다."""
        rows = list(
            iter_district_rows(
                BLOCK_START_GRID, BLOCK_START, district_name="송파구갑", emd_names=EMD_NAMES
            )
        )
        assert [r.emd_name for r in rows] == ["풍납1동", "잠실6동"]

    def test_candidate_names_come_from_the_blocks_own_first_row(self):
        """지역구마다 후보가 다르다 — 강남구갑('김강남')이 아니라 송파구갑
        블록 첫 행('가당 김갑'·'나당 이을')의 이름이 나와야 한다."""
        rows = list(
            iter_district_rows(
                BLOCK_START_GRID, BLOCK_START, district_name="송파구갑", emd_names=EMD_NAMES
            )
        )
        assert rows[0].results == [("가당", "김갑"), ("나당", "이을")]

    def test_padded_blank_columns_do_not_appear_in_votes(self):
        """빈 슬롯을 후보로 세면 results 와 votes 길이가 어긋난다."""
        rows = list(
            iter_district_rows(
                BLOCK_START_GRID, BLOCK_START, district_name="송파구갑", emd_names=EMD_NAMES
            )
        )
        assert len(rows[0].votes) == len(rows[0].results) == 2


class TestNormalizeEmd:
    def test_je_dong_suffix(self):
        assert normalize_emd("풍납제1동") == "풍납1동"

    def test_already_normalized(self):
        assert normalize_emd("잠실6동") == "잠실6동"


class TestCheckArithmetic:
    def test_valid_row_passes(self):
        check_arithmetic(
            DistrictRow(
                emd_name="풍납1동",
                eligible_voters=100,
                total_votes=80,
                counted_votes=75,
                invalid_votes=5,
                votes=[50, 25],
            )
        )

    def test_vote_sum_mismatch_is_caught(self):
        with pytest.raises(ValueError, match="출처의 '계'"):
            check_arithmetic(
                DistrictRow(
                    emd_name="풍납1동",
                    eligible_voters=100,
                    total_votes=80,
                    counted_votes=75,
                    invalid_votes=5,
                    votes=[50, 999],
                )
            )

    def test_turnout_over_100_percent_is_caught(self):
        with pytest.raises(ValueError, match="선거인수"):
            check_arithmetic(
                DistrictRow(
                    emd_name="풍납1동",
                    eligible_voters=10,
                    total_votes=80,
                    counted_votes=75,
                    invalid_votes=5,
                    votes=[50, 25],
                )
            )
