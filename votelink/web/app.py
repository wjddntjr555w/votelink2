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

from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
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
from votelink.web.forms import CycleForm, RosterForm, build_cycle, parse_roster, roster_text
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
from votelink.web.render import base_ctx
from votelink.web.render import client_ip as _client_ip
from votelink.web.render import render as _render
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
        # 캠프 관할로 좁힌 목록이다. 관할이 선거구 하나면 `/` 가 그리로 바로 간다 —
        # 캠프가 로그인해서 254개 목록을 마주하지 않는다.
        districts = available_districts(settings, request.state.lens)
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
        return _render(request, "onboarding.html", _onboarding_ctx(request, first=True))

    @app.post("/onboarding", response_class=Response)
    def onboarding(request: Request, form: Annotated[CycleForm, Form()]) -> Response:
        """관할·진영·선거일을 받아 `cycles/<id>/` 를 만든다.

        여기가 **온보딩 완료 지점**이다. 이 파일들이 생기기 전까지 캠프 계정은
        데이터 화면을 볼 수 없다 — 관할을 모르면 무엇을 보여줄지 알 수 없으므로
        fail-closed 가 자연스럽다 (P-002 §6).
        """
        return _save_cycle(request, form, action="onboarding", first=True)

    @app.get("/cycles", response_class=Response)
    def cycles(request: Request) -> Response:
        """이 캠프의 선거 주기 목록. **캠프는 영속이고 선거가 그 안에서 바뀐다** (P-001 §7).

        지금 어느 주기를 보고 있는지 여기서 말한다 — 선택은 자동(선거일 기준)이라
        캠프가 고를 것은 없지만, 무엇을 보고 있는지는 알아야 한다.
        """
        from pydantic import ValidationError

        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        camp_id = request.state.account.camp_id
        current = request.state.lens.cycle_id if request.state.lens else None

        rows = []
        for cid in camp_mod.list_cycles(camp_id, s.camps_root):
            try:
                cycle = camp_mod.load_cycle(
                    camp_id, cid, s.camps_root, districts_path=s.districts_path
                )
            except (camp_mod.CampConfigError, FileNotFoundError, ValidationError) as exc:
                rows.append({"id": cid, "error": str(exc), "current": cid == current})
                continue
            try:
                roster = camp_mod.load_roster(camp_id, cid, s.camps_root)
            except (FileNotFoundError, ValidationError):
                # 로스터가 깨져도 주기 설정은 보여준다. 고치러 갈 링크가 필요하다.
                roster = None
            rows.append({"id": cid, "cycle": cycle, "roster": roster, "current": cid == current})

        return _render(request, "cycles.html", _auth_ctx(request, rows=rows, today=dt.date.today()))

    @app.get("/cycles/new", response_class=Response)
    def new_cycle_form(request: Request) -> Response:
        return _render(request, "onboarding.html", _onboarding_ctx(request, first=False))

    @app.post("/cycles/new", response_class=Response)
    def new_cycle(request: Request, form: Annotated[CycleForm, Form()]) -> Response:
        """다음 선거 주기를 추가한다. 관할도 진영도 바뀔 수 있으므로 전부 다시 받는다 —
        구청장에 나갔다가 다음엔 시의원에 나갈 수 있고 당적도 바뀐다 (P-001 §7)."""
        return _save_cycle(request, form, action="add_cycle", first=False)

    def _save_cycle(request: Request, form: CycleForm, *, action: str, first: bool) -> Response:
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
            return _render(
                request,
                "onboarding.html",
                _onboarding_ctx(request, error=str(exc), form=values, first=first),
                status_code=400,
            )

        control.audit.log(
            action,
            account_id=account.id,
            camp_id=account.camp_id,
            target=cycle_id,
            detail={"emd_count": len(cycle.territory.emd_codes)},
            ip=_client_ip(request),
            path=s.control_db,
        )
        # 주기를 더했으면 목록으로 — 새 주기가 현재가 됐는지 아닌지를 바로 보여준다.
        return RedirectResponse("/" if first else "/cycles", status_code=303)

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
        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        camp_id = request.state.account.camp_id
        if cycle_id not in camp_mod.list_cycles(camp_id, s.camps_root):
            raise camp_mod.CycleNotFound(f"선거 주기 '{cycle_id}' 가 이 캠프에 없다")
        return cycle_id

    @app.get("/cycles/{cycle_id}/edit", response_class=Response)
    def edit_cycle_form(request: Request, cycle_id: str) -> Response:
        from votelink import camp as camp_mod

        s: WebSettings = request.app.state.settings
        cid = _own_cycle(request, cycle_id)
        cycle = camp_mod.load_cycle(
            request.state.account.camp_id, cid, s.camps_root, districts_path=s.districts_path
        )
        return _render(request, "cycle_edit.html", _edit_ctx(request, cid, cycle))

    @app.post("/cycles/{cycle_id}/edit", response_class=Response)
    def preview_cycle(
        request: Request, cycle_id: str, form: Annotated[CycleForm, Form()]
    ) -> Response:
        """**저장하지 않는다.** 무엇이 바뀌는지 계산해 보여주고 확인을 받는다."""
        from votelink import camp as camp_mod
        from votelink.camp.changes import diff_cycle

        s: WebSettings = request.app.state.settings
        cid = _own_cycle(request, cycle_id)
        values = form.model_dump()
        before = camp_mod.load_cycle(
            request.state.account.camp_id, cid, s.camps_root, districts_path=s.districts_path
        )
        try:
            after = build_cycle(s, values)
        except ValueError as exc:
            return _render(
                request,
                "cycle_edit.html",
                _edit_ctx(request, cid, before, error=str(exc), form=values),
                status_code=400,
            )

        change = diff_cycle(before, after, cid, s.districts_path)
        if change.is_empty:
            return RedirectResponse("/cycles", status_code=303)
        return _render(
            request,
            "cycle_preview.html",
            _auth_ctx(request, cycle_id=cid, change=change, form=values),
        )

    @app.post("/cycles/{cycle_id}/apply", response_class=Response)
    def apply_cycle(
        request: Request, cycle_id: str, form: Annotated[CycleForm, Form()]
    ) -> Response:
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
            return _render(
                request,
                "cycle_edit.html",
                _edit_ctx(request, cid, before, error=str(exc), form=values),
                status_code=400,
            )

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
        return RedirectResponse("/cycles", status_code=303)

    @app.get("/cycles/{cycle_id}/roster", response_class=Response)
    def roster_form(request: Request, cycle_id: str) -> Response:
        return _render(request, "cycle_roster.html", _roster_ctx(request, cycle_id))

    @app.post("/cycles/{cycle_id}/roster", response_class=Response)
    def save_roster(
        request: Request, cycle_id: str, form: Annotated[RosterForm, Form()]
    ) -> Response:
        """후보 로스터를 저장한다.

        관할과 달리 **틀려도 분석을 바꾸지 않는다** — 로스터는 화면 표기에만 쓰이고
        진영별 집계는 `party_lineage.yaml` 이 한다. 그래서 확인 단계를 두지 않는다.
        """
        from votelink.camp import scaffold

        s: WebSettings = request.app.state.settings
        account = request.state.account
        cid = _own_cycle(request, cycle_id)
        try:
            roster = parse_roster(form)
            scaffold.write_roster(account.camp_id, cid, roster, s.camps_root)
        except (ValueError, scaffold.ScaffoldError) as exc:
            return _render(
                request,
                "cycle_roster.html",
                _roster_ctx(request, cid, error=str(exc), form=form.model_dump()),
                status_code=400,
            )

        control.audit.log(
            "edit_roster",
            account_id=account.id,
            camp_id=account.camp_id,
            target=cid,
            detail={"opponents": len(roster.opponents)},
            ip=_client_ip(request),
            path=s.control_db,
        )
        return RedirectResponse("/cycles", status_code=303)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    # 운영자 콘솔은 별도 모듈이다 (P-003 §6: "화면 넷이 서로 다른 성격이라 구현은
    # 나눠서 해도 된다"). 접근 통제는 라우터가 아니라 미들웨어에 있다 — 라우터에
    # 걸면 `include_router` 를 잊은 다음 사람이 통제까지 함께 잊는다.
    app.include_router(ops.router)

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


