"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

축소판: 행정동 3개 × 대선 1계열. 손으로 계산할 수 있게 숫자를 둔다.
- A(풍납1동): 인구 큼, 변동성 큼, 접전, turnout_gap 여유 큼   → 상위여야 한다
- B(오륜동):  인구 작음, 변동성 작음, 보수 우세, 여유 작음     → 하위여야 한다
- C(방이1동): 중간, turnout_gap 입력 없음                      → has_turnout=False 경로
"""

import pytest

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.models import Record
from votelink.reference import districts as districts_mod

from ..analyzer import Analyzer

META = AnalyzerMeta.model_validate(
    {
        "id": "target_priority",
        "name": "시험용",
        "inputs": ["segment_profile", "turnout_gap"],
        "outputs": ["target_priority"],
        "geo_level": "emd",
        "config": {
            "default_district": "test_district",
            "common": {
                "weights": {
                    "size": 0.2,
                    "volatility": 0.3,
                    "competitiveness": 0.3,
                    "turnout_headroom": 0.2,
                },
                "segment_cuts": {
                    "volatility_hi": 60,
                    "competitiveness_hi": 60,
                    "competitiveness_mid": 40,
                    "competitiveness_lo": 25,
                    "turnout_headroom_hi": 60,
                },
            },
            "districts": {"test_district": {}},
        },
    }
)

CODES = {"1171051000": "풍납1동", "1171060000": "오륜동", "1171058000": "방이1동"}


@pytest.fixture(autouse=True)
def _district(tmp_path, monkeypatch):
    """districts.yaml 을 축소판으로 갈아끼운다. 실제 파일을 읽지 않는다."""
    path = tmp_path / "districts.yaml"
    emd = "\n".join(f'      - {{ name: "{n}", code: "{c}" }}' for c, n in CODES.items())
    path.write_text(
        "version: test\ndistricts:\n"
        "  - id: test_district\n"
        "    name: 시험 선거구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 시험구\n"
        "    source: test\n"
        "    emd:\n" + emd + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(districts_mod, "DISTRICTS_PATH", path)
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


AGE_MIX = {
    "0-9": 5.0,
    "10-19": 10.0,
    "20-29": 15.0,
    "30-39": 15.0,
    "40-49": 15.0,
    "50-59": 15.0,
    "60-69": 10.0,
    "70-79": 10.0,
    "80+": 5.0,
}


def _shares(con: float) -> dict:
    """보수 con %, 중도·기타 0.5 씩, 나머지 진보. 합 100."""
    return {"conservative": con, "progressive": 100.0 - con - 1.0, "centrist": 0.5, "other": 0.5}


def _profile(code: str, name: str, *, pop: int, swing: float, con_latest: float) -> Record:
    con_first = con_latest - swing  # 최신이 최댓값이 되도록
    return Record(
        kind="segment_profile",
        collector_id="fake_voter_profile",
        source_name="시험",
        source_license="public_open",
        observed_at="2024-12-01T00:00:00+09:00",
        observed_precision="month",
        geo_level="emd",
        geo_code=code,
        geo_name=name,
        confidence=0.5,
        derived_from=["a" * 16],
        natural_key=f"voter_profile|presidential|{code}|2024-12",
        payload={
            "profile_type": "voter_profile",
            "as_of": "2024-12",
            "election_type": "presidential",
            "lean_series": [
                {
                    "election_id": "2019-01-01-presidential",
                    "election_date": "2019-01-01",
                    "election_type": "presidential",
                    "camp_share": _shares(con_first),
                    "turnout": 70.0,
                },
                {
                    "election_id": "2022-03-09-presidential",
                    "election_date": "2022-03-09",
                    "election_type": "presidential",
                    "camp_share": _shares(con_latest),
                    "turnout": 72.0,
                },
            ],
            "swing": swing,
            "trend": "conservative_shift",
            "age_mix": AGE_MIX,
            "sex_ratio": 1.0,
            "population_total": pop,
            "population_month": "2024-12",
        },
    )


def _turnout(code: str, name: str, *, mean_gap: float) -> Record:
    return Record(
        kind="turnout_gap",
        collector_id="fake_turnout_gap",
        source_name="시험",
        source_license="public_open",
        observed_at="2022-03-09T00:00:00+09:00",
        observed_precision="day",
        geo_level="emd",
        geo_code=code,
        geo_name=name,
        confidence=0.9,
        derived_from=["b" * 16],
        natural_key=f"turnout_gap|presidential|{code}|2022-03-09",
        payload={
            "election_type": "presidential",
            "emd_name": name,
            "points": [
                {
                    "election_id": "2022-03-09-presidential",
                    "turnout": 0.70,
                    "baseline": 0.70 - mean_gap,
                    "gap": mean_gap,
                    "eligible_voters": 10000,
                    "total_votes": 7000,
                }
            ],
            "latest_gap": mean_gap,
            "mean_gap": mean_gap,
            "gap_slope": 0.0,
            "below_baseline": mean_gap < 0,
            "elections_used": 1,
            "as_of": "2022-03-09",
        },
    )


def make_inputs() -> list[Record]:
    return [
        _profile("1171051000", "풍납1동", pop=30000, swing=12.0, con_latest=48.0),
        _profile("1171060000", "오륜동", pop=18000, swing=4.0, con_latest=60.0),
        _profile("1171058000", "방이1동", pop=25000, swing=8.0, con_latest=52.0),
        _turnout("1171051000", "풍납1동", mean_gap=-0.05),  # 평균보다 낮음 → 여유 큼
        _turnout("1171060000", "오륜동", mean_gap=-0.01),
        # 방이1동은 turnout_gap 없음
    ]


def run() -> list[Record]:
    results = list(Analyzer(meta=META).compute(make_inputs()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    return results


# --- 계약 -----------------------------------------------------------------------


def test_output_records_are_valid():
    records = run()
    assert records, "입력이 있는데 산출이 하나도 없다"
    assert len(records) == 3
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.collector_id == Analyzer.id
        assert r.geo_code is not None
        assert r.kind == "target_priority"


def test_evidence_is_recorded():
    for r in run():
        assert r.derived_from, "derived_from 이 비었다"
        assert len(set(r.derived_from)) == len(r.derived_from)


def test_confidence_is_not_certain_and_drops_without_turnout():
    by_code = {r.geo_code: r for r in run()}
    assert by_code["1171051000"].confidence == 0.65  # 두 입력 다 있음
    assert by_code["1171058000"].confidence == 0.4  # turnout_gap 없음
    for r in by_code.values():
        assert r.confidence < 1.0


def test_observed_at_points_at_the_input_not_the_run():
    inputs = make_inputs()
    latest_input = max(r.observed_at for r in inputs)
    for r in run():
        assert r.observed_at <= latest_input


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    assert [r.record_id for r in run()] == [r.record_id for r in run()]


def test_empty_input_is_an_error():
    try:
        list(Analyzer(meta=META).compute([]))
    except AnalyzeError:
        return
    raise AssertionError("입력 0건인데 AnalyzeError 가 나지 않았다")


# --- 변별력 -------------------------------------------------------------------


def test_attention_score_discriminates_between_units():
    """모든 동에서 같은 값이 나오면 이 지표는 아무것도 말하지 않는다 (§9)."""
    scores = {r.geo_code: r.payload["attention_score"] for r in run()}
    assert len(set(scores.values())) == 3, f"동마다 값이 갈리지 않는다: {scores}"


def test_rank_is_a_dense_ordering_within_the_group():
    ranks = sorted(r.payload["rank"] for r in run())
    assert ranks == [1, 2, 3]
    for r in run():
        assert r.payload["group_size"] == 3


def test_high_volatility_competitive_dong_outranks_the_safe_one():
    """A(변동성·접전 큼) 가 B(보수 우세·저변동) 보다 앞선다 — 블렌드가 의도대로 작동."""
    by_code = {r.geo_code: r for r in run()}
    assert by_code["1171051000"].payload["rank"] < by_code["1171060000"].payload["rank"]


def test_indices_stay_in_range():
    for r in run():
        p = r.payload
        for key in (
            "size_index",
            "volatility_index",
            "competitiveness_index",
            "turnout_headroom",
            "attention_score",
        ):
            assert 0.0 <= p[key] <= 100.0, f"{key}={p[key]}"


def test_dong_without_turnout_input_has_zero_headroom():
    by_code = {r.geo_code: r for r in run()}
    assert by_code["1171058000"].payload["turnout_headroom"] == 0.0
    assert by_code["1171058000"].payload["has_turnout_input"] is False
