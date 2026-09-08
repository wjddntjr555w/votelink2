"""캠프 전용 공간 — 후보 신원·관할·진영·상대 로스터.

제안서: `docs/proposals/P-001-camp-data-isolation.md`.

공용 데이터는 진영 단위로 중립 계산하고, 여기 있는 **렌즈**(`Cycle.lineage`)가
그것을 "우리 / 상대"로 번역한다. 데이터를 캠프마다 복제하지 않는 이유가 이것이다.
"""

from votelink.camp.loader import (
    CampConfigError,
    CampNotFound,
    CycleNotFound,
    camp_dir,
    camps_dir,
    cycle_dir,
    cycle_id_for,
    list_camps,
    list_cycles,
    load_camp,
    load_cycle,
    load_roster,
    space_for,
)
from votelink.camp.models import (
    CampInfo,
    Candidate,
    Cycle,
    Election,
    Office,
    Roster,
    Territory,
)

__all__ = [
    "CampConfigError",
    "CampInfo",
    "CampNotFound",
    "Candidate",
    "Cycle",
    "CycleNotFound",
    "Election",
    "Office",
    "Roster",
    "Territory",
    "camp_dir",
    "camps_dir",
    "cycle_dir",
    "cycle_id_for",
    "list_camps",
    "list_cycles",
    "load_camp",
    "load_cycle",
    "load_roster",
    "space_for",
]
