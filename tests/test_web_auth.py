"""인증이 붙은 웹 — 무엇이 규칙이 되는가 (P-002 §12).

여기서 지키는 것 넷:

- **로그인 없이는 산출물이 있는 화면이 하나도 열리지 않는다.** 라우트를 전수로 돈다.
- **공개 표면에 산출물이 없다.** `0.0.0.0` 바인딩을 허용한 근거가 이것이라(P-002 §2),
  로그인 화면에 숫자가 하나라도 새면 그 근거가 무너진다.
- **캠프 A 의 세션으로 캠프 B 의 지역구를 열 수 없다.** P-001 §10 격리의 웹 계층 짝이다.
- **어느 캠프의 눈으로 보는지는 세션이 정한다.** 같은 프로세스에서 두 캠프가 각자의
  렌즈로 본다 — 경쟁 캠프를 제한 없이 받기로 한 결정이 이것을 요구한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_web import _ABSOLUTE_URL_RE, ALLOWED_EXTERNAL_HOSTS
from tests.test_web_loader import CODES, profile_record
from votelink import control, store
from votelink.camp import list_cycles, load_cycle
from votelink.control import accounts as acc
from votelink.control import audit, signup
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.settings import WebSettings

GAP = CODES
EUL = ["1171061000", "1171062000", "1171063000"]

POLICY = "outputs:\n  - kind: segment_profile\n    risk: low\n"

CAMP_SCREENS = ["/", "/d/test_gap/", "/d/test_gap/map", "/d/test_gap/news", "/compare", "/nation"]
"""산출물이 있는 화면 전부. 새 화면이 생기면 여기에 넣는다 — 넣는 것을 잊으면
그 화면만 검사를 안 받는 게 아니라, 이 목록이 라우트 지도와 어긋난 채로 통과한다."""


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def _write_districts(tmp_path):
    """선거구 둘. 하나로는 "남의 지역구"를 만들 수 없다."""
    lines = ["districts:\n"]
    for did, name, codes in (
        ("test_gap", "시험 지역구 갑", GAP),
        ("test_eul", "시험 지역구 을", EUL),
    ):
        lines.append(
            f"  - id: {did}\n    name: {name}\n    sido: 시험시\n    sigungu: 시험구\n    emd:\n"
        )
        lines += [f'      - {{name: 동{c[-4:]}, code: "{c}"}}\n' for c in codes]
    path = tmp_path / "districts.yaml"
    path.write_text("".join(lines), encoding="utf-8")
    return path


class Env:
    """앱 하나 + control.db 하나 + 캠프 공간 하나. 테스트가 이것만 들고 다닌다."""

    def __init__(self, tmp_path):
        self.root = tmp_path
        self.db = tmp_path / "control.db"
        control.init(self.db)

        data_root = tmp_path / "shared"
        store.append_records(
            "voter_profile", [profile_record(c) for c in GAP + EUL], DataSpace(data_root)
        )
        policy_path = tmp_path / "compliance.policy.yaml"
        policy_path.write_text(POLICY, encoding="utf-8")

        self.settings = WebSettings(
            auth=True,
            control_db=self.db,
            camps_root=tmp_path,
            districts_path=_write_districts(tmp_path),
            data_root=data_root,
            policy_path=policy_path,
            boundaries_path=tmp_path / "없다.geojson",
        )
        self.operator = acc.create(
            "op@test", "pw", role=acc.Role.OPERATOR, status=acc.Status.ACTIVE, path=self.db
        )

    def client(self) -> TestClient:
        return TestClient(create_app(self.settings))

    def approve(self, email: str, camp_id: str, name: str = "홍길동") -> str:
        req = signup.request(email, "pw", name, "010", path=self.db)
        return signup.approve(
            req.id, self.operator.id, camp_id=camp_id, path=self.db, camps_root=self.root
        )

    def onboard(self, client: TestClient, preset: str, **overrides):
        """React `CycleFormPage` 가 fetch 로 부르는 것과 같은 모양 — 폼이 아니라 JSON."""
        form = {
            "election_type": "national_assembly",
            "office": "national_assembly",
            "election_date": "2028-04-12",
            "lineage": "progressive",
            "party": "시험당",
            "preset": preset,
        }
        form.update(overrides)
        return client.post("/api/onboarding", json=form)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def login(client: TestClient, email: str, password: str = "pw"):
    """React `LoginPage` 가 fetch 로 부르는 것과 같은 모양 — 폼이 아니라 JSON."""
    return client.post("/api/login", json={"email": email, "password": password})


def camp_client(env: Env, email: str, camp_id: str, preset: str, name: str = "홍길동"):
    """승인 + 온보딩까지 끝난 캠프의 클라이언트."""
    env.approve(email, camp_id, name)
    client = env.client()
    login(client, email)
    env.onboard(client, preset)
    return client


# --- 로그인 없이는 아무것도 안 보인다 -------------------------------------------------


@pytest.mark.parametrize("path", CAMP_SCREENS + ["/onboarding", "/pending"])
def test_every_camp_screen_redirects_to_login(env, path):
    """라우트를 전수로 돈다. **미들웨어가 강제하므로 새 라우트도 자동으로 걸린다** —
    라우트가 검사를 불러야 하는 구조였다면 이 테스트는 빠뜨린 라우트를 못 잡는다."""
    response = env.client().get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("path", ["/login", "/signup", "/healthz"])
def test_public_screens_open_without_a_session(env, path):
    assert env.client().get(path).status_code == 200


def test_the_public_surface_carries_no_output(env):
    """**공개 표면에 산출물이 없다.** 이것이 `0.0.0.0` 바인딩을 허용한 근거다 —
    노출되는 화면에 공표할 내용 자체가 없어서 노출이 공표가 되지 않는다 (P-002 §2).
    여기에 숫자를 하나라도 올리면 그 근거가 무너진다."""
    client = env.client()
    for path in ("/login", "/signup"):
        html = client.get(path).text
        assert all(f"동{c[-4:]}" not in html for c in GAP + EUL)
        assert "70.0" not in html  # turnout
        assert "선거구 비교" not in html  # 데이터 화면으로 가는 링크도 없다


@pytest.mark.parametrize("path", ["/login", "/signup", "/pending", "/onboarding"])
def test_the_auth_screens_make_no_external_requests(env, path):
    """인터넷에 열리는 화면이 생겼으니 이 규칙이 더 중요해졌다 — 외부 폰트 한 줄이면
    누가 언제 로그인 화면을 열었는지가 제3자에게 간다."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")
    html = client.get(path, follow_redirects=True).text

    assert "http://" not in html
    for host in _ABSOLUTE_URL_RE.findall(html):
        assert host in ALLOWED_EXTERNAL_HOSTS


