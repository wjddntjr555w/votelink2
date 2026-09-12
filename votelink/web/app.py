"""FastAPI 앱과 라우트. 규약은 `docs/40-webapp-spec.md`.

여기는 얇다. 읽기는 `loader.py`, 계산은 `viewmodel.py` 가 하고 이 파일은 둘을 잇는다
— `runner.py`(L1·L2)와 같은 자리다.

**`create_app` 팩토리**로 만드는 이유는 테스트다. 전역을 monkeypatch 하는 대신
`create_app(WebSettings(records_root=tmp_path))` 로 임시 디렉터리를 주입한다.
라우트는 `Depends()` 대신 `request.app.state` 를 읽는다.

**요청별 상태는 `request.state` 다.** 인증이 켜지면 어느 캠프의 눈으로 보는지가 앱이
아니라 세션에서 온다 (P-002 §8). 그래서 렌즈·검토 기록·선거일을 `app.state` 가 아니라
`request.state` 에서 읽는다 — 인증이 꺼져 있으면 미들웨어가 앱 전역 값을 그대로 복사해
넣으므로 라우트의 코드 경로는 하나다.

화면 축은 셋이다 (§7): 선거구(대시보드+지도) · 비교(`/compare`) · 전국 동(`/nation`).
각 화면은 `?election_type=` 로 재필터한다 (기본 presidential).
그 앞에 인증 화면 넷이 붙는다: `/login` · `/signup` · `/pending` · `/onboarding`.
캠프 설정은 `/cycles` 아래에 있다 — 주기 목록, 추가(`new`), 수정(`{id}/edit` → 미리보기 →
`{id}/apply`), 후보 로스터(`{id}/roster`). 운영자 화면은 `ops.py` 에 따로 있다.

**수정만 두 단계다.** 관할이 틀리면 에러 없이 모든 분석이 조용히 틀리므로(P-001 §16),
저장 전에 무엇이 달라지는지 보여주고 확인받는다. 그 계산은 `camp/changes.py` 에 있다.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from votelink import control
from votelink.camp import CampConfigError
from votelink.contract.enums import Camp, ElectionType
from votelink.reference.compliance import EMPTY_REVIEW, Compliance, load_policy, load_review
from votelink.reference.districts import DistrictNotFound
from votelink.web import auth, ops
from votelink.web.forms import (
    CAMP_ALIASES,
    CycleForm,
    RosterForm,
    build_cycle,
    parse_roster,
    roster_text,
)
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
from votelink.web.render import base_ctx, bootstrap_password
from votelink.web.render import client_ip as _client_ip
from votelink.web.render import render as _render
from votelink.web.settings import WebSettings
from votelink.web.shapes import ShapeError, shapes_for
from votelink.web.viewmodel import (
    CAMP_LABELS,
    DEFAULT_METRIC,
    build_candidate_comparison,
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
FRONTEND_DIST = HERE.parent.parent / "frontend" / "dist"
"""React SPA 빌드 결과물. 1단계 범위는 대시보드(`/d/{id}/`) 하나뿐 — 나머지 24개
화면은 여전히 Jinja2 가 서빙한다 (docs/40-webapp-spec.md §10 갱신분)."""

SETUP_ERRORS = (AmbiguousDistrict, DistrictNotFound, FileNotFoundError, ShapeError, CampConfigError)
"""설정·참조 데이터가 어긋난 경우. 트레이스백 대신 무엇을 고쳐야 하는지 보여준다.

