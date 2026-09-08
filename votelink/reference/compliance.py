"""산출물 검증 상태. **L3가 절대 규칙 5를 집행하는 근거다.**

`CLAUDE.md` 절대 규칙 5: "선거법 검증을 통과하지 않은 산출물은 웹앱에 경고 없이
표시하지 않는다." 그 '통과했다'의 정의는 `docs/90-compliance.md` 에 있고, 정책 자체는
코드가 아니라 데이터(`data/shared/reference/compliance.yaml`)에 둔다 —
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

POLICY_PATH = Path("data/shared/reference/compliance.policy.yaml")
"""**공용** — 산출물의 성질(위험도·배포범위·기간제한). 운영자가 유지하고 전 캠프가 같이 본다."""

REVIEW_FILENAME = "compliance.review.yaml"
"""**캠프·주기별** — 그 캠프 법률 검토자의 서명. `cycles/<cycle_id>/` 에 산다.

정책과 검토를 한 파일에 두면 캠프가 늘어나는 순간 무너진다. 무엇이 위험한가는 모두에게
같지만, 검토했는가는 캠프마다 다르기 때문이다 (`docs/proposals/P-001` §13).
"""

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


def _reject_cleared(status: ReviewStatus, where: str) -> ReviewStatus:
    """`cleared` 는 사람의 서명이지 기본값이 될 수 없다.

    기본값으로 통과시키면, 새 분석기가 새 산출물을 낼 때마다 아무도 모르게 검증이
    비켜간다. 규칙 5가 막으려는 게 정확히 그 상황이다 (`docs/90-compliance.md §4`).
    """
    if status is ReviewStatus.CLEARED:
        raise ValueError(
            f"{where} 를 cleared 로 둘 수 없다. cleared 는 캠프 법률 검토자의 서명으로만 "
            f"들어간다 ({REVIEW_FILENAME})"
        )
    return status


class OutputPolicy(BaseModel):
    """**공용** — 산출물 한 종류(kind)의 성질. 캠프와 무관하게 같다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RecordKind
    risk: Risk
    derived: bool = False
    """L2 파생 산출물인가. 참이면 `derived_from` 이 비었을 때 근거 없음을 경고한다."""
    distribution: str = "internal_only"
    ai_generated: bool = False
    blackout: str | None = None
    """기간 제한 이름. 설정되면 선거일 없이는 판정할 수 없다."""
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    default_status: ReviewStatus = ReviewStatus.UNREVIEWED
    """**캠프의 검토 기록이 없을 때의 처분.**

    고위험 산출물(메시지 자산·게시물 배치안)은 `blocked` 로 둔다 —
    `docs/90-compliance.md §5` 가 "기본 blocked" 라고 정한 것이 이 자리다.
    검토 기록을 캠프 쪽으로 옮기면서 이 바닥이 없으면, 검토 기록이 아직 없는 새 캠프에서
    고위험 산출물이 `unreviewed`(= 경고와 함께 내용 표시)로 떨어진다.
    """
    note: str = ""

    @model_validator(mode="after")
    def _default_must_stay_closed(self):
        _reject_cleared(self.default_status, f"'{self.kind}' 의 default_status")
        return self


class Policy(BaseModel):
    """`compliance.policy.yaml` — 공용 정책표."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "unknown"
    default_status: ReviewStatus = ReviewStatus.UNREVIEWED
    """정책표에 아예 없는 kind 의 처분. fail-closed."""
    outputs: list[OutputPolicy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _guard(self):
        _reject_cleared(self.default_status, "default_status")
        kinds = [o.kind for o in self.outputs]
        if len(kinds) != len(set(kinds)):
            raise ValueError("같은 kind 가 두 번 있다. 어느 쪽이 적용되는지 알 수 없다")
        return self

    def for_kind(self, kind: RecordKind) -> OutputPolicy | None:
        return next((o for o in self.outputs if o.kind == kind), None)


class OutputReview(BaseModel):
    """**캠프·주기별** — 이 산출물에 대한 그 캠프 법률 검토자의 기록."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RecordKind
    status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewed_by: str = ""
    reviewed_at: str = ""
    note: str = ""


