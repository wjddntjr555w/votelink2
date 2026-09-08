"""선거구 비교 화면 (`/compare`).

여러 선거구를 각각 근사 집계해 한 표로 놓는다. 데이터가 없는 선거구는 사유와 함께
목록에 남긴다 — 조용히 빠지지 않는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_web import POLICY_BLOCKED, POLICY_LOW, REVIEW_CLEARED, REVIEW_NONE
from tests.test_web_loader import CODES, profile_record, write_districts
from votelink import store
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.settings import WebSettings

EXTRA = (
    "  - id: test_eul\n"
    "    name: 시험 지역구 을\n"
    "    sido: 시험시\n"
    "    sigungu: 시험구\n"
    "    emd:\n"
    '      - {name: 딴동, code: "1171057000"}\n'
)


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def build(tmp_path, policy: str = POLICY_LOW, *, review: str = REVIEW_CLEARED) -> TestClient:
    store.append_records("voter_profile", [profile_record(c) for c in CODES], DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.policy.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    review_path = tmp_path / "compliance.review.yaml"
    review_path.write_text(review, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path, extra=EXTRA),
        data_root=tmp_path,
        policy_path=policy_path,
        review_path=review_path,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_compare_shows_one_row_and_skips_the_rest(tmp_path):
    html = build(tmp_path).get("/compare").text
    assert "시험 지역구 갑" in html
    assert "제외된 선거구" in html
    assert "시험 지역구 을" in html
    assert "voter_profile --district test_eul" in html  # 조치


def test_compare_sort_key_garbage_does_not_crash(tmp_path):
    assert build(tmp_path).get("/compare?sort=말도안되는키").status_code == 200


def test_compare_blocked_keeps_numbers_out(tmp_path):
    html = build(tmp_path, POLICY_BLOCKED, review=REVIEW_NONE).get("/compare").text
    assert "표시가 차단된 산출물이다" in html
    assert "<table" not in html  # 표 자체가 안 나간다


def test_compare_for_a_type_with_no_data_is_all_skipped(tmp_path):
    html = build(tmp_path).get("/compare?election_type=national_assembly").text
    assert "비교할 선거구가 없다" in html
