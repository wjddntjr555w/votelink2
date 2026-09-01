"""수집 예절 — 재시도·백오프·robots 는 클라이언트가 강제한다."""

import httpx
import pytest

from tests.conftest import make_meta
from votelink.collect import http


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)


def client_with(handler, **over):
    return http.polite_client(make_meta(**over), transport=httpx.MockTransport(handler))


def test_user_agent_identifies_the_project():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json={})

    with client_with(handler) as c:
        c.get("https://example.test/x")
    assert "votelink2" in seen["ua"]


def test_retries_on_503_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, json={"ok": True})

    with client_with(handler) as c:
        resp = c.get("https://example.test/x")
    assert resp.json() == {"ok": True}
    assert calls["n"] == 3


def test_gives_up_after_four_retries():
    def handler(request):
        return httpx.Response(503)

    with client_with(handler) as c, pytest.raises(http.FetchError, match="4회"):
        c.get("https://example.test/x")


def test_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    with client_with(handler) as c, pytest.raises(http.FetchError, match="404"):
        c.get("https://example.test/x")
    assert calls["n"] == 1, "4xx 는 재시도해도 달라지지 않는다"


def test_robots_is_checked_only_for_crawl_access(monkeypatch):
    checked = []
    monkeypatch.setattr(http._robots, "allowed", lambda url, ua: checked.append(url) or False)

    def handler(request):
        return httpx.Response(200, json={})

    with client_with(handler, access="api") as c:
        c.get("https://example.test/x")
    assert checked == [], "API 접근은 robots 대상이 아니다"

    with client_with(handler, access="crawl") as c, pytest.raises(http.RobotsDisallowed):
        c.get("https://example.test/x")
    assert checked == ["https://example.test/x"]
