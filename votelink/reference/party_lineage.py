"""대선 후보 → 진영(camp) 매핑.

정당명은 회차마다 바뀐다(1992 민자당 … 2025 국민의힘). 동별 성향을 시계열로
비교하려면 공통 축이 필요한데, **그 축을 정하는 일은 정치적 판단이다.**
그래서 코드가 아니라 데이터(`data/shared/reference/party_lineage.yaml`)에 둔다 —
이견이 있으면 그 파일만 고치고 재분석하면 된다. `districts.py` 와 같은 구조다.

기본 키는 `(election_id, candidate)` 다. 정당이 아니다:
  - 2002년(16대) 개표자료에는 정당 열 자체가 없다 (원본 헤더가 후보명만 준다)
  - 같은 사람이 회차마다 다른 위치에 있다 (이회창: 1997·2002 한나라당 → 2007 무소속)

**총선은 지역구 300여 곳이 같은 election_id 를 공유한다** (대선은 선거구 개념이
없어 하나였다). 그래서 같은 이름이 다른 지역구에 우연히 겹칠 수 있다 — 실제로
2024년(22대) 서울에서만 '이상규'가 성북구을(국민의힘)·관악구을(진보당) 두 곳에
있다. 이런 경우에만 `district` 필드로 `(election_id, district, candidate)` 로
더 좁게 키를 준다 — `district` 는 레코드 payload 의 `district_name` 과 정확히
같은 문자열이어야 한다(예: "서울 관악구을"). `camp_of` 는 district 가 있는 항목을
먼저 찾고, 없으면 기본(district 없는) 항목으로 넘어간다. 대부분의 후보는
지역구 하나에서만 나오므로 `district` 를 안 적어도 된다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from votelink.contract.enums import Camp

LINEAGE_PATH = Path("data/shared/reference/party_lineage.yaml")

_lock = threading.Lock()
_cache: _Table | None = None


class CampNotFound(LookupError):
    """매핑에 없는 후보.

    **조용히 OTHER 로 떨어뜨리지 않는다.** 그러면 '매핑 누락'과 '실제 군소후보'를
    구분할 수 없고, 새 선거를 붙였을 때 득표가 통째로 사라진 것을 아무도 모른다.
    """


class CandidateCamp(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    election: str
    candidate: str
    camp: Camp
    party: str | None = None  # 참고용. 매칭에 쓰지 않는다
    district: str | None = None  # 동명이인 구분용. payload.district_name 과 같은 문자열
    source: str | None = None


@dataclass(frozen=True)
class _Table:
    plain: dict[tuple[str, str], CandidateCamp] = field(default_factory=dict)
    by_district: dict[tuple[str, str, str], CandidateCamp] = field(default_factory=dict)


def load_lineage(path: Path | None = None, *, force: bool = False) -> _Table:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        target = path or LINEAGE_PATH
        if not target.exists():
            raise FileNotFoundError(f"진영 매핑 파일이 없다: {target}")
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        entries = [CandidateCamp.model_validate(c) for c in raw.get("candidates", [])]

        plain: dict[tuple[str, str], CandidateCamp] = {}
        by_district: dict[tuple[str, str, str], CandidateCamp] = {}
        for entry in entries:
            if entry.district is None:
                key2 = (entry.election, entry.candidate)
                if key2 in plain:
                    raise ValueError(
                        f"같은 (선거, 후보)가 두 번 있다: {key2}. "
                        "동명이인이면 district 필드로 구분하라"
                    )
                plain[key2] = entry
            else:
                key3 = (entry.election, entry.district, entry.candidate)
                if key3 in by_district:
                    raise ValueError(f"같은 (선거, 지역구, 후보)가 두 번 있다: {key3}")
                by_district[key3] = entry
        _cache = _Table(plain=plain, by_district=by_district)
        return _cache


def reset_cache() -> None:
    """테스트용."""
    global _cache
    with _lock:
        _cache = None


def camp_of(
    election_id: str, candidate: str, district_name: str | None = None, path: Path | None = None
) -> Camp:
    """이 선거(+선거구)의 이 후보가 어느 진영인가. 매핑에 없으면 CampNotFound.

    `district_name` 이 주어지면 그 지역구 전용 항목을 먼저 찾고, 없으면 기본
    항목으로 넘어간다 — 대부분의 후보는 기본 항목 하나로 충분하다.
    """
    table = load_lineage(path)
    entry = None
    if district_name is not None:
        entry = table.by_district.get((election_id, district_name, candidate))
    if entry is None:
        entry = table.plain.get((election_id, candidate))
    if entry is None:
        raise CampNotFound(
            f"진영 매핑에 없는 후보다: {election_id} / {candidate}"
            + (f" ({district_name})" if district_name else "")
            + ". data/shared/reference/party_lineage.yaml 에 추가하라 "
            "(추측으로 other 처리하지 않는다)"
        )
    return entry.camp
