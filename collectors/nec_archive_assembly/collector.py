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
from .rows import (
    DEFAULT_TOTAL_MARKERS,
    Layout,
    check_arithmetic,
    iter_district_rows,
    normalize_emd,
)


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
        base = Path(self.config["archive_dir"])
        if not base.is_dir():
            raise FetchError(
                f"아카이브 폴더가 없다: {base}. "
                "선관위 개표자료를 data/raw/nec_archive_assembly/ 옆에 두어야 한다"
            )
        for election in self.config["elections"]:
            election = self._resolve(election)
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
        if election is None:
            # `--reparse` 는 이 collector_id 의 raw 이력 전체를 읽는데, 선거구마다
            # elections 목록이 다르다(송파갑만 18~21대를 더 갖고 있다, D-002). 이
            # raw 가 다른 선거구용으로 fetch 된 회차일 뿐이면 조용히 건너뛴다 —
            # '다른 시군구 행을 버린다'(iter_district_rows)와 같은 판단이다.
            return
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
        district = resolve_district(self.config["district"])
        # row.emd_name 은 이미 normalize_emd() 를 거친 값이므로 districts.yaml 쪽도
        # 같은 정규화를 거쳐 비교한다 — 표기가 서로 다를 수 있다(D-001).
        code = next(
            (e.code for e in district.emd if normalize_emd(e.name) == row.emd_name), None
        )
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
            # geo_code 로 유일성을 준다 — 동 이름만 쓰면 다른 자치구의 동명이 겹친다
            # (예: '신사동' 이 관악구·강남구 둘 다에 있다). 47개 선거구로 넓히기
            # 전에는 선거구가 하나뿐이라 드러나지 않았던 사고다(D-002).
            natural_key=f"{election['id']}|{code}",
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

    def _election(self, election_id: str) -> dict[str, Any] | None:
        """이 선거구의 config 에 이 election_id 가 있으면 돌려주고, 없으면 None.

        선거구마다 elections 목록이 다를 수 있어(D-002) '없다'가 항상 설정
        오류는 아니다 — 그 판단은 `parse()` 가 한다(다른 선거구용 raw 는 건너뛴다).
        """
        for election in self.config["elections"]:
            if election["id"] == election_id:
                return self._resolve(election)
        return None

    def _resolve(self, election: dict[str, Any]) -> dict[str, Any]:
        """district_match == "{auto}" 인 항목의 표기를 이 선거구 값으로 채운다.

        22대(전국 단일 파일)뿐 아니라 19~21대(선거구별 파일)도 파일명에
        **같은 표기**("강남구갑" 등)를 그대로 쓴다는 게 실측으로 확인됐다(D-004)
        — 그래서 selector.file/sheet 안의 "{auto}" 도 같이 치환한다. 18대는
        이 템플릿을 안 쓴다(아래 _auto_district_match 참조) — 이 함수는 그
        회차의 config 자체가 없는 선거구에는 호출되지 않는다.
        """
        if election.get("district_match") != "{auto}":
            return election
        auto = self._auto_district_match()
        token = auto["district_match"]
        selector = dict(election["selector"])
        if "{auto}" in selector.get("file", ""):
            selector["file"] = selector["file"].format(auto=token)
        sheet = selector.get("sheet")
        if isinstance(sheet, str) and "{auto}" in sheet:
            selector["sheet"] = sheet.format(auto=token)
        return {**election, **auto, "selector": selector}

    def _auto_district_match(self) -> dict[str, str]:
        """이 선거구의 districts.yaml name 에서 파일/시트/텍스트 표기를 유도한다.

        22대 전국 파일은 이 표기가 곧 districts.yaml 의 출처다(docs/SETUP.md §3,
        "제22대 국회의원선거 개표결과(지역구) 전국 xlsx 에서 프로그램으로 추출").
        19~21대(선거구별 파일)도 파일명이 같은 표기 규칙을 따른다는 것을 실측으로
        확인했다(D-004). **18대(2008)는 이 템플릿을 쓰지 않는다** — 파일명은
        맞아도 그 시절 행정동 자체가 지금과 다른 경우가 흔하다(관악구는 2008년에
        '봉천제1동'~'봉천제11동'이었고 지금 이름으로 남은 동이 거의 없다 — 개명
        이력을 모르면 추정이 된다). 송파갑만 개별 검증을 거쳐 자기 elections 에
        18대를 직접 얹어 뒀다.
        19~21대에서도 파일명은 맞는데 실제 동 구성이 안 맞는 선거구가 있었다
        (노원구 갑/을, 강동구 갑/을, 강남구 을, 구로구 갑·은평구 갑·송파구 병 일부
        회차) — 실측으로 걸러 해당 회차를 그 선거구의 elections 목록에서 뺐다
        (meta.yaml 의 districts.<id> override). 이유가 다른 3종(중구성동구 갑/을,
        강남구병·강서구병)도 마찬가지로 해당 회차를 아예 뺐다. 어느 쪽이든
        코드는 이 값을 유도만 할 뿐 추정하지 않는다 — 판단은 meta.yaml 에 있다.
        "서울 강남구 갑" -> "강남구갑".
        """
        name = resolve_district(self.config["district"]).name
        match = name.removeprefix("서울 ").replace(" ", "")
        return {"district_match": match, "district_name": f"서울 {match}"}

    @cached_property
    def _emd_names(self) -> set[str]:
        """수집 대상 행정동. districts.yaml 이 단일 진실이다 (현재=2024 기준).

        normalize_emd() 를 거쳐서 비교한다 — 파일 쪽 이름도 같은 정규화를 거치므로
        (§iter_district_rows) 표기 차이가 매칭 실패로 이어지지 않는다(D-001).
        """
        return {normalize_emd(emd.name) for emd in resolve_district(self.config["district"]).emd}
