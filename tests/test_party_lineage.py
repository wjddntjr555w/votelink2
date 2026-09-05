"""정당→진영 매핑 — 동명이인 지역구 후보 구분(D-003).

총선은 지역구 300여 곳이 같은 election_id 를 공유해서, 다른 지역구에 이름이
우연히 겹치는 후보가 나올 수 있다(2024년 서울 '이상규' 처럼). 그때만 `district`
필드로 더 좁게 구분한다는 것이 이 테스트의 핵심이다.
"""

from __future__ import annotations

import pytest

from votelink.contract.enums import Camp
from votelink.reference import party_lineage as lineage


@pytest.fixture(autouse=True)
def fresh_cache():
    lineage.reset_cache()
    yield
    lineage.reset_cache()


def write(tmp_path, text: str):
    path = tmp_path / "party_lineage.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_plain_lookup_ignores_district(tmp_path):
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 박정훈, camp: conservative }\n",
    )
    assert lineage.camp_of("2024-04-10-national_assembly", "박정훈", path=path) == Camp.CONSERVATIVE
    # district 를 줘도 plain 항목으로 넘어간다 — 대부분의 후보가 이 경로다.
    assert (
        lineage.camp_of("2024-04-10-national_assembly", "박정훈", "서울 송파구갑", path=path)
        == Camp.CONSERVATIVE
    )


def test_district_disambiguates_same_name(tmp_path):
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 이상규, camp: conservative,"
        ' district: "서울 성북구을" }\n'
        "  - { election: 2024-04-10-national_assembly, candidate: 이상규, camp: progressive,"
        ' district: "서울 관악구을" }\n',
    )
    assert (
        lineage.camp_of("2024-04-10-national_assembly", "이상규", "서울 성북구을", path=path)
        == Camp.CONSERVATIVE
    )
    assert (
        lineage.camp_of("2024-04-10-national_assembly", "이상규", "서울 관악구을", path=path)
        == Camp.PROGRESSIVE
    )


def test_missing_district_falls_through_to_not_found(tmp_path):
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 이상규, camp: conservative,"
        ' district: "서울 성북구을" }\n',
    )
    # district 전용 항목만 있고 plain 항목이 없으면, 다른 지역구(또는 district 없이)
    # 조회는 여전히 실패해야 한다 — 조용히 아무 진영에나 붙지 않는다.
    with pytest.raises(lineage.CampNotFound):
        lineage.camp_of("2024-04-10-national_assembly", "이상규", "서울 다른구갑", path=path)
    with pytest.raises(lineage.CampNotFound):
        lineage.camp_of("2024-04-10-national_assembly", "이상규", path=path)


def test_duplicate_plain_entry_is_rejected(tmp_path):
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 김철수, camp: conservative }\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 김철수, camp: progressive }\n",
    )
    with pytest.raises(ValueError, match="두 번"):
        lineage.load_lineage(path, force=True)


def test_duplicate_district_entry_is_rejected(tmp_path):
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 이상규, camp: conservative,"
        ' district: "서울 성북구을" }\n'
        "  - { election: 2024-04-10-national_assembly, candidate: 이상규, camp: progressive,"
        ' district: "서울 성북구을" }\n',
    )
    with pytest.raises(ValueError, match="두 번"):
        lineage.load_lineage(path, force=True)


def test_same_name_different_district_and_no_district_coexist(tmp_path):
    # 흔치 않지만: 대부분은 plain 하나, 특정 지역구만 다른 사람이라 district 로 예외 처리.
    path = write(
        tmp_path,
        "candidates:\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 홍길동, camp: conservative }\n"
        "  - { election: 2024-04-10-national_assembly, candidate: 홍길동, camp: progressive,"
        ' district: "서울 특이구갑" }\n',
    )
    assert (
        lineage.camp_of("2024-04-10-national_assembly", "홍길동", "서울 특이구갑", path=path)
        == Camp.PROGRESSIVE
    )
    assert (
        lineage.camp_of("2024-04-10-national_assembly", "홍길동", "서울 아무구을", path=path)
        == Camp.CONSERVATIVE
    )
