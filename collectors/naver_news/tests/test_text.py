"""응답 형식과 무관한 순수 함수. 합성 데이터로 검증해도 되는 부분이다
(docs/20-collector-spec.md §7). 봉투 검증은 fixture 가 있어야 하는 test_parse.py 에서 한다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from ..text import clean_text, match_terms, normalize_url, parse_pub_date, publisher_from_url

KST = timezone(timedelta(hours=9))


class TestCleanText:
    def test_strips_highlight_tags(self):
        assert clean_text("<b>송파구</b> 재건축 속도") == "송파구 재건축 속도"

    def test_unescapes_entities(self):
        assert clean_text("&quot;주민 반발&quot; &amp; 대책") == '"주민 반발" & 대책'

    def test_escaped_tag_stays_literal(self):
        # 원문이 &lt;b&gt; 로 이스케이프해 보낸 것은 강조 태그가 아니라 내용이다.
        assert clean_text("코드에 &lt;b&gt; 를 쓴다") == "코드에 <b> 를 쓴다"


class TestNormalizeUrl:
    def test_lowercases_scheme_and_host(self):
        assert normalize_url("HTTPS://News.Example.COM/a/1") == "https://news.example.com/a/1"

    def test_drops_fragment_and_trailing_slash(self):
        assert normalize_url("https://ex.com/a/1/#top") == "https://ex.com/a/1"

    def test_keeps_article_id_in_query(self):
        # 국내 언론사 다수가 쿼리에 기사 번호를 담는다. 이걸 버리면 서로 다른 기사가
        # 같은 record_id 로 뭉개진다 — 조용히 데이터가 사라지는 종류의 버그다.
        assert normalize_url("https://ex.com/view?idxno=123") == "https://ex.com/view?idxno=123"

    def test_drops_tracking_params_only(self):
        got = normalize_url("https://ex.com/v?utm_source=naver&idxno=7&fbclid=xy")
        assert got == "https://ex.com/v?idxno=7"

    def test_query_order_does_not_change_result(self):
        a = normalize_url("https://ex.com/v?b=2&a=1")
        b = normalize_url("https://ex.com/v?a=1&b=2")
        assert a == b, "쿼리 순서가 다르면 같은 기사가 두 레코드가 된다"

    @pytest.mark.parametrize("bad", ["", "   ", "not-a-url", "/relative/path"])
    def test_rejects_non_urls(self, bad):
        with pytest.raises(ValueError):
            normalize_url(bad)


class TestPublisherFromUrl:
    def test_falls_back_to_host(self):
        assert publisher_from_url("https://www.example.com/a") == "example.com"

    def test_uses_dictionary_when_present(self):
        names = {"example.com": "예시일보"}
        assert publisher_from_url("https://www.example.com/a", names) == "예시일보"

    def test_unknown_host_is_not_an_error(self):
        # 매체명 미상은 계약 위반이 아니다. 격리하지 않는다.
        assert publisher_from_url("https://n.news.naver.com/x") == "n.news.naver.com"


class TestParsePubDate:
    def test_parses_rfc1123_with_offset(self):
        got = parse_pub_date("Mon, 30 Aug 2026 14:20:00 +0900")
        assert got == datetime(2026, 8, 30, 14, 20, tzinfo=KST)

    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError):
            parse_pub_date("Mon, 30 Aug 2026 14:20:00")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            parse_pub_date("어제")


class TestMatchTerms:
    def test_returns_only_dictionary_hits(self):
        text = "송파구 잠실 재건축, 강남구는 제외"
        assert match_terms(text, ["송파구", "잠실", "노원구"]) == ["송파구", "잠실"]

    def test_result_is_sorted_and_deduplicated(self):
        assert match_terms("잠실 잠실 송파구", ["잠실", "송파구"]) == ["송파구", "잠실"]

    def test_no_dictionary_no_hits(self):
        # 사전 밖의 지명은 잡히지 않는다. NER 은 L2 의 일이다.
        assert match_terms("문정동 법조타운", ["송파구"]) == []
