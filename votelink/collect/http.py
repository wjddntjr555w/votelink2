"""수집 예절이 내장된 HTTP 클라이언트.

수집기는 httpx 를 직접 부르지 않는다. rate limit, 백오프, robots.txt, User-Agent 를
개별 수집기가 각자 구현하면 반드시 누군가 빠뜨린다.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

import httpx

from votelink.collect.meta import AccessMethod, CollectorMeta

log = logging.getLogger(__name__)

USER_AGENT = "votelink2/0.1 (+https://github.com/wjddntjr555w/votelink2)"
BACKOFF_SECONDS = (2, 4, 8, 16)
RETRY_STATUS = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 30.0


class FetchError(RuntimeError):
    """네트워크·인증 실패. 실행을 중단시킨다 (raw 를 저장하지 않는다)."""


class RobotsDisallowed(FetchError):
    """robots.txt 가 막았다. 우회하지 않는다."""


class _RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str, user_agent: str) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._cache:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(f"{origin}/robots.txt")
            try:
                parser.read()
            except Exception as exc:  # noqa: BLE001
                # robots.txt 를 못 읽었다. 금지로 단정하지 않되 기록은 남긴다.
                log.warning("robots.txt 를 읽지 못했다 (%s): %s", origin, exc)
                self._cache[origin] = None
            else:
                self._cache[origin] = parser
        parser = self._cache[origin]
        return True if parser is None else parser.can_fetch(user_agent, url)


_robots = _RobotsCache()


class PoliteClient:
    """요청 간격을 지키고, 일시적 오류에만 지수 백오프로 재시도한다."""

    def __init__(self, meta: CollectorMeta, client: httpx.Client) -> None:
        self._meta = meta
        self._client = client
        self._min_interval = 1.0 / meta.rate_limit_rps
        self._last_request_at = 0.0
        self._check_robots = meta.access is AccessMethod.CRAWL

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if self._check_robots and not _robots.allowed(url, USER_AGENT):
            raise RobotsDisallowed(f"robots.txt 가 금지한 경로다: {url}")

        last_error: Exception | None = None
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            self._throttle()
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
            else:
                if resp.status_code not in RETRY_STATUS:
                    if resp.status_code >= 400:
                        raise FetchError(f"{resp.status_code} {method} {url}")
                    return resp
                last_error = FetchError(f"{resp.status_code} {method} {url}")

            if attempt < len(BACKOFF_SECONDS):
                delay = BACKOFF_SECONDS[attempt]
                log.warning(
                    "재시도 %d/%d (%ds 후): %s", attempt + 1, len(BACKOFF_SECONDS), delay, url
                )
                time.sleep(delay)

        raise FetchError(f"4회 재시도 후에도 실패했다: {url}") from last_error

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()


@contextmanager
def polite_client(meta: CollectorMeta, **client_kwargs) -> Iterator[PoliteClient]:
    headers = {"User-Agent": USER_AGENT, **client_kwargs.pop("headers", {})}
    with httpx.Client(
        headers=headers,
        timeout=client_kwargs.pop("timeout", DEFAULT_TIMEOUT),
        follow_redirects=True,
        **client_kwargs,
    ) as client:
        yield PoliteClient(meta, client)