`CampConfigError` 는 캠프 설정이 스스로 모순되는 경우다 — 폴더 이름과 선거일이 다르거나
관할에 없는 행정동코드가 있다. 사람이 고칠 일이라 여기 함께 둔다."""

OFFICE_LABELS = {
    "president": "대통령",
    "national_assembly": "국회의원",
    "metro_head": "광역단체장 (시·도지사)",
    "basic_head": "기초단체장 (시장·군수·구청장)",
    "metro_council": "광역의원",
    "basic_council": "기초의원",
    "education": "교육감",
}
"""온보딩 폼의 직위 라벨. `Office` enum 이 유일한 출처이고 여기는 표기만 붙인다 —
`viewmodel.py` 의 라벨표들과 달리 캠프 설정 전용이라 화면 계층에 둔다."""


def _spa_shell() -> Response:
    """React SPA 셸(`frontend/dist/index.html`). React Router 가 URL을 읽으므로
    이 화면들(`/d/{id}/`, `/d/{id}/map`)은 인자를 안 받고 같은 파일을 돌려준다."""
    index_path = FRONTEND_DIST / "index.html"
    if not index_path.exists():
        return PlainTextResponse(
            "프런트엔드가 빌드되지 않았다. `cd frontend && npm run build` 를 먼저 실행하라.",
            status_code=500,
        )
    return FileResponse(index_path)


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
    # React SPA(대시보드 1단계)의 빌드 산출물. 빌드 전이면 마운트하지 않는다 —
    # 다른 24개 화면·테스트는 프런트엔드 빌드 없이도 그대로 동작해야 한다.
    if (FRONTEND_DIST / "assets").exists():
        app.mount(
            "/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets"
        )
    if s.auth:
        # 스키마를 앱이 스스로 만든다. 여러 번 불러도 안전하고, "승인은 CLI 로 했는데
        # 웹은 테이블이 없다"는 어긋남이 생기지 않는다. 레코드가 아니므로
        # "L3 는 레코드를 쓰지 않는다"(web/__init__.py)를 깨지 않는다.
        control.init(s.control_db)
    # 운영자가 아직 배포 기본 비밀번호를 쓰는가. `None` 은 "아직 안 세어 봤다"는 뜻이다 —
    # 검사가 scrypt 라 요청마다는 물론이고 기동 때마다 돌릴 것도 아니다. 이 값을 보는
    # 화면(`/me`·`/ops/`)이 처음 열릴 때 한 번 세고, 비밀번호가 바뀌는 자리가 갱신한다.
    app.state.bootstrap_password = None

    @app.middleware("http")
    async def _authenticate(request: Request, call_next):
        """모든 요청이 여기를 지난다. **라우트가 검사를 부르지 않는다** (P-002 §8).

        판정은 `auth.authorize` 가 하고 여기는 집행만 한다. 그 함수는 sqlite 와
        YAML 을 읽는 동기 코드라 스레드풀로 넘긴다 — 이벤트 루프를 막지 않는다.
        """
        s: WebSettings = request.app.state.settings
        if not s.auth:
            # 인증이 꺼진 앱. 렌즈는 기동 시 정해진 하나뿐이다 (`serve --camp`).
            # 이 경우에도 `request.state` 를 채워 라우트의 코드 경로를 하나로 둔다.
            request.state.account = None
            request.state.lens = request.app.state.lens
            request.state.review = request.app.state.review
            request.state.election_day = request.app.state.election_day
            return await call_next(request)

        token = request.cookies.get(control.COOKIE_NAME)
        d = await run_in_threadpool(auth.authorize, token, request.url.path, s)
        request.state.account = d.account
        request.state.lens = d.lens
        request.state.review = d.review or EMPTY_REVIEW
        request.state.election_day = d.election_day

        if d.redirect:
            return RedirectResponse(d.redirect, status_code=303)
        if d.denied:
            # **격리가 실제로 막은 순간이다.** 이 줄이 "유출이 없었다"의 증거가 된다.
            await run_in_threadpool(
                control.audit.log,
                "denied",
                account_id=d.account.id if d.account else None,
                camp_id=d.camp_id,
                target=request.url.path,
                detail={"reason": d.denied},
                ip=_client_ip(request),
                path=s.control_db,
            )
            return _render(request, "denied.html", _ctx(request, message=d.denied), status_code=403)
        return await call_next(request)

    @app.get("/", response_class=Response)
    def index(request: Request) -> Response:
        """선거구 하나면 그리로 보낸다. 여러 개면 고르게 한다 —
        조용히 첫 번째를 열면 옆 지역구를 보여주면서 맞다고 우기는 화면이 된다."""
        settings: WebSettings = request.app.state.settings
        # 캠프 관할로 좁힌 목록이다. 관할이 선거구 하나면 `/` 가 그리로 바로 간다 —
        # 캠프가 로그인해서 254개 목록을 마주하지 않는다.
        districts = available_districts(settings, request.state.lens)
        target = settings.district_id or (districts[0][0] if len(districts) == 1 else None)
        if target:
            return RedirectResponse(f"/d/{target}/", status_code=307)
        return _render(request, "districts.html", _ctx(request))

    @app.get("/d/{district_id}/", response_class=Response)
    def dashboard(district_id: str) -> Response:
        """React SPA 셸. 데이터는 `/api/d/{district_id}` 가 낸다 — 여기는 그냥
        빌드된 `index.html` 을 돌려주고, React Router 가 URL을 읽는다
        (서버는 이 인자를 쓰지 않는다). `/map` 도 같은 셸을 쓴다(`_spa_shell`)."""
        return _spa_shell()

    @app.get("/d/{district_id}/map", response_class=Response)
    def map_screen(district_id: str) -> Response:
        return _spa_shell()

    @app.get("/api/d/{district_id}")
    def api_dashboard(
        request: Request,
        district_id: str,
        sort: str = "code",
        election_type: str = "presidential",
    ) -> dict:
        """대시보드 JSON API. `dashboard.html` 이 템플릿에 넘기던 것과 같은 값들을
        그대로 반환한다 — 계산은 전부 `viewmodel.py` 의 순수 함수가 하고,
        여기는 그 결과를 JSON으로 옮길 뿐이다(FastAPI 가 Pydantic 모델을
        재귀적으로 인코딩한다).

        **규칙 5는 여기서도 서버가 집행한다 — 프런트엔드(ComplianceGate)를 믿지
        않는다.** Jinja 시절엔 `blocked` 콘텐츠가 애초에 HTML로 안 나갔다. JSON
        API 에서 그 성질을 잃지 않으려면 `_redact_*` 가 verdict 를 보고 본문을
        지운 **뒤에** 응답을 만들어야 한다 — 클라이언트가 verdict 를 보고 알아서
        숨기는 것과는 다르다(그건 화면이 예쁘게 숨기는 것뿐, 네트워크 탭에는
        그대로 남는다)."""
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        view = _view(request, district_id, sort=sort, election_type=et)
        pulse = build_pulse_card(load_news_pulse(settings, district_id), _compliance(request))
        issue_board = build_issue_board(
            load_local_issue(settings, district_id), _compliance(request)
        )
        candidate_comparison = _candidate_comparison(request, view)
        lens = request.state.lens
        account = getattr(request.state, "account", None)

        view_shows = view.verdict is not None and view.verdict.status != "blocked"
        return {
            "view": _redact_district_view(view, view_shows),
            "pulse": _redact_output(pulse, ("verdict",)),
            "issue_board": _redact_output(issue_board, ("verdict",)),
            "candidate_comparison": candidate_comparison.model_dump(mode="json")
            if candidate_comparison and view_shows
            else None,
            "district_id": district_id,
            "districts": available_districts(settings, lens),
            "election_types": election_type_choices(),
            "auth_on": settings.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    @app.get("/api/d/{district_id}/map")
    def api_map(
        request: Request,
        district_id: str,
        metric: str = DEFAULT_METRIC,
        election_type: str = "presidential",
    ) -> dict:
        """지도 JSON API. 좌표·색·범례는 전부 `viewmodel.py::build_map` 이 이미
        계산해서 낸다 — 프런트는 그 결과를 SVG로 옮겨 그릴 뿐, 산술을 하지 않는다.

        규칙 5: `view`(대시보드와 같은 형태)와 `map` 둘 다 리댁션한다. `map` 은
        `metric`/`metrics`(지표 전환 목록)만 게이트 밖 — Jinja 시절 `map.html` 에서
        지표 전환 nav 가 `output()` 밖에 있던 것과 같다."""
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        view = _view(request, district_id, election_type=et)
        shapes = shapes_for(
            [(c.geo_code, c.geo_name) for c in view.cards],
            path=settings.boundaries_path,
        )
        map_view = build_map(view, shapes, metric_key=metric)
        lens = request.state.lens
        account = getattr(request.state, "account", None)

        view_shows = view.verdict is not None and view.verdict.status != "blocked"
        return {
            "view": _redact_district_view(view, view_shows),
            "map": _redact_output(map_view, ("verdict", "metric", "metrics")),
            "district_id": district_id,
            "districts": available_districts(settings, lens),
            "election_types": election_type_choices(),
            "auth_on": settings.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    @app.get("/d/{district_id}/news", response_class=Response)
    def news_screen(district_id: str) -> Response:
        return _spa_shell()

    @app.get("/api/d/{district_id}/news")
    def api_news(
        request: Request,
        district_id: str,
        sort: str = "date",
        scope: str = "all",
        q: str = "",
    ) -> dict:
        """수집한 지역 기사 목록. 분석기 없이 L1 레코드를 그대로 낸다. `?q=` 로
        제목·언론사·언급어를 부분 문자열 검색한다. `election_type` 축이 없다 —
        기사는 선거 계열에 속하지 않는다(그래서 `election_types` 를 빈 목록으로
        내려 프런트가 그 전환 UI 를 안 그린다).

        규칙 5: 옛 `news.html` 에서 `output(view.verdict)` 게이트가 기사 표
        (`rows`)만 감쌌다 — 요약 집계(건수·상위 언론사·기간)는 게이트 밖이었다.
        API 리댁션도 그 경계를 그대로 지킨다(`_redact_news_view`)."""
        settings: WebSettings = request.app.state.settings
        news = load_news(settings, district_id)
        view = build_news_view(news, _compliance(request), sort=sort, scope=scope, query=q)
        lens = request.state.lens
        account = getattr(request.state, "account", None)

        shows = view.verdict is not None and view.verdict.status != "blocked"
        return {
            "view": _redact_news_view(view, shows),
            "lens": lens.model_dump(mode="json") if lens else None,
            "district_id": district_id,
            "districts": available_districts(settings, lens),
            "election_types": [],
            "auth_on": settings.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    @app.get("/compare", response_class=Response)
    def compare() -> Response:
        return _spa_shell()

    @app.get("/api/compare")
    def api_compare(
        request: Request, sort: str = "name", election_type: str = "presidential"
    ) -> dict:
        """모든 선거구를 하나의 표로. 공용 코퍼스는 전 캠프 읽기 전용이라(P-001 §4)
        관할 밖 선거구도 행은 나오지만 링크는 안 나온다 — `districts`(관할로 좁힌
        목록)에 없는 `district_id` 는 프런트가 링크 대신 평문으로 그린다.

        규칙 5: 옛 `compare.html` 에서 `output(view.verdict)` 게이트가 표(`rows`)만
        감쌌다 — 제외된 선거구 목록(`skipped`)은 게이트 밖이었다. 뉴스와 같은 경계다."""
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        lens = request.state.lens
        comparison = load_comparison(settings, election_type=et)
        view = build_comparison(comparison, _compliance(request), sort=sort, lens=lens)
        account = getattr(request.state, "account", None)

        shows = view.verdict is not None and view.verdict.status != "blocked"
        return {
            "view": _redact_comparison_view(view, shows),
            "lens": lens.model_dump(mode="json") if lens else None,
            "district_id": None,
            "districts": available_districts(settings, lens),
            "election_types": election_type_choices(),
            "auth_on": settings.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    @app.get("/nation", response_class=Response)
    def nation() -> Response:
        return _spa_shell()

    @app.get("/api/nation")
    def api_nation(
        request: Request, sort: str = "code", election_type: str = "presidential"
    ) -> dict:
        """전국 전체 동. 선거구 소속 필터를 의도적으로 건너뛴다 — 전국은 선거구
        하나가 아니다.

        규칙 5: 옛 `nation.html` 에서 `output(view.verdict)` 게이트가 `summary_card`
        와 `cards` 만 감쌌다 — 요약 집계(표시 건수·인구·기준월·출처)는 게이트
        밖이었다. `_redact_nation_view` 가 그 경계를 그대로 지킨다."""
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        lens = request.state.lens
        profiles = load_all_emd(settings, election_type=et)
        view = build_nation_view(profiles, _compliance(request), sort=sort, lens=lens)
        account = getattr(request.state, "account", None)

        shows = view.verdict is not None and view.verdict.status != "blocked"
        return {
            "view": _redact_nation_view(view, shows),
            "lens": lens.model_dump(mode="json") if lens else None,
            "district_id": None,
            "districts": available_districts(settings, lens),
            "election_types": election_type_choices(),
            "auth_on": settings.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    # --- 인증 화면 (P-002 §9) -------------------------------------------------------
    #
    # 여기 넷은 **산출물이 없다.** 그래서 인터넷에 열려도 "의도치 않은 공표"가 되지
    # 않고, 그것이 `DEFAULT_HOST` 전제를 바꾼 근거다 (P-002 §2).

    @app.get("/login", response_class=Response)
    def login_form(request: Request) -> Response:
        if getattr(request.state, "account", None):
            return RedirectResponse("/", status_code=303)
        return _spa_shell()

    @app.post("/api/login")
    def api_login(
        request: Request,
        email: Annotated[str, Body()],
        password: Annotated[str, Body()],
    ) -> Response:
        """React `LoginPage` 가 fetch 로 부른다 — 폼 대신 JSON. 성공하면 세션
        쿠키를 붙인 JSON을, 실패하면 401 JSON을 낸다(리다이렉트가 아니다: fetch가
        따라간 리다이렉트의 최종 응답은 SPA 셸 HTML이라 클라이언트가 성공 여부를
        구분할 수 없다)."""
        s: WebSettings = request.app.state.settings
        ip = _client_ip(request)
        account = control.accounts.authenticate(email, password, path=s.control_db)
        if account is None or account.status is control.Status.SUSPENDED:
            # **왜 실패했는지 나누어 말하지 않는다.** 없는 계정·틀린 비밀번호·정지를
            # 구분해 주면 어느 이메일이 등록돼 있는지 새고, 경쟁 캠프를 함께 받는
            # 제품에서 그건 정보 누출이다 (P-002 §8).
            control.audit.log("login_failed", target=email, ip=ip, path=s.control_db)
            return JSONResponse(
                {"error": "이메일이나 비밀번호가 맞지 않는다"}, status_code=401
            )
        token = control.sessions.start(
            account.id,
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            path=s.control_db,
        )
        control.accounts.touch_login(account.id, path=s.control_db)
        control.audit.log(
            "login", account_id=account.id, camp_id=account.camp_id, ip=ip, path=s.control_db
        )
        return _with_session(JSONResponse({"ok": True}), request, token)

    @app.post("/logout", response_class=Response)
    def logout(request: Request) -> Response:
        """POST 만 받는다. GET 이면 남의 페이지에 심은 이미지 한 장으로 로그아웃된다."""
        s: WebSettings = request.app.state.settings
        account = getattr(request.state, "account", None)
        control.sessions.end(request.cookies.get(control.COOKIE_NAME), path=s.control_db)
        if account:
            control.audit.log(
                "logout",
                account_id=account.id,
                camp_id=account.camp_id,
                ip=_client_ip(request),
                path=s.control_db,
            )
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(control.COOKIE_NAME)
        return response

    @app.get("/signup", response_class=Response)
    def signup_form(request: Request) -> Response:
        if getattr(request.state, "account", None):
            return RedirectResponse("/", status_code=303)
        return _spa_shell()

    @app.post("/api/signup")
    def api_signup(
        request: Request,
        email: Annotated[str, Body()],
        password: Annotated[str, Body()],
        candidate_name: Annotated[str, Body()],
        contact: Annotated[str, Body()],
        wanted_election: Annotated[str, Body()] = "",
    ) -> Response:
        """**신청은 가볍게 받는다.** 관할·진영·선거일은 승인 뒤 온보딩에서 받는다 —
        캠프가 아직 확정하지 못한 값을 신청서에 억지로 적게 하지 않는다 (P-002 §6)."""
        s: WebSettings = request.app.state.settings
        try:
            req = control.signup.request(
                email,
                password,
                candidate_name,
                contact,
                wanted_election.strip() or None,
                path=s.control_db,
            )
        except (control.SignupError, control.AccountError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        # 신청 직후 로그인시킨다. 이 세션이 볼 수 있는 것은 `/pending` 하나뿐이다.
        token = control.sessions.start(req.account_id, ip=_client_ip(request), path=s.control_db)
        control.audit.log(
            "signup",
            account_id=req.account_id,
            target=email,
            ip=_client_ip(request),
            path=s.control_db,
        )
        return _with_session(JSONResponse({"ok": True}), request, token)

    @app.get("/pending", response_class=Response)
    def pending() -> Response:
        return _spa_shell()

    @app.get("/api/pending")
    def api_pending(request: Request) -> dict:
        """승인 대기. **공용 데이터도 보여주지 않는다** — 승인 전에는 아무것도 없다."""
        s: WebSettings = request.app.state.settings
        account = getattr(request.state, "account", None)
        req = (
            control.signup.for_account(account.id, path=s.control_db)
            if account and not account.is_operator
            else None
        )
        return {
            "request": (
                {
                    "candidate_name": req.candidate_name,
                    "contact": req.contact,
                    "wanted_election": req.wanted_election,
                    "requested_at": req.requested_at,
                }
                if req
                else None
            ),
            "auth_on": s.auth,
            "account": (
                {"email": account.email, "is_operator": account.is_operator} if account else None
            ),
        }

    @app.get("/onboarding", response_class=Response)
    def onboarding_form() -> Response:
        return _spa_shell()

    @app.get("/api/onboarding")
    def api_onboarding_form(request: Request) -> dict:
        settings: WebSettings = request.app.state.settings
        return {"form": {}, "first": True, **_cycle_form_options(settings)}

    @app.post("/api/onboarding")
    def api_onboarding(request: Request, form: CycleForm) -> Response:
        """관할·진영·선거일을 받아 `cycles/<id>/` 를 만든다. React `CycleFormPage`
        가 fetch 로 부른다(온보딩·주기 추가 공용 — `_save_cycle` 이 공유 경로다).

        여기가 **온보딩 완료 지점**이다. 이 파일들이 생기기 전까지 캠프 계정은
        데이터 화면을 볼 수 없다 — 관할을 모르면 무엇을 보여줄지 알 수 없으므로
        fail-closed 가 자연스럽다 (P-002 §6).
        """
        return _save_cycle_json(request, form, action="onboarding")

    @app.get("/cycles", response_class=Response)
    def cycles() -> Response:
        return _spa_shell()

    @app.get("/api/cycles")
    def api_cycles(request: Request) -> dict:
        """이 캠프의 선거 주기 목록. **캠프는 영속이고 선거가 그 안에서 바뀐다** (P-001 §7).

        지금 어느 주기를 보고 있는지 여기서 말한다 — 선택은 자동(선거일 기준)이라
        캠프가 고를 것은 없지만, 무엇을 보고 있는지는 알아야 한다.
        """
        from pydantic import ValidationError

        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        account = request.state.account
        lens = request.state.lens
        camp_id = account.camp_id
        current = lens.cycle_id if lens else None

        rows = []
        for cid in camp_mod.list_cycles(camp_id, s.camps_root):
            try:
                cycle = camp_mod.load_cycle(
                    camp_id, cid, s.camps_root, districts_path=s.districts_path
                )
            except (camp_mod.CampConfigError, FileNotFoundError, ValidationError) as exc:
                rows.append(
                    {
                        "id": cid,
                        "error": str(exc),
                        "cycle": None,
                        "roster": None,
                        "current": cid == current,
                    }
                )
                continue
            try:
                roster = camp_mod.load_roster(camp_id, cid, s.camps_root)
            except (FileNotFoundError, ValidationError):
                # 로스터가 깨져도 주기 설정은 보여준다. 고치러 갈 링크가 필요하다.
                roster = None
            rows.append(
                {
                    "id": cid,
                    "error": None,
                    "cycle": cycle.model_dump(mode="json"),
                    "roster": roster.model_dump(mode="json") if roster else None,
                    "current": cid == current,
                }
            )

        return {
            "rows": rows,
            "today": dt.date.today().isoformat(),
            "lens": lens.model_dump(mode="json") if lens else None,
            "auth_on": s.auth,
            "account": {"email": account.email, "is_operator": account.is_operator},
        }

    @app.get("/cycles/new", response_class=Response)
    def new_cycle_form() -> Response:
        return _spa_shell()

    @app.get("/api/cycles/new")
    def api_new_cycle_form(request: Request) -> dict:
        settings: WebSettings = request.app.state.settings
        return {"form": {}, "first": False, **_cycle_form_options(settings)}

    @app.post("/api/cycles/new")
    def api_new_cycle(request: Request, form: CycleForm) -> Response:
        """다음 선거 주기를 추가한다. 관할도 진영도 바뀔 수 있으므로 전부 다시 받는다 —
        구청장에 나갔다가 다음엔 시의원에 나갈 수 있고 당적도 바뀐다 (P-001 §7)."""
        return _save_cycle_json(request, form, action="add_cycle")

    def _save_cycle_json(request: Request, form: CycleForm, *, action: str) -> Response:
        """온보딩과 주기 추가가 **같은 저장 경로를 쓴다.** 첫 주기와 두 번째 주기가
        다른 파일을 만들 이유가 없고, 갈라두면 한쪽만 고치는 일이 생긴다."""
        from votelink import camp as camp_mod
        from votelink.camp import scaffold

        s: WebSettings = request.app.state.settings
        account = request.state.account
        values = form.model_dump()
        try:
            cycle = build_cycle(s, values)
            info = camp_mod.load_camp(account.camp_id, s.camps_root)
            cycle_id = scaffold.cycle_id_or_undated(cycle)
            scaffold.write_cycle(
                account.camp_id,
                cycle_id,
                cycle,
                info.candidate_name,
                form.party.strip(),
                bool(form.incumbent),
                root=s.camps_root,
            )
        except (ValueError, scaffold.ScaffoldError, camp_mod.CampConfigError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        control.audit.log(
            action,
            account_id=account.id,
            camp_id=account.camp_id,
            target=cycle_id,
            detail={"emd_count": len(cycle.territory.emd_codes)},
            ip=_client_ip(request),
            path=s.control_db,
        )
        # 어디로 보낼지는 프런트가 안다(온보딩은 "/", 주기 추가는 "/cycles" — 호출한
        # 화면이 이미 그 구분을 갖고 있다). 여기는 저장됐다는 사실만 말한다.
        return JSONResponse({"ok": True, "cycle_id": cycle_id})

    # --- 주기 수정 — 저장 전에 무엇이 바뀌는지 보여주고 확인받는다 -------------------
    #
    # **관할이 틀리면 에러 없이 모든 분석이 조용히 틀린다** (P-001 §16). 그래서 수정은
    # 두 단계다: 폼 → 미리보기(확인) → 저장. 미리보기는 상태를 어디에도 저장하지 않고
    # 폼 값을 hidden 으로 다시 넘긴다 — 확인 화면 하나 때문에 세션 저장소를 들이지 않는다.

    def _own_cycle(request: Request, cycle_id: str) -> str:
        """이 캠프의 주기가 맞는지 확인하고 그 id 를 돌려준다.

        **경로 파라미터를 파일 경로에 그대로 쓰지 않는다.** Starlette 가 `%2F` 를
        라우팅 전에 풀어서 탈출은 실제로 닿지 않지만, 그 사실에 기대지 않는다 —
        `list_cycles` 화이트리스트가 유일하게 안전한 검사이고, 덤으로 모르는 주기에
        깔끔한 404 를 준다.
        """
        s: WebSettings = request.app.state.settings
        return _cycle_in_camp(s, request.state.account.camp_id, cycle_id)

    @app.get("/cycles/{cycle_id}/edit", response_class=Response)
    def edit_cycle_form(cycle_id: str) -> Response:
        return _spa_shell()

    @app.get("/api/cycles/{cycle_id}/edit")
    def api_edit_cycle_form(request: Request, cycle_id: str) -> dict:
        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        cid = _own_cycle(request, cycle_id)
        cycle = camp_mod.load_cycle(
            request.state.account.camp_id, cid, s.camps_root, districts_path=s.districts_path
        )
        options = _cycle_form_options(s)
        return {
            "cycle_id": cid,
            "form": _prefill_cycle_form(cycle, options["emd_groups"]),
            **options,
        }

    @app.post("/api/cycles/{cycle_id}/edit")
    def api_preview_cycle(request: Request, cycle_id: str, form: CycleForm) -> Response:
        """**저장하지 않는다.** 무엇이 바뀌는지 계산해 돌려준다 — React `CycleEditPage`
        가 이 값으로 확인 화면을 그리고, 확인을 누르면 같은 폼 값을 `/api/cycles/{id}/apply`
        로 다시 보낸다. `change.is_empty` 가 참이면 프런트가 확인 화면 없이 목록으로
        바로 돌아간다 — 옛 Jinja 라우트가 그 경우 `/cycles` 로 리다이렉트하던 것과
        같은 판단이다."""
        from votelink import camp as camp_mod
        from votelink.camp.changes import diff_cycle

        s: WebSettings = request.app.state.settings
        cid = _own_cycle(request, cycle_id)
        before = camp_mod.load_cycle(
            request.state.account.camp_id, cid, s.camps_root, districts_path=s.districts_path
        )
        try:
            after = build_cycle(s, form.model_dump())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        change = diff_cycle(before, after, cid, s.districts_path)
        return JSONResponse({"change": _change_to_json(change)})

    @app.post("/api/cycles/{cycle_id}/apply")
    def api_apply_cycle(request: Request, cycle_id: str, form: CycleForm) -> Response:
        """확인을 거친 수정을 저장한다.

        **폴더를 먼저 옮기고 내용을 쓴다.** 이동이 더 실패하기 쉬운 연산이라(대상이 이미
        있을 수 있다) 먼저 실패하면 아무것도 안 바뀐다. 반대로 이동 뒤 쓰기가 실패하면
        폴더 이름과 내용이 어긋나는데, 그건 `load_cycle` 의 폴더명 검증이 다음 읽기에서
        곧바로 드러낸다 — 조용히 틀린 답을 주지 않는다.
        """
        from votelink import camp as camp_mod
        from votelink.camp import scaffold
        from votelink.camp.changes import diff_cycle

        s: WebSettings = request.app.state.settings
        account = request.state.account
        cid = _own_cycle(request, cycle_id)
        values = form.model_dump()
        before = camp_mod.load_cycle(
            account.camp_id, cid, s.camps_root, districts_path=s.districts_path
        )
        try:
            after = build_cycle(s, values)
            change = diff_cycle(before, after, cid, s.districts_path)
            new_id = change.cycle_id_after
            target = scaffold.rename_cycle(account.camp_id, cid, new_id, s.camps_root)
            scaffold.write_election(account.camp_id, new_id, after, s.camps_root)
        except (ValueError, scaffold.ScaffoldError, camp_mod.CampConfigError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        control.audit.log(
            "edit_cycle",
            account_id=account.id,
            camp_id=account.camp_id,
            target=change.cycle_id_after,
            # **무엇이 바뀌었는지 남긴다** — P-001 §11 의 "갱신 이력 노출"이 여기서도
            # 필요하다. 관할이 바뀌면 그 뒤의 모든 숫자가 달라지므로, 나중에 "왜
            # 지난주와 다른가"를 물을 때 답할 수 있어야 한다.
            detail={
                "from": cid,
                "added": len(change.added),
                "removed": len(change.removed),
                "lineage": (
                    f"{change.lineage_before.value}→{change.lineage_after.value}"
                    if change.lineage_flipped
                    else None
                ),
                "moved": str(target.name) if change.moved else None,
            },
            ip=_client_ip(request),
            path=s.control_db,
        )
        return JSONResponse({"ok": True})

    @app.get("/cycles/{cycle_id}/roster", response_class=Response)
    def roster_form(cycle_id: str) -> Response:
        return _spa_shell()

    @app.get("/api/cycles/{cycle_id}/roster")
    def api_roster_form(request: Request, cycle_id: str) -> dict:
        """로스터 폼이 채울 값. 저장된 로스터가 있으면 그것을, 없으면 빈 폼을 낸다."""
        from pydantic import ValidationError

        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        camp_id = request.state.account.camp_id
        cid = _own_cycle(request, cycle_id)
        try:
            roster = camp_mod.load_roster(camp_id, cid, s.camps_root)
            form = {
                "ours_name": roster.ours.name,
                "ours_party": roster.ours.party,
                "ours_lineage": roster.ours.lineage.value,
                "ours_incumbent": roster.ours.incumbent,
                "opponents": roster_text(roster),
            }
        except (FileNotFoundError, ValidationError):
            # 로스터 파일이 깨졌거나 없다. 빈 폼으로 다시 만들 수 있게 둔다.
            form = {
                "ours_name": "",
                "ours_party": "",
                "ours_lineage": "",
                "ours_incumbent": False,
                "opponents": "",
            }
        return {
            "cycle_id": cid,
            "form": form,
            "lineage_options": [(c.value, label) for label, c in CAMP_ALIASES.items()],
        }

    @app.post("/api/cycles/{cycle_id}/roster")
    def api_save_roster(
        request: Request,
        cycle_id: str,
        ours_name: Annotated[str, Body()],
        ours_party: Annotated[str, Body()],
        ours_lineage: Annotated[str, Body()],
        opponents: Annotated[str, Body()] = "",
        ours_incumbent: Annotated[bool, Body()] = False,
    ) -> Response:
        """후보 로스터를 저장한다. React `RosterPage` 가 fetch 로 부른다.

        관할과 달리 **틀려도 분석을 바꾸지 않는다** — 로스터는 화면 표기에만 쓰이고
        진영별 집계는 `party_lineage.yaml` 이 한다. 그래서 확인 단계를 두지 않는다.
        """
        from votelink.camp import scaffold

        s: WebSettings = request.app.state.settings
        account = request.state.account
        cid = _own_cycle(request, cycle_id)
        form = RosterForm(
            ours_name=ours_name,
            ours_party=ours_party,
            ours_lineage=ours_lineage,
            ours_incumbent="1" if ours_incumbent else "",
            opponents=opponents,
        )
        try:
            roster = parse_roster(form)
            scaffold.write_roster(account.camp_id, cid, roster, s.camps_root)
        except (ValueError, scaffold.ScaffoldError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        control.audit.log(
            "edit_roster",
            account_id=account.id,
            camp_id=account.camp_id,
            target=cid,
            detail={"opponents": len(roster.opponents)},
            ip=_client_ip(request),
            path=s.control_db,
        )
        return JSONResponse({"ok": True})

    # --- 내 계정 -------------------------------------------------------------------
    #
    # **로그인한 사람은 누구나 연다** — 승인 대기든 온보딩 전이든 운영자든.
    # 비밀번호를 바꾸는 일은 계정 상태와 무관하고, 특히 부트스트랩 운영자는
    # 여기 말고는 바꿀 데가 없다.

    @app.get("/me", response_class=Response)
    def me() -> Response:
        return _spa_shell()

    @app.get("/api/me")
    def api_me(request: Request) -> dict:
        """내 계정 화면. **참조 데이터도 산출물도 읽지 않는다** — 계정 정보뿐이다."""
        settings: WebSettings = request.app.state.settings
        account = request.state.account
        return {
            "account": {
                "email": account.email,
                "is_operator": account.is_operator,
                "camp_id": account.camp_id,
                "created_at": account.created_at,
                "last_login_at": account.last_login_at,
            },
            "sessions": control.sessions.active_count(account.id, path=settings.control_db),
            "bootstrap": bootstrap_password(request),
            "auth_on": settings.auth,
        }

    @app.post("/api/me")
    def api_change_password(
        request: Request,
        # 셋 다 기본값이 `""` 다. React `MePage` 가 빈 값을 그대로 보낼 수 있고,
        # 그러면 사용자가 우리 오류 화면 대신 FastAPI 422 를 마주한다. 여기까지
        # 오게 두고 아래에서 우리 말로 거절한다.
        current: Annotated[str, Body()] = "",
        new: Annotated[str, Body()] = "",
        confirm: Annotated[str, Body()] = "",
    ) -> Response:
        """비밀번호 변경. 이 앱에서 **자기 비밀번호를 바꾸는 유일한 통로**다.

        React `MePage` 가 fetch 로 부른다 — 로그인·가입과 같은 이유로 JSON 이다."""
        s: WebSettings = request.app.state.settings
        account = request.state.account

        def fail(message: str) -> Response:
            return JSONResponse({"error": message}, status_code=400)

        # **현재 비밀번호를 확인한다.** 세션이 탈취돼도 비밀번호까지 바꾸지는 못하게 —
        # 그러지 않으면 잠깐의 세션 탈취가 계정 탈취가 된다.
        if control.accounts.authenticate(account.email, current, path=s.control_db) is None:
            control.audit.log(
                "change_password_failed",
                account_id=account.id,
                camp_id=account.camp_id,
                ip=_client_ip(request),
                path=s.control_db,
            )
            return fail("지금 쓰는 비밀번호가 맞지 않는다")
        if new != confirm:
            return fail("새 비밀번호 두 개가 서로 다르다")
        if new == control.accounts.BOOTSTRAP_PASSWORD:
            # 되돌리면 기동 가드(`cli.py`)가 무의미해진다. 아는 비밀번호는 인증이 아니다.
            return fail("배포 기본 비밀번호로는 되돌릴 수 없다")
        try:
            control.accounts.set_password(account.id, new, path=s.control_db)
        except control.AccountError as exc:
            return fail(str(exc))

        # **다른 기기의 세션을 전부 끊는다.** 비밀번호를 바꾸는 이유가 유출일 수 있고,
        # 그때 남은 세션을 살려두면 바꾼 의미가 없다. 대신 지금 이 세션은 새로 발급해
        # 바꾼 사람이 자기도 로그아웃되는 일이 없게 한다.
        control.sessions.end_all(account.id, path=s.control_db)
        token = control.sessions.start(
            account.id,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            path=s.control_db,
        )
        control.audit.log(
            "change_password",
            account_id=account.id,
            camp_id=account.camp_id,
            ip=_client_ip(request),
            path=s.control_db,
        )
        request.app.state.bootstrap_password = control.accounts.uses_bootstrap_password(
            path=s.control_db
        )
        return _with_session(JSONResponse({"ok": True}), request, token)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    # 운영자 콘솔은 별도 모듈이다 (P-003 §6: "화면 넷이 서로 다른 성격이라 구현은
    # 나눠서 해도 된다"). 접근 통제는 라우터가 아니라 미들웨어에 있다 — 라우터에
    # 걸면 `include_router` 를 잊은 다음 사람이 통제까지 함께 잊는다.
    app.include_router(ops.router)
    app.include_router(ops.api_router)

    for error in SETUP_ERRORS:
        app.add_exception_handler(error, _setup_error)

    # 없는 캠프·주기는 **404 다.** 설정 오류(500)와 구분한다 — "고칠 것이 있다"와
    # "그런 것이 없다"는 사람이 할 일이 다르다. URL 을 손으로 친 경우가 대부분이다.
    from votelink.camp import CampNotFound, CycleNotFound

    for error in (CampNotFound, CycleNotFound):
        app.add_exception_handler(error, _not_found)

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

    **요청별이다.** 인증이 켜지면 검토 기록도 선거일도 세션의 캠프에서 온다.
    """
    settings: WebSettings = request.app.state.settings
    return Compliance(
        policy=load_policy(settings.policy_path),
        review=request.state.review,
        election_day=request.state.election_day,
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
        lens=request.state.lens,
    )


