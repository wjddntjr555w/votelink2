"""산출물 검증 상태. **L3가 절대 규칙 5를 집행하는 근거다.**

`CLAUDE.md` 절대 규칙 5: "선거법 검증을 통과하지 않은 산출물은 웹앱에 경고 없이
표시하지 않는다." 그 '통과했다'의 정의는 `docs/90-compliance.md` 에 있고, 정책 자체는
코드가 아니라 데이터(`data/reference/compliance.yaml`)에 둔다 —
**법률 검토는 사람의 판단이고, 변호사가 파이썬을 읽지 않아도 고칠 수 있어야 한다.**
`districts.py`(획정이 바뀐다)·`party_lineage.py`(정치적 판단이다)와 같은 구조다.

**이 모듈은 적법성을 판정하지 않는다.** 검토 여부를 기록에서 읽고, 검토되지 않은 것을
`unreviewed` 로 드러낼 뿐이다. 최종 판단자는 캠프의 법률 검토다.

판정 입력은 **계약 봉투 필드뿐**이다(`kind`, `confidence`, `derived_from`).
`analyzers/registry.yaml` 이나 `AnalyzerMeta.verified` 를 읽지 않는다 — L2의 내부 상태이고,
읽는 순간 계층 무지(`docs/00-overview.md §3`)가 깨진다.
"""

from __future__ import annotations

import threading
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from votelink.contract.enums import RecordKind
from votelink.contract.models import Record

POLICY_PATH = Path("data/reference/compliance.yaml")

_lock = threading.Lock()
_cache: Policy | None = None


class ReviewStatus(StrEnum):
    """산출물의 검토 상태. `docs/90-compliance.md §3`.

    `Emd.code = None`("코드를 모른다"), `LeanPoint.gap_* = None`("편차를 모른다")과
    같은 정신이다 — 모르는 것을 아는 척하지 않는다.
    """

    CLEARED = "cleared"
    """사람이 검토했다고 서명한 기록. **시스템의 판단이 아니다.**"""

    UNREVIEWED = "unreviewed"
    """아직 검토되지 않았다. 기본값이며, 모르면 여기로 떨어진다."""

    BLOCKED = "blocked"
    """지금 표시하면 안 된다."""


