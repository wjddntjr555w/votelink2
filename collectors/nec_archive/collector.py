"""선관위 개표자료 아카이브 수집기 — 대통령선거 (1992~2025).

fetch: Excel 을 셀 격자로 **디코딩만** 해서 담는다 (해석 금지)
parse: 격자 -> election_result 레코드 (네트워크 금지, 순수 함수)

제안서: docs/proposals/C-004-nec-archive-presidential.md
"""

from __future__ import annotations

from collections import Counter
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
    normalize_emd,
)


class Collector(BaseCollector):
    id = "nec_archive"

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """아카이브의 Excel 을 격자로 풀어 담는다. 네트워크를 타지 않는다.

        `since` 는 무시한다 (`incremental: false`). 과거 선거는 값이 바뀌지 않고,
        재실행해도 `record_id` 가 같아 멱등이다.
        """
        base = Path(self.config["archive_dir"])
        if not base.is_dir():
            raise FetchError(
                f"아카이브 폴더가 없다: {base}. "
                "선관위 개표자료를 data/raw/nec_archive/ 아래에 두어야 한다 (docs/SETUP.md)"
            )
        for election in self.config["elections"]:
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
            sigungu_match=self._sigungu_match(),
            emd_names=self._emd_names,
            total_markers=tuple(self.config["precinct_total_markers"]),
        )
        yield from self.map_items(rows, lambda row: self._to_record(row, election))

        # 기준선(전국·서울시·해당 자치구). 동별 득표율은 '무엇 대비'가 있어야 지표가 된다.
        # 규칙은 선거마다 다르므로 meta.yaml 에 두었고, 없는 회차는 그냥 건너뛴다
        # (2002년은 시도 열이 없어 서울시를 못 만든다).
        # sgg/sgg_prefix 의 "{sigungu}" 자리는 이 선거구의 자치구명으로 치환한다
        # (D-002 — 47개 선거구로 확장하며 송파구 하드코딩을 없앴다).
        # YAML 은 리스트를 주지만 규칙은 frozen 이라 튜플로 맞춘다.
        sigungu_name = resolve_district(self.config["district"]).sigungu
        rules = [
            BaselineRule(
                **{
                    **rule,
                    "emd": tuple(rule.get("emd", ())),
                    "sgg": self._fmt_sigungu(rule.get("sgg"), sigungu_name),
                    "sgg_prefix": self._fmt_sigungu(rule.get("sgg_prefix"), sigungu_name),
                }
            )
            for rule in election.get("baselines", [])
        ]
        # sigungu 규칙만 "행이 없음"을 관대하게 본다 — 그 자치구가 이 회차 시점에
        # 아직 없었을 수 있다(예: 금천구·강북구는 1995년 분구, 1992년 파일엔 없다).
        # nation/sido 규칙은 그대로 크게 실패한다 — 그건 회차마다 항상 있어야 하고,
        # 없으면 baselines 조건이 이 파일 표기와 안 맞는다는 신호다.
        baseline_rows: list[BaselineRow] = []
        for rule in rules:
            try:
                baseline_rows.extend(iter_baseline_rows(grid, layout, [rule]))
            except ValueError:
                if rule.level != "sigungu":
                    raise

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
        district = resolve_district(self.config["district"])
        # row.emd_name 은 이미 normalize_emd() 를 거친 값(§ iter_emd_rows) 이므로
        # districts.yaml 쪽도 같은 정규화를 거쳐 비교한다 — 표기가 서로 다를 수 있다.
        code = next(
            (e.code for e in district.emd if normalize_emd(e.name) == row.emd_name), None
        )
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
            # geo_code 로 유일성을 준다 — 동 이름만 쓰면 다른 자치구의 동명이 겹친다
            # (예: '신사동' 이 관악구·강남구 둘 다에 있다). 47개 선거구로 넓히기
            # 전에는 선거구가 하나뿐이라 드러나지 않았던 사고다(D-002).
            natural_key=f"{election['id']}|{code}",
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
        geo = self._baseline_geo[row.level]
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
            # level 만으로는 sigungu 단위가 25개 자치구 사이에서 겹친다(모두
            # '...|baseline|sigungu' 가 된다) — geo_code 로 자치구를 구분한다.
            # nation/sido 는 모든 선거구에서 같은 가야 정상이라 code 가 없거나
            # (nation) 같은 값(sido)이면 의도대로 하나로 합쳐진다.
            natural_key=f"{election['id']}|baseline|{row.level}|{geo['code'] or 'nation'}",
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
        for election in self.config["elections"]:
            if election["id"] == election_id:
                return election
        raise ValueError(
            f"meta.yaml 에 없는 선거다: {election_id}. raw 는 있는데 설정에서 지워졌을 수 있다"
        )

    @cached_property
    def _emd_names(self) -> set[str]:
        """수집 대상 행정동. districts.yaml 이 단일 진실이다.

        normalize_emd() 를 거쳐서 비교한다 — 파일 쪽 이름도 같은 정규화를 거치므로
        (§iter_emd_rows) '창신제1동'(districts.yaml) 과 '창신1동'(선관위 원본 표기)
        같은 표기 차이가 매칭 실패로 이어지지 않는다.
        """
        return {normalize_emd(emd.name) for emd in resolve_district(self.config["district"]).emd}

    def _sigungu_match(self) -> tuple[str, ...]:
        """동 필터에 쓸 자치구명 부분 문자열들. districts.yaml 의 sigungu 에서 유도한다.

        '구'를 뗀다 — 원본 파일의 표기 흔들림('송파구' 든 다른 접미사든)에 substring
        매칭으로 잡히게 하기 위해서다(기존 송파구 설정의 관례를 그대로 따른다).

        선거구가 두 자치구에 걸치면(예: 중구성동구 을 — 중구 15동 + 성동구 4동,
        D-001·D-002 에서 발견) district.sigungu 하나만으로는 놓치는 동이 생긴다.
        그런 선거구는 meta.yaml 의 config.extra_sigungu 로 추가 자치구를 적는다.
        """
        primary = resolve_district(self.config["district"]).sigungu.removesuffix("구")
        extra = tuple(self.cfg("extra_sigungu") or ())
        return (primary, *extra)

    @cached_property
    def _baseline_geo(self) -> dict[str, dict[str, str | None]]:
        """전국·서울시·해당 자치구의 지리 식별자. districts.yaml 에서 유도한다(D-002).

        sigungu 코드는 그 선거구 행정동코드(admmCd)들의 공통 4자리 접두사 + '000000'
        이다 — mois_population 이 실측한 sigungu_admm_code 와 같은 규칙
        (docs/SETUP.md §2). 접두사가 하나로 안 모이면(선거구가 두 시군구에 걸친
        경우, 예: 중구성동구 을) 더 많은 동이 속한 접두사를 쓴다 — district.sigungu
        가 가리키는 그 자치구다(D-001 §제약과 위험에 같은 한계가 적혀 있다).
        """
        district = resolve_district(self.config["district"])
        if district.sido != "서울특별시":
            raise ValueError(
                f"{district.id}: 서울 밖 선거구의 기준선은 아직 지원하지 않는다 "
                f"(sido={district.sido!r}). SEOUL_SIDO 상수를 일반화해야 한다"
            )
        codes = district.emd_codes
        if not codes:
            raise ValueError(
                f"{district.id}: 확인된 행정동코드가 없다 — "
                "먼저 `votelink district backfill-codes` 를 돌려라 (D-001)"
            )
        prefix, _ = Counter(c[:4] for c in codes).most_common(1)[0]
        return {
            "nation": {"code": None, "name": "전국"},
            "sido": {"code": "1100000000", "name": "서울특별시"},
            "sigungu": {"code": f"{prefix}000000", "name": district.sigungu},
        }

    @staticmethod
    def _fmt_sigungu(value: str | None, sigungu_name: str) -> str | None:
        if value is None:
            return None
        return value.format(sigungu=sigungu_name)
