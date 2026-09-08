"""모든 테스트에 걸리는 안전장치.

`testpaths` 가 `tests/` · `collectors/` · `analyzers/` 셋이다. 픽스처를 `tests/conftest.py`
에만 두면 나머지 둘은 실제 `data/` 에 쓸 수 있다 — 루트에 두면 세 곳이 전부 덮인다.

실제로 한 번 샜다. `data/records/fake_collector.jsonl` 과 `data/rejected/fake_collector/`
가 남아 있었고(P-001 1b 이전이라 `shared/` 가 없던 시절 경로다), 내용이
`tests/conftest.py` 의 `make_record` 산출물이었다. 그때는
`tests/` 안의 문제라 그 파일의 픽스처를 autouse 로 바꾸는 것으로 막았지만, 같은 일이
수집기·분석기 테스트에서 일어나지 않을 이유는 없었다.

지금은 `collectors/*/tests/` 와 `analyzers/*/tests/` 가 `store` 를 아예 쓰지 않는다.
이 픽스처는 그 사실이 바뀌는 날을 위한 것이다 — **개별 테스트가 기억해야 하는
안전장치는 언젠가 잊힌다.**

**2026-09-08 (P-001 롤아웃 1단계):** 예전에는 `store.RECORDS_DIR` 같은 모듈 전역을
monkeypatch 했다. 이제 경로가 `DataSpace` 값이라 그냥 임시 공간을 만들어 넘긴다 —
전역을 건드리지 않으므로 "어느 모듈의 전역을 패치해야 먹히는가" 같은 함정이 없다.
"""

from pathlib import Path

import pytest

from votelink import store
from votelink.control import db as control_db
from votelink.store import DataSpace


@pytest.fixture(autouse=True)
def _no_real_data_dir(tmp_path, monkeypatch):
    """`DataSpace.default()` 가 테스트 중에 실제 `data/` 를 가리키지 못하게 한다.

    경로가 값이 된 뒤에도 전역이 **하나** 남는다 — `store.SHARED_DIR`. `default()` 가
    그것을 읽고, CLI 코드를 복사해 온 테스트는 `space=DataSpace.default()` 라고 쓰기
    쉽다. 그 한 줄이 실제 `data/shared/records/` 에 쓰는 길이므로 여기서 막는다.

    **`data/shared/reference/` 는 돌리지 않는다.** 읽기 전용 참조 데이터이고, 실제
    파일이 유효한지 보는 것도 테스트의 일이다 (`test_districts.py`, `test_compliance.py`).
    """
    monkeypatch.setattr(store, "SHARED_DIR", tmp_path / "default")
    # control plane(계정·세션·감사)도 같은 이유로 막는다. 테스트가 실제 계정을
    # 만들면 그 계정으로 로그인이 되는 상태가 저장소에 남는다.
    monkeypatch.setattr(control_db, "CONTROL_DB", tmp_path / "control.db")


@pytest.fixture
def space(tmp_path) -> DataSpace:
    """임시 데이터 공간. 레코드를 읽고 쓰는 테스트는 이걸 넘긴다."""
    return DataSpace(tmp_path)


@pytest.fixture
def data_root(tmp_path) -> Path:
    """`space` 와 같은 뿌리. 경로를 직접 들여다보는 테스트가 쓴다."""
    return tmp_path
