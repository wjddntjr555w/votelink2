"""이슈 × 후보 교차표 분석기.

load:    디스크에서 news_article 을 읽는다 (네트워크 금지)
compute: news_article + 이슈 어휘집 + 캠프 로스터 -> issue_candidate_matrix (순수 함수)

제안서: docs/proposals/A-007-issue-candidate-matrix.md
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.camp.roster_terms import camps_covering_district
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record
from votelink.reference import resolve_district

from . import calc

PROFILE_TYPE = "issue_candidate_matrix"


class Analyzer(BaseAnalyzer):
    id = "issue_candidate_matrix"

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
            raise AnalyzeError(
                f"'{district.id}' 를 관할하는 캠프가 없다 — 로스터 없이는 후보를 특정할 수 없다"
            )
        candidates = calc.merge_rosters(rosters)

        try:
            lexicon = calc.load_lexicon()
        except FileNotFoundError as exc:
            # 참조 데이터 결손은 전체 중단이다 (docs/30-analysis-spec.md §6).
            raise AnalyzeError(str(exc)) from exc

        yield from self.map_items(
            [(district, sigungu_codes, news, candidates, lexicon)], self._to_record
        )

    def _to_record(self, unit: tuple[Any, set[str], list[Record], list, calc.Lexicon]) -> Record:
        district, sigungu_codes, news, candidates, lexicon = unit

        window_weeks = int(self.cfg("window_weeks", 12))
        latest = max(r.observed_at for r in news)
        window_start = latest.date() - timedelta(weeks=window_weeks)
        windowed = [r for r in news if r.observed_at.date() >= window_start]

        category_totals: dict[str, int] = {}
        category_labels = {c.key: c.label for c in lexicon.categories}
        cell_counts: dict[tuple[str, str], int] = {}
        derived_from: list[str] = []
        seen_ids: set[str] = set()

        for r in windowed:
            payload = r.payload
            haystack = f"{payload.get('title', '')} {payload.get('summary', '')}"
            cats = calc.match_categories(haystack, lexicon)
            for cat_key in cats:
                category_totals[cat_key] = category_totals.get(cat_key, 0) + 1
            if not cats:
                continue

            persons = set(payload.get("mentioned_persons") or [])
            hit_candidates = [c for c in candidates if c.name in persons]
            if not hit_candidates:
                continue

            if r.record_id not in seen_ids:
                seen_ids.add(r.record_id)
                derived_from.append(r.record_id)
            for cand in hit_candidates:
                for cat_key in cats:
                    key = (cat_key, cand.name)
                    cell_counts[key] = cell_counts.get(key, 0) + 1

        qualifying_categories = sorted({cat_key for cat_key, _ in cell_counts})
        if not qualifying_categories:
            raise ValueError(
                f"'{district.id}' 에서 이슈 카테고리와 후보 언급이 동시에 걸리는 기사가 없다 "
                "(어휘집이 이 지역 어휘가 아니거나, 후보 매칭이 안 됐을 수 있다)"
            )

        categories_payload = []
        for cat_key in qualifying_categories:
            article_count = category_totals[cat_key]
            hits = [
                {
                    "name": cand.name,
                    "is_ours": cand.is_ours,
                    "count": cell_counts[(cat_key, cand.name)],
                    "share_of_category": round(
                        cell_counts[(cat_key, cand.name)] / article_count * 100, 1
                    ),
                }
                for cand in candidates
                if cell_counts.get((cat_key, cand.name), 0) > 0
            ]
            hits.sort(key=lambda h: h["count"], reverse=True)
            categories_payload.append(
                {
                    "category": cat_key,
                    "label": category_labels[cat_key],
                    "article_count": article_count,
                    "candidates": hits,
                }
            )
        # article_count 내림차순 (계약)
        categories_payload.sort(key=lambda c: c["article_count"], reverse=True)

        as_of = latest.strftime("%Y-%m")
        geo_code = sorted(sigungu_codes)[0]

        return Record(
            kind="issue_candidate_matrix",
            collector_id=self.id,
            source_name="votelink 분석 (naver_news + issue_lexicon + 캠프 로스터)",
            source_url=None,
            source_license="public_open",
            observed_at=latest,
            observed_precision="day",
            geo_level="sigungu",
            geo_code=geo_code,
            geo_name=district.sigungu,
            # 이슈 매칭(어휘집 substring)과 후보 매칭(이름 정확 일치) 두 가지 오탐
            # 위험이 곱해진다 — candidate_mention_share(0.7)보다 낮게 둔다.
            confidence=0.6,
            derived_from=sorted(derived_from),
            natural_key=f"{PROFILE_TYPE}|{geo_code}|{as_of}",
            payload={
                "as_of": as_of,
                "window_weeks": window_weeks,
                "lexicon_version": lexicon.version,
                "total_articles": len(windowed),
                "categories": categories_payload,
            },
        )
