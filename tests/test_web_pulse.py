"""뉴스 펄스 카드 (대시보드).

news_pulse 레코드 1건 → 카드. L3 는 spike 판정을 다시 계산하지 않고 L2 가 준
값을 그대로 그린다. backfill_distorted 면 경고가 붙는다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.test_web_loader import write_districts
from votelink import store
from votelink.contract.models import KST, Record
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.reference.compliance import load_policy
from votelink.web.app import create_app
from votelink.web.loader import load_news_pulse
from votelink.web.settings import WebSettings
from votelink.web.viewmodel import build_pulse_card

SIGUNGU = "1171000000"

POLICY_UNREVIEWED = (
    "election_day: null\n"
    "outputs:\n"
    "  - kind: news_pulse\n"
    "    risk: low\n"
    "    status: unreviewed\n"
    '    note: "파생 집계"\n'
)


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def weekly(week_start: str, count: int, *, spike=False, z=None, dist=None):
    return {
        "week_start": week_start,
        "article_count": count,
        "district_specific_count": dist if dist is not None else count,
        "publisher_count": min(count, 3) if count else 0,
        "top_publisher_share": 50.0 if count else 0.0,
        "spike": spike,
        "spike_z": z,
    }


def pulse_record(
    *,
    as_of="2026-09",
    geo_code=SIGUNGU,
    weeks=None,
    distorted=False,
) -> Record:
    weeks = weeks or [weekly("2026-08-24", 4), weekly("2026-08-31", 9, spike=True, z=2.8)]
    total = sum(w["article_count"] for w in weeks)
    return Record(
        kind="news_pulse",
        collector_id="news_pulse",
        source_name="votelink 분석 (naver_news)",
        source_url=None,
        source_license="public_open",
        observed_at=datetime(2026, 9, 6, tzinfo=KST),
        observed_precision="day",
        ingested_at=datetime(2026, 9, 7, tzinfo=KST),
        geo_level="sigungu",
        geo_code=geo_code,
        geo_name="서울 송파구",
        confidence=0.6,
        derived_from=[],
        natural_key=f"news_pulse|{geo_code}|{as_of}",
        payload={
            "as_of": as_of,
            "window_weeks": 4,
            "weekly": weeks,
            "total_articles": total,
            "top_places": [{"term": "잠실", "count": 10}],
            "top_persons": [],
            "top_publishers": [{"term": "yna.co.kr", "count": 6}],
            "backfill_distorted": distorted,
        },
    )


def settings_for(tmp_path, records, policy=POLICY_UNREVIEWED) -> WebSettings:
    store.append_records("news_pulse", records, root=tmp_path / "records")
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        records_root=tmp_path / "records",
        policy_path=policy_path,
    )


# --- 로더 -------------------------------------------------------------------


def test_load_news_pulse_picks_newest_as_of(tmp_path):
    st = settings_for(
        tmp_path,
        [pulse_record(as_of="2026-07"), pulse_record(as_of="2026-09")],
    )
    got = load_news_pulse(st, "test_gap")
    assert got is not None
    assert got.payload.as_of == "2026-09"


def test_load_news_pulse_ignores_other_sigungu(tmp_path):
    st = settings_for(tmp_path, [pulse_record(geo_code="1168000000")])
    assert load_news_pulse(st, "test_gap") is None


def test_load_news_pulse_none_when_absent(tmp_path):
    st = settings_for(tmp_path, [])
    assert load_news_pulse(st, "test_gap") is None


# --- 뷰모델 ---------------------------------------------------------------------


def test_build_pulse_card_carries_l2_spike_verbatim(tmp_path):
    st = settings_for(tmp_path, [pulse_record()])
    card = build_pulse_card(load_news_pulse(st, "test_gap"), load_policy(st.policy_path))
    assert card is not None
    assert card.latest_count == 9
    assert card.latest_spike is True
    assert card.latest_z_text == "z +2.8"
    assert card.spike_weeks == 1
    assert [b.height_pct for b in card.bars] == [pytest.approx(44.4), 100.0]


def test_build_pulse_card_z_text_when_undecidable(tmp_path):
    weeks = [weekly("2026-08-24", 4), weekly("2026-08-31", 5)]
    st = settings_for(tmp_path, [pulse_record(weeks=weeks)])
    card = build_pulse_card(load_news_pulse(st, "test_gap"), load_policy(st.policy_path))
    assert card.latest_spike is False
    assert card.latest_z_text == "판정 불가"


def test_build_pulse_card_none_passthrough(tmp_path):
    st = settings_for(tmp_path, [])
    assert build_pulse_card(None, load_policy(st.policy_path)) is None


# --- 라우트 -------------------------------------------------------------------


def test_dashboard_renders_pulse_card(tmp_path):
    st = settings_for(tmp_path, [pulse_record(distorted=True)])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    html = client.get("/d/test_gap/").text
    assert "뉴스 펄스" in html
    assert "pulse__bars" in html
    assert "부풀어 있다" in html  # backfill 경고
    assert "선거법 검토를 받지 않은 산출물이다" in html  # unreviewed 배너


def test_dashboard_without_pulse_is_fine(tmp_path):
    st = settings_for(tmp_path, [])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    html = client.get("/d/test_gap/").text
    assert "뉴스 펄스" not in html
    assert html  # 페이지는 정상 렌더