class Review(BaseModel):
    """`cycles/<cycle_id>/compliance.review.yaml`. 캠프가 없으면 빈 것이 쓰인다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "unknown"
    outputs: list[OutputReview] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_duplicate_kinds(self):
        kinds = [o.kind for o in self.outputs]
        if len(kinds) != len(set(kinds)):
            raise ValueError("같은 kind 가 두 번 있다. 어느 쪽이 적용되는지 알 수 없다")
        return self

    def for_kind(self, kind: RecordKind) -> OutputReview | None:
        return next((o for o in self.outputs if o.kind == kind), None)


EMPTY_REVIEW = Review()
"""캠프가 없을 때(진영 중립 보기) 쓰는 빈 검토 기록. 전부 미검토로 떨어진다."""


class Compliance(BaseModel):
    """판정에 필요한 전부 — 공용 정책 + 이 캠프의 검토 기록 + 선거일.

    둘을 합쳐 하나로 만들지 않고 나란히 든다. 그래야 판정 사유가 "정책표에 없다"와
    "이 캠프가 아직 검토하지 않았다"를 구분해 말할 수 있다 — 사용자가 할 일이 다르다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: Policy
    review: Review = EMPTY_REVIEW
    election_day: str | None = None
    """선거일(YYYY-MM-DD). 캠프의 `election.yaml` 에서 온다. **모르면 null** —
    기간 의존 판정이 전부 unreviewed 로 떨어진다."""


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


def load_review(path: Path) -> Review:
    """캠프 주기의 검토 기록. 파일이 없으면 빈 것 — 아무것도 검토되지 않은 상태다.

    **캐시하지 않는다.** 캠프마다 다른 파일이고, 모듈 전역에 담으면 캠프 A 와 B 의
    동시 요청이 같은 슬롯을 두고 경쟁한다 (`docs/proposals/P-001` §10).
    """
    if not path.exists():
        return EMPTY_REVIEW
    return Review.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def review(record: Record, path: Path | None = None) -> Verdict:
    """공용 정책만으로 판정한다. 캠프 검토 기록이 없으므로 전부 미검토로 떨어진다."""
    return review_with(Compliance(policy=load_policy(path)), record)


def review_with(compliance: Compliance, record: Record) -> Verdict:
    """이 레코드를 웹앱에 어떻게 표시할 것인가. `docs/90-compliance.md §8`.

    **순수 함수다** — 같은 (정책+검토, 레코드)면 같은 판정이 나온다. 시계도 난수도
    디스크도 쓰지 않는다. L3의 뷰모델이 순수하게 남으려면 판정도 순수해야 한다.

    상태는 두 곳에서 온다: **캠프의 검토 기록이 있으면 그것**, 없으면 **공용 정책의
    기본 처분**. 고위험 산출물이 `blocked` 로 시작하는 것이 후자다.
    """
    rule = compliance.policy.for_kind(record.kind)
    entry = compliance.review.for_kind(record.kind)
    notes = _notes(record, rule)

    if rule is None:
        return Verdict(
            status=compliance.policy.default_status,
            reasons=(
                f"정책표에 '{record.kind}' 항목이 없다. "
                "검토되지 않은 산출물로 다룬다 (fail-closed)",
            ),
            notes=notes,
        )

    status = entry.status if entry is not None else rule.default_status
    signed_by = entry.reviewed_by if entry is not None else ""

    if status is ReviewStatus.BLOCKED:
        blocked_note = (entry.note if entry is not None else "") or rule.note
        return Verdict(
            status=ReviewStatus.BLOCKED,
            reasons=(blocked_note or "이 산출물의 표시가 차단됐다",),
            notes=notes,
        )

    if status is ReviewStatus.CLEARED and not signed_by.strip():
        return Verdict(
            status=ReviewStatus.UNREVIEWED,
            reasons=(
                "status 가 cleared 인데 reviewed_by 가 비어 있다 — "
                "서명 없는 서명란은 서명이 아니다",
            ),
            notes=notes,
        )

    if rule.blackout is not None and compliance.election_day is None:
        return Verdict(
            status=ReviewStatus.UNREVIEWED,
            reasons=(
                f"'{rule.blackout}' 은 기간 판정이 필요한데 선거일이 설정되지 않았다. "
                "캠프의 election.yaml 에 선거일을 적어야 기간을 계산할 수 있다",
            ),
            notes=notes,
        )

    reasons: tuple[str, ...] = ()
    if status is ReviewStatus.UNREVIEWED:
        # 사유 없는 경고는 사용자가 무엇을 해야 하는지 알려주지 않는다.
        reasons = (
            (
                f"이 캠프의 검토 기록({REVIEW_FILENAME})에 '{record.kind}' 가 없다 — "
                "아직 법률 검토를 받지 않았다"
            )
            if entry is None
            else (
                f"검토 기록에 unreviewed 로 남아 있다. 검토를 마치면 "
                f"{REVIEW_FILENAME} 에 서명을 남긴다"
            ),
        )

    return Verdict(
        status=status,
        reasons=reasons,
        notes=notes,
        reviewed_by=signed_by,
        reviewed_at=entry.reviewed_at if entry is not None else "",
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