def _candidate_comparison(request: Request, view):
    """후보자 비교 — 렌즈와 로스터가 둘 다 있을 때만. 사진·인지도·호감도는 없는
    데이터라 만들지 않는다 (있는 데이터: 지지율·최근 변화·지역 강세만)."""
    lens = request.state.lens
    if lens is None:
        return None
    from pydantic import ValidationError

    from votelink import camp as camp_mod

    settings: WebSettings = request.app.state.settings
    try:
        roster = camp_mod.load_roster(lens.camp_id, lens.cycle_id, settings.camps_root)
    except (FileNotFoundError, ValidationError):
        # 로스터가 없거나 깨져도 대시보드는 뜬다 — 후보자 비교 섹션만 조용히 빠진다.
        return None
    if not roster.opponents:
        return None
    return build_candidate_comparison(lens, roster.opponents[0].name, view.cards, view.summary_card)


# --- 규칙 5: JSON API 경계에서의 집행 ------------------------------------------------
#
# `_output.html` 이 하던 일(blocked/판정없음 이면 콘텐츠를 안 그린다)을 JSON
# 응답 자체에서도 한다. 프런트엔드의 ComplianceGate 는 "예쁘게 숨기는" 역할만
# 하고, "실제로 안 보낸다"는 여기가 한다 — 네트워크 탭에 남는 것과 화면에
# 안 보이는 것은 다른 문제다.

