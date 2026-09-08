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
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from votelink import control
from votelink.contract.enums import Camp, ElectionType
from votelink.reference.compliance import EMPTY_REVIEW, Compliance, load_policy, load_review
from votelink.reference.districts import DistrictNotFound
from votelink.web import auth
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
    CAMP_LABELS,
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
    if s.auth:
        # 스키마를 앱이 스스로 만든다. 여러 번 불러도 안전하고, "승인은 CLI 로 했는데
        # 웹은 테이블이 없다"는 어긋남이 생기지 않는다. 레코드가 아니므로
        # "L3 는 레코드를 쓰지 않는다"(web/__init__.py)를 깨지 않는다.
        control.init(s.control_db)

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
            comparison, _compliance(request), sort=sort, lens=request.state.lens
        )
        return _render(request, "compare.html", _ctx(request, view=view))

    @app.get("/nation", response_class=Response)
    def nation(
        request: Request, sort: str = "code", election_type: str = "presidential"
    ) -> Response:
        settings: WebSettings = request.app.state.settings
        et = resolve_election_type(election_type)
        profiles = load_all_emd(settings, election_type=et)
        view = build_nation_view(profiles, _compliance(request), sort=sort, lens=request.state.lens)
        return _render(request, "nation.html", _ctx(request, view=view))

    # --- 인증 화면 (P-002 §9) -------------------------------------------------------
    #
    # 여기 넷은 **산출물이 없다.** 그래서 인터넷에 열려도 "의도치 않은 공표"가 되지
    # 않고, 그것이 `DEFAULT_HOST` 전제를 바꾼 근거다 (P-002 §2).

    @app.get("/login", response_class=Response)
    def login_form(request: Request) -> Response:
        if getattr(request.state, "account", None):
            return RedirectResponse("/", status_code=303)
        return _render(request, "login.html", _auth_ctx(request))

    @app.post("/login", response_class=Response)
    def login(
        request: Request,
        email: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Response:
        s: WebSettings = request.app.state.settings
        ip = _client_ip(request)
        account = control.accounts.authenticate(email, password, path=s.control_db)
        if account is None or account.status is control.Status.SUSPENDED:
            # **왜 실패했는지 나누어 말하지 않는다.** 없는 계정·틀린 비밀번호·정지를
            # 구분해 주면 어느 이메일이 등록돼 있는지 새고, 경쟁 캠프를 함께 받는
            # 제품에서 그건 정보 누출이다 (P-002 §8).
            control.audit.log("login_failed", target=email, ip=ip, path=s.control_db)
            return _render(
                request,
                "login.html",
                _auth_ctx(request, error="이메일이나 비밀번호가 맞지 않는다", email=email),
                status_code=401,
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
        return _with_session(RedirectResponse("/", status_code=303), request, token)

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
        return _render(request, "signup.html", _auth_ctx(request))

    @app.post("/signup", response_class=Response)
    def signup(
        request: Request,
        email: Annotated[str, Form()],
        password: Annotated[str, Form()],
        candidate_name: Annotated[str, Form()],
        contact: Annotated[str, Form()],
        wanted_election: Annotated[str, Form()] = "",
    ) -> Response:
        """**신청은 가볍게 받는다.** 관할·진영·선거일은 승인 뒤 온보딩에서 받는다 —
        캠프가 아직 확정하지 못한 값을 신청서에 억지로 적게 하지 않는다 (P-002 §6)."""
        s: WebSettings = request.app.state.settings
        form = {
            "email": email,
            "candidate_name": candidate_name,
            "contact": contact,
            "wanted_election": wanted_election,
        }
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
            return _render(
                request, "signup.html", _auth_ctx(request, error=str(exc), **form), status_code=400
            )

        # 신청 직후 로그인시킨다. 이 세션이 볼 수 있는 것은 `/pending` 하나뿐이다.
        token = control.sessions.start(req.account_id, ip=_client_ip(request), path=s.control_db)
        control.audit.log(
            "signup",
            account_id=req.account_id,
            target=email,
            ip=_client_ip(request),
            path=s.control_db,
        )
        return _with_session(RedirectResponse("/pending", status_code=303), request, token)

    @app.get("/pending", response_class=Response)
    def pending(request: Request) -> Response:
        """승인 대기. **공용 데이터도 보여주지 않는다** — 승인 전에는 아무것도 없다."""
        s: WebSettings = request.app.state.settings
        account = getattr(request.state, "account", None)
        req = (
            control.signup.for_account(account.id, path=s.control_db)
            if account and not account.is_operator
            else None
        )
        return _render(request, "pending.html", _auth_ctx(request, request_row=req))

    @app.get("/onboarding", response_class=Response)
    def onboarding_form(request: Request) -> Response:
        return _render(request, "onboarding.html", _onboarding_ctx(request))

    @app.post("/onboarding", response_class=Response)
    def onboarding(
        request: Request,
        election_type: Annotated[str, Form()],
        office: Annotated[str, Form()],
        lineage: Annotated[str, Form()],
        party: Annotated[str, Form()],
        election_date: Annotated[str, Form()] = "",
        incumbent: Annotated[str, Form()] = "",
        preset: Annotated[str, Form()] = "",
        sigungu: Annotated[str, Form()] = "",
        emd_codes: Annotated[str, Form()] = "",
        legal_reviewer: Annotated[str, Form()] = "",
    ) -> Response:
        """관할·진영·선거일을 받아 `cycles/<id>/` 를 만든다.

        여기가 **온보딩 완료 지점**이다. 이 파일들이 생기기 전까지 캠프 계정은
        데이터 화면을 볼 수 없다 — 관할을 모르면 무엇을 보여줄지 알 수 없으므로
        fail-closed 가 자연스럽다 (P-002 §6).
        """
        from votelink import camp as camp_mod
        from votelink.camp import scaffold

        s: WebSettings = request.app.state.settings
        account = request.state.account
        form = {
            "election_type": election_type,
            "office": office,
            "election_date": election_date,
            "lineage": lineage,
            "party": party,
            "incumbent": incumbent,
            "preset": preset,
            "sigungu": sigungu,
            "emd_codes": emd_codes,
            "legal_reviewer": legal_reviewer,
        }
        try:
            cycle = _build_cycle(s, form)
            info = camp_mod.load_camp(account.camp_id, s.camps_root)
            cycle_id = camp_mod.cycle_id_for(cycle) or f"미정-{cycle.election.type.value}"
            scaffold.write_cycle(
                account.camp_id,
                cycle_id,
                cycle,
                info.candidate_name,
                party.strip(),
                bool(incumbent),
                root=s.camps_root,
            )
        except (ValueError, scaffold.ScaffoldError, camp_mod.CampConfigError) as exc:
            return _render(
                request,
                "onboarding.html",
                _onboarding_ctx(request, error=str(exc), form=form),
                status_code=400,
            )

        control.audit.log(
            "onboarding",
            account_id=account.id,
            camp_id=account.camp_id,
            target=cycle_id,
            detail={"emd_count": len(cycle.territory.emd_codes)},
            ip=_client_ip(request),
            path=s.control_db,
        )
        return RedirectResponse("/", status_code=303)

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


def _ctx(request: Request, district_id: str | None = None, **extra) -> dict:
    """모든 화면이 공유하는 컨텍스트 — 현재 선거구, 전환 목록, 선거 계열 목록, 렌즈, 로그인 상태."""
    settings: WebSettings = request.app.state.settings
    return {
        "district_id": district_id,
        "districts": available_districts(settings),
        "election_types": election_type_choices(),
        "lens": getattr(request.state, "lens", None),
        "account": getattr(request.state, "account", None),
        "auth_on": settings.auth,
        **extra,
    }


def _auth_ctx(request: Request, **extra) -> dict:
    """로그인·가입·대기 화면의 컨텍스트.

    **참조 데이터를 읽지 않는다.** 로그인도 하지 않은 요청에 선거구 목록을 읽어줄
    이유가 없고, 참조 데이터가 깨져 있어도 로그인만은 돼야 운영자가 손을 쓸 수 있다.
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


def _onboarding_ctx(
    request: Request, *, error: str | None = None, form: dict | None = None
) -> dict:
    """온보딩 폼이 고를 값들. 선택지는 전부 코드가 아니라 참조 데이터·enum 에서 온다."""
    from votelink.camp.models import Office
    from votelink.reference.districts import load_districts

    settings: WebSettings = request.app.state.settings
    table = load_districts(settings.districts_path)
    return _auth_ctx(
        request,
        error=error,
        form=form or {},
        presets=sorted((d.id, d.name) for d in table.values()),
        sigungus=sorted({d.sigungu for d in table.values() if d.sigungu}),
        type_options=election_type_choices(),
        office_options=[(o.value, OFFICE_LABELS[o]) for o in Office],
        lineage_options=[(c.value, CAMP_LABELS[c]) for c in Camp],
    )


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


def _build_cycle(settings: WebSettings, form: dict):
    """온보딩 폼 → `Cycle`. 저장하기 **전에** 전부 검증한다.

    `load_cycle` 이 읽기 경로에서도 같은 검증을 하지만, 그때는 이미 파일이 디스크에
    있다. **관할이 틀리면 에러 없이 모든 분석이 조용히 틀리므로**(P-001 §16) 잘못된
    값이 파일이 되는 일 자체를 막는다.
    """
    from votelink.camp import known_emd_codes
    from votelink.camp.models import Cycle, Election, Office, Territory
    from votelink.camp.scaffold import resolve_territory

    raw_date = (form.get("election_date") or "").strip()
    try:
        election_date = dt.date.fromisoformat(raw_date) if raw_date else None
    except ValueError as exc:
        raise ValueError(f"선거일은 YYYY-MM-DD 형식이어야 한다: '{raw_date}'") from exc

    # 줄바꿈·쉼표·공백 아무거나 구분자로 받는다. 사람이 표에서 복사해 붙인다.
    codes = [c for c in re.split(r"[\s,]+", form.get("emd_codes") or "") if c]
    preset_label, resolved = resolve_territory(
        (form.get("preset") or "").strip() or None,
        (form.get("sigungu") or "").strip() or None,
        codes,
        settings.districts_path,
    )
    unknown = sorted(set(resolved) - known_emd_codes(settings.districts_path))
    if unknown:
        raise ValueError(
            f"districts.yaml 이 모르는 행정동코드다: {', '.join(unknown)}. "
            "`uv run votelink district list --emd` 로 대조하라"
        )

    return Cycle(
        election=Election(
            type=ElectionType(form["election_type"]),
            office=Office(form["office"]),
            date=election_date,
        ),
        lineage=Camp(form["lineage"]),
        territory=Territory(preset=preset_label, emd_codes=resolved),
        legal_reviewer=(form.get("legal_reviewer") or "").strip() or None,
    )


def _render(request: Request, template: str, context: dict, status_code: int = 200) -> Response:
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code
    )


def _client_ip(request: Request) -> str | None:
    """접속 IP. 프록시 뒤라면 uvicorn 을 `--proxy-headers` 로 띄워야 실주소가 잡힌다."""
    return request.client.host if request.client else None


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
        ctx = {
            **base,
            "districts": [],
            "lens": getattr(request.state, "lens", None),
            "account": getattr(request.state, "account", None),
            "auth_on": request.app.state.settings.auth,
        }
    return _render(request, "error.html", ctx, status_code=500)
