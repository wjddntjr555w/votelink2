"""실제 응답으로 parse 를 검증한다.

fixture 가 없으면 이 수집기는 **아직 검증되지 않은 상태**다. 합성 데이터로 대신하지 않는다.
출처의 실제 지저분함(빈 문자열, 콤마, 예상 못 한 필드명)이 반영되지 않기 때문이다.

    uv run votelink collect mois_population --capture-fixture
"""

import json
from pathlib import Path

import pytest

from collectors.mois_population.collector import Collector
from votelink.collect import RawBatch, Rejected
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import Record

FIXTURE = Path(__file__).parent / "fixtures" / "sample_raw.json"
META_PATH = Path(__file__).resolve().parents[1] / "meta.yaml"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason=(
        "실제 응답 fixture 가 없다 — mois_population 은 아직 미검증이다. "
        "`uv run votelink collect mois_population --capture-fixture` 로 받아라"
    ),
)


def _collector():
    """이 fixture(종로구 삼청동)는 필드 형식 검증용이다 — 송파구 대상이 아니므로
    district 필터를 끄고 쓴다. 필터링 자체는 test_district_filter.py 가 검증한다.
    """
    meta = CollectorMeta.load(META_PATH)
    meta = meta.model_copy(update={"config": {**meta.config, "district": None}})
    return Collector(meta=meta)


@pytest.fixture
def results():
    raw = RawBatch(collector_id=Collector.id, body=json.loads(FIXTURE.read_text("utf-8")))
    return list(_collector().parse(raw))


def test_no_items_are_rejected(results):
    rejected = [r for r in results if isinstance(r, Rejected)]
    assert not rejected, f"격리된 항목: {[r.short_reason for r in rejected][:5]}"


def test_records_satisfy_the_contract(results):
    records = [r for r in results if isinstance(r, Record)]
    assert records, "fixture 에서 레코드가 하나도 안 나왔다"
    for r in records:
        Record.model_validate(r.model_dump())
        assert r.geo_code and len(r.geo_code) == 10
        assert r.payload["total"] == sum(c["count"] for c in r.payload["breakdown"])


def test_one_record_per_emd(results):
    records = [r for r in results if isinstance(r, Record)]
    codes = [r.geo_code for r in records]
    assert len(codes) == len(set(codes)), "같은 행정동이 두 번 나왔다 — 재집계가 안 됐다"


def test_parse_is_deterministic(results):
    raw = RawBatch(collector_id=Collector.id, body=json.loads(FIXTURE.read_text("utf-8")))
    again = [r.record_id for r in _collector().parse(raw) if isinstance(r, Record)]
    assert [r.record_id for r in results if isinstance(r, Record)] == again


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("abc%2Fdef%3D%3D", "abc/def=="),  # Encoding 키
        ("abc/def==", "abc/def=="),  # Decoding 키는 그대로
        ("  spaced  ", "spaced"),
    ],
)
def test_service_key_is_normalized(given, expected):
    """Encoding 키를 그대로 넣으면 이중 인코딩되어 인증이 실패한다."""
    from collectors.mois_population.collector import normalize_service_key

    assert normalize_service_key(given) == expected
