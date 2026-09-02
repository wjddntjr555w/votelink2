"""행정구역 코드 변환 — 이 프로젝트 최대의 함정.

행안부·통계청·선관위가 서로 다른 코드 체계를 쓴다. 내부 표준은 행안부 행정동코드다.
각 수집기는 자기 출처의 코드를 여기서 내부 표준으로 바꾼다.

**매핑 실패는 예외다.** null 로 넘기면 그 지역이 통째로 전략에서 빠진다.
"""

from __future__ import annotations

import csv
import re
import threading
from dataclasses import dataclass
from pathlib import Path

REFERENCE_CSV = Path("data/reference/geo_mapping.csv")
CSV_HEADER = ["source_system", "source_code", "source_name", "emd_code", "emd_name"]

_WS_RE = re.compile(r"\s+")
_lock = threading.Lock()
_table: GeoTable | None = None


class GeoMappingError(LookupError):
    """행정동코드로 변환하지 못했다. 계약 위반이므로 해당 레코드는 격리된다."""


def normalize_name(name: str) -> str:
    """'서울특별시 송파구 풍납1동' 처럼 표기가 흔들리는 지역명을 비교 가능하게 만든다."""
    return _WS_RE.sub("", name).replace("·", "").lower()


@dataclass(frozen=True)
class GeoEntry:
    emd_code: str
    emd_name: str


class GeoTable:
    """(체계, 코드) 와 정규화된 이름 두 갈래로 조회한다."""

    def __init__(self) -> None:
        self._by_code: dict[tuple[str, str], GeoEntry] = {}
        self._by_name: dict[str, GeoEntry] = {}
        self._ambiguous_names: set[str] = set()

    def add(self, system: str, code: str, name: str, emd_code: str, emd_name: str) -> None:
        entry = GeoEntry(emd_code=emd_code, emd_name=emd_name)
        if code:
            self._by_code[(system, code)] = entry
        # 출처 표기('서울특별시 송파구 풍납1동')와 짧은 동명('풍납1동') 둘 다로 찾을 수 있어야 한다.
        for candidate in (name, emd_name):
            if not candidate:
                continue
            key = normalize_name(candidate)
            existing = self._by_name.get(key)
            if existing and existing.emd_code != emd_code:
                # 같은 동 이름이 여러 시군구에 있다 (예: 신흥동). 이름만으로는 못 정한다.
                self._ambiguous_names.add(key)
            else:
                self._by_name[key] = entry

    def lookup(self, value: str, system: str | None) -> GeoEntry:
        value = value.strip()
        if not value:
            raise GeoMappingError("빈 값은 행정동코드로 변환할 수 없다")

        if system:
            hit = self._by_code.get((system, value))
            if hit:
                return hit

        for (_sys, code), entry in self._by_code.items():
            if code == value:
                return entry

        key = normalize_name(value)
        if key in self._ambiguous_names:
            raise GeoMappingError(
                f"'{value}' 는 여러 시군구에 존재해 이름만으로 확정할 수 없다. "
                "상위 행정구역을 붙여서 넘겨라 (예: '서울특별시 송파구 풍납1동')"
            )
        hit = self._by_name.get(key)
        if hit:
            return hit

        raise GeoMappingError(
            f"'{value}' 를 행정동코드로 변환하지 못했다 (system={system}). "
            f"{REFERENCE_CSV} 에 매핑을 추가하거나 `votelink geo import` 로 갱신하라"
        )

    def __len__(self) -> int:
        return len(self._by_code) + len(self._by_name)


def load_table(path: Path | None = None, *, force: bool = False) -> GeoTable:
    global _table
    with _lock:
        if _table is not None and not force:
            return _table
        target = path or REFERENCE_CSV
        table = GeoTable()
        if target.exists():
            with target.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    table.add(
                        system=(row.get("source_system") or "").strip(),
                        code=(row.get("source_code") or "").strip(),
                        name=(row.get("source_name") or "").strip(),
                        emd_code=(row.get("emd_code") or "").strip(),
                        emd_name=(row.get("emd_name") or "").strip(),
                    )
        _table = table
        return table


def reset_table() -> None:
    """테스트용. 캐시된 매핑표를 버린다."""
    global _table
    with _lock:
        _table = None


def to_emd_code(value: str, *, system: str | None = None) -> str:
    """출처의 지역 코드 또는 지역명 -> 행안부 행정동코드 10자리 (GEO_CODE_DIGITS).

    변환 실패 시 GeoMappingError. 절대 None 을 돌려주지 않는다.
    """
    table = load_table()
    if len(table) == 0:
        raise GeoMappingError(
            f"행정동 매핑표가 비어 있다: {REFERENCE_CSV}. "
            "`votelink geo import <행안부 행정동코드 CSV>` 로 먼저 채워라"
        )
    return table.lookup(value, system).emd_code


def to_emd_name(value: str, *, system: str | None = None) -> str:
    return load_table().lookup(value, system).emd_name
