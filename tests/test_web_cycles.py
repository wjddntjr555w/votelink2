"""선거 주기 화면 — 캠프가 다음 선거를 스스로 더한다 (P-001 §7).

여기서 지키는 것 셋:

- **캠프는 영속이고 선거가 그 안에서 바뀐다.** 주기를 더해도 기존 주기는 남는다.
- **지금 보는 주기는 선거일이 정한다.** 캠프가 고르지 않으므로 틀릴 여지가 없고,
  대신 화면이 무엇을 보고 있는지 말한다.
- **첫 설정과 주기 추가가 같은 저장 경로를 쓴다.** 갈라두면 한쪽만 고치게 된다.
"""

from __future__ import annotations

import datetime as dt

import pytest

from tests.test_web import _ABSOLUTE_URL_RE, ALLOWED_EXTERNAL_HOSTS
from tests.test_web_auth import Env, camp_client, login
from votelink import camp as camp_mod
from votelink.control import audit


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def add(client, *, date: str, preset: str = "test_gap", **over):
    """React `CycleFormPage` 가 fetch 로 부르는 것과 같은 모양 — 폼이 아니라 JSON."""
    form = {
        "election_type": "local",
        "office": "basic_head",
        "election_date": date,
        "lineage": "progressive",
        "party": "시험당",
        "preset": preset,
    }
    form.update(over)
    return client.post("/api/cycles/new", json=form)


# --- 목록 (JSON API, React SPA) ----------------------------------------------------
#
# `/cycles` 는 빌드된 SPA 셸만 돌려준다. 데이터·회귀 테스트는 `/api/cycles` 를 본다.


