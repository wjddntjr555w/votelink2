"""수집기 기반 클래스와 원본 배치.

핵심 규칙: fetch 는 네트워크만, parse 는 순수 함수.
개별 항목의 계약 위반이 배치 전체를 죽이지 않도록 map_items 로 감싼다.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def slugify(value: str) -> str:
    """배치 키를 파일명으로 쓸 수 있게 만든다."""
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return (slug or "batch")[:80]


class RawBatch(BaseModel):
    """fetch 가 가져온 원본. 가공하지 않은 그대로여야 한다.

    body 는 JSON 직렬화 가능해야 한다 (dict/list/str). HTML 은 문자열로 담는다.
    """

    model_config = ConfigDict(extra="forbid")

    collector_id: str
    body: Any
    batch_key: str = "batch"
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(KST))
    source_url: str | None = None

    @property
    def filename(self) -> str:
        return f"{slugify(self.batch_key)}.json.gz"


class Rejected(BaseModel):
    """계약을 위반해 격리되는 항목. data/rejected/ 로 간다."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    raw_item: Any = None

    @property
    def short_reason(self) -> str:
        return self.reason.splitlines()[0][:200]


ParseResult = Record | Rejected


class BaseCollector(ABC):
    """수집기 기반 클래스.

    하위 클래스가 정의할 것: `id`, `fetch()`, `parse()`.
    """

    id: str

    def __init__(self, meta: CollectorMeta | None = None) -> None:
        self._meta = meta or CollectorMeta.load(self.package_dir / "meta.yaml")

    @property
    def meta(self) -> CollectorMeta:
        return self._meta

    @property
    def package_dir(self) -> Path:
        import sys

        module = sys.modules[type(self).__module__]
        return Path(module.__file__).resolve().parent

    # --- 하위 클래스 구현 ------------------------------------------------------

    @abstractmethod
    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """네트워크에서 원본을 가져온다. 파싱하지 않는다."""

    @abstractmethod
    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        """원본 -> 공통 레코드. 순수 함수. 네트워크 금지."""

    # --- 도우미 ---------------------------------------------------------------

    def map_items(
        self, items: Iterable[Any], to_record: Callable[[Any], Record]
    ) -> Iterator[ParseResult]:
        """항목마다 to_record 를 부르고, 실패한 항목만 Rejected 로 바꿔 계속 진행한다.

        이 감싸기가 없으면 100건 중 3건이 깨졌을 때 나머지 97건도 사라진다.
        """
        for item in items:
            try:
                yield to_record(item)
            except Exception as exc:  # noqa: BLE001 - 개별 항목 격리가 목적
                yield Rejected(reason=f"{type(exc).__name__}: {exc}", raw_item=item)
