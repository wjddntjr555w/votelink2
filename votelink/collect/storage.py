"""수집 원본(raw)의 저장 레이아웃.

`<space>/raw/`  fetch 원본. **불변.** 어떤 경우에도 수정·삭제하지 않는다

레코드·격리 입출력(`records/`, `rejected/`)은 L1·L2 공용이라 `votelink/store.py` 로
옮겼다. 기존 import 경로가 깨지지 않도록 여기서 재수출한다.

경로는 모듈 상수가 아니라 `DataSpace` 값이다 (`docs/proposals/P-001` §10).
"""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from votelink.collect.base import RawBatch
from votelink.store import (
    DATA_DIR,
    DataSpace,
    append_records,
    append_rejected,
    day,
    existing_record_ids,
)

__all__ = [
    "DATA_DIR",
    "DataSpace",
    "append_records",
    "append_rejected",
    "existing_record_ids",
    "iter_raw",
    "write_raw",
]


# --- raw (불변) ----------------------------------------------------------------


def write_raw(batch: RawBatch, space: DataSpace) -> Path:
    """원본을 그대로 저장한다. 이미 있으면 덮어쓰지 않는다."""
    target = space.raw / batch.collector_id / day(batch.fetched_at) / batch.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem = target.name.removesuffix(".json.gz")
        target = target.with_name(f"{stem}.{batch.fetched_at.strftime('%H%M%S')}.json.gz")
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        fh.write(batch.model_dump_json())
    return target


def iter_raw(
    collector_id: str, space: DataSpace, since: datetime | None = None
) -> Iterator[RawBatch]:
    """저장된 원본을 오래된 순으로 돌려준다. --reparse 가 쓴다."""
    base = space.raw / collector_id
    if not base.exists():
        return
    for path in sorted(base.rglob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            batch = RawBatch.model_validate_json(fh.read())
        if since is None or batch.fetched_at >= since:
            yield batch


# records / rejected 는 votelink.store 에 있다 (위 재수출 참조).
