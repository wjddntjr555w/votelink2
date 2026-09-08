"""전국 전체 동 화면 (`/nation`).

선거구 소속 필터를 의도적으로 건너뛴다 — 전국은 선거구 하나가 아니다.
편차는 전국 대비만 유효하다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_web import POLICY_BLOCKED, POLICY_CLEARED
from tests.test_web_loader import CODES, OUTSIDE, profile_record, write_districts
from votelink import store
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.settings import WebSettings


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def build(tmp_path, records, policy: str = POLICY_CLEARED) -> TestClient:
    store.append_records("voter_profile", records, DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_nation_shows_dongs_from_outside_the_configured_district(tmp_path):
    html = build(tmp_path, [profile_record(CODES[0]), profile_record(OUTSIDE)]).get("/nation").text
    assert f"동{CODES[0][-4:]}" in html
    assert f"동{OUTSIDE[-4:]}" in html  # 선거구 밖인데도 나온다
    assert "표시 2곳" in html


def test_nation_cards_only_carry_the_nation_gap(tmp_path):
    html = build(tmp_path, [profile_record(CODES[0])]).get("/nation").text
    assert "전국" in html
    assert "시험구 대비" not in html  # sigungu 편차는 전국 화면에 없다


def test_nation_dedups_to_newest_as_of(tmp_path):
    client = build(
        tmp_path,
        [profile_record(CODES[0], "2024-12"), profile_record(CODES[0], "2025-03")],
    )
    html = client.get("/nation").text
    assert "표시 1곳" in html
    assert "이전 기준월 1건" in html


def test_nation_blocked_keeps_numbers_out(tmp_path):
    html = build(tmp_path, [profile_record(CODES[0])], POLICY_BLOCKED).get("/nation").text
    assert "표시가 차단된 산출물이다" in html
    assert "70.0" not in html


def test_nation_empty_for_a_type_with_no_data(tmp_path):
    html = build(tmp_path, [profile_record(CODES[0])]).get("/nation?election_type=local").text
    assert "분석 결과가 없다" in html
