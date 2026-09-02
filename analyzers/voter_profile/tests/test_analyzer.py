"""compute() 는 순수 함수이므로 파일 없이 레코드를 직접 넣어 검증한다.

여기서 쓰는 입력은 **실제 데이터의 축소판**이다 (합성 숫자지만 구조는 동일).
동 3개 × 선거 3회로 줄여도 검증하려는 성질은 그대로다:
전국 공통 흐름이 있어도 편차로 동별 차이를 잡아내는가.
"""

from datetime import datetime

import pytest

from votelink.analyze.base import AnalyzeError
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.enums import Camp, RecordKind, Trend
from votelink.contract.models import KST, Record, Rejected
from votelink.reference import districts, party_lineage

from ..analyzer import Analyzer

# 동 3개짜리 시험용 선거구. 코드는 형식만 유효하며 실제 지역이 아니다.
DISTRICT_YAML = """
version: test
districts:
  - id: test_district
    name: 시험 선거구
    sido: 서울특별시
    sigungu: 시험구
    emd:
      - { name: 강한보수동, code: "1171051000" }
      - { name: 중간동,     code: "1171052000" }
      - { name: 약한보수동, code: "1171053000" }
"""

LINEAGE_YAML = """
version: test
candidates:
  - { election: 2017-05-09-presidential, candidate: 보수후보, camp: conservative }
  - { election: 2017-05-09-presidential, candidate: 진보후보, camp: progressive }
  - { election: 2022-03-09-presidential, candidate: 보수후보, camp: conservative }
  - { election: 2022-03-09-presidential, candidate: 진보후보, camp: progressive }
  - { election: 2025-06-03-presidential, candidate: 보수후보, camp: conservative }
  - { election: 2025-06-03-presidential, candidate: 진보후보, camp: progressive }
"""

ELECTIONS = [("2017-05-09", 30.0), ("2022-03-09", 50.0), ("2025-06-03", 55.0)]
"""(선거일, 전국 기준 보수 %). 셋 다 오르는 **공통 흐름**을 일부러 넣었다 —
절대 기울기로 판정하면 세 동이 전부 보수이동으로 나오는 상황이다."""

# 동별 오프셋: 공통 흐름 위에 얹히는 그 동네만의 이동
OFFSETS = {
    "1171051000": [0.0, 4.0, 8.0],  # 지역구 평균보다 점점 더 보수로
    "1171052000": [0.0, 0.0, 0.0],  # 평균과 함께 움직인다
    "1171053000": [0.0, -4.0, -8.0],  # 점점 덜 보수로
}


@pytest.fixture
def reference(tmp_path, monkeypatch):
    d = tmp_path / "districts.yaml"
    d.write_text(DISTRICT_YAML, encoding="utf-8")
    lineage = tmp_path / "party_lineage.yaml"
    lineage.write_text(LINEAGE_YAML, encoding="utf-8")

    monkeypatch.setattr(districts, "DISTRICTS_PATH", d)
    monkeypatch.setattr(party_lineage, "LINEAGE_PATH", lineage)
    districts.reset_cache()
    party_lineage.reset_cache()
    yield
    districts.reset_cache()
    party_lineage.reset_cache()


def election_record(code: str, name: str, date: str, conservative_pct: float) -> Record:
    """유효투표 1000표짜리 개표 레코드. 무효표까지 넣어 산술 불변식을 실제로 태운다."""
    con = round(conservative_pct * 10)
    return Record(
        kind=RecordKind.ELECTION_RESULT,
        collector_id="fake_archive",
        source_name="시험",
        source_license="public_open",
        observed_at=datetime.fromisoformat(f"{date}T00:00:00+09:00"),
        observed_precision="day",
        geo_level="emd",
        geo_code=code,
        geo_name=name,
        confidence=1.0,
        payload={
            "election_id": f"{date}-presidential",
            "election_type": "presidential",
            "district_name": "시험 선거구",
            "precinct": None,
            "eligible_voters": 1500,
            "total_votes": 1010,
            "invalid_votes": 10,
            "results": [
                {"party": "가", "candidate": "보수후보", "votes": con},
                {"party": "나", "candidate": "진보후보", "votes": 1000 - con},
            ],
        },
        natural_key=f"{date}|{code}",
    )


