"""선거구 뉴스 펄스 분석기.

load:    news_article 레코드를 디스크에서 읽는다 (네트워크 금지)
compute: 그 선거구 시군구의 기사를 주 단위로 접어 news_pulse 레코드 1건 (순수 함수)
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any

from votelink.analyze import AnalyzeError, BaseAnalyzer, ComputeResult
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record
from votelink.reference import District, resolve_district

from .calc import Article, fold_weeks, is_backfill_distorted, week_start_of

PROFILE_TYPE = "news_pulse"
DISTRICT_CONFIDENCE = 0.9
"""L1(naver_news)이 행정동·통칭을 직접 때렸을 때 매기는 신뢰도. 그 아래는 구 단위."""
TOP_N = 10


class Analyzer(BaseAnalyzer):
    id = "news_pulse"

    def compute(self, records: list[Record]) -> Iterator[ComputeResult]:
        if not records:
            raise AnalyzeError("입력 레코드가 0건이다. 먼저 naver_news 를 돌려라")

        district = resolve_district(self.config["district"])
        sigungu_codes = {f"{c[:4]}000000" for c in district.emd_codes}
        if not sigungu_codes:
            raise AnalyzeError(
                f"{district.id}: districts.yaml 의 emd[].code 가 비어 시군구 코드를 못 만든다"
            )

        articles = [
            r for r in records if r.kind is RecordKind.NEWS_ARTICLE and r.geo_code in sigungu_codes
        ]
        if not articles:
            raise AnalyzeError(
                f"{district.id} 시군구({sorted(sigungu_codes)})에 속한 news_article 이 없다"
            )

        unit = self._fold(articles, district, sigungu_codes)
        # map_items 로 감싸 계산 중 예외가 나도 빈 산출이 아니라 격리로 드러나게 한다.
        yield from self.map_items([unit], self._to_record)

    # --- 계산 (순수) --------------------------------------------------------

    def _fold(
        self, articles: list[Record], district: District, sigungu_codes: set[str]
    ) -> dict[str, Any]:
        window_weeks = int(self.cfg("window_weeks", 12))

        folded = fold_weeks(
            [
                Article(
                    week_start=week_start_of(r.observed_at.date()),
                    publisher=str(r.payload["publisher"]),
                    district_specific=r.confidence >= DISTRICT_CONFIDENCE,
                    record_id=r.record_id,
                )
                for r in articles
            ],
            history_weeks=int(self.cfg("history_weeks", 8)),
            min_history_weeks=int(self.cfg("min_history_weeks", 8)),
            spike_z_threshold=float(self.cfg("spike_z_threshold", 2.0)),
        )
        kept = folded[-window_weeks:]
        kept_ids = {rid for p in kept for rid in p["_record_ids"]}
        kept_records = [r for r in articles if r.record_id in kept_ids]

        observed_at = max(r.observed_at for r in kept_records)
        counts = [p["article_count"] for p in kept]

        return {
            "geo_code": min(sigungu_codes),
            "geo_name": district.sigungu,
            "observed_at": observed_at,
            "derived_from": sorted(kept_ids),
            "payload": {
                "as_of": observed_at.strftime("%Y-%m"),
                "window_weeks": window_weeks,
                "weekly": [{k: v for k, v in p.items() if k != "_record_ids"} for p in kept],
                "total_articles": sum(counts),
                "top_places": _tally(kept_records, "mentioned_places"),
                "top_persons": _tally(kept_records, "mentioned_persons"),
                "top_publishers": _tally_publisher(kept_records),
                "backfill_distorted": is_backfill_distorted(
                    counts, ratio=float(self.cfg("backfill_distortion_ratio", 3.0))
                ),
            },
        }

    def _to_record(self, unit: dict[str, Any]) -> Record:
        return Record(
            kind="news_pulse",
            collector_id=self.id,  # 분석기 id. 입력을 만든 naver_news 가 아니다
            source_name="votelink 분석 (naver_news)",
            source_url=None,
            source_license="public_open",
            # 가장 최근 기사의 시점. 분석을 돌린 시각이 아니다.
            observed_at=unit["observed_at"],
            observed_precision="day",
            geo_level="sigungu",
            geo_code=unit["geo_code"],
            geo_name=unit["geo_name"],
            # 파생이고, 표본이 지명 매칭이라 스포츠·연예를 포함한다 (그 필터는 issue_ranker).
            confidence=0.6,
            derived_from=unit["derived_from"],
            natural_key=f"{PROFILE_TYPE}|{unit['geo_code']}|{unit['payload']['as_of']}",
            payload=unit["payload"],
        )


def _tally(records: list[Record], field: str) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for r in records:
        counter.update(str(x) for x in r.payload.get(field, []))
    return _top(counter)


def _tally_publisher(records: list[Record]) -> list[dict[str, Any]]:
    counter = Counter(str(r.payload["publisher"]) for r in records)
    return _top(counter)


def _top(counter: Counter[str]) -> list[dict[str, Any]]:
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]
    return [{"term": term, "count": n} for term, n in ordered]
