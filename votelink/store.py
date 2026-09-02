"""저장된 공통 레코드를 읽고 쓴다. **L1·L2 공용.**

`docs/00-overview.md §3`: L1과 L2는 서로의 코드를 모른다. 오직 공통 레코드 계약으로만
연결된다. 그래서 레코드 입출력은 어느 한쪽 계층에 속하지 않고 여기 있다 —
`votelink/collect/storage.py` 는 raw(수집 원본) 전용으로 남고 이 함수들을 재수출한다.

```
data/records/   계약을 통과한 공통 레코드 (JSONL). 원천도 파생도 같은 형식
data/rejected/  계약을 위반해 격리된 항목 (사유 포함)
```
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from votelink.contract.enums import RecordKind
from votelink.contract.models import KST, Record, Rejected, load_record

log = logging.getLogger(__name__)

DATA_DIR = Path("data")
RECORDS_DIR = DATA_DIR / "records"
REJECTED_DIR = DATA_DIR / "rejected"


def _day(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d")


# --- 쓰기 -----------------------------------------------------------------------


def append_records(owner_id: str, records: list[Record], root: Path | None = None) -> Path:
    """`data/records/<owner_id>.jsonl` 에 덧붙인다.

    owner_id 는 수집기 id 이거나 분석기 id 다. 파생 레코드도 원천과 같은 계약을
    쓰므로 파일 형식이 같다.
    """
    target = (root or RECORDS_DIR) / f"{owner_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.model_dump_json() + "\n")
    return target


def existing_record_ids(owner_id: str, root: Path | None = None) -> set[str]:
    """이미 저장된 record_id. 재실행 시 중복 저장을 막는다."""
    target = (root or RECORDS_DIR) / f"{owner_id}.jsonl"
    if not target.exists():
        return set()
    ids: set[str] = set()
    with target.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line)["record_id"])
    return ids


def upsert_records(
    owner_id: str, records: list[Record], root: Path | None = None
) -> tuple[int, int]:
    """같은 `record_id` 는 새 값으로 교체하고 나머지 줄은 보존한다. (교체수, 신규수).

    **분석기용이다.** 수집기는 원본이 불변이라 append 로 충분하지만, 분석 결과는
    로직이나 참조 데이터(`party_lineage.yaml` 등)를 고치면 같은 키에서 다른 값이
    나온다. append 만 하면 그 갱신이 '중복'으로 조용히 버려져서, 매핑을 고치고
    재실행해도 산출물이 그대로인 상태가 된다.

    다른 `as_of` 의 과거 분석은 record_id 가 다르므로 그대로 남는다.
    """
    target = (root or RECORDS_DIR) / f"{owner_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)

    incoming = {r.record_id: r for r in records}
    kept: list[str] = []
    replaced = 0
    if target.exists():
        with target.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                if json.loads(line)["record_id"] in incoming:
                    replaced += 1
                    continue  # 새 값으로 갈아끼운다
                kept.append(line.rstrip("\n"))

    tmp = target.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for line in kept:
            fh.write(line + "\n")
        for record in records:
            fh.write(record.model_dump_json() + "\n")
    tmp.replace(target)  # 원자적 교체. 중간에 죽어도 반쪽 파일이 남지 않는다

    return replaced, len(records) - replaced


def append_rejected(
    owner_id: str, items: list[Rejected], when: datetime, root: Path | None = None
) -> Path:
    target = (root or REJECTED_DIR) / owner_id / f"{_day(when)}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for item in items:
            fh.write(item.model_dump_json() + "\n")
    return target


# --- 읽기 -----------------------------------------------------------------------


def iter_records(
    kinds: Iterable[RecordKind] | None = None,
    *,
    exclude_owners: Iterable[str] = (),
    root: Path | None = None,
) -> Iterator[Record]:
    """저장된 레코드를 읽는다. 분석기의 입력 경로다.

    kinds 를 주면 그 종류만 돌려준다. **모르는 kind 와 상위 schema_version 은 조용히
    건너뛴다** (계약 §7 전방 호환) — 새 수집기가 붙어도 기존 분석기가 죽지 않는다.

    exclude_owners: 읽지 않을 파일(=수집기·분석기 id). 분석기가 자기 출력을 다시
    입력으로 먹는 것을 막는다.
    """
    base = root or RECORDS_DIR
    if not base.exists():
        return
    wanted = set(kinds) if kinds is not None else None
    skip = set(exclude_owners)

    for path in sorted(base.glob("*.jsonl")):
        if path.stem in skip:
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                # kind 필터를 모델 생성 앞에 둔다. 관심 없는 레코드까지 검증하면
                # 수집기가 늘어날수록 분석이 느려지고, 남의 계약 위반에 죽는다.
                if wanted is not None and raw.get("kind") not in wanted:
                    continue
                record = load_record(raw)
                if record is None:
                    continue
                yield record


def load_records(
    kinds: Iterable[RecordKind] | None = None,
    *,
    exclude_owners: Iterable[str] = (),
    root: Path | None = None,
) -> list[Record]:
    """iter_records 의 리스트 판. 분석기는 보통 전량을 메모리에 올린다
    (읍면동 단위 집계라 규모가 작다)."""
    return list(iter_records(kinds, exclude_owners=exclude_owners, root=root))
