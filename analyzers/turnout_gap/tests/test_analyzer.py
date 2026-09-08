"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

축소판: 동 3개 × 대선 3회. 손으로 계산할 수 있는 숫자를 쓴다 —
선거인수를 1000으로 고정하면 투표수가 곧 투표율(‰)이라 기준선을 암산할 수 있다.
"""

from datetime import datetime

import pytest

from votelink.analyze import AnalyzeError, Rejected
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.models import KST, Record
from votelink.reference import districts as districts_mod

from ..analyzer import Analyzer

META = AnalyzerMeta.model_validate(
    {
        "id": "turnout_gap",
        "name": "시험용",
        "inputs": ["election_result"],
        "outputs": ["turnout_gap"],
        "geo_level": "emd",
        "config": {
            "default_district": "test_district",
            "common": {"min_elections_for_slope": 3},
            "districts": {"test_district": {}},
        },
    }
)

CODES = {"1111051500": "높은동", "1111051600": "보통동", "1111051700": "낮은동"}

# 회차별 (동코드 → 투표수). 선거인수는 전부 1000.
# 높은동은 늘 평균 위, 낮은동은 늘 평균 아래이고 **격차가 벌어진다** —
# 실제 송파갑에서 관찰된 모양(오륜동 +1.9→+9.7, 방이2동 -1.5→-7.7)의 축소판이다.
BALLOTS = {
    "2017-05-09-presidential": {"1111051500": 810, "1111051600": 800, "1111051700": 790},
    "2022-03-09-presidential": {"1111051500": 730, "1111051600": 700, "1111051700": 670},
    "2025-06-03-presidential": {"1111051500": 660, "1111051600": 600, "1111051700": 540},
}


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


def make_inputs() -> list[Record]:
    records = []
    for eid, ballots in BALLOTS.items():
        for code, votes in ballots.items():
            records.append(
                Record(
                    kind="election_result",
                    collector_id="fake_nec",
                    source_name="시험",
                    source_license="public_open",
                    observed_at=datetime.fromisoformat(eid[:10]).replace(tzinfo=KST),
                    observed_precision="day",
                    geo_level="emd",
                    geo_code=code,
                    geo_name=CODES[code],
                    confidence=1.0,
                    natural_key=f"{eid}|{code}",
                    payload={
                        "election_id": eid,
                        "election_type": "presidential",
                        "district_name": "시험 선거구",
                        "eligible_voters": 1000,
                        "total_votes": votes,
                        "invalid_votes": 0,
                        "results": [{"party": "가당", "candidate": "갑", "votes": votes}],
                    },
                )
            )
    return records


def run() -> list[Record]:
    results = list(Analyzer(meta=META).compute(make_inputs()))
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목이 있다: {[r.short_reason for r in rejected]}"
    return results


def by_name(records: list[Record]) -> dict[str, Record]:
    return {r.geo_name: r for r in records}


# --- 계약 -----------------------------------------------------------------------


def test_output_records_are_valid():
    records = run()
    assert len(records) == 3, "동 3개 × 계열 1개"
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.collector_id == Analyzer.id
        assert r.geo_code is not None


def test_evidence_is_recorded():
    """근거를 못 대는 결론은 실패로 간주한다."""
    for r in run():
        assert r.derived_from
        assert len(set(r.derived_from)) == len(r.derived_from), "derived_from 에 중복이 있다"


def test_evidence_includes_the_whole_election_not_just_this_dong():
    """기준선이 그 회차의 모든 동을 쓰므로, 한 동의 결론은 나머지 동에도 의존한다."""
    for r in run():
        assert len(r.derived_from) == 9, "3회차 × 동 3개 = 9건이 근거여야 한다"


def test_confidence_is_not_certain():
    for r in run():
        assert r.confidence < 1.0


def test_observed_at_points_at_the_input_not_the_run():
    inputs = make_inputs()
    latest = max(r.observed_at for r in inputs)
    for r in run():
        assert r.observed_at <= latest


# --- 순수성 ---------------------------------------------------------------------


def test_compute_is_deterministic():
    assert [r.record_id for r in run()] == [r.record_id for r in run()]


def test_empty_input_is_an_error():
    with pytest.raises(AnalyzeError):
        list(Analyzer(meta=META).compute([]))


def test_records_outside_the_district_are_ignored():
    """관할 밖 동이 섞여 들어와도 기준선을 오염시키지 않는다."""
    outsider = make_inputs()[0].model_copy(deep=True)
    outsider.geo_code = "9999999999"
    outsider.geo_name = "남의동"
    baseline_before = by_name(run())["높은동"].payload["points"][0]["baseline"]

    results = list(Analyzer(meta=META).compute([*make_inputs(), outsider]))
    after = by_name([r for r in results if isinstance(r, Record)])
    assert "남의동" not in after
    assert after["높은동"].payload["points"][0]["baseline"] == baseline_before


# --- 계산 -----------------------------------------------------------------------


def test_baseline_is_weighted_not_a_simple_mean():
    """선거인수가 모두 1000이면 가중 합과 단순 평균이 같다 — 2017 회차 기준선은
    (810+800+790)/3000 = 0.800 이다."""
    assert by_name(run())["보통동"].payload["points"][0]["baseline"] == pytest.approx(0.800)


def test_gap_is_turnout_minus_baseline():
    p = by_name(run())["높은동"].payload["points"][0]
    assert p["turnout"] == pytest.approx(0.810)
    assert p["gap"] == pytest.approx(0.010)


def test_below_baseline_marks_the_gotv_candidates():
    got = {name: r.payload["below_baseline"] for name, r in by_name(run()).items()}
    assert got == {"높은동": False, "보통동": False, "낮은동": True}


def test_gap_slope_catches_the_widening():
    """격차가 벌어지면 높은동은 양의 기울기, 낮은동은 음의 기울기가 나와야 한다."""
    got = {name: r.payload["gap_slope"] for name, r in by_name(run()).items()}
    assert got["높은동"] > 0
    assert got["낮은동"] < 0
    assert got["보통동"] == pytest.approx(0.0, abs=1e-9)


def test_points_are_ordered_oldest_first():
    ids = [p["election_id"] for p in by_name(run())["높은동"].payload["points"]]
    assert ids == sorted(ids)


# --- 변별력 ---------------------------------------------------------------------


def test_output_discriminates_between_units():
    """모든 단위에서 같은 값이 나오면 그 지표는 아무것도 말하지 않는다
    (docs/30-analysis-spec.md §9)."""
    values = {r.geo_code: r.payload["mean_gap"] for r in run()}
    assert len(set(values.values())) > 1, f"모든 단위가 같은 값이다: {values}"


def test_absolute_turnout_would_not_discriminate_across_elections():
    """왜 절대 투표율이 아니라 편차를 쓰는가 — 회차별 전국 효과가 지배한다.

    이 축소판에서도 회차 평균이 80% → 70% → 60% 로 떨어진다. 절대값으로 시계열을
    비교하면 그 하락이 동별 차이를 덮는다. 편차는 회차와 무관하게 유지된다.
    """
    records = by_name(run())
    baselines = [p["baseline"] for p in records["보통동"].payload["points"]]
    assert baselines == sorted(baselines, reverse=True), "회차마다 기준선이 떨어져야 한다"
    # 보통동은 늘 평균이므로 편차가 0 근처로 유지된다 — 기준선이 떨어져도.
    gaps = [p["gap"] for p in records["보통동"].payload["points"]]
    assert all(abs(g) < 1e-9 for g in gaps)
