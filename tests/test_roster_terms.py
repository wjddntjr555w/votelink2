"""district → 그 district 를 관할하는 캠프들의 로스터 합집합 (P-006).

**캠프별로 뉴스를 쪼개 수집하지 않는다** (P-001 §5). 이 모듈은 fetch 시점에 참고할
"이 district 를 관할하는 모든 캠프의 로스터 합집합"만 계산한다 — 그래서 여기서는
캠프 A/B 가 같은 district 를 공유할 때 이름이 제대로 합쳐지는지, 관할이 안 겹치는
캠프는 빠지는지, 깨진 캠프 설정 하나가 전체를 막지 않는지를 본다.
"""

from __future__ import annotations

import datetime as dt

import pytest

from votelink import camp
from votelink.camp import scaffold
from votelink.camp.models import CampInfo, Cycle
from votelink.contract.enums import Camp as CampLineage
from votelink.reference import districts as districts_mod

GA = "1111051500"
NA = "1111051600"
DA = "1111051700"


@pytest.fixture(autouse=True)
def _districts(tmp_path, monkeypatch):
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
    return tmp_path / "data"


def make_camp(root, camp_id, *, emd_codes, ours_name, ours_party, opponents=()):
    cycle = Cycle.model_validate(
        {
            "election": {
                "type": "national_assembly",
                "office": "national_assembly",
                "date": dt.date(2028, 4, 12),
            },
            "lineage": CampLineage.PROGRESSIVE,
            "territory": {"emd_codes": emd_codes},
        }
    )
    info = CampInfo(camp_id=camp_id, candidate_name=ours_name, created_at=dt.date(2026, 9, 8))
    cid = scaffold.default_cycle_id(cycle)
    scaffold.write_camp(info, root)
    scaffold.write_cycle(camp_id, cid, cycle, ours_name, ours_party, False, root)
    if opponents:
        roster = camp.load_roster(camp_id, cid, root)
        roster = camp.Roster.model_validate(
            {
                "ours": roster.ours.model_dump(),
                "opponents": [
                    {"name": n, "party": p, "lineage": "conservative"} for n, p in opponents
                ],
            }
        )
        scaffold.write_roster(camp_id, cid, roster, root)
    return cid


def test_camps_covering_district_intersects_by_emd(root):
    make_camp(root, "camp-a", emd_codes=[GA], ours_name="김철수", ours_party="가당")
    make_camp(root, "camp-outside", emd_codes=[DA], ours_name="최영수", ours_party="가당")

    rosters = camp.camps_covering_district("test_gap", camps_root=root)
    names = {r.ours.name for r in rosters}
    assert names == {"김철수"}


def test_multiple_camps_in_the_same_district_are_unioned(root):
    make_camp(root, "camp-a", emd_codes=[GA], ours_name="김철수", ours_party="가당")
    make_camp(root, "camp-b", emd_codes=[NA], ours_name="박영수", ours_party="다당")

    terms = camp.person_terms_for_district("test_gap", camps_root=root)
    assert terms == ["김철수", "박영수"]


def test_opponents_are_included(root):
    make_camp(
        root,
        "camp-a",
        emd_codes=[GA],
        ours_name="김철수",
        ours_party="가당",
        opponents=[("이영희", "나당")],
    )

    terms = camp.person_terms_for_district("test_gap", camps_root=root)
    assert terms == ["김철수", "이영희"]


def test_same_candidate_name_is_deduplicated(root):
    make_camp(root, "camp-a", emd_codes=[GA], ours_name="김철수", ours_party="가당")
    make_camp(root, "camp-b", emd_codes=[NA], ours_name="김철수", ours_party="가당")

    terms = camp.person_terms_for_district("test_gap", camps_root=root)
    assert terms == ["김철수"]


def test_a_broken_camp_is_skipped_not_fatal(root):
    make_camp(root, "camp-a", emd_codes=[GA], ours_name="김철수", ours_party="가당")
    good_cid = make_camp(root, "camp-b", emd_codes=[NA], ours_name="박영수", ours_party="다당")
    path = camp.cycle_dir("camp-b", good_cid, root) / "election.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(NA, "9999999999"), encoding="utf-8")

    terms = camp.person_terms_for_district("test_gap", camps_root=root)
    assert terms == ["김철수"], "camp-b 가 깨졌다고 camp-a 까지 안 보이면 안 된다"


def test_candidate_queries_use_name_and_party_as_a_qualifier(root):
    make_camp(root, "camp-a", emd_codes=[GA], ours_name="김철수", ours_party="가당")

    queries = camp.candidate_queries_for_district("test_gap", camps_root=root)
    assert queries == [{"id": camp.candidate_slug("김철수"), "q": "김철수 가당"}]


def test_candidate_slug_is_deterministic_ascii():
    assert camp.candidate_slug("김철수").isascii()
    assert camp.candidate_slug("김철수") == camp.candidate_slug("김철수")


def test_no_camps_is_an_empty_list_not_an_error(root):
    assert camp.person_terms_for_district("test_gap", camps_root=root) == []
