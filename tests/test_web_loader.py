"""L3 로더 — 무엇을 읽고 무엇을 숨기는가.

거르는 방식이 **화이트리스트**라는 것이 요점이다 (`docs/40-webapp-spec.md §5`).
시험 데이터 이름을 코드에 굽지 않고 kind + 선거구 소속으로 거른다. 그래야 다음에
다른 이름의 잔여물이 생겨도 자동으로 걸린다.

숨긴 것은 반드시 센다. 9가 10이 되거나 8이 되는 일을 조용히 넘기지 않기 위해서다.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_record
from votelink import store
from votelink.contract.enums import AgeBand, ElectionType
from votelink.reference import districts as districts_mod
from votelink.web.loader import (
    AmbiguousDistrict,
    load_all_emd,
    load_comparison,
    load_profiles,
)
from votelink.web.settings import WebSettings

CODES = ["1171051000", "1171052000", "1171056100"]
OUTSIDE = "1168051000"  # 강남구. 옆 지역구 데이터가 섞인 상황


@pytest.fixture(autouse=True)
def fresh_cache():
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


def write_districts(tmp_path, codes=CODES, extra: str = "") -> object:
    emd = "\n".join(f'      - {{name: 동{c[-4:]}, code: "{c}"}}' for c in codes)
    path = tmp_path / "districts.yaml"
    path.write_text(
        "districts:\n"
        "  - id: test_gap\n"
        "    name: 시험 지역구 갑\n"
        "    sido: 시험시\n"
        "    sigungu: 시험구\n"
        "    emd:\n"
        f"{emd}\n{extra}",
        encoding="utf-8",
    )
    return path


def profile_record(code: str, as_of: str = "2024-12", *, election_type: str = "presidential"):
    series = [
        {
            "election_id": f"2025-06-03-{election_type}",
            "election_date": "2025-06-03",
            "election_type": election_type,
            "camp_share": {
                "conservative": 50.0,
                "progressive": 50.0,
                "centrist": 0.0,
                "other": 0.0,
            },
            "turnout": 70.0,
            "gap_district": 1.0,
            "gap_sigungu": None,
            "gap_sido": None,
            "gap_nation": None,
        }
    ]
    return make_record(
        kind="segment_profile",
        geo_code=code,
        geo_name=f"동{code[-4:]}",
        natural_key=f"voter_profile|{election_type}|{code}|{as_of}",
        payload={
            "profile_type": "voter_profile",
            "as_of": as_of,
            "election_type": election_type,
            "lean_series": series,
            "swing": 0.0,
            "trend": "stable",
            "age_mix": {b.value: 100.0 / len(AgeBand) for b in AgeBand},
            "sex_ratio": 0.97,
            "population_total": 1000,
            "population_month": as_of,
        },
    )


def settings_for(tmp_path, **over) -> WebSettings:
    base = {
        "districts_path": write_districts(tmp_path),
        "records_root": tmp_path / "records",
    }
    base.update(over)
    return WebSettings(**base)


# --- 화이트리스트 ------------------------------------------------------------------


def test_records_outside_the_district_are_ignored(tmp_path):
    """옆 지역구 데이터가 섞여도 아무 에러가 없다 — 그래서 세어야 한다."""
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0]), profile_record(OUTSIDE)],
        root=tmp_path / "records",
    )
    result = load_profiles(settings_for(tmp_path))

    assert result.diagnostics.read == 2
    assert result.diagnostics.outside_district == 1
    assert [p.geo_code for p in result.profiles] == [CODES[0]]


def test_other_kinds_in_the_same_directory_do_not_leak(tmp_path):
    """`fake_collector.jsonl` 이 남아 있어도 카드 수가 변하지 않는다.

    이름을 블랙리스트에 굽지 않고 kind 로 거르기 때문이다.
    """
    root = tmp_path / "records"
    store.append_records("voter_profile", [profile_record(CODES[0])], root=root)
    store.append_records("fake_collector", [make_record(i) for i in range(5)], root=root)

    result = load_profiles(settings_for(tmp_path))
    assert result.diagnostics.read == 1  # news_article 은 세지도 않는다
    assert len(result.profiles) == 1


# --- 같은 동이 여러 장인 경우 --------------------------------------------------------


def test_only_the_newest_as_of_survives(tmp_path):
    """다음 달 인구로 재분석하면 같은 동의 레코드가 둘이 된다 (§6).

    분석기 버그가 아니라 의도된 보존이다. 고르는 것은 L3의 일이다.
    """
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0], "2024-12"), profile_record(CODES[0], "2025-03")],
        root=tmp_path / "records",
    )
    result = load_profiles(settings_for(tmp_path))

    assert len(result.profiles) == 1
    assert result.profiles[0].payload.as_of == "2025-03"
    assert result.diagnostics.superseded == 1  # 숨겼다고 반드시 말한다


def test_older_as_of_arriving_first_still_loses(tmp_path):
    """파일 안의 줄 순서에 결과가 좌우되지 않는다."""
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0], "2025-03"), profile_record(CODES[0], "2024-12")],
        root=tmp_path / "records",
    )
    result = load_profiles(settings_for(tmp_path))
    assert result.profiles[0].payload.as_of == "2025-03"


# --- 결측 노출 -------------------------------------------------------------------


def test_missing_dongs_are_reported(tmp_path):
    """'9 / 9' 의 오른쪽은 선거구 정의에서 온다. 왼쪽만 보여주면 결측이 안 보인다."""
    store.append_records("voter_profile", [profile_record(CODES[0])], root=tmp_path / "records")
    diag = load_profiles(settings_for(tmp_path)).diagnostics

    assert diag.loaded == 1
    assert diag.expected == 3
    assert diag.missing_codes == CODES[1:]
    assert not diag.is_complete


def test_complete_coverage_is_reported(tmp_path):
    store.append_records(
        "voter_profile", [profile_record(c) for c in CODES], root=tmp_path / "records"
    )
    diag = load_profiles(settings_for(tmp_path)).diagnostics
    assert diag.is_complete
    assert diag.missing_codes == []


def test_no_records_directory_is_not_a_crash(tmp_path):
    """서버가 안 뜨면 *왜* 비었는지 볼 화면조차 없다. 빈 결과를 돌려준다."""
    result = load_profiles(settings_for(tmp_path, records_root=tmp_path / "없다"))
    assert result.profiles == []
    assert result.diagnostics.loaded == 0
    assert result.diagnostics.expected == 3  # 무엇이 있어야 하는지는 여전히 안다


# --- 선거구 선택 -----------------------------------------------------------------


def test_single_district_is_picked_without_being_told(tmp_path):
    assert load_profiles(settings_for(tmp_path)).district.id == "test_gap"


def test_two_districts_without_a_choice_is_an_error(tmp_path):
    """조용히 첫 번째를 고르지 않는다 — 옆 지역구를 보여주며 맞다고 우기는 화면이 된다."""
    extra = (
        "  - id: test_eul\n"
        "    name: 시험 지역구 을\n"
        "    sido: 시험시\n"
        "    sigungu: 시험구\n"
        "    emd:\n"
        '      - {name: 딴동, code: "1171057000"}\n'
    )
    path = write_districts(tmp_path, extra=extra)
    settings = WebSettings(districts_path=path, records_root=tmp_path / "records")
    with pytest.raises(AmbiguousDistrict, match="--district"):
        load_profiles(settings)


def test_explicit_district_id_is_honoured(tmp_path):
    result = load_profiles(settings_for(tmp_path, district_id="test_gap"))
    assert result.district.id == "test_gap"


# --- 읽기 전용 -------------------------------------------------------------------


# --- 선거 계열 필터 -------------------------------------------------------------


def test_other_election_types_are_filtered_and_counted(tmp_path):
    """대선 파일에 총선 레코드가 섞여도 조용히 뭉개지 않는다."""
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0]), profile_record(CODES[0], election_type="national_assembly")],
        root=tmp_path / "records",
    )
    result = load_profiles(settings_for(tmp_path))  # 기본 = presidential
    assert [p.payload.election_type for p in result.profiles] == [ElectionType.PRESIDENTIAL]
    assert result.diagnostics.other_election_type == 1


def test_requesting_a_type_with_no_data_returns_empty(tmp_path):
    store.append_records(
        "voter_profile", [profile_record(c) for c in CODES], root=tmp_path / "records"
    )
    result = load_profiles(settings_for(tmp_path), election_type=ElectionType.NATIONAL_ASSEMBLY)
    assert result.profiles == []
    assert result.diagnostics.other_election_type == len(CODES)
    assert result.diagnostics.expected == len(CODES)  # 무엇이 있어야 하는지는 안다


# --- 선거구 비교 --------------------------------------------------------------------


def test_comparison_splits_loaded_from_skipped(tmp_path):
    extra = (
        "  - id: test_eul\n"
        "    name: 시험 지역구 을\n"
        "    sido: 시험시\n"
        "    sigungu: 시험구\n"
        "    emd:\n"
        '      - {name: 딴동, code: "1171057000"}\n'
    )
    path = write_districts(tmp_path, extra=extra)
    store.append_records(
        "voter_profile", [profile_record(c) for c in CODES], root=tmp_path / "records"
    )
    settings = WebSettings(districts_path=path, records_root=tmp_path / "records")

    comp = load_comparison(settings)
    assert [dp.district.id for dp in comp.rows] == ["test_gap"]
    assert [s.district_id for s in comp.skipped] == ["test_eul"]
    assert "voter_profile" in comp.skipped[0].fix  # 조치를 알려준다


def test_comparison_pending_district_says_so(tmp_path):
    extra = (
        "  - id: test_pending\n"
        "    name: 코드 없는 구\n"
        "    sido: 시험시\n"
        "    sigungu: 시험구\n"
        "    emd:\n"
        "      - {name: 미확정동, code: null}\n"
    )
    path = write_districts(tmp_path, extra=extra)
    store.append_records(
        "voter_profile", [profile_record(c) for c in CODES], root=tmp_path / "records"
    )
    comp = load_comparison(WebSettings(districts_path=path, records_root=tmp_path / "records"))
    skip = next(s for s in comp.skipped if s.district_id == "test_pending")
    assert "행정동코드" in skip.reason


# --- 전국 전체 동 -------------------------------------------------------------------


def test_all_emd_bypasses_the_district_filter(tmp_path):
    """전국은 선거구 하나가 아니다 — contains 필터를 건너뛴다."""
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0]), profile_record(OUTSIDE)],
        root=tmp_path / "records",
    )
    result = load_all_emd(settings_for(tmp_path))
    assert {p.geo_code for p in result.profiles} == {CODES[0], OUTSIDE}
    assert result.diagnostics.outside_district == 0


def test_all_emd_keeps_only_newest_as_of(tmp_path):
    store.append_records(
        "voter_profile",
        [profile_record(CODES[0], "2024-12"), profile_record(CODES[0], "2025-03")],
        root=tmp_path / "records",
    )
    result = load_all_emd(settings_for(tmp_path))
    assert len(result.profiles) == 1
    assert result.profiles[0].payload.as_of == "2025-03"
    assert result.diagnostics.superseded == 1


def test_loading_does_not_write_anything(tmp_path):
    """L3는 쓰지 않는다. 웹앱이 데이터를 만들면 derived_from 추적이 끊긴다."""
    root = tmp_path / "records"
    store.append_records("voter_profile", [profile_record(c) for c in CODES], root=root)
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}

    load_profiles(settings_for(tmp_path))

    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")}
    assert before == after
