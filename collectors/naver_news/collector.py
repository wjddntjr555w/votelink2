"""네이버 뉴스 검색 수집기 — 송파구 지역 기사 메타.

fetch: 검색 API 페이지를 가공 없이 받는다
parse: 원본 -> news_article 레코드 (네트워크 금지, 순수 함수)

제안서: docs/proposals/C-003-naver-news.md
본문 전문은 저장하지 않는다. 링크 + 메타 + 출처가 준 스니펫까지다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from functools import cached_property
from typing import Any

from votelink.collect import BaseCollector, FetchError, ParseResult, RawBatch, polite_client
from votelink.contract.models import Record, to_kst
from votelink.reference.districts import resolve_district

from .text import clean_text, match_terms, normalize_url, parse_pub_date, publisher_from_url

ENV_CLIENT_ID = "NAVER_CLIENT_ID"
ENV_CLIENT_SECRET = "NAVER_CLIENT_SECRET"

# 응답 필드명. fixture 없이 공식 문서만 보고 구현했으므로 한 곳에 모아 둔다.
# 실제 응답이 다르면 여기만 고치면 된다.
F_ITEMS = "items"
F_TITLE = "title"
F_ORIGINAL_LINK = "originallink"
F_LINK = "link"
F_DESCRIPTION = "description"
F_PUB_DATE = "pubDate"

# 계약(NewsArticlePayload.summary)의 상한. 넘으면 자른다.
SUMMARY_MAX = 600

CONFIDENCE_DISTRICT = 0.9  # 지역구 안의 동·지명이 직접 나온 기사
CONFIDENCE_SIGUNGU = 0.7  # 구 단위 표현만 나온 기사


class Collector(BaseCollector):
    id = "naver_news"

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        cfg = self.meta.config
        paging = cfg["paging"]
        display, max_start = int(paging["display"]), int(paging["max_start"])

        with polite_client(self.meta, headers=self._auth_headers()) as client:
            for query in cfg["queries"]:
                yield from self._fetch_query(client, query, since, display, max_start)

    def _auth_headers(self) -> dict[str, str]:
        client_id = os.environ.get(ENV_CLIENT_ID)
        client_secret = os.environ.get(ENV_CLIENT_SECRET)
        if not client_id or not client_secret:
            raise FetchError(
                f"{ENV_CLIENT_ID}/{ENV_CLIENT_SECRET} 가 없다. "
                "developers.naver.com 에서 애플리케이션을 등록해 발급받아라 (docs/SETUP.md)"
            )
        return {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}

    def _fetch_query(
        self,
        client: Any,
        query: dict[str, str],
        since: datetime | None,
        display: int,
        max_start: int,
    ) -> Iterator[RawBatch]:
        cfg = self.meta.config
        start = 1
        page = 1
        while start <= max_start:
            resp = client.get(
                cfg["endpoint"],
                params={
                    "query": query["q"],
                    "display": display,
                    "start": start,
                    "sort": cfg["sort"],
                },
            )
            body = resp.json()
            # batch_key 는 파일명이 된다. 한글은 slugify 에서 전부 사라져 서로 뭉개지므로
            # 검색어마다 ascii id 를 두고 그걸 쓴다.
            yield RawBatch(
                collector_id=self.id,
                body=body,
                batch_key=f"{query['id']}-p{page:03d}",
                source_url=str(resp.url),
            )

            items = body.get(F_ITEMS) or []
            if len(items) < display:
                break
            # 검색 API 에 기간 파라미터가 없다. sort=date 로 최신순을 받다가
            # since 보다 오래된 페이지에 닿으면 멈춘다. 응답을 가공하지는 않는다 —
            # 다음 페이지를 요청할지만 정하는 판단이다.
            if since and self._page_is_older_than(items, since):
                break
            start += display
            page += 1

    @staticmethod
    def _page_is_older_than(items: list[dict[str, Any]], since: datetime) -> bool:
        """페이지의 모든 기사가 since 이전이면 더 받을 게 없다."""
        newest = None
        for item in items:
            try:
                published = parse_pub_date(item[F_PUB_DATE])
            except (KeyError, TypeError, ValueError):
                return False  # 시각을 못 읽으면 멈출 근거가 없다. 계속 받는다
            if newest is None or published > newest:
                newest = published
        return newest is not None and newest < to_kst(since)

    # --- parse ----------------------------------------------------------------

    def parse(self, raw: RawBatch) -> Iterator[ParseResult]:
        items = raw.body.get(F_ITEMS) or []
        # 지역 사전에 하나도 걸리지 않는 기사는 격리가 아니라 필터로 버린다.
        # 계약 위반이 아니라 대상이 아닐 뿐이고, 격리하면 격리율 임계(5%)를 넘겨
        # 수집 전체가 실패한다. ('송파'라는 이름의 인물·회사·아파트 브랜드)
        local = [item for item in items if self._mentions_region(item)]
        yield from self.map_items(local, self._to_record)

    def _to_record(self, item: dict[str, Any]) -> Record:
        cfg = self.meta.config
        title = clean_text(item[F_TITLE])
        summary = clean_text(item[F_DESCRIPTION])
        url = normalize_url(item.get(F_ORIGINAL_LINK) or item[F_LINK])
        observed = to_kst(parse_pub_date(item[F_PUB_DATE]))

        haystack = f"{title}\n{summary}"
        district_hits = match_terms(haystack, self._district_terms)
        places = match_terms(haystack, self._district_terms + self._sigungu_terms)

        return Record(
            kind="news_article",
            collector_id=self.id,
            source_name=self.meta.source_name,
            source_url=url,
            source_license=self.meta.source_license,
            observed_at=observed,
            observed_precision="minute",
            geo_level="sigungu",
            # 기사 하나는 행정동 하나에 속하지 않는다. 동 단위 귀속은 추정이고
            # 추정은 L1 의 일이 아니다 — L2 가 mentioned_places 로 파생 레코드를 만든다.
            geo_code=str(cfg["sigungu_code"]),
            geo_name=cfg["geo_name"],
            confidence=CONFIDENCE_DISTRICT if district_hits else CONFIDENCE_SIGUNGU,
            derived_from=[],
            # 같은 기사가 여러 검색어에 걸려도 record_id 가 같아 자동으로 하나가 된다.
            natural_key=url,
            payload={
                "title": title,
                "publisher": publisher_from_url(url, cfg.get("publisher_names") or {}),
                "published_at": observed.isoformat(),
                "url": url,
                # LLM 요약이 아니라 출처가 준 description 스니펫이다.
                "summary": summary[:SUMMARY_MAX],
                "full_text_stored": False,
                "mentioned_places": places,
                "mentioned_persons": match_terms(haystack, self._person_terms),
                # 주제 분류는 해석이다. L2 의 local_issue 파생 레코드가 채운다.
                "topics": [],
            },
        )

    # --- 지역 사전 -------------------------------------------------------------

    def _mentions_region(self, item: dict[str, Any]) -> bool:
        title = item.get(F_TITLE) or ""
        description = item.get(F_DESCRIPTION) or ""
        if not isinstance(title, str) or not isinstance(description, str):
            return False
        haystack = clean_text(f"{title}\n{description}")
        return bool(match_terms(haystack, self._district_terms + self._sigungu_terms))

    @cached_property
    def _district_terms(self) -> list[str]:
        """지역구를 특정하는 표현. 걸리면 confidence 가 올라간다.

        districts.yaml 의 행정동명(풍납1동 등)과 meta.yaml 의 표현(풍납동 등)을 합친다.
        뉴스는 보통 법정동·통칭으로 쓰기 때문에 둘 다 필요하다.
        """
        district = resolve_district(self.meta.config["district"])
        terms = {emd.name for emd in district.emd}
        terms.update(self.meta.config.get("district_terms") or [])
        return sorted(terms)

    @cached_property
    def _sigungu_terms(self) -> list[str]:
        return sorted(set(self.meta.config.get("sigungu_terms") or []))

    @cached_property
    def _person_terms(self) -> list[str]:
        """공인 화이트리스트. 일반인 이름은 어떤 경우에도 넣지 않는다 (절대규칙 3)."""
        return sorted(set(self.meta.config.get("person_terms") or []))
