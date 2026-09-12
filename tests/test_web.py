"""화면 — 렌더된 HTML 이 계약을 지키는가.

가장 중요한 두 개는 절대 규칙 5의 회귀 테스트다:
정책표에서 항목을 **지우면** 모든 카드에 경고가 붙어야 하고(fail-closed),
`blocked` 로 바꾸면 payload 의 수치가 HTML 에 **없어야** 한다.

규칙을 문서에만 적으면 지켜지지 않는다. 여기가 집행 지점이다.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from tests.test_web_loader import CODES, profile_record, write_districts
from votelink import store
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.settings import WebSettings
from votelink.web.viewmodel import DEFAULT_METRIC

# 정책(공용)은 산출물의 성질만, 검토 기록(캠프)은 서명만 담는다 (P-001 §13).
POLICY_LOW = "outputs:\n  - kind: segment_profile\n    risk: low\n"
POLICY_EMPTY = "outputs: []\n"
POLICY_BLOCKED = (
    "outputs:\n"
    "  - kind: segment_profile\n"
    "    risk: high\n"
    "    default_status: blocked\n"
    '    note: "선거일 전 6일 공표 금지"\n'
)
"""고위험 산출물은 캠프 검토가 없으면 blocked 로 시작한다 (`90-compliance.md §5`)."""

REVIEW_CLEARED = (
    "outputs:\n"
    "  - kind: segment_profile\n"
    "    status: cleared\n"
    '    reviewed_by: "법률검토자"\n'
    '    reviewed_at: "2026-09-10"\n'
)
REVIEW_NONE = "outputs: []\n"


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def build(
    tmp_path,
    policy: str = POLICY_LOW,
    *,
    review: str = REVIEW_CLEARED,
    records=True,
) -> TestClient:
    if records:
        store.append_records(
            "voter_profile", [profile_record(c) for c in CODES], DataSpace(tmp_path)
        )
    policy_path = tmp_path / "compliance.policy.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    review_path = tmp_path / "compliance.review.yaml"
    review_path.write_text(review, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
        review_path=review_path,
        boundaries_path=tmp_path / "없다.geojson",
    )
    return TestClient(create_app(settings))


# --- 절대 규칙 5의 회귀 테스트 -------------------------------------------------------


def test_removing_the_policy_entry_warns_every_card(tmp_path):
    """정책표에서 지우면 fail-closed 로 전부 경고가 붙는다.

    새 분석기가 새 산출물을 낼 때 아무도 코드를 고치지 않아도 경고가 붙어야 한다.
    이 테스트가 깨지면 규칙 5가 깨진 것이다.

    대시보드는 1단계부터 React SPA 다(`/d/test_gap/` 는 빌드된 셸만 돌려준다) —
    데이터는 `/api/d/test_gap` 이 낸다. 회귀 테스트는 그 JSON 을 본다.
    """
    data = build(tmp_path, POLICY_EMPTY).get("/api/d/test_gap").json()
    view = data["view"]
    assert view["verdict"]["status"] == "unreviewed"
    assert any("정책표에" in r for r in view["verdict"]["reasons"])  # 왜 경고인지도 말한다
    geo_names = {c["geo_name"] for c in view["cards"]}
    assert all(f"동{c[-4:]}" in geo_names for c in CODES)  # 경고와 함께 내용은 보인다


def test_blocked_keeps_the_numbers_out_of_the_json(tmp_path):
    """차단이면 수치가 JSON 에도 나가지 않는다 — 프런트가 숨기는 게 아니라

    서버가 애초에 안 보낸다(`_redact_district_view`, `votelink/web/app.py`).
    """
    response = build(tmp_path, POLICY_BLOCKED, review=REVIEW_NONE).get("/api/d/test_gap")
    raw = response.text
    view = response.json()["view"]

    assert view["verdict"]["status"] == "blocked"
    assert any("선거일 전 6일 공표 금지" in r for r in view["verdict"]["reasons"])
    # payload 의 값이 하나도 새지 않아야 한다 — 전체 응답 텍스트를 통째로 본다.
    assert "70.0" not in raw  # turnout
    assert "0.97" not in raw  # sex_ratio
    assert view["cards"] == []
    assert view["population_total"] == 0
    assert view["situation"] is None
    assert f"동{CODES[0][-4:]}" not in raw


# 옛 `test_the_output_macro_refuses_a_missing_verdict` — "판정 없음은 '안전'이 아니라
# '모름'이다"(P-002 §10) 회귀 테스트 — 는 여기 없다. 마지막까지 그 매크로
# (`_output.html`)를 쓰던 화면(운영자 콘솔)이 React 로 옮겨가면서 매크로 자체가
# 죽은 코드가 됐다(삭제함). 같은 보장은 이제 `frontend/src/components/compliance/
# ComplianceGate.test.tsx` 가 진다 — 그쪽이 절대 규칙 5 에서 가장 두껍게 테스트된
# 컴포넌트다.


def test_cleared_shows_the_signature_not_a_warning(tmp_path):
    verdict = build(tmp_path).get("/api/d/test_gap").json()["view"]["verdict"]
    assert verdict["status"] == "cleared"
    assert verdict["reviewed_by"] == "법률검토자"


def test_blocked_map_hides_values_too(tmp_path):
    """규칙 5는 화면마다 다시 구현되지 않는다 — `_redact_output` 을 대시보드와 지도가 같이 쓴다."""
    data = build(tmp_path, POLICY_BLOCKED, review=REVIEW_NONE).get("/api/d/test_gap/map").json()
    assert data["map"]["verdict"]["status"] == "blocked"
    assert data["map"]["cells"] == []
    assert data["map"]["legend"] == []


# --- 대시보드 (JSON API, 1단계부터 React SPA) --------------------------------------
#
# `/d/{id}/` 는 빌드된 SPA 셸만 돌려준다(FRONTEND_DIST/index.html). 데이터·회귀
# 테스트는 `/api/d/{id}` 를 본다 — 계산은 여전히 viewmodel.py 순수 함수가 한다.


def test_dashboard_lists_every_dong(tmp_path):
    response = build(tmp_path).get("/api/d/test_gap")
    assert response.status_code == 200
    geo_names = {c["geo_name"] for c in response.json()["view"]["cards"]}
    for code in CODES:
        assert f"동{code[-4:]}" in geo_names


def test_dashboard_shows_loaded_over_expected(tmp_path):
    """'3 / 3'. 둘 다 보여준다 — 다르면 결측이다."""
    assert build(tmp_path).get("/api/d/test_gap").json()["view"]["coverage_text"] == "3 / 3"


def test_missing_dong_is_called_out(tmp_path):
    store.append_records("voter_profile", [profile_record(CODES[0])], DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(POLICY_LOW, encoding="utf-8")
    client = TestClient(
        create_app(
            WebSettings(
                districts_path=write_districts(tmp_path),
                data_root=tmp_path,
                policy_path=policy_path,
                boundaries_path=tmp_path / "없다.geojson",
            )
        )
    )
    view = client.get("/api/d/test_gap").json()["view"]
    assert view["coverage_text"] == "1 / 3"
    assert len(view["diagnostics"]["missing_codes"]) > 0


def test_sort_changes_the_order(tmp_path):
    client = build(tmp_path)
    assert client.get("/api/d/test_gap?sort=swing").status_code == 200
    # 정렬 키가 이상해도 죽지 않는다
    assert client.get("/api/d/test_gap?sort=말도안되는키").status_code == 200


def test_dashboard_shows_a_district_summary_card(tmp_path):
    """동 카드 위에 선거구 전체를 묶은 근사 집계 한 장."""
    view = build(tmp_path).get("/api/d/test_gap").json()["view"]
    assert view["summary_card"]["label"] == "시험 지역구 갑 종합"
    assert view["summary_card"]["approx"] is True


def test_election_type_switcher_offers_all_four(tmp_path):
    data = build(tmp_path).get("/api/d/test_gap").json()
    labels = {label for _, label in data["election_types"]}
    assert labels == {"대선", "총선", "지방선거", "재보궐"}


def test_requesting_a_type_with_no_data_shows_empty_state(tmp_path):
    client = build(tmp_path)
    r = client.get("/api/d/test_gap?election_type=national_assembly")
    assert r.status_code == 200
    view = r.json()["view"]
    assert view["is_empty"] is True
    assert view["election_type_label"] == "총선"
    # 쓰레기 값은 기본값으로 떨어진다
    assert client.get("/api/d/test_gap?election_type=쓰레기").status_code == 200


def test_empty_state_points_at_the_analyzer(tmp_path):
    """서버가 안 뜨면 왜 비었는지 볼 화면조차 없다."""
    response = build(tmp_path, records=False).get("/api/d/test_gap")
    assert response.status_code == 200
    view = response.json()["view"]
    assert view["is_empty"] is True
    assert view["election_type_label"] == "대선"  # 어느 계열이 비었는지 말해준다
    assert view["diagnostics"]["expected"] > 0


# --- 지도 (JSON API, React SPA) --------------------------------------------------
#
# `/d/{id}/map` 은 빌드된 SPA 셸만 돌려준다. 데이터·회귀 테스트는 `/api/d/{id}/map` 을 본다.


def test_map_renders_with_each_metric(tmp_path):
    client = build(tmp_path)
    for metric in ("gap_district", "conservative", "swing", "turnout"):
        response = client.get(f"/api/d/test_gap/map?metric={metric}")
        assert response.status_code == 200, metric
        assert response.json()["map"]["metric"]["key"] == metric


def test_map_legend_shows_real_numbers(tmp_path):
    """색만 보여주면 크기를 알 수 없다."""
    data = build(tmp_path).get("/api/d/test_gap/map?metric=turnout").json()["map"]
    assert data["v_min"] == 70.0
    assert data["v_max"] == 70.0
    assert data["known"] == 3
    assert data["total"] == 3


def test_map_says_it_is_not_a_real_boundary(tmp_path):
    data = build(tmp_path).get("/api/d/test_gap/map").json()["map"]
    assert data["is_real_boundary"] is False


def test_unknown_metric_falls_back(tmp_path):
    data = build(tmp_path).get("/api/d/test_gap/map?metric=없는지표").json()["map"]
    assert data["metric"]["key"] == DEFAULT_METRIC


def test_map_screen_serves_the_spa_shell(tmp_path):
    assert build(tmp_path).get("/d/test_gap/map").status_code == 200


# --- 로컬 원칙 -------------------------------------------------------------------


# 2026-09-12 결정 — 외부 요청 0건 원칙을 화이트리스트로 완화했다
# (docs/40-webapp-spec.md §10). 이 목록 밖 도메인은 여전히 금지.
ALLOWED_EXTERNAL_HOSTS = {"cdn.tailwindcss.com", "cdnjs.cloudflare.com"}

_ABSOLUTE_URL_RE = re.compile(r'https?://([^"\'\s/]+)')


def test_no_external_requests(tmp_path):
    """화이트리스트 밖 외부 요청이 있으면 캠프의 열람 맥락이 제3자에게 샌다."""
    client = build(tmp_path)
    for url in ("/", "/d/test_gap/", "/d/test_gap/map", "/compare", "/nation"):
        html = client.get(url).text
        assert "http://" not in html, url  # 비TLS는 화이트리스트여도 금지
        # 프로토콜-상대 URL(//host/...)도 절대 URL과 같은 효과라 같은 화이트리스트를 지킨다.
        assert not re.search(r"""(href|src)=["']//""", html), url
        for host in _ABSOLUTE_URL_RE.findall(html):
            assert host in ALLOWED_EXTERNAL_HOSTS, (url, host)


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

    urls = (
        "/",
        "/d/test_gap/",
        "/d/test_gap/?sort=swing",
        "/d/test_gap/map?metric=swing",
        "/compare",
        "/nation",
        "/healthz",
    )
    for url in urls:
        assert client.get(url).status_code == 200

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}
    assert before == after


