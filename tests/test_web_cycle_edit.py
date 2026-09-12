"""주기 수정 — 저장 전에 무엇이 바뀌는지 보여주고 확인받는다.

**이 화면이 왜 두 단계인지가 여기 전부다.** P-001 §16 이 가장 위험한 실패로 지목한 것은
"관할 입력이 틀리면 모든 분석이 조용히 틀린다" — 틀린 관할은 에러를 내지 않고 그냥 다른
답을 준다. 수정을 열어주는 대가로 확인 절차가 붙는다.

여기서 지키는 것 넷:

- **미리보기는 아무것도 저장하지 않는다.** 확인을 누르기 전까지 파일이 그대로다.
- **미리보기가 실제 동작과 같은 규칙을 쓴다.** 열린다고 보여준 선거구가 실제로 열려야
  하고, 아니면 확인 절차가 거짓말이 된다.
- **선거일을 고치면 폴더도 함께 옮긴다.** `cycle_id` 는 파생값이라 안 옮기면 그 주기가
  통째로 안 읽힌다.
- **남의 주기는 못 고친다.** 경로 파라미터를 파일 경로에 그대로 쓰지 않는다.
"""

from __future__ import annotations

import pytest

from tests.test_web import _ABSOLUTE_URL_RE, ALLOWED_EXTERNAL_HOSTS
from tests.test_web_auth import Env, camp_client, login
from votelink import camp as camp_mod
from votelink.control import audit


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


CURRENT = "2028-04-12-national_assembly"


def form_for(**over):
    """수정 폼의 기본값 — `camp_client` 가 만든 주기와 같은 내용."""
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


def preview(client, cycle_id=CURRENT, **over):
    """React `CycleEditPage` 가 fetch 로 부르는 것과 같은 모양 — 폼이 아니라 JSON.
    저장하지 않는다 — `change` 계산 결과만 돌려준다."""
    return client.post(f"/api/cycles/{cycle_id}/edit", json=form_for(**over))


def apply(client, cycle_id=CURRENT, **over):
    return client.post(f"/api/cycles/{cycle_id}/apply", json=form_for(**over))


def cycle_of(env, camp="gap", cid=CURRENT):
    return camp_mod.load_cycle(camp, cid, env.root, districts_path=env.settings.districts_path)


# --- 접근 통제 ----------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/cycles/x/edit", "/cycles/x/roster"])
def test_editing_needs_a_login(env, path):
    assert env.client().get(path, follow_redirects=False).headers["location"] == "/login"


def test_the_operator_is_sent_to_the_console(env):
    client = env.client()
    login(client, "op@test")
    assert (
        client.get(f"/cycles/{CURRENT}/edit", follow_redirects=False).headers["location"] == "/ops/"
    )


def test_a_cycle_that_is_not_ours_is_not_found(env):
    """**경로 파라미터를 파일 경로에 그대로 쓰지 않는다.**

    Starlette 가 `%2F` 를 라우팅 전에 풀어서 경로 탈출은 실제로 닿지 않지만, 그 사실에
    기대지 않는다. `list_cycles` 화이트리스트가 유일하게 안전한 검사다. `/cycles/{id}/edit`
    는 이제 SPA 셸만 돌려준다(어떤 `id` 든 200) — 실제 검사는 프런트가 부르는
    `/api/cycles/{id}/edit` 에 있다.
    """
    camp_client(env, "eul@test", "eul", "test_eul")
    client = camp_client(env, "gap@test", "gap", "test_gap")

    for bad in ("없는주기", "..", "../../eul/cycles/" + CURRENT):
        response = client.get(f"/api/cycles/{bad}/edit", follow_redirects=False)
        assert response.status_code in (404, 500), bad
        assert "관할" not in response.text, bad


# --- 미리보기는 저장하지 않는다 -------------------------------------------------------


