"""읍면동 유권자 프로파일 — 진영 성향 시계열 × 인구 구조.

제안서: docs/proposals/A-001-voter-profile.md

load: data/records/ 에서 election_result + population 을 읽는다 (기반 클래스 구현)
compute: 동 하나당 segment_profile 레코드 하나. **순수 함수.**

이 분석기는 **예측이 아니다.** 표본이 8회 × 9동뿐이고 인구는 단일 시점이라
회귀모델은 우연을 학습한다. 여기서 하는 일은 지표화이며, 산출물 이름도
prediction 이 아니라 profile 이다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from typing import Any, NamedTuple

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.contract.enums import (
    GeoLevel,
    ObservedPrecision,
    RecordKind,
    SourceLicense,
)
from votelink.contract.models import Record
from votelink.reference.districts import resolve_district
from votelink.reference.party_lineage import CampNotFound, camp_of

from .calc import CampTally, age_mix_of, classify_trend, swing_of

PROFILE_TYPE = "voter_profile"
SOURCE_NAME = "votelink 분석 (선관위 개표자료 + 행안부 주민등록 인구)"

# 기준선 레코드의 geo_level -> LeanPoint 의 필드명.
# 아직 이 레코드들이 없으므로(A-001 §5) 해당 gap 은 None 으로 남는다.
BASELINE_FIELDS = {
    GeoLevel.SIGUNGU: "gap_sigungu",
    GeoLevel.SIDO: "gap_sido",
    GeoLevel.NATION: "gap_nation",
}


class _Row(NamedTuple):
    """한 선거·한 동의 개표 집계."""

    record: Record
    tally: CampTally
    date: str


class Analyzer(BaseAnalyzer):
    id = "voter_profile"

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        district = resolve_district(self.config["district"])
        codes = set(district.emd_codes)
        if not codes:
            raise AnalyzeError(
                f"선거구 '{district.id}' 에 확인된 행정동코드가 없다. "
                "districts.yaml 의 emd[].code 를 먼저 채워야 한다"
            )

        # 순서 보존 중복 제거 — items 곱집합의 결정성을 위해.
        wanted_types = list(dict.fromkeys(self.config["election_types"]))
        wanted_set = set(wanted_types)

        # election_type -> election_id -> geo_code -> _Row
        by_election: dict[str, dict[str, dict[str, _Row]]] = defaultdict(lambda: defaultdict(dict))
        # election_type -> election_id -> geo_level -> 보수 득표 %
        baselines: dict[str, dict[str, dict[GeoLevel, tuple[str, float]]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # geo_code -> 가장 최근 인구 레코드
        populations: dict[str, Record] = {}

        for record in records:
            if record.kind is RecordKind.POPULATION:
                self._collect_population(record, codes, populations)
            elif record.kind is RecordKind.ELECTION_RESULT:
                self._collect_election(record, codes, wanted_set, by_election, baselines)

        if not by_election:
            raise AnalyzeError(
                f"선거구 '{district.name}' 에 해당하는 개표 레코드가 없다 "
                f"(선거 유형 {sorted(wanted_set)}). "
                "nec_archive 를 먼저 돌렸는지, districts.yaml 의 코드가 맞는지 확인하라"
            )

        # 선거 계열마다 따로 시간순으로 세운다. 대선과 총선을 한 축에 올리면 편차의
        # 의미가 달라지므로(A-001) 계열을 섞지 않는다 — 계열당 레코드 1건.
        ordered_by_type: dict[str, list[str]] = {}
        # 지역구 가중평균 = Σ(동별 보수 득표) / Σ(동별 유효투표). 계열 안에서만 합산한다.
        # 동별 단순평균이 아니다 — 인구가 다른 동을 같은 무게로 세면 왜곡된다.
        district_pct: dict[str, dict[str, float]] = {}
        for etype, elections in by_election.items():
            dates = {eid: next(iter(rows.values())).date for eid, rows in elections.items()}
            ordered_by_type[etype] = sorted(elections, key=lambda eid: dates[eid])
            pct: dict[str, float] = {}
            for eid, rows in elections.items():
                total = CampTally()
                for row in rows.values():
                    total.merge(row.tally)
                pct[eid] = total.conservative_pct
            district_pct[etype] = pct

        context = _Context(
            district=district,
            ordered_by_type=ordered_by_type,
            by_election=by_election,
            baselines=baselines,
            populations=populations,
            district_pct=district_pct,
            threshold=float(self.config["trend_threshold"]),
            window=int(self.config["trend_window"]),
        )

        # (동 × 계열) 곱집합. config 에 있으나 개표가 0건인 계열은 조용히 건너뛴다
        # (레코드 미생성, 예외 아님) — 전체가 0건이면 위에서 이미 실패했다.
        items = [
            (code, etype)
            for etype in wanted_types
            if etype in by_election
            for code in sorted(codes)
        ]
        yield from self.map_items(items, lambda pair: self._profile(pair[0], pair[1], context))

    # --- 입력 분류 -------------------------------------------------------------

    @staticmethod
    def _collect_population(record: Record, codes: set[str], out: dict[str, Record]) -> None:
        if record.geo_level is not GeoLevel.EMD or record.geo_code not in codes:
            return
        previous = out.get(record.geo_code)
        # 여러 기준월이 쌓이면 가장 최근 것만 쓴다. age_mix 는 현재 스냅샷이다.
        if previous is None or record.observed_at > previous.observed_at:
            out[record.geo_code] = record

    def _collect_election(
        self,
        record: Record,
        codes: set[str],
        wanted_types: set[str],
        by_election: dict[str, dict[str, dict[str, _Row]]],
        baselines: dict[str, dict[str, dict[GeoLevel, tuple[str, float]]]],
    ) -> None:
        payload = record.payload
        etype = payload["election_type"]
        if etype not in wanted_types:
            return
        # 투표구 행은 동 합계와 이중계산된다. 동 단위(precinct=null)만 받는다.
        if payload.get("precinct"):
            return

        is_emd = record.geo_level is GeoLevel.EMD and record.geo_code in codes
        is_baseline = record.geo_level in BASELINE_FIELDS
        if not (is_emd or is_baseline):
            return

        tally = self._tally(record)
        election_id = payload["election_id"]
        if is_emd:
            by_election[etype][election_id][record.geo_code] = _Row(
                record=record,
                tally=tally,
                date=record.observed_at.date().isoformat(),
            )
        else:
            baselines[etype][election_id][record.geo_level] = (
                record.record_id,
                tally.conservative_pct,
            )

    @staticmethod
    def _tally(record: Record) -> CampTally:
        """후보별 득표를 진영별로 합친다.

        매핑에 없는 후보가 하나라도 있으면 **전체를 실패시킨다.** 그 후보의 득표가
        조용히 빠지면 나머지 진영 비율이 전부 틀리는데 숫자는 그럴듯하게 나온다.
        조치도 명확하다 — party_lineage.yaml 에 한 줄 추가하면 된다.
        """
        payload = record.payload
        tally = CampTally()
        for entry in payload["results"]:
            try:
                camp = camp_of(
                    payload["election_id"], entry["candidate"], payload.get("district_name")
                )
            except CampNotFound as exc:
                raise AnalyzeError(str(exc)) from exc
            tally.add(camp, entry["votes"])
        return tally

    # --- 동 하나의 프로파일 ------------------------------------------------------

    def _profile(self, code: str, etype: str, ctx: _Context) -> Record:
        elections = ctx.by_election[etype]
        rows = [
            (eid, elections[eid][code])
            for eid in ctx.ordered_by_type[etype]
            if code in elections[eid]
        ]
        if not rows:
            raise ValueError(f"개표 기록이 없는 행정동이다: {code} ({etype})")

        population = ctx.populations.get(code)
        if population is None:
            raise ValueError(
                f"인구 레코드가 없는 행정동이다: {code}. "
                "mois_population 을 먼저 돌려야 프로파일을 만들 수 있다"
            )

        lean_series: list[dict[str, Any]] = []
        gaps: list[float] = []
        conservative: list[float] = []
        sources: list[str] = []
        type_pct = ctx.district_pct[etype]
        type_baselines = ctx.baselines.get(etype, {})

        for election_id, row in rows:
            payload = row.record.payload
            own_pct = row.tally.conservative_pct
            gap_district = own_pct - type_pct[election_id]

            point: dict[str, Any] = {
                "election_id": election_id,
                "election_date": row.date,
                "election_type": payload["election_type"],
                "camp_share": {str(k): v for k, v in row.tally.share().items()},
                "turnout": payload["total_votes"] * 100.0 / payload["eligible_voters"],
                "gap_district": gap_district,
                # 기준선이 없어도 키는 만든다. '차이가 없다'와 '모른다'는 다르지만,
                # '키가 없다'는 읽는 쪽에서 둘 다 아닌 세 번째 상태가 된다.
                **dict.fromkeys(BASELINE_FIELDS.values()),
            }
            for level, field in BASELINE_FIELDS.items():
                found = type_baselines.get(election_id, {}).get(level)
                if found is not None:
                    base_id, base_pct = found
                    point[field] = own_pct - base_pct
                    sources.append(base_id)

            lean_series.append(point)
            gaps.append(gap_district)
            conservative.append(own_pct)
            sources.append(row.record.record_id)

        age_mix, sex_ratio, total = age_mix_of(population.payload["breakdown"])
        sources.append(population.record_id)

        payload = {
            "profile_type": PROFILE_TYPE,
            "as_of": population.payload["reference_month"],
            "election_type": etype,
            "lean_series": lean_series,
            "swing": swing_of(conservative),
            "trend": str(classify_trend(gaps, threshold=ctx.threshold, window=ctx.window)),
            "age_mix": {str(band): pct for band, pct in age_mix.items()},
            "sex_ratio": sex_ratio,
            "population_total": total,
            "population_month": population.payload["reference_month"],
        }

        return Record(
            kind=RecordKind.SEGMENT_PROFILE,
            collector_id=self.id,
            source_name=SOURCE_NAME,
            source_url=None,
            # 원천(선관위·행안부)이 둘 다 공공저작물이므로 파생도 같은 조건이다.
            source_license=SourceLicense.PUBLIC_OPEN,
            # 분석 실행 시각이 아니라 **입력이 가리키는 시점**이다.
            # 실행할 때마다 값이 바뀌면 시계열이 망가진다.
            observed_at=population.observed_at,
            observed_precision=ObservedPrecision.MONTH,
            geo_level=GeoLevel.EMD,
            geo_code=code,
            geo_name=ctx.district.name_of(code) or rows[0][1].record.geo_name,
            confidence=self._confidence(len(rows), etype, ctx),
            # dict.fromkeys 로 순서를 지키며 유일화한다 (계약이 중복을 거부한다).
            derived_from=list(dict.fromkeys(sources)),
            payload=payload,
            natural_key=(f"{PROFILE_TYPE}|{etype}|{code}|{population.payload['reference_month']}"),
        )

    @staticmethod
    def _confidence(my_elections: int, etype: str, ctx: _Context) -> float:
        """A-001 §계산 규칙. 1.0 은 주지 않는다 — 실측이 아니라 파생이고,
        인구가 단일 시점이라 시계열 해석에 한계가 있다. 계열 안에서만 판정한다."""
        ordered = ctx.ordered_by_type[etype]
        if my_elections < len(ordered):
            return 0.5  # 개표 회차 결측 (동 통폐합 등)
        type_baselines = ctx.baselines.get(etype, {})
        complete = all(len(type_baselines.get(eid, {})) == len(BASELINE_FIELDS) for eid in ordered)
        return 0.9 if complete else 0.7


class _Context(NamedTuple):
    """_profile 이 쓰는 계산 문맥. 인자 8개를 늘어놓지 않기 위한 묶음이다.

    개표·기준선·순서·가중평균은 전부 election_type 으로 한 겹 갈라져 있다 —
    한 계열의 프로파일을 만들 때 다른 계열의 값이 새지 않는다.
    """

    district: Any
    ordered_by_type: dict[str, list[str]]
    by_election: dict[str, dict[str, dict[str, _Row]]]
    baselines: dict[str, dict[str, dict[GeoLevel, tuple[str, float]]]]
    populations: dict[str, Record]
    district_pct: dict[str, dict[str, float]]
    threshold: float
    window: int
