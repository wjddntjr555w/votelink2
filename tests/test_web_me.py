"""내 계정 — 자기 비밀번호를 바꾸는 유일한 통로.

여기서 지키는 것 넷:

- **로그인만 했으면 누구나 연다.** 승인 대기든 온보딩 전이든 운영자든. 특히 부트스트랩
  운영자(`root`)는 이 화면 말고는 비밀번호를 바꿀 데가 없다.
- **현재 비밀번호를 확인한다.** 세션이 탈취돼도 비밀번호까지 바꾸지는 못하게 —
  그러지 않으면 잠깐의 세션 탈취가 계정 탈취가 된다.
- **바꾸면 다른 기기의 세션이 끊기고 현재 세션은 살아 있다.** 바꾸는 이유가 유출일 수
  있고, 그때 남은 세션을 살려두면 바꾼 의미가 없다.
- **배포 기본 비밀번호로는 되돌릴 수 없다.** 되돌리면 기동 가드가 무의미해진다.
"""

from __future__ import annotations

import pytest

from tests.test_web import _ABSOLUTE_URL_RE, ALLOWED_EXTERNAL_HOSTS
from tests.test_web_auth import Env, camp_client, login
from votelink.control import accounts as acc
from votelink.control import audit, sessions


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def change(client, current="pw", new="새비밀번호", confirm=None):
    """React `MePage` 가 fetch 로 부르는 것과 같은 모양 — 폼이 아니라 JSON."""
    return client.post(
        "/api/me",
        json={"current": current, "new": new, "confirm": confirm if confirm is not None else new},
    )


# --- 누가 열 수 있나 ------------------------------------------------------------------


def test_a_logged_out_visitor_is_sent_to_login(env):
    assert env.client().get("/me", follow_redirects=False).headers["location"] == "/login"


def test_a_pending_account_can_still_open_it(env):
    """승인 대기 중이라도 비밀번호는 바꿀 수 있어야 한다. 다른 화면은 전부 막혀 있다."""
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
    assert client.get("/me").status_code == 200
    assert client.get("/compare", follow_redirects=False).headers["location"] == "/pending"


def test_an_unonboarded_camp_can_open_it(env):
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")
    assert client.get("/me").status_code == 200
    assert client.get("/compare", follow_redirects=False).headers["location"] == "/onboarding"


def test_the_operator_can_open_it(env):
    """운영자는 `/onboarding`·`/pending` 에서는 `/ops/` 로 되돌려지지만 `/me` 는 아니다."""
    client = env.client()
    login(client, "op@test")
    assert client.get("/me").status_code == 200


