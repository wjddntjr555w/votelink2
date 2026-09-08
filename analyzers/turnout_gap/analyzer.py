"""투표율 편차 분석기.

load:    디스크에서 election_result 를 읽는다 (기본 구현)
compute: 동 × 선거 계열마다 "선거구 평균 대비 투표율 편차" 시계열을 만든다. 순수 함수.

제안서: docs/proposals/A-004-turnout-gap.md
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime

from analyzers.turnout_gap.calc import Tally, baseline_turnout, election_date, slope
from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.contract.enums import RecordKind
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

PROFILE_TYPE = "turnout_gap"


class Unit:
    """산출 레코드 1건에 대응하는 묶음 — 동 1개 × 선거 계열 1개."""

    def __init__(self, election_type: str, geo_code: str, geo_name: str):
        self.election_type = election_type
        self.geo_code = geo_code
        self.geo_name = geo_name
        self.points: list[dict] = []  # 오래된 회차 순
        self.derived_from: list[str] = []


class Analyzer(BaseAnalyzer):
    id = "turnout_gap"

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        if not records:
            raise AnalyzeError("입력 레코드가 0건이다. 먼저 수집기를 돌려라")

        district = resolve_district(self.config["district"])
        codes = {e.code for e in district.emd if e.code}
        if not codes:
            raise AnalyzeError(
                f"{district.name}: districts.yaml 에 행정동코드가 없다. "
                "`uv run votelink district list --emd` 로 확인하고 D-001 백필을 먼저 돌려라"
            )

        results = [
            r
            for r in records
            if r.kind is RecordKind.ELECTION_RESULT and r.geo_level == "emd" and r.geo_code in codes
        ]
        if not results:
            raise AnalyzeError(
                f"{district.name}: 관할 행정동의 election_result 가 없다 "
                f"(행정동 {len(codes)}개). 수집기를 먼저 돌려라"
            )

        yield from self.map_items(self._group(results), self._to_record)

    # --- 그룹핑 ---------------------------------------------------------------

    def _group(self, results: list[Record]) -> list[Unit]:
        """회차마다 기준선을 잡고, 동 × 계열로 시계열을 접는다.

        기준선이 그 회차의 **모든 동**을 쓰므로, 한 동의 산출은 나머지 동의 레코드에도
        의존한다 — `derived_from` 에 그 회차 전체를 넣는 이유다.
        """
        by_election: dict[tuple[str, str], list[Record]] = defaultdict(list)
        for r in results:
            by_election[(r.payload["election_type"], r.payload["election_id"])].append(r)

        units: dict[tuple[str, str], Unit] = {}
        for (etype, eid), rows in sorted(by_election.items(), key=lambda kv: kv[0][1]):
            tallies = [
                Tally(
                    election_id=eid,
                    geo_code=r.geo_code,
                    geo_name=r.geo_name or r.geo_code,
                    eligible_voters=r.payload["eligible_voters"],
                    total_votes=r.payload["total_votes"],
                )
                for r in rows
            ]
            base = baseline_turnout(tallies)
            evidence = [r.record_id for r in rows]

            for t in tallies:
                key = (etype, t.geo_code)
                unit = units.setdefault(key, Unit(etype, t.geo_code, t.geo_name))
                unit.points.append(
                    {
                        "election_id": eid,
                        "turnout": t.turnout,
                        "baseline": base,
                        "gap": t.turnout - base,
                        "eligible_voters": t.eligible_voters,
                        "total_votes": t.total_votes,
                    }
                )
                unit.derived_from.extend(evidence)

        return list(units.values())

    # --- 레코드 ---------------------------------------------------------------

    def _to_record(self, unit: Unit) -> Record:
        gaps = [p["gap"] for p in unit.points]
        as_of = election_date(unit.points[-1]["election_id"])
        used = len(unit.points)
        min_for_slope = int(self.cfg("min_elections_for_slope", 3))

        return Record(
            kind="turnout_gap",
            collector_id=self.id,
            source_name="votelink 분석 (선관위 개표 아카이브)",
            source_url=None,
            source_license="public_open",
            # 입력이 가리키는 시점 = 최근 회차의 선거일. 분석 실행 시각이 아니다.
            observed_at=datetime.fromisoformat(as_of).replace(tzinfo=KST),
            observed_precision="day",
            geo_level="emd",
            geo_code=unit.geo_code,
            geo_name=unit.geo_name,
            # 실측이 아니라 파생이라 1.0 을 주지 않는다. 회차가 적으면 기울기를
            # 신뢰할 수 없으므로 더 내린다 (meta.yaml 주석 참조).
            confidence=0.9 if used >= min_for_slope else 0.7,
            derived_from=sorted(set(unit.derived_from)),
            natural_key=f"{PROFILE_TYPE}|{unit.election_type}|{unit.geo_code}|{as_of}",
            payload={
                "election_type": unit.election_type,
                "emd_name": unit.geo_name,
                "points": unit.points,
                "latest_gap": gaps[-1],
                "mean_gap": sum(gaps) / len(gaps),
                # 회차가 모자라면 기울기를 말하지 않는다 — 2점으로 그은 직선은
                # 추세가 아니라 두 값의 차이일 뿐이다.
                "gap_slope": slope(gaps) if used >= min_for_slope else 0.0,
                "below_baseline": sum(gaps) / len(gaps) < 0,
                "elections_used": used,
                "as_of": as_of,
            },
        )
