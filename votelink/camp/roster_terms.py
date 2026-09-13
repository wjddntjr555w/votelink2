"""district → 그 district 를 관할하는 캠프들의 로스터.

제안서: `docs/proposals/P-006-camp-aware-news-collection.md`.

**캠프별로 뉴스를 쪼개 수집하지 않는다** (`P-001-camp-data-isolation.md` §5).
이 모듈은 district 단위 공용 수집이 fetch 시점에 참고할 "이 district 를 관할하는
모든 캠프의 로스터 합집합"만 계산한다 — 수집 자체는 여전히 district 하나당 1회다.

로딩에 실패한 캠프(깨진 yaml·관할 검증 실패)는 조용히 건너뛴다. `current_cycle_id` 가
이미 쓰는 fail-soft 패턴과 같다 — 캠프 하나의 설정 오류가 다른 모든 district 의 뉴스
수집을 막으면 안 된다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import ValidationError

from votelink.camp.loader import (
    CampConfigError,
    CampNotFound,
    CycleNotFound,
    current_cycle_id,
    list_camps,
    load_cycle,
    load_roster,
)
from votelink.camp.models import Candidate, Roster
from votelink.reference.districts import resolve_district

_LOAD_ERRORS = (CampNotFound, CycleNotFound, CampConfigError, FileNotFoundError, ValidationError)


def camps_covering_district(
    district_id: str,
    *,
    camps_root: Path | None = None,
    districts_path: Path | None = None,
) -> list[Roster]:
    """이 district 와 관할이 겹치는 모든 캠프의 **현재 주기** 로스터.

    `covers_district`(`votelink/web/auth.py`)와 같은 규칙(emd 교집합)으로 판정한다 —
    다른 규칙을 쓰면 화면의 관할 판정과 뉴스 수집의 관할 판정이 어긋난다.
    """
    district = resolve_district(district_id, districts_path)
    target_emd = set(district.emd_codes)

    rosters: list[Roster] = []
    for camp_id in list_camps(camps_root):
        cycle_id = current_cycle_id(camp_id, camps_root, districts_path=districts_path)
        if cycle_id is None:
            continue
        try:
            cycle = load_cycle(camp_id, cycle_id, camps_root, districts_path=districts_path)
            if not (target_emd & set(cycle.territory.emd_codes)):
                continue
            rosters.append(load_roster(camp_id, cycle_id, camps_root))
        except _LOAD_ERRORS:
            continue
    return rosters


def _all_candidates(rosters: list[Roster]) -> list[Candidate]:
    seen: dict[str, Candidate] = {}
    for roster in rosters:
        for candidate in (roster.ours, *roster.opponents):
            seen.setdefault(candidate.name, candidate)
    return sorted(seen.values(), key=lambda c: c.name)


def person_terms_for_district(district_id: str, **kwargs) -> list[str]:
    """이 district 를 관할하는 캠프들의 ours+opponents 이름 합집합(정렬)."""
    rosters = camps_covering_district(district_id, **kwargs)
    return [c.name for c in _all_candidates(rosters)]


def candidate_slug(name: str) -> str:
    """검색어 id 로 쓸 결정적 ascii 슬러그. raw 파일명이 되므로 한글은 못 쓴다."""
    return f"cand-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:8]}"


def candidate_queries_for_district(district_id: str, **kwargs) -> list[dict[str, str]]:
    """`{id, q}` 목록. q 는 "이름 정당" — 정당을 한정어로 붙여 동명이인 노이즈를 줄인다.

    이름 단독 쿼리는 만들지 않는다 — 흔한 이름에서 노이즈가 개선 목적을 무력화한다.
    """
    rosters = camps_covering_district(district_id, **kwargs)
    return [
        {"id": candidate_slug(c.name), "q": f"{c.name} {c.party}"} for c in _all_candidates(rosters)
    ]
