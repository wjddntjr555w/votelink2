"""저장 레이아웃.

data/raw/       fetch 원본. **불변.** 어떤 경우에도 수정·삭제하지 않는다
data/records/   계약을 통과한 공통 레코드 (JSONL)
data/rejected/  계약을 위반해 격리된 항목 (사유 포함)
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from votelink.collect.base import RawBatch, Rejected
from votelink.contract.models import KST, Record

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
RECORDS_DIR = DATA_DIR / "records"
REJECTED_DIR = DATA_DIR / "rejected"


def _day(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y-%m-%d")


# --- raw (불변) ----------------------------------------------------------------


def write_raw(batch: RawBatch, root: Path | None = None) -> Path:
    """원본을 그대로 저장한다. 이미 있으면 덮어쓰지 않는다."""
    root = root or RAW_DIR
    target = root / batch.collector_id / _day(batch.fetched_at) / batch.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        stem = target.name.removesuffix(".json.gz")
        target = target.with_name(f"{stem}.{batch.fetched_at.strftime('%H%M%S')}.json.gz")
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        fh.write(batch.model_dump_json())
    return target


def iter_raw(
    collector_id: str, since: datetime | None = None, root: Path | None = None
) -> Iterator[RawBatch]:
    """저장된 원본을 오래된 순으로 돌려준다. --reparse 가 쓴다."""
    base = (root or RAW_DIR) / collector_id
    if not base.exists():
        return
    for path in sorted(base.rglob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            batch = RawBatch.model_validate_json(fh.read())
        if since is None or batch.fetched_at >= since:
            yield batch


# --- records -------------------------------------------------------------------


def append_records(collector_id: str, records: list[Record], root: Path | None = None) -> Path:
    target = (root or RECORDS_DIR) / f"{collector_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.model_dump_json() + "\n")
    return target


def existing_record_ids(collector_id: str, root: Path | None = None) -> set[str]:
    """이미 저장된 record_id. 재수집 시 중복 저장을 막는다."""
    target = (root or RECORDS_DIR) / f"{collector_id}.jsonl"
    if not target.exists():
        return set()
    ids: set[str] = set()
    with target.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line)["record_id"])
    return ids


# --- rejected ------------------------------------------------------------------


def append_rejected(
    collector_id: str, items: list[Rejected], when: datetime, root: Path | None = None
) -> Path:
    target = (root or REJECTED_DIR) / collector_id / f"{_day(when)}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for item in items:
            fh.write(item.model_dump_json() + "\n")
    return target
