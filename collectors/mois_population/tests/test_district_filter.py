"""시군구 단위로 조회한 응답을 지역구의 동 이름으로 걸러낸다.

lv=3 조회(2026-09-01 확인)는 시군구 산하 모든 행정동을 한 번에 준다 — 송파구만
조회해도 27개 동이 다 온다. 그중 우리 지역구 9개만 남겨야 한다.

여기서 쓰는 값은 실제 필드 '이름'(2026-09-01 확인)을 그대로 쓰되, 인구 수치는
합성이다. 필터링 로직만 검증하면 되기 때문이다.
"""

from pathlib import Path

import pytest

from collectors.mois_population.collector import Collector
from votelink.collect import RawBatch
from votelink.collect.meta import CollectorMeta
from votelink.contract.models import Record
from votelink.reference import districts as districts_mod

META_PATH = Path(__file__).resolve().parents[1] / "meta.yaml"

# 실제 응답 형태(동 단위로 이미 집계됨, tong/ban 빈 문자열)를 흉내낸 한 개 동 분량.
_ZERO_AGES = {
    f"{sex}{age}AgeNmprCnt": 0
    for sex in ("male", "feml")
    for age in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
}


def dong_row(name: str, admm_code: str, total_male20: int = 0):
    row = dict(_ZERO_AGES)
    row.update(
        {
            "tong": "",
            "ban": "",
            "ctpvNm": "서울특별시",
            "sggNm": "송파구",
            "dongNm": name,
            "admmCd": admm_code,
            "statsYm": "202412",
            "male20AgeNmprCnt": total_male20,
        }
    )
    row["totNmprCnt"] = total_male20
    return row


def envelope(*rows):
    return {
        "Response": {
            "head": {
                "resultCode": "0",
                "resultMsg": "NORMAL_SERVICE",
                "totalCount": str(len(rows)),
            },
            "items": {"item": list(rows)},
        }
    }


@pytest.fixture(autouse=True)
def fresh_district_cache():
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


def _collector():
    return Collector(meta=CollectorMeta.load(META_PATH))


_ALL_NINE = [
    ("풍납1동", "1171051000"),
    ("풍납2동", "1171052000"),
    ("방이1동", "1171058000"),
    ("방이2동", "1171059000"),
    ("오륜동", "1171060000"),
    ("송파1동", "1171061000"),
    ("송파2동", "1171062000"),
    ("잠실4동", "1171065000"),
    ("잠실6동", "1171067000"),
]


def test_dongs_outside_the_district_are_dropped():
    """송파구 27개 중 우리 9개만 남아야 한다. 나머지 18개가 섞여 있어도 걸러낸다."""
    body = envelope(
        *(dong_row(n, c) for n, c in _ALL_NINE),
        dong_row("가락본동", "1171057000", 999),  # 우리 지역구가 아니다
    )
    raw = RawBatch(collector_id=Collector.id, body=body)
    records = [r for r in _collector().parse(raw) if isinstance(r, Record)]
    assert {r.geo_name for r in records} == {n for n, _ in _ALL_NINE}
    assert "가락본동" not in {r.geo_name for r in records}


def test_missing_target_dong_fails_loudly():
    """9개 중 일부만 응답에 있으면 조용히 넘어가지 않는다."""
    body = envelope(dong_row("풍납1동", "1171051000"))  # 나머지 8개가 빠졌다
    raw = RawBatch(collector_id=Collector.id, body=body)
    with pytest.raises(ValueError, match="풍납2동"):
        list(_collector().parse(raw))


def test_all_nine_present_succeeds():
    names_codes = _ALL_NINE
    body = envelope(*(dong_row(n, c) for n, c in names_codes))
    raw = RawBatch(collector_id=Collector.id, body=body)
    records = [r for r in _collector().parse(raw) if isinstance(r, Record)]
    assert {r.geo_name for r in records} == {n for n, _ in names_codes}
    assert {r.geo_code for r in records} == {c for _, c in names_codes}


def test_explicit_admm_codes_disables_filtering():
    """admm_codes 를 직접 주면 이름 필터를 걸지 않는다 — 사용자가 범위를 통제한다."""
    meta = CollectorMeta.load(META_PATH)
    meta = meta.model_copy(update={"config": {**meta.config, "admm_codes": ["1171099999"]}})
    body = envelope(dong_row("아무동", "1171099999", 5))
    raw = RawBatch(collector_id=Collector.id, body=body)
    records = [r for r in Collector(meta=meta).parse(raw) if isinstance(r, Record)]
    assert [r.geo_name for r in records] == ["아무동"]


def test_query_codes_prefers_explicit_over_sigungu():
    meta = CollectorMeta.load(META_PATH)
    meta = meta.model_copy(update={"config": {**meta.config, "admm_codes": ["9999999999"]}})
    assert Collector(meta=meta).query_codes() == ["9999999999"]


def test_query_codes_falls_back_to_sigungu_code():
    assert _collector().query_codes() == ["1171000000"]
