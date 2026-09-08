"""D-002 — 송파구 하드코딩을 없애고 districts.yaml 에서 유도하는 부분.

실제 `data/reference/districts.yaml`(커밋된, D-001 로 admmCd 가 채워진 것)을 그대로
쓴다 — 이 유도 로직 자체가 그 데이터를 신뢰하는 게 핵심이라 합성 데이터로는 의미가
옅다. 네트워크·raw 파일은 필요 없다(전부 config 해석 단계).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from votelink.collect.meta import CollectorMeta
from votelink.reference import districts as districts_mod

from ..collector import Collector

META = CollectorMeta.load(Path("collectors/nec_archive/meta.yaml"))


@pytest.fixture(autouse=True)
def fresh_cache():
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


def _collector(district_id: str) -> Collector:
    return Collector(meta=META, district_id=district_id)


class TestSigunguMatch:
    def test_songpa_unchanged(self):
        assert _collector("seoul_songpa_gap")._sigungu_match() == ("송파",)

    def test_derives_from_districts_yaml(self):
        assert _collector("seoul_gangnam_gap")._sigungu_match() == ("강남",)
        assert _collector("seoul_jongno")._sigungu_match() == ("종로",)

    def test_cross_sigungu_district_adds_extra_sigungu(self):
        # 중구성동구 을은 district.sigungu(중구)만으로는 성동구 4동을 놓친다 —
        # config.extra_sigungu 로 채운다(D-002).
        assert _collector("seoul_jung_seongdong_eul")._sigungu_match() == ("중", "성동")


class TestBaselineGeo:
    def test_songpa_matches_previously_hand_verified_values(self):
        geo = _collector("seoul_songpa_gap")._baseline_geo
        assert geo["nation"] == {"code": None, "name": "전국"}
        assert geo["sido"] == {"code": "1100000000", "name": "서울특별시"}
        assert geo["sigungu"] == {"code": "1171000000", "name": "송파구"}

    def test_derives_sigungu_code_prefix_from_emd_codes(self):
        geo = _collector("seoul_gangnam_gap")._baseline_geo
        assert geo["sigungu"] == {"code": "1168000000", "name": "강남구"}

    def test_uses_five_digit_prefix_for_gwangjin(self):
        # 광진(11215)·강북(11305)·금천(11545)은 5번째 자리가 0이 아니다 — 4자리로
        # 자르면 존재하지 않는 코드가 나온다. primary_sigungu_code 로 통일했다(D-006).
        geo = _collector("seoul_gwangjin_gap")._baseline_geo
        assert geo["sigungu"] == {"code": "1121500000", "name": "광진구"}

    def test_cross_sigungu_district_uses_majority_prefix(self):
        # 중구성동구 을은 중구 15동 + 성동구 4동(금호1~4가동·옥수동)이 섞여 있다.
        # district.sigungu == "중구" 이므로 다수인 중구 접두사(1114)를 써야 한다.
        geo = _collector("seoul_jung_seongdong_eul")._baseline_geo
        assert geo["sigungu"]["name"] == "중구"
        assert geo["sigungu"]["code"].startswith("1114")


class TestFmtSigungu:
    def test_substitutes_placeholder(self):
        assert Collector._fmt_sigungu("{sigungu}", "강남구") == "강남구"

    def test_leaves_plain_string_untouched(self):
        assert Collector._fmt_sigungu("송파구", "강남구") == "송파구"

    def test_none_stays_none(self):
        assert Collector._fmt_sigungu(None, "강남구") is None
