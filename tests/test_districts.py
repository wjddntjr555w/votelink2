"""선거구 정의 — 획정이 바뀌면 코드가 아니라 데이터를 고친다."""

import json

import pytest

from votelink import store
from votelink.reference import districts as mod
from votelink.reference import resolve_district
from votelink.store import DataSpace

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


def test_internal_codes_are_all_confirmed():
    """송파갑 9개 행정동코드가 전부 채워져 있다 (2026-09-01 백필).

    값은 전부 mois_population 실제 응답에서 왔다. 모르는 것을 그럴듯한 값으로
    채우면 조용히 엉뚱한 동네를 수집하므로, 추정값은 하나도 넣지 않는다.
    미확인 상태를 표현하는 모델 쪽 동작은 test_resolved_codes_are_exposed 가 지킨다.
    """
    d = resolve_district(TARGET)
    assert d.fully_resolved
    assert d.pending == []
    codes = d.emd_codes
    assert len(codes) == 9
    assert len(set(codes)) == 9, "같은 코드가 두 동에 붙었다"
    for code in codes:
        assert code.isdigit() and len(code) == 10, f"행정동코드가 아니다: {code}"
        # 1171 = 서울 송파구. 옆 시군구 코드를 붙여넣는 사고를 잡는다.
        assert code.startswith("1171"), f"송파구 코드가 아니다: {code}"


def test_internal_codes_match_what_mois_actually_collected():
    """선거구 정의의 코드가 인구 레코드의 geo_code 와 실제로 만나야 한다.

    이게 어긋나면 L2에서 선거결과와 인구를 조인할 수 없다 — 두 수집기를
    만든 이유가 통째로 사라진다. 레코드가 아직 없으면 검증할 게 없으므로 skip.

    `records/mois_population.jsonl` 은 선거구별로 나뉘지 않는다(`docs/11-storage.md`)
    — 다른 선거구를 collect 하면 같은 파일에 쌓인다(D-001, 47개 선거구 백필).
    그래서 '정확히 일치'가 아니라 'TARGET 의 코드가 전부 그 안에 있다'로 확인한다.
    """
    # 경로를 손으로 적지 않는다 — 레이아웃이 바뀌면 이 테스트가 실패가 아니라 조용한
    # skip 으로 변한다 (P-001 1b 이전 때 실제로 그랬다). DataSpace 가 레이아웃의 진실이다.
    # 루트 conftest 의 가드가 store.SHARED_DIR 을 tmp 로 돌리므로 실제 공간을 직접 만든다 —
    # 이 테스트는 저장소에 **실제로 쌓인** 레코드를 보는 것이 목적이다.
    records = DataSpace(store.DATA_DIR / "shared").record_file("mois_population")
    if not records.exists():
        pytest.skip("mois_population 레코드가 아직 없다")

    lines = [line for line in records.read_text("utf-8").splitlines() if line.strip()]
    collected = {json.loads(line)["geo_code"] for line in lines}
    defined = set(resolve_district(TARGET).emd_codes)
    missing = defined - collected
    assert not missing, f"선거구 정의에 있는데 수집 레코드에는 없다: {missing}"


def test_unknown_district_lists_known_ones():
    with pytest.raises(mod.DistrictNotFound, match=TARGET):
        resolve_district("없는선거구")


def test_sigungu_codes_use_five_digit_prefix():
    """시군구 코드는 행정동코드 앞 5자리 + "00000" 이다.

    앞 4자리로 자르면 5번째 자리가 0이 아닌 구 — 서울 광진(11215)·강북(11305)·
    금천(11545) — 에서 틀린다. 송파(11710)는 5번째가 0이라 [:4] 로도 우연히 맞았고,
    그래서 이 버그가 여태 안 드러났다. naver_news 가 실제로 저장한 geo_code 와 대조.
    """
    assert resolve_district("seoul_gwangjin_gap").sigungu_codes == ["1121500000"]
    assert resolve_district("seoul_gangbuk_gap").sigungu_codes == ["1130500000"]
    assert resolve_district("seoul_geumcheon").sigungu_codes == ["1154500000"]
    assert resolve_district("seoul_songpa_gap").sigungu_codes == ["1171000000"]


def test_sigungu_codes_span_two_sigungu_when_district_does():
    """중구·성동구 을은 두 자치구에 걸친다 — 코드도 둘 다, 오름차순으로."""
    assert resolve_district("seoul_jung_seongdong_eul").sigungu_codes == [
        "1114000000",
        "1120000000",
    ]


def test_primary_sigungu_code_uses_same_five_digit_rule_as_sigungu_codes():
    """nec_archive 기준선과 voter_profile 대조가 공유하는 단일 자치구 코드(D-006).

    sigungu_codes 와 같은 5자리 규칙이라야 한다 — 4자리는 광진·강북·금천에서
    틀리고, 그 경우 voter_profile 이 자기 자치구 기준선을 못 찾아 gap_sigungu 가
    None 으로 떨어진다.
    """
    assert resolve_district("seoul_gwangjin_gap").primary_sigungu_code == "1121500000"
    assert resolve_district("seoul_gangbuk_eul").primary_sigungu_code == "1130500000"
    assert resolve_district("seoul_geumcheon").primary_sigungu_code == "1154500000"
    # 송파(11710)는 [:4] 와 [:5] 가 같아 값이 안 바뀐다 — 송파갑 검증 회귀 방지.
    assert resolve_district("seoul_songpa_gap").primary_sigungu_code == "1171000000"


def test_primary_sigungu_code_picks_dominant_sigungu_when_district_spans_two():
    """중구성동구 을은 중구 15동 + 성동구 4동 — 더 많은 중구(1114)를 쓴다.

    sigungu_codes 는 둘 다 주지만, 기준선은 하나여야 하므로 다수 자치구로 좁힌다
    (nec_archive._baseline_geo 와 같은 선택).
    """
    assert resolve_district("seoul_jung_seongdong_eul").primary_sigungu_code == "1114000000"
    assert resolve_district("seoul_jung_seongdong_gap").primary_sigungu_code == "1120000000"


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
    """수집기는 동 목록을 따로 들고 있지 않다 — 시군구 코드 하나로 조회하고,
    대상 동 이름은 district 정의에서 가져와 응답을 걸러낸다."""
    from pathlib import Path

    from collectors.mois_population.collector import Collector
    from votelink.collect.meta import CollectorMeta

    meta = CollectorMeta.load(Path("collectors/mois_population/meta.yaml"))
    collector = Collector(meta=meta)
    # 시군구 코드는 이제 선거구 블록 안에 있다 — 해석된 config 로 확인한다.
    resolved = meta.resolved_config(None)
    assert collector.query_codes() == [resolved["sigungu_admm_code"]]
    assert collector._target_names() == {e.name for e in resolve_district(TARGET).emd}