# --- 승인 전 · 온보딩 전 ---------------------------------------------------------------


def test_a_pending_account_sees_only_pending(env):
    client = env.client()
    client.post(
        "/api/signup",
        json={
            "email": "new@test",
            "password": "pw",
            "candidate_name": "김후보",
            "contact": "010",
        },
    )
    assert client.get("/pending").status_code == 200
    for path in CAMP_SCREENS + ["/onboarding"]:
        response = client.get(path, follow_redirects=False)
        assert response.headers["location"] == "/pending", path


def test_signup_shows_the_error_without_creating_an_account(env):
    client = env.client()
    response = client.post(
        "/api/signup",
        json={"email": "x@test", "password": "pw", "candidate_name": "  ", "contact": "010"},
    )
    assert response.status_code == 400
    assert "후보 이름" in response.json()["error"]
    assert acc.by_email("x@test", path=env.db) is None


def test_an_approved_camp_without_a_cycle_goes_to_onboarding(env):
    """관할을 모르면 무엇을 보여줄지 알 수 없다. fail-closed 가 자연스럽다."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")
    for path in CAMP_SCREENS:
        assert client.get(path, follow_redirects=False).headers["location"] == "/onboarding"
    assert client.get("/onboarding").status_code == 200


# --- 온보딩 -----------------------------------------------------------------------


def test_onboarding_writes_the_cycle_and_opens_the_screens(env):
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    response = env.onboard(client, "test_gap")
    assert response.status_code == 200
    assert response.json()["ok"] is True

    assert list_cycles("hong", env.root) == ["2028-04-12-national_assembly"]
    cycle = load_cycle(
        "hong", "2028-04-12-national_assembly", env.root, districts_path=env.settings.districts_path
    )
    assert sorted(cycle.territory.emd_codes) == sorted(GAP)
    assert client.get("/d/test_gap/").status_code == 200


def test_onboarding_refuses_an_unknown_emd_code(env):
    """**관할이 틀리면 에러 없이 모든 분석이 조용히 틀린다** (P-001 §16).
    그래서 잘못된 값이 파일이 되는 일 자체를 막는다 — 읽을 때가 아니라 쓰기 전에."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    response = env.onboard(client, "", emd_codes="9999999999")
    assert response.status_code == 400
    assert "9999999999" in response.json()["error"]
    assert list_cycles("hong", env.root) == [], "거부했으면 아무 파일도 남지 않아야 한다"