_VIEW_CONTENT_FIELDS = (
    "cards",
    "summary_card",
    "situation",
    "insights",
    "watchlist",
    "region_status",
    "region_category",
    "population_total",
    "population_months",
    "as_of_months",
    "source_names",
    "source_licenses",
    "missing_gaps",
    "avg_confidence",
)
"""`DistrictView` 필드 중 `output(view.verdict)` 게이트 **안**에서만 그리는 것들
(대시보드 3차 리디자인 `dashboard.html` 기준). 페이지 헤더(district_name·
coverage_text·diagnostics 등)는 게이트 밖이라 여기 없다 — 원래도 보이던 것들이다."""


def _redact_district_view(view, shows: bool) -> dict:
    data = view.model_dump(mode="json")
    if shows:
        return data
    data.update(
        {
            "cards": [],
            "summary_card": None,
            "situation": None,
            "insights": [],
            "watchlist": [],
            "region_status": {},
            "region_category": {},
            "population_total": 0,
            "population_months": [],
            "as_of_months": [],
            "source_names": [],
            "source_licenses": [],
            "missing_gaps": 0,
            "avg_confidence": 0.0,
        }
    )
    return data


def _redact_news_view(view, shows: bool) -> dict:
    """뉴스는 요약 집계(건수·언론사·기간·지명·인물)와 기사 표(`rows`)의 리댁션
    경계가 다르다 — 옛 `news.html` 에서 `output()` 게이트가 표만 감쌌던 그대로다."""
    data = view.model_dump(mode="json")
    if not shows:
        data["rows"] = []
    return data


