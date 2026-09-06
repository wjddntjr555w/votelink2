"""FastAPI 앱과 라우트. 규약은 `docs/40-webapp-spec.md`.

여기는 얇다. 읽기는 `loader.py`, 계산은 `viewmodel.py` 가 하고 이 파일은 둘을 잇는다
— `runner.py`(L1·L2)와 같은 자리다.

**`create_app` 팩토리**로 만드는 이유는 테스트다. 전역을 monkeypatch 하는 대신
`create_app(WebSettings(records_root=tmp_path))` 로 임시 디렉터리를 주입한다.
라우트는 `Depends()` 대신 `request.app.state` 를 읽는다.

화면 축은 셋이다 (§7): 선거구(대시보드+지도) · 비교(`/compare`) · 전국 동(`/nation`).
각 화면은 `?election_type=` 로 재필터한다 (기본 presidential).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from votelink.contract.enums import ElectionType
from votelink.reference.compliance import load_policy
from votelink.reference.districts import DistrictNotFound
from votelink.web.loader import (
    AmbiguousDistrict,
    available_districts,
    load_all_emd,
    load_comparison,
    load_news,
    load_profiles,
)
from votelink.web.settings import WebSettings
from votelink.web.shapes import ShapeError, shapes_for
from votelink.web.viewmodel import (
    DEFAULT_METRIC,
    build_comparison,
    build_map,
    build_nation_view,
    build_news_view,
    build_view,
    election_type_choices,
    resolve_election_type,
)

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"

SETUP_ERRORS = (AmbiguousDistrict, DistrictNotFound, FileNotFoundError, ShapeError)
"""설정·참조 데이터가 어긋난 경우. 트레이스백 대신 무엇을 고쳐야 하는지 보여준다."""


def create_app(settings: WebSettings | None = None) -> FastAPI:
    app = FastAPI(
        title="votelink",
        # /docs·/redoc 을 끈다. Swagger UI 가 CDN 에서 스크립트를 받아오는데,
        # 외부 요청 0건이 이 웹앱의 컴플라이언스 요건이다 (docs/40-webapp-spec.md §10).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings or WebSettings()
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=Response)
    def index(request: Request) -> Response:
        """선거구 하나면 그리로 보낸다. 여러 개면 고르게 한다 —
        조용히 첫 번째를 열면 옆 지역구를 보여주면서 맞다고 우기는 화면이 된다."""
        settings: WebSettings = request.app.state.settings
        districts = available_districts(settings)
        target = settings.district_id or (districts[0][0] if len(districts) == 1 else None)
        if target:
            return RedirectResponse(f"/d/{target}/", status_code=307)
        return _render(request, "districts.html", _ctx(request))

    @app.get("/d/{district_id}/", response_class=Response)
    def dashboard(
        request: Request,
        district_id: str,
        sort: str = "code",
        election_type: str = "presidential",
    ) -> Response:
        et = resolve_election_type(election_type)
        view = _view(request, district_id, sort=sort, election_type=et)
        return _render(request, "dashboard.html", _ctx(request, district_id, view=view))

    @app.get("/d/{district_id}/map", response_class=Response)
    def map_screen(
        request: Request,
        district_id: str,
        metric: str = DEFAULT_METRIC,
        election_type: str = "presidential",
    ) -> Response:
        et = resolve_election_type(election_type)
        view = _view(request, district_id, election_type=et)
        shapes = shapes_for(
            [(c.geo_code, c.geo_name) for c in view.cards],
            path=request.app.state.settings.boundaries_path,
        )
        return _render(
            request,
            "map.html",
            _ctx(
                request,
                district_id,
                view=view,
                map=build_map(view, shapes, metric_key=metric),
            ),
        )

    @app.get("/d/{district_id}/news", response_class=Response)
    def news_screen(
        request: Request,
        district_id: str,
        sort: str = "date",
        scope: str = "all",
    ) -> Response:
        """수집한 지역 기사 목록. 분석기 없이 L1 레코드를 그대로 표로 낸다.
        `?election_type=` 축이 없다 — 기사는 선거 계열에 속하지 않는다."""
        settings: WebSettings = request.app.state.settings
        news = load_news(settings, district_id)
        policy = load_policy(settings.policy_path)
        view = build_news_view(news, policy, sort=sort, scope=scope)
        return _render(request, "news.html", _ctx(request, district_id, view=view))

    @app.get("/compare", response_class=Response)
    def compare(
        request: Request, sort: str = "name", election_type: str = "presidential"
    ) -> Response:
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        comparison = load_comparison(settings, election_type=et)
        policy = load_policy(settings.policy_path)
        view = build_comparison(comparison, policy, sort=sort)
        return _render(request, "compare.html", _ctx(request, view=view))

    @app.get("/nation", response_class=Response)
    def nation(
        request: Request, sort: str = "code", election_type: str = "presidential"
    ) -> Response:
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        profiles = load_all_emd(settings, election_type=et)
        policy = load_policy(settings.policy_path)
        view = build_nation_view(profiles, policy, sort=sort)
        return _render(request, "nation.html", _ctx(request, view=view))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    for error in SETUP_ERRORS:
        app.add_exception_handler(error, _setup_error)

    return app


def _view(
    request: Request,
    district_id: str | None = None,
    *,
    sort: str = "code",
    election_type: ElectionType = ElectionType.PRESIDENTIAL,
):
    settings: WebSettings = request.app.state.settings
    profiles = load_profiles(settings, district_id, election_type=election_type)
    policy = load_policy(settings.policy_path)
    return build_view(profiles, policy, sort=sort, election_type=election_type)


def _ctx(request: Request, district_id: str | None = None, **extra) -> dict:
    """모든 화면이 공유하는 컨텍스트 — 현재 선거구, 전환 목록, 선거 계열 목록."""
    settings: WebSettings = request.app.state.settings
    return {
        "district_id": district_id,
        "districts": available_districts(settings),
        "election_types": election_type_choices(),
        **extra,
    }


def _render(request: Request, template: str, context: dict) -> Response:
    return request.app.state.templates.TemplateResponse(request, template, context)


def _setup_error(request: Request, exc: Exception) -> Response:
    return request.app.state.templates.TemplateResponse(
        request,
        "error.html",
        {"message": str(exc), "kind": type(exc).__name__},
        status_code=500,
    )
