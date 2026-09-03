"""분석기 메타데이터 — analyzers/<id>/meta.yaml 의 스키마.

CollectorMeta 와 형제지만 상속하지 않는다. 분석기에는 출처(source_name/url/license)나
접근 방식(api/file)이 없고, 대신 inputs/outputs 가 있다. 억지로 한 모델에 넣으면
양쪽 다 안 맞는 필드를 갖게 된다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from votelink.contract.enums import GeoLevel, RecordKind
from votelink.districtcfg import resolve_config


class AnalyzerMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    inputs: list[RecordKind] = Field(
        min_length=1,
        description="읽는 kind. 여기 없는 kind 는 무시한다 (계약 §7 전방 호환)",
    )
    outputs: list[RecordKind] = Field(min_length=1, description="내는 kind")
    geo_level: GeoLevel = Field(description="산출물의 집계 단위")
    proposal: str | None = None
    verified: bool = Field(
        default=False,
        description="실제 입력으로 compute 가 검증됐는가. False면 신뢰하지 않는다",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="분석기별 설정(임계값 등). 코드에 박지 않고 여기 둔다",
    )

    @field_validator("proposal")
    @classmethod
    def _proposal_must_exist(cls, v: str | None) -> str | None:
        # 제안서 없이 만들어진 분석기를 잡아낸다. 경로만 확인하고 내용은 보지 않는다.
        if v and not Path(v).exists():
            raise ValueError(f"proposal 경로가 없다: {v}")
        return v

    def resolved_config(self, district_id: str | None = None) -> dict[str, Any]:
        """선거구 하나를 골라 평평한 설정 dict 를 만든다 (`votelink.districtcfg`).

        `common`/`districts` 구조가 아닌 평평한 `config` 는 그대로 돌려준다.
        """
        return resolve_config(self.id, self.config, district_id)

    @classmethod
    def load(cls, path: Path) -> AnalyzerMeta:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        meta = cls.model_validate(data)
        if meta.id != path.parent.name:
            raise ValueError(f"meta.id({meta.id})와 폴더명({path.parent.name})이 다르다")
        return meta