def _redact_comparison_view(view, shows: bool) -> dict:
    """`compare.html` 에서 `output()` 게이트가 표(`rows`)만 감쌌다 — 제외된
    선거구 목록(`skipped`)은 게이트 밖이었다. 뉴스와 같은 경계 판단."""
    data = view.model_dump(mode="json")
    if not shows:
        data["rows"] = []
    return data


def _redact_nation_view(view, shows: bool) -> dict:
    """`nation.html` 에서 `output()` 게이트가 `summary_card`·`cards` 만 감쌌다 —
    요약 집계(표시 건수·인구·기준월·출처)는 게이트 밖이었다."""
    data = view.model_dump(mode="json")
    if not shows:
        data["cards"] = []
        data["summary_card"] = None
    return data


def _zero_like(value):
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    if isinstance(value, str):
        return ""
    return None


def _redact_output(model, keep: tuple[str, ...]) -> dict | None:
    """뉴스 펄스·이슈 보드처럼 **본문에 중첩 객체가 없는** 산출물용 범용 리댁션.
    `keep`(보통 `("verdict",)`) 밖의 필드는 전부 같은 타입의 빈 값으로 지운다."""
    if model is None:
        return None
    data = model.model_dump(mode="json")
    verdict = data.get("verdict")
    shows = verdict is not None and verdict.get("status") != "blocked"
    if shows:
        return data
    return {k: (v if k in keep else _zero_like(v)) for k, v in data.items()}


