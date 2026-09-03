"""웹앱(L3) — 저장된 레코드를 읽어서 화면으로 만든다. 규약은 `docs/40-webapp-spec.md`.

**L3는 쓰지 않는다.** 이 패키지는 `store.append_records` / `upsert_records` /
`append_rejected` 를 import 하지 않는다. 웹앱이 데이터를 만들기 시작하면 `derived_from`
추적이 끊기고, 화면의 숫자가 어디서 왔는지 말할 수 없게 된다.

**이 모듈은 fastapi 를 import 하지 않는다.** 앱 팩토리는 `votelink.web.app` 에 있고,
CLI가 `cmd_serve` 안에서 늦게 불러온다 — 웹 의존성이 없는 환경에서도 `collect`·`analyze`
가 죽지 않아야 하기 때문이다. 여기에는 의존성 없는 상수만 둔다.
"""

DEFAULT_HOST = "127.0.0.1"
"""기본 호스트. **`0.0.0.0` 이 아니다.**

편의가 아니라 컴플라이언스에 인접한 결정이다 — 미검토 산출물이 경고와 함께 뜨는 화면을
LAN에 열어두면 그게 의도치 않은 공표가 된다 (`docs/90-compliance.md §6`).
"""

DEFAULT_PORT = 8420

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT"]
