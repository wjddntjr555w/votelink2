"""뉴스 검색용 정당명 전역 목록 — 운영자 콘솔에서 개수 제한 없이 추가·수정·삭제한다.

제안서: `docs/proposals/P-006-camp-aware-news-collection.md` §5.

`party_lineage.yaml`(후보→진영 매핑, 판단 근거가 대부분인 파일)과는 성격이 다르다.
여기는 판단 근거 없는 단순 문자열 목록이라 `docs/proposals/P-003-operator-console.md`
§3의 "원문 텍스트+git 커밋" 제약과 무관하다 — 일반 폼 CRUD로 관리한다
(`votelink/web/ops.py`).

모듈 전역 캐시를 두지 않는다. `camp/loader.py` 와 같은 이유다 — 쓰기 직후 다른 요청이
읽어도 항상 디스크의 최신값이어야 한다.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

NEWS_PARTIES_PATH = Path("data/shared/reference/news_parties.yaml")

_lock = threading.Lock()


class PartyNotFound(LookupError):
    """알 수 없는 정당 id. 이미 삭제됐거나 오타다."""


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = Field(min_length=1)


def party_slug(name: str) -> str:
    """결정적 ascii id. 이름이 곧 검색어이자 매칭키이므로 이름에서 파생시킨다."""
    return f"party-{hashlib.sha256(name.strip().encode('utf-8')).hexdigest()[:8]}"


def _read(path: Path) -> list[Party]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Party.model_validate(p) for p in raw.get("parties", [])]


def _write(path: Path, parties: list[Party]) -> None:
    """임시 파일에 쓴 뒤 rename — 쓰다 끊겨도 원본이 반쯤 쓰인 상태로 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"parties": [p.model_dump() for p in parties]}
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def list_parties(path: Path | None = None) -> list[Party]:
    return sorted(_read(path or NEWS_PARTIES_PATH), key=lambda p: p.name)


def add_party(name: str, path: Path | None = None) -> Party:
    """이름이 같은 정당이 있으면 그 항목을 그대로 돌려준다(중복 추가 아님)."""
    target = path or NEWS_PARTIES_PATH
    name = name.strip()
    if not name:
        raise ValueError("정당명이 비어 있다")
    with _lock:
        parties = _read(target)
        existing = next((p for p in parties if p.name == name), None)
        if existing:
            return existing
        party = Party(id=party_slug(name), name=name)
        _write(target, [*parties, party])
        return party


def update_party(party_id: str, new_name: str, path: Path | None = None) -> Party:
    target = path or NEWS_PARTIES_PATH
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("정당명이 비어 있다")
    with _lock:
        parties = _read(target)
        if not any(p.id == party_id for p in parties):
            raise PartyNotFound(f"정당 '{party_id}' 를 찾을 수 없다")
        updated = [Party(id=party_id, name=new_name) if p.id == party_id else p for p in parties]
        _write(target, updated)
        return next(p for p in updated if p.id == party_id)


def delete_party(party_id: str, path: Path | None = None) -> None:
    target = path or NEWS_PARTIES_PATH
    with _lock:
        parties = _read(target)
        remaining = [p for p in parties if p.id != party_id]
        if len(remaining) == len(parties):
            raise PartyNotFound(f"정당 '{party_id}' 를 찾을 수 없다")
        _write(target, remaining)


def party_queries_for_geo(geo_name: str, path: Path | None = None) -> list[dict[str, str]]:
    """`{id, q}` 목록. 정당명+지역명, 정당명 단독 두 종류를 만든다.

    단독 검색으로 들어오는 전국 뉴스는 수집기의 지역 스코프 필터
    (district_terms/sigungu_terms/person_terms 중 하나라도 매칭)를 통과해야 저장되므로,
    지역과 무관한 기사가 새로 쌓이지는 않는다.
    """
    queries: list[dict[str, str]] = []
    for party in list_parties(path):
        queries.append({"id": f"{party.id}-region", "q": f"{party.name} {geo_name}"})
        queries.append({"id": party.id, "q": party.name})
    return queries