def _auth_ctx(request: Request, **extra) -> dict:
    """로그인·가입·대기 화면의 컨텍스트.

    **참조 데이터를 읽지 않는다.** 로그인도 하지 않은 요청에 선거구 목록을 읽어줄
    이유가 없고, 참조 데이터가 깨져 있어도 로그인만은 돼야 운영자가 손을 쓸 수 있다.
    운영자 화면(`ops.py`)이 같은 이유로 같은 것을 쓴다.
    """
    return base_ctx(request, **extra)


def _onboarding_ctx(
    request: Request,
    *,
    error: str | None = None,
    form: dict | None = None,
    first: bool = True,
) -> dict:
    """주기 폼이 고를 값들. 선택지는 전부 코드가 아니라 참조 데이터·enum 에서 온다.

    `first` 는 첫 설정(`/onboarding`)과 주기 추가(`/cycles/new`)를 가른다. 받는 값은
    같고 문구와 저장 뒤 행선지만 다르다.
    """
    from votelink.camp.models import Office
    from votelink.reference.districts import load_districts

    settings: WebSettings = request.app.state.settings
    table = load_districts(settings.districts_path)
    return _auth_ctx(
        request,
        error=error,
        form=form or {},
        first=first,
        presets=sorted((d.id, d.name) for d in table.values()),
        sigungus=sorted({d.sigungu for d in table.values() if d.sigungu}),
        type_options=election_type_choices(),
        office_options=[(o.value, OFFICE_LABELS[o]) for o in Office],
        lineage_options=[(c.value, CAMP_LABELS[c]) for c in Camp],
    )


