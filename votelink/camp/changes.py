"""주기 설정을 고치면 무엇이 달라지는가.

제안서: `docs/proposals/P-001-camp-data-isolation.md` §7·§16.

**이 모듈이 있는 이유는 하나다.** P-001 §16 이 가장 위험한 실패로 지목한 것이
"관할 입력이 틀리면 모든 분석이 조용히 틀린다"이다 — 틀린 관할은 에러를 내지 않고
그냥 다른 답을 준다. 수정을 열어주려면 **저장 전에 무엇이 달라지는지 보여주고
확인받는 절차**가 함께 있어야 한다. 그 계산이 여기 있다.

순수 계산이다. 파일을 쓰지 않고 화면도 모른다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from votelink.camp.models import Cycle, Office
from votelink.camp.scaffold import cycle_id_or_undated
from votelink.contract.enums import Camp, ElectionType
from votelink.reference.districts import load_districts


@dataclass(frozen=True)
class Emd:
    """행정동 하나. 코드만 보여주면 사람이 무엇이 빠지는지 알 수 없다."""

    code: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})" if self.name else self.code


@dataclass(frozen=True)
class CycleChange:
    """수정 전후의 차이. 화면이 이것을 그대로 그린다."""

    cycle_id_before: str
    cycle_id_after: str

    date_before: dt.date | None = None
    date_after: dt.date | None = None
    type_before: ElectionType | None = None
    type_after: ElectionType | None = None
    office_before: Office | None = None
    office_after: Office | None = None
    lineage_before: Camp | None = None
    lineage_after: Camp | None = None
    reviewer_before: str | None = None
    reviewer_after: str | None = None

    added: list[Emd] = field(default_factory=list)
    removed: list[Emd] = field(default_factory=list)
    kept: int = 0

    opened: list[tuple[str, str]] = field(default_factory=list)
    """이 수정으로 **열리게 되는** 선거구 (id, 이름). 지금은 403 이고 저장 후 열린다."""

    closed: list[tuple[str, str]] = field(default_factory=list)
    """이 수정으로 **닫히게 되는** 선거구. 지금 보고 있는 화면이 사라질 수 있다."""

    @property
    def moved(self) -> bool:
        """폴더가 옮겨지는가. 선거일이나 계열이 바뀌면 `cycle_id` 가 파생값이라 바뀐다."""
        return self.cycle_id_before != self.cycle_id_after

    @property
    def lineage_flipped(self) -> bool:
        """진영이 바뀌는가. **화면의 우세·열세가 통째로 뒤집힌다.**"""
        return self.lineage_before is not self.lineage_after

    @property
    def territory_changed(self) -> bool:
        return bool(self.added or self.removed)

    @property
    def is_empty(self) -> bool:
        """바뀌는 것이 하나도 없다. 확인을 물을 이유가 없다."""
        return not (
            self.moved
            or self.lineage_flipped
            or self.territory_changed
            or self.office_before is not self.office_after
            or (self.reviewer_before or None) != (self.reviewer_after or None)
        )


def diff_cycle(before: Cycle, after: Cycle, cycle_id: str, districts_path=None) -> CycleChange:
    """수정 전후의 차이를 센다.

    선거구 열림·닫힘은 `covers_district` 와 **같은 규칙**으로 판정한다 — 관할과 선거구는
    포함 관계가 아니라 교집합이 비었는지로만 갈린다 (P-001 §6). 여기서 다른 규칙을 쓰면
    미리보기가 실제 동작과 어긋나고, 그건 확인 절차를 거짓말로 만든다.
    """
    table = load_districts(districts_path)
    names = {e.code: e.name for d in table.values() for e in d.emd if e.code}

    old_codes = set(before.territory.emd_codes)
    new_codes = set(after.territory.emd_codes)

    def emds(codes: set[str]) -> list[Emd]:
        return [Emd(code=c, name=names.get(c, "")) for c in sorted(codes)]

    opened, closed = [], []
    for d in table.values():
        d_codes = set(d.emd_codes)
        was = bool(old_codes & d_codes)
        now = bool(new_codes & d_codes)
        if now and not was:
            opened.append((d.id, d.name))
        elif was and not now:
            closed.append((d.id, d.name))

    return CycleChange(
        cycle_id_before=cycle_id,
        cycle_id_after=cycle_id_or_undated(after),
        date_before=before.election.date,
        date_after=after.election.date,
        type_before=before.election.type,
        type_after=after.election.type,
        office_before=before.election.office,
        office_after=after.election.office,
        lineage_before=before.lineage,
        lineage_after=after.lineage,
        reviewer_before=before.legal_reviewer,
        reviewer_after=after.legal_reviewer,
        added=emds(new_codes - old_codes),
        removed=emds(old_codes - new_codes),
        kept=len(old_codes & new_codes),
        opened=opened,
        closed=closed,
    )
