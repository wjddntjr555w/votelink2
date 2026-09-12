"""전국 전체 동 화면 (`/nation`).

선거구 소속 필터를 의도적으로 건너뛴다 — 전국은 선거구 하나가 아니다.
편차는 전국 대비만 유효하다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_web import POLICY_BLOCKED, POLICY_LOW, REVIEW_CLEARED, REVIEW_NONE
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


def build(
    tmp_path, records, policy: str = POLICY_LOW, *, review: str = REVIEW_CLEARED
) -> TestClient:
    store.append_records("voter_profile", records, DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.policy.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    review_path = tmp_path / "compliance.review.yaml"
    review_path.write_text(review, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
        review_path=review_path,
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


# `/nation` 은 빌드된 SPA 셸만 돌려준다. 데이터·회귀 테스트는 `/api/nation` 을 본다.


def test_nation_screen_serves_the_spa_shell(tmp_path):
    assert build(tmp_path, [profile_record(CODES[0])]).get("/nation").status_code == 200


def test_nation_shows_dongs_from_outside_the_configured_district(tmp_path):
    view = build(tmp_path, [profile_record(CODES[0]), profile_record(OUTSIDE)]).get(
        "/api/nation"
    ).json()["view"]
    geo_names = {c["geo_name"] for c in view["cards"]}
    assert f"동{CODES[0][-4:]}" in geo_names
    assert f"동{OUTSIDE[-4:]}" in geo_names  # 선거구 밖인데도 나온다
    assert view["diagnostics"]["loaded"] == 2


def test_nation_cards_only_carry_the_nation_gap(tmp_path):
    view = build(tmp_path, [profile_record(CODES[0])]).get("/api/nation").json()["view"]
    gaps = view["cards"][0]["gaps"]
    assert "nation" in gaps
    assert "sigungu" not in gaps  # sigungu 편차는 전국 화면에 없다


def test_nation_dedups_to_newest_as_of(tmp_path):
    client = build(
        tmp_path,
        [profile_record(CODES[0], "2024-12"), profile_record(CODES[0], "2025-03")],
    )
    view = client.get("/api/nation").json()["view"]
    assert view["diagnostics"]["loaded"] == 1
    assert view["diagnostics"]["superseded"] == 1


def test_nation_blocked_keeps_numbers_out(tmp_path):
    view = (
        build(tmp_path, [profile_record(CODES[0])], POLICY_BLOCKED, review=REVIEW_NONE)
        .get("/api/nation")
        .json()["view"]
    )
    assert view["verdict"]["status"] == "blocked"
    assert view["cards"] == []
    assert view["summary_card"] is None


def test_nation_empty_for_a_type_with_no_data(tmp_path):
    view = build(tmp_path, [profile_record(CODES[0])]).get(
        "/api/nation?election_type=local"
    ).json()["view"]
    assert view["cards"] == []
