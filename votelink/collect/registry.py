"""수집기 등록부.

collectors/<id>/meta.yaml 들을 모아 collectors/registry.yaml 을 만든다.
전체 목록이 필요할 때 폴더 20개를 뒤지지 않고 이 파일 하나만 읽으면 된다.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import yaml

from votelink.collect.base import BaseCollector
from votelink.collect.meta import CollectorMeta

COLLECTORS_DIR = Path("collectors")
REGISTRY_PATH = COLLECTORS_DIR / "registry.yaml"


def discover(root: Path = COLLECTORS_DIR) -> dict[str, CollectorMeta]:
    """meta.yaml 을 가진 하위 폴더를 전부 찾는다."""
    found: dict[str, CollectorMeta] = {}
    if not root.exists():
        return found
    for meta_path in sorted(root.glob("*/meta.yaml")):
        meta = CollectorMeta.load(meta_path)
        found[meta.id] = meta
    return found


def sync(root: Path = COLLECTORS_DIR, out: Path | None = None) -> Path:
    """registry.yaml 재생성. 손으로 수정하지 않는다."""
    metas = discover(root)
    target = out or (root / "registry.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "generated_by": "votelink registry sync",
        "count": len(metas),
        "collectors": [
            {
                "id": m.id,
                "name": m.name,
                "kinds": [str(k) for k in m.kinds],
                "source_name": m.source_name,
                "access": str(m.access),
                "schedule": m.schedule,
                "geo_level": str(m.geo_level),
                "verified": m.verified,
                "requires_secrets": m.requires_secrets,
            }
            for m in metas.values()
        ],
    }
    target.write_text(
        "# 자동 생성물. 손으로 고치지 말 것. `uv run votelink registry sync`\n"
        + yaml.safe_dump(body, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target


def load(collector_id: str, root: Path = COLLECTORS_DIR) -> BaseCollector:
    """collectors/<id>/collector.py 의 Collector 클래스를 불러 인스턴스로 만든다."""
    metas = discover(root)
    if collector_id not in metas:
        known = ", ".join(sorted(metas)) or "(없음)"
        raise KeyError(f"수집기 '{collector_id}' 를 찾을 수 없다. 등록된 것: {known}")

    # collectors/ 는 프로젝트 루트 기준 패키지다. 콘솔 스크립트로 실행하면
    # 작업 디렉터리가 sys.path 에 없을 수 있어 직접 넣어준다.
    parent = str(root.resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module = importlib.import_module(f"{root.name}.{collector_id}.collector")
    cls = getattr(module, "Collector", None)
    if cls is None:
        raise AttributeError(f"{root.name}/{collector_id}/collector.py 에 Collector 클래스가 없다")
    return cls(meta=metas[collector_id])
