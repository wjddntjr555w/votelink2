"""`meta.yaml` 의 `config` 를 선거구 하나로 해석한다.

수집기(L1)와 분석기(L2)가 같은 규칙을 쓴다. `config` 는 세 개의 특수 키로 선거구
축을 연다:

    config:
      default_district: seoul_songpa_gap   # --district 없이 실행하면 이걸 쓴다
      districts:                           # 선거구별로 달라지는 값
        seoul_songpa_gap: { sigungu_admm_code: "1171000000" }
      common: { ... }                      # (선택) 선거구 무관 값을 명시적으로 묶고 싶을 때

해석 결과 = **나머지 최상위 키**(평평한 기본값) + `common` + 선택된 `districts.<id>`,
그리고 `district` 키가 자동으로 채워진다. 즉 `common` 을 안 써도 최상위에 평평하게
둔 값들이 그대로 기본값이 된다.

이 세 키가 하나도 없으면 **평평한 config** 로 보고 그대로 돌려준다 — 아직 다지역구로
옮기지 않은 수집기도 계속 동작한다. 이때 다른 선거구를 `--district` 로 요구하면
조용히 엉뚱한 데이터를 수집하지 않도록 실행을 막는다.
"""

from __future__ import annotations

from typing import Any

_AXIS_KEYS = ("default_district", "districts", "common")


def resolve_config(
    owner_id: str, config: dict[str, Any], district_id: str | None = None
) -> dict[str, Any]:
    is_layered = any(k in config for k in _AXIS_KEYS)
    if not is_layered:
        wanted = district_id
        if wanted and config.get("district") not in (None, wanted):
            raise KeyError(
                f"{owner_id}: config 가 아직 단일 선거구('{config.get('district')}') 형태다. "
                f"'{wanted}' 를 쓰려면 meta.yaml 에 default_district/districts 를 두어야 한다"
            )
        return dict(config)

    resolved: dict[str, Any] = {k: v for k, v in config.items() if k not in _AXIS_KEYS}
    resolved.update(config.get("common", {}) or {})

    blocks = config.get("districts", {}) or {}
    chosen = district_id or config.get("default_district")
    if chosen is not None:
        if chosen not in blocks:
            known = ", ".join(sorted(blocks)) or "(없음)"
            raise KeyError(
                f"{owner_id}: 선거구 '{chosen}' 설정이 meta.yaml 에 없다. 있는 것: {known}"
            )
        resolved.update(blocks[chosen])
        resolved.setdefault("district", chosen)
    return resolved