def _ctx(request: Request, district_id: str | None = None, **extra) -> dict:
    """모든 화면이 공유하는 컨텍스트 — 현재 선거구, 전환 목록, 선거 계열 목록, 렌즈, 로그인 상태."""
    settings: WebSettings = request.app.state.settings
    lens = getattr(request.state, "lens", None)
    return {
        "district_id": district_id,
        "districts": available_districts(settings, lens),
        "election_types": election_type_choices(),
        "lens": lens,
        "account": getattr(request.state, "account", None),
        "auth_on": settings.auth,
        **extra,
    }


def _cycle_form_options(settings: WebSettings) -> dict:
    """주기 폼이 고를 값들. 선택지는 전부 코드가 아니라 참조 데이터·enum 에서 온다.

    `/api/onboarding`·`/api/cycles/new`·`/api/cycles/{id}/edit`(캠프)·
    `/api/ops/camps/{id}/cycles/{cid}/edit`(운영자 대리 수정)가 전부 이 데이터를
    쓴다 — 계산은 한 곳에만 둔다.
    """
    from votelink.camp.models import Office
    from votelink.reference.districts import load_districts

    table = load_districts(settings.districts_path)
    # 동 이름 체크박스(shuttle)가 고를 수 있는 행정동. code=null 인 미확인 동은
    # 빠진다 — 코드가 없으면 관할에 넣을 수 없다(백필 D-001 이 먼저다). 자치구별로
    # 묶어 낸다. 이름이 겹치는 동이 자치구 경계를 넘는 일은 없다.
    emd_seen: set[str] = set()
    emd_by_sigungu: dict[str, list[tuple[str, str]]] = {}
    for d in table.values():
        for e in d.emd:
            if not e.code or e.code in emd_seen:
                continue
            emd_seen.add(e.code)
            emd_by_sigungu.setdefault(d.sigungu, []).append((e.code, e.name))
    emd_groups = [
        (sg, sorted(emd_by_sigungu[sg], key=lambda ce: ce[1])) for sg in sorted(emd_by_sigungu)
    ]
    return {
        "presets": sorted((d.id, d.name) for d in table.values()),
        "sigungus": sorted({d.sigungu for d in table.values() if d.sigungu}),
        "emd_groups": emd_groups,
        "type_options": election_type_choices(),
        "office_options": [(o.value, OFFICE_LABELS[o]) for o in Office],
        "lineage_options": [(c.value, CAMP_LABELS[c]) for c in Camp],
    }