def test_onboarding_refuses_an_empty_territory(env):
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    response = env.onboard(client, "")
    assert response.status_code == 400
    assert "관할이 비었다" in response.json()["error"]


def test_onboarding_accepts_dong_picked_by_name(env):
    """동 이름 shuttle 로 고른 코드(emd_pick)가 관할에 들어간다 (P-004).
    프리셋 없이 emd_pick 만으로 관할을 만든다 — 프리셋이 없는 기초의원 선거구 케이스."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    response = env.onboard(client, "", emd_pick=[GAP[0], GAP[1]])
    assert response.status_code == 200
    cycle = load_cycle(
        "hong",
        list_cycles("hong", env.root)[0],
        env.root,
        districts_path=env.settings.districts_path,
    )
    assert sorted(cycle.territory.emd_codes) == sorted([GAP[0], GAP[1]])


def test_onboarding_merges_picked_dong_with_preset(env):
    """emd_pick 과 프리셋이 합쳐지고 중복은 제거된다 — resolve_territory 가 dedup."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    response = env.onboard(client, "test_gap", emd_pick=[GAP[0], EUL[0]])
    assert response.status_code == 200
    cycle = load_cycle(
        "hong",
        list_cycles("hong", env.root)[0],
        env.root,
        districts_path=env.settings.districts_path,
    )
    assert sorted(cycle.territory.emd_codes) == sorted(set(GAP) | {EUL[0]})


def test_onboarding_rejects_the_whole_submission_when_one_code_is_unknown(env):
    """이름으로 고른 동(emd_pick)과 잘못된 직접입력(emd_codes)이 섞여 와도 부분
    저장은 없다 — 검증은 합쳐진 관할 전체에 대해 한 번에 실패한다. (폼을 다시
    열 때 이전 선택을 유지하는 일은 이제 React `CycleFormPage` 의 클라이언트
    상태다 — 서버는 hidden input 을 더 이상 내지 않는다.)"""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    # 알 수 없는 코드로 저장을 깨되, 이름으로 고른 동도 함께 보낸다.
    response = env.onboard(client, "", emd_pick=[GAP[0]], emd_codes="9999999999")
    assert response.status_code == 400
    assert list_cycles("hong", env.root) == []


def test_onboarding_keeps_an_unknown_election_day_null(env):
    """선거일을 임의로 채우지 않는다. 모르면 null 이고, 기간에 의존하는 판정은
    전부 미검토로 떨어진다."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")

    assert env.onboard(client, "test_gap", election_date="").status_code == 200
    cycle_id = list_cycles("hong", env.root)[0]
    assert cycle_id == "미정-national_assembly"
    cycle = load_cycle("hong", cycle_id, env.root, districts_path=env.settings.districts_path)
    assert cycle.election.date is None


# --- 격리: 캠프 A 의 세션으로 캠프 B 의 지역구 ------------------------------------------


def test_a_camp_cannot_open_another_camps_district(env):
    """**P-001 §10 격리의 웹 계층 짝이다.** 같은 서버에 경쟁 캠프가 공존하므로
    URL 을 바꿔 옆 캠프의 화면을 여는 일이 가능해서는 안 된다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/d/test_gap/").status_code == 200

    response = client.get("/d/test_eul/", follow_redirects=False)
    assert response.status_code == 403
    assert "관할이 아니다" in response.text
    assert all(f"동{c[-4:]}" not in response.text for c in EUL), "거부 화면에 남의 숫자가 없다"


