"""화면 — 렌더된 HTML 이 계약을 지키는가.

가장 중요한 두 개는 절대 규칙 5의 회귀 테스트다:
정책표에서 항목을 **지우면** 모든 카드에 경고가 붙어야 하고(fail-closed),
`blocked` 로 바꾸면 payload 의 수치가 HTML 에 **없어야** 한다.

규칙을 문서에만 적으면 지켜지지 않는다. 여기가 집행 지점이다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_web_loader import CODES, profile_record, write_districts
from votelink import store
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.web.app import create_app
from votelink.web.settings import WebSettings

POLICY_CLEARED = (
    "election_day: null\n"
    "outputs:\n"
    "  - kind: segment_profile\n"
    "    risk: low\n"
    "    status: cleared\n"
    '    reviewed_by: "법률검토자"\n'
    '    reviewed_at: "2026-09-10"\n'
)
POLICY_EMPTY = "election_day: null\noutputs: []\n"
POLICY_BLOCKED = (
    "election_day: null\n"
    "outputs:\n"
    "  - kind: segment_profile\n"
    "    risk: high\n"
    "    status: blocked\n"
    '    note: "선거일 전 6일 공표 금지"\n'
)


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def build(tmp_path, policy: str = POLICY_CLEARED, *, records=True) -> TestClient:
    if records:
        store.append_records(
            "voter_profile", [profile_record(c) for c in CODES], root=tmp_path / "records"
        )
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path),
        records_root=tmp_path / "records",
        policy_path=policy_path,
        boundaries_path=tmp_path / "없다.geojson",
    )
    return TestClient(create_app(settings))


# --- 절대 규칙 5의 회귀 테스트 -------------------------------------------------------


def test_removing_the_policy_entry_warns_every_card(tmp_path):
    """정책표에서 지우면 fail-closed 로 전부 경고가 붙는다.

    새 분석기가 새 산출물을 낼 때 아무도 코드를 고치지 않아도 경고가 붙어야 한다.
    이 테스트가 깨지면 규칙 5가 깨진 것이다.
    """
    html = build(tmp_path, POLICY_EMPTY).get("/").text
    assert "선거법 검토를 받지 않은" in html
    assert "정책표에" in html  # 왜 경고인지도 말한다
    assert all(f"동{c[-4:]}" in html for c in CODES)  # 경고와 함께 내용은 보인다


def test_blocked_keeps_the_numbers_out_of_the_html(tmp_path):
    """차단이면 수치가 HTML 에 나가지 않는다. 매크로가 caller() 를 부르지 않는다."""
    html = build(tmp_path, POLICY_BLOCKED).get("/").text

    assert "표시가 차단된 산출물이다" in html
    assert "선거일 전 6일 공표 금지" in html
    # payload 의 값이 하나도 새지 않아야 한다
    assert "70.0" not in html  # turnout
    assert "0.97" not in html  # sex_ratio
    assert "1,000" not in html  # population_total
    assert f"동{CODES[0][-4:]}" not in html


def test_cleared_shows_the_signature_not_a_warning(tmp_path):
    html = build(tmp_path).get("/").text
    assert "검토 완료" in html
    assert "법률검토자" in html
    assert "선거법 검토를 받지 않은" not in html


def test_blocked_map_hides_values_too(tmp_path):
    """규칙 5는 화면마다 다시 구현되지 않는다. 같은 매크로를 쓴다."""
    html = build(tmp_path, POLICY_BLOCKED).get("/map").text
    assert "표시가 차단된 산출물이다" in html
    assert '<svg class="map"' not in html


# --- 대시보드 --------------------------------------------------------------------


def test_dashboard_lists_every_dong(tmp_path):
    response = build(tmp_path).get("/")
    assert response.status_code == 200
    for code in CODES:
        assert f"동{code[-4:]}" in response.text


def test_dashboard_shows_loaded_over_expected(tmp_path):
    """'3 / 3'. 둘 다 보여준다 — 다르면 결측이다."""
    assert "3 / 3" in build(tmp_path).get("/").text


def test_missing_dong_is_called_out(tmp_path):
    store.append_records("voter_profile", [profile_record(CODES[0])], root=tmp_path / "records")
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(POLICY_CLEARED, encoding="utf-8")
    client = TestClient(
        create_app(
            WebSettings(
                districts_path=write_districts(tmp_path),
                records_root=tmp_path / "records",
                policy_path=policy_path,
                boundaries_path=tmp_path / "없다.geojson",
            )
        )
    )
    html = client.get("/").text
    assert "1 / 3" in html
    assert "분석 결과가 없는 행정동" in html


def test_sort_changes_the_order(tmp_path):
    client = build(tmp_path)
    assert client.get("/?sort=swing").status_code == 200
    assert client.get("/?sort=말도안되는키").status_code == 200  # 정렬 때문에 죽지 않는다


def test_empty_state_points_at_the_analyzer(tmp_path):
    """서버가 안 뜨면 왜 비었는지 볼 화면조차 없다."""
    response = build(tmp_path, records=False).get("/")
    assert response.status_code == 200
    assert "표시할 분석 결과가 없다" in response.text
    assert "votelink analyze voter_profile" in response.text


# --- 지도 -----------------------------------------------------------------------


def test_map_renders_with_each_metric(tmp_path):
    client = build(tmp_path)
    for metric in ("gap_district", "conservative", "swing", "turnout"):
        response = client.get(f"/map?metric={metric}")
        assert response.status_code == 200, metric
        assert 'id="hatch"' in response.text  # 값 없음 무늬는 항상 정의돼 있다


def test_map_legend_shows_real_numbers(tmp_path):
    """색만 보여주면 크기를 알 수 없다."""
    html = build(tmp_path).get("/map?metric=turnout").text
    assert "70.0 ~ 70.0%" in html
    assert "3곳 중 3곳" in html  # 분모


def test_map_says_it_is_not_a_real_boundary(tmp_path):
    assert "실제 행정동 경계가 아니다" in build(tmp_path).get("/map").text


def test_unknown_metric_falls_back(tmp_path):
    assert build(tmp_path).get("/map?metric=없는지표").status_code == 200


# --- 로컬 원칙 -------------------------------------------------------------------


def test_no_external_requests(tmp_path):
    """외부 요청 0건이어야 캠프의 열람 맥락이 제3자에게 새지 않는다."""
    client = build(tmp_path)
    for url in ("/", "/map"):
        html = client.get(url).text
        # 절대 URL 이 하나도 없어야 한다. CSS·SVG 전부 같은 출처이거나 인라인이다.
        assert "http://" not in html, url
        assert "https://" not in html, url
        assert "//" not in html.replace("</", "").replace("<!--", ""), url


def test_api_docs_are_off(tmp_path):
    """Swagger UI 가 CDN 에서 스크립트를 받아온다. 그 경로를 아예 없앤다."""
    client = build(tmp_path)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_healthz(tmp_path):
    response = build(tmp_path).get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


# --- 읽기 전용 -------------------------------------------------------------------


def test_serving_never_writes(tmp_path):
    """L3는 쓰지 않는다. 요청 전후로 파일 목록과 mtime 이 같아야 한다."""
    client = build(tmp_path)
    root = tmp_path / "records"
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}

    for url in ("/", "/map", "/?sort=swing", "/map?metric=swing", "/healthz"):
        assert client.get(url).status_code == 200

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}
    assert before == after


# --- 설정 오류 -------------------------------------------------------------------


def test_missing_policy_file_shows_what_to_fix(tmp_path):
    """규칙 5를 집행할 근거가 없으면 조용히 통과시키지 않는다."""
    store.append_records("voter_profile", [profile_record(CODES[0])], root=tmp_path / "records")
    client = TestClient(
        create_app(
            WebSettings(
                districts_path=write_districts(tmp_path),
                records_root=tmp_path / "records",
                policy_path=tmp_path / "없다.yaml",
                boundaries_path=tmp_path / "없다.geojson",
            )
        ),
        raise_server_exceptions=False,
    )
    response = client.get("/")
    assert response.status_code == 500
    assert "화면을 그릴 수 없다" in response.text
    assert "compliance.yaml" in response.text
