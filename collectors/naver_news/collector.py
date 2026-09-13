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

from votelink.camp import candidate_queries_for_district, person_terms_for_district
from votelink.collect import BaseCollector, FetchError, ParseResult, RawBatch, polite_client
from votelink.contract.models import Record, to_kst
from votelink.reference.districts import resolve_district
from votelink.reference.news_parties import party_queries_for_geo

from .text import clean_text, match_terms, normalize_url, parse_pub_date, publisher_from_url

ENV_CLIENT_ID = "NAVER_CLIENT_ID"
ENV_CLIENT_SECRET = "NAVER_CLIENT_SECRET"

# 검색어 범위를 좁힌다. 운영자가 캠프 로스터를 막 갱신했을 때, 지명·정당 검색어까지
# 전부 다시 돌리지 않고 후보·상대후보 검색어만 빠르게 재실행하고 싶을 때 쓴다
# (`votelink/web/ops.py` 의 "이 지역구 후보 뉴스만 재수집" 버튼, P-006).
# CLI 인자로 만들지 않는다 — `collect` 서브커맨드는 모든 수집기가 공유하는 generic
# 인터페이스이고, 이건 naver_news 하나만의 관심사다. NAVER_CLIENT_ID 처럼 이미
# 환경변수로 여닫는 값이 있으므로 같은 통로를 쓴다.
ENV_QUERY_SCOPE = "NAVER_NEWS_QUERY_SCOPE"
SCOPE_ALL = "all"
SCOPE_CANDIDATES = "candidates"

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
# 후보 실명은 지리적 모호성이 없다(동명이인 노이즈는 검색어 쪽에서 정당 한정어로 줄인다).
# sigungu_terms(0.7)처럼 흔한 지명과 달리 district_terms 급 특정성을 준다.
CONFIDENCE_PERSON = 0.9


