"""운영자 콘솔 (P-003 §2 캠프 관리 · §5 감사 로그).

여기서 지키는 것 셋:

- **캠프 계정은 `/ops/*` 를 열 수 없다.** P-002 의 `gate` 는 온보딩까지 마친 캠프를
  통과시키고 나면 그 뒤를 막지 않는다. 그 구멍을 `auth.is_ops` 가 막고, 여기가 그
  집행 지점이다.
- **운영자의 조치는 전부 감사 로그에 남는다.** 운영자는 단일 신뢰 지점이라(P-003 §6)
  기술로 줄일 수 없고 기록만 된다. 기록이 빠지면 통제가 0이 된다.
- **CLI 와 웹이 같은 함수를 부른다.** 웹이 규칙을 다시 구현하면 둘이 갈라진다.
"""

from __future__ import annotations

import pytest

from tests.test_web_auth import Env, camp_client, login
from votelink.camp import list_camps
from votelink.control import accounts as acc
from votelink.control import audit, sessions, signup


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def operator_client(env: Env):
    client = env.client()
    login(client, "op@test")
    return client


# --- 접근 통제 ----------------------------------------------------------------------


OPS_PATHS = [
    "/ops/",
    "/ops/audit",
    "/ops/camps/gap",
    "/ops/camps/gap/cycles/2028-04-12-national_assembly/edit",
]


@pytest.mark.parametrize("path", OPS_PATHS)
def test_a_camp_account_cannot_open_the_console(env, path):
    """**P-002 의 `gate` 가 남긴 구멍이다.** 온보딩까지 마친 캠프 계정은 gate 를
    통과하므로, `/ops` 를 따로 막지 않으면 그대로 열린다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 403
    assert "운영자 화면이다" in response.text


@pytest.mark.parametrize("path", OPS_PATHS)
def test_the_console_needs_a_login(env, path):
    response = env.client().get(path, follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_a_camp_account_cannot_post_to_the_console(env):
    """읽기만 막고 쓰기를 열어두면 막은 것이 아니다. 접두어 판정이라 메서드와 무관하다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    other = acc.by_email("op@test", path=env.db)
    response = client.post(f"/ops/accounts/{other.id}/logout", follow_redirects=False)
    assert response.status_code == 403


