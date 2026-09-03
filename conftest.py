"""모든 테스트에 걸리는 안전장치.

`testpaths` 가 `tests/` · `collectors/` · `analyzers/` 셋이다. 픽스처를 `tests/conftest.py`
에만 두면 나머지 둘은 실제 `data/` 에 쓸 수 있다 — 루트에 두면 세 곳이 전부 덮인다.

실제로 한 번 샜다. `data/records/fake_collector.jsonl` 과 `data/rejected/fake_collector/`
가 남아 있었고, 내용이 `tests/conftest.py` 의 `make_record` 산출물이었다. 그때는
`tests/` 안의 문제라 그 파일의 픽스처를 autouse 로 바꾸는 것으로 막았지만, 같은 일이
수집기·분석기 테스트에서 일어나지 않을 이유는 없었다.

지금은 `collectors/*/tests/` 와 `analyzers/*/tests/` 가 `store` 를 아예 쓰지 않는다.
이 픽스처는 그 사실이 바뀌는 날을 위한 것이다 — **개별 테스트가 기억해야 하는
안전장치는 언젠가 잊힌다.**
"""

import pytest

from votelink import store
from votelink.collect import storage


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    """`data/` 하위 쓰기 경로를 임시 디렉터리로 돌린다.

    raw 는 `storage` 가, records/rejected 는 `store` 가 진실이다 (L1·L2 공용이라
    `votelink/store.py` 로 옮겼다). `storage` 쪽 재수출 이름을 패치해도 함수는
    `store` 모듈의 전역을 보므로 효과가 없다 — 여기를 고쳐야 한다.

    **`data/reference/` 는 돌리지 않는다.** 읽기 전용 참조 데이터이고, 실제 파일이
    유효한지 보는 것도 테스트의 일이다 (`test_districts.py`, `test_compliance.py`).
    """
    monkeypatch.setattr(storage, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(store, "RECORDS_DIR", tmp_path / "records")
    monkeypatch.setattr(store, "REJECTED_DIR", tmp_path / "rejected")
    return tmp_path
