"""선거구 등록 후보별 주간 뉴스 언급 비교 분석기.

load:    디스크에서 news_article 을 읽는다 (네트워크 금지)
compute: news_article + 캠프 로스터 -> candidate_mention_share (순수 함수)

제안서: docs/proposals/A-006-candidate-mention-share.md
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.camp.roster_terms import camps_covering_district
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record
from votelink.reference import resolve_district

from . import calc

PROFILE_TYPE = "candidate_mention_share"


class Analyzer(BaseAnalyzer):
    id = "candidate_mention_share"

    # load() 는 기본 구현으로 충분하다 — meta.inputs(news_article) 를 전부 읽고
    # 자기 출력은 뺀다.

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        if not records:
            raise AnalyzeError("입력 레코드가 0건이다. 먼저 수집기를 돌려라")

        district = resolve_district(self.config["district"])
        sigungu_codes = set(district.sigungu_codes)
        news = [
            r for r in records if r.kind is RecordKind.NEWS_ARTICLE and r.geo_code in sigungu_codes
        ]
        if not news:
            raise AnalyzeError(
                f"'{district.id}' 시군구({sorted(sigungu_codes)})에 속한 news_article 이 없다"
            )

        rosters = camps_covering_district(district.id)
        if not rosters:
            # 캠프가 아직 없는 district 는 오류가 아니라 자연스러운 상태다(온보딩 전).
            # 다만 이 분석기는 로스터 없이는 산출물 자체를 만들 수 없다.
            raise AnalyzeError(
                f"'{district.id}' 를 관할하는 캠프가 없다 — 로스터 없이는 후보를 특정할 수 없다"
            )
        candidates = calc.merge_rosters(rosters)

        # map_items 로 감싼다 — 선거구당 산출은 1건이지만 형태는 다른 분석기와
        # 맞춘다(news_pulse/issue_ranker). 실패해도 Rejected 로 격리된다.
        yield from self.map_items([(district, sigungu_codes, news, candidates)], self._to_record)

    def _to_record(self, unit: tuple[Any, set[str], list[Record], list]) -> Record:
        district, sigungu_codes, news, candidates = unit

        window_weeks = int(self.cfg("window_weeks", 12))
        backfill_ratio = float(self.cfg("backfill_distortion_ratio", 3.0))

        latest = max(r.observed_at for r in news)
        weeks = calc.recent_weeks(latest.date(), window_weeks)

        candidate_payloads = []
        derived_from: list[str] = []
        seen_ids: set[str] = set()
        weekly_totals = [0] * len(weeks)

        # 1차: 후보별 주간 집계 (share_pct 는 그 주 전체 합이 필요하므로 2차에서 채운다)
        per_candidate: list[tuple] = []
        for cand in candidates:
            matches = [
                (calc.week_start(r.observed_at), r.record_id)
                for r in news
                if cand.name in (r.payload.get("mentioned_persons") or [])
            ]
            tallies, used_ids = calc.tally_weeks(weeks, matches)
            for i, t in enumerate(tallies):
                weekly_totals[i] += t.count
            for rid in used_ids:
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    derived_from.append(rid)
            per_candidate.append((cand, tallies))

        for cand, tallies in per_candidate:
            weekly = []
            prev_count = None
            for i, t in enumerate(tallies):
                weekly.append(
                    {
                        "week_start": t.week.isoformat(),
                        "article_count": t.count,
                        "share_pct": calc.share_pct(t.count, weekly_totals[i]),
                        "wow_change_pct": (
                            None if prev_count is None else calc.wow_change_pct(t.count, prev_count)
                        ),
                    }
                )
                prev_count = t.count
            candidate_payloads.append(
                {
                    "name": cand.name,
                    "party": cand.party,
                    "lineage": cand.lineage,
                    "is_ours": cand.is_ours,
                    "weekly": weekly,
                    "total_articles": sum(t.count for t in tallies),
                }
            )

        if not derived_from:
            raise ValueError(
                f"'{district.id}' 에서 등록 후보 어느 이름도 매치된 기사가 없다 "
                "(mentioned_persons 미반영이거나 동명이인 불일치)"
            )

        total_articles = sum(c["total_articles"] for c in candidate_payloads)
        as_of = latest.strftime("%Y-%m")
        # 두 시군구에 걸치면 사전순 첫 코드 (news_pulse 와 동일 규칙)
        geo_code = sorted(sigungu_codes)[0]

        return Record(
            kind="candidate_mention_share",
            collector_id=self.id,
            source_name="votelink 분석 (naver_news 후보 언급 집계)",
            source_url=None,
            source_license="public_open",
            observed_at=latest,
            observed_precision="day",
            geo_level="sigungu",
            geo_code=geo_code,
            geo_name=district.sigungu,
            # 후보명 정확 문자열 일치만 본다 — 동명이인·약칭 오탐 위험이 있어
            # news_pulse/issue_ranker(0.8 내외)보다 낮게 둔다 (A-006 §제약).
            confidence=0.7,
            derived_from=sorted(derived_from),
            natural_key=f"{PROFILE_TYPE}|{geo_code}|{as_of}",
            payload={
                "as_of": as_of,
                "window_weeks": window_weeks,
                "candidates": candidate_payloads,
                "total_articles": total_articles,
                "backfill_distorted": calc.is_backfill_distorted(weekly_totals, backfill_ratio),
            },
        )
