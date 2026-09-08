"""이슈 카테고리 → 키워드 어휘집.

지역 현안을 어떤 축으로 나누고 어떤 낱말을 그 축에 넣을지는 **지역적·정치적
편집 판단이다.** `party_lineage.py` 와 같은 이유로 코드가 아니라 데이터
(`data/shared/reference/issue_lexicon.yaml`)에 둔다 — 이견이 있으면 그 파일만 고치고
`uv run votelink analyze issue_ranker` 를 다시 돌리면 된다.

매칭은 형태소 분석도 개체명 인식도 아니다. 기사 `title + summary` 문자열에
`keywords` 중 하나라도 substring 으로 등장하면 그 카테고리로 센다
(`collectors/naver_news/text.py:match_terms` 와 같은 방식). 한 기사가 여러
카테고리에 걸리면 전부 센다. LLM 을 쓰지 않으므로 재현 가능하다.

`Lexicon.version` 은 산출 레코드 payload 의 `lexicon_version` 에 박힌다. 어휘집이
곧 편집 판단이라 어떤 판(version)으로 만든 결과인지 역추적할 수 있어야 한다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

LEXICON_PATH = Path("data/shared/reference/issue_lexicon.yaml")

_lock = threading.Lock()
_cache: Lexicon | None = None


class LexiconError(RuntimeError):
    """어휘집을 읽을 수 없거나 형식이 계약에 맞지 않는다. 조용히 넘어가지 않는다 —
    분석기는 이걸 AnalyzeError 로 올려 전체를 중단한다 (참조 데이터 결손)."""


class IssueCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, description="payload.issues[].category 에 그대로 들어간다")
    label: str = Field(min_length=1, description="사람이 읽는 이름")
    keywords: list[str] = Field(min_length=1, description="substring 매칭 대상. 빈 카테고리는 거부")

    @field_validator("keywords")
    @classmethod
    def _no_blank_keyword(cls, v: list[str]) -> list[str]:
        if any(not k or not k.strip() for k in v):
            raise ValueError("빈 keyword 가 있다 — 빈 문자열은 모든 기사에 매칭된다")
        return v


class Lexicon(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(
        min_length=1, description="검수 완료일 등. payload.lexicon_version 에 박힌다"
    )
    categories: list[IssueCategory] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _keys_unique(cls, v: list[IssueCategory]) -> list[IssueCategory]:
        keys = [c.key for c in v]
        if len(keys) != len(set(keys)):
            raise ValueError(f"category key 가 중복된다: {keys}")
        return v


def load_lexicon(path: Path | None = None, *, force: bool = False) -> Lexicon:
    """어휘집을 읽는다. 없으면 FileNotFoundError, 형식이 틀리면 LexiconError."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        target = path or LEXICON_PATH
        if not target.exists():
            raise FileNotFoundError(f"이슈 어휘집 파일이 없다: {target}")
        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            lexicon = Lexicon.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - 파싱·검증 실패를 한 종류로 묶는다
            raise LexiconError(f"{target} 를 읽을 수 없다: {exc}") from exc
        _cache = lexicon
        return _cache


def reset_cache() -> None:
    """테스트용."""
    global _cache
    with _lock:
        _cache = None
