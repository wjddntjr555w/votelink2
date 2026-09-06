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
import mmap
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


def _kind_markers(kinds: set[RecordKind]) -> tuple[str, ...]:
    """레코드 직렬화형에서 kind 가 나타나는 고정 형태.

    `Record.model_dump_json()` 은 pydantic v2 의 압축 JSON 이라 공백이 없다 →
    `"kind":"<value>"`. 이 형태는 결정적이므로 이 문자열이 없으면 그 줄(또는 파일)에
    해당 kind 레코드는 없다 — 거짓 음성이 나올 수 없다.
    """
    return tuple(f'"kind":"{k.value}"' for k in kinds)


def _file_may_contain(path: Path, markers: tuple[str, ...]) -> bool:
    """파일 전체에서 kind 마커를 한 번에 찾아 통째로 건너뛸지 정한다.

    `records/` 는 소유자별 단일 파일이고 `naver_news.jsonl` 처럼 한 kind 가 수만 줄이
    되면, kind 필터가 있어도 매 호출이 그 파일을 줄 단위로 `json.loads` 한다
    (`docs/11-storage.md §6` 이 예고한 지점). 원하는 kind 가 파일 어디에도 없으면
    mmap 부분문자열 검색 한 번으로 파일을 건너뛴다. 거짓 양성(다른 필드 값에 우연히
    같은 바이트열)이면 아래 줄 단위 경로가 정상적으로 다시 거른다.
    """
    if path.stat().st_size == 0:
        return False
    needles = [m.encode() for m in markers]
    with (
        path.open("rb") as fh,
        mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as blob,
    ):
        return any(blob.find(n) != -1 for n in needles)


def count_records(kinds: Iterable[RecordKind], *, root: Path | None = None) -> int:
    """해당 kind 레코드의 총 건수. mmap 부분문자열 카운트라 `json.loads` 를 하지 않는다.

    로더가 "전체 N건 중 M건 표시" 진단을 그리려면 코퍼스 전체 크기를 알아야 하는데,
    kind 를 geo 로 좁혀 읽으면(`iter_records(..., geo_codes=...)`) 그 분모를 잃는다.
    한 줄 = 한 레코드이므로 마커 카운트가 곧 건수다 (거짓 양성은 자유 텍스트에
    `"kind":"<value>"` 형태가 그대로 나와야 해서 사실상 0).
    """
    base = root or RECORDS_DIR
    if not base.exists():
        return 0
    needles = [m.encode() for m in _kind_markers(set(kinds))]
    total = 0
    for path in sorted(base.glob("*.jsonl")):
        blob = path.read_bytes()
        total += sum(blob.count(n) for n in needles)
    return total


def iter_records(
    kinds: Iterable[RecordKind] | None = None,
    *,
    geo_codes: Iterable[str] | None = None,
    exclude_owners: Iterable[str] = (),
    root: Path | None = None,
) -> Iterator[Record]:
    """저장된 레코드를 읽는다. 분석기의 입력 경로다.

    kinds 를 주면 그 종류만 돌려준다. **모르는 kind 와 상위 schema_version 은 조용히
    건너뛴다** (계약 §7 전방 호환) — 새 수집기가 붙어도 기존 분석기가 죽지 않는다.

    geo_codes 를 주면 `record.geo_code` 가 그 안에 드는 레코드만 돌려준다. 필터를
    호출자(로더)가 아니라 여기서 걸어야 `naver_news.jsonl`(수만 줄) 에서 관심 밖
    시군구를 `load_record` 하기 전에 부분문자열로 쳐낼 수 있다 (`docs/11-storage.md §6`).
    빈 컬렉션을 주면 아무것도 돌려주지 않는다 (원하는 geo 가 없다는 뜻).

    exclude_owners: 읽지 않을 파일(=수집기·분석기 id). 분석기가 자기 출력을 다시
    입력으로 먹는 것을 막는다.
    """
    base = root or RECORDS_DIR
    if not base.exists():
        return
    wanted = set(kinds) if kinds is not None else None
    markers = _kind_markers(wanted) if wanted is not None else None
    geo_wanted = set(geo_codes) if geo_codes is not None else None
    geo_markers = tuple(f'"geo_code":"{c}"' for c in geo_wanted) if geo_wanted is not None else None
    skip = set(exclude_owners)

    for path in sorted(base.glob("*.jsonl")):
        if path.stem in skip:
            continue
        # 원하는 kind 가 파일 어디에도 없으면 줄 단위로 열지 않는다.
        if markers is not None and not _file_may_contain(path, markers):
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                # 값비싼 json.loads 앞에 부분문자열로 한 번 거른다. 마커 형태가
                # 결정적이라 거짓 음성이 없고, 거짓 양성은 아래에서 다시 걸린다.
                if markers is not None and not any(m in line for m in markers):
                    continue
                if geo_markers is not None and not any(m in line for m in geo_markers):
                    continue
                raw = json.loads(line)
                # kind 필터를 모델 생성 앞에 둔다. 관심 없는 레코드까지 검증하면
                # 수집기가 늘어날수록 분석이 느려지고, 남의 계약 위반에 죽는다.
                if wanted is not None and raw.get("kind") not in wanted:
                    continue
                if geo_wanted is not None and raw.get("geo_code") not in geo_wanted:
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
