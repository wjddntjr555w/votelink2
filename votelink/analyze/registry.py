"""분석기 등록부.

analyzers/<id>/meta.yaml 들을 모아 analyzers/registry.yaml 을 만든다.
수집기 등록부와 같은 이유로 존재한다 — 전체 목록이 필요할 때 폴더를 뒤지지 않는다.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import yaml

from votelink.analyze.base import BaseAnalyzer
from votelink.analyze.meta import AnalyzerMeta

ANALYZERS_DIR = Path("analyzers")
REGISTRY_PATH = ANALYZERS_DIR / "registry.yaml"


def discover(root: Path = ANALYZERS_DIR) -> dict[str, AnalyzerMeta]:
    """meta.yaml 을 가진 하위 폴더를 전부 찾는다."""
    found: dict[str, AnalyzerMeta] = {}
    if not root.exists():
        return found
    for meta_path in sorted(root.glob("*/meta.yaml")):
        meta = AnalyzerMeta.load(meta_path)
        found[meta.id] = meta
    return found


def sync(root: Path = ANALYZERS_DIR, out: Path | None = None) -> Path:
    """registry.yaml 재생성. 손으로 수정하지 않는다."""
    metas = discover(root)
    target = out or (root / "registry.yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "generated_by": "votelink analyze registry sync",
        "count": len(metas),
        "analyzers": [
            {
                "id": m.id,
                "name": m.name,
                "inputs": [str(k) for k in m.inputs],
                "outputs": [str(k) for k in m.outputs],
                "geo_level": str(m.geo_level),
                "verified": m.verified,
            }
            for m in metas.values()
        ],
    }
    target.write_text(
        "# 자동 생성물. 손으로 고치지 말 것. `uv run votelink analyze --sync`\n"
        + yaml.safe_dump(body, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target


def load(analyzer_id: str, root: Path = ANALYZERS_DIR) -> BaseAnalyzer:
    """analyzers/<id>/analyzer.py 의 Analyzer 클래스를 불러 인스턴스로 만든다."""
    metas = discover(root)
    if analyzer_id not in metas:
        known = ", ".join(sorted(metas)) or "(없음)"
        raise KeyError(f"분석기 '{analyzer_id}' 를 찾을 수 없다. 등록된 것: {known}")

    # analyzers/ 는 프로젝트 루트 기준 패키지다. 콘솔 스크립트로 실행하면
    # 작업 디렉터리가 sys.path 에 없을 수 있어 직접 넣어준다.
    parent = str(root.resolve().parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module = importlib.import_module(f"{root.name}.{analyzer_id}.analyzer")
    cls = getattr(module, "Analyzer", None)
    if cls is None:
        raise AttributeError(f"{root.name}/{analyzer_id}/analyzer.py 에 Analyzer 클래스가 없다")
    return cls(meta=metas[analyzer_id])
