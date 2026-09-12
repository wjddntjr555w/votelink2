"""이슈 보드 카드 (대시보드).

local_issue 레코드 1건 → 카드. L3 는 trend 를 다시 계산하지 않고 issue_ranker 가
준 값을 그대로 그린다. unclassified 비율이 크면 "어휘집 보강 신호" 문구가 붙는다.
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
from votelink.reference.compliance import Compliance, load_policy
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.loader import load_local_issue
from votelink.web.settings import WebSettings
from votelink.web.viewmodel import build_issue_board

SIGUNGU = "1171000000"

POLICY_UNREVIEWED = 'outputs:\n  - kind: local_issue\n    risk: low\n    note: "어휘집 분류 파생"\n'


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def rank(
    category, recency, *, label=None, count=3, share=30.0, trend="flat", headlines=None, places=None
):
    return {
        "category": category,
        "label": label or category,
        "article_count": count,
        "share": share,
        "recency_score": recency,
        "trend": trend,
        "top_places": [{"term": t, "count": n} for t, n in (places or [])],
        "sample_headlines": headlines or [],
    }


def issue_record(
    *,
    as_of="2026-09",
    geo_code=SIGUNGU,
    issues=None,
    total=None,
    unclassified=4,
    distorted=False,
) -> Record:
    if issues is None:
        issues = [
            rank(
                "transit",
                90.0,
                label="교통",
                trend="rising",
                count=8,
                share=50.0,
                headlines=["트램 개통 목표", "9호선 연장 착공"],
                places=[("잠실", 5)],
            ),
            rank("redevelopment", 40.0, label="재건축", trend="falling", count=6, share=37.5),
        ]
    if total is None:
        # 겹치는 분류가 없다고 보고 불변식을 등호로 만족시킨다.
        total = sum(i["article_count"] for i in issues) + unclassified
    return Record(
        kind="local_issue",
        collector_id="issue_ranker",
        source_name="votelink 분석 (naver_news + issue_lexicon)",
        source_url=None,
        source_license="api_tos",
        observed_at=datetime(2026, 9, 6, tzinfo=KST),
        observed_precision="day",
        ingested_at=datetime(2026, 9, 7, tzinfo=KST),
        geo_level="sigungu",
        geo_code=geo_code,
        geo_name="서울 송파구",
        confidence=0.5,
        derived_from=[],
        natural_key=f"local_issue|{geo_code}|{as_of}",
        payload={
            "as_of": as_of,
            "window_weeks": 12,
            "total_articles": total,
            "issues": issues,
            "unclassified_count": unclassified,
            "lexicon_version": "test-1",
            "backfill_distorted": distorted,
        },
    )


def settings_for(tmp_path, records, policy=POLICY_UNREVIEWED) -> WebSettings:
    store.append_records("issue_ranker", records, DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
    )


# --- 로더 -------------------------------------------------------------------


def test_load_local_issue_picks_newest_as_of(tmp_path):
    st = settings_for(tmp_path, [issue_record(as_of="2026-07"), issue_record(as_of="2026-09")])
    got = load_local_issue(st, "test_gap")
    assert got is not None
    assert got.payload.as_of == "2026-09"


def test_load_local_issue_ignores_other_sigungu(tmp_path):
    st = settings_for(tmp_path, [issue_record(geo_code="1168000000")])
    assert load_local_issue(st, "test_gap") is None


def test_load_local_issue_none_when_absent(tmp_path):
    st = settings_for(tmp_path, [])
    assert load_local_issue(st, "test_gap") is None


# --- 뷰모델 ---------------------------------------------------------------------


def test_build_issue_board_carries_payload_verbatim(tmp_path):
    st = settings_for(tmp_path, [issue_record()])
    card = build_issue_board(
        load_local_issue(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert card is not None
    assert card.lexicon_version == "test-1"
    assert [b.category for b in card.bars] == ["transit", "redevelopment"]
    top = card.bars[0]
    assert top.trend_label == "↑ 뜨는"
    assert top.width_pct == 100.0  # 최대 recency_score
    assert card.bars[1].width_pct == pytest.approx(44.4)
    assert top.headlines == ["트램 개통 목표", "9호선 연장 착공"]
    assert top.places == [("잠실", 5)]


def test_build_issue_board_caps_at_top_n(tmp_path):
    issues = [
        rank(f"c{i}", float(100 - i), trend="flat")
        for i in range(9)  # recency_score 내림차순
    ]
    st = settings_for(tmp_path, [issue_record(issues=issues, unclassified=13)])
    card = build_issue_board(
        load_local_issue(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert len(card.bars) == 6


def test_build_issue_board_unclassified_pct(tmp_path):
    # 기본 issues 분류분 14 + 미분류 6 = total 20
    st = settings_for(tmp_path, [issue_record(unclassified=6)])
    card = build_issue_board(
        load_local_issue(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert card.total_articles == 20
    assert card.unclassified_pct == pytest.approx(30.0)


def test_build_issue_board_none_passthrough(tmp_path):
    st = settings_for(tmp_path, [])
    assert build_issue_board(None, Compliance(policy=load_policy(st.policy_path))) is None


# --- 라우트 -------------------------------------------------------------------


def test_dashboard_renders_issue_board(tmp_path):
    """대시보드는 1단계부터 React SPA 다 — `/api/d/test_gap` 의 JSON을 본다."""
    # 기본 issues 분류분 14 + 미분류 14 = total 28 → 미분류 50%
    st = settings_for(tmp_path, [issue_record(distorted=True, unclassified=14)])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    issue_board = client.get("/api/d/test_gap").json()["issue_board"]
    assert issue_board is not None
    assert issue_board["unclassified_pct"] >= 50
    assert issue_board["backfill_distorted"] is True
    assert issue_board["verdict"]["status"] == "unreviewed"


def test_dashboard_without_issue_board_is_fine(tmp_path):
    st = settings_for(tmp_path, [])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    data = client.get("/api/d/test_gap").json()
    assert data["issue_board"] is None