def population_record(code: str, name: str) -> Record:
    return Record(
        kind=RecordKind.POPULATION,
        collector_id="fake_population",
        source_name="시험",
        source_license="public_open",
        observed_at=datetime(2024, 12, 1, tzinfo=KST),
        observed_precision="month",
        geo_level="emd",
        geo_code=code,
        geo_name=name,
        confidence=1.0,
        payload={
            "reference_month": "2024-12",
            "total": 400,
            "breakdown": [
                {"age_band": "20-29", "sex": "M", "count": 100},
                {"age_band": "20-29", "sex": "F", "count": 100},
                {"age_band": "60-69", "sex": "M", "count": 100},
                {"age_band": "60-69", "sex": "F", "count": 100},
            ],
        },
        natural_key=f"2024-12|{code}",
    )


NAMES = {"1171051000": "강한보수동", "1171052000": "중간동", "1171053000": "약한보수동"}


def make_records(*, with_population: bool = True) -> list[Record]:
    out: list[Record] = []
    for code, name in NAMES.items():
        for i, (date, base) in enumerate(ELECTIONS):
            out.append(election_record(code, name, date, base + OFFSETS[code][i]))
        if with_population:
            out.append(population_record(code, name))
    return out


def analyzer(**config) -> Analyzer:
    meta = AnalyzerMeta(
        id="voter_profile",
        name="시험",
        inputs=[RecordKind.ELECTION_RESULT, RecordKind.POPULATION],
        outputs=[RecordKind.SEGMENT_PROFILE],
        geo_level="emd",
        config={
            "district": "test_district",
            "election_types": ["presidential"],
            "trend_threshold": 0.3,
            "trend_window": 3,
            **config,
        },
    )
    return Analyzer(meta=meta)


def run(records) -> list[Record]:
    results = list(analyzer().compute(records))
    assert not [r for r in results if isinstance(r, Rejected)]
    return results


class TestOutputShape:
    def test_one_record_per_emd(self, reference):
        out = run(make_records())
        assert len(out) == 3
        assert {r.geo_code for r in out} == set(NAMES)
        assert {r.kind for r in out} == {RecordKind.SEGMENT_PROFILE}

    def test_derived_from_names_every_input_used(self, reference):
        """근거를 못 대는 결론은 이 프로젝트에서 실패로 간주한다."""
        out = run(make_records())
        for record in out:
            # 개표 3회 + 인구 1건
            assert len(record.derived_from) == 4
            assert len(set(record.derived_from)) == 4

    def test_observed_at_is_the_input_time_not_now(self, reference):
        """실행할 때마다 값이 바뀌면 시계열이 망가진다."""
        out = run(make_records())
        assert all(r.observed_at.date().isoformat() == "2024-12-01" for r in out)
        assert all(r.payload["as_of"] == "2024-12" for r in out)

    def test_record_id_is_stable_across_runs(self, reference):
        first = {r.record_id for r in run(make_records())}
        second = {r.record_id for r in run(make_records())}
        assert first == second


class TestTrendUsesDeviationNotAbsolute:
    """이 분석기에서 가장 중요한 성질.

    세 동 모두 절대 보수율이 오르지만(30→50→55의 공통 흐름), 지역구 평균 대비로는
    한 동만 오르고 한 동은 내린다. 절대 기울기로 판정하면 셋 다 보수이동이 되어
    변별력이 0이 된다 — 실제 데이터에서 9개 동이 전부 그렇게 나왔다.
    """

    def test_three_towns_get_three_different_trends(self, reference):
        out = {r.geo_code: r.payload for r in run(make_records())}
        assert out["1171051000"]["trend"] == Trend.CONSERVATIVE_SHIFT
        assert out["1171052000"]["trend"] == Trend.STABLE
        assert out["1171053000"]["trend"] == Trend.PROGRESSIVE_SHIFT

    def test_absolute_conservative_share_rises_in_all_three(self, reference):
        """대조군: 절대값만 보면 셋이 구분되지 않는다는 것을 명시적으로 남긴다."""
        out = {r.geo_code: r.payload for r in run(make_records())}
        for payload in out.values():
            series = [p["camp_share"][Camp.CONSERVATIVE] for p in payload["lean_series"]]
            assert series[0] < series[-1]

    def test_gap_district_is_centered_on_the_weighted_average(self, reference):
        """편차의 가중합은 0이다 (오프셋이 대칭이고 동 규모가 같으므로)."""
        out = run(make_records())
        for i in range(len(ELECTIONS)):
            gaps = [r.payload["lean_series"][i]["gap_district"] for r in out]
            assert sum(gaps) == pytest.approx(0.0, abs=1e-9)