# --- 다지역구 -----------------------------------------------------------------

TWO_DISTRICTS_EXTRA = (
    "  - id: test_eul\n"
    "    name: 시험 지역구 을\n"
    "    sido: 시험시\n"
    "    sigungu: 시험구\n"
    "    emd:\n"
    '      - {name: 딴동, code: "1171057000"}\n'
)


def build_two(tmp_path) -> TestClient:
    store.append_records("voter_profile", [profile_record(c) for c in CODES], DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(POLICY_LOW, encoding="utf-8")
    settings = WebSettings(
        districts_path=write_districts(tmp_path, extra=TWO_DISTRICTS_EXTRA),
        data_root=tmp_path,
        policy_path=policy_path,
        boundaries_path=tmp_path / "없다.geojson",
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_root_offers_a_choice_when_there_are_several(tmp_path):
    """선거구가 여럿이면 조용히 첫 번째를 열지 않고 고르게 한다 — `/` 는 React
    셸(200, 리다이렉트 아님)을 돌려주고, 목록 자체는 `/api/districts` 가 낸다."""
    client = build_two(tmp_path)
    assert client.get("/", follow_redirects=False).status_code == 200
    districts = dict(client.get("/api/districts").json()["districts"])
    assert districts["test_gap"] == "시험 지역구 갑"
    assert districts["test_eul"] == "시험 지역구 을"


def test_each_district_renders_on_its_own_path(tmp_path):
    client = build_two(tmp_path)
    assert client.get("/d/test_gap/").status_code == 200
    assert client.get("/d/test_eul/").status_code == 200
    # 갑에는 프로파일이 있고 을에는 없다 — 을은 빈 상태지만 API는 여전히 200이다
    eul = client.get("/api/d/test_eul").json()["view"]
    assert eul["is_empty"] is True
    assert "동1000" not in [c["geo_name"] for c in eul["cards"]]


def test_switcher_appears_with_multiple_districts(tmp_path):
    data = build_two(tmp_path).get("/api/d/test_gap").json()
    ids = {d_id for d_id, _ in data["districts"]}
    assert {"test_gap", "test_eul"} <= ids


def test_unknown_district_shows_what_to_fix(tmp_path):
    response = build_two(tmp_path).get("/api/d/없는구")
    assert response.status_code == 500
    assert "없는구" in response.text


# --- 설정 오류 -------------------------------------------------------------------


def test_missing_policy_file_shows_what_to_fix(tmp_path):
    """규칙 5를 집행할 근거가 없으면 조용히 통과시키지 않는다."""
    store.append_records("voter_profile", [profile_record(CODES[0])], DataSpace(tmp_path))
    client = TestClient(
        create_app(
            WebSettings(
                districts_path=write_districts(tmp_path),
                data_root=tmp_path,
                policy_path=tmp_path / "없다.yaml",
                boundaries_path=tmp_path / "없다.geojson",
            )
        ),
        raise_server_exceptions=False,
    )
    response = client.get("/api/d/test_gap")
    assert response.status_code == 500
    assert "화면을 그릴 수 없다" in response.text
    assert "compliance.yaml" in response.text
