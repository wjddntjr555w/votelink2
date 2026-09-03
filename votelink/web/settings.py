"""웹앱 설정. 전부 선택값이며, `None` 은 "해당 모듈의 기본 경로를 쓴다"는 뜻이다.

경로를 주입 가능하게 두는 이유는 테스트다. 전역을 monkeypatch 하는 대신
`create_app(WebSettings(records_root=tmp_path))` 로 임시 디렉터리를 넘긴다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from votelink.web import DEFAULT_HOST, DEFAULT_PORT


class WebSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_id: str | None = None
    """기본 선거구. 요청 URL `/d/<선거구>/` 이 이것을 덮어쓴다.

    `None` 이고 `districts.yaml` 에 선거구가 하나뿐이면 그것을 쓴다. 여럿이면
    `/` 가 선거구 선택 화면을 띄운다 — 조용히 첫 번째를 고르지 않는다.
    """

    records_root: Path | None = None
    """`data/records/`. `None` 이면 `store.RECORDS_DIR`."""

    districts_path: Path | None = None
    """`data/reference/districts.yaml`."""

    policy_path: Path | None = None
    """`data/reference/compliance.yaml`."""

    boundaries_path: Path | None = None
    """`data/reference/emd_boundaries.geojson`. 없으면 격자로 그린다."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