@pytest.mark.parametrize("suffix", ["", "map", "news"])
def test_the_territory_check_covers_every_screen_under_a_district(env, suffix):
    """검사가 경로 모양(`/d/<id>/…`)에 걸려 있다. `/d/` 밑에 화면을 더 붙여도
    검사는 이미 따라와 있다 — 라우트마다 부르는 구조였다면 새 화면이 뚫린다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get(f"/d/test_eul/{suffix}", follow_redirects=False).status_code == 403


def test_an_unknown_district_is_not_the_same_as_someone_elses(env):
    """ "없는 선거구"와 "남의 선거구"를 같은 화면으로 뭉개면 어느 쪽인지 알 수 없다.

    대시보드는 React SPA 다 — `/d/없는선거구/` 는 셸만 돌려주므로(항상 200) 실제
    판정은 데이터를 내는 `/api/d/없는선거구` 에서 본다.
    """
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.get("/api/d/없는선거구", follow_redirects=False)
    assert response.status_code == 500
    assert "관할이 아니다" not in response.text


def test_the_api_route_is_scoped_to_the_camp_too(env):
    """대시보드가 React SPA 로 바뀌면서 실제 데이터는 `/api/d/{id}` 가 낸다 — 화면
    (`/d/{id}/`)만 관할로 막고 API 를 안 막으면 남의 선거구 데이터가 API 로 그냥
    새 나간다. `district_in_path` 가 `/api/d/` 모양도 인식해야 한다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.get("/api/d/test_eul", follow_redirects=False)
    assert response.status_code == 403
    assert "관할이 아니다" in response.text

    entry = audit.recent(path=env.db)[0]
    assert entry.action == "denied"
    assert entry.target == "/api/d/test_eul"


def test_the_denial_lands_in_the_audit_log(env):
    """**격리가 실제로 막은 순간이 기록으로 남는다.** 경쟁 캠프를 함께 받는 제품에서
    "유출이 없었다"를 증명할 수단은 이것뿐이다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    client.get("/d/test_eul/", follow_redirects=False)

    entry = audit.recent(path=env.db)[0]
    assert entry.action == "denied"
    assert entry.camp_id == "gap"
    assert entry.target == "/d/test_eul/"


def test_the_operator_is_not_bound_to_one_camp(env):
    """운영자는 전 캠프를 본다. **단일 신뢰 지점이다** — 계정 수를 최소로 유지하는
    것이 유일한 통제다 (P-003 §6)."""
    camp_client(env, "gap@test", "gap", "test_gap")
    client = env.client()
    login(client, "op@test")
    assert client.get("/d/test_gap/").status_code == 200
    assert client.get("/d/test_eul/").status_code == 200


# --- 렌즈는 세션이 정한다 -----------------------------------------------------------


def test_two_camps_see_their_own_lens_in_one_process(env):
    """`serve --camp` 는 프로세스 하나에 캠프 하나였다. 인증이 붙으면 같은 앱에서
    두 캠프가 각자의 렌즈로 본다 — 그래서 렌즈가 `app.state` 가 아니라
    `request.state` 에 있다."""
    a = camp_client(env, "gap@test", "gap", "test_gap", name="갑후보")
    b = camp_client(env, "eul@test", "eul", "test_eul", name="을후보")

    lens_a = a.get("/api/d/test_gap").json()["view"]["lens"]
    lens_b = b.get("/api/d/test_eul").json()["view"]["lens"]
    assert "갑후보" in lens_a["label"]
    assert "을후보" in lens_b["label"]


def test_the_district_nav_is_narrowed_to_the_camp(env):
    """미들웨어가 관할 밖을 403 으로 막으니, 이동 UI 에 남겨 두면 눌러도 거부되는
    항목만 늘어난다. 보안이 아니라 정직함의 문제다 — 선거구 정의는 공개 참조 데이터다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")

    # 관할이 선거구 하나뿐이면 `/` 가 그리로 바로 간다 — 고를 것이 없다.
    assert client.get("/", follow_redirects=False).headers["location"] == "/d/test_gap/"
    assert 'value="test_eul"' not in client.get("/d/test_gap/").text