class Collector(BaseCollector):
    id = "naver_news"

    # --- fetch ----------------------------------------------------------------

    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        cfg = self.config
        paging = cfg["paging"]
        display, max_start = int(paging["display"]), int(paging["max_start"])

        with polite_client(self.meta, headers=self._auth_headers()) as client:
            for query in self._queries():
                yield from self._fetch_query(client, query, since, display, max_start)

    def _queries(self) -> list[dict[str, str]]:
        """지명 검색어(손입력) + 캠프 로스터 후보 검색어 + 전역 정당 검색어.

        캠프별로 수집을 쪼개지 않는다 — 이 district 를 관할하는 모든 캠프의 로스터를
        합쳐 한 번만 돈다 (P-001 §5, P-006).

        `NAVER_NEWS_QUERY_SCOPE=candidates` 면 후보 검색어만 돈다 — 지명·정당
        검색어는 건너뛴다. 매칭 사전(`_person_terms` 등)은 범위와 무관하게 항상
        전부 채운다 — 그래야 이 범위로 받은 기사도 스코프 판정·mentioned_* 이
        평소와 똑같이 계산된다.
        """
        cfg = self.config
        district_id = cfg.get("district")
        candidate_queries = candidate_queries_for_district(district_id) if district_id else []

        if os.environ.get(ENV_QUERY_SCOPE) == SCOPE_CANDIDATES:
            return candidate_queries

        queries = list(cfg["queries"]) + candidate_queries
        queries += party_queries_for_geo(cfg["geo_name"])
        return queries

    def _auth_headers(self) -> dict[str, str]:
        client_id = os.environ.get(ENV_CLIENT_ID)
        client_secret = os.environ.get(ENV_CLIENT_SECRET)
        if not client_id or not client_secret:
            raise FetchError(
                f"{ENV_CLIENT_ID}/{ENV_CLIENT_SECRET} 가 없다. "
                "NAVER Cloud Platform 콘솔에서 발급받아라 (docs/SETUP.md §5). "
                "구 developers.naver.com 은 2026-07-31 로 신규 등록이 끝났다"
            )
        # 헤더 이름을 코드에 박지 않는다. 2026년 이관으로 HUB(X-NCP-*)와
        # 레거시(X-Naver-*)가 공존하고, 레거시 키는 2027-06-30 까지만 산다.
        auth = self.config["auth"]
        return {auth["header_id"]: client_id, auth["header_secret"]: client_secret}

    def _fetch_query(
        self,
        client: Any,
        query: dict[str, str],
        since: datetime | None,
        display: int,
        max_start: int,
    ) -> Iterator[RawBatch]:
        cfg = self.config
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
        # 지역 사전·후보명에 하나도 걸리지 않는 기사는 격리가 아니라 필터로 버린다.
        # 계약 위반이 아니라 대상이 아닐 뿐이고, 격리하면 격리율 임계(5%)를 넘겨
        # 수집 전체가 실패한다. ('송파'라는 이름의 인물·회사·아파트 브랜드)
        local = [item for item in items if self._in_scope(item)]
        yield from self.map_items(local, self._to_record)

    def _to_record(self, item: dict[str, Any]) -> Record:
        cfg = self.config
        title = clean_text(item[F_TITLE])
        summary = clean_text(item[F_DESCRIPTION])
        url = normalize_url(item.get(F_ORIGINAL_LINK) or item[F_LINK])
        observed = to_kst(parse_pub_date(item[F_PUB_DATE]))

        haystack = f"{title}\n{summary}"
        district_hits = match_terms(haystack, self._district_terms)
        places = match_terms(haystack, self._district_terms + self._sigungu_terms)
        persons = match_terms(haystack, self._person_terms)
        # 지명이 district 급이면 그걸 우선한다. 지명은 없고 후보 실명만 걸린 기사도
        # district 급 특정성을 준다 — 동명이인 노이즈는 검색어의 정당 한정어로 줄였다.
        confidence = (
            CONFIDENCE_DISTRICT
            if district_hits
            else CONFIDENCE_PERSON
            if persons
            else CONFIDENCE_SIGUNGU
        )

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
            confidence=confidence,
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
                "mentioned_persons": persons,
                # 주제 분류는 해석이다. L2 의 local_issue 파생 레코드가 채운다.
                "topics": [],
            },
        )

    # --- 지역 사전 -------------------------------------------------------------

    def _in_scope(self, item: dict[str, Any]) -> bool:
        """지명 또는 후보 실명 중 하나라도 걸리면 이 district 의 대상으로 본다.

        후보명만 걸리고 지명이 없는 기사(예: "OOO 의원, 국회서 OO법 발의")를 여기서
        버리면 person 쿼리로 찾아놓고도 폐기된다 — person_terms 도 범위 판정 근거다.
        """
        title = item.get(F_TITLE) or ""
        description = item.get(F_DESCRIPTION) or ""
        if not isinstance(title, str) or not isinstance(description, str):
            return False
        haystack = clean_text(f"{title}\n{description}")
        terms = self._district_terms + self._sigungu_terms + self._person_terms
        return bool(match_terms(haystack, terms))

    @cached_property
    def _district_terms(self) -> list[str]:
        """지역구를 특정하는 표현. 걸리면 confidence 가 올라간다.

        districts.yaml 의 행정동명(풍납1동 등)과 meta.yaml 의 표현(풍납동 등)을 합친다.
        뉴스는 보통 법정동·통칭으로 쓰기 때문에 둘 다 필요하다.
        """
        district = resolve_district(self.config["district"])
        terms = {emd.name for emd in district.emd}
        terms.update(self.config.get("district_terms") or [])
        return sorted(terms)

    @cached_property
    def _sigungu_terms(self) -> list[str]:
        return sorted(set(self.config.get("sigungu_terms") or []))

    @cached_property
    def _person_terms(self) -> list[str]:
        """공인 화이트리스트. 일반인 이름은 어떤 경우에도 넣지 않는다 (절대규칙 3).

        meta.yaml 의 손입력 값 + 이 district 를 관할하는 캠프들의 candidates.yaml
        (ours+opponents, 공개 출처 필드)에서 자동 파생된 값의 합집합이다 (P-006).
        """
        terms = set(self.config.get("person_terms") or [])
        district_id = self.config.get("district")
        if district_id:
            terms.update(person_terms_for_district(district_id))
        return sorted(terms)
