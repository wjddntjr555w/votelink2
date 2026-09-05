"""D-002 — 22대(2024)를 47개 선거구로 확장하며 추가한 자동 유도 부분.

`_auto_district_match` 는 실제 `data/reference/districts.yaml` 의 name 에서 값을
유도한다 — 합성 데이터로는 이 신뢰 관계 자체를 검증할 수 없다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from votelink.collect.meta import CollectorMeta
from votelink.reference import districts as districts_mod

from ..collector import Collector

META = CollectorMeta.load(Path("collectors/nec_archive_assembly/meta.yaml"))


@pytest.fixture(autouse=True)
def fresh_cache():
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


def _collector(district_id: str) -> Collector:
    return Collector(meta=META, district_id=district_id)


class TestAutoDistrictMatch:
    @pytest.mark.parametrize(
        "district_id,expected_match,expected_name",
        [
            ("seoul_gangnam_gap", "강남구갑", "서울 강남구갑"),
            ("seoul_jongno", "종로구", "서울 종로구"),  # 갑/을/병 없는 단일 선거구
            ("seoul_jung_seongdong_eul", "중구성동구을", "서울 중구성동구을"),
            ("seoul_gangseo_byeong", "강서구병", "서울 강서구병"),
        ],
    )
    def test_derives_from_districts_yaml_name(self, district_id, expected_match, expected_name):
        result = _collector(district_id)._auto_district_match()
        assert result == {"district_match": expected_match, "district_name": expected_name}

    def test_only_applies_to_elections_marked_auto(self):
        """송파갑은 자기 elections 를 통째로 얹었으니 "{auto}" 마커가 없다 — 그대로 남는다."""
        election = _collector("seoul_songpa_gap")._election("2024-04-10-national_assembly")
        assert election["district_match"] == "송파구갑"

    def test_other_districts_use_auto_marker_at_config_level(self):
        gap_election = _collector("seoul_gangnam_gap")._election("2024-04-10-national_assembly")
        assert gap_election["district_match"] == "강남구갑"  # 이미 치환된 값
