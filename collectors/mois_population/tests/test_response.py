"""응답 봉투 열기 — 형식이 여러 가지라서 열어보고 판단한다.

여기 쓰는 데이터는 봉투 '모양'만 흉내낸 합성 데이터다. 필드 의미는 검증하지 않는다
(그건 실제 fixture 를 요구하는 test_parse.py 의 몫이다).
"""

import pytest

from collectors.mois_population.response import (
    ApiError,
    ResponseShapeError,
    extract_rows,
)

ROWS = [{"행정동명": "풍납1동"}, {"행정동명": "풍납2동"}]


@pytest.mark.parametrize(
    "body",
    [
        {"data": ROWS},
        {"response": {"body": {"items": {"item": ROWS}}}},
        {"response": {"body": {"items": ROWS}}},
        {"items": ROWS},
        {"row": ROWS},
    ],
    ids=["odcloud", "표준REST", "표준REST변형", "items", "row"],
)
def test_known_envelopes_are_opened(body):
    assert extract_rows(body) == ROWS


def test_unknown_envelope_is_found_by_search(caplog):
    """모르는 형태여도 찾아내되, 어디서 찾았는지 알려준다."""
    body = {"admmSexdAgePpltn": [{"head": [{"totalCount": 2}]}, {"rows": ROWS}]}
    assert extract_rows(body) == ROWS
    assert "config.data_path" in caplog.text


def test_explicit_path_wins():
    body = {"data": [{"틀린": "목록"}], "진짜": {"목록": ROWS}}
    assert extract_rows(body, "진짜.목록") == ROWS


def test_wrong_explicit_path_is_explicit():
    with pytest.raises(ResponseShapeError, match="data_path"):
        extract_rows({"data": ROWS}, "없는.경로")


def test_api_error_is_raised_not_swallowed():
    """키 미등록·트래픽 초과를 '0건'으로 넘기면 조용히 빈 전략이 나온다."""
    body = {
        "response": {
            "header": {"resultCode": "30", "resultMsg": "SERVICE KEY IS NOT REGISTERED ERROR"}
        }
    }
    with pytest.raises(ApiError, match="SERVICE KEY"):
        extract_rows(body)


def test_normal_result_code_passes():
    body = {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL"},
            "body": {"items": {"item": ROWS}},
        }
    }
    assert extract_rows(body) == ROWS


def test_no_list_at_all_reports_top_level_keys():
    with pytest.raises(ResponseShapeError, match="이상함"):
        extract_rows({"이상함": 1})
