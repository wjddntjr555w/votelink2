"""폼 값 → 캠프 설정 모델. 검증은 **저장하기 전에** 전부 여기서 끝난다.

`load_cycle` 이 읽기 경로에서도 같은 검증을 하지만, 그때는 이미 파일이 디스크에 있다.
**관할이 틀리면 에러 없이 모든 분석이 조용히 틀리므로**(P-001 §16) 잘못된 값이 파일이
되는 일 자체를 막는다.

`app.py` 에서 뽑아냈다 — 온보딩·주기 추가·주기 수정·로스터가 전부 이 파싱을 공유하고,
넷이 각자 파싱하면 언젠가 한 곳만 고친다.
"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict

from votelink.camp.models import Candidate, Cycle, Election, Office, Roster, Territory
from votelink.contract.enums import Camp, ElectionType

CAMP_ALIASES = {
    "진보": Camp.PROGRESSIVE,
    "보수": Camp.CONSERVATIVE,
    "중도": Camp.CENTRIST,
    "기타": Camp.OTHER,
}
"""로스터를 한 줄씩 칠 때 한글로 적어도 받는다. 값은 `party_lineage.yaml` 의 4축 그대로다."""

TRUTHY = {"y", "yes", "true", "1", "현직", "o", "ㅇ"}


class CycleForm(BaseModel):
    """선거 주기 폼. `/onboarding`·`/cycles/new`·`/cycles/{id}/edit` 이 **같은 것을 받는다.**

    필드가 열 개라 라우트마다 늘어놓으면 언젠가 한쪽만 고친다. 첫 주기와 두 번째
    주기와 고친 주기가 다른 값을 받을 이유가 없다 — 관할도 진영도 당적도 주기마다
    다시 정한다 (P-001 §7).

    `extra="ignore"` 다. 계약 모델들이 `forbid` 인 것과 다른데, 여기는 레코드가 아니라
    브라우저 폼이라서다 — 제출 버튼 이름 하나가 딸려 와도 422 로 죽는 대신 무시한다.
    """

    model_config = ConfigDict(extra="ignore")

    election_type: str
    office: str
    lineage: str
    party: str = ""
    """우리 후보의 정당. **주기를 만들 때만 쓴다** — 수정 화면에는 없다.

    당적은 로스터(`candidates.yaml`)에 살고, 같은 값을 주기 폼과 로스터 폼 두 곳에서
    받으면 어긋난다. 만들 때만 여기서 받는 이유는 그때 로스터도 함께 생기기 때문이다.
    """

    election_date: str = ""
    incumbent: str = ""
    preset: str = ""
    sigungu: str = ""
    emd_pick: list[str] = []
    """동 이름 체크박스(shuttle 위젯)로 고른 행정동코드. 반복 폼 키로 들어온다.

    `emd_codes` textarea 와 **합쳐진다** — `resolve_territory` 가 프리셋·자치구·직접입력을
    이미 합치므로 넷째 입력 하나가 늘 뿐이다 (P-004). JS 가 죽으면 이 필드는 비고
    textarea 만 남는다.
    """
    emd_codes: str = ""
    legal_reviewer: str = ""


class RosterForm(BaseModel):
    """후보 로스터 폼.

    상대 후보를 **한 줄에 한 명**으로 받는다. 명수가 정해지지 않은 목록을 JS 없이 받는
    가장 단순한 방법이고, 선관위 후보자 명부에서 복사해 붙이기도 쉽다. 관할 행정동
    코드를 textarea 로 받는 것과 같은 결이다.
    """

    model_config = ConfigDict(extra="ignore")

    ours_name: str
    ours_party: str
    ours_lineage: str
    ours_incumbent: str = ""
    opponents: str = ""


def build_cycle(settings, form: dict) -> Cycle:
    """폼 → `Cycle`. 저장하기 **전에** 전부 검증한다."""
    from votelink.camp import known_emd_codes
    from votelink.camp.scaffold import resolve_territory

    raw_date = (form.get("election_date") or "").strip()
    try:
        election_date = dt.date.fromisoformat(raw_date) if raw_date else None
    except ValueError as exc:
        raise ValueError(f"선거일은 YYYY-MM-DD 형식이어야 한다: '{raw_date}'") from exc

    # 동 이름 체크박스(shuttle)로 고른 것 + textarea 직접입력을 합친다. 순서는
    # 상관없다 — resolve_territory 가 중복을 제거한다.
    # 줄바꿈·쉼표·공백 아무거나 구분자로 받는다. 사람이 표에서 복사해 붙인다.
    picked = [c.strip() for c in (form.get("emd_pick") or []) if c and c.strip()]
    typed = [c for c in re.split(r"[\s,]+", form.get("emd_codes") or "") if c]
    codes = picked + typed
    preset_label, resolved = resolve_territory(
        (form.get("preset") or "").strip() or None,
        (form.get("sigungu") or "").strip() or None,
        codes,
        settings.districts_path,
    )
    unknown = sorted(set(resolved) - known_emd_codes(settings.districts_path))
    if unknown:
        raise ValueError(
            f"districts.yaml 이 모르는 행정동코드다: {', '.join(unknown)}. "
            "`uv run votelink district list --emd` 로 대조하라"
        )

    return Cycle(
        election=Election(
            type=ElectionType(form["election_type"]),
            office=Office(form["office"]),
            date=election_date,
        ),
        lineage=Camp(form["lineage"]),
        territory=Territory(preset=preset_label, emd_codes=resolved),
        legal_reviewer=(form.get("legal_reviewer") or "").strip() or None,
    )


def _lineage(value: str, *, where: str) -> Camp:
    text = (value or "").strip()
    if text in CAMP_ALIASES:
        return CAMP_ALIASES[text]
    try:
        return Camp(text)
    except ValueError as exc:
        allowed = ", ".join(f"{ko}({en.value})" for ko, en in CAMP_ALIASES.items())
        raise ValueError(f"{where}: 모르는 진영이다 — {text}. 쓸 수 있는 값: {allowed}") from exc


def parse_roster(form: RosterForm) -> Roster:
    """폼 → `Roster`.

    상대 한 줄의 형식: `이름 | 정당 | 진영 | 현직 | 비고`
    뒤 둘은 생략할 수 있다. 빈 줄과 `#` 로 시작하는 줄은 건너뛴다.

    **미기입을 `other` 로 자동 강등하지 않는다.** 진영을 못 읽으면 그 줄에서 멈춘다 —
    `party_lineage.yaml` 이 "매핑에 없는 후보는 격리된다"고 못박은 것과 같은 이유로,
    조용히 other 로 떨어뜨리면 '분류 누락'과 '실제 군소후보'를 구분할 수 없게 된다.
    """
    opponents: list[Candidate] = []
    for lineno, raw in enumerate((form.opponents or "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        where = f"상대 후보 {lineno}번째 줄"
        if len(parts) < 3:
            raise ValueError(f"{where}: `이름 | 정당 | 진영` 까지는 있어야 한다. 받은 것: '{line}'")
        name, party, lineage = parts[0], parts[1], parts[2]
        if not name or not party:
            raise ValueError(f"{where}: 이름과 정당이 비었다. 받은 것: '{line}'")
        opponents.append(
            Candidate(
                name=name,
                party=party,
                lineage=_lineage(lineage, where=where),
                incumbent=len(parts) > 3 and parts[3].lower() in TRUTHY,
                note=(parts[4] or None) if len(parts) > 4 else None,
            )
        )

    return Roster(
        ours=Candidate(
            name=form.ours_name.strip(),
            party=form.ours_party.strip(),
            lineage=_lineage(form.ours_lineage, where="우리 후보"),
            incumbent=bool(form.ours_incumbent),
        ),
        opponents=opponents,
    )


def roster_text(roster: Roster) -> str:
    """`Roster` → 상대 후보 textarea 의 내용. 폼을 다시 열 때 쓴다."""
    lines = []
    for o in roster.opponents:
        parts = [o.name, o.party, o.lineage.value, "현직" if o.incumbent else ""]
        if o.note:
            parts.append(o.note)
        while parts and not parts[-1]:
            parts.pop()
        lines.append(" | ".join(parts))
    return "\n".join(lines)
