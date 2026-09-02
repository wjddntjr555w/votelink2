"""대선 후보 → 진영(camp) 매핑.

정당명은 회차마다 바뀐다(1992 민자당 … 2025 국민의힘). 동별 성향을 시계열로
비교하려면 공통 축이 필요한데, **그 축을 정하는 일은 정치적 판단이다.**
그래서 코드가 아니라 데이터(`data/reference/party_lineage.yaml`)에 둔다 —
이견이 있으면 그 파일만 고치고 재분석하면 된다. `districts.py` 와 같은 구조다.

키는 `(election_id, candidate)` 다. 정당이 아니다:
  - 2002년(16대) 개표자료에는 정당 열 자체가 없다 (원본 헤더가 후보명만 준다)
  - 같은 사람이 회차마다 다른 위치에 있다 (이회창: 1997·2002 한나라당 → 2007 무소속)
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from votelink.contract.enums import Camp

LINEAGE_PATH = Path("data/reference/party_lineage.yaml")

_lock = threading.Lock()
_cache: dict[tuple[str, str], CandidateCamp] | None = None


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
    source: str | None = None


def load_lineage(
    path: Path | None = None, *, force: bool = False
) -> dict[tuple[str, str], CandidateCamp]:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        target = path or LINEAGE_PATH
        if not target.exists():
            raise FileNotFoundError(f"진영 매핑 파일이 없다: {target}")
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        entries = [CandidateCamp.model_validate(c) for c in raw.get("candidates", [])]

        table: dict[tuple[str, str], CandidateCamp] = {}
        for entry in entries:
            key = (entry.election, entry.candidate)
            if key in table:
                raise ValueError(
                    f"같은 (선거, 후보)가 두 번 있다: {key}. "
                    "동명이인이면 party_lineage.yaml 에서 구분할 방법을 정해야 한다"
                )
            table[key] = entry
        _cache = table
        return _cache


def reset_cache() -> None:
    """테스트용."""
    global _cache
    with _lock:
        _cache = None


def camp_of(election_id: str, candidate: str, path: Path | None = None) -> Camp:
    """이 선거의 이 후보가 어느 진영인가. 매핑에 없으면 CampNotFound."""
    table = load_lineage(path)
    entry = table.get((election_id, candidate))
    if entry is None:
        raise CampNotFound(
            f"진영 매핑에 없는 후보다: {election_id} / {candidate}. "
            "data/reference/party_lineage.yaml 에 추가하라 "
            "(추측으로 other 처리하지 않는다)"
        )
    return entry.camp
