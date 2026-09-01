"""수집기 메타데이터 — collectors/<id>/meta.yaml 의 스키마.

registry 가 이 파일들을 모아 registry.yaml 을 만든다.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from votelink.contract.enums import GeoLevel, RecordKind, SourceLicense


class AccessMethod(StrEnum):
    API = "api"
    RSS = "rss"
    CRAWL = "crawl"
    FILE = "file"


class CollectorMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    kinds: list[RecordKind] = Field(min_length=1)
    source_name: str
    source_url: str
    source_license: SourceLicense
    access: AccessMethod
    schedule: str | None = None
    incremental: bool = False
    geo_level: GeoLevel
    requires_secrets: list[str] = Field(default_factory=list)
    rate_limit_rps: float = Field(default=1.0, gt=0, le=10)
    proposal: str | None = None
    verified: bool = Field(
        default=False,
        description="실제 응답 fixture로 parse 가 검증됐는가. False면 신뢰하지 않는다",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="수집기별 설정(엔드포인트, 기준월 등). 비밀값은 여기 넣지 않는다",
    )

    @field_validator("proposal")
    @classmethod
    def _proposal_must_exist(cls, v: str | None) -> str | None:
        # 제안서 없이 만들어진 수집기를 잡아낸다. 경로만 확인하고 내용은 보지 않는다.
        if v and not Path(v).exists():
            raise ValueError(f"proposal 경로가 없다: {v}")
        return v

    @classmethod
    def load(cls, path: Path) -> CollectorMeta:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        meta = cls.model_validate(data)
        if meta.id != path.parent.name:
            raise ValueError(f"meta.id({meta.id})와 폴더명({path.parent.name})이 다르다")
        return meta
