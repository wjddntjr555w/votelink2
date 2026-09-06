"""선거구 이슈 랭커.

load:    news_article 레코드를 디스크에서 읽는다 (네트워크 금지)
compute: 그 선거구 시군구의 기사를 어휘집으로 분류해 local_issue 레코드 1건 (순수 함수)

어휘집(data/reference/issue_lexicon.yaml)이 곧 편집 판단이므로 그 version 을
payload 에 박는다. LLM 을 쓰지 않는다 — 순수 substring 매칭이라 재현 가능하다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record, Rejected
from votelink.reference import District, resolve_district
from votelink.reference.issue_lexicon import Lexicon, LexiconError, load_lexicon

from .calc import (
    Article,
    build_window,
    classify,
    is_backfill_distorted,
    recency_score,
    sample_headlines,
    top_places,
    trend_of,
    week_counts_all,
    week_counts_classified,
    week_counts_for,
    week_start_of,
)

PROFILE_TYPE = "local_issue"
SOURCE_NAME = "votelink 분석 (naver_news + issue_lexicon)"
CONFIDENCE = 0.5
"""파생이고, 어휘집 매칭이라는 거친 분류가 한 단계 더 들어갔으며, 표본이 '송파'=지명
매칭이라 스포츠·연예 노이즈를 포함한다. news_pulse(0.6)보다 낮다."""
ISOLATION_LIMIT = 0.05


class Analyzer(BaseAnalyzer):
    id = "issue_ranker"

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        if not records:
            raise AnalyzeError("입력 레코드가 0건이다. 먼저 naver_news 를 돌려라")

        district = resolve_district(self.config["district"])
        sigungu_codes = {f"{c[:4]}000000" for c in district.emd_codes}
        if not sigungu_codes:
            raise AnalyzeError(
                f"{district.id}: districts.yaml 의 emd[].code 가 비어 시군구 코드를 못 만든다"
            )

        try:
            lexicon = load_lexicon()
        except (FileNotFoundError, LexiconError) as exc:
            # 참조 데이터 결손은 전체 중단이다. 조용히 빈 산출을 내지 않는다.
            raise AnalyzeError(f"이슈 어휘집을 읽을 수 없다: {exc}") from exc

        min_conf = float(self.cfg("min_confidence", 0.7))
        raw = [
            r
            for r in records
            if r.kind is RecordKind.NEWS_ARTICLE
            and r.geo_code in sigungu_codes
            and r.confidence >= min_conf
        ]
        if not raw:
            raise AnalyzeError(
                f"{district.id} 시군구({sorted(sigungu_codes)}) · confidence>={min_conf} 인 "
                "news_article 이 없다"
            )

        articles, rejected = self._parse_articles(raw, lexicon)
        if rejected and len(rejected) / len(raw) > ISOLATION_LIMIT:
            raise AnalyzeError(
                f"기사 분류 격리율 {len(rejected) / len(raw):.1%} > "
                f"{ISOLATION_LIMIT:.0%}. 어휘집·payload 를 확인하라"
            )

        unit = self._fold(articles, district, sigungu_codes, lexicon, {r.record_id: r for r in raw})
        yield from self.map_items([unit], self._to_record)
        # 격리된 기사도 data/rejected/ 로 남긴다 — 조용한 누락을 만들지 않는다.
        yield from rejected

    # --- 파싱 (레코드 → calc.Article) -------------------------------------------

    def _parse_articles(
        self, raw: list[Record], lexicon: Lexicon
    ) -> tuple[list[Article], list[Rejected]]:
        cats = [(c.key, tuple(c.keywords)) for c in lexicon.categories]
        articles: list[Article] = []
        rejected: list[Rejected] = []
        for r in raw:
            try:
                p = r.payload
                title = str(p["title"])
                summary = str(p.get("summary", ""))
                articles.append(
                    Article(
                        week_start=week_start_of(r.observed_at.date()),
                        title=title,
                        summary=summary,
                        published_at=str(p.get("published_at", r.observed_at.isoformat())),
                        url=str(p.get("url", "")),
                        places=tuple(str(x) for x in p.get("mentioned_places", [])),
                        record_id=r.record_id,
                        categories=classify(title, summary, cats),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - 개별 기사 격리가 목적
                rejected.append(
                    Rejected(reason=f"{type(exc).__name__}: {exc}", raw_item=r.record_id)
                )
        return articles, rejected

    # --- 계산 (순수) --------------------------------------------------------

    def _fold(
        self,
        articles: list[Article],
        district: District,
        sigungu_codes: set[str],
        lexicon: Lexicon,
        by_id: dict[str, Record],
    ) -> dict[str, Any]:
        window_weeks = int(self.cfg("window_weeks", 12))
        half_life = float(self.cfg("half_life_weeks", 4))
        rising = float(self.cfg("trend_rising_ratio", 1.3))
        falling = float(self.cfg("trend_falling_ratio", 0.77))
        top_n = int(self.cfg("top_places_n", 5))
        headline_limit = int(self.cfg("sample_headlines_limit", 3))

        window = build_window(articles, window_weeks=window_weeks)
        kept_ids = sorted(a.record_id for a in window.kept)  # unclassified 포함
        if not kept_ids:
            raise AnalyzeError("창 자르기 후 남은 기사가 0건이다")

        observed_at = max(by_id[rid].observed_at for rid in kept_ids)
        total = len(window.kept)
        classified_total = sum(1 for a in window.kept if a.categories)
        unclassified = total - classified_total

        total_counts = week_counts_classified(window)
        issues: list[dict[str, Any]] = []
        for cat in lexicon.categories:
            members = [a for a in window.kept if cat.key in a.categories]
            if not members:
                continue
            counts = week_counts_for(cat.key, window)
            issues.append(
                {
                    "category": cat.key,
                    "label": cat.label,
                    "article_count": len(members),
                    "share": round(len(members) * 100.0 / classified_total, 2)
                    if classified_total
                    else 0.0,
                    "recency_score": round(recency_score(counts, half_life_weeks=half_life), 4),
                    "trend": trend_of(
                        counts, total_counts, rising_ratio=rising, falling_ratio=falling
                    ).value,
                    "top_places": top_places(members, top_n=top_n),
                    "sample_headlines": sample_headlines(members, limit=headline_limit),
                }
            )
        issues.sort(key=lambda d: (-d["recency_score"], d["category"]))

        return {
            "geo_code": min(sigungu_codes),
            "geo_name": district.sigungu,
            "observed_at": observed_at,
            "derived_from": kept_ids,
            "payload": {
                "as_of": observed_at.strftime("%Y-%m"),
                "window_weeks": window_weeks,
                "total_articles": total,
                "issues": issues,
                "unclassified_count": unclassified,
                "lexicon_version": lexicon.version,
                "backfill_distorted": is_backfill_distorted(
                    week_counts_all(window),
                    ratio=float(self.cfg("backfill_distortion_ratio", 3.0)),
                ),
            },
        }

    def _to_record(self, unit: dict[str, Any]) -> Record:
        return Record(
            kind="local_issue",
            collector_id=self.id,  # 분석기 id. 입력을 만든 naver_news 가 아니다
            source_name=SOURCE_NAME,
            source_url=None,
            source_license="api_tos",  # 기사가 네이버 검색 API ToS 출처다 — 정직하게 상속
            # 가장 최근 기사의 시점. 분석을 돌린 시각이 아니다.
            observed_at=unit["observed_at"],
            observed_precision="day",
            geo_level="sigungu",
            geo_code=unit["geo_code"],
            geo_name=unit["geo_name"],
            confidence=CONFIDENCE,
            derived_from=unit["derived_from"],
            natural_key=f"{PROFILE_TYPE}|{unit['geo_code']}|{unit['payload']['as_of']}",
            payload=unit["payload"],
        )
