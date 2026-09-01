"""행정동코드 변환 — 매핑 실패는 조용히 넘어가지 않는다."""

import pytest

from votelink.collect import geo


def test_lookup_by_source_code(geo_table):
    assert geo.to_emd_code("3230040", system="mois") == "1111054000"


def test_lookup_across_systems(geo_table):
    """선관위 코드도 같은 행정동으로 수렴해야 한다."""
    assert geo.to_emd_code("SP-01", system="nec") == "1111054000"


def test_lookup_by_name(geo_table):
    assert geo.to_emd_code("서울특별시 시험구 가나동") == "1111054000"


def test_name_whitespace_is_normalized(geo_table):
    assert geo.to_emd_code(" 서울특별시  시험구 가나동 ") == "1111054000"


def test_ambiguous_name_is_refused(geo_table):
    """같은 동 이름이 여러 시군구에 있으면 찍지 않고 거부한다."""
    with pytest.raises(geo.GeoMappingError, match="여러 시군구"):
        geo.to_emd_code("신흥동")


def test_unknown_value_raises(geo_table):
    with pytest.raises(geo.GeoMappingError, match="변환하지 못했다"):
        geo.to_emd_code("없는동")


def test_empty_value_raises(geo_table):
    with pytest.raises(geo.GeoMappingError):
        geo.to_emd_code("   ")


def test_empty_table_gives_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(geo, "REFERENCE_CSV", tmp_path / "missing.csv")
    geo.reset_table()
    with pytest.raises(geo.GeoMappingError, match="votelink geo import"):
        geo.to_emd_code("가나동")
    geo.reset_table()


def test_never_returns_none(geo_table):
    """계약상 to_emd_code 는 None 을 돌려줄 수 없다."""
    assert geo.to_emd_code("다라동") is not None
