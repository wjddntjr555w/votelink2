"""선관위 개표자료 아카이브 수집기 — 대통령선거 (1992~2025).

fetch: Excel 을 셀 격자로 **디코딩만** 해서 담는다 (해석 금지)
parse: 격자 -> election_result 레코드 (네트워크 금지, 순수 함수)

제안서: docs/proposals/C-004-nec-archive-presidential.md
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
from .rows import (
    BaselineRow,
    BaselineRule,
    Layout,
    check_arithmetic,
    check_baseline_arithmetic,
    iter_baseline_rows,
    iter_emd_rows,
    merge_baseline_rows,
)


class Collector(BaseCollector):
    id = "nec_archive"

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """아카이브의 Excel 을 격자로 풀어 담는다. 네트워크를 타지 않는다.

        `since` 는 무시한다 (`incremental: false`). 과거 선거는 값이 바뀌지 않고,
        재실행해도 `record_id` 가 같아 멱등이다.
        """
        base = Path(self.meta.config["archive_dir"])
        if not base.is_dir():
            raise FetchError(
                f"아카이브 폴더가 없다: {base}. "
                "선관위 개표자료를 data/raw/nec_archive/ 아래에 두어야 한다 (docs/SETUP.md)"
            )
        for election in self.meta.config["elections"]:
            path = base / election["file"]
            if not path.is_file():
                raise FetchError(f"{election['id']}: 파일이 없다 — {path}")

            body: dict[str, Any] = {"election_id": election["id"], "grid": read_grid(path)}

            # 17대(2007)는 시도별 16개 파일로 쪼개져 있어 전국 총계를 만들려면
            # 서울 파일(위) 말고 나머지 15개도 읽어야 한다. 격자를 같은 배치에
            # 함께 담아 두면 parse 가 네트워크·파일 접근 없이 순수 함수로 남는다.
            for region in election.get("extra_files", []):
                region_path = base / region["file"]
                if not region_path.is_file():
                    raise FetchError(
                        f"{election['id']}/{region['name']}: 파일이 없다 — {region_path}"
                    )
                body.setdefault("region_grids", {})[region["name"]] = read_grid(region_path)

            yield RawBatch(
                collector_id=self.id,
                # 격자는 원본 그대로다. election_id 는 '이 격자가 어느 선거인지'를
                # 표시할 뿐이며, 레이아웃은 meta.yaml 에 남는다 —
                # 그래야 파서를 고쳤을 때 --reparse 로 다시 만들 수 있다.
                body=body,
                batch_key=election["id"],
                source_url=path.as_posix(),
            )

    # --- parse ----------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        election = self._election(raw.body["election_id"])
        layout = Layout(**election["layout"])
        grid = raw.body["grid"]

        rows = iter_emd_rows(
            grid,
            layout,
            sigungu_match=self.meta.config["sigungu_match"],
            emd_names=self._emd_names,
            total_markers=tuple(self.meta.config["precinct_total_markers"]),
        )
        yield from self.map_items(rows, lambda row: self._to_record(row, election))

        # 기준선(전국·서울시·송파구). 동별 득표율은 '무엇 대비'가 있어야 지표가 된다.
        # 규칙은 선거마다 다르므로 meta.yaml 에 두었고, 없는 회차는 그냥 건너뛴다
        # (2002년은 시도 열이 없어 서울시를 못 만든다).
        # YAML 은 리스트를 주지만 규칙은 frozen 이라 튜플로 맞춘다.
        rules = [
            BaselineRule(**{**rule, "emd": tuple(rule.get("emd", ()))})
            for rule in election.get("baselines", [])
        ]
        baseline_rows = list(iter_baseline_rows(grid, layout, rules)) if rules else []

        # 17대(2007)는 서울 파일 하나로는 전국을 만들 수 없다. 나머지 15개 시도
        # 파일의 자체 총계(구 합계의 합)를 서울 몫과 더한다.
        #
        # region_grids 가 없는 raw 배치를 만나면(이 기능을 추가하기 전에 fetch 된
        # 배치) **건너뛴다.** data/raw/ 는 절대 수정·삭제하지 않으므로 옛 배치가
        # 남아 있는 것은 정상이고, --reparse 는 새 배치도 함께 읽어 그쪽에서
        # 전국 레코드를 만든다. 조용히 넘어가는 게 아니라 옛 스키마는 이 필드를
        # 낼 수 없다는 사실을 반영할 뿐이다.
        extra = election.get("extra_files")
        region_grids = raw.body.get("region_grids") if extra else None
        if extra and region_grids is not None:
            region_rows = [self._region_total(layout, region_grids[r["name"]], r) for r in extra]
            seoul_total = next(r for r in baseline_rows if r.level == "sido")
            baseline_rows.append(merge_baseline_rows([seoul_total, *region_rows], level="nation"))

        if baseline_rows:
            yield from self.map_items(
                baseline_rows, lambda row: self._to_baseline_record(row, election)
            )

    @staticmethod
    def _region_total(layout: Layout, grid: Any, region: dict[str, Any]) -> BaselineRow:
        """시도 파일 하나의 자체 총계 (그 파일 안의 구 합계 행을 전부 더한 값)."""
        rule = BaselineRule(level=region["name"], emd=("합계",), expect=region["expect"])
        (row,) = list(iter_baseline_rows(grid, layout, [rule]))
        check_baseline_arithmetic(row)
        return row

    def _to_record(self, row: Any, election: dict[str, Any]) -> Record:
        check_arithmetic(row)
        district = resolve_district(self.meta.config["district"])
        code = next((e.code for e in district.emd if e.name == row.emd_name), None)
        if not code:
            raise ValueError(
                f"{row.emd_name}: districts.yaml 에 행정동코드가 없다. "
                "매핑 실패를 null 로 넘기지 않는다"
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
                "election_type": "presidential",
                # 대선에는 선거구 개념이 없다. 분석 대상 선거구를 적는다.
                "district_name": district.name,
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

    def _to_baseline_record(self, row: Any, election: dict[str, Any]) -> Record:
        """상위 행정단위(전국·서울시·송파구) 합계 레코드.

        동 레코드와 **같은 kind·같은 payload** 를 쓴다. 다른 것은 geo_level 뿐이다.
        그래서 분석기는 이걸 특별 취급하지 않고 geo_level 로만 분기하면 된다.
        """
        check_baseline_arithmetic(row)
        geo = self.meta.config["baseline_geo"][row.level]
        return Record(
            kind="election_result",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=self.meta.source_url,
            source_license=self.meta.source_license,
            observed_at=datetime.fromisoformat(election["date"]),
            observed_precision="day",
            geo_level=row.level,
            # nation 은 계약상 geo_code 를 가질 수 없다 (docs/10-data-contract.md §3).
            geo_code=geo["code"],
            geo_name=geo["name"] if geo["code"] else None,
            confidence=1.0,  # 공식 확정 개표결과의 합계다. 추정이 아니다
            derived_from=[],
            natural_key=f"{election['id']}|baseline|{row.level}",
            payload={
                "election_id": election["id"],
                "election_type": "presidential",
                "district_name": geo["name"],
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
        """수집 대상 행정동. districts.yaml 이 단일 진실이다."""
        return {emd.name for emd in resolve_district(self.meta.config["district"]).emd}
