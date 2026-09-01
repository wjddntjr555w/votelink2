"""행 접기 로직 — 응답 형식과 무관한 산수라 합성 데이터로 검증한다.

docs/20-collector-spec.md §7: 재집계·환산 같은 순수 로직은 별도 함수로 빼서
합성 데이터로 검증해도 된다. 출처 형식 자체의 검증은 test_parse.py 가 한다.
"""

import pytest

from collectors.nec_election_result.rows import (
    ColumnMissing,
    EmdTally,
    pick_column,
    split_party,
    tally_rows,
    to_int,
)

AGG = {
    "eligible_voters": "선거인수",
    "total_votes": "투표수",
    "invalid_votes": "무효 투표수",
    "abstained": "기권자수",
}


def row(emd, item, count, precinct="제1투"):
    return {"읍면동명": emd, "투표구명": precinct, "후보자": item, "득표수": count}


@pytest.mark.parametrize(
    ("given", "expected"),
    [("1,234", 1234), (" 5 678 ", 5678), ("", 0), (None, 0), ("0", 0), (42, 42)],
)
def test_to_int_tolerates_source_dirtiness(given, expected):
    assert to_int(given) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("더불어민주당 조재희", ("더불어민주당", "조재희")),
        ("무소속 송진호", ("무소속", "송진호")),
        ("개혁신당 송재열", ("개혁신당", "송재열")),
    ],
)
def test_split_party(label, expected):
    assert split_party(label) == expected


def test_split_party_rejects_unexpected_shape():
    """'정당 후보명' 형태가 아니면 조용히 넘기지 않는다."""
    with pytest.raises(ValueError, match="형태가 아니다"):
        split_party("선거인수")


def test_pick_column_takes_first_present():
    """총선은 '법정읍면동명', 대선은 '읍면동명' 이다. 파일마다 다른 컬럼명을 흡수한다."""
    header = ["구시군명", "읍면동명"]
    assert pick_column(header, ["법정읍면동명", "읍면동명"], "읍면동") == "읍면동명"


def test_pick_column_reports_what_it_looked_for():
    with pytest.raises(ColumnMissing, match="읍면동"):
        pick_column(["시도명"], ["법정읍면동명", "읍면동명"], "읍면동")


def test_precinct_rows_are_folded_into_one_dong():
    """한 동의 투표구 여러 개가 하나로 접혀야 한다."""
    rows = []
    for p in ("제1투", "제2투"):
        rows += [
            row("풍납1동", "선거인수", 100, p),
            row("풍납1동", "투표수", 70, p),
            row("풍납1동", "더불어민주당 조재희", 40, p),
            row("풍납1동", "국민의힘 박정훈", 25, p),
            row("풍납1동", "무효 투표수", 5, p),
            row("풍납1동", "기권자수", 30, p),
        ]
    tallies = tally_rows(
        rows,
        emd_col="읍면동명",
        item_col="후보자",
        count_col="득표수",
        keep={"풍납1동"},
        agg_items=AGG,
    )
    assert list(tallies) == ["풍납1동"]
    t = tallies["풍납1동"]
    assert (t.eligible_voters, t.total_votes, t.invalid_votes, t.abstained) == (200, 140, 10, 60)
    assert t.candidates == {"더불어민주당 조재희": 80, "국민의힘 박정훈": 50}
    t.check()


def test_rows_outside_the_district_are_dropped():
    """관외사전투표 같은 비행정동 항목은 버린다 (격리하지 않는다)."""
    rows = [
        row("풍납1동", "투표수", 70),
        row("관외사전투표", "투표수", 999, ""),
        row("거소·선상투표", "투표수", 12, ""),
        row("잠실2동", "투표수", 500),  # 송파을 소속 — 대상 아님
    ]
    tallies = tally_rows(
        rows,
        emd_col="읍면동명",
        item_col="후보자",
        count_col="득표수",
        keep={"풍납1동"},
        agg_items=AGG,
    )
    assert list(tallies) == ["풍납1동"]
    assert tallies["풍납1동"].total_votes == 70


def test_results_are_sorted_by_votes_desc():
    t = EmdTally(emd="풍납1동", candidates={"A당 가": 10, "B당 나": 30, "C당 다": 20})
    assert [r["candidate"] for r in t.results()] == ["나", "다", "가"]


def test_check_names_the_dong_when_arithmetic_breaks():
    """계약 모델도 같은 검증을 하지만, 어느 동인지는 여기서만 알려준다."""
    t = EmdTally(emd="풍납1동", total_votes=100, invalid_votes=5, candidates={"A당 가": 90})
    with pytest.raises(ValueError, match="풍납1동.*95.*100"):
        t.check()


def test_check_catches_elector_mismatch():
    t = EmdTally(
        emd="방이1동",
        eligible_voters=200,
        total_votes=100,
        invalid_votes=0,
        abstained=50,  # 100+50 != 200
        candidates={"A당 가": 100},
    )
    with pytest.raises(ValueError, match="방이1동.*선거인수"):
        t.check()
