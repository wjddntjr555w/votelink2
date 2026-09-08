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
from votelink.reference.compliance import Compliance, load_policy, load_review
from votelink.reference.districts import DistrictNotFound
from votelink.web.lens import load_lens
from votelink.web.loader import (
    AmbiguousDistrict,
    available_districts,
    load_all_emd,
    load_comparison,
    load_local_issue,
    load_news,
    load_news_pulse,
    load_profiles,
)
from votelink.web.settings import WebSettings
from votelink.web.shapes import ShapeError, shapes_for
from votelink.web.viewmodel import (
    DEFAULT_METRIC,
    build_comparison,
    build_issue_board,
    build_map,
    build_nation_view,
    build_news_view,
    build_pulse_card,
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
    # 렌즈는 기동 시 한 번 읽는다. 캠프 설정이 깨져 있으면 여기서 죽는 것이 맞다 —
    # 관할이 틀린 채로 화면을 그리면 조용히 다른 답을 보여준다 (P-001 §16).
    # 세션이 캠프를 정하게 되면(P-002) 이 자리는 요청별로 옮겨간다.
    s = app.state.settings
    app.state.lens = (
        load_lens(s.camp_id, s.cycle_id, s.camps_root, s.districts_path) if s.camp_id else None
    )
    # 검토 기록과 선거일도 캠프에서 온다 (P-001 §13). 캠프가 없으면 검토 기록이 비고
    # 선거일을 모르므로 전부 미검토 + 기간 판정 불가로 떨어진다 — fail-closed 다.
    app.state.review, app.state.election_day = _camp_compliance(app.state.lens, s)
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
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        view = _view(request, district_id, sort=sort, election_type=et)
        pulse = build_pulse_card(load_news_pulse(settings, district_id), _compliance(request))
        issue_board = build_issue_board(
            load_local_issue(settings, district_id), _compliance(request)
        )
        return _render(
            request,
            "dashboard.html",
            _ctx(request, district_id, view=view, pulse=pulse, issue_board=issue_board),
        )

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
        q: str = "",
    ) -> Response:
        """수집한 지역 기사 목록. 분석기 없이 L1 레코드를 그대로 표로 낸다.
        `?q=` 로 제목·언론사·언급어를 부분 문자열 검색한다.
        `?election_type=` 축이 없다 — 기사는 선거 계열에 속하지 않는다."""
        settings: WebSettings = request.app.state.settings
        news = load_news(settings, district_id)
        view = build_news_view(news, _compliance(request), sort=sort, scope=scope, query=q)
        return _render(request, "news.html", _ctx(request, district_id, view=view))

    @app.get("/compare", response_class=Response)
    def compare(
        request: Request, sort: str = "name", election_type: str = "presidential"
    ) -> Response:
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        comparison = load_comparison(settings, election_type=et)
        view = build_comparison(
            comparison, _compliance(request), sort=sort, lens=request.app.state.lens
        )
        return _render(request, "compare.html", _ctx(request, view=view))

    @app.get("/nation", response_class=Response)
    def nation(
        request: Request, sort: str = "code", election_type: str = "presidential"
    ) -> Response:
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        profiles = load_all_emd(settings, election_type=et)
        view = build_nation_view(
            profiles, _compliance(request), sort=sort, lens=request.app.state.lens
        )
        return _render(request, "nation.html", _ctx(request, view=view))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    for error in SETUP_ERRORS:
        app.add_exception_handler(error, _setup_error)

    return app


def _camp_compliance(lens, settings: WebSettings):
    """(검토 기록, 선거일). 캠프가 없으면 (빈 기록, None).

    선거일을 `compliance` 파일이 아니라 캠프의 `election.yaml` 에서 읽는다 —
    진실의 출처를 둘로 만들지 않는다. 캠프마다 나가는 선거가 다르므로 공표
    금지기간(§108) 판정도 캠프마다 다르다.
    """
    from votelink.camp import cycle_dir, load_cycle
    from votelink.reference.compliance import EMPTY_REVIEW, REVIEW_FILENAME

    if lens is None:
        # 캠프가 없어도 검토 기록을 직접 물릴 수 있다. 그때 선거일은 여전히 모른다 —
        # 선거일의 출처는 캠프의 election.yaml 하나뿐이다.
        return (load_review(settings.review_path) if settings.review_path else EMPTY_REVIEW), None

    cycle = load_cycle(
        lens.camp_id, lens.cycle_id, settings.camps_root, districts_path=settings.districts_path
    )
    path = settings.review_path or (
        cycle_dir(lens.camp_id, lens.cycle_id, settings.camps_root) / REVIEW_FILENAME
    )
    day = cycle.election.date
    return load_review(path), day.isoformat() if day else None


def _compliance(request: Request) -> Compliance:
    """공용 정책 + 이 캠프의 검토 기록 + 선거일.

    검토 기록과 선거일은 캠프에서 온다 — 무엇이 위험한가는 모두에게 같지만
    검토했는가와 언제가 선거일인가는 캠프마다 다르다 (`P-001` §13).
    캠프가 없으면(진영 중립 보기) 검토 기록이 비어 전부 미검토로 떨어진다.
    """
    settings: WebSettings = request.app.state.settings
    return Compliance(
        policy=load_policy(settings.policy_path),
        review=request.app.state.review,
        election_day=request.app.state.election_day,
    )


def _view(
    request: Request,
    district_id: str | None = None,
    *,
    sort: str = "code",
    election_type: ElectionType = ElectionType.PRESIDENTIAL,
):
    settings: WebSettings = request.app.state.settings
    profiles = load_profiles(settings, district_id, election_type=election_type)
    return build_view(
        profiles,
        _compliance(request),
        sort=sort,
        election_type=election_type,
        lens=request.app.state.lens,
    )


def _ctx(request: Request, district_id: str | None = None, **extra) -> dict:
    """모든 화면이 공유하는 컨텍스트 — 현재 선거구, 전환 목록, 선거 계열 목록, 렌즈."""
    settings: WebSettings = request.app.state.settings
    return {
        "district_id": district_id,
        "districts": available_districts(settings),
        "election_types": election_type_choices(),
        "lens": request.app.state.lens,
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
