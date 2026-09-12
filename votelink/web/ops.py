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

접근 통제는 여기 없다. `auth.is_ops` 가 미들웨어에서 막는다 (`web/auth.py`) —
`/ops/...` 화면과 `/api/ops/...` 데이터 경로 둘 다 그 함수가 인식해야 한다.

**2026-09-12 — React SPA 로 옮겼다.** `router`(`/ops`)는 이제 SPA 셸만 돌려준다.
실제 데이터·조치는 `api_router`(`/api/ops`)가 JSON으로 낸다. 계산은 그대로다 —
승인·거절·정지 등은 여전히 `votelink/control/` 을 그대로 부르고, 주기 대리 수정은
여전히 `app.py` 의 `_cycle_form_options`/`_prefill_cycle_form`/`_change_to_json`
과 `build_cycle`/`diff_cycle`/`scaffold` 를 그대로 부른다(새 로직 0, P-005 §3).
옛 PRG(POST 뒤 리다이렉트로 `?ok=`/`?err=` 조회) 패턴은 없앴다 — 각 액션이
`{"ok": true, "message": "..."}` 또는 `{"error": "..."}` 를 직접 돌려주고, React
`OpsConsolePage` 가 그 자리에서 배너를 보여준다(로그인·가입·마이페이지와 같은 이유).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Request
from starlette.responses import JSONResponse, Response

from votelink import control
from votelink.control import accounts as acc
from votelink.web.forms import CycleForm
from votelink.web.render import bootstrap_password, client_ip
from votelink.web.settings import WebSettings

router = APIRouter(prefix="/ops")
api_router = APIRouter(prefix="/api/ops")

AUDIT_LIMIT = 200


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def _account_json(a: acc.Account) -> dict:
    return {
        "id": a.id,
        "email": a.email,
        "is_operator": a.is_operator,
        "camp_id": a.camp_id,
        "status": a.status.value,
        "created_at": a.created_at,
        "last_login_at": a.last_login_at,
    }


def _entry_json(e) -> dict:
    """`control/audit.py::Entry` — plain dataclass라 `model_dump` 가 없다."""
    return {
        "id": e.id,
        "at": e.at,
        "account_id": e.account_id,
        "camp_id": e.camp_id,
        "action": e.action,
        "target": e.target,
        "detail": e.detail,
        "ip": e.ip,
    }


# --- SPA 셸 ------------------------------------------------------------------------


@router.get("/", response_class=Response)
def console() -> Response:
    from votelink.web.app import _spa_shell

    return _spa_shell()


@router.get("/camps/{camp_id}", response_class=Response)
def camp_detail(camp_id: str) -> Response:
    from votelink.web.app import _spa_shell

    return _spa_shell()


@router.get("/camps/{camp_id}/cycles/{cycle_id}/edit", response_class=Response)
def ops_edit_cycle_form(camp_id: str, cycle_id: str) -> Response:
    from votelink.web.app import _spa_shell

    return _spa_shell()


@router.get("/audit", response_class=Response)
def audit_log() -> Response:
    from votelink.web.app import _spa_shell

    return _spa_shell()


# --- 캠프 관리 -----------------------------------------------------------------------


@api_router.get("/console")
def api_console(request: Request) -> dict:
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
                "id": req.id,
                "candidate_name": req.candidate_name,
                "email": applicant.email,
                "contact": req.contact,
                "wanted_election": req.wanted_election,
                "requested_at": req.requested_at,
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
                "account": _account_json(a),
                "sessions": control.sessions.active_count(a.id, path=db),
                "onboarded": bool(a.camp_id and list_cycles(a.camp_id, s.camps_root)),
            }
        )
    account = request.state.account
    return {
        "queue": queue,
        "rows": rows,
        "bootstrap": bootstrap_password(request),
        "auth_on": s.auth,
        "account": {"email": account.email, "is_operator": account.is_operator},
    }


