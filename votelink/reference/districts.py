"""선거구 ↔ 행정동 매핑.

선거구 획정은 매 선거마다 바뀐다. 그래서 코드가 아니라 데이터
(`data/reference/districts.yaml`)로 둔다.

L1은 '어디를 수집할지', L2는 '어디를 분석할지'를 여기서 가져온다.
두 계층이 각자 목록을 들고 있으면 반드시 어긋난다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from votelink.contract.models import GEO_CODE_DIGITS

DISTRICTS_PATH = Path("data/reference/districts.yaml")

_lock = threading.Lock()
_cache: dict[str, District] | None = None


class DistrictNotFound(LookupError):
    """알 수 없는 선거구. 오타이거나 districts.yaml 에 아직 없다."""


class Emd(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    name: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not (v.isdigit() and len(v) == GEO_CODE_DIGITS):
            raise ValueError(f"행정기관코드는 숫자 {GEO_CODE_DIGITS}자리여야 한다: {v!r}")
        return v


class District(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    sido: str
    sigungu: str
    emd: list[Emd] = Field(min_length=1)
    source: str = "unknown"

    @field_validator("emd")
    @classmethod
    def _no_duplicates(cls, v: list[Emd]) -> list[Emd]:
        codes = [e.code for e in v]
        if len(codes) != len(set(codes)):
            raise ValueError("같은 행정동코드가 두 번 들어 있다")
        return v

    @property
    def emd_codes(self) -> list[str]:
        return [e.code for e in self.emd]

    def name_of(self, code: str) -> str | None:
        return next((e.name for e in self.emd if e.code == code), None)

    def contains(self, code: str) -> bool:
        """이 선거구에 속하는 행정동인가. 옆 지역구 데이터가 섞였는지 볼 때 쓴다."""
        return any(e.code == code for e in self.emd)


def load_districts(path: Path | None = None, *, force: bool = False) -> dict[str, District]:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        target = path or DISTRICTS_PATH
        if not target.exists():
            raise FileNotFoundError(f"선거구 정의 파일이 없다: {target}")
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        districts = [District.model_validate(d) for d in raw.get("districts", [])]
        _cache = {d.id: d for d in districts}
        return _cache


def reset_cache() -> None:
    """테스트용."""
    global _cache
    with _lock:
        _cache = None


def resolve_district(key: str, path: Path | None = None) -> District:
    """id 또는 이름으로 선거구를 찾는다."""
    districts = load_districts(path)
    if key in districts:
        return districts[key]
    for district in districts.values():
        if district.name == key:
            return district
    known = ", ".join(sorted(districts)) or "(없음)"
    raise DistrictNotFound(f"선거구 '{key}' 를 찾을 수 없다. 정의된 것: {known}")
