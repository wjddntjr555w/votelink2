"""수집 런타임 테스트 공용 픽스처."""

from datetime import datetime

import pytest

from votelink.collect import geo, storage
from votelink.collect.base import BaseCollector, RawBatch
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=KST)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """data/ 하위 경로를 임시 디렉터리로 돌린다."""
    monkeypatch.setattr(storage, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(storage, "RECORDS_DIR", tmp_path / "records")
    monkeypatch.setattr(storage, "REJECTED_DIR", tmp_path / "rejected")
    return tmp_path


@pytest.fixture
def geo_table(tmp_path, monkeypatch):
    """송파구 일부를 가정한 시험용 매핑표. 실제 코드값이 아니다."""
    csv_path = tmp_path / "geo_mapping.csv"
    csv_path.write_text(
        "source_system,source_code,source_name,emd_code,emd_name\n"
        "mois,11710530,서울특별시 송파구 풍납1동,11710530,풍납1동\n"
        "mois,11710540,서울특별시 송파구 풍납2동,11710540,풍납2동\n"
        "nec,SP-01,풍납1동,11710530,풍납1동\n"
        "mois,11220110,성남시 수정구 신흥동,11220110,신흥동\n"
        "mois,11330110,인천시 어딘가 신흥동,11330110,신흥동\n",
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
        geo_code="11710530",
        geo_name="풍납1동",
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
