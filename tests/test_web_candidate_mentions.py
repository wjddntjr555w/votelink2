"""후보 언급 비교 카드 (대시보드).

candidate_mention_share 레코드 1건 → 카드. L3 는 share_pct/wow_change_pct 를
다시 계산하지 않고 candidate_mention_share 분석기가 준 값을 그대로 그린다.
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
from votelink.web.loader import load_candidate_mention_share
from votelink.web.settings import WebSettings
from votelink.web.viewmodel import build_candidate_mention_card

SIGUNGU = "1171000000"

POLICY_UNREVIEWED = (
    'outputs:\n  - kind: candidate_mention_share\n    risk: low\n    note: "언급 집계 파생"\n'
)


@pytest.fixture(autouse=True)
def fresh_caches():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def week(start, count, *, share=None, wow=None):
    return {
        "week_start": start,
        "article_count": count,
        "share_pct": share,
        "wow_change_pct": wow,
    }


def candidate(name, party, lineage, *, is_ours=False, weekly=None, total=None):
    weekly = weekly or []
    return {
        "name": name,
        "party": party,
        "lineage": lineage,
        "is_ours": is_ours,
        "weekly": weekly,
        "total_articles": total if total is not None else sum(w["article_count"] for w in weekly),
    }


def cms_record(
    *,
    as_of="2026-09",
    geo_code=SIGUNGU,
    candidates=None,
    distorted=False,
) -> Record:
    if candidates is None:
        candidates = [
            candidate(
                "김철수",
                "국민의힘",
                "conservative",
                is_ours=True,
                weekly=[
                    week("2026-08-17", 1, share=100.0, wow=None),
                    week("2026-08-24", 2, share=50.0, wow=100.0),
                    week("2026-08-31", 3, share=75.0, wow=50.0),
                ],
            ),
            candidate(
                "이영희",
                "더불어민주당",
                "progressive",
                is_ours=False,
                weekly=[
                    week("2026-08-17", 0, share=0.0, wow=None),
                    week("2026-08-24", 2, share=50.0, wow=None),
                    week("2026-08-31", 1, share=25.0, wow=-50.0),
                ],
            ),
        ]
    total = sum(c["total_articles"] for c in candidates)
    return Record(
        kind="candidate_mention_share",
        collector_id="candidate_mention_share",
        source_name="votelink 분석 (naver_news 후보 언급 집계)",
        source_url=None,
        source_license="public_open",
        observed_at=datetime(2026, 9, 6, tzinfo=KST),
        observed_precision="day",
        ingested_at=datetime(2026, 9, 7, tzinfo=KST),
        geo_level="sigungu",
        geo_code=geo_code,
        geo_name="서울 송파구",
        confidence=0.7,
        derived_from=[],
        natural_key=f"candidate_mention_share|{geo_code}|{as_of}",
        payload={
            "as_of": as_of,
            "window_weeks": 3,
            "candidates": candidates,
            "total_articles": total,
            "backfill_distorted": distorted,
        },
    )


def settings_for(tmp_path, records, policy=POLICY_UNREVIEWED) -> WebSettings:
    store.append_records("candidate_mention_share", records, DataSpace(tmp_path))
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(policy, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
    )


# --- 로더 -------------------------------------------------------------------


def test_load_candidate_mention_share_picks_newest_as_of(tmp_path):
    st = settings_for(tmp_path, [cms_record(as_of="2026-07"), cms_record(as_of="2026-09")])
    got = load_candidate_mention_share(st, "test_gap")
    assert got is not None
    assert got.payload.as_of == "2026-09"


def test_load_candidate_mention_share_ignores_other_sigungu(tmp_path):
    st = settings_for(tmp_path, [cms_record(geo_code="1168000000")])
    assert load_candidate_mention_share(st, "test_gap") is None


def test_load_candidate_mention_share_none_when_absent(tmp_path):
    st = settings_for(tmp_path, [])
    assert load_candidate_mention_share(st, "test_gap") is None


# --- 뷰모델 ---------------------------------------------------------------------


def test_build_candidate_mention_card_carries_payload_verbatim(tmp_path):
    st = settings_for(tmp_path, [cms_record()])
    card = build_candidate_mention_card(
        load_candidate_mention_share(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert card is not None
    names = [c.name for c in card.candidates]
    assert names == ["김철수", "이영희"]

    ours = card.candidates[0]
    assert ours.is_ours is True
    assert ours.lineage_label == "보수"
    assert [b.count for b in ours.bars] == [1, 2, 3]
    # 카드 전체 최댓값(3) 대비 — 후보 간 막대가 서로 비교 가능해야 한다
    assert ours.bars[2].height_pct == 100.0
    assert ours.bars[0].height_pct == pytest.approx(33.3)

    opponent = card.candidates[1]
    assert opponent.is_ours is False
    assert opponent.lineage_label == "진보"


def test_build_candidate_mention_card_highlight(tmp_path):
    """급변 하이라이트는 카드 전체에서 |wow_change_pct| 최댓값 하나만 뽑는다."""
    st = settings_for(tmp_path, [cms_record()])
    card = build_candidate_mention_card(
        load_candidate_mention_share(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert card.highlight is not None
    # 김철수 wow +100.0 이 이영희 wow -50.0 보다 절댓값이 크다
    assert card.highlight.name == "김철수"
    assert card.highlight.direction == "up"
    assert card.highlight.week_start == "2026-08-24"


def test_build_candidate_mention_card_no_highlight_when_all_wow_none(tmp_path):
    candidates = [
        candidate(
            "김철수", "국민의힘", "conservative", is_ours=True, weekly=[week("2026-08-31", 1)]
        ),
    ]
    st = settings_for(tmp_path, [cms_record(candidates=candidates)])
    card = build_candidate_mention_card(
        load_candidate_mention_share(st, "test_gap"), Compliance(policy=load_policy(st.policy_path))
    )
    assert card.highlight is None


def test_build_candidate_mention_card_none_passthrough(tmp_path):
    st = settings_for(tmp_path, [])
    assert (
        build_candidate_mention_card(None, Compliance(policy=load_policy(st.policy_path))) is None
    )


# --- 라우트 -------------------------------------------------------------------


def test_dashboard_renders_candidate_mentions(tmp_path):
    """대시보드는 1단계부터 React SPA 다 — `/api/d/test_gap` 의 JSON을 본다."""
    st = settings_for(tmp_path, [cms_record(distorted=True)])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    body = client.get("/api/d/test_gap").json()["candidate_mentions"]
    assert body is not None
    assert body["backfill_distorted"] is True
    assert body["verdict"]["status"] == "unreviewed"
    assert len(body["candidates"]) == 2


def test_dashboard_without_candidate_mentions_is_fine(tmp_path):
    st = settings_for(tmp_path, [])
    client = TestClient(create_app(st), raise_server_exceptions=False)
    data = client.get("/api/d/test_gap").json()
    assert data["candidate_mentions"] is None