def test_an_onboarded_camp_can_open_it(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/me").status_code == 200


def test_it_shows_who_you_are(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    data = client.get("/api/me").json()
    assert data["account"]["email"] == "gap@test"
    assert data["account"]["is_operator"] is False
    assert data["sessions"] == 1


def test_it_carries_no_output(env):
    """계정 정보뿐이다. 참조 데이터도 산출물도 읽지 않는다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    raw = client.get("/api/me").text
    assert "동1000" not in raw
    assert "70.0" not in raw


def test_it_makes_no_external_requests(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    html = client.get("/me").text
    assert "http://" not in html
    for host in _ABSOLUTE_URL_RE.findall(html):
        assert host in ALLOWED_EXTERNAL_HOSTS


# --- 비밀번호 변경 --------------------------------------------------------------------


def test_the_current_password_must_be_right(env):
    """**세션이 탈취돼도 비밀번호까지 바꾸지는 못하게.** 그러지 않으면 잠깐의 세션
    탈취가 계정 탈취가 된다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = change(client, current="틀린비번")

    assert response.status_code == 400
    assert "맞지 않는다" in response.json()["error"]
    assert acc.authenticate("gap@test", "pw", path=env.db) is not None, "옛 비번이 살아 있다"


def test_a_failed_attempt_is_recorded(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change(client, current="틀린비번")
    assert audit.recent(path=env.db)[0].action == "change_password_failed"


def test_the_two_new_passwords_must_match(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = change(client, new="가나다", confirm="라마바")

    assert response.status_code == 400
    assert "서로 다르다" in response.json()["error"]
    assert acc.authenticate("gap@test", "pw", path=env.db) is not None


def test_an_empty_password_is_refused(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.post("/api/me", json={"current": "pw", "new": "", "confirm": ""})
    assert response.status_code == 400
    assert acc.authenticate("gap@test", "pw", path=env.db) is not None


def test_the_bootstrap_password_cannot_be_restored(env):
    """되돌리면 기동 가드가 무의미해진다. 아는 비밀번호는 인증이 아니다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = change(client, new=acc.BOOTSTRAP_PASSWORD)

    assert response.status_code == 400
    assert "되돌릴 수 없다" in response.json()["error"]


def test_the_new_password_works_and_the_old_one_does_not(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert change(client).status_code == 200

    assert login(env.client(), "gap@test", "새비밀번호").status_code == 200
    assert login(env.client(), "gap@test", "pw").status_code == 401


def test_other_sessions_end_but_this_one_survives(env):
    """바꾸는 이유가 유출일 수 있다. 그때 남은 세션을 살려두면 바꾼 의미가 없다.
    대신 바꾼 사람이 자기도 로그아웃되면 안 된다."""
    here = camp_client(env, "gap@test", "gap", "test_gap")
    elsewhere = env.client()
    login(elsewhere, "gap@test")
    account = acc.by_email("gap@test", path=env.db)
    assert sessions.active_count(account.id, path=env.db) == 2

    change(here)

    assert sessions.active_count(account.id, path=env.db) == 1
    assert here.get("/me").status_code == 200, "바꾼 창은 살아 있다"
    assert elsewhere.get("/compare", follow_redirects=False).headers["location"] == "/login"


def test_the_change_is_audited(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change(client)
    entry = audit.recent(path=env.db)[0]
    assert (entry.action, entry.camp_id) == ("change_password", "gap")


def test_the_change_returns_ok_without_a_redirect(env):
    """React `MePage` 가 fetch 로 부르므로 PRG(리다이렉트 뒤 조회)가 필요 없다 —
    응답 자체가 성공 여부를 말하고, 새로고침이 변경을 두 번 하지도 않는다
    (새로고침은 GET 이지 이 POST 를 다시 보내지 않는다)."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = change(client)
    assert response.json() == {"ok": True}


# --- 부트스트랩 비밀번호 경고 ----------------------------------------------------------


def bootstrap_env(tmp_path):
    """`root`/`root` 운영자만 있는 서버 — `serve --auth` 가 처음 띄운 상태."""
    env = Env(tmp_path)
    acc.set_password(env.operator.id, acc.BOOTSTRAP_PASSWORD, path=env.db)
    return env


def test_the_operator_is_warned_while_the_password_is_the_default(tmp_path):
    env = bootstrap_env(tmp_path)
    client = env.client()
    login(client, "op@test", acc.BOOTSTRAP_PASSWORD)

    assert client.get("/api/me").json()["bootstrap"] is True
    assert client.get("/api/ops/console").json()["bootstrap"] is True


def test_the_warning_goes_away_once_it_is_changed(tmp_path):
    env = bootstrap_env(tmp_path)
    client = env.client()
    login(client, "op@test", acc.BOOTSTRAP_PASSWORD)
    change(client, current=acc.BOOTSTRAP_PASSWORD, new="제대로된비번")

    assert client.get("/api/ops/console").json()["bootstrap"] is False


def test_an_operator_reset_also_refreshes_the_warning(tmp_path):
    """운영자가 `/ops/` 에서 자기 비밀번호를 재발급해도 배너 판정이 따라간다."""
    env = bootstrap_env(tmp_path)
    client = env.client()
    login(client, "op@test", acc.BOOTSTRAP_PASSWORD)
    assert client.get("/api/ops/console").json()["bootstrap"] is True

    client.post(f"/api/ops/accounts/{env.operator.id}/passwd", json={"password": "제대로된비번"})

    fresh = env.client()
    login(fresh, "op@test", "제대로된비번")
    assert fresh.get("/api/ops/console").json()["bootstrap"] is False


def test_a_camp_password_does_not_trigger_the_warning(env):
    """판정은 **운영자** 계정만 본다. 캠프가 무엇을 쓰든 서버 노출과 무관하다."""
    account = acc.by_email("op@test", path=env.db)
    assert account is not None
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    acc.set_password(acc.by_email("gap@test", path=env.db).id, acc.BOOTSTRAP_PASSWORD, path=env.db)

    assert not acc.uses_bootstrap_password(path=env.db)
    assert camp.get("/api/me").json()["bootstrap"] is False
