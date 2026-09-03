"""수집기 기반 클래스와 원본 배치.

핵심 규칙: fetch 는 네트워크만, parse 는 순수 함수.
개별 항목의 계약 위반이 배치 전체를 죽이지 않도록 map_items 로 감싼다.
"""

from __future__ import annotations

import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record, Rejected

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


# Rejected 는 votelink.contract.models 로 옮겼다 — L2 도 격리를 쓰기 때문이다.
# 기존 import 경로(`from votelink.collect.base import Rejected`)는 그대로 동작한다.
ParseResult = Record | Rejected


class BaseCollector(ABC):
    """수집기 기반 클래스.

    하위 클래스가 정의할 것: `id`, `fetch()`, `parse()`.
    """

    id: str
    _package_dir: Path | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 수집기 폴더 경로를 **클래스가 만들어지는 시점에** 붙잡아 둔다.
        # 나중에 sys.modules 를 뒤져 찾으면, 그 사이 모듈이 지워졌을 때
        # (테스트가 정리하다 지우는 일이 있다) KeyError 로 죽는다.
        module = sys.modules.get(cls.__module__)
        file = getattr(module, "__file__", None)
        if file:
            cls._package_dir = Path(file).resolve().parent

    def __init__(
        self, meta: CollectorMeta | None = None, *, district_id: str | None = None
    ) -> None:
        self._meta = meta or CollectorMeta.load(self.package_dir / "meta.yaml")
        self.district_id = district_id
        self._config: dict[str, Any] | None = None

    @property
    def meta(self) -> CollectorMeta:
        return self._meta

    @property
    def config(self) -> dict[str, Any]:
        """이 선거구로 해석된 평평한 설정. `meta.config` 대신 이것을 읽는다.

        `district_id` 가 주어지면 그 선거구 블록이, 없으면 `default_district` 가 적용된다
        (`votelink.districtcfg`). 평평한 `meta.config` 는 그대로 통과한다.
        """
        if self._config is None:
            self._config = self._meta.resolved_config(self.district_id)
        return self._config

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    @property
    def package_dir(self) -> Path:
        if self._package_dir is None:
            raise RuntimeError(
                f"{type(self).__name__} 의 폴더 경로를 알 수 없다 "
                "(파일에서 정의된 클래스가 아니다). meta 를 직접 넘겨 만들면 필요 없다"
            )
        return self._package_dir

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
