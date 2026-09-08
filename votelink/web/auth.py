"""인증·접근 판정. 제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §8·§9.

**미들웨어로 강제한다.** 예외 핸들러나 데코레이터는 라우트가 검사를 *호출해야* 동작하고,
그건 새 라우트를 추가하며 빠뜨릴 수 있다는 뜻이다. P-001 §10 이 "빠뜨리면 `TypeError`"를
고른 것과 같은 이유로 여기서도 **못 빠뜨리는 쪽**을 고른다 — 경로가 아래 표에 없으면
자동으로 보호된다(fail-closed). `app.py:8` 이 `Depends()` 를 안 쓰기로 한 결정과 충돌하지
않는다. 라우트별 의존성 주입과 앱 전역 미들웨어는 별개 사안이다.

**관할 검사도 여기 있다.** `/d/<선거구>/` 는 URL 이 곧 열람 대상이라, 캠프 A 의 세션으로
캠프 B 의 지역구를 열 수 있으면 P-001 §10 의 격리가 웹에서 무너진다. 라우트마다 검사를
부르게 두지 않고 경로 모양(`/d/<id>/...`)으로 판정한다 — `/d/` 밑에 새 화면을 붙여도
검사는 이미 걸려 있다.

캠프 컨텍스트(렌즈·검토 기록·선거일)는 **요청마다** 세션에서 만든다. 모듈 전역이나
`app.state` 에 캐시하지 않는다 — 캠프 A 와 B 의 동시 요청이 같은 슬롯을 두고 경쟁한다.
파일 I/O 가 요청마다 붙지만 캠프 설정 파일은 작고, 그 비용이 격리를 사는 값이다.

이 모듈은 **동기**다. 미들웨어가 스레드풀로 넘겨 부른다 — sqlite 조회와 YAML 읽기를
이벤트 루프에서 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from votelink.control import accounts as acc
from votelink.control import sessions
from votelink.web.lens import Lens, load_lens

if TYPE_CHECKING:
    from votelink.web.settings import WebSettings

PUBLIC_PATHS = frozenset({"/login", "/signup", "/healthz"})
"""로그인 없이 열리는 경로. **여기에 산출물이 없다** — 그래서 `0.0.0.0` 바인딩이
"의도치 않은 공표"가 되지 않는다 (P-002 §2). 새 경로를 여기 넣기 전에 그 화면에
산출물이 있는지 먼저 본다."""

PENDING_PATHS = frozenset({"/pending", "/logout"})
"""승인 대기 계정이 볼 수 있는 전부. 공용 데이터도 안 보인다 (P-002 §6)."""

ONBOARDING_PATHS = frozenset({"/onboarding", "/logout"})
"""승인은 됐으나 관할을 아직 안 채운 캠프. 관할이 없으면 무엇을 보여줄지 알 수 없다."""

OPS_PREFIX = "/ops"
"""운영자 콘솔 (P-003). **접두어로 판정한다** — 화면을 더 붙여도 검사가 이미 걸려 있다.
`/d/` 관할 검사와 같은 방식이고 같은 이유다."""


@dataclass(frozen=True)
class Decision:
    """이 요청을 어떻게 처리할 것인가. 미들웨어가 받아 그대로 집행한다."""

    account: acc.Account | None = None
    redirect: str | None = None
    denied: str | None = None
    """관할 밖. 사유 문장을 담는다(403 화면과 감사 로그가 같은 문장을 쓴다).

    리다이렉트가 아니라 403 인 이유: 다시 로그인해도 달라지지 않는 일에 로그인
    화면을 보여주면 거짓말이 된다.
    """

    lens: Lens | None = None
    review: object | None = None
    election_day: str | None = None

    @property
    def camp_id(self) -> str | None:
        return self.account.camp_id if self.account else None


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/static/")


def is_ops(path: str) -> bool:
    return path == OPS_PREFIX or path.startswith(OPS_PREFIX + "/")


def district_in_path(path: str) -> str | None:
    """`/d/<선거구>/…` 의 선거구. 그 모양이 아니면 None.

    라우트 이름이 아니라 **경로 모양**으로 찾는다. `/d/` 밑에 새 화면이 생겨도
    관할 검사가 자동으로 따라붙는다.
    """
    parts = path.strip("/").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "d" and parts[1] else None


def resolve_account(token: str | None, *, db=None) -> acc.Account | None:
    """쿠키 → 세션 → 계정. 어느 단계든 끊기면 None."""
    session = sessions.resolve(token, path=db)
    if session is None:
        return None
    try:
        return acc.get(session.account_id, path=db)
    except acc.AccountError:
        # 세션은 살아 있는데 계정이 사라졌다. 세션도 끊는다.
        sessions.end(token, path=db)
        return None


def gate(account: acc.Account | None, path: str, *, onboarded: bool) -> str | None:
    """어디로 보낼 것인가. 통과면 `None`, 아니면 리다이렉트 대상 경로.

    순수 함수다 — 판정을 미들웨어의 부작용과 갈라 두어야 테스트가 표로 짜인다.
    """
    if is_public(path):
        return None
    if account is None:
        return "/login"
    if account.status is acc.Status.SUSPENDED:
        # 거절되거나 정지된 계정. `authorize` 가 세션을 이미 끊었으므로 여기까지
        # 오지 않는 것이 정상이고, 이 줄은 다른 호출자를 위한 이중 방어다.
        return "/login"
    if account.status is acc.Status.PENDING:
        return None if path in PENDING_PATHS else "/pending"
    if account.is_operator:
        # 운영자는 전 캠프를 본다. **단일 신뢰 지점이다** (P-003 §6).
        # 다만 캠프 계정용 화면 둘은 갈 곳이 아니다 — 운영자에겐 채울 캠프도,
        # 기다릴 신청도 없다. `/onboarding` 은 POST 하면 camp_id 가 None 이라 터진다.
        return "/ops/" if path in ("/onboarding", "/pending") else None
    if not account.camp_id:
        # 활성 캠프 계정인데 캠프가 없다. 승인이 중간에 끊긴 상태다 (P-002 §6).
        return "/pending" if path != "/pending" else None
    if not onboarded:
        return None if path in ONBOARDING_PATHS else "/onboarding"
    return None


def is_onboarded(account: acc.Account | None, settings: WebSettings) -> bool:
    """온보딩이 끝났는가 = 선거 주기가 하나라도 있는가.

    `camp.yaml` 은 승인 때 생기고 `cycles/<id>/election.yaml` 은 온보딩 때 생긴다.
    관할·진영·선거일이 전부 후자에 있으므로, 그것이 없으면 화면을 그릴 수 없다.
    """
    from votelink.camp import list_cycles

    if account is None or not account.camp_id:
        return False
    if account.is_operator:
        return True
    return bool(list_cycles(account.camp_id, settings.camps_root))


def camp_view(account: acc.Account, settings: WebSettings):
    """(렌즈, 검토 기록, 선거일). 온보딩이 끝난 캠프 계정에만 부른다.

    선거일을 공용 정책이 아니라 캠프의 `election.yaml` 에서 읽는다 — 진실의 출처를
    둘로 만들지 않는다. 캠프마다 나가는 선거가 다르므로 §108 공표 금지기간 판정도
    캠프마다 다르다 (P-001 §13).
    """
    from votelink.camp import cycle_dir, load_cycle
    from votelink.reference.compliance import REVIEW_FILENAME, load_review

    lens = load_lens(account.camp_id, None, settings.camps_root, settings.districts_path)
    cycle = load_cycle(
        account.camp_id, lens.cycle_id, settings.camps_root, districts_path=settings.districts_path
    )
    path = settings.review_path or (
        cycle_dir(account.camp_id, lens.cycle_id, settings.camps_root) / REVIEW_FILENAME
    )
    day = cycle.election.date
    return lens, load_review(path), (day.isoformat() if day else None)


def covers_district(lens: Lens | None, district_id: str, settings: WebSettings) -> bool:
    """이 선거구가 캠프 관할과 겹치는가.

    **겹치기만 하면 통과시킨다.** 캠프 관할과 국회의원 선거구는 서로 포함 관계가
    아니다 — 구청장 캠프의 관할은 선거구 셋에 걸쳐 있고, 기초의원 캠프는 한 선거구의
    일부만 갖는다 (P-001 §6). 교집합이 비었을 때만 남의 지역구다.

    모르는 선거구는 여기서 막지 않는다. 라우트가 `DistrictNotFound` 로 처리한다 —
    "없는 선거구"와 "남의 선거구"를 같은 화면으로 뭉개면 어느 쪽인지 알 수 없다.
    """
    from votelink.reference.districts import load_districts

    if lens is None or not lens.territory:
        return True
    district = load_districts(settings.districts_path).get(district_id)
    if district is None:
        return True
    return bool(lens.territory & set(district.emd_codes))


def authorize(token: str | None, path: str, settings: WebSettings) -> Decision:
    """쿠키와 경로 하나로 이 요청의 처리 방식을 정한다. **동기·차단 I/O.**"""
    account = resolve_account(token, db=settings.control_db)
    if account is not None and account.status is acc.Status.SUSPENDED:
        # **정지는 즉시 듣는다.** 운영자가 계정을 정지하면 그 순간부터 다음 요청이
        # 막혀야지, 남아 있는 세션의 수명만큼 더 열려 있으면 정지가 아니다.
        sessions.end(token, path=settings.control_db)
        account = None
    onboarded = is_onboarded(account, settings)
    redirect = gate(account, path, onboarded=onboarded)
    if redirect is not None:
        return Decision(account=account, redirect=redirect)

    if is_ops(path) and not (account and account.is_operator):
        # **운영자 화면에 캠프 계정이 들어오는 것을 여기서 막는다.** `gate` 가
        # 온보딩까지 마친 캠프를 통과시키고 나면 그 뒤에는 아무도 안 막는다.
        return Decision(account=account, denied="운영자 화면이다. 캠프 계정으로는 열 수 없다")

    if account is None or account.is_operator or not onboarded:
        # 공개 화면, 운영자, 온보딩 전. 캠프 렌즈가 없다 — 화면은 진영 중립으로 그린다.
        return Decision(account=account)

    lens, review, day = camp_view(account, settings)
    district_id = district_in_path(path)
    if district_id and not covers_district(lens, district_id, settings):
        return Decision(
            account=account,
            denied=f"선거구 '{district_id}' 는 이 캠프의 관할이 아니다",
            lens=lens,
        )
    return Decision(account=account, lens=lens, review=review, election_day=day)
