"""수집 런타임 테스트 공용 픽스처."""

from datetime import datetime

import pytest

from votelink.collect import geo
from votelink.collect.base import BaseCollector, RawBatch
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import KST, Record

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=KST)

# `data_root` 픽스처는 저장소 루트의 conftest.py 에 있다 — testpaths 셋(tests/ ·
# collectors/ · analyzers/)을 전부 덮어야 하기 때문이다. 여기서 다시 정의하면
# 안쪽 정의가 루트를 가려서 커버리지가 tests/ 로 좁아진다.


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
