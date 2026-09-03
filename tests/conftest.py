"""수집 런타임 테스트 공용 픽스처."""

from datetime import datetime

import pytest

from votelink import store
from votelink.collect import geo, storage
from votelink.collect.base import BaseCollector, RawBatch
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=KST)


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    """data/ 하위 경로를 임시 디렉터리로 돌린다.

    raw 는 storage 가, records/rejected 는 store 가 진실이다 (L1·L2 공용이라
    votelink/store.py 로 옮겼다). storage 쪽 재수출 이름을 패치해도 함수는
    store 모듈의 전역을 보므로 효과가 없다 — 여기를 고쳐야 한다.

    **autouse 인 이유**: 이 픽스처를 안 받은 테스트가 하나라도 있으면 그 테스트는
    실제 `data/records/` 에 쓴다. 실제로 그렇게 샌 흔적이 남아 있었다
    (`data/records/fake_collector.jsonl`, `data/rejected/fake_collector/`).
    개별 테스트가 기억해야 하는 안전장치는 언젠가 잊힌다.

    `data/reference/` 는 돌리지 않는다 — 읽기 전용 참조 데이터이고, 실제 파일이
    유효한지 보는 것도 테스트의 일이다(`test_districts.py`, `test_compliance.py`).
    """
    monkeypatch.setattr(storage, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(store, "RECORDS_DIR", tmp_path / "records")
    monkeypatch.setattr(store, "REJECTED_DIR", tmp_path / "rejected")
    return tmp_path


@pytest.fixture
def geo_table(tmp_path, monkeypatch):
    """시험용 매핑표. 형식만 유효하며 실제 지역-코드 대응이 아니다."""
    csv_path = tmp_path / "geo_mapping.csv"
    csv_path.write_text(
        "source_system,source_code,source_name,emd_code,emd_name\n"
        "mois,3230040,서울특별시 시험구 가나동,1111054000,가나동\n"
        "mois,3230041,서울특별시 시험구 다라동,1111055000,다라동\n"
        "nec,SP-01,가나동,1111054000,가나동\n"
        "mois,3780031,성남시 수정구 신흥동,4113154000,신흥동\n"
        "mois,2820053,인천시 미추홀구 신흥동,2817753000,신흥동\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(geo, "REFERENCE_CSV", csv_path)
    geo.reset_table()
    yield csv_path
    geo.reset_table()


def make_meta(**over) -> CollectorMeta:
    base = dict(
        id="fake_collector",
        name="시험용 수집기",
        kinds=["news_article"],
        source_name="시험 출처",
        source_url="https://example.test",
        source_license="api_tos",
        access="api",
        geo_level="emd",
    )
    base.update(over)
    return CollectorMeta.model_validate(base)


def make_record(n: int = 0, **over) -> Record:
    base = dict(
        kind="news_article",
        collector_id="fake_collector",
        source_name="시험 출처",
        source_url=f"https://example.test/{n}",
        source_license="api_tos",
        observed_at=datetime(2026, 8, 30, 14, 20, tzinfo=KST),
        observed_precision="minute",
        ingested_at=NOW,
        geo_level="emd",
        geo_code="1111054000",
        geo_name="가나동",
        confidence=1.0,
        natural_key=f"https://example.test/{n}",
        payload={
            "title": f"기사 {n}",
            "publisher": "가상일보",
            "published_at": "2026-08-30T14:20:00+09:00",
            "url": f"https://example.test/{n}",
            "summary": "요약.",
        },
    )
    base.update(over)
    return Record(**base)


class FakeCollector(BaseCollector):
    """네트워크를 타지 않는 수집기. items 의 각 원소를 레코드 하나로 만든다.

    원소가 dict 가 아니면 parse 에서 터지게 해 격리 경로를 시험한다.
    """

    id = "fake_collector"

    def __init__(self, items, meta=None):
        super().__init__(meta=meta or make_meta())
        self.items = items
        self.fetch_calls = 0

    def fetch(self, since):
        self.fetch_calls += 1
        yield RawBatch(collector_id=self.id, body={"items": self.items}, batch_key="b1")

    def parse(self, raw):
        yield from self.map_items(raw.body["items"], self._to_record)

    @staticmethod
    def _to_record(item):
        if not isinstance(item, dict):
            raise ValueError(f"dict 가 아니다: {item!r}")
        return make_record(item["n"])
