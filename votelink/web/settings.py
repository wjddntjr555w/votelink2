"""웹앱 설정. 전부 선택값이며, `None` 은 "해당 모듈의 기본 경로를 쓴다"는 뜻이다.

경로를 주입 가능하게 두는 이유는 테스트다. 전역을 monkeypatch 하는 대신
`create_app(WebSettings(data_root=tmp_path))` 로 임시 디렉터리를 넘긴다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from votelink import store
from votelink.store import DataSpace
from votelink.web import DEFAULT_HOST, DEFAULT_PORT


class WebSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    district_id: str | None = None
    """기본 선거구. 요청 URL `/d/<선거구>/` 이 이것을 덮어쓴다.

    `None` 이고 `districts.yaml` 에 선거구가 하나뿐이면 그것을 쓴다. 여럿이면
    `/` 가 선거구 선택 화면을 띄운다 — 조용히 첫 번째를 고르지 않는다.
    """

    data_root: Path | None = None
    """데이터 공간의 뿌리 (`records/`·`raw/`·`rejected/` 의 부모).
    `None` 이면 공용 공간 `data/shared/` (`store.SHARED_DIR`).

    `records/` 가 아니라 그 부모를 받는다 — `DataSpace` 가 세 하위 디렉터리를 함께
    들기 때문이다 (`docs/proposals/P-001` §10). 캠프 공간이 생기면 여기에
    `data/camps/<camp_id>/` 가 들어온다.
    """

    camp_id: str | None = None
    """어느 캠프의 눈으로 볼 것인가 (`P-001` §5 렌즈). `None` 이면 진영 중립으로 그린다.

    지금은 `serve --camp` 로 기동 시 한 번 정해진다. 세션이 캠프를 정하는 것은
    인증이 붙는 P-002 의 일이다 — 그때 이 필드는 요청별 값으로 옮겨간다.
    """

    cycle_id: str | None = None
    """선거 주기. `None` 이면 그 캠프의 가장 최근 주기."""

    camps_root: Path | None = None
    """`camps/` 의 부모(`data/`). `None` 이면 `store.DATA_DIR`. 주입은 테스트용이다."""

    districts_path: Path | None = None
    """`data/shared/reference/districts.yaml`."""

    policy_path: Path | None = None
    """`data/shared/reference/compliance.yaml`."""

    boundaries_path: Path | None = None
    """`data/shared/reference/emd_boundaries.geojson`. 없으면 격자로 그린다."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def space(self) -> DataSpace:
        """이 설정이 가리키는 데이터 공간. 로더가 레코드를 읽을 때 쓴다.

        `store.DATA_DIR` 을 import 로 당겨오지 않고 매번 모듈에서 읽는다 — `from ...
        import DATA_DIR` 은 이름을 복사하므로 테스트의 monkeypatch 가 먹지 않는다
        (루트 `conftest.py` 가 기록한 함정과 같은 것).
        """
        return DataSpace(self.data_root or store.SHARED_DIR)