def _prefill_cycle_form(cycle, emd_groups: list[tuple[str, list[tuple[str, str]]]]) -> dict:
    """저장된 주기 → 수정 폼의 초기값. 현재 관할을 shuttle 오른쪽(선택됨)에 미리
    채운다(P-005 §9). districts.yaml 이 아는 코드는 `emd_pick` 으로 — 위젯이 이름으로
    보여준다. 모르는(미확인) 코드는 `emd_pick` 에 넣으면 `build_cycle` 이 저장을
    거부하므로 textarea(`emd_codes`)로 내린다."""
    known = {code for _sg, items in emd_groups for code, _name in items}
    picked = [c for c in cycle.territory.emd_codes if c in known]
    unknown = [c for c in cycle.territory.emd_codes if c not in known]
    return {
        "election_type": cycle.election.type.value,
        "office": cycle.election.office.value,
        "election_date": cycle.election.date.isoformat() if cycle.election.date else "",
        "lineage": cycle.lineage.value,
        # `party` 는 로스터(candidates.yaml)에 있고 여기서는 안 고친다.
        # 주기 폼과 로스터 폼이 같은 값을 두 곳에서 쓰면 어긋난다.
        "party": "",
        "preset": cycle.territory.preset or "",
        "sigungu": "",
        "emd_pick": picked,
        "emd_codes": "\n".join(unknown),
        "legal_reviewer": cycle.legal_reviewer or "",
    }


