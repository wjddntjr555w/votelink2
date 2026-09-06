"""뉴스 원문 목록 화면 (`/d/<선거구>/news`).

분석기가 없는 화면이다. L1 이 수집한 `news_article` 레코드를 구 단위로 걸러
표로 늘어놓고 원문 링크로만 보낸다. 여기서 지키는 것 둘:

- 선거구 소속 필터는 **시군구 코드**로 한다 (기사 geo_level 이 sigungu 라
  emd 코드 목록으로 매칭하는 `District.contains` 가 안 잡는다).
- 규칙 5 — 정책표에 news_article 이 없거나 unreviewed 면 경고가 표 위에 붙는다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_record
from tests.test_web_loader import write_districts
from votelink import store
from votelink.contract.models import KST, Record
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.reference.compliance import load_policy
from votelink.web.app import create_app
from votelink.web.loader import load_news
from votelink.web.settings import WebSettings
from votelink.web.viewmodel import build_news_view

INSIDE = "1171000000"  # 시험구 (CODES 의 시군구 코드)
OUTSIDE = "1168000000"  # 옆 자치구

POLICY_UNREVIEWED = (
    "election_day: null\n"
    "outputs:\n"
    "  - kind: news_article\n"
    "    risk: low\n"
    "    status: unreviewed\n"
    '    note: "메타만 저장 · 원문 링크로만 연결"\n'
)
POLICY_EMPTY = "election_day: null\noutputs: []\n"


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def news_record(
    url: str,
    *,
    geo_code: str = INSIDE,
    confidence: float = 0.7,
    publisher: str = "가상일보",
    published_at: str = "2026-09-06T12:00:00+09:00",
    places: list[str] | None = None,
    persons: list[str] | None = None,
) -> Record:
    hh, mm = published_at[11:13], published_at[14:16]
    return make_record(
        kind="news_article",
        geo_level="sigungu",
        geo_code=geo_code,
        geo_name="서울 송파구",
        confidence=confidence,
        observed_at=datetime(2026, 9, 6, int(hh), int(mm), tzinfo=KST),
        ingested_at=datetime(2026, 9, 7, 0, 0, tzinfo=KST),
        natural_key=url,
        source_url=url,
        payload={
            "title": f"제목 {url[-1]}",
            "publisher": publisher,
            "published_at": published_at,
            "url": url,
            "summary": "요약.",
            "mentioned_places": places or ["송파구"],
            "mentioned_persons": persons or [],
        },
    )


def settings_for(tmp_path, records, policy: str = POLICY_UNREVIEWED) -> WebSettings:
    store.append_records("naver_news", records, root=tmp_path / "records")
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        records_root=tmp_path / "records",
        policy_path=policy_path,
    )


def client(tmp_path, records, policy: str = POLICY_UNREVIEWED) -> TestClient:
    app = create_app(settings_for(tmp_path, records, policy))
    return TestClient(app, raise_server_exceptions=False)


# --- 로더 -------------------------------------------------------------------


def test_load_news_keeps_only_articles_in_the_district_sigungu(tmp_path):
    st = settings_for(
        tmp_path,
        [news_record("https://a.test/1"), news_record("https://b.test/2", geo_code=OUTSIDE)],
    )
    news = load_news(st, "test_gap")
    assert [i.payload.url for i in news.items] == ["https://a.test/1"]
    assert news.diagnostics.read == 2
    assert news.diagnostics.outside_district == 1
    assert news.diagnostics.shown == 1


def test_load_news_sorts_newest_first(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", published_at="2026-09-06T09:00:00+09:00"),
            news_record("https://a.test/2", published_at="2026-09-06T18:00:00+09:00"),
        ],
    )
    news = load_news(st, "test_gap")
    assert [i.payload.url for i in news.items] == ["https://a.test/2", "https://a.test/1"]


# --- 뷰모델 -----------------------------------------------------------------


def test_build_news_view_splits_district_specific_from_sigungu_only(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", confidence=0.9),
            news_record("https://a.test/2", confidence=0.7),
            news_record("https://a.test/3", confidence=0.7),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path))
    assert view.district_specific_count == 1
    assert view.sigungu_only_count == 2
    assert view.coverage_text == "동·지명 직접 1건 / 구 단위만 2건"


def test_build_news_view_publisher_sort(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", publisher="한겨레"),
            news_record("https://a.test/2", publisher="가나다일보"),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), sort="publisher")
    assert [r.publisher for r in view.rows] == ["가나다일보", "한겨레"]


def test_build_news_view_confidence_sort(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", confidence=0.7),
            news_record("https://a.test/2", confidence=0.9),
        ],
    )
    policy = load_policy(st.policy_path)
    view = build_news_view(load_news(st, "test_gap"), policy, sort="confidence")
    assert [r.confidence for r in view.rows] == [0.9, 0.7]


def test_build_news_view_empty(tmp_path):
    st = settings_for(tmp_path, [])
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path))
    assert view.is_empty
    assert view.nothing_collected
    assert view.verdict is None


def test_build_news_view_scope_district_filters_but_keeps_the_full_denominator(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", confidence=0.9),
            news_record("https://a.test/2", confidence=0.7),
            news_record("https://a.test/3", confidence=0.7),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), scope="district")
    assert [r.url for r in view.rows] == ["https://a.test/1"]
    assert view.matched == 1
    # 스코프를 걸어도 관련도 요약은 전체 기준이라 흔들리지 않는다.
    assert view.district_specific_count == 1
    assert view.sigungu_only_count == 2
    assert not view.nothing_collected


def test_build_news_view_oldest_sort(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", published_at="2026-09-06T18:00:00+09:00"),
            news_record("https://a.test/2", published_at="2026-09-06T09:00:00+09:00"),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), sort="oldest")
    assert [r.published_at for r in view.rows] == [
        "2026-09-06T09:00:00+09:00",
        "2026-09-06T18:00:00+09:00",
    ]


def test_build_news_view_query_filters_by_publisher(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", publisher="조선일보"),
            news_record("https://a.test/2", publisher="한겨레"),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="조선")
    assert [r.publisher for r in view.rows] == ["조선일보"]
    assert view.query == "조선"
    assert view.matched == 1


def test_build_news_view_query_matches_place_and_person(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", places=["풍납동"]),
            news_record("https://a.test/2", places=["방이동"], persons=["홍길동"]),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="풍납동")
    assert [r.url for r in view.rows] == ["https://a.test/1"]
    got = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="홍길동")
    assert [r.url for r in got.rows] == ["https://a.test/2"]


def test_build_news_view_query_matches_summary_snippet(tmp_path):
    """지명·현안어는 제목보다 요약에 더 자주 있다 — 검색이 요약까지 훑어야 한다."""
    rec = make_record(
        kind="news_article",
        geo_level="sigungu",
        geo_code=INSIDE,
        geo_name="서울 송파구",
        confidence=0.7,
        observed_at=datetime(2026, 9, 6, 12, 0, tzinfo=KST),
        ingested_at=datetime(2026, 9, 7, 0, 0, tzinfo=KST),
        natural_key="https://a.test/s",
        source_url="https://a.test/s",
        payload={
            "title": "제목에는 없는 낱말",
            "publisher": "가상일보",
            "published_at": "2026-09-06T12:00:00+09:00",
            "url": "https://a.test/s",
            "summary": "위례선 트램 노선안이 확정됐다.",
            "mentioned_places": ["송파구"],
            "mentioned_persons": [],
        },
    )
    st = settings_for(tmp_path, [rec, news_record("https://a.test/2")])
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="트램")
    assert [r.url for r in view.rows] == ["https://a.test/s"]


def test_build_news_view_query_then_scope_denominator_is_the_query_subset(tmp_path):
    st = settings_for(
        tmp_path,
        [
            news_record("https://a.test/1", publisher="조선일보", confidence=0.9),
            news_record("https://a.test/2", publisher="조선일보", confidence=0.7),
            news_record("https://a.test/3", publisher="한겨레", confidence=0.9),
        ],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="조선")
    # 검색 결과(2건) 기준: 강함 1 / 구단위 1. 한겨레 강함 1건은 세지 않는다.
    assert view.district_specific_count == 1
    assert view.sigungu_only_count == 1


def test_build_news_view_query_no_match_is_empty(tmp_path):
    st = settings_for(tmp_path, [news_record("https://a.test/1", publisher="조선일보")])
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), query="없는말")
    assert view.is_empty
    assert not view.nothing_collected


def test_build_news_view_truncates_and_says_so(tmp_path):
    st = settings_for(
        tmp_path,
        [news_record(f"https://a.test/{i}") for i in range(5)],
    )
    view = build_news_view(load_news(st, "test_gap"), load_policy(st.policy_path), limit=2)
    assert len(view.rows) == 2
    assert view.matched == 5
    assert view.truncated
    assert view.shown_text == "5건 중 2건 표시"


# --- 라우트 -----------------------------------------------------------------


def test_news_route_renders_table_and_links_to_source(tmp_path):
    html = client(tmp_path, [news_record("https://news.test/x")]).get("/d/test_gap/news").text
    assert "news-table" in html
    assert 'href="https://news.test/x"' in html
    assert "제목 x" in html


def test_news_route_has_nav_link(tmp_path):
    html = client(tmp_path, [news_record("https://news.test/x")]).get("/d/test_gap/news").text
    assert "/d/test_gap/news" in html
    assert 'class="on"' in html  # 현재 탭 강조


def test_news_route_warns_when_policy_has_no_entry(tmp_path):
    html = (
        client(tmp_path, [news_record("https://news.test/x")], POLICY_EMPTY)
        .get("/d/test_gap/news")
        .text
    )
    assert "선거법 검토를 받지 않은 산출물이다" in html


def test_news_route_empty_state(tmp_path):
    html = client(tmp_path, []).get("/d/test_gap/news").text
    assert "수집된 기사가 없다" in html


def test_news_route_scope_district_excludes_sigungu_only_rows(tmp_path):
    recs = [
        news_record("https://news.test/strong", confidence=0.9),
        news_record("https://news.test/weak", confidence=0.7),
    ]
    html = client(tmp_path, recs).get("/d/test_gap/news?scope=district").text
    assert 'href="https://news.test/strong"' in html
    assert 'href="https://news.test/weak"' not in html


def test_news_route_scope_with_no_match_keeps_the_switcher(tmp_path):
    recs = [news_record("https://news.test/weak", confidence=0.7)]
    html = client(tmp_path, recs).get("/d/test_gap/news?scope=district").text
    assert "이 스코프에 해당하는 기사가 없다" in html
    assert "수집된 기사가 없다" not in html  # 수집은 됐다
    assert "/d/test_gap/news?scope=all" in html  # 되돌아갈 링크가 있다


def test_news_route_has_search_box_and_oldest_sort(tmp_path):
    html = client(tmp_path, [news_record("https://news.test/x")]).get("/d/test_gap/news").text
    assert 'name="q"' in html
    assert "오래된순" in html


def test_news_route_query_filters_and_keeps_state(tmp_path):
    recs = [
        news_record("https://news.test/a", publisher="조선일보"),
        news_record("https://news.test/b", publisher="한겨레"),
    ]
    html = (
        client(tmp_path, recs)
        .get("/d/test_gap/news?q=%ED%95%9C%EA%B2%A8%EB%A0%88&sort=oldest")  # q=한겨레
        .text
    )
    assert 'href="https://news.test/b"' in html
    assert 'href="https://news.test/a"' not in html
    assert "「한겨레」 검색" in html
    assert "지우기" in html
    # 정렬 탭 링크가 검색어를 유지한다
    assert "q=%ED%95%9C%EA%B2%A8%EB%A0%88" in html or "q=한겨레" in html


def test_news_route_query_no_match_message(tmp_path):
    html = (
        client(tmp_path, [news_record("https://news.test/x", publisher="조선일보")])
        .get("/d/test_gap/news?q=zzz")
        .text
    )
    assert "에 걸리는 기사가 없다" in html
    assert "수집된 기사가 없다" not in html
