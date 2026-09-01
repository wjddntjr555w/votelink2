"""공통 레코드 계약 — L1(수집)과 L2(분석)를 잇는 유일한 접점.

이 파일이 스키마의 단일 진실이다. docs/10-data-contract.md 는 이 모델의 의도를 설명한다.
둘이 어긋나면 이 파일이 옳다.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from votelink.contract.enums import (
    GeoLevel,
    ObservedPrecision,
    RecordKind,
    SourceLicense,
)
from votelink.contract.payloads import PAYLOAD_MODELS

log = logging.getLogger(__name__)

CONTRACT_VERSION = "1.0"
"""계약이 깨지는 변경이 있을 때만 올린다. 필드 추가는 올리지 않는다."""

KST = timezone(timedelta(hours=9), "KST")
"""이 시스템의 모든 시각은 한국 현지시각이다. 유세 시간대, 통계 기준일,
선거법상 기간이 전부 KST 기준이므로 UTC로 저장하지 않는다."""

RECORD_ID_LEN = 16

# 내부 표준 코드 체계: 행정안전부 **행정표준코드의 행정기관코드 7자리**.
# (예: 서울 송파구 풍납1동 = 3230040)
#
# 계층에 따라 자릿수가 달라지지 않는다 — 시도·시군구·행정동 모두 7자리다.
# 그래서 자릿수는 약한 검증이고, 진짜 검증은 "매핑표/출처에 존재하는 코드인가"이다.
#
# 다른 체계(법정동코드 10자리, 통계청 행정구역코드 8자리)는 내부 표준이 아니며
# 매핑표의 source_code 로만 존재한다.
GEO_CODE_DIGITS = 7
GEO_CODE_LEVELS = {GeoLevel.SIDO, GeoLevel.SIGUNGU, GeoLevel.EMD, GeoLevel.POINT}
GEO_CODE_FORBIDDEN = {GeoLevel.NATION, GeoLevel.NONE}

_RECORD_ID_RE = re.compile(rf"^[0-9a-f]{{{RECORD_ID_LEN}}}$")


def make_record_id(kind: str, collector_id: str, natural_key: str) -> str:
    """결정적 ID. 같은 데이터를 다시 수집해도 같은 값이 나와야 멱등성이 성립한다.

    natural_key 는 출처 안에서 그 데이터를 유일하게 가리키는 문자열이다
    (기사 URL, '선거ID+투표구', '기준월+행정동코드' 등).
    """
    if not natural_key:
        raise ValueError("natural_key 가 비어 있다. record_id 를 만들 수 없다")
    seed = f"{kind}|{collector_id}|{natural_key}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:RECORD_ID_LEN]


def to_kst(value: datetime) -> datetime:
    """naive 는 KST로 간주하고, aware 는 KST로 변환한다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