def _change_to_json(change) -> dict:
    """`camp/changes.py::CycleChange`(plain dataclass) → JSON. Pydantic이 아니라서
    `model_dump` 가 없다 — enum 은 `.value` 로 직접 꺼낸다."""

    def opt_enum(v):
        return v.value if v is not None else None

    def opt_date(v):
        return v.isoformat() if v is not None else None

    return {
        "cycle_id_before": change.cycle_id_before,
        "cycle_id_after": change.cycle_id_after,
        "date_before": opt_date(change.date_before),
        "date_after": opt_date(change.date_after),
        "type_before": opt_enum(change.type_before),
        "type_after": opt_enum(change.type_after),
        "office_before": opt_enum(change.office_before),
        "office_after": opt_enum(change.office_after),
        "lineage_before": opt_enum(change.lineage_before),
        "lineage_after": opt_enum(change.lineage_after),
        "reviewer_before": change.reviewer_before,
        "reviewer_after": change.reviewer_after,
        "added": [{"code": e.code, "name": e.name, "label": e.label} for e in change.added],
        "removed": [{"code": e.code, "name": e.name, "label": e.label} for e in change.removed],
        "kept": change.kept,
        "opened": list(change.opened),
        "closed": list(change.closed),
        "moved": change.moved,
        "lineage_flipped": change.lineage_flipped,
        "territory_changed": change.territory_changed,
        "is_empty": change.is_empty,
    }


def _cycle_in_camp(settings: WebSettings, camp_id: str, cycle_id: str) -> str:
    """이 캠프에 이 주기가 있는지 화이트리스트로 확인하고 그 id 를 돌려준다.

    **경로 파라미터를 파일 경로에 그대로 쓰지 않는다.** `list_cycles` 화이트리스트가
    유일하게 안전한 검사이고, 덤으로 모르는 주기에 깔끔한 404 를 준다. 캠프 라우트는
    세션 계정의 `camp_id` 를, 운영자 라우트는 URL 경로의 `camp_id` 를 넘긴다 (P-005 §4).
    """
    from votelink import camp as camp_mod

    if cycle_id not in camp_mod.list_cycles(camp_id, settings.camps_root):
        raise camp_mod.CycleNotFound(f"선거 주기 '{cycle_id}' 가 이 캠프에 없다")
    return cycle_id




def _with_session(response: Response, request: Request, token: str) -> Response:
    """세션 쿠키를 붙인다.

    - `httponly` — 스크립트가 읽지 못한다.
    - `samesite=lax` — 남의 사이트에서 건너온 POST 에는 쿠키가 실리지 않는다.
      **CSRF 토큰을 따로 두지 않는 근거가 이것이다** (P-002 §8).
    - `secure` — 요청이 https 로 들어왔을 때만 붙인다. 프록시가 TLS 를 끊는 구성이면
      uvicorn 을 `--proxy-headers` 로 띄워야 이 판정이 맞는다.
    """
    response.set_cookie(
        control.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=int(control.sessions.IDLE_TTL.total_seconds()),
        path="/",
    )
    return response


def _not_found(request: Request, exc: Exception) -> Response:
    """없는 캠프·주기. 설정이 깨진 것이 아니라 그런 것이 없는 것이다."""
    return _render(
        request,
        "error.html",
        base_ctx(request, message=str(exc), kind="찾을 수 없다"),
        status_code=404,
    )


def _setup_error(request: Request, exc: Exception) -> Response:
    """설정·참조 데이터 오류.

    이 화면도 로그인 상태를 들고 가야 한다 — 여기서만 상태를 잃으면 사용자는 자기가
    로그아웃된 줄 안다 (P-002 §8 이 지목한, `_ctx` 를 비껴가던 자리다).

    다만 `_ctx` 를 그대로 부를 수는 없다. 선거구 목록을 읽다가 난 오류가 바로 이
    화면을 부른 원인일 수 있어서, 같은 읽기를 다시 하면 오류 화면 자체가 죽는다.
    """
    base = {"message": str(exc), "kind": type(exc).__name__}
    try:
        ctx = _ctx(request, **base)
    except Exception:  # noqa: BLE001 - 오류 화면이 오류로 죽지 않게 한다
        ctx = base_ctx(request, **base)
    return _render(request, "error.html", ctx, status_code=500)
