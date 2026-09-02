"""기준선(상위 행정단위) 합계 추출. 합성 격자로 검증한다.

동별 득표율은 '무엇 대비'가 있어야 지표가 되므로, 같은 파일에서 전국·시도·시군구
합계 행을 함께 읽는다. 33년치 표기가 제각각이라 조건은 meta.yaml 규칙으로 들어온다.
"""

import pytest

from ..rows import (
    BaselineRow,
    BaselineRule,
    Layout,
    check_baseline_arithmetic,
    iter_baseline_rows,
)

LAYOUT = Layout(
    sido=0,
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

# 전국 = 서울(300) + 부산(100). 서울 = 송파구(200) + 강남구(100).
GRID = [
    ["시도명", "구시군명", "읍면동명", "투표구명", "선거인수", "투표수", "", "", "", "무효"],
    ["", "", "", "", "", "", "가당\n김갑", "나당\n이을", "계", ""],
    ["전국", "합계", "", "", "800", "400", "240", "140", "380", "20"],
    ["서울특별시", "합계", "", "", "600", "300", "180", "105", "285", "15"],
    ["서울특별시", "송파구", "합계", "", "400", "200", "120", "70", "190", "10"],
    ["서울특별시", "", "풍납1동", "", "200", "100", "60", "35", "95", "5"],
    ["서울특별시", "", "풍납1동", "1투", "100", "50", "30", "17", "47", "3"],
    ["서울특별시", "강남구", "합계", "", "200", "100", "60", "35", "95", "5"],
    ["부산광역시", "합계", "", "", "200", "100", "60", "35", "95", "5"],
    ["부산광역시", "해운대구", "합계", "", "200", "100", "60", "35", "95", "5"],
]


def run(*rules: BaselineRule) -> dict[str, BaselineRow]:
    return {r.level: r for r in iter_baseline_rows(GRID, LAYOUT, list(rules))}


class TestSingleRowRules:
    def test_nation_row(self):
        out = run(BaselineRule(level="nation", sido="전국", expect=1))
        assert out["nation"].eligible_voters == 800
        assert out["nation"].votes == [240, 140]

    def test_sido_row_uses_prefix(self):
        """'서울' 이 '서울특별시' 를 잡는다. 표기가 회차마다 다르기 때문이다."""
        out = run(BaselineRule(level="sido", sido_prefix="서울", sgg="합계", expect=1))
        assert out["sido"].eligible_voters == 600

    def test_sigungu_row(self):
        out = run(BaselineRule(level="sigungu", sgg="송파구", emd=("합계",), expect=1))
        assert out["sigungu"].eligible_voters == 400


class TestSummingRules:
    """규칙 하나가 여러 행에 맞으면 합산한다 — 1992년 송파구는 '갑'+'을' 로만 존재한다."""

    def test_multiple_matches_are_summed(self):
        """16대는 시도 열이 없어 구 합계를 전부 더해 전국을 만든다."""
        out = run(BaselineRule(level="nation", emd=("합계",), expect=3))
        # 송파 400 + 강남 200 + 해운대 200 = 800 — 파일의 전국 행과 일치한다
        assert out["nation"].matched_rows == 3
        assert out["nation"].eligible_voters == 800
        assert out["nation"].votes == [240, 140]

    def test_forward_fill_carries_merged_cells(self):
        """병합셀은 블록 첫 행에만 값이 있다. 앞의 값을 이어 쓰지 않으면 동이 새어나간다."""
        out = run(BaselineRule(level="sigungu", sgg="송파구", emd=("풍납1동",), expect=2))
        # 구시군 칸이 빈 두 행(동 합계 + 투표구)이 모두 송파구로 이어져야 한다
        assert out["sigungu"].matched_rows == 2


class TestExpectGuard:
    """expect 가 없으면 결함이 조용히 지나간다 — 18대 송파구가 정확히 그랬다."""

    def test_too_many_rows_fails(self):
        with pytest.raises(ValueError, match="2개 행을 잡았는데 1개를 기대했다"):
            run(BaselineRule(level="sigungu", sgg="송파구", emd=("풍납1동",), expect=1))

    def test_too_few_rows_fails(self):
        with pytest.raises(ValueError, match="1개 행을 잡았는데 9개를 기대했다"):
            run(BaselineRule(level="nation", sido="전국", expect=9))

    def test_no_match_fails_loudly(self):
        """기준선이 소리 없이 빠지면 '아직 없어서'인지 '규칙이 틀려서'인지 알 수 없다."""
        with pytest.raises(ValueError, match="맞는 행이 없다"):
            run(BaselineRule(level="sigungu", sgg="없는구"))

    def test_take_first_uses_only_the_leading_row(self):
        """18대는 송파구에 '소계'가 둘이다 — 구 전체와 재외·부재자를 뺀 관내분."""
        out = run(
            BaselineRule(level="sigungu", sgg="송파구", emd=("풍납1동",), expect=2, take_first=True)
        )
        assert out["sigungu"].eligible_voters == 200  # 합산했다면 300
        assert out["sigungu"].matched_rows == 1


class TestArithmetic:
    def test_valid_row_passes(self):
        check_baseline_arithmetic(run(BaselineRule(level="nation", sido="전국"))["nation"])

    def test_vote_sum_mismatch_is_caught(self):
        row = BaselineRow(
            level="nation",
            eligible_voters=800,
            total_votes=400,
            counted_votes=380,
            invalid_votes=20,
            votes=[240, 999],  # 출처의 '계'와 안 맞는다
        )
        with pytest.raises(ValueError, match="출처의 '계'"):
            check_baseline_arithmetic(row)

    def test_turnout_over_100_percent_is_caught(self):
        row = BaselineRow(
            level="nation",
            eligible_voters=100,
            total_votes=400,
            counted_votes=380,
            invalid_votes=20,
            votes=[240, 140],
        )
        with pytest.raises(ValueError, match="선거인수"):
            check_baseline_arithmetic(row)
