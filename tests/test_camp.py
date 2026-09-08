"""캠프 공간 — 로더와 온보딩 (P-001 §7·§9).

가장 중요한 것은 **관할 검증**이다. P-001 §16 이 "관할 입력이 틀리면 모든 분석이
조용히 틀린다"를 가장 위험한 실패 방식으로 지목했다 — 틀린 관할은 에러를 내지 않고
그냥 다른 답을 준다. 그래서 읽기 경로가 그것을 막는지 본다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from votelink import camp
from votelink.camp import scaffold
from votelink.camp.models import CampInfo, Cycle
from votelink.contract.enums import Camp, ElectionType
from votelink.reference import districts as districts_mod

GA = "1111051500"
NA = "1111051600"
DA = "1111051700"


@pytest.fixture(autouse=True)
def _districts(tmp_path, monkeypatch):
    """축소판 districts.yaml. 실제 파일을 읽지 않는다.

    두 선거구가 같은 자치구(시험구)에 있어서 --sigungu 합집합을 볼 수 있다.
    """
    path = tmp_path / "districts.yaml"
    path.write_text(
        "version: test\ndistricts:\n"
        "  - id: test_gap\n    name: 시험 갑\n    sido: 서울특별시\n"
        "    sigungu: 시험구\n    source: test\n    emd:\n"
        f'      - {{ name: "가동", code: "{GA}" }}\n'
        f'      - {{ name: "나동", code: "{NA}" }}\n'
        "  - id: test_eul\n    name: 시험 을\n    sido: 서울특별시\n"
        "    sigungu: 시험구\n    source: test\n    emd:\n"
        f'      - {{ name: "다동", code: "{DA}" }}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(districts_mod, "DISTRICTS_PATH", path)
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


@pytest.fixture
def root(tmp_path):
    """`data/` 에 해당하는 임시 뿌리. 캠프는 그 아래 camps/ 로 간다."""
    return tmp_path / "data"


def make(root, camp_id="test-camp", *, date=dt.date(2028, 4, 12), cycle_id=None, **over):
    cycle = Cycle.model_validate(
        {
            "election": {
                "type": ElectionType.NATIONAL_ASSEMBLY,
                "office": "national_assembly",
                "date": date,
            },
            "lineage": Camp.PROGRESSIVE,
            "territory": {"preset": "test_gap", "emd_codes": [GA, NA]},
            **over,
        }
    )
    info = CampInfo(camp_id=camp_id, candidate_name="홍길동", created_at=dt.date(2026, 9, 8))
    cid = cycle_id or scaffold.default_cycle_id(cycle)
    scaffold.write_camp(info, root)
    scaffold.write_cycle(camp_id, cid, cycle, "홍길동", "가당", False, root)
    return cid


# --- 관할 검증 — 이 파일에서 가장 중요한 것 -------------------------------------


def test_unknown_emd_code_is_rejected_on_read(root):
    """온보딩 CLI 에만 검증을 두면 손으로 고친 파일을 못 잡는다. 읽기가 막아야 한다."""
    cid = make(root)
    path = camp.cycle_dir("test-camp", cid, root) / "election.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f'"{GA}"', '"9999999999"'), encoding="utf-8"
    )
    with pytest.raises(camp.CampConfigError, match="9999999999"):
        camp.load_cycle("test-camp", cid, root)


def test_duplicate_emd_code_is_rejected(root):
    with pytest.raises(ValidationError, match="두 번"):
        Cycle.model_validate(
            {
                "election": {"type": "national_assembly", "office": "national_assembly"},
                "lineage": "progressive",
                "territory": {"emd_codes": [GA, GA]},
            }
        )


def test_malformed_emd_code_is_rejected(root):
    with pytest.raises(ValidationError, match="10자리"):
        Cycle.model_validate(
            {
                "election": {"type": "national_assembly", "office": "national_assembly"},
                "lineage": "progressive",
                "territory": {"emd_codes": ["123"]},
            }
        )


def test_empty_territory_is_rejected(root):
    with pytest.raises(ValidationError):
        Cycle.model_validate(
            {
                "election": {"type": "national_assembly", "office": "national_assembly"},
                "lineage": "progressive",
                "territory": {"emd_codes": []},
            }
        )


# --- 계약 정합 -------------------------------------------------------------------


def test_office_must_match_election_type():
    """지방선거 하나에 다섯 직위가 있다. 계열만으로는 캠프를 특정할 수 없다."""
    with pytest.raises(ValidationError, match="올 수 없다"):
        Cycle.model_validate(
            {
                "election": {"type": "presidential", "office": "basic_head"},
                "lineage": "progressive",
                "territory": {"emd_codes": [GA]},
            }
        )


def test_election_type_uses_the_contract_enum():
    """`assembly` 같은 별칭을 두지 않는다 — 레코드의 election_type 과 같아야
    렌즈가 voter_profile·turnout_gap 을 걸러낼 수 있다."""
    with pytest.raises(ValidationError):
        Cycle.model_validate(
            {
                "election": {"type": "assembly", "office": "national_assembly"},
                "lineage": "progressive",
                "territory": {"emd_codes": [GA]},
            }
        )


def test_lineage_uses_the_party_lineage_axis():
    """진영 값이 party_lineage.yaml 의 4축과 달라지면 렌즈가 동작하지 않는다."""
    with pytest.raises(ValidationError):
        Cycle.model_validate(
            {
                "election": {"type": "national_assembly", "office": "national_assembly"},
                "lineage": "우리편",
                "territory": {"emd_codes": [GA]},
            }
        )


# --- 폴더와 파일이 어긋나는 경우 -------------------------------------------------


def test_cycle_folder_must_match_the_election_date(root):
    cid = make(root, date=dt.date(2028, 4, 12), cycle_id="엉뚱한이름")
    with pytest.raises(camp.CampConfigError, match="폴더 이름"):
        camp.load_cycle("test-camp", cid, root)


def test_camp_id_must_match_the_folder(root):
    make(root, camp_id="test-camp")
    path = camp.camp_dir("test-camp", root) / "camp.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("camp_id: test-camp", "camp_id: other-camp"),
        encoding="utf-8",
    )
    with pytest.raises(camp.CampConfigError, match="폴더 이름"):
        camp.load_camp("test-camp", root)


def test_unknown_camp_lists_the_known_ones(root):
    make(root, camp_id="test-camp")
    with pytest.raises(camp.CampNotFound, match="test-camp"):
        camp.load_camp("없는캠프", root)


def test_unknown_cycle_lists_the_known_ones(root):
    cid = make(root)
    with pytest.raises(camp.CycleNotFound, match=cid):
        camp.load_cycle("test-camp", "없는주기", root)


# --- 선거일을 모를 때 -------------------------------------------------------------


def test_cycle_without_a_date_needs_an_explicit_name(root):
    """선거일을 모르면 주기 이름을 유도할 수 없다. 임의 날짜로 채우지 않는다."""
    cycle = Cycle.model_validate(
        {
            "election": {"type": "national_assembly", "office": "national_assembly", "date": None},
            "lineage": "progressive",
            "territory": {"emd_codes": [GA]},
        }
    )
    assert camp.cycle_id_for(cycle) is None
    with pytest.raises(scaffold.ScaffoldError, match="--cycle"):
        scaffold.default_cycle_id(cycle)


def test_cycle_without_a_date_loads_with_any_folder_name(root):
    cid = make(root, date=None, cycle_id="2028-미정-national_assembly")
    loaded = camp.load_cycle("test-camp", cid, root)
    assert loaded.election.date is None


# --- 온보딩 ----------------------------------------------------------------------


def test_preset_fills_the_district_emd(root):
    preset, codes = scaffold.resolve_territory("test_gap", None, [])
    assert preset == "test_gap"
    assert codes == [GA, NA]


def test_sigungu_unions_every_district_in_it():
    """구청장은 국회의원 선거구 여럿을 아우른다 — 그 합집합이 관할이다 (P-001 §6)."""
    preset, codes = scaffold.resolve_territory(None, "시험구", [])
    assert preset == "sigungu:시험구"
    assert sorted(codes) == sorted([GA, NA, DA])


def test_explicit_emd_works_without_a_preset():
    """기초의원 선거구는 districts.yaml 에 아예 없다. 손으로 고를 수 있어야 한다."""
    preset, codes = scaffold.resolve_territory(None, None, [DA])
    assert preset is None
    assert codes == [DA]


def test_sources_combine_and_deduplicate():
    _, codes = scaffold.resolve_territory("test_gap", "시험구", [GA])
    assert sorted(codes) == sorted([GA, NA, DA]), "합쳐지되 중복은 한 번만"


def test_unknown_preset_lists_the_known_ones():
    with pytest.raises(scaffold.ScaffoldError, match="test_gap"):
        scaffold.resolve_territory("없는선거구", None, [])


def test_no_territory_source_is_an_error():
    with pytest.raises(scaffold.ScaffoldError, match="관할이 비었다"):
        scaffold.resolve_territory(None, None, [])


def test_creating_twice_is_refused(root):
    make(root, camp_id="test-camp")
    info = CampInfo(camp_id="test-camp", candidate_name="홍길동", created_at=dt.date(2026, 9, 8))
    with pytest.raises(scaffold.ScaffoldError, match="이미 있다"):
        scaffold.write_camp(info, root)


# --- 생성된 파일 -------------------------------------------------------------------


def test_generated_yaml_keeps_its_comments(root):
    """설정 파일은 판단 근거를 주석으로 안고 있는 것이 이 저장소의 관례다.
    safe_dump 로 만들면 그게 사라진다."""
    cid = make(root)
    body = (camp.cycle_dir("test-camp", cid, root) / "election.yaml").read_text(encoding="utf-8")
    assert "# 렌즈" in body
    assert "조용히 틀린다" in body

    roster = (camp.cycle_dir("test-camp", cid, root) / "candidates.yaml").read_text(
        encoding="utf-8"
    )
    assert "뒷조사 금지" in roster
    assert "other 로 자동 강등하지 않는다" in roster


def test_cycle_dir_has_the_same_shape_as_shared(root):
    """records/·rejected/ 규약이 양쪽에서 같아야 store.py 가 루트만 바꿔 재사용된다."""
    cid = make(root)
    target = camp.cycle_dir("test-camp", cid, root)
    for sub in ("records", "rejected", "incoming"):
        assert (target / sub).is_dir(), sub


def test_space_for_carries_shared_and_camp(root):
    cid = make(root)
    space = camp.space_for("test-camp", cid, root)
    assert space.camp_root == camp.cycle_dir("test-camp", cid, root)
    assert space.records.name == "records"


def test_round_trip(root):
    cid = make(root)
    info = camp.load_camp("test-camp", root)
    cycle = camp.load_cycle("test-camp", cid, root)
    roster = camp.load_roster("test-camp", cid, root)

    assert info.candidate_name == "홍길동"
    assert cycle.lineage is Camp.PROGRESSIVE
    assert cycle.territory.emd_codes == [GA, NA]
    assert roster.ours.party == "가당"
    assert roster.opponents == [], "후보 확정 전이면 비어 있어도 된다"


def test_listing(root):
    make(root, camp_id="camp-a")
    make(root, camp_id="camp-b")
    assert camp.list_camps(root) == ["camp-a", "camp-b"]
    assert camp.list_cycles("camp-a", root) == ["2028-04-12-national_assembly"]


def test_listing_is_empty_before_any_camp(root):
    assert camp.list_camps(root) == []


# --- 로스터 ----------------------------------------------------------------------


def test_duplicate_candidate_names_are_rejected():
    with pytest.raises(ValidationError, match="두 번"):
        camp.Roster.model_validate(
            {
                "ours": {"name": "홍길동", "party": "가당", "lineage": "progressive"},
                "opponents": [{"name": "홍길동", "party": "나당", "lineage": "conservative"}],
            }
        )


def test_opponent_note_carries_the_reasoning():
    """무소속·신당은 진영이 자명하지 않다. 근거를 적는 자리가 있어야 한다."""
    roster = camp.Roster.model_validate(
        {
            "ours": {"name": "홍길동", "party": "가당", "lineage": "progressive"},
            "opponents": [
                {
                    "name": "이영희",
                    "party": "무소속",
                    "lineage": "centrist",
                    "note": "경선 불복 탈당. 계보는 보수이나 중도 표방.",
                }
            ],
        }
    )
    assert roster.opponents[0].note


# --- 어느 주기가 "지금"인가 --------------------------------------------------------


def add_cycle(root, camp_id="test-camp", *, date, cycle_id=None, etype=None):
    """이미 있는 캠프에 주기를 하나 더 붙인다. `make` 와 달리 camp.yaml 을 안 만든다."""
    et = etype or ElectionType.NATIONAL_ASSEMBLY
    office = "national_assembly" if et is ElectionType.NATIONAL_ASSEMBLY else "basic_head"
    cycle = Cycle.model_validate(
        {
            "election": {"type": et, "office": office, "date": date},
            "lineage": Camp.PROGRESSIVE,
            "territory": {"preset": "test_gap", "emd_codes": [GA, NA]},
        }
    )
    cid = cycle_id or scaffold.default_cycle_id(cycle, f"미정-{et.value}")
    scaffold.write_cycle(camp_id, cid, cycle, "홍길동", "가당", False, root)
    return cid


TODAY = dt.date(2026, 9, 9)


def test_the_nearest_upcoming_election_wins(root):
    """캠프는 늘 '다음 선거'를 준비한다."""
    make(root, date=dt.date(2028, 4, 12))
    add_cycle(root, date=dt.date(2026, 6, 3), etype=ElectionType.LOCAL)
    soon = add_cycle(root, date=dt.date(2027, 3, 3))

    assert camp.current_cycle_id("test-camp", root, today=TODAY) == soon


def test_an_undated_cycle_never_beats_a_dated_one(root):
    """**여기가 이 규칙을 만든 이유다.**

    예전에는 폴더 이름 사전순 마지막을 골랐는데, 선거일을 모르는 주기의 이름이
    `미정-…` 이라 한글이 숫자보다 뒤로 갔다. 그래서 날짜를 모르는 주기가 언제나
    이겼고, 그러면 공표 금지기간(§108) 판정이 전부 불가로 떨어진다.
    """
    dated = make(root, date=dt.date(2028, 4, 12))
    undated = add_cycle(root, date=None)

    assert sorted([dated, undated])[-1] == undated, "사전순으로는 미정이 이긴다"
    assert camp.current_cycle_id("test-camp", root, today=TODAY) == dated


def test_an_undated_cycle_is_used_when_it_is_all_there_is(root):
    """마지막 수단으로는 쓴다. 주기가 하나뿐인데 안 고르면 화면이 아예 안 뜬다."""
    make(root, date=None, cycle_id="미정-national_assembly")
    assert camp.current_cycle_id("test-camp", root, today=TODAY) == "미정-national_assembly"


def test_the_most_recent_past_election_wins_when_all_are_over(root):
    """전부 지났으면 가장 최근에 치른 것. 다음 주기를 아직 안 만든 캠프다."""
    make(root, date=dt.date(2020, 4, 15))
    recent = add_cycle(root, date=dt.date(2024, 4, 10))

    assert camp.current_cycle_id("test-camp", root, today=TODAY) == recent


def test_election_day_itself_counts_as_upcoming(root):
    """선거 당일에 지난 선거로 넘어가면 그날 하루 화면이 옆 주기를 본다."""
    make(root, date=dt.date(2024, 4, 10))
    today_cycle = add_cycle(root, date=TODAY)

    assert camp.current_cycle_id("test-camp", root, today=TODAY) == today_cycle


def test_a_broken_cycle_is_skipped_not_fatal(root):
    """주기 하나가 깨졌다고 캠프 전체가 화면을 잃지는 않는다."""
    good = make(root, date=dt.date(2028, 4, 12))
    bad = add_cycle(root, date=dt.date(2030, 4, 10))
    path = camp.cycle_dir("test-camp", bad, root) / "election.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(GA, "9999999999"), encoding="utf-8")

    assert camp.current_cycle_id("test-camp", root, today=TODAY) == good


def test_no_cycles_is_none_not_an_error(root):
    scaffold.write_camp(
        CampInfo(camp_id="empty", candidate_name="홍길동", created_at=dt.date(2026, 9, 8)), root
    )
    assert camp.current_cycle_id("empty", root, today=TODAY) is None
