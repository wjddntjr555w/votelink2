"""중앙선관위 과거 선거 개표결과 수집기 (행정동 단위).

fetch: 사람이 포털에서 내려받아 `data/shared/incoming/` 에 넣어둔 CSV를 **디코딩만** 해서 내놓는다.
       네트워크를 타지 않는다. CSV 파싱도 하지 않는다 (그건 parse 의 일이다).
parse: 순수 함수. 투표구 행을 행정동으로 접고, 대상 선거구의 동만 남겨 공통 레코드로 만든다.

오픈API가 아니라 파일데이터를 쓰는 이유는 docs/SETUP.md §4 에 적었다 —
API 쪽은 후보 득표수·읍면동 필드가 공식 문서에 없다.

geo_code 는 districts.yaml 의 행정동코드에서 온다. 이 출처는 지역을 이름으로만 주기 때문이다.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from votelink.collect import BaseCollector, ParseResult, RawBatch
from votelink.collect.http import FetchError
from votelink.contract.models import KST, Record
from votelink.reference import resolve_district

from .rows import EmdTally, pick_column, tally_rows, to_int  # noqa: F401  (to_int 는 테스트가 쓴다)

log = logging.getLogger(__name__)


class Collector(BaseCollector):
    id = "nec_election_result"

    # --- fetch ---------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """확정 개표결과라 since 는 무시한다 (meta.incremental=false)."""
        incoming = Path(self.cfg("incoming_dir", ""))
        if not incoming.is_dir():
            raise FetchError(
                f"{incoming} 폴더가 없다. 포털에서 개표결과 CSV를 내려받아 넣어라 "
                "(docs/SETUP.md §4)"
            )

        elections = self.cfg("elections", []) or []
        if not elections:
            raise FetchError("meta.yaml 의 config.elections 가 비어 있다")

        found = 0
        missing: list[str] = []
        for election in elections:
            path = self._find_file(incoming, election["file_match"])
            if path is None:
                missing.append(f"{election['election_id']} (찾는 이름: {election['file_match']})")
                continue
            text = self._decode(path)
            found += 1
            yield RawBatch(
                collector_id=self.id,
                body=text,
                batch_key=f"{election['election_id']}|{path.name}",
                source_url=self.meta.source_url,
            )

        if missing:
            # 아직 안 받은 선거는 정상적인 중간 상태다. 다만 조용히 넘기지는 않는다.
            log.warning("CSV를 찾지 못해 건너뛴 선거: %s", "; ".join(missing))
        if not found:
            raise FetchError(
                f"{incoming} 에서 대상 CSV를 하나도 찾지 못했다. 건너뛴 선거: {'; '.join(missing)}"
            )

    @staticmethod
    def _find_file(incoming: Path, needle: str) -> Path | None:
        matches = sorted(p for p in incoming.glob("*.csv") if needle in p.name)
        if len(matches) > 1:
            log.warning("'%s' 에 맞는 파일이 여러 개다. 첫 번째를 쓴다: %s", needle, matches)
        return matches[0] if matches else None

    def _decode(self, path: Path) -> str:
        """파일마다 인코딩이 다르다 (총선 cp949 / 대선 utf-8). 순서대로 시도한다.

        디코딩은 파싱이 아니다 — 바이트를 문자로 바꿀 뿐이므로 fetch 단계에서 한다.
        """
        raw = path.read_bytes()
        encodings = self.cfg("encodings", ["utf-8-sig", "cp949"]) or ["utf-8-sig"]
        for enc in encodings:
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            log.info("%s: %s 로 디코딩", path.name, enc)
            return text
        raise FetchError(f"{path.name} 을 {encodings} 중 어느 것으로도 디코딩하지 못했다")

    # --- parse ---------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        election = self._election_of(raw.batch_key)
        district = resolve_district(self.cfg("district"))

        rows = list(csv.DictReader(str(raw.body).splitlines()))
        if not rows:
            raise ValueError(f"{raw.batch_key}: CSV에 데이터 행이 없다")

        cols = self.cfg("columns", {}) or {}
        header = rows[0].keys()
        sgg_col = pick_column(header, cols.get("sgg", []), "선거구/구시군")
        emd_col = pick_column(header, cols.get("emd", []), "읍면동")
        item_col = pick_column(header, cols.get("item", []), "후보자")
        count_col = pick_column(header, cols.get("count", []), "득표수")

        target = {e.name for e in district.emd}
        sgg_match = election["sgg_match"]
        # 정확 일치로 좁힌다. '송파구' 부분일치를 쓰면 송파구을·병이 딸려 들어오는데,
        # 옆 지역구가 섞여도 숫자는 그럴듯해서 아무도 눈치채지 못한다.
        selected = [r for r in rows if (r.get(sgg_col) or "").strip() == sgg_match]
        if not selected:
            seen = sorted({(r.get(sgg_col) or "").strip() for r in rows})[:10]
            raise ValueError(f"{sgg_col}='{sgg_match}' 인 행이 없다. 파일에 있는 값 예시: {seen}")

        tallies = tally_rows(
            selected,
            emd_col=emd_col,
            item_col=item_col,
            count_col=count_col,
            keep=target,
            agg_items=self.cfg("aggregate_items", {}) or {},
        )

        missing = target - set(tallies)
        if missing:
            # 9개 중 6개만 들어와도 그 6개로 그럴듯한 전략이 나온다. 조용히 넘기지 않는다.
            raise ValueError(
                f"{election['election_id']}: 다음 행정동을 찾지 못했다: {sorted(missing)}. "
                "동 이름이 바뀌었거나 선거구 획정이 달라졌을 수 있다"
            )

        items = [(election, tally) for tally in tallies.values()]
        yield from self.map_items(items, self._to_record)

    def _to_record(self, item: tuple[dict[str, Any], EmdTally]) -> Record:
        election, tally = item
        tally.check()  # 산식이 안 맞으면 이 동 하나만 격리된다

        district = resolve_district(self.cfg("district"))
        full_name = f"{district.sido} {district.sigungu} {tally.emd}"

        return Record(
            kind="election_result",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=self.meta.source_url,
            source_license=self.meta.source_license,
            observed_at=datetime.strptime(election["date"], "%Y-%m-%d").replace(tzinfo=KST),
            observed_precision="day",
            geo_level="emd",
            geo_code=self._geo_code(tally.emd),
            geo_name=tally.emd,
            confidence=1.0,
            derived_from=[],
            natural_key=f"{election['election_id']}|{full_name}",
            payload={
                "election_id": election["election_id"],
                "election_type": election["election_type"],
                "district_name": election["district_name"],
                "precinct": None,  # 행정동 전체 집계. 투표구 단위는 MVP 밖
                "eligible_voters": tally.eligible_voters,
                "total_votes": tally.total_votes,
                "results": tally.results(),
                "invalid_votes": tally.invalid_votes,
            },
        )

    # --- 도우미 ---------------------------------------------------------------

    def _geo_code(self, emd: str) -> str:
        """districts.yaml 의 행정동코드에서 가져온다.

        이 출처는 지역명만 주고 코드를 안 준다. 내부 표준 코드는 districts.yaml 이
        갖고 있으며, 그 값은 mois_population 의 실제 응답에서 확인된 것이다.
        """
        district = resolve_district(self.cfg("district"))
        for e in district.emd:
            if e.name == emd:
                if not e.code:
                    raise ValueError(
                        f"{emd}: districts.yaml 에 행정동코드가 없다(code: null). "
                        "mois_population 을 수집해 코드를 확정하라"
                    )
                return e.code
        raise ValueError(f"{emd}: districts.yaml '{self.cfg('district')}' 에 없는 행정동")

    def _election_of(self, batch_key: str) -> dict[str, Any]:
        election_id = batch_key.split("|", 1)[0]
        for e in self.cfg("elections", []) or []:
            if e["election_id"] == election_id:
                return e
        raise ValueError(f"batch_key '{batch_key}' 에 해당하는 선거가 config.elections 에 없다")

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.meta.config.get(key, default)