def test_compare_shows_every_district_but_links_only_ours(env):
    """이 표는 **모든** 선거구를 낸다 — 공용 코퍼스는 전 캠프 읽기 전용이고(P-001 §4),
    "우리 지역구가 옆과 어떻게 다른가"가 이 화면의 존재 이유다.
    `districts`(열 수 있는 목록)에 없으면 프런트가 링크 대신 평문으로 그린다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    data = client.get("/api/compare").json()
    names = {r["district_name"] for r in data["view"]["rows"]}
    open_ids = {d_id for d_id, _ in data["districts"]}

    assert "시험 지역구 을" in names, "공용 데이터라 표에는 나온다"
    assert open_ids == {"test_gap"}, "열 수 없는 선거구는 이 목록에 없다(프런트가 링크 여부를 판단)"


def test_the_operator_still_sees_every_district(env):
    camp_client(env, "gap@test", "gap", "test_gap")
    client = env.client()
    login(client, "op@test")
    open_ids = {d_id for d_id, _ in client.get("/api/compare").json()["districts"]}
    assert open_ids == {"test_gap", "test_eul"}


def test_a_camp_screen_states_which_camp_it_is(env):
    client = camp_client(env, "gap@test", "gap", "test_gap", name="갑후보")
    assert "갑후보" in client.get("/api/compare").json()["lens"]["label"]


# --- 세션 -------------------------------------------------------------------------


def test_login_does_not_say_which_half_was_wrong(env):
    """구분해 알려주면 어느 이메일이 등록돼 있는지 새고, 경쟁 캠프를 함께 받는
    제품에서 그건 정보 누출이다."""
    env.approve("hong@test", "hong")
    client = env.client()
    unknown = login(client, "없는@test")
    wrong = login(client, "hong@test", "틀림")

    assert unknown.status_code == wrong.status_code == 401
    assert "맞지 않는다" in unknown.json()["error"]
    # JSON 오류 응답에 입력값(이메일)을 아예 되돌려 주지 않는다 — 두 응답이 한 글자도 다르지 않다.
    assert unknown.text == wrong.text


def test_the_session_cookie_is_httponly_and_lax(env):
    env.approve("hong@test", "hong")
    client = env.client()
    header = login(client, "hong@test").headers["set-cookie"]
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header, "http 로 들어온 요청에 Secure 를 붙이면 쿠키가 안 실린다"


def test_logout_ends_the_session(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.post("/logout", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/compare", follow_redirects=False).headers["location"] == "/login"


def test_logout_refuses_get(env):
    """GET 으로 로그아웃되면 남의 페이지에 심은 이미지 한 장으로 세션이 끊긴다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/logout", follow_redirects=False).status_code == 405


def test_suspension_takes_effect_on_the_very_next_request(env):
    """정지가 남은 세션 수명만큼 늦게 듣는다면 그건 정지가 아니다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    account = acc.by_email("gap@test", path=env.db)
    acc.set_status(account.id, acc.Status.SUSPENDED, path=env.db)

    assert client.get("/compare", follow_redirects=False).headers["location"] == "/login"
    assert control.sessions.active_count(account.id, path=env.db) == 0


def test_forced_logout_ends_every_session(env):
    """비밀번호가 샜을 때의 즉시 대응. 2FA 를 두지 않기로 한 결정의 보완책이다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    account = acc.by_email("gap@test", path=env.db)
    control.sessions.end_all(account.id, path=env.db)
    assert client.get("/compare", follow_redirects=False).headers["location"] == "/login"


def test_login_and_denial_are_both_recorded(env):
    """접속 기록이 2FA 를 두지 않은 자리를 메운다 (P-002 §14)."""
    camp_client(env, "gap@test", "gap", "test_gap")
    actions = [e.action for e in audit.recent(path=env.db)]
    assert "login" in actions
    assert "onboarding" in actions


def test_a_failed_login_is_recorded_too(env):
    env.approve("hong@test", "hong")
    login(env.client(), "hong@test", "틀림")
    entry = audit.recent(path=env.db)[0]
    assert entry.action == "login_failed"
    assert entry.target == "hong@test"


# --- 인증이 꺼진 앱은 지금까지와 똑같다 -------------------------------------------------


def test_auth_off_leaves_every_screen_open(tmp_path):
    """기본값은 꺼짐이다. 그 상태의 앱은 1인 로컬 사용과 정확히 같고,
    `cli.py` 가 그 앱을 `127.0.0.1` 밖으로 내보내지 않는다."""
    env = Env(tmp_path)
    client = TestClient(create_app(env.settings.model_copy(update={"auth": False})))
    for path in CAMP_SCREENS:
        assert client.get(path).status_code == 200, path