class Risk(StrEnum):
    """산출물 위험도. `docs/90-compliance.md §5`."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OutputPolicy(BaseModel):
    """산출물 한 종류(kind)에 대한 정책."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RecordKind
    risk: Risk
    status: ReviewStatus = ReviewStatus.UNREVIEWED
    derived: bool = False
    """L2 파생 산출물인가. 참이면 `derived_from` 이 비었을 때 근거 없음을 경고한다."""
    distribution: str = "internal_only"
    ai_generated: bool = False
    blackout: str | None = None
    """기간 제한 이름. 설정되면 `election_day` 없이는 판정할 수 없다."""
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reviewed_by: str = ""
    reviewed_at: str = ""
    note: str = ""


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "unknown"
    election_day: str | None = None
    """선거일(YYYY-MM-DD). **모르면 null.** 기간 의존 판정이 전부 unreviewed 로 떨어진다."""
    default_status: ReviewStatus = ReviewStatus.UNREVIEWED
    outputs: list[OutputPolicy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_must_stay_closed(self):
        """`default_status: cleared` 는 규칙 5를 끄는 것이다.

        정책표에 없는 kind가 조용히 무경고로 표시되면, 새 분석기가 새 산출물을 낼 때마다
        아무도 모르게 검증이 비켜간다. 규칙 5가 막으려는 게 정확히 그 상황이다.
        """
        if self.default_status is ReviewStatus.CLEARED:
            raise ValueError(
                "default_status 를 cleared 로 둘 수 없다. 정책표에 없는 kind 는 "
                "unreviewed 여야 한다 (docs/90-compliance.md §4 fail-closed)"
            )
        return self

    @model_validator(mode="after")
    def _no_duplicate_kinds(self):
        kinds = [o.kind for o in self.outputs]
        if len(kinds) != len(set(kinds)):
            raise ValueError("같은 kind 가 두 번 있다. 어느 쪽이 적용되는지 알 수 없다")
        return self

    def for_kind(self, kind: RecordKind) -> OutputPolicy | None:
        return next((o for o in self.outputs if o.kind == kind), None)


class Verdict(BaseModel):
    """판정 결과. 웹앱은 이것만 보고 배지와 경고를 그린다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReviewStatus
    reasons: tuple[str, ...] = ()
    """상태가 왜 그 값인지. `cleared` 로 통과하면 비어 있다."""
    notes: tuple[str, ...] = ()
    """**상태와 무관하게 항상 표시된다.** 검토를 통과한 것과 데이터가 튼튼한 것은 다르다."""
    reviewed_by: str = ""
    reviewed_at: str = ""

    @property
    def is_cleared(self) -> bool:
        return self.status is ReviewStatus.CLEARED

    @property
    def shows_content(self) -> bool:
        """콘텐츠를 그려도 되는가. `blocked` 면 수치가 화면에 나가지 않는다."""
        return self.status is not ReviewStatus.BLOCKED


def load_policy(path: Path | None = None, *, force: bool = False) -> Policy:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        target = path or POLICY_PATH
        if not target.exists():
            raise FileNotFoundError(
                f"산출물 검증 정책 파일이 없다: {target}. "
                "규칙 5를 집행할 근거가 없으므로 표시하지 않는다"
            )
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        _cache = Policy.model_validate(raw)
        return _cache


def reset_cache() -> None:
    """테스트용."""
    global _cache
    with _lock:
        _cache = None


def review(record: Record, path: Path | None = None) -> Verdict:
    """이 레코드를 웹앱에 어떻게 표시할 것인가. `docs/90-compliance.md §8`.

    순수 함수다 — 같은 (정책, 레코드)면 같은 판정이 나온다. 시계도 난수도 쓰지 않는다.
    """
    policy = load_policy(path)
    rule = policy.for_kind(record.kind)
    notes = _notes(record, rule)

    if rule is None:
        return Verdict(
            status=policy.default_status,
            reasons=(
                f"정책표에 '{record.kind}' 항목이 없다. "
                "검토되지 않은 산출물로 다룬다 (fail-closed)",
            ),
            notes=notes,
        )

    if rule.status is ReviewStatus.BLOCKED:
        return Verdict(
            status=ReviewStatus.BLOCKED,
            reasons=(rule.note or "정책표가 이 산출물의 표시를 차단했다",),
            notes=notes,
        )

    if rule.status is ReviewStatus.CLEARED and not rule.reviewed_by.strip():
        return Verdict(
            status=ReviewStatus.UNREVIEWED,
            reasons=(
                "status 가 cleared 인데 reviewed_by 가 비어 있다 — "
                "서명 없는 서명란은 서명이 아니다",
            ),
            notes=notes,
        )

    if rule.blackout is not None and policy.election_day is None:
        return Verdict(
            status=ReviewStatus.UNREVIEWED,
            reasons=(
                f"'{rule.blackout}' 은 기간 판정이 필요한데 election_day 가 설정되지 않았다. "
                "선거일을 모르면 기간을 계산할 수 없다",
            ),
            notes=notes,
        )

    return Verdict(
        status=rule.status,
        notes=notes,
        reviewed_by=rule.reviewed_by,
        reviewed_at=rule.reviewed_at,
    )


def _notes(record: Record, rule: OutputPolicy | None) -> tuple[str, ...]:
    """상태를 바꾸지 않는 경고. 데이터의 튼튼함에 대한 것이지 적법성에 대한 것이 아니다."""
    if rule is None:
        return ()
    notes: list[str] = []
    if rule.min_confidence is not None and record.confidence < rule.min_confidence:
        notes.append(f"신뢰도 {record.confidence:.2f} 가 기준 {rule.min_confidence:.2f} 미만이다")
    if rule.derived and not record.derived_from:
        notes.append("파생 산출물인데 derived_from 이 비어 있다 — 근거를 추적할 수 없다")
    return tuple(notes)
