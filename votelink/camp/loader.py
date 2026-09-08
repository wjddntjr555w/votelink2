"""캠프 설정을 디스크에서 읽는다.

제안서: `docs/proposals/P-001-camp-data-isolation.md` §7·§9.

```
data/camps/<camp_id>/camp.yaml
data/camps/<camp_id>/cycles/<cycle_id>/election.yaml
                                       candidates.yaml
                                       records/ · rejected/ · incoming/
```

**모듈 전역 캐시를 두지 않는다.** `districts.py` 는 파일 하나를 전역에 캐시하지만
캠프는 그러면 안 된다 — 전역은 요청별 상태를 담을 수 없어서 캠프 A 와 B 의 동시
요청이 같은 슬롯을 두고 경쟁한다 (P-001 §10). 읽을 때마다 경로에서 읽는다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from votelink.camp.models import CampInfo, Cycle, Roster
from votelink.reference.districts import load_districts
from votelink.store import DATA_DIR, SHARED_DIR, DataSpace


class CampNotFound(LookupError):
    """알 수 없는 캠프. 오타이거나 아직 만들어지지 않았다."""


class CycleNotFound(LookupError):
    """그 캠프에 그 선거 주기가 없다."""


class CampConfigError(ValueError):
    """캠프 설정이 스스로 모순된다. 조용히 넘어가면 분석이 통째로 틀린다."""


def camps_dir(root: Path | None = None) -> Path:
    """캠프 공간의 뿌리. `data/shared/` 와 형제다."""
    return (root or DATA_DIR) / "camps"


def camp_dir(camp_id: str, root: Path | None = None) -> Path:
    return camps_dir(root) / camp_id


def cycle_dir(camp_id: str, cycle_id: str, root: Path | None = None) -> Path:
    return camp_dir(camp_id, root) / "cycles" / cycle_id


def space_for(camp_id: str, cycle_id: str, root: Path | None = None) -> DataSpace:
    """이 캠프 주기의 데이터 공간.

    공용 코퍼스는 읽기 전용으로 함께 들고, 캠프 스코프 산출물은 주기 폴더에 쓴다.
    `records/`·`rejected/` 규약이 `shared/` 와 같아서 `store.py` 가 루트만 바꿔
    그대로 재사용된다 (P-001 §9).
    """
    return DataSpace(SHARED_DIR, camp_root=cycle_dir(camp_id, cycle_id, root))


def list_camps(root: Path | None = None) -> list[str]:
    base = camps_dir(root)
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "camp.yaml").exists())


def list_cycles(camp_id: str, root: Path | None = None) -> list[str]:
    base = camp_dir(camp_id, root) / "cycles"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "election.yaml").exists())


def _read_yaml(path: Path, what: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{what} 이 없다: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_camp(camp_id: str, root: Path | None = None) -> CampInfo:
    path = camp_dir(camp_id, root) / "camp.yaml"
    if not path.exists():
        known = ", ".join(list_camps(root)) or "(없음)"
        raise CampNotFound(f"캠프 '{camp_id}' 를 찾을 수 없다. 있는 것: {known}")
    info = CampInfo.model_validate(_read_yaml(path, "camp.yaml"))
    if info.camp_id != camp_id:
        raise CampConfigError(
            f"{path}: camp_id 가 '{info.camp_id}' 인데 폴더 이름은 '{camp_id}' 다. "
            "폴더를 옮겼거나 파일을 복사한 뒤 안을 고치지 않았다"
        )
    return info


def load_cycle(
    camp_id: str,
    cycle_id: str,
    root: Path | None = None,
    *,
    districts_path: Path | None = None,
) -> Cycle:
    """주기 설정을 읽고 **관할이 실재하는지까지 확인한다.**

    관할 검증을 읽기 경로에 두는 이유: 온보딩 CLI 에만 두면 `election.yaml` 을 손으로
    고친 경우를 못 잡는다. P-001 §16 이 "관할 입력이 틀리면 모든 분석이 조용히
    틀린다"를 가장 위험한 실패 방식으로 지목했다 — 틀린 관할은 에러를 내지 않고
    그냥 다른 답을 준다.
    """
    path = cycle_dir(camp_id, cycle_id, root) / "election.yaml"
    if not path.exists():
        known = ", ".join(list_cycles(camp_id, root)) or "(없음)"
        raise CycleNotFound(f"캠프 '{camp_id}' 에 주기 '{cycle_id}' 가 없다. 있는 것: {known}")

    cycle = Cycle.model_validate(_read_yaml(path, "election.yaml"))

    expected = cycle_id_for(cycle)
    if expected is not None and cycle_id != expected:
        raise CampConfigError(
            f"{path}: 폴더 이름 '{cycle_id}' 가 선거일·계열에서 나온 '{expected}' 와 다르다. "
            "날짜를 고쳤으면 폴더도 함께 옮겨야 한다 — 둘이 어긋나면 어느 쪽이 진실인지 알 수 없다"
        )

    unknown = sorted(set(cycle.territory.emd_codes) - known_emd_codes(districts_path))
    if unknown:
        raise CampConfigError(
            f"{path}: districts.yaml 에 없는 행정동코드가 관할에 있다: {unknown}. "
            "오타이거나 D-001 백필이 아직 그 지역을 채우지 않았다 — "
            "`uv run votelink district list --emd` 로 확인하라"
        )
    return cycle


def load_roster(camp_id: str, cycle_id: str, root: Path | None = None) -> Roster:
    path = cycle_dir(camp_id, cycle_id, root) / "candidates.yaml"
    return Roster.model_validate(_read_yaml(path, "candidates.yaml"))


def cycle_id_for(cycle: Cycle) -> str | None:
    """선거일 + 계열. 선거일을 모르면 유도할 수 없다 (`None`).

    그 경우 폴더 이름이 곧 주기의 정체성이고, 사람이 직접 정한다.
    """
    if cycle.election.date is None:
        return None
    return f"{cycle.election.date.isoformat()}-{cycle.election.type.value}"


def known_emd_codes(districts_path: Path | None = None) -> set[str]:
    """districts.yaml 이 아는 모든 행정동코드.

    선거구 단위가 아니라 합집합인 이유: 캠프 관할은 선거구와 일치하지 않는다.
    구청장은 국회의원 선거구 셋을 아우르고, 기초의원 선거구는 아예 없다 (P-001 §6).

    공개 함수인 이유는 **쓰기 전에 막기 위해서다.** 읽기 경로의 검증(`load_cycle`)은
    손으로 고친 파일까지 잡아주지만, 웹 온보딩 폼은 저장하기 **전에** 같은 검증을
    해야 한다 — 관할이 틀리면 에러 없이 모든 분석이 조용히 틀린다 (P-001 §16).
    """
    return {c for d in load_districts(districts_path).values() for c in d.emd_codes}
