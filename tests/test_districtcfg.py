"""`votelink.districtcfg.resolve_config` — meta.yaml 의 config 를 선거구 하나로 해석."""

from __future__ import annotations

import pytest

from votelink.districtcfg import resolve_config


def test_flat_config_passes_through_unchanged():
    flat = {"district": "seoul_songpa_gap", "endpoint": "x", "reference_month": "2024-12"}
    assert resolve_config("mois_population", flat) == flat


def test_flat_config_rejects_a_different_district():
    """옮겨지지 않은 수집기에 다른 선거구를 요구하면 조용히 엉뚱한 데이터를 수집하지 않는다."""
    flat = {"district": "seoul_songpa_gap"}
    with pytest.raises(KeyError, match="default_district/districts"):
        resolve_config("mois_population", flat, "seoul_songpa_eul")


def test_non_axis_top_level_keys_are_defaults():
    """common 을 안 써도 최상위 평평한 값이 기본값으로 흐른다."""
    cfg = {
        "endpoint": "x",
        "params": {"lv": "3"},
        "default_district": "seoul_songpa_gap",
        "districts": {"seoul_songpa_gap": {"sigungu_admm_code": "1171000000"}},
    }
    got = resolve_config("mois_population", cfg)
    assert got == {
        "endpoint": "x",
        "params": {"lv": "3"},
        "sigungu_admm_code": "1171000000",
        "district": "seoul_songpa_gap",
    }


def test_layered_config_merges_common_and_the_chosen_block():
    cfg = {
        "default_district": "seoul_songpa_gap",
        "common": {"endpoint": "x", "reference_month": "2024-12"},
        "districts": {
            "seoul_songpa_gap": {"sigungu_admm_code": "1171000000"},
            "seoul_songpa_eul": {"sigungu_admm_code": "1171000000", "endpoint": "y"},
        },
    }
    got = resolve_config("mois_population", cfg, "seoul_songpa_eul")
    assert got == {
        "endpoint": "y",  # 선거구 블록이 common 을 덮어쓴다
        "reference_month": "2024-12",
        "sigungu_admm_code": "1171000000",
        "district": "seoul_songpa_eul",  # 자동으로 채워진다
    }


def test_layered_config_falls_back_to_default_district():
    cfg = {
        "default_district": "seoul_songpa_gap",
        "common": {"endpoint": "x"},
        "districts": {"seoul_songpa_gap": {"sigungu_admm_code": "1171000000"}},
    }
    got = resolve_config("mois_population", cfg, None)
    assert got["district"] == "seoul_songpa_gap"
    assert got["sigungu_admm_code"] == "1171000000"


def test_unknown_district_block_is_an_error():
    cfg = {
        "common": {},
        "districts": {"seoul_songpa_gap": {}},
    }
    with pytest.raises(KeyError, match="seoul_gangnam_gap"):
        resolve_config("mois_population", cfg, "seoul_gangnam_gap")