class TestSeriesContents:
    def test_series_is_ordered_oldest_first(self, reference):
        payload = run(make_records())[0].payload
        dates = [p["election_date"] for p in payload["lean_series"]]
        assert dates == sorted(dates)

    def test_turnout_uses_eligible_voters(self, reference):
        payload = run(make_records())[0].payload
        # 1010 / 1500
        assert payload["lean_series"][0]["turnout"] == pytest.approx(67.333, abs=0.01)

    def test_baseline_gaps_are_none_until_baseline_records_exist(self, reference):
        """'차이가 없다'와 '모른다'는 다르다. 0.0 으로 채우지 않는다."""
        point = run(make_records())[0].payload["lean_series"][0]
        assert point["gap_sigungu"] is None
        assert point["gap_sido"] is None
        assert point["gap_nation"] is None
        assert point["gap_district"] is not None

    def test_swing_is_absolute_amplitude(self, reference):
        out = {r.geo_code: r.payload for r in run(make_records())}
        # 강한보수동: 30 → 54 → 63
        assert out["1171051000"]["swing"] == pytest.approx(33.0, abs=0.01)

    def test_confidence_is_0_7_without_baselines(self, reference):
        """1.0 을 주지 않는다 — 실측이 아니라 파생이다."""
        assert all(r.confidence == 0.7 for r in run(make_records()))


class TestFailureModes:
    def test_unmapped_candidate_fails_the_whole_run(self, reference):
        """조용히 other 로 떨어뜨리면 나머지 진영 비율이 전부 틀리는데 숫자는 그럴듯하다."""
        records = make_records()
        records[0].payload["results"][0]["candidate"] = "매핑에없는후보"
        with pytest.raises(AnalyzeError, match="진영 매핑에 없는 후보"):
            list(analyzer().compute(records))

    def test_missing_population_quarantines_only_that_emd(self, reference):
        """3개 중 1개가 깨져도 나머지 2개는 나온다."""
        records = [
            r
            for r in make_records()
            if not (r.kind is RecordKind.POPULATION and r.geo_code == "1171053000")
        ]
        results = list(analyzer().compute(records))
        good = [r for r in results if isinstance(r, Record)]
        bad = [r for r in results if isinstance(r, Rejected)]
        assert len(good) == 2
        assert len(bad) == 1
        assert "인구 레코드가 없는" in bad[0].reason

    def test_no_matching_elections_fails_loudly(self, reference):
        """입력이 있는데 0건을 내면 '분석이 안 됐다'와 구분되지 않는다."""
        records = [r for r in make_records() if r.kind is RecordKind.POPULATION]
        with pytest.raises(AnalyzeError, match="개표 레코드가 없다"):
            list(analyzer().compute(records))

    def test_other_election_types_are_ignored(self, reference):
        """총선이 섞여 들어와도 대선 시계열을 오염시키지 않는다."""
        records = make_records()
        intruder = election_record("1171051000", "강한보수동", "2024-04-10", 99.0)
        intruder.payload["election_type"] = "national_assembly"
        intruder.payload["election_id"] = "2024-04-10-national_assembly"
        results = run([*records, intruder])
        for record in results:
            assert len(record.payload["lean_series"]) == 3

    def test_precinct_rows_are_skipped(self, reference):
        """투표구 행이 동 합계와 이중계산되면 득표가 배로 뛴다."""
        records = make_records()
        precinct = election_record("1171051000", "강한보수동", "2025-06-03", 90.0)
        precinct.payload["precinct"] = "제1투표소"
        precinct.natural_key = "precinct-row"
        out = {r.geo_code: r.payload for r in run([*records, precinct])}
        assert out["1171051000"]["lean_series"][-1]["camp_share"][Camp.CONSERVATIVE] == (
            pytest.approx(63.0)
        )
