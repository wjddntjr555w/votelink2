"""분석기 기반 클래스.

수집기와 **의도적으로 대칭**이다. 구조가 같으면 새로 배울 게 없다.

    L1  fetch()  네트워크만  →  parse()   순수 함수
    L2  load()   디스크만    →  compute() 순수 함수

핵심 규칙: `compute` 는 순수 함수다. 네트워크 금지, LLM 금지, 난수 금지, 시계 금지.
같은 입력이면 언제 돌려도 같은 결과가 나와야 한다. 이게 깨지면 `derived_from` 으로
근거를 역추적해도 그 근거가 그 결론을 낳았는지 확인할 수 없다.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from votelink import store
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.models import Record, Rejected

ComputeResult = Record | Rejected


class BaseAnalyzer(ABC):
    """분석기 기반 클래스.

    하위 클래스가 정의할 것: `id`, `compute()`. `load()` 는 기본 구현으로 충분한 경우가
    많다 (meta.inputs 에 적힌 kind 를 전부 읽어온다).
    """

    id: str
    _package_dir: Path | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 폴더 경로를 클래스 생성 시점에 붙잡는다. 나중에 sys.modules 를 뒤지면
        # 그 사이 모듈이 지워졌을 때 KeyError 로 죽는다 (수집기에서 겪은 결함이다).
        module = sys.modules.get(cls.__module__)
        file = getattr(module, "__file__", None)
        if file:
            cls._package_dir = Path(file).resolve().parent

    def __init__(self, meta: AnalyzerMeta | None = None) -> None:
        self._meta = meta or AnalyzerMeta.load(self.package_dir / "meta.yaml")

    @property
    def meta(self) -> AnalyzerMeta:
        return self._meta

    @property
    def package_dir(self) -> Path:
        if self._package_dir is None:
            raise RuntimeError(
                f"{type(self).__name__} 의 폴더 경로를 알 수 없다 "
                "(파일에서 정의된 클래스가 아니다). meta 를 직접 넘겨 만들면 필요 없다"
            )
        return self._package_dir

    # --- load -----------------------------------------------------------------

    def load(self) -> list[Record]:
        """입력 레코드를 읽는다. **디스크만 본다. 네트워크 금지.**

        자기 출력 파일은 제외한다 — 분석기가 자기 결론을 입력으로 다시 먹으면
        재실행할 때마다 결과가 흘러간다.
        """
        return store.load_records(self.meta.inputs, exclude_owners=[self.id])

    # --- compute --------------------------------------------------------------

    @abstractmethod
    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        """입력 레코드 -> 파생 레코드. 순수 함수.

        만드는 Record 에는 반드시 `derived_from` 을 채운다. 근거를 못 대는 결론은
        이 프로젝트에서 실패로 간주한다.
        """

    # --- 도우미 ----------------------------------------------------------------

    def map_items(
        self, items: Iterable[Any], to_record: Callable[[Any], Record]
    ) -> Iterator[ComputeResult]:
        """항목마다 to_record 를 부르고, 실패한 항목만 Rejected 로 바꿔 계속 진행한다.

        9개 동 중 1개가 깨졌을 때 나머지 8개까지 사라지지 않게 한다.
        """
        for item in items:
            try:
                yield to_record(item)
            except Exception as exc:  # noqa: BLE001 - 개별 항목 격리가 목적
                yield Rejected(reason=f"{type(exc).__name__}: {exc}", raw_item=item)


class AnalyzeError(Exception):
    """분석을 계속할 수 없는 상태 (입력 없음, 참조 데이터 결손 등)."""
