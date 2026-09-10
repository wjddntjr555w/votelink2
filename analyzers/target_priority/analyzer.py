"""타깃 동 우선순위 분석기.

load:    디스크에서 segment_profile + turnout_gap 을 읽는다 (기본 구현)
compute: 행정동 × 선거계열 -> target_priority 파생 레코드 (순수 함수)

**진영 중립**이다. "우리 동원 대상이냐 설득 대상이냐"는 캠프 렌즈가 L3 에서 정한다
(P-001). 여기서는 어느 편이 봐도 같은 요인(규모·변동성·경합·투표율 여유)과 그 블렌드만
낸다. 제안서: docs/proposals/A-005-target-priority.md
"""

from collections import defaultdict
from collections.abc import Iterator

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record
from votelink.reference import resolve_district

from .calc import Row, classify, fill_indices

PROFILE_TYPE = "target_priority"


class Analyzer(BaseAnalyzer):
    id = "target_priority"

    # load() 는 기본 구현으로 충분하다 — meta.inputs(segment_profile, turnout_gap)를
    # 전부 읽고 자기 출력은 뺀다. 참조 데이터는 compute 안에서 resolve_district 로 읽는다.

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        if not records:
            raise AnalyzeError("입력 레코드가 0건이다. 먼저 voter_profile·turnout_gap 을 돌려라")

        district = resolve_district(self.config["district"])
        emd_codes = {e.code for e in district.emd if e.code}

        profiles = [
            r for r in records if r.kind is RecordKind.SEGMENT_PROFILE and r.geo_code in emd_codes
        ]
        if not profiles:
            # 참조 데이터·필수 입력 결손은 전체 중단이다. 빈 산출물을 조용히 내지 않는다.
            raise AnalyzeError(
                f"'{self.config['district']}' 관할의 segment_profile 이 없다. "
                "voter_profile 을 이 선거구로 먼저 돌려라"
            )

        turnout = {
            (r.geo_code, r.payload["election_type"]): r
            for r in records
            if r.kind is RecordKind.TURNOUT_GAP and r.geo_code in emd_codes
        }

        weights = self.config["weights"]
        cuts = self.config["segment_cuts"]

        # segment_profile 은 (동, 계열)당 1건. 계열별로 그룹을 만들어 그 안에서 정규화한다.
        groups: dict[str, list[Row]] = defaultdict(list)
        for p in profiles:
            groups[p.payload["election_type"]].append(self._row(p, turnout))

        units: list[Row] = []
        for rows in groups.values():
            fill_indices(rows, weights)
            for r in rows:
                r.segment_note = classify(r, cuts)
            units.extend(rows)

        # map_items 로 감싸야 9개 중 1개가 깨져도 나머지가 살아남는다.
        yield from self.map_items(units, self._to_record)

    def _row(self, profile: Record, turnout: dict) -> Row:
        """한 segment_profile 을 원시 요인으로. 순수 함수. 여기서 던지면 map_items 가 격리한다."""
        pay = profile.payload
        etype = pay["election_type"]
        latest = pay["lean_series"][-1]["camp_share"]
        con = float(latest["conservative"])
        pro = float(latest["progressive"])

        tg = turnout.get((profile.geo_code, etype))
        deficit = max(0.0, -float(tg.payload["mean_gap"])) if tg else None

        return Row(
            geo_code=profile.geo_code,
            geo_name=profile.geo_name or profile.geo_code,
            election_type=etype,
            as_of=pay["as_of"],
            observed_at=profile.observed_at,
            population_total=int(pay["population_total"]),
            swing=float(pay["swing"]),
            margin=abs(con - pro),
            conservative_share=con,
            progressive_share=pro,
            deficit=deficit,
            evidence=[profile.record_id] + ([tg.record_id] if tg else []),
            has_turnout=tg is not None,
        )

    def _to_record(self, r: Row) -> Record:
        return Record(
            kind="target_priority",
            collector_id=self.id,  # 분석기 id. 입력을 만든 수집기가 아니다
            source_name="votelink 분석 (voter_profile + turnout_gap)",
            source_url=None,
            source_license="public_open",
            # segment_profile 의 observed_at 을 그대로 물려준다 — 분석 실행 시각이 아니다.
            # (turnout_gap 은 선거일 기준이라 더 과거일 수 있어 쓰지 않는다.)
            observed_at=r.observed_at,
            observed_precision="month",
            geo_level="emd",
            geo_code=r.geo_code,
            geo_name=r.geo_name,
            # 파생이라 1.0 을 주지 않는다. 두 입력이 다 있으면 0.65, turnout_gap 이
            # 없으면 동원 요인을 못 봤으므로 0.4 로 더 내린다. (meta.yaml 주석 참조)
            confidence=0.65 if r.has_turnout else 0.4,
            derived_from=list(dict.fromkeys(r.evidence)),  # 중복 제거, 순서 보존
            natural_key=f"{PROFILE_TYPE}|{r.election_type}|{r.geo_code}|{r.as_of}",
            payload={
                "as_of": r.as_of,
                "election_type": r.election_type,
                "size_index": round(r.size_index, 2),
                "volatility_index": round(r.volatility_index, 2),
                "competitiveness_index": round(r.competitiveness_index, 2),
                "turnout_headroom": round(r.turnout_headroom, 2),
                "attention_score": round(r.attention_score, 2),
                "rank": r.rank,
                "group_size": r.group_size,
                "segment_note": r.segment_note,
                "conservative_share": round(r.conservative_share, 2),
                "progressive_share": round(r.progressive_share, 2),
                "population_total": r.population_total,
                "has_turnout_input": r.has_turnout,
            },
        )
