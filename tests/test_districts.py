"""선거구 정의 — 획정이 바뀌면 코드가 아니라 데이터를 고친다."""

import pytest

from votelink.reference import districts as mod
from votelink.reference import resolve_district

TARGET = "seoul_songpa_gap"


@pytest.fixture(autouse=True)
def fresh_cache():
    mod.reset_cache()
    yield
    mod.reset_cache()


def write(tmp_path, emd_yaml: str):
    path = tmp_path / "d.yaml"
    path.write_text(
        f"districts:\n  - id: x\n    name: X\n    sido: S\n    sigungu: G\n    emd:\n{emd_yaml}",
        encoding="utf-8",
    )
    return path


# --- 실제 정의 -----------------------------------------------------------------


def test_target_district_is_defined():
    d = resolve_district(TARGET)
    assert d.name == "서울 송파구 갑"
    assert len(d.emd) == 9


def test_lookup_by_name_also_works():
    assert resolve_district("서울 송파구 갑").id == TARGET


def test_org_codes_are_recorded():
    """사용자가 준 행정기관코드 7자리는 참고용으로 남긴다."""
    d = resolve_district(TARGET)
    assert d.emd[0].org_code == "3230040"
    assert {e.org_code for e in d.emd} >= {"3230048", "3230065"}


def test_internal_codes_are_still_pending():
    """행정동코드 10자리를 아직 모른다는 사실이 드러나야 한다.

    모르는 것을 그럴듯한 값으로 채우면 조용히 엉뚱한 동네를 수집한다.
    """
    d = resolve_district(TARGET)
    assert not d.fully_resolved
    assert len(d.pending) == 9
    assert d.emd_codes == []


def test_unknown_district_lists_known_ones():
    with pytest.raises(mod.DistrictNotFound, match=TARGET):
        resolve_district("없는선거구")


# --- 모델 규칙 -----------------------------------------------------------------


def test_resolved_codes_are_exposed(tmp_path):
    path = write(
        tmp_path,
        "      - {name: 가, code: '1111054000'}\n      - {name: 나, org_code: '3230041'}\n",
    )
    d = mod.load_districts(path, force=True)["x"]
    assert d.emd_codes == ["1111054000"]
    assert [e.name for e in d.pending] == ["나"]


def test_contains_and_name_lookup(tmp_path):
    path = write(tmp_path, "      - {name: 가, code: '1111054000'}\n")
    d = mod.load_districts(path, force=True)["x"]
    assert d.contains("1111054000")
    assert not d.contains("9999999999")
    assert d.name_of("1111054000") == "가"


def test_bad_code_length_is_rejected(tmp_path):
    """통계청 8자리 코드를 그대로 넣는 실수를 막는다."""
    path = write(tmp_path, "      - {name: 가, code: '11710530'}\n")
    with pytest.raises(ValueError, match="10자리"):
        mod.load_districts(path, force=True)


@pytest.mark.parametrize(
    ("emd_yaml", "label"),
    [
        (
            "      - {name: 가, code: '1111054000'}\n      - {name: 나, code: '1111054000'}\n",
            "행정동코드",
        ),
        (
            "      - {name: 가, org_code: '3230040'}\n      - {name: 나, org_code: '3230040'}\n",
            "행정기관코드",
        ),
        ("      - {name: 가}\n      - {name: 가}\n", "행정동명"),
    ],
)
def test_duplicates_are_rejected(tmp_path, emd_yaml, label):
    with pytest.raises(ValueError, match=label):
        mod.load_districts(write(tmp_path, emd_yaml), force=True)


# --- 수집기와의 연결 ------------------------------------------------------------


def test_collector_has_no_district_list_of_its_own():
    from pathlib import Path

    from collectors.mois_population.collector import Collector
    from votelink.collect.meta import CollectorMeta

    meta = CollectorMeta.load(Path("collectors/mois_population/meta.yaml"))
    assert Collector(meta=meta).target_codes() == resolve_district(TARGET).emd_codes
