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
  - { election: 2016-04-13-national_assembly, candidate: 보수후보, camp: conservative }
  - { election: 2016-04-13-national_assembly, candidate: 진보후보, camp: progressive }
  - { election: 2020-04-15-national_assembly, candidate: 보수후보, camp: conservative }
  - { election: 2020-04-15-national_assembly, candidate: 진보후보, camp: progressive }
  - { election: 2024-04-10-national_assembly, candidate: 보수후보, camp: conservative }
  - { election: 2024-04-10-national_assembly, candidate: 진보후보, camp: progressive }
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

# 총선 계열. 강한보수동의 편차 방향을 대선과 **반대**로 뒤집어, 같은 동이라도
# 계열에 따라 trend 가 갈리는 것(= 계열이 서로 오염되지 않음)을 증명한다.
ASSEMBLY_ELECTIONS = [("2016-04-13", 35.0), ("2020-04-15", 45.0), ("2024-04-10", 48.0)]
ASSEMBLY_OFFSETS = {
    "1171051000": [0.0, -4.0, -8.0],  # 대선에선 보수이동, 총선에선 진보이동
    "1171052000": [0.0, 0.0, 0.0],
    "1171053000": [0.0, 4.0, 8.0],
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


def election_record(
    code: str, name: str, date: str, conservative_pct: float, *, etype: str = "presidential"
) -> Record:
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
            "election_id": f"{date}-{etype}",
            "election_type": etype,
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
        natural_key=f"{date}|{code}|{etype}",
    )


