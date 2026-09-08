"""운영자 콘솔. 제안서: `docs/proposals/P-003-operator-console.md`.

**이번 범위는 화면 둘이다** — 캠프 관리와 감사 로그. P-003 §2 의 나머지 둘(수집·분석
실행, 참조데이터 편집)은 아직이다. §6 이 "화면 넷이 서로 다른 성격이라 구현은 나눠서
해도 된다"고 적어둔 그대로다.

**여기는 CLI 를 감싸기만 한다.** 승인·거절·정지·세션 종료·비밀번호 발급은 전부
`votelink/control/` 에 이미 있고 `votelink account …` 가 같은 함수를 부른다. 웹이 그
규칙을 다시 구현하면 두 개가 갈라진다 (P-003 §4 가 수집 실행에 대해 말한 것과 같은
이유이고, 상태 변경에도 그대로 적용된다).

**이 화면들에는 산출물이 없다.** 계정·신청·감사 로그는 레코드가 아니다. 운영자 화면에
캠프의 분석 숫자를 올리면 그 순간 `verdict` 계산이 필요해지고 절대 규칙 5 가 걸린다 —
운영에 필요한 것은 설정과 메타이지 분석 결과가 아니다.

접근 통제는 여기 없다. `auth.is_ops` 가 미들웨어에서 막는다 (`web/auth.py`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from votelink import control
from votelink.control import accounts as acc
from votelink.web.render import base_ctx, client_ip, render
from votelink.web.settings import WebSettings

router = APIRouter(prefix="/ops")

AUDIT_LIMIT = 200


def _ctx(request: Request, **extra) -> dict:
    """운영자 화면의 컨텍스트. 알림 메시지는 쿼리스트링으로 온다.

    플래시 메시지를 세션에 담지 않는다 — 그러려면 세션 저장소에 쓰기가 필요하고,
    한 줄 알림 때문에 그것을 들이지 않는다. 임의 문자열이 화면에 되비치지만 Jinja
    autoescape 가 켜져 있고, 이 화면은 운영자만 연다.
    """
    return base_ctx(
        request,
        ok=request.query_params.get("ok"),
        err=request.query_params.get("err"),
        **extra,
    )


def _back(to: str, *, ok: str | None = None, err: str | None = None) -> Response:
    """POST 뒤에는 항상 리다이렉트한다(PRG). 새로고침이 승인을 두 번 하지 않는다."""
    from urllib.parse import quote

    if ok:
        to = f"{to}?ok={quote(ok)}"
    elif err:
        to = f"{to}?err={quote(err)}"
    return RedirectResponse(to, status_code=303)


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


# --- 캠프 관리 -----------------------------------------------------------------------


@router.get("/", response_class=Response)
def console(request: Request) -> Response:
    """승인 큐 + 계정 목록. 운영자의 홈이다."""
    from votelink.camp import list_camps, list_cycles

    s = _settings(request)
    db = s.control_db
    existing = set(list_camps(s.camps_root))

    queue = []
    for req in control.signup.pending(path=db):
        applicant = acc.get(req.account_id, path=db)
        suggested = control.signup.suggest_camp_id(req.candidate_name, applicant.email)
        queue.append(
            {
                "req": req,
                "email": applicant.email,
                "suggested": suggested,
                # 제안값이 이미 쓰이고 있으면 저장이 실패한다. 누르기 전에 알려준다 —
                # camp_id 는 경로가 되므로 한 번 정하면 바꾸기 어렵다.
                "taken": suggested in existing,
            }
        )

    rows = []
    for a in acc.listing(path=db):
        rows.append(
            {
                "account": a,
                "sessions": control.sessions.active_count(a.id, path=db),
                "onboarded": bool(a.camp_id and list_cycles(a.camp_id, s.camps_root)),
            }
        )
    return render(request, "ops_camps.html", _ctx(request, queue=queue, rows=rows))


@router.post("/signups/{request_id}/approve", response_class=Response)
def approve(
    request: Request,
    request_id: int,
    camp_id: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
) -> Response:
    """승인 → **디스크에 캠프 공간이 생긴다.** 여기가 DB↔디스크 인계점이다."""
    s = _settings(request)
    operator = request.state.account
    try:
        made = control.signup.approve(
            request_id,
            operator.id,
            camp_id=camp_id.strip() or None,
            note=note.strip() or None,
            path=s.control_db,
            camps_root=s.camps_root,
        )
    except (control.SignupError, control.AccountError, ValueError) as exc:
        return _back("/ops/", err=str(exc))

    control.audit.log(
        "approve_signup",
        account_id=operator.id,
        camp_id=made,
        target=str(request_id),
        detail={"note": note.strip()} if note.strip() else None,
        ip=client_ip(request),
        path=s.control_db,
    )
    return _back("/ops/", ok=f"승인 완료 · 캠프 공간 생성: {made}")


@router.post("/signups/{request_id}/reject", response_class=Response)
def reject(
    request: Request,
    request_id: int,
    note: Annotated[str, Form()] = "",
) -> Response:
    """거절. **사유가 비면 거부한다** — 신청자가 무엇을 고쳐야 하는지 알아야 한다."""
    s = _settings(request)
    operator = request.state.account
    try:
        control.signup.reject(request_id, operator.id, note=note, path=s.control_db)
    except control.SignupError as exc:
        return _back("/ops/", err=str(exc))

    control.audit.log(
        "reject_signup",
        account_id=operator.id,
        target=str(request_id),
        detail={"note": note.strip()},
        ip=client_ip(request),
        path=s.control_db,
    )
    return _back("/ops/", ok="거절 처리했다. 사유를 신청자에게 전달하라")


@router.post("/accounts/{account_id}/status", response_class=Response)
def set_status(
    request: Request,
    account_id: int,
    status: Annotated[str, Form()],
) -> Response:
    """정지 / 정지 해제.

    **정지는 세션도 함께 끊는다.** 상태만 바꾸면 남은 세션의 수명만큼 더 열려 있고,
    그건 정지가 아니다. (미들웨어도 다음 요청에서 끊지만, 여기서 먼저 끊어 두면
    "정지했는데 아직 접속 중"으로 보이는 순간이 없다.)
    """
    s = _settings(request)
    operator = request.state.account
    if operator.id == account_id:
        return _back("/ops/", err="자기 계정은 정지할 수 없다. 운영자가 0명이 된다")
    try:
        target = acc.Status(status)
    except ValueError:
        return _back("/ops/", err=f"알 수 없는 상태다: {status}")

    acc.set_status(account_id, target, path=s.control_db)
    ended = (
        control.sessions.end_all(account_id, path=s.control_db)
        if target is acc.Status.SUSPENDED
        else 0
    )
    control.audit.log(
        "set_status",
        account_id=operator.id,
        target=str(account_id),
        detail={"status": target.value, "sessions_ended": ended},
        ip=client_ip(request),
        path=s.control_db,
    )
    return _back("/ops/", ok=f"계정 {account_id} → {target.value} (세션 {ended}개 종료)")


@router.post("/accounts/{account_id}/logout", response_class=Response)
def force_logout(request: Request, account_id: int) -> Response:
    """세션 강제 종료. **비밀번호가 샜을 때의 즉시 대응이다** — 2FA 를 두지 않기로 한
    결정의 보완책이고, 세션을 DB 에 둔 덕에 공짜로 따라왔다 (P-002 §8)."""
    s = _settings(request)
    operator = request.state.account
    n = control.sessions.end_all(account_id, path=s.control_db)
    control.audit.log(
        "force_logout",
        account_id=operator.id,
        target=str(account_id),
        detail={"sessions_ended": n},
        ip=client_ip(request),
        path=s.control_db,
    )
    return _back("/ops/", ok=f"계정 {account_id} 의 세션 {n}개를 끊었다")


@router.post("/accounts/{account_id}/passwd", response_class=Response)
def set_password(
    request: Request,
    account_id: int,
    password: Annotated[str, Form()],
) -> Response:
    """임시 비밀번호 발급.

    메일 발송 인프라가 없어 자가 재설정이 없다 (P-002 §14·§15). 그래서 이것이
    비밀번호를 잊은 캠프의 **유일한 통로**다. 기존 세션도 함께 끊는다 — 재발급의
    이유가 유출일 수 있고, 그때 남은 세션을 살려두면 재발급이 무의미하다.
    """
    s = _settings(request)
    operator = request.state.account
    try:
        acc.set_password(account_id, password, path=s.control_db)
    except acc.AccountError as exc:
        return _back("/ops/", err=str(exc))
    n = control.sessions.end_all(account_id, path=s.control_db)
    control.audit.log(
        "set_password",
        account_id=operator.id,
        target=str(account_id),
        detail={"sessions_ended": n},
        ip=client_ip(request),
        path=s.control_db,
    )
    return _back(
        "/ops/", ok=f"계정 {account_id} 비밀번호 재발급 (세션 {n}개 종료). 캠프에 전달하라"
    )


# --- 캠프 상세 -----------------------------------------------------------------------


@router.get("/camps/{camp_id}", response_class=Response)
def camp_detail(request: Request, camp_id: str) -> Response:
    """한 캠프의 설정. `votelink camp show` 의 웹 판이다.

    **설정과 메타만 보여준다.** 분석 산출물은 올리지 않는다 — 올리는 순간 verdict
    계산이 필요해지고, 운영에 필요한 것은 그게 아니다.
    """
    from pydantic import ValidationError

    from votelink import camp as camp_mod

    s = _settings(request)
    try:
        info = camp_mod.load_camp(camp_id, s.camps_root)
    except (camp_mod.CampNotFound, camp_mod.CampConfigError, ValidationError) as exc:
        return render(request, "ops_camp.html", _ctx(request, camp_id=camp_id, error=str(exc)), 404)

    cycles = []
    for cid in camp_mod.list_cycles(camp_id, s.camps_root):
        try:
            cycle = camp_mod.load_cycle(camp_id, cid, s.camps_root, districts_path=s.districts_path)
        except (camp_mod.CampConfigError, FileNotFoundError, ValidationError) as exc:
            cycles.append({"id": cid, "error": str(exc)})
            continue
        try:
            roster = camp_mod.load_roster(camp_id, cid, s.camps_root)
        except (FileNotFoundError, camp_mod.CampConfigError, ValidationError):
            roster = None
        cycles.append({"id": cid, "cycle": cycle, "roster": roster})

    return render(
        request,
        "ops_camp.html",
        _ctx(
            request,
            camp_id=camp_id,
            info=info,
            cycles=cycles,
            account=next((a for a in acc.listing(path=s.control_db) if a.camp_id == camp_id), None),
            entries=control.audit.recent(limit=30, camp_id=camp_id, path=s.control_db),
        ),
    )


# --- 감사 로그 -----------------------------------------------------------------------


@router.get("/audit", response_class=Response)
def audit_log(request: Request, camp: str = "", limit: int = AUDIT_LIMIT) -> Response:
    """접근 이력. **운영자만 본다** — 캠프에게 열지 않기로 했다 (P-003 §5).

    화면이 그 한계를 함께 말한다: 캠프당 계정이 1개라 로그는 "이 캠프의 누군가"까지만
    말한다. 읽는 사람이 그걸 모르면 로그를 과신한다.
    """
    from votelink.camp import list_camps

    s = _settings(request)
    entries = control.audit.recent(
        limit=max(1, min(limit, 1000)),
        camp_id=camp or None,
        path=s.control_db,
    )
    return render(
        request,
        "ops_audit.html",
        _ctx(request, entries=entries, camps=list_camps(s.camps_root), camp=camp, limit=limit),
    )
