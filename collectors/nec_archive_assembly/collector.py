"""선관위 개표자료 아카이브 수집기 — 국회의원선거 지역구 (2008~2024).

fetch: Excel 을 셀 격자로 **디코딩만** 해서 담는다 (해석 금지)
parse: 격자 -> election_result 레코드 (네트워크 금지, 순수 함수)

대선(nec_archive)과 코드를 공유하지 않는다 (프로젝트 규칙). 후보 열 폭이 지역구
마다 달라 파싱 방식 자체가 다르다 — 자세한 것은 rows.py 와
docs/proposals/C-005-nec-archive-assembly.md 참조.

**16·17대(2000·2004)는 이번 범위가 아니다.** 후보명이 별도 열 없이 투표구
텍스트에 섞여 있어(`풍납제1동제1투`) 이 수집기와 다른 추출 방식이 필요하다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from votelink.collect import BaseCollector, FetchError, ParseResult, RawBatch
from votelink.contract.models import Record
from votelink.reference.districts import resolve_district

from .excel import read_grid
from .rows import DEFAULT_TOTAL_MARKERS, Layout, check_arithmetic, iter_district_rows


class Collector(BaseCollector):
    id = "nec_archive_assembly"

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """아카이브의 Excel 을 격자로 풀어 담는다. 네트워크를 타지 않는다.

        어느 파일·시트를 읽을지는 `meta.yaml` 의 `selector` 가 정한다 — '어디를
        읽을지' 는 설정이고, '그 안에서 무엇을 골라낼지'(지역구 필터링)는 parse
        의 일이다. `selector.sheet` 가 있으면 그 파일이 이미 지역구 하나로
        좁혀진 것이고(18~21대), 없으면 grid 전체가 전국이라 parse 가 골라낸다
        (22대, `layout.district_col`).
        """
        base = Path(self.meta.config["archive_dir"])
        if not base.is_dir():
            raise FetchError(
                f"아카이브 폴더가 없다: {base}. "
                "선관위 개표자료를 data/raw/nec_archive_assembly/ 옆에 두어야 한다"
            )
        for election in self.meta.config["elections"]:
            selector = election["selector"]
            path = base / selector["file"]
            if not path.is_file():
                raise FetchError(f"{election['id']}: 파일이 없다 — {path}")
            yield RawBatch(
                collector_id=self.id,
                body={
                    "election_id": election["id"],
                    "grid": read_grid(path, sheet=selector.get("sheet", 0)),
                },
                batch_key=election["id"],
                source_url=path.as_posix(),
            )

    # --- parse ----------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        election = self._election(raw.body["election_id"])
        layout = Layout(**election["layout"])
        rows = iter_district_rows(
            raw.body["grid"],
            layout,
            district_name=election["district_match"],
            emd_names=self._emd_names,
            total_markers=tuple(election.get("total_markers", DEFAULT_TOTAL_MARKERS)),
        )
        yield from self.map_items(rows, lambda row: self._to_record(row, election))

    def _to_record(self, row: Any, election: dict[str, Any]) -> Record:
        check_arithmetic(row)
        district = resolve_district(self.meta.config["district"])
        code = next((e.code for e in district.emd if e.name == row.emd_name), None)
        if not code:
            raise ValueError(
                f"{row.emd_name}: districts.yaml 에 행정동코드가 없다. "
                "매핑 실패를 null 로 넘기지 않는다 — 이 회차의 지역구 획정이 "
                "지금과 달랐을 수 있다 (C-005 §역사적 선거구 획정)"
            )
        return Record(
            kind="election_result",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=self.meta.source_url,
            source_license=self.meta.source_license,
            observed_at=datetime.fromisoformat(election["date"]),
            observed_precision="day",
            geo_level="emd",
            geo_code=code,
            geo_name=row.emd_name,
            confidence=1.0,  # 공식 확정 개표결과. 표본이 아니다
            derived_from=[],
            natural_key=f"{election['id']}|{row.emd_name}",
            payload={
                "election_id": election["id"],
                "election_type": "national_assembly",
                "district_name": election["district_name"],
                "precinct": None,
                "eligible_voters": row.eligible_voters,
                "total_votes": row.total_votes,
                "results": [
                    {"party": party, "candidate": name, "votes": votes}
                    for (party, name), votes in zip(row.results, row.votes, strict=True)
                ],
                "invalid_votes": row.invalid_votes,
            },
        )

    # --- 설정 ------------------------------------------------------------------

    def _election(self, election_id: str) -> dict[str, Any]:
        for election in self.meta.config["elections"]:
            if election["id"] == election_id:
                return election
        raise ValueError(
            f"meta.yaml 에 없는 선거다: {election_id}. raw 는 있는데 설정에서 지워졌을 수 있다"
        )

    @cached_property
    def _emd_names(self) -> set[str]:
        """수집 대상 행정동. districts.yaml 이 단일 진실이다 (현재=2024 기준)."""
        return {emd.name for emd in resolve_district(self.meta.config["district"]).emd}
