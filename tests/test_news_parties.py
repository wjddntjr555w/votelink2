"""뉴스 검색용 정당명 전역 목록 — 운영자 CRUD (P-006 §5).

`party_lineage.yaml` 과 달리 판단 근거가 없는 단순 문자열 리스트이므로 원문 편집이
아니라 add/update/delete 순수 함수로 관리한다. 여기서는 그 CRUD 가 실제로 디스크를
정확히 갱신하는지, 검색어가 두 종류(정당+지역, 정당 단독) 모두 나오는지를 본다.
"""

from __future__ import annotations

import pytest

from votelink.reference import news_parties as np


@pytest.fixture
def path(tmp_path):
    return tmp_path / "news_parties.yaml"


def test_empty_list_before_anything_added(path):
    assert np.list_parties(path) == []


def test_add_and_list(path):
    party = np.add_party("국민의힘", path)
    assert party.name == "국민의힘"
    assert party.id.isascii()
    assert [p.name for p in np.list_parties(path)] == ["국민의힘"]


def test_adding_the_same_name_twice_does_not_duplicate(path):
    first = np.add_party("국민의힘", path)
    second = np.add_party("국민의힘", path)
    assert first.id == second.id
    assert len(np.list_parties(path)) == 1


def test_update_renames_in_place(path):
    party = np.add_party("국민의힘", path)
    updated = np.update_party(party.id, "개혁신당", path)
    assert updated.id == party.id
    assert [p.name for p in np.list_parties(path)] == ["개혁신당"]


def test_update_unknown_id_raises(path):
    with pytest.raises(np.PartyNotFound):
        np.update_party("party-ffffffff", "개혁신당", path)


def test_delete_removes_it(path):
    party = np.add_party("국민의힘", path)
    np.delete_party(party.id, path)
    assert np.list_parties(path) == []


def test_delete_unknown_id_raises(path):
    with pytest.raises(np.PartyNotFound):
        np.delete_party("party-ffffffff", path)


def test_list_is_sorted_by_name(path):
    np.add_party("더불어민주당", path)
    np.add_party("국민의힘", path)
    assert [p.name for p in np.list_parties(path)] == ["국민의힘", "더불어민주당"]


def test_survives_a_reload(path):
    np.add_party("국민의힘", path)
    assert [p.name for p in np.list_parties(path)] == ["국민의힘"]


# --- 검색어 파생 -----------------------------------------------------------------


def test_queries_include_region_and_standalone_forms(path):
    np.add_party("국민의힘", path)
    queries = np.party_queries_for_geo("서울 송파구", path)
    qs = {q["q"] for q in queries}
    assert "국민의힘 서울 송파구" in qs
    assert "국민의힘" in qs
    assert len(queries) == 2


def test_no_limit_on_party_count(path):
    for i in range(30):
        np.add_party(f"정당{i}", path)
    assert len(np.list_parties(path)) == 30