def baseline_election_record(
    geo_level: str,
    geo_code: str | None,
    date: str,
    conservative_pct: float,
    *,
    etype: str = "presidential",
) -> Record:
    """상위 단위(sigungu/sido/nation) 합계 레코드.

    emd 개표 레코드와 payload 구조가 같고 geo_level 만 다르다 — 분석기는 geo_level
    로만 분기한다(nec_archive._to_baseline_record 와 동일한 모양).
    """
    con = round(conservative_pct * 10)
    return Record(
        kind=RecordKind.ELECTION_RESULT,
        collector_id="fake_archive",
        source_name="시험",
        source_license="public_open",
        observed_at=datetime.fromisoformat(f"{date}T00:00:00+09:00"),
        observed_precision="day",
        geo_level=geo_level,
        geo_code=geo_code,
        geo_name=None if geo_code is None else "기준선",
        confidence=1.0,
        payload={
            "election_id": f"{date}-{etype}",
            "election_type": etype,
            "district_name": "기준선",
            "precinct": None,
            "eligible_voters": 1500,
            "total_votes": 1010,
            "invalid_votes": 10,
            "results": [
                {"party": "가", "candidate": "보수후보", "votes": con},
                {"party": "나", "candidate": "진보후보", "votes": 1000 - con},
            ],
        },
        natural_key=f"{date}|baseline|{geo_level}|{geo_code or 'nation'}",
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


def make_multi_type_records() -> list[Record]:
    """대선 + 총선 두 계열을 같은 동들에 얹은 입력."""
    out = make_records()
    for code, name in NAMES.items():
        for i, (date, base) in enumerate(ASSEMBLY_ELECTIONS):
            out.append(
                election_record(
                    code,
                    name,
                    date,
                    base + ASSEMBLY_OFFSETS[code][i],
                    etype="national_assembly",
                )
            )
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


def run_multi(records, *, types=("presidential", "national_assembly"), **config) -> list[Record]:
    results = list(analyzer(election_types=list(types), **config).compute(records))
    assert not [r for r in results if isinstance(r, Rejected)]
    return results


class TestOutputShape:
    def test_one_record_per_emd_and_election_type(self, reference):
        out = run(make_records())
        assert len(out) == 3  # 3 동 × 1 계열(대선)
        assert {(r.geo_code, r.payload["election_type"]) for r in out} == {
            (code, "presidential") for code in NAMES
        }
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

    def test_other_election_types_are_ignored_when_not_configured(self, reference):
        """config.election_types 에 없는 계열은 통째로 버린다 (대선 시계열 불변)."""
        records = make_records()
        intruder = election_record(
            "1171051000", "강한보수동", "2024-04-10", 99.0, etype="national_assembly"
        )
        results = run([*records, intruder])
        assert len(results) == 3  # 총선 레코드가 생기지 않는다
        for record in results:
            assert record.payload["election_type"] == "presidential"
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


class TestElectionTypeSeparation:
    """대선·총선을 한 시계열에 섞지 않고 계열마다 레코드 1건씩 낸다.

    핵심 성질: 한 계열의 파생값(swing/trend/gap/derived_from)에 다른 계열이 새지 않는다.
    """

    def test_one_record_per_emd_and_type(self, reference):
        out = run_multi(make_multi_type_records())
        assert len(out) == 6  # 3 동 × 2 계열
        assert {(r.geo_code, r.payload["election_type"]) for r in out} == {
            (code, etype) for code in NAMES for etype in ("presidential", "national_assembly")
        }

    def test_each_record_series_is_a_single_type(self, reference):
        for record in run_multi(make_multi_type_records()):
            etype = record.payload["election_type"]
            assert {p["election_type"] for p in record.payload["lean_series"]} == {etype}

    def test_presidential_series_is_identical_with_or_without_assembly(self, reference):
        solo = {r.geo_code: r.payload for r in run(make_records())}
        mixed = {
            r.geo_code: r.payload
            for r in run_multi(make_multi_type_records())
            if r.payload["election_type"] == "presidential"
        }
        for code, payload in solo.items():
            assert mixed[code]["swing"] == pytest.approx(payload["swing"])
            assert mixed[code]["trend"] == payload["trend"]
            assert [p["camp_share"] for p in mixed[code]["lean_series"]] == [
                p["camp_share"] for p in payload["lean_series"]
            ]

    def test_trend_diverges_between_types_for_the_same_emd(self, reference):
        out = {
            (r.geo_code, r.payload["election_type"]): r.payload
            for r in run_multi(make_multi_type_records())
        }
        # 강한보수동: 대선 편차는 상승(보수이동), 총선 편차는 하강(진보이동)
        assert out[("1171051000", "presidential")]["trend"] == Trend.CONSERVATIVE_SHIFT
        assert out[("1171051000", "national_assembly")]["trend"] == Trend.PROGRESSIVE_SHIFT

    def test_derived_from_is_scoped_to_its_own_type(self, reference):
        records = make_multi_type_records()
        pres_ids = {
            r.record_id
            for r in records
            if r.kind is RecordKind.ELECTION_RESULT and r.payload["election_type"] == "presidential"
        }
        asm_ids = {
            r.record_id
            for r in records
            if r.kind is RecordKind.ELECTION_RESULT
            and r.payload["election_type"] == "national_assembly"
        }
        for record in run_multi(records):
            used = set(record.derived_from)
            if record.payload["election_type"] == "presidential":
                assert used & pres_ids and not (used & asm_ids)
            else:
                assert used & asm_ids and not (used & pres_ids)

    def test_two_records_for_one_emd_share_population_but_not_identity(self, reference):
        by_type = {
            r.payload["election_type"]: r
            for r in run_multi(make_multi_type_records())
            if r.geo_code == "1171051000"
        }
        pres, asm = by_type["presidential"], by_type["national_assembly"]
        assert pres.geo_code == asm.geo_code
        assert pres.payload["as_of"] == asm.payload["as_of"]
        assert pres.observed_at == asm.observed_at
        assert pres.payload["population_total"] == asm.payload["population_total"]
        assert pres.record_id != asm.record_id
        assert pres.natural_key != asm.natural_key

    def test_confidence_is_judged_within_each_type(self, reference):
        records = make_multi_type_records()
        # 강한보수동의 총선 한 회차를 뺀다 → 그 계열 레코드만 회차 결측(0.5)
        dropped = [
            r
            for r in records
            if not (
                r.kind is RecordKind.ELECTION_RESULT
                and r.geo_code == "1171051000"
                and r.payload["election_id"] == "2016-04-13-national_assembly"
            )
        ]
        conf = {(r.geo_code, r.payload["election_type"]): r.confidence for r in run_multi(dropped)}
        assert conf[("1171051000", "national_assembly")] == 0.5
        assert conf[("1171052000", "national_assembly")] == 0.7  # baseline 없음
        assert conf[("1171051000", "presidential")] == 0.7  # 대선은 온전

    def test_configured_type_with_no_data_is_skipped_not_fatal(self, reference):
        out = run_multi(
            make_multi_type_records(),
            types=("presidential", "national_assembly", "local"),
        )
        assert len(out) == 6  # local 개표가 0건이라 local 레코드는 안 나온다
        assert "local" not in {r.payload["election_type"] for r in out}


class TestSigunguBaselineScoping:
    """다지역구 실행에서는 입력에 서울 25개 자치구의 sigungu 기준선이 다 들어온다
    (load 는 geo 로 안 거른다). 분석기는 자기 자치구(primary_sigungu_code) 것만
    gap_sigungu 에 써야 한다 — 안 그러면 마지막에 처리된 옆 자치구가 이긴다(D-006).

    test_district 의 emd 코드는 1171xxxxx 라 자기 자치구 코드는 1171000000 이다.
    """

    def _records_with_baselines(self) -> list[Record]:
        recs = make_records()
        for _i, (date, base) in enumerate(ELECTIONS):
            # 자기 자치구(송파, 1171000000): 지역구 평균보다 5%p 낮은 보수세
            recs.append(baseline_election_record("sigungu", "1171000000", date, base - 5.0))
            # 옆 자치구(강남, 1168000000): 뒤에 온다 — 안 좁히면 이 값이 gap_sigungu 를 먹는다
            recs.append(baseline_election_record("sigungu", "1168000000", date, base + 30.0))
            recs.append(baseline_election_record("sido", "1100000000", date, base - 2.0))
            recs.append(baseline_election_record("nation", None, date, base))
        return recs

    def test_gap_sigungu_uses_own_sigungu_not_the_last_one_seen(self, reference):
        mid = {r.geo_code: r.payload for r in run(self._records_with_baselines())}["1171052000"]
        # 중간동: own_pct == 지역구 평균 == base
        for i, (_date, _base) in enumerate(ELECTIONS):
            point = mid["lean_series"][i]
            # 자기 자치구 기준선 = base - 5 → gap = +5. 강남(base+30)을 썼다면 -30 근처.
            assert point["gap_sigungu"] == pytest.approx(5.0, abs=0.3)
            assert point["gap_sido"] == pytest.approx(2.0, abs=0.3)
            assert point["gap_nation"] == pytest.approx(0.0, abs=0.3)

    def test_confidence_is_09_when_own_sigungu_baseline_is_complete(self, reference):
        assert all(r.confidence == 0.9 for r in run(self._records_with_baselines()))

    def test_only_decoy_sigungu_present_leaves_gap_none(self, reference):
        recs = make_records()
        for date, base in ELECTIONS:
            recs.append(baseline_election_record("sigungu", "1168000000", date, base + 30.0))
        point = run(recs)[0].payload["lean_series"][0]
        assert point["gap_sigungu"] is None
