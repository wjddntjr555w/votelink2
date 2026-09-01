"""공통 데이터 계약. 스키마의 단일 진실."""

from votelink.contract.enums import (
    AgeBand,
    ElectionType,
    GeoLevel,
    ObservedPrecision,
    RecordKind,
    Sex,
    SourceLicense,
)
from votelink.contract.models import (
    CONTRACT_VERSION,
    KST,
    Record,
    load_record,
    make_record_id,
    to_kst,
)

__all__ = [
    "CONTRACT_VERSION",
    "KST",
    "AgeBand",
    "ElectionType",
    "GeoLevel",
    "ObservedPrecision",
    "Record",
    "RecordKind",
    "Sex",
    "SourceLicense",
    "load_record",
    "make_record_id",
    "to_kst",
]
