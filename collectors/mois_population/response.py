"""공공데이터포털 응답에서 목록을 꺼낸다.

포털 API는 데이터셋마다 봉투 형태가 다르다(odcloud / 표준 REST / 행안부 자체 형식).
어느 것인지 미리 알 수 없으므로 알려진 형태를 순서대로 시도하고, 그래도 못 찾으면
구조를 탐색한 뒤 **찾은 경로를 알려준다**. 사용자는 그 경로를 meta.yaml 에 고정하면 된다.

여기서 하는 일은 봉투를 여는 것뿐이다. 필드 해석은 aggregate.py 가 한다.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# 알려진 봉투 경로. 위에서부터 시도한다.
KNOWN_PATHS: tuple[tuple[str, ...], ...] = (
    # 실제 확인됨 (2026-09-01, admmSexdAgePpltn/selectAdmmSexdAgePpltn).
    # 이 서비스 계열은 최상위 키가 대문자 "Response" 다 — 흔한 소문자 표준과 다르다.
    ("Response", "items", "item"),
    ("data",),  # odcloud 자동변환
    ("response", "body", "items", "item"),  # 포털 표준 REST
    ("response", "body", "items"),  # 표준 REST 변형
    ("items", "item"),
    ("items",),
    ("row",),
)

# 포털은 오류를 HTTP 200 본문에 담아 보낸다. 봉투 위치가 데이터셋마다 달라서
# 고정 경로로 찾지 않고 구조를 훑어 코드 키를 가진 dict 를 찾는다.
CODE_KEYS = ("resultCode", "returnReasonCode", "errorCode")
MSG_KEYS = ("resultMsg", "returnAuthMsg", "errMsg", "errorMsg")

OK_CODES = {"00", "0", "INFO-000", "NORMAL SERVICE."}

# 자주 나오는 코드에 대한 조치 안내. 원문 메시지는 항상 함께 보여준다.
ERROR_HINTS: dict[str, str] = {
    "12": (
        "엔드포인트 경로가 틀렸다. 포털 데이터셋의 '상세기능'에 있는 요청 URL은 보통 "
        "https://apis.data.go.kr/<기관>/<서비스>/<오퍼레이션> 형태다 — "
        "오퍼레이션 이름이 빠졌는지 확인하라 (meta.yaml 의 config.endpoint)"
    ),
    "20": "서비스 접근이 거부됐다. 해당 데이터셋에 활용신청이 승인됐는지 확인하라",
    "22": "일일 호출 한도를 초과했다. paging.size 를 키우고 호출 수를 줄여라",
    "30": "인증키가 등록되지 않았다. 키를 다시 확인하라 (Encoding/Decoding 둘 다 지원한다)",
    "31": "활용기간이 만료됐다. 포털에서 연장 신청하라",
    "32": "등록되지 않은 IP다. 포털 개발계정에 호출 IP를 등록하라",
}


class ResponseShapeError(ValueError):
    """응답에서 목록을 찾지 못했다. 봉투 형태가 예상과 다르다."""


class ApiError(RuntimeError):
    """포털이 오류를 돌려줬다 (키 미등록, 트래픽 초과 등)."""


def dig(body: Any, path: tuple[str, ...]) -> Any:
    cur = body
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _find_status(node: Any, depth: int = 0) -> dict[str, Any] | None:
    """코드 키를 가진 dict 를 찾는다. 봉투가 어떻게 감싸여 있든 걸린다."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        if any(k in node for k in CODE_KEYS):
            return node
        for value in node.values():
            found = _find_status(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for value in node[:20]:
            found = _find_status(value, depth + 1)
            if found:
                return found
    return None


def check_api_error(body: Any) -> None:
    """정상 코드가 아니면 즉시 알려준다. 빈 목록으로 조용히 넘어가지 않는다.

    키 미등록·한도 초과·경로 오류를 '0건 수집 성공'으로 넘기면
    아무 경고 없이 빈 전략이 나온다.
    """
    status = _find_status(body)
    if status is None:
        return

    code = str(next(status[k] for k in CODE_KEYS if k in status)).strip()
    if code in OK_CODES:
        return

    parts = [str(status[k]).strip() for k in MSG_KEYS if status.get(k)]
    message = " / ".join(dict.fromkeys(parts)) or "(사유 없음)"
    hint = ERROR_HINTS.get(code.lstrip("0") or code) or ERROR_HINTS.get(code)
    raise ApiError(f"[{code}] {message}" + (f"\n  → {hint}" if hint else ""))


# 데이터 목록이 들어 있는 흔한 키 이름. 껍데기 리스트를 벗길 때 쓴다.
DATA_KEYS = ("row", "rows", "item", "items", "data")


def _unwrap(rows: list[dict[str, Any]], trail: tuple[str, ...]):
    """껍데기 리스트를 벗긴다.

    행안부/열린데이터 형식은 `{서비스명: [{"head": [...]}, {"row": [...]}]}` 처럼
    바깥 리스트가 메타와 데이터를 나눠 담는다. 이 바깥 리스트도 'dict의 리스트'라서
    그대로 두면 껍데기를 데이터로 착각한다.
    """
    for i, element in enumerate(rows):
        for key in DATA_KEYS:
            inner = element.get(key)
            if isinstance(inner, list) and inner and all(isinstance(x, dict) for x in inner):
                return (*trail, str(i), key), inner
    return None


def _search(node: Any, trail: tuple[str, ...] = (), depth: int = 0):
    """dict 원소를 담은 첫 리스트를 찾는다. 얕은 곳을 먼저 본다."""
    if depth > 6:
        return None
    if isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
        return _unwrap(node, trail) or (trail, node)
    if isinstance(node, dict):
        for key, value in node.items():
            found = _search(value, (*trail, key), depth + 1)
            if found:
                return found
    if isinstance(node, list):
        for i, value in enumerate(node):
            found = _search(value, (*trail, str(i)), depth + 1)
            if found:
                return found
    return None


def extract_rows(body: Any, path: str = "") -> list[dict[str, Any]]:
    """응답 본문에서 데이터 행 목록을 꺼낸다.

    path 를 주면 그 경로만 쓴다 (`response.body.items.item` 처럼 점으로 구분).
    """
    check_api_error(body)

    if path:
        rows = dig(body, tuple(path.split(".")))
        if not isinstance(rows, list):
            raise ResponseShapeError(f"config.data_path='{path}' 가 리스트를 가리키지 않는다")
        return rows

    for known in KNOWN_PATHS:
        rows = dig(body, known)
        if isinstance(rows, list):
            return rows

    found = _search(body)
    if found:
        trail, rows = found
        log.warning(
            "알려지지 않은 응답 형태다. '%s' 에서 %d행을 찾았다. "
            "meta.yaml 의 config.data_path 에 이 경로를 고정하라",
            ".".join(trail),
            len(rows),
        )
        return rows

    keys = ", ".join(body) if isinstance(body, dict) else type(body).__name__
    raise ResponseShapeError(
        f"응답에서 데이터 목록을 찾지 못했다. 최상위 키: {keys}. "
        "config.data_path 로 경로를 지정하라"
    )
