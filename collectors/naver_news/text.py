"""응답 형식과 무관한 순수 문자열 처리.

fixture 없이도 검증할 수 있도록 collector.py 에서 분리했다 (docs/20-collector-spec.md §7).
여기 있는 함수는 전부 결정적이며, 해석(감성·분류·추정)을 하지 않는다.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAG_RE = re.compile(r"<[^>]+>")

# 기사 식별과 무관한 유입 추적 파라미터. 이것만 떼고 나머지 쿼리는 보존한다.
# 국내 언론사 상당수가 `?idxno=123` 처럼 쿼리에 기사 번호를 담기 때문에
# 쿼리를 통째로 버리면 서로 다른 기사가 같은 record_id 로 뭉개진다.
_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "igshid", "spm"})
_TRACKING_PREFIXES = ("utm_",)


def clean_text(value: str) -> str:
    """검색 API 가 붙이는 `<b>` 강조 태그와 HTML 엔티티를 푼다.

    내용은 바꾸지 않는다. 이 값은 요약 생성물이 아니라 출처가 준 스니펫이다.
    """
    return html.unescape(_TAG_RE.sub("", value)).strip()


def _is_tracking(key: str) -> bool:
    return key in _TRACKING_PARAMS or key.startswith(_TRACKING_PREFIXES)


def normalize_url(url: str) -> str:
    """record_id 의 재료. 같은 기사가 다른 표기로 와도 같은 값이 나와야 한다.

    스킴·호스트를 소문자로 맞추고, 프래그먼트와 추적 파라미터를 버리고,
    남은 쿼리를 정렬한다. 기사 번호가 든 쿼리는 남는다.
    """
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"URL 로 볼 수 없다: {url!r}")

    kept = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(kept), ""))


def publisher_from_url(url: str, names: dict[str, str] | None = None) -> str:
    """언론사명. 검색 API 가 매체명을 주지 않으므로 호스트에서 만든다.

    사전에 없으면 호스트를 그대로 쓴다 — 틀린 게 아니라 아직 모르는 것이므로
    격리하지 않는다.
    """
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    if not host:
        raise ValueError(f"호스트를 찾을 수 없다: {url!r}")
    return (names or {}).get(host, host)


def parse_pub_date(value: str) -> datetime:
    """RFC 1123(`Mon, 30 Aug 2026 14:20:00 +0900`) -> 타임존 있는 datetime."""
    dt = parsedate_to_datetime(value)
    if dt.tzinfo is None:
        raise ValueError(f"타임존이 없는 발행시각이다: {value!r}")
    return dt


def match_terms(text: str, terms: Iterable[str]) -> list[str]:
    """사전에 있는 표현이 문자열로 등장하는지만 본다.

    형태소 분석도 개체명 인식도 아니다. 사전 밖의 지명은 잡히지 않으며,
    그게 의도다 — 사전에 없는 것을 추측하는 순간 그건 해석이고 L2 의 일이다.
    """
    return sorted({t for t in terms if t and t in text})
