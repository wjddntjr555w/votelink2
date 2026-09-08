"""선거구 ↔ 행정동 매핑.

선거구 획정은 매 선거마다 바뀐다. 그래서 코드가 아니라 데이터
(`data/reference/districts.yaml`)로 둔다.

L1은 '어디를 수집할지', L2는 '어디를 분석할지'를 여기서 가져온다.
두 계층이 각자 목록을 들고 있으면 반드시 어긋난다.
"""

from __future__ import annotations

import threading
from collections import Counter
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
    """선거구에 속한 행정동 하나.

    code 는 내부 표준(행정동코드 10자리)이며 **아직 모를 수 있다.**
    org_code(행정기관코드 7자리)만 아는 상태를 정직하게 표현하기 위해 null 을 허용한다.
    모르는 것을 아는 척하는 것보다 비어 있는 편이 낫다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    code: str | None = None
    org_code: str | None = None

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str | None) -> str | None:
        if v is not None and not (v.isdigit() and len(v) == GEO_CODE_DIGITS):
            raise ValueError(f"행정동코드는 숫자 {GEO_CODE_DIGITS}자리여야 한다: {v!r}")
        return v

    @property
    def resolved(self) -> bool:
        return self.code is not None


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
        for label, values in (
            ("행정동코드", [e.code for e in v if e.code]),
            ("행정기관코드", [e.org_code for e in v if e.org_code]),
            ("행정동명", [e.name for e in v]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"같은 {label} 가 두 번 들어 있다")
        return v

    @property
    def emd_codes(self) -> list[str]:
        """확인된 행정동코드만. 미확인 동은 조용히 빠지지 않도록 pending 으로 드러난다."""
        return [e.code for e in self.emd if e.code]

    @property
    def sigungu_codes(self) -> list[str]:
        """이 선거구가 걸친 시군구 코드(행정동코드 앞 5자리 + "00000"), 오름차순.

        앞 4자리로 자르면 5번째 자리가 0이 아닌 구 — 서울 광진(11215)·강북(11305)·
        금천(11545) — 에서 틀린다. 두 시군구에 걸친 선거구(중구·성동구 을)면 둘 다 든다.
        """
        return sorted({f"{c[:5]}00000" for c in self.emd_codes})

    @property
    def primary_sigungu_code(self) -> str:
        """이 선거구의 대표 자치구 코드(행정동코드 앞 5자리 + "00000").

        두 시군구에 걸친 선거구(중구성동구 을)면 **더 많은 동이 속한** 쪽을 쓴다 —
        district.sigungu 가 가리키는 그 자치구다. nec_archive 의 sigungu 기준선
        생성과 voter_profile 의 기준선 대조가 이 하나를 공유해야 어긋나지 않는다.
        `sigungu_codes` 와 같은 5자리 규칙이다(4자리는 광진·강북·금천에서 틀린다).
        """
        counts = Counter(f"{c[:5]}00000" for c in self.emd_codes)
        if not counts:
            raise ValueError(
                f"선거구 '{self.id}' 에 확인된 행정동코드가 없다 — "
                "primary_sigungu_code 를 유도할 수 없다"
            )
        # most_common 은 동률 시 삽입 순서를 지킨다. emd 는 districts.yaml 순서라
        # 결정적이다.
        return counts.most_common(1)[0][0]

    @property
    def pending(self) -> list[Emd]:
        """내부 표준 코드를 아직 모르는 행정동."""
        return [e for e in self.emd if not e.resolved]

    @property
    def fully_resolved(self) -> bool:
        return not self.pending

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
