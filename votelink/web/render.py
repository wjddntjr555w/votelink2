"""템플릿 렌더의 단일 통로.

`app.py`(캠프 화면)와 `ops.py`(운영자 화면)가 함께 쓴다. **여기가 없으면 둘이 서로를
import 해야 하고 그건 순환이다.** 화면이 늘어나도 응답 객체가 만들어지는 자리는 하나로
둔다 — `_output.html` 이 산출물의 단일 통로인 것과 같은 이유다.
"""

from __future__ import annotations

from fastapi import Request
from starlette.responses import Response


def render(request: Request, template: str, context: dict, status_code: int = 200) -> Response:
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


def client_ip(request: Request) -> str | None:
    """접속 IP. 프록시 뒤라면 uvicorn 을 `--proxy-headers` 로 띄워야 실주소가 잡힌다."""
    return request.client.host if request.client else None


def bootstrap_password(request: Request) -> bool:
    """운영자가 아직 배포 기본 비밀번호를 쓰는가. **처음 물을 때만 센다.**

    `app.state.bootstrap_password` 가 `None` 이면 아직 안 세어 본 것이다. 검사가
    운영자 수만큼의 scrypt 라 기동 때마다 돌릴 것이 못 되고, 이 값을 보는 화면은
    `/me` 와 `/ops/` 둘뿐이다. 비밀번호가 바뀌는 자리가 결과를 갱신한다.
    """
    from votelink import control

    settings = request.app.state.settings
    if not settings.auth:
        return False
    if request.app.state.bootstrap_password is None:
        request.app.state.bootstrap_password = control.accounts.uses_bootstrap_password(
            path=settings.control_db
        )
    return request.app.state.bootstrap_password


def base_ctx(request: Request, **extra) -> dict:
    """`base.html` 이 요구하는 최소 컨텍스트.

    선거구 목록·선거 계열 같은 **참조 데이터를 읽지 않는다.** 로그인 화면과 운영자
    화면은 그것들이 필요 없고, 참조 데이터가 깨져 있어도 열려야 사람이 손을 쓸 수 있다.
    """
    return {
        "district_id": None,
        "districts": [],
        "election_types": [],
        "lens": getattr(request.state, "lens", None),
        "account": getattr(request.state, "account", None),
        "auth_on": request.app.state.settings.auth,
        **extra,
    }