def test_cycles_screen_serves_the_spa_shell(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/cycles").status_code == 200


def test_the_list_marks_which_cycle_is_current(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    rows = client.get("/api/cycles").json()["rows"]

    ids = {r["id"] for r in rows}
    assert "2028-04-12-national_assembly" in ids
    current = [r for r in rows if r["current"]]
    assert [r["id"] for r in current] == ["2028-04-12-national_assembly"]


def test_the_list_needs_onboarding_first(env):
    """관할을 모르면 보여줄 주기가 없다."""
    env.approve("hong@test", "hong")
    client = env.client()
    login(client, "hong@test")
    for path in ("/cycles", "/cycles/new"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/onboarding"


def test_an_onboarded_camp_is_sent_from_onboarding_to_the_list(env):
    """첫 설정은 끝났다. 다음 주기는 목록을 보고 나서 더한다 — 안 그러면 같은 주기를
    두 번 만든다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/onboarding", follow_redirects=False).headers["location"] == "/cycles"


def test_the_operator_has_no_cycles_of_their_own(env):
    """운영자에겐 캠프가 없다. `/cycles` 는 camp_id 를 읽으므로 그대로 두면 터진다."""
    client = env.client()
    login(client, "op@test")
    for path in ("/cycles", "/cycles/new"):
        assert client.get(path, follow_redirects=False).headers["location"] == "/ops/"


def test_a_logged_out_visitor_sees_login(env):
    assert env.client().get("/cycles", follow_redirects=False).headers["location"] == "/login"


# --- 추가 -------------------------------------------------------------------------


def test_adding_a_cycle_keeps_the_old_one(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")

    response = add(client, date="2030-06-05")
    assert response.status_code == 200
    assert response.json()["ok"] is True

    assert camp_mod.list_cycles("gap", env.root) == [
        "2028-04-12-national_assembly",
        "2030-06-05-local",
    ]


def _current_id(rows):
    return next(r["id"] for r in rows if r["current"])


def test_a_later_election_does_not_steal_the_current_view(env):
    """2030년 지선을 등록해도 화면은 2028년 총선을 본다 — 그게 다음 선거다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2030-06-05")

    rows = client.get("/api/cycles").json()["rows"]
    assert _current_id(rows) == "2028-04-12-national_assembly"


def test_an_earlier_upcoming_election_becomes_the_current_view(env):
    """2026년 지선이 2028년 총선보다 먼저다. 그쪽으로 화면이 옮겨간다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2027-06-05")

    rows = client.get("/api/cycles").json()["rows"]
    assert _current_id(rows) == "2027-06-05-local"


def test_the_new_cycle_can_change_the_lineage_and_territory(env):
    """구청장에 나갔다가 다음엔 시의원에 나갈 수 있고 당적도 바뀐다 —
    그래서 관할도 진영도 캠프가 아니라 주기에 붙어 있다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2027-06-05", preset="test_eul", lineage="conservative")

    cycle = camp_mod.load_cycle(
        "gap", "2027-06-05-local", env.root, districts_path=env.settings.districts_path
    )
    assert cycle.lineage.value == "conservative"
    assert cycle.territory.preset == "test_eul"


def test_the_new_cycle_moves_the_camp_screens(env):
    """주기가 바뀌면 관할도 바뀐다. 어제까지 403 이던 지역구가 오늘 열린다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/d/test_eul/", follow_redirects=False).status_code == 403

    add(client, date="2027-06-05", preset="test_eul")

    assert client.get("/d/test_eul/").status_code == 200
    assert client.get("/d/test_gap/", follow_redirects=False).status_code == 403


def test_a_duplicate_cycle_is_refused(env):
    """같은 날 같은 계열을 두 번 만들면 폴더가 겹친다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2030-06-05")

    response = add(client, date="2030-06-05")
    assert response.status_code == 400
    assert "이미 있다" in response.json()["error"]
    assert len(camp_mod.list_cycles("gap", env.root)) == 2, "실패가 세 번째를 만들지 않는다"


def test_an_unknown_emd_is_refused_here_too(env):
    """**관할이 틀리면 에러 없이 모든 분석이 조용히 틀린다.** 첫 설정과 같은 검증이
    걸려 있어야 한다 — 저장 경로를 하나로 둔 이유다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = add(client, date="2030-06-05", preset="", emd_codes="9999999999")

    assert response.status_code == 400
    assert "9999999999" in response.json()["error"]
    assert len(camp_mod.list_cycles("gap", env.root)) == 1


def test_adding_a_cycle_is_audited(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2030-06-05")

    entry = audit.recent(path=env.db)[0]
    assert (entry.action, entry.camp_id, entry.target) == (
        "add_cycle",
        "gap",
        "2030-06-05-local",
    )


def test_an_undated_cycle_does_not_hijack_the_view(env):
    """선거일 미정 주기를 더해도 화면은 날짜가 있는 주기를 계속 본다.
    폴더 이름 사전순이었다면 `미정-…` 이 이겼다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="")

    assert "미정-local" in camp_mod.list_cycles("gap", env.root)
    rows = client.get("/api/cycles").json()["rows"]
    assert _current_id(rows) == "2028-04-12-national_assembly"


def test_the_form_says_which_mode_it_is_in(env):
    """같은 폼이지만 첫 설정과 주기 추가는 다른 일이다 — `first` 플래그가 그 구분이고,
    React `CycleFormPage` 가 문구·저장 뒤 행선지를 그 값으로 가른다."""
    env.approve("hong@test", "hong")
    first = env.client()
    login(first, "hong@test")
    assert first.get("/api/onboarding").json()["first"] is True

    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/api/cycles/new").json()["first"] is False


def test_the_cycle_screens_make_no_external_requests(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    for path in ("/cycles", "/cycles/new"):
        html = client.get(path).text
        assert "http://" not in html
        for host in _ABSOLUTE_URL_RE.findall(html):
            assert host in ALLOWED_EXTERNAL_HOSTS


def test_a_broken_cycle_is_shown_not_hidden(env):
    """고칠 수 없는 화면을 조용히 숨기면 캠프가 왜 안 보이는지 알 수 없다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    add(client, date="2030-06-05")
    path = camp_mod.cycle_dir("gap", "2030-06-05-local", env.root) / "election.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"1171051000"', '"9999999999"'), encoding="utf-8"
    )

    rows = client.get("/api/cycles").json()["rows"]
    broken = next(r for r in rows if r["id"] == "2030-06-05-local")
    assert broken["error"]  # React `CyclesPage` 가 이 값을 "설정이 깨져 있다" 배너에 그린다
    assert broken["cycle"] is None
    assert _current_id(rows) == "2028-04-12-national_assembly", "나머지는 멀쩡하다"


def test_past_and_upcoming_are_labelled_differently(env):
    """예정/지난 표시(React `CyclesPage` 가 `election.date >= today` 로 계산)가
    오늘 날짜에 달려 있다 — API 는 그 판단에 필요한 날짜 값 둘 다 낸다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    past = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    add(client, date=past)

    data = client.get("/api/cycles").json()
    dates = {r["id"]: r["cycle"]["election"]["date"] for r in data["rows"]}
    assert dates["2028-04-12-national_assembly"] >= data["today"], "예정"
    assert dates[f"{past}-local"] < data["today"], "지난 선거"
