"""`meta.yaml` 의 `config` 를 선거구 하나로 해석한다.

수집기(L1)와 분석기(L2)가 같은 규칙을 쓴다. `config` 구조는 둘 중 하나다:

1. 평평한 형태 (다지역구 이전) — 그대로 돌려준다.
2. 계층 형태::

       config:
         default_district: seoul_songpa_gap
         common: { ... }              # 선거구 무관
         districts:
           seoul_songpa_gap: { ... }  # 선거구별 덮어쓰기

   `common` 위에 선택된 선거구 블록을 덮어쓰고 `district` 키를 채워 평평하게 만든다.

`--district` 없이 실행하면 `default_district` 를 쓴다. 둘 다 없으면 선거구 정보가
필요없는 수집기로 보고 `common` 만 돌려준다.
"""

from __future__ import annotations

from typing import Any


def resolve_config(
    owner_id: str, config: dict[str, Any], district_id: str | None = None
) -> dict[str, Any]:
    is_layered = "common" in config or "districts" in config
    if not is_layered:
        # 평평한 config. 다른 선거구를 요구했는데 이 수집기가 아직 옮겨지지 않았다면
        # 조용히 엉뚱한 선거구를 수집하지 않도록 막는다.
        wanted = district_id
        if wanted and config.get("district") not in (None, wanted):
            raise KeyError(
                f"{owner_id}: config 가 아직 단일 선거구('{config.get('district')}') 형태다. "
                f"'{wanted}' 를 쓰려면 meta.yaml 을 common/districts 구조로 옮겨야 한다"
            )
        return dict(config)

    resolved: dict[str, Any] = dict(config.get("common", {}))
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