def test_the_camp_attempt_is_recorded(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    client.get("/ops/", follow_redirects=False)
    entry = audit.recent(path=env.db)[0]
    assert (entry.action, entry.camp_id, entry.target) == ("denied", "gap", "/ops/")


def test_an_operator_is_sent_to_the_console_not_to_onboarding(env):
    """운영자에겐 채울 캠프도 기다릴 신청도 없다. `/onboarding` 은 POST 하면
    camp_id 가 None 이라 터진다."""
    client = operator_client(env)
    for path in ("/onboarding", "/pending"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/ops/"


# --- 승인 큐 ------------------------------------------------------------------------


def test_the_queue_shows_a_suggested_camp_id(env):
    signup.request("kim.chul_su@test", "pw", "김철수", "010", path=env.db)
    html = operator_client(env).get("/ops/").text
    assert "김철수" in html
    assert 'value="kim-chul-su"' in html, "한글 이름을 경로에 쓰지 않는다"


def test_the_queue_warns_when_the_suggested_id_is_taken(env):
    """camp_id 는 경로가 되므로 한 번 정하면 바꾸기 어렵다. 누르기 전에 알려준다."""
    env.approve("hong@test", "hong")
    signup.request("hong@other", "pw", "홍길동", "010", path=env.db)
    html = operator_client(env).get("/ops/").text
    assert "이미 쓰이고 있다" in html


def test_approving_creates_the_camp_space(env):
    req = signup.request("hong@test", "pw", "홍길동", "010", path=env.db)
    client = operator_client(env)

    response = client.post(
        f"/ops/signups/{req.id}/approve",
        data={"camp_id": "hong", "note": "계약 완료"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert list_camps(env.root) == ["hong"]
    assert acc.by_email("hong@test", path=env.db).camp_id == "hong"

    entry = audit.recent(path=env.db)[0]
    assert (entry.action, entry.camp_id) == ("approve_signup", "hong")
    assert entry.detail["note"] == "계약 완료"


def test_the_operator_can_override_the_suggested_camp_id(env):
    req = signup.request("kim@test", "pw", "김철수", "010", path=env.db)
    operator_client(env).post(
        f"/ops/signups/{req.id}/approve", data={"camp_id": "songpa-kim"}, follow_redirects=False
    )
    assert list_camps(env.root) == ["songpa-kim"]


def test_a_colliding_camp_id_is_refused_without_losing_the_queue(env):
    env.approve("first@test", "hong")
    req = signup.request("second@test", "pw", "홍길동", "010", path=env.db)
    client = operator_client(env)

    # TestClient 는 리다이렉트를 따라가므로 이 응답이 곧 사유가 붙은 `/ops/` 화면이다.
    landed = client.post(f"/ops/signups/{req.id}/approve", data={"camp_id": "hong"})
    assert signup.get(req.id, path=env.db).is_pending, "실패했으면 큐에 남아 있어야 한다"
    assert "캠프 공간을 만들 수 없다" in landed.text


def test_rejecting_needs_a_reason(env):
    """신청자가 무엇을 고쳐야 하는지 알아야 한다."""
    req = signup.request("hong@test", "pw", "홍길동", "010", path=env.db)
    client = operator_client(env)

    landed = client.post(f"/ops/signups/{req.id}/reject", data={"note": "  "})
    assert signup.get(req.id, path=env.db).is_pending
    assert "사유" in landed.text


def test_rejecting_suspends_the_account(env):
    req = signup.request("hong@test", "pw", "홍길동", "010", path=env.db)
    operator_client(env).post(f"/ops/signups/{req.id}/reject", data={"note": "계약 미체결"})

    assert acc.by_email("hong@test", path=env.db).status is acc.Status.SUSPENDED
    entry = audit.recent(path=env.db)[0]
    assert entry.action == "reject_signup"
    assert entry.detail["note"] == "계약 미체결"


# --- 계정 조치 ----------------------------------------------------------------------


def test_suspending_also_ends_the_sessions(env):
    """상태만 바꾸면 남은 세션의 수명만큼 더 열려 있다. 그건 정지가 아니다."""
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    target = acc.by_email("gap@test", path=env.db)
    assert sessions.active_count(target.id, path=env.db) == 1

    operator_client(env).post(f"/ops/accounts/{target.id}/status", data={"status": "suspended"})

    assert acc.get(target.id, path=env.db).status is acc.Status.SUSPENDED
    assert sessions.active_count(target.id, path=env.db) == 0
    assert camp.get("/compare", follow_redirects=False).headers["location"] == "/login"


def test_the_operator_cannot_suspend_themselves(env):
    """운영자가 0명이 되면 아무도 캠프를 승인할 수 없고 되돌릴 수도 없다."""
    client = operator_client(env)
    me = acc.by_email("op@test", path=env.db)

    landed = client.post(f"/ops/accounts/{me.id}/status", data={"status": "suspended"})
    assert acc.get(me.id, path=env.db).status is acc.Status.ACTIVE
    assert "자기 계정은 정지할 수 없다" in landed.text


def test_an_unknown_status_is_refused(env):
    client = operator_client(env)
    target = acc.create("x@test", "pw", path=env.db)
    landed = client.post(f"/ops/accounts/{target.id}/status", data={"status": "관리자"})
    assert acc.get(target.id, path=env.db).status is acc.Status.PENDING
    assert "알 수 없는 상태" in landed.text


def test_forced_logout_ends_every_session(env):
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    target = acc.by_email("gap@test", path=env.db)

    operator_client(env).post(f"/ops/accounts/{target.id}/logout")

    assert camp.get("/compare", follow_redirects=False).headers["location"] == "/login"
    assert acc.get(target.id, path=env.db).status is acc.Status.ACTIVE, "정지가 아니라 로그아웃이다"
    assert audit.recent(path=env.db)[0].action == "force_logout"


def test_a_new_password_works_and_kills_the_old_session(env):
    """메일 발송이 없어 이것이 비밀번호를 잊은 캠프의 유일한 통로다.
    재발급의 이유가 유출일 수 있으므로 남은 세션을 살려두지 않는다."""
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    target = acc.by_email("gap@test", path=env.db)

    operator_client(env).post(f"/ops/accounts/{target.id}/passwd", data={"password": "새비번"})

    assert camp.get("/compare", follow_redirects=False).headers["location"] == "/login"
    fresh = env.client()
    assert login(fresh, "gap@test", "새비번").status_code == 303
    assert login(env.client(), "gap@test", "pw").status_code == 401


def test_an_empty_password_is_refused(env):
    client = operator_client(env)
    target = acc.create("x@test", "pw", path=env.db)
    client.post(f"/ops/accounts/{target.id}/passwd", data={"password": ""})
    assert acc.authenticate("x@test", "pw", path=env.db) is not None, "옛 비밀번호가 살아 있다"


def test_every_action_is_posted_not_linked(env):
    """상태를 바꾸는 것을 GET 으로 두면 링크 한 줄로 남의 캠프가 정지된다."""
    camp_client(env, "gap@test", "gap", "test_gap")
    target = acc.by_email("gap@test", path=env.db)
    client = operator_client(env)
    for path in (f"/ops/accounts/{target.id}/logout", f"/ops/accounts/{target.id}/status"):
        assert client.get(path, follow_redirects=False).status_code == 405


# --- 캠프 상세 ----------------------------------------------------------------------


def test_the_camp_detail_shows_the_settings(env):
    camp_client(env, "gap@test", "gap", "test_gap", name="갑후보")
    html = operator_client(env).get("/ops/camps/gap").text

    assert "갑후보" in html
    assert "2028-04-12-national_assembly" in html
    assert "3개 동" in html
    assert "progressive" in html


def test_the_camp_detail_carries_no_analysis_output(env):
    """**운영자 화면에 산출물을 올리지 않는다.** 올리는 순간 verdict 계산이
    필요해지고 절대 규칙 5 가 걸린다. 운영에 필요한 것은 설정과 메타다."""
    camp_client(env, "gap@test", "gap", "test_gap")
    html = operator_client(env).get("/ops/camps/gap").text

    assert "70.0" not in html  # turnout
    assert "동1000" not in html  # 동 이름 = 산출물 카드
    assert "검토를 받지 않은" not in html and "표시가 차단된" not in html


def test_an_unonboarded_camp_says_so(env):
    env.approve("hong@test", "hong")
    html = operator_client(env).get("/ops/camps/hong").text
    assert "온보딩 미완료" in html


def test_an_unknown_camp_is_404_not_500(env):
    response = operator_client(env).get("/ops/camps/없는캠프")
    assert response.status_code == 404
    assert "읽을 수 없다" in response.text


# --- 캠프 주기 대리 수정 (P-005) --------------------------------------------------
#
# 캠프가 스스로 못 고치는 상태거나 이미 저장된 명백한 오류를 운영자가 대신 교정한다.
# 저장 경로는 캠프 쪽과 같은 2단계이고(폼 → 미리보기 → 확인), 다른 것은 둘뿐이다:
# camp_id 를 URL 에서 읽고, 저장할 때 사유를 요구한다.

CID = "2028-04-12-national_assembly"


def _cycle_form(**over):
    base = {
        "election_type": "national_assembly",
        "office": "national_assembly",
        "election_date": "2028-04-12",
        "lineage": "progressive",
        "preset": "test_gap",
        "sigungu": "",
        "emd_codes": "",
        "legal_reviewer": "",
    }
    base.update(over)
    return base


def test_operator_edits_a_camp_cycle_through_the_two_step_flow(env):
    """운영자가 캠프 대신 주기를 고친다 — 폼 → 미리보기 → 사유와 함께 저장."""
    camp_client(env, "gap@test", "gap", "test_gap")
    op = operator_client(env)

    form = op.get(f"/ops/camps/gap/cycles/{CID}/edit")
    assert form.status_code == 200
    assert "운영자가 대신" in form.text  # 대리 수정임을 밝힌다

    preview = op.post(
        f"/ops/camps/gap/cycles/{CID}/edit",
        data=_cycle_form(lineage="conservative"),
        follow_redirects=False,
    )
    assert preview.status_code == 200
    assert "진영이 바뀝니다" in preview.text  # 캠프 쪽과 같은 미리보기

    saved = op.post(
        f"/ops/camps/gap/cycles/{CID}/apply",
        data=_cycle_form(lineage="conservative", note="캠프 요청: 진영 오분류 정정"),
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"].startswith("/ops/camps/gap?ok=")

    from votelink import camp as camp_mod

    cycle = camp_mod.load_cycle("gap", CID, env.root, districts_path=env.settings.districts_path)
    assert cycle.lineage.value == "conservative"


def test_operator_edit_without_a_reason_is_refused(env):
    """거절이 사유 없으면 거부되는 것과 같은 이유 (P-003 §2). 사유가 비면 저장하지 않는다."""
    camp_client(env, "gap@test", "gap", "test_gap")
    op = operator_client(env)

    response = op.post(
        f"/ops/camps/gap/cycles/{CID}/apply",
        data=_cycle_form(lineage="conservative"),  # note 없음
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "사유를 적어야" in response.text

    from votelink import camp as camp_mod

    cycle = camp_mod.load_cycle("gap", CID, env.root, districts_path=env.settings.districts_path)
    assert cycle.lineage.value == "progressive"  # 저장되지 않았다


def test_operator_edit_is_a_distinct_audit_action(env):
    """`edit_cycle` 로 뭉치면 "이 캠프의 누군가"가 고친 것처럼 보인다 (P-003 §5).
    운영자 대리 수정은 `edit_cycle_by_operator` 로 남고 사유가 detail 에 붙는다."""
    camp_client(env, "gap@test", "gap", "test_gap")
    op = operator_client(env)

    op.post(
        f"/ops/camps/gap/cycles/{CID}/apply",
        data=_cycle_form(lineage="conservative", note="캠프 요청으로 정정"),
        follow_redirects=False,
    )
    entry = audit.recent(path=env.db, camp_id="gap")[0]
    assert entry.action == "edit_cycle_by_operator"
    assert entry.account_id == acc.by_email("op@test", path=env.db).id
    assert entry.detail["note"] == "캠프 요청으로 정정"
    assert entry.detail["lineage"] == "progressive→conservative"


def test_operator_edit_on_an_unknown_camp_is_404(env):
    response = operator_client(env).get(
        f"/ops/camps/없는캠프/cycles/{CID}/edit", follow_redirects=False
    )
    assert response.status_code == 404


def test_operator_edit_on_an_unknown_cycle_is_404(env):
    camp_client(env, "gap@test", "gap", "test_gap")
    response = operator_client(env).get(
        "/ops/camps/gap/cycles/1999-01-01-national_assembly/edit", follow_redirects=False
    )
    assert response.status_code == 404


# --- 감사 로그 ----------------------------------------------------------------------


def test_the_audit_screen_states_its_own_limit(env):
    """P-003 §5 가 요구한 문장이다. 읽는 사람이 이 한계를 모르면
    "이 캠프의 누군가"를 "이 사람"으로 읽어버린다."""
    html = operator_client(env).get("/ops/audit").text
    assert "이 캠프의 누군가" in html


def test_the_audit_screen_filters_by_camp(env):
    camp_client(env, "gap@test", "gap", "test_gap")
    camp_client(env, "eul@test", "eul", "test_eul")
    client = operator_client(env)

    html = client.get("/ops/audit?camp=gap").text
    assert "gap" in html
    rows = html.count('href="/ops/camps/eul"')
    assert rows == 0, "다른 캠프의 줄이 섞이지 않는다"


def test_a_denial_is_visible_to_the_operator(env):
    """`denied` 는 격리가 실제로 막은 순간이다. 그 줄이 "유출이 없었다"의 증거다."""
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    camp.get("/d/test_eul/", follow_redirects=False)

    html = operator_client(env).get("/ops/audit").text
    assert "denied" in html
    assert "/d/test_eul/" in html


def test_the_audit_limit_is_clamped(env):
    """사용자가 준 숫자를 그대로 쿼리에 넣지 않는다."""
    for path in ("/ops/audit?limit=0", "/ops/audit?limit=99999", "/ops/audit?limit=-5"):
        assert operator_client(env).get(path).status_code == 200


# --- 내비게이션 ---------------------------------------------------------------------


def test_only_the_operator_sees_the_console_link(env):
    assert "/ops/" in operator_client(env).get("/compare").text
    camp = camp_client(env, "gap@test", "gap", "test_gap")
    assert "/ops/" not in camp.get("/compare").text


@pytest.mark.parametrize("path", ["/ops/", "/ops/audit", "/ops/camps/gap"])
def test_the_console_makes_no_external_requests(env, path):
    """외부 요청 0건은 화면이 늘어날 때마다 다시 확인해야 하는 규칙이다 —
    한 화면의 외부 폰트 한 줄이면 누가 언제 무엇을 봤는지가 제3자에게 간다."""
    camp_client(env, "gap@test", "gap", "test_gap")
    html = operator_client(env).get(path).text

    assert "http://" not in html
    assert "https://" not in html
    assert "//" not in html.replace("</", "").replace("<!--", "")
