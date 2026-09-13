"""수집 실행기 — docs/20-collector-spec.md §6 실패 처리를 구현한다.

핵심: 격리율이 임계를 넘으면 유효분도 커밋하지 않는다.
5%가 조용히 누락되면 그 5%가 어느 동네인지 아무도 모른 채 전략에서 빠진다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from votelink.collect import storage
from votelink.collect.base import BaseCollector, Rejected
from votelink.contract.models import KST, Record
from votelink.store import DataSpace, upsert_records

log = logging.getLogger(__name__)

REJECT_RATE_LIMIT = 0.05


@dataclass
class RunReport:
    collector_id: str
    started_at: datetime
    batches: int = 0
    parsed: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    written: int = 0
    raw_files: list[str] = field(default_factory=list)
    reject_reasons: dict[str, int] = field(default_factory=dict)
    failed: bool = False
    failure_reason: str | None = None

    @property
    def reject_rate(self) -> float:
        return self.rejected / self.parsed if self.parsed else 0.0

    def summary(self) -> str:
        head = f"[{self.collector_id}] 배치 {self.batches} · 파싱 {self.parsed} · "
        head += f"유효 {self.accepted} · 격리 {self.rejected} ({self.reject_rate:.1%}) · "
        head += f"중복 {self.duplicates} · 저장 {self.written}"
        if self.failed:
            head += f"\n실패: {self.failure_reason}"
        if self.reject_reasons:
            head += "\n격리 사유:"
            for reason, n in sorted(self.reject_reasons.items(), key=lambda x: -x[1])[:5]:
                head += f"\n  {n:>4}건  {reason}"
        return head


def run(
    collector: BaseCollector,
    *,
    space: DataSpace,
    since: datetime | None = None,
    dry_run: bool = False,
    reparse: bool = False,
) -> RunReport:
    """수집 1회 실행.

    space: 어느 데이터 공간에 읽고 쓰는가. 기본값을 두지 않는다 (`P-001` §10)
    dry_run: 아무것도 저장하지 않고 계약 검증만 한다
    reparse: 네트워크를 타지 않고 저장된 raw 만 다시 파싱한다
    """
    report = RunReport(collector_id=collector.id, started_at=datetime.now(KST))

    batches = (
        storage.iter_raw(collector.id, space, since)
        if reparse
        else _fetch_and_persist(collector, since, dry_run, report, space)
    )

    accepted: list[Record] = []
    rejected: list[Rejected] = []
    seen: set[str] = (
        set() if (dry_run or reparse) else storage.existing_record_ids(collector.id, space)
    )

    for batch in batches:
        report.batches += 1
        for result in collector.parse(batch):
            report.parsed += 1
            if isinstance(result, Rejected):
                report.rejected += 1
                key = result.short_reason
                report.reject_reasons[key] = report.reject_reasons.get(key, 0) + 1
                rejected.append(result)
                continue
            if result.record_id in seen:
                report.duplicates += 1
                continue
            seen.add(result.record_id)
            report.accepted += 1
            accepted.append(result)

    if report.parsed and report.reject_rate > REJECT_RATE_LIMIT:
        report.failed = True
        report.failure_reason = (
            f"격리율 {report.reject_rate:.1%} 가 임계 {REJECT_RATE_LIMIT:.0%} 를 넘었다. "
            "유효분도 저장하지 않는다 — 파서나 출처 형식을 먼저 확인하라"
        )

    if not dry_run:
        if rejected:
            storage.append_rejected(collector.id, rejected, report.started_at, space)
        if accepted and not report.failed:
            if reparse:
                # 같은 record_id 를 append 하면 중복이 쌓인다 (D-007). 이 owner_id
                # 파일은 다른 선거구가 채운 record_id 와 공유될 수 있으므로(예:
                # naver_news 는 선거구별로 같은 파일에 쌓인다, docs/11-storage.md §2)
                # 파일 전체를 이 실행 결과로 교체하지 않는다 — upsert 로 일치하는
                # record_id 만 갈아끼우고 나머지 줄은 보존한다.
                upsert_records(collector.id, accepted, space)
            else:
                storage.append_records(collector.id, accepted, space)
            report.written = len(accepted)

    return report


def _fetch_and_persist(
    collector: BaseCollector,
    since: datetime | None,
    dry_run: bool,
    report: RunReport,
    space: DataSpace,
):
    """fetch 결과를 흘려보내면서 즉시 raw 로 저장한다.

    parse 가 터져도 원본은 이미 디스크에 있어야 한다. 그래야 --reparse 로 복구된다.
    """
    for batch in collector.fetch(since):
        if not dry_run:
            path = storage.write_raw(batch, space)
            report.raw_files.append(str(path))
        yield batch
