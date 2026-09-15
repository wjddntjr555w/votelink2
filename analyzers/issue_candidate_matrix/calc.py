"""순수 계산 + 참조 데이터 로딩.

이슈 어휘집 매칭(`issue_ranker`)과 캠프 로스터 병합(`candidate_mention_share`)은
이미 있는 두 분석기가 각자 하지만, 분석기 폴더 독립 원칙(`docs/30-analysis-spec.md
§3` — 다른 분석기의 코드를 import하지 않는다) 때문에 여기 다시 둔다. 참조 파일은
`issue_ranker`와 같은 `issue_lexicon.yaml`을 그대로 읽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ISSUE_LEXICON_PATH = Path("data/shared/reference/issue_lexicon.yaml")


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Lexicon:
    version: str
    categories: tuple[Category, ...]


def load_lexicon(path: Path | None = None) -> Lexicon:
    target = path or ISSUE_LEXICON_PATH
    if not target.exists():
        raise FileNotFoundError(f"이슈 어휘집이 없다: {target}")
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    categories = tuple(
        Category(key=c["key"], label=c["label"], keywords=tuple(c["keywords"]))
        for c in raw.get("categories", [])
    )
    return Lexicon(version=str(raw.get("version", "unknown")), categories=categories)


def match_categories(haystack: str, lexicon: Lexicon) -> list[str]:
    """title+summary 안에 어휘집 keyword 가 substring 으로 있으면 그 category.key.

    `issue_ranker`와 같은 방식(형태소 분석 없음, substring). 한 기사가 여러
    카테고리에 걸리면 전부 반환한다(비배타).
    """
    return [cat.key for cat in lexicon.categories if any(kw in haystack for kw in cat.keywords)]


@dataclass
class CandidateInfo:
    """로스터 후보 1명 + 이 district 안에서 is_ours 인지."""

    name: str
    is_ours: bool


def merge_rosters(rosters: list) -> list[CandidateInfo]:
    """여러 캠프 로스터를 하나의 후보 목록으로 합친다.

    `candidate_mention_share`의 `calc.merge_rosters`와 같은 정신(로스터 등장
    순서 보존, 이름 중복은 첫 등장 유지·is_ours는 하나라도 True면 True) —
    분석기 폴더 독립을 위해 다시 구현한다.
    """
    order: list[str] = []
    ours: dict[str, bool] = {}
    for roster in rosters:
        for cand, is_ours in [(roster.ours, True)] + [(o, False) for o in roster.opponents]:
            if cand.name not in ours:
                order.append(cand.name)
            ours[cand.name] = ours.get(cand.name, False) or is_ours
    return [CandidateInfo(name=name, is_ours=ours[name]) for name in order]