def test_the_preview_changes_nothing_on_disk(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    before = (camp_mod.cycle_dir("gap", CURRENT, env.root) / "election.yaml").read_text("utf-8")

    response = preview(client, preset="test_eul")

    assert response.status_code == 200
    assert "change" in response.json()
    after = (camp_mod.cycle_dir("gap", CURRENT, env.root) / "election.yaml").read_text("utf-8")
    assert before == after, "확인을 누르기 전까지 파일이 그대로다"


def test_the_preview_names_the_dongs_that_come_and_go(env):
    """코드만 보여주면 사람이 무엇이 빠지는지 알 수 없다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change = preview(client, preset="test_eul").json()["change"]

    assert len(change["added"]) == 3
    assert len(change["removed"]) == 3
    removed_labels = [e["label"] for e in change["removed"]]
    assert any("동1000" in label for label in removed_labels)  # test_gap 의 첫 동 — 빠지는 쪽
    assert any("1171051000" in label for label in removed_labels), "이름과 코드를 함께 보여준다"


def test_the_preview_warns_about_districts_that_close(env):
    """지금 보고 있는 화면이 사라질 수 있다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change = preview(client, preset="test_eul").json()["change"]

    closed_names = [name for _id, name in change["closed"]]
    opened_names = [name for _id, name in change["opened"]]
    assert "시험 지역구 갑" in closed_names
    assert "시험 지역구 을" in opened_names


def test_the_preview_warns_that_the_lineage_flips_the_screen(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change = preview(client, lineage="conservative").json()["change"]
    assert change["lineage_flipped"] is True


def test_the_preview_warns_that_the_folder_moves(env):
    """`cycle_id` 는 선거일과 계열에서 나온 파생값이다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change = preview(client, election_date="2028-04-19").json()["change"]

    assert change["moved"] is True
    assert change["cycle_id_after"] == "2028-04-19-national_assembly"


def test_no_change_reports_itself_as_empty(env):
    """바뀌는 것이 없으면 프런트가 확인 화면 없이 목록으로 바로 돌아간다 — 그 판단은
    `change.is_empty` 로 한다(옛 Jinja 라우트의 `/cycles` 리다이렉트와 같은 결정)."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = preview(client)
    assert response.status_code == 200
    assert response.json()["change"]["is_empty"] is True


def test_a_bad_value_goes_back_to_the_form_not_the_preview(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = preview(client, preset="", emd_codes="9999999999")

    assert response.status_code == 400
    assert "9999999999" in response.json()["error"]


# --- 저장 -------------------------------------------------------------------------


def test_applying_moves_the_territory(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    assert client.get("/d/test_eul/", follow_redirects=False).status_code == 403

    response = apply(client, preset="test_eul")
    assert response.status_code == 200
    assert response.json()["ok"] is True

    assert cycle_of(env).territory.preset == "test_eul"
    assert client.get("/d/test_eul/").status_code == 200
    assert client.get("/d/test_gap/", follow_redirects=False).status_code == 403


def test_what_the_preview_promised_is_what_happens(env):
    """미리보기가 실제 동작과 다른 규칙을 쓰면 확인 절차가 거짓말이 된다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    change = preview(client, preset="test_eul").json()["change"]
    assert "시험 지역구 을" in [name for _id, name in change["opened"]]

    apply(client, preset="test_eul")
    assert client.get("/d/test_eul/").status_code == 200


def test_applying_a_new_date_moves_the_folder_with_its_contents(env):
    """폴더 안에는 법률 검토 기록과 이 주기의 레코드가 함께 있다.
    검토는 그 선거에 대한 것이지 폴더 이름에 대한 것이 아니다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    old = camp_mod.cycle_dir("gap", CURRENT, env.root)
    (old / "compliance.review.yaml").write_text("version: 표시\noutputs: []\n", encoding="utf-8")
    (old / "records" / "mark.jsonl").write_text("{}\n", encoding="utf-8")

    apply(client, election_date="2028-04-19")

    new_id = "2028-04-19-national_assembly"
    assert camp_mod.list_cycles("gap", env.root) == [new_id]
    new = camp_mod.cycle_dir("gap", new_id, env.root)
    assert "version: 표시" in (new / "compliance.review.yaml").read_text("utf-8")
    assert (new / "records" / "mark.jsonl").exists()
    assert not old.exists()


def test_the_moved_cycle_still_loads(env):
    """폴더를 안 옮기면 `load_cycle` 의 폴더명 검증이 그 주기를 통째로 거부한다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    apply(client, election_date="2028-04-19")

    cycle = cycle_of(env, cid="2028-04-19-national_assembly")
    assert cycle.election.date.isoformat() == "2028-04-19"
    assert client.get("/d/test_gap/").status_code == 200, "화면이 계속 뜬다"


def test_a_date_can_be_cleared_and_the_folder_follows(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    apply(client, election_date="")

    assert camp_mod.list_cycles("gap", env.root) == ["미정-national_assembly"]
    assert cycle_of(env, cid="미정-national_assembly").election.date is None


def test_moving_onto_an_existing_cycle_is_refused(env):
    """같은 날 같은 계열의 선거를 두 번 둘 수 없다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    client.post(
        "/api/cycles/new",
        json={
            "election_type": "national_assembly",
            "office": "national_assembly",
            "election_date": "2030-04-10",
            "lineage": "progressive",
            "party": "시험당",
            "preset": "test_gap",
        },
    )
    response = apply(client, election_date="2030-04-10")

    assert response.status_code == 400
    assert "이미 있다" in response.json()["error"]
    assert sorted(camp_mod.list_cycles("gap", env.root)) == [
        "2028-04-12-national_assembly",
        "2030-04-10-national_assembly",
    ], "실패가 주기를 지우거나 덮어쓰지 않는다"


def test_the_reviewer_survives_a_rewrite(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    apply(client, legal_reviewer="김변호사 (○○법률사무소)")
    assert cycle_of(env).legal_reviewer == "김변호사 (○○법률사무소)"


def test_the_edit_is_audited_with_what_changed(env):
    """관할이 바뀌면 그 뒤의 모든 숫자가 달라진다. 나중에 "왜 지난주와 다른가"를
    물을 때 답할 수 있어야 한다 (P-001 §11)."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    apply(client, preset="test_eul", lineage="conservative")

    entry = audit.recent(path=env.db)[0]
    assert entry.action == "edit_cycle"
    assert entry.camp_id == "gap"
    assert entry.detail["added"] == 3
    assert entry.detail["removed"] == 3
    assert entry.detail["lineage"] == "progressive→conservative"


def test_the_form_is_prefilled_with_what_is_saved(env):
    """빈 폼을 주면 안 건드린 항목까지 다시 쳐야 하고, 그러다 관할을 새로 치는 순간
    사고가 난다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    form = client.get(f"/api/cycles/{CURRENT}/edit").json()["form"]

    assert form["election_date"] == "2028-04-12"
    assert "1171051000" in form["emd_pick"], "지금 관할이 그대로 들어 있다"
    assert form["preset"] == "test_gap"


def test_the_form_prefills_the_dong_shuttle_with_the_current_territory(env):
    """수정 폼도 온보딩처럼 동 이름 shuttle 을 쓴다 (P-005 §9). React `CycleFormPage`
    가 `emd_pick` 을 shuttle 의 "선택됨" 쪽 초기 상태로 받는다 — 지금 관할이 미리
    들어와 있어야 뺄 수 있다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    form = client.get(f"/api/cycles/{CURRENT}/edit").json()["form"]

    cycle = cycle_of(env)
    assert sorted(form["emd_pick"]) == sorted(cycle.territory.emd_codes)


# --- 후보 로스터 (JSON API, React SPA) ----------------------------------------------
#
# `/cycles/{id}/roster` 는 빌드된 SPA 셸만 돌려준다. 데이터·저장은
# `/api/cycles/{id}/roster` 를 본다 — 계산은 여전히 `parse_roster`/`roster_text` 가 한다.


def test_the_roster_form_shows_what_is_saved(env):
    client = camp_client(env, "gap@test", "gap", "test_gap", name="갑후보")
    form = client.get(f"/api/cycles/{CURRENT}/roster").json()["form"]
    assert form["ours_name"] == "갑후보"
    assert form["ours_party"] == "시험당"


def test_opponents_are_one_per_line(env):
    client = camp_client(env, "gap@test", "gap", "test_gap", name="갑후보")
    response = client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "ours_incumbent": True,
            "opponents": (
                "김철수 | 국민의힘 | 보수 | 현직\n"
                "\n"
                "# 주석 줄은 건너뛴다\n"
                "이영희 | 무소속 | 중도 |  | 경선 불복 탈당\n"
            ),
        },
    )
    assert response.status_code == 200

    roster = camp_mod.load_roster("gap", CURRENT, env.root)
    assert roster.ours.incumbent
    assert [o.name for o in roster.opponents] == ["김철수", "이영희"]
    assert roster.opponents[0].incumbent
    assert roster.opponents[1].lineage.value == "centrist"
    assert roster.opponents[1].note == "경선 불복 탈당"


def test_an_unknown_lineage_stops_the_line(env):
    """**미기입을 other 로 자동 강등하지 않는다.** 조용히 떨어뜨리면 '분류 누락'과
    '실제 군소후보'를 구분할 수 없게 된다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": "김철수 | 국민의힘 | 우파\n",
        },
    )
    assert response.status_code == 400
    assert "모르는 진영이다 — 우파" in response.json()["error"]
    assert camp_mod.load_roster("gap", CURRENT, env.root).opponents == []


def test_a_short_line_says_which_line(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    response = client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": "김철수 | 국민의힘\n",
        },
    )
    assert response.status_code == 400
    assert "1번째 줄" in response.json()["error"]


def test_the_roster_round_trips(env):
    """저장한 로스터를 다시 열면 같은 텍스트가 나온다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    lines = "김철수 | 국민의힘 | conservative | 현직\n이영희 | 무소속 | centrist"
    client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": lines,
        },
    )
    form = client.get(f"/api/cycles/{CURRENT}/roster").json()["form"]
    assert "김철수 | 국민의힘 | conservative | 현직" in form["opponents"]
    assert "이영희 | 무소속 | centrist" in form["opponents"]


def test_a_quote_in_a_name_does_not_break_the_file(env):
    """후보 이름·정당명은 사람이 폼에 치는 값이다. `:` 나 `"` 가 섞이면 YAML 이 깨진다."""
    client = camp_client(env, "gap@test", "gap", "test_gap")
    client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": '홍"길동: 기호1번',
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": "김철수 | 무소속: 기호2번 | 보수",
        },
    )
    roster = camp_mod.load_roster("gap", CURRENT, env.root)
    assert roster.ours.name == '홍"길동: 기호1번'
    assert roster.opponents[0].party == "무소속: 기호2번"


def test_the_roster_list_shows_the_opponent_count(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    row = next(r for r in client.get("/api/cycles").json()["rows"] if r["id"] == CURRENT)
    assert row["roster"]["opponents"] == []

    client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": "김철수 | 국민의힘 | 보수",
        },
    )
    row = next(r for r in client.get("/api/cycles").json()["rows"] if r["id"] == CURRENT)
    assert len(row["roster"]["opponents"]) == 1


def test_the_roster_edit_is_audited(env):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    client.post(
        f"/api/cycles/{CURRENT}/roster",
        json={
            "ours_name": "갑후보",
            "ours_party": "시험당",
            "ours_lineage": "progressive",
            "opponents": "김철수 | 국민의힘 | 보수",
        },
    )
    entry = audit.recent(path=env.db)[0]
    assert (entry.action, entry.detail["opponents"]) == ("edit_roster", 1)


@pytest.mark.parametrize("path", ["edit", "roster"])
def test_the_edit_screens_make_no_external_requests(env, path):
    client = camp_client(env, "gap@test", "gap", "test_gap")
    html = client.get(f"/cycles/{CURRENT}/{path}").text
    assert "http://" not in html
    for host in _ABSOLUTE_URL_RE.findall(html):
        assert host in ALLOWED_EXTERNAL_HOSTS
