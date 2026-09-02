"""분석 실행기.

수집 실행기(`votelink/collect/runner.py`)와 같은 실패 철학을 쓴다:
격리율이 임계를 넘으면 유효분도 커밋하지 않는다. 9개 동 중 1개가 조용히 빠지면
그 동네가 전략에서 통째로 사라진 채 아무도 모른다.

수집기와 다른 점 하나: 저장이 append 가 아니라 **upsert** 다. 분석 결과는 참조
데이터나 로직을 고치면 같은 키에서 다른 값이 나오기 때문이다 (store.upsert_records).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from votelink import store
from votelink.analyze.base import AnalyzeError, BaseAnalyzer
from votelink.contract.models import KST, Record, Rejected

log = logging.getLogger(__name__)

REJECT_RATE_LIMIT = 0.05


@dataclass
class AnalysisReport:
    analyzer_id: str
    started_at: datetime
    inputs: int = 0
    computed: int = 0
    accepted: int = 0
    rejected: int = 0
    replaced: int = 0
    added: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)
    failed: bool = False
    failure_reason: str | None = None

    @property
    def reject_rate(self) -> float:
        return self.rejected / self.computed if self.computed else 0.0

    def summary(self) -> str:
        head = f"[{self.analyzer_id}] 입력 {self.inputs} · 산출 {self.computed} · "
        head += f"유효 {self.accepted} · 격리 {self.rejected} ({self.reject_rate:.1%}) · "
        head += f"교체 {self.replaced} · 신규 {self.added}"
        if self.failed:
            head += f"\n실패: {self.failure_reason}"
        if self.reject_reasons:
            head += "\n격리 사유:"
            for reason, n in sorted(self.reject_reasons.items(), key=lambda x: -x[1])[:5]:
                head += f"\n  {n:>4}건  {reason}"
        return head


def run(analyzer: BaseAnalyzer, *, dry_run: bool = False) -> AnalysisReport:
    """분석 1회 실행.

    dry_run: 아무것도 저장하지 않고 계약 검증만 한다
    """
    report = AnalysisReport(analyzer_id=analyzer.id, started_at=datetime.now(KST))

    records = analyzer.load()
    report.inputs = len(records)

    # 입력 0건은 성공이 아니라 실패다. 조용히 0건을 내면 '분석이 돌았는데 결과가
    # 없다'와 '수집이 안 됐다'를 구분할 수 없다.
    if not records:
        report.failed = True
        report.failure_reason = (
            f"입력 레코드가 0건이다 (기대 kind: {[str(k) for k in analyzer.meta.inputs]}). "
            "수집기를 먼저 돌렸는지 확인하라 — data/records/ 가 비어 있다"
        )
        return report

    accepted: list[Record] = []
    rejected: list[Rejected] = []

    try:
        for result in analyzer.compute(records):
            report.computed += 1
            if isinstance(result, Rejected):
                report.rejected += 1
                key = result.short_reason
                report.reject_reasons[key] = report.reject_reasons.get(key, 0) + 1
                rejected.append(result)
                continue
            report.accepted += 1
            accepted.append(result)
    except AnalyzeError as exc:
        # 개별 항목이 아니라 분석 자체가 불가능한 상태. 부분 저장하지 않는다.
        report.failed = True
        report.failure_reason = str(exc)
        return report

    if report.computed and report.reject_rate > REJECT_RATE_LIMIT:
        report.failed = True
        report.failure_reason = (
            f"격리율 {report.reject_rate:.1%} 가 임계 {REJECT_RATE_LIMIT:.0%} 를 넘었다. "
            "유효분도 저장하지 않는다 — 참조 데이터나 계산을 먼저 확인하라"
        )

    if not dry_run:
        if rejected:
            store.append_rejected(analyzer.id, rejected, report.started_at)
        if accepted and not report.failed:
            report.replaced, report.added = store.upsert_records(analyzer.id, accepted)

    return report