@api_router.post("/signups/{request_id}/approve")
def api_approve(
    request: Request,
    request_id: int,
    camp_id: Annotated[str, Body(embed=True)] = "",
    note: Annotated[str, Body(embed=True)] = "",
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
        return JSONResponse({"error": str(exc)}, status_code=400)

    control.audit.log(
        "approve_signup",
        account_id=operator.id,
        camp_id=made,
        target=str(request_id),
        detail={"note": note.strip()} if note.strip() else None,
        ip=client_ip(request),
        path=s.control_db,
    )
    return JSONResponse({"ok": True, "message": f"승인 완료 · 캠프 공간 생성: {made}"})


@api_router.post("/signups/{request_id}/reject")
def api_reject(
    request: Request,
    request_id: int,
    note: Annotated[str, Body(embed=True)] = "",
) -> Response:
    """거절. **사유가 비면 거부한다** — 신청자가 무엇을 고쳐야 하는지 알아야 한다."""
    s = _settings(request)
    operator = request.state.account
    try:
        control.signup.reject(request_id, operator.id, note=note, path=s.control_db)
    except control.SignupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    control.audit.log(
        "reject_signup",
        account_id=operator.id,
        target=str(request_id),
        detail={"note": note.strip()},
        ip=client_ip(request),
        path=s.control_db,
    )
    return JSONResponse({"ok": True, "message": "거절 처리했다. 사유를 신청자에게 전달하라"})


@api_router.post("/accounts/{account_id}/status")
def api_set_status(
    request: Request,
    account_id: int,
    status: Annotated[str, Body(embed=True)],
) -> Response:
    """정지 / 정지 해제.

    **정지는 세션도 함께 끊는다.** 상태만 바꾸면 남은 세션의 수명만큼 더 열려 있고,
    그건 정지가 아니다. (미들웨어도 다음 요청에서 끊지만, 여기서 먼저 끊어 두면
    "정지했는데 아직 접속 중"으로 보이는 순간이 없다.)
    """
    s = _settings(request)
    operator = request.state.account
    if operator.id == account_id:
        return JSONResponse(
            {"error": "자기 계정은 정지할 수 없다. 운영자가 0명이 된다"}, status_code=400
        )
    try:
        target = acc.Status(status)
    except ValueError:
        return JSONResponse({"error": f"알 수 없는 상태다: {status}"}, status_code=400)

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
    return JSONResponse(
        {"ok": True, "message": f"계정 {account_id} → {target.value} (세션 {ended}개 종료)"}
    )


@api_router.post("/accounts/{account_id}/logout")
def api_force_logout(request: Request, account_id: int) -> Response:
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
    return JSONResponse({"ok": True, "message": f"계정 {account_id} 의 세션 {n}개를 끊었다"})


@api_router.post("/accounts/{account_id}/passwd")
def api_set_password(
    request: Request,
    account_id: int,
    password: Annotated[str, Body(embed=True)],
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
        return JSONResponse({"error": str(exc)}, status_code=400)
    n = control.sessions.end_all(account_id, path=s.control_db)
    control.audit.log(
        "set_password",
        account_id=operator.id,
        target=str(account_id),
        detail={"sessions_ended": n},
        ip=client_ip(request),
        path=s.control_db,
    )
    # 운영자의 비밀번호가 바뀌었을 수 있다. 배너 판정을 다시 센다 (`app.py` 참조).
    request.app.state.bootstrap_password = control.accounts.uses_bootstrap_password(
        path=s.control_db
    )
    return JSONResponse(
        {
            "ok": True,
            "message": f"계정 {account_id} 비밀번호 재발급 (세션 {n}개 종료). 캠프에 전달하라",
        }
    )


# --- 캠프 상세 -----------------------------------------------------------------------


@api_router.get("/camps/{camp_id}")
def api_camp_detail(request: Request, camp_id: str) -> Response:
    """한 캠프의 설정. `votelink camp show` 의 웹 판이다.

    **설정과 메타만 보여준다.** 분석 산출물은 올리지 않는다 — 올리는 순간 verdict
    계산이 필요해지고, 운영에 필요한 것은 그게 아니다.
    """
    from pydantic import ValidationError

    from votelink import camp as camp_mod

    s = _settings(request)
    operator = request.state.account
    viewer = {"auth_on": s.auth, "operator": {"email": operator.email, "is_operator": True}}
    try:
        info = camp_mod.load_camp(camp_id, s.camps_root)
    except (camp_mod.CampNotFound, camp_mod.CampConfigError, ValidationError) as exc:
        return JSONResponse(
            {
                "camp_id": camp_id,
                "error": str(exc),
                "info": None,
                "cycles": [],
                "account": None,
                "entries": [],
                **viewer,
            },
            status_code=404,
        )

    cycles = []
    for cid in camp_mod.list_cycles(camp_id, s.camps_root):
        try:
            cycle = camp_mod.load_cycle(camp_id, cid, s.camps_root, districts_path=s.districts_path)
        except (camp_mod.CampConfigError, FileNotFoundError, ValidationError) as exc:
            cycles.append({"id": cid, "error": str(exc), "cycle": None, "roster": None})
            continue
        try:
            roster = camp_mod.load_roster(camp_id, cid, s.camps_root)
        except (FileNotFoundError, camp_mod.CampConfigError, ValidationError):
            roster = None
        cycles.append(
            {
                "id": cid,
                "error": None,
                "cycle": cycle.model_dump(mode="json"),
                "roster": roster.model_dump(mode="json") if roster else None,
            }
        )

    account = next((a for a in acc.listing(path=s.control_db) if a.camp_id == camp_id), None)
    entries = control.audit.recent(limit=30, camp_id=camp_id, path=s.control_db)
    return JSONResponse(
        {
            "camp_id": camp_id,
            "error": None,
            "info": info.model_dump(mode="json"),
            "cycles": cycles,
            "account": _account_json(account) if account else None,
            "entries": [_entry_json(e) for e in entries],
            **viewer,
        }
    )


# --- 캠프 주기 대리 수정 (P-005) --------------------------------------------------
#
# 캠프가 스스로 못 고치는 상태(로그인 불가·정지·온보딩 미완)거나 이미 저장된 명백한
# 오류를 운영자가 캠프 대신 교정한다. **저장 경로는 캠프 쪽과 완전히 같다** —
# 폼 → 미리보기 → 확인, `build_cycle`·`diff_cycle`·`scaffold` 를 app.py 의 것을 그대로
# 부른다 (새 로직 0, P-005 §3). 다른 것은 둘뿐이다: camp_id 를 URL 에서 읽고 (§4),
# 저장할 때 사유를 요구한다 (§2 — 거절이 사유 없으면 거부되는 것과 같은 이유).


class _OpsCycleForm(CycleForm):
    """대리 수정 저장 폼. 캠프 폼에 사유 한 칸을 더한다 — 저장 시 필수다 (P-005 §2,
    거절이 사유 없으면 거부되는 것과 같은 이유). 미리보기는 사유가 필요 없으므로
    그쪽은 `CycleForm` 을 그대로 받는다."""

    note: str = ""


def _target_cycle(request: Request, camp_id: str, cycle_id: str):
    """대상 캠프·주기를 화이트리스트로 거르고 (settings, cid, before) 를 돌려준다.

    `{camp_id}`·`{cycle_id}` 둘 다 경로 파라미터라 파일 경로에 그대로 쓰지 않는다 —
    `list_camps`·`list_cycles` 화이트리스트로 먼저 거른다.
    """
    from votelink import camp as camp_mod
    from votelink.web.app import _cycle_in_camp

    s = _settings(request)
    if camp_id not in camp_mod.list_camps(s.camps_root):
        raise camp_mod.CampNotFound(f"캠프 '{camp_id}' 가 없다")
    cid = _cycle_in_camp(s, camp_id, cycle_id)
    before = camp_mod.load_cycle(camp_id, cid, s.camps_root, districts_path=s.districts_path)
    return s, cid, before


@api_router.get("/camps/{camp_id}/cycles/{cycle_id}/edit")
def api_ops_edit_cycle_form(request: Request, camp_id: str, cycle_id: str) -> dict:
    from votelink.web.app import _cycle_form_options, _prefill_cycle_form

    s, cid, before = _target_cycle(request, camp_id, cycle_id)
    options = _cycle_form_options(s)
    return {
        "cycle_id": cid,
        "camp_id": camp_id,
        "form": _prefill_cycle_form(before, options["emd_groups"]),
        **options,
    }


@api_router.post("/camps/{camp_id}/cycles/{cycle_id}/edit")
def api_ops_preview_cycle(
    request: Request, camp_id: str, cycle_id: str, form: CycleForm
) -> Response:
    """**저장하지 않는다.** 캠프 쪽 미리보기와 같은 계산을 돌려준다."""
    from votelink.camp.changes import diff_cycle
    from votelink.web.app import _change_to_json
    from votelink.web.forms import build_cycle

    s, cid, before = _target_cycle(request, camp_id, cycle_id)
    try:
        after = build_cycle(s, form.model_dump())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    change = diff_cycle(before, after, cid, s.districts_path)
    return JSONResponse({"change": _change_to_json(change)})


@api_router.post("/camps/{camp_id}/cycles/{cycle_id}/apply")
def api_ops_apply_cycle(
    request: Request, camp_id: str, cycle_id: str, form: _OpsCycleForm
) -> Response:
    """확인을 거친 대리 수정을 저장한다. **사유가 비면 저장하지 않는다.**

    감사 액션은 캠프 자신의 `edit_cycle` 과 **구분한다**(`edit_cycle_by_operator`) —
    같은 이름으로 뭉치면 "이 캠프의 누군가"가 고친 것처럼 보이고, P-003 §5 가 경고한
    과신이 거기서 생긴다.
    """
    from votelink import camp as camp_mod
    from votelink.camp import scaffold
    from votelink.camp.changes import diff_cycle
    from votelink.web.app import _change_to_json
    from votelink.web.forms import build_cycle

    operator = request.state.account
    s, cid, before = _target_cycle(request, camp_id, cycle_id)

    note = form.note.strip()
    values = form.model_dump(exclude={"note"})

    try:
        after = build_cycle(s, values)
        change = diff_cycle(before, after, cid, s.districts_path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not note:
        # 사유 없이 저장을 누른 경우. 무엇이 바뀌는지는 이미 계산됐으니 그 값과 함께
        # 알려준다 — 프런트가 확인 화면을 유지한 채 사유 칸만 다시 물을 수 있다.
        return JSONResponse(
            {"error": "대신 고치는 사유를 적어야 저장한다.", "change": _change_to_json(change)},
            status_code=400,
        )

    try:
        new_id = change.cycle_id_after
        target = scaffold.rename_cycle(camp_id, cid, new_id, s.camps_root)
        scaffold.write_election(camp_id, new_id, after, s.camps_root)
    except (scaffold.ScaffoldError, camp_mod.CampConfigError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    control.audit.log(
        "edit_cycle_by_operator",
        account_id=operator.id,
        camp_id=camp_id,
        target=change.cycle_id_after,
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
            "note": note,
        },
        ip=client_ip(request),
        path=s.control_db,
    )
    message = f"{camp_id} · {change.cycle_id_after} 수정을 저장했다"
    return JSONResponse({"ok": True, "message": message})


# --- 감사 로그 -----------------------------------------------------------------------


@api_router.get("/audit")
def api_audit_log(request: Request, camp: str = "", limit: int = AUDIT_LIMIT) -> dict:
    """접근 이력. **운영자만 본다** — 캠프에게 열지 않기로 했다 (P-003 §5).

    화면이 그 한계를 함께 말한다: 캠프당 계정이 1개라 로그는 "이 캠프의 누군가"까지만
    말한다. 읽는 사람이 그걸 모르면 로그를 과신한다.
    """
    from votelink.camp import list_camps

    s = _settings(request)
    operator = request.state.account
    entries = control.audit.recent(
        limit=max(1, min(limit, 1000)),
        camp_id=camp or None,
        path=s.control_db,
    )
    return {
        "entries": [_entry_json(e) for e in entries],
        "camps": list_camps(s.camps_root),
        "camp": camp,
        "limit": limit,
        "auth_on": s.auth,
        "operator": {"email": operator.email, "is_operator": True},
    }