def _edit_ctx(request: Request, cycle_id: str, cycle, *, error=None, form=None) -> dict:
    """수정 폼. 폼 값을 안 주면 **지금 저장된 값**으로 채운다.

    빈 폼을 주면 사람이 안 건드린 항목까지 다시 입력해야 하고, 그러다 관할을 새로
    치는 순간 P-001 §16 의 사고가 난다.
    """
    ctx = _onboarding_ctx(request, error=error, form=form, first=False)
    if form is None:
        ctx["form"] = {
            "election_type": cycle.election.type.value,
            "office": cycle.election.office.value,
            "election_date": cycle.election.date.isoformat() if cycle.election.date else "",
            "lineage": cycle.lineage.value,
            # `party` 는 로스터(candidates.yaml)에 있고 여기서는 안 고친다.
            # 주기 폼과 로스터 폼이 같은 값을 두 곳에서 쓰면 어긋난다.
            "party": "",
            "preset": cycle.territory.preset or "",
            "sigungu": "",
            "emd_codes": "\n".join(cycle.territory.emd_codes),
            "legal_reviewer": cycle.legal_reviewer or "",
        }
    ctx["cycle_id"] = cycle_id
    ctx["editing"] = True
    return ctx


def _roster_ctx(request: Request, cycle_id: str, *, error=None, form=None) -> dict:
    """로스터 폼. 폼 값을 안 주면 저장된 로스터를 풀어서 채운다."""
    from pydantic import ValidationError

    from votelink import camp as camp_mod
    from votelink.web.forms import CAMP_ALIASES

    settings: WebSettings = request.app.state.settings
    camp_id = request.state.account.camp_id
    if form is None:
        try:
            roster = camp_mod.load_roster(camp_id, cycle_id, settings.camps_root)
            form = {
                "ours_name": roster.ours.name,
                "ours_party": roster.ours.party,
                "ours_lineage": roster.ours.lineage.value,
                "ours_incumbent": "1" if roster.ours.incumbent else "",
                "opponents": roster_text(roster),
            }
        except (FileNotFoundError, ValidationError):
            # 로스터 파일이 깨졌거나 없다. 빈 폼으로 다시 만들 수 있게 둔다.
            form = {}
    return _auth_ctx(
        request,
        cycle_id=cycle_id,
        error=error,
        form=form,
        lineage_options=[(c.value, label) for label, c in CAMP_ALIASES.items()],
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
