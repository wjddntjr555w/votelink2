"""선거구 정의 — 획정이 바뀌면 코드가 아니라 데이터를 고친다."""

import pytest

from votelink.reference import districts as mod
from votelink.reference import resolve_district


@pytest.fixture(autouse=True)
def fresh_cache():
    mod.reset_cache()
    yield
    mod.reset_cache()


def test_target_district_is_defined():
    d = resolve_district("seoul_songpa_gap")
    assert d.name == "서울 송파구 갑"
    assert len(d.emd) == 9


def test_lookup_by_name_also_works():
    assert resolve_district("서울 송파구 갑").id == "seoul_songpa_gap"


def test_codes_are_seven_digit_admm_codes():
    for code in resolve_district("seoul_songpa_gap").emd_codes:
        assert code.isdigit() and len(code) == 7


def test_contains_detects_outside_dong():
    d = resolve_district("seoul_songpa_gap")
    assert d.contains("3230040")  # 풍납1동
    assert d.contains("3230063")  # 잠실4동
    assert not d.contains("9999999")  # 존재하지 않는 코드


def test_name_lookup():
    assert resolve_district("seoul_songpa_gap").name_of("3230048") == "오륜동"


def test_unknown_district_lists_known_ones(tmp_path):
    with pytest.raises(mod.DistrictNotFound, match="seoul_songpa_gap"):
        resolve_district("없는선거구")


def test_duplicate_emd_is_rejected(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "districts:\n"
        "  - id: x\n    name: X\n    sido: S\n    sigungu: G\n"
        "    emd:\n"
        "      - {code: '3230040', name: A}\n"
        "      - {code: '3230040', name: A}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="두 번"):
        mod.load_districts(path, force=True)


def test_bad_code_length_is_rejected(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "districts:\n"
        "  - id: x\n    name: X\n    sido: S\n    sigungu: G\n"
        "    emd:\n      - {code: '11710530', name: A}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="7자리"):
        mod.load_districts(path, force=True)


def test_collector_targets_come_from_the_district():
    """수집기가 행정동 목록을 따로 들고 있지 않다는 확인."""
    from pathlib import Path

    from collectors.mois_population.collector import Collector
    from votelink.collect.meta import CollectorMeta

    meta = CollectorMeta.load(Path("collectors/mois_population/meta.yaml"))
    codes = Collector(meta=meta).target_codes()
    assert codes == resolve_district("seoul_songpa_gap").emd_codes
