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


class TestLegacyElectionsGeneralization:
    """D-004 — 19~21대(선거구별 파일)도 "{auto}" 로 파일명을 유도한다.

    18대(2008)는 자동 확장에서 뺐다 — 파일명은 맞아도 그 시절 행정동 자체가
    지금과 다른 경우가 흔해서(관악구 '봉천제N동' 등, 추정 불가) 송파갑(개별
    검증됨) 말고는 지원하지 않는다.
    """

    def test_18th_is_not_generalized(self):
        assert _collector("seoul_gangnam_gap")._election("2008-04-09-national_assembly") is None

    def test_18th_still_works_for_songpa_gap(self):
        election = _collector("seoul_songpa_gap")._election("2008-04-09-national_assembly")
        assert election["selector"]["sheet"] == "송파구갑"

    def test_19th_file_name_is_derived(self):
        election = _collector("seoul_gangnam_gap")._election("2012-04-11-national_assembly")
        assert election["selector"]["file"].endswith("국희의원_서울_강남구갑.xls")

    def test_20th_and_21st_file_names_are_derived(self):
        for eid, filename in [
            ("2016-04-13-national_assembly", "개표상황(투표구별)_강남구갑.xlsx"),
            ("2020-04-15-national_assembly", "개표상황(투표구별)_강남구갑.xlsx"),
        ]:
            election = _collector("seoul_gangnam_gap")._election(eid)
            assert election["selector"]["file"].endswith(filename)

    def test_historically_absent_district_has_no_18th_or_19th(self):
        """중구성동구 갑/을은 2008~2020 엔 이 결합 형태가 없었다 — 22대만 지원한다."""
        col = _collector("seoul_jung_seongdong_eul")
        assert col._election("2008-04-09-national_assembly") is None
        assert col._election("2012-04-11-national_assembly") is None
        assert col._election("2016-04-13-national_assembly") is None
        assert col._election("2020-04-15-national_assembly") is None
        assert col._election("2024-04-10-national_assembly") is not None

    def test_third_split_district_starts_from_20th(self):
        """강남구병·강서구병은 3분할이 20대(2016)부터 생겼다 — 18·19대는 없다."""
        for did in ("seoul_gangnam_byeong", "seoul_gangseo_byeong"):
            col = _collector(did)
            assert col._election("2008-04-09-national_assembly") is None
            assert col._election("2012-04-11-national_assembly") is None
            assert col._election("2016-04-13-national_assembly") is not None
            assert col._election("2020-04-15-national_assembly") is not None
            assert col._election("2024-04-10-national_assembly") is not None

    def test_districts_with_persistent_boundary_drift_are_22nd_only(self):
        """노원구 갑/을·강동구 갑/을·강남구 을은 19~21대 파일명은 맞지만 실제
        동 개수가 today's districts.yaml 과 안 맞았다(실측, D-004) — 22대만 남긴다."""
        for did in (
            "seoul_nowon_gap",
            "seoul_nowon_eul",
            "seoul_gangdong_gap",
            "seoul_gangdong_eul",
            "seoul_gangnam_eul",
        ):
            col = _collector(did)
            assert col._election("2012-04-11-national_assembly") is None
            assert col._election("2016-04-13-national_assembly") is None
            assert col._election("2020-04-15-national_assembly") is None
            assert col._election("2024-04-10-national_assembly") is not None

    def test_districts_with_single_election_drift(self):
        """구로구 갑(19·20대만 어긋남)·은평구 갑·송파구 병(19대만 어긋남)."""
        col = _collector("seoul_guro_gap")
        assert col._election("2012-04-11-national_assembly") is None
        assert col._election("2016-04-13-national_assembly") is None
        assert col._election("2020-04-15-national_assembly") is not None

        for did in ("seoul_eunpyeong_gap", "seoul_songpa_byeong"):
            col = _collector(did)
            assert col._election("2012-04-11-national_assembly") is None
            assert col._election("2016-04-13-national_assembly") is not None

    def test_songpa_gap_legacy_elections_unchanged(self):
        """송파갑은 자기 elections 를 통째로 얹었으니 "{auto}" 가 아니다 — 회귀 없음."""
        col = _collector("seoul_songpa_gap")
        election = col._election("2012-04-11-national_assembly")
        assert election["selector"]["file"] == (
            "제19대 국회의원선거/제19대 국회의원선거(지역구)/01_서울/국희의원_서울_송파구갑.xls"
        )

    def test_election_not_in_this_districts_config_returns_none(self):
        """--reparse 는 이 collector_id 의 raw 이력 전체를 읽는다 — 중구성동구갑
        config 엔 없는 18대(2008) raw 를 만나도 설정 오류로 보지 않는다(그 시절엔
        '중구성동구' 결합 형태 자체가 없었다, D-004)."""
        col = _collector("seoul_jung_seongdong_gap")
        assert col._election("2008-04-09-national_assembly") is None


def test_parse_skips_batches_for_elections_not_in_this_districts_config():
    from votelink.collect.base import RawBatch

    col = _collector("seoul_jung_seongdong_gap")
    batch = RawBatch(
        collector_id=col.id, body={"election_id": "2008-04-09-national_assembly", "grid": []}
    )
    assert list(col.parse(batch)) == []