class Record(BaseModel):
    """봉투 15필드 + 본문 1필드.

    수집기는 이것만 만들면 된다. 분석기는 이것만 읽으면 된다.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    record_id: str = Field(default="", description="자동 계산. natural_key 를 넘기면 채워진다")
    schema_version: str = CONTRACT_VERSION
    kind: RecordKind
    collector_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_url: str | None = None
    source_license: SourceLicense
    observed_at: datetime = Field(description="데이터가 가리키는 시점 (기사 발행일, 통계 기준일)")
    observed_precision: ObservedPrecision
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(KST))
    geo_level: GeoLevel
    geo_code: str | None = None
    geo_name: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    derived_from: list[str] = Field(
        default_factory=list,
        description="파생 레코드의 근거 record_id 목록. 원천 레코드는 빈 리스트",
    )
    payload: dict[str, Any]

    # natural_key 는 record_id 계산용 입력이며 저장되지 않는다.
    natural_key: str | None = Field(default=None, exclude=True, repr=False)

    # --- 시각 -----------------------------------------------------------------

    @field_validator("observed_at", "ingested_at", mode="after")
    @classmethod
    def _normalize_tz(cls, v: datetime) -> datetime:
        return to_kst(v)

    # --- id -------------------------------------------------------------------

    @model_validator(mode="after")
    def _fill_record_id(self):
        if not self.record_id:
            if not self.natural_key:
                raise ValueError(
                    "record_id 또는 natural_key 중 하나는 있어야 한다. "
                    "수집기는 natural_key 를 넘기고, 저장된 레코드를 읽을 때는 record_id 가 있다"
                )
            object.__setattr__(
                self,
                "record_id",
                make_record_id(self.kind, self.collector_id, self.natural_key),
            )
        elif not _RECORD_ID_RE.match(self.record_id):
            raise ValueError(f"record_id 형식이 잘못됐다: {self.record_id!r}")
        return self

    @field_validator("derived_from")
    @classmethod
    def _check_derived_ids(cls, v: list[str]) -> list[str]:
        for rid in v:
            if not _RECORD_ID_RE.match(rid):
                raise ValueError(f"derived_from 에 잘못된 record_id: {rid!r}")
        if len(v) != len(set(v)):
            raise ValueError("derived_from 에 중복된 record_id 가 있다")
        return v

    # --- 교차 검증 -------------------------------------------------------------

    @model_validator(mode="after")
    def _check_time_order(self):
        if self.observed_at > self.ingested_at:
            raise ValueError(
                f"observed_at({self.observed_at.isoformat()})이 "
                f"ingested_at({self.ingested_at.isoformat()})보다 미래다. "
                "두 값을 혼동했을 가능성이 높다"
            )
        return self

    @model_validator(mode="after")
    def _check_geo(self):
        level, code = self.geo_level, self.geo_code

        if level in GEO_CODE_FORBIDDEN:
            if code is not None:
                raise ValueError(f"geo_level={level} 인데 geo_code 가 있다: {code!r}")
            return self

        if code is None:
            raise ValueError(
                f"geo_level={level} 인데 geo_code 가 없다. "
                "행정동코드 매핑 실패를 null 로 넘기지 않는다 (계약 위반 → 격리 대상)"
            )
        if not (code.isdigit() and len(code) == GEO_CODE_DIGITS):
            raise ValueError(
                f"geo_code 는 행정기관코드 숫자 {GEO_CODE_DIGITS}자리여야 한다: {code!r}. "
                "법정동코드(10자리)나 통계청 행정구역코드(8자리)를 그대로 넣지 않는다"
            )
        if not self.geo_name:
            raise ValueError("geo_code 가 있으면 geo_name 도 있어야 한다")
        return self

    @model_validator(mode="after")
    def _check_payload(self):
        model = PAYLOAD_MODELS.get(self.kind)
        if model is None:
            raise ValueError(
                f"kind={self.kind} 의 payload 모델이 없다. "
                "새 kind 추가는 계약 변경이므로 payloads.py 에 모델을 등록해야 한다"
            )
        model.model_validate(self.payload)  # 위반 시 여기서 터진다
        return self

    @model_validator(mode="after")
    def _check_fulltext_license(self):
        """뉴스 원문 전문 저장은 public_open 출처에서만 허용한다."""
        if (
            self.kind is RecordKind.NEWS_ARTICLE
            and self.payload.get("full_text_stored")
            and self.source_license is not SourceLicense.PUBLIC_OPEN
        ):
            raise ValueError(
                f"source_license={self.source_license} 출처의 뉴스 원문 전문은 저장할 수 없다. "
                "링크 + 메타 + 요약까지만 저장한다"
            )
        return self


class UnsupportedRecord(Exception):
    """이 버전이 처리할 수 없는 저장 레코드."""


def load_record(raw: dict[str, Any]) -> Record | None:
    """저장된 레코드를 읽는다. 전방 호환 규칙(docs/10-data-contract.md §7)을 구현한다.

    - 상위 schema_version → None (처리 거부)
    - 모르는 kind → None (무시하고 로그)
    - 그 외 계약 위반 → 예외를 그대로 올린다 (격리 대상)
    """
    version = str(raw.get("schema_version", ""))
    if version and _major(version) > _major(CONTRACT_VERSION):
        log.warning("상위 계약 버전 레코드를 건너뛴다: %s > %s", version, CONTRACT_VERSION)
        return None

    kind = raw.get("kind")
    if kind not in set(RecordKind):
        log.warning("알 수 없는 kind 를 건너뛴다: %r", kind)
        return None

    return Record.model_validate(raw)


def _major(version: str) -> int:
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError):
        return 0


__all__ = [
    "CONTRACT_VERSION",
    "KST",
    "Record",
    "UnsupportedRecord",
    "load_record",
    "make_record_id",
    "to_kst",
]
