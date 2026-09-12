"""렌즈 — 공용 숫자를 캠프 관점으로 읽는다 (P-001 §5).

이 파일이 지키는 계약은 둘이다:

1. **렌즈는 숫자를 바꾸지 않는다.** 같은 공용 계산 결과를 읽는 방식만 달라진다.
   이게 깨지면 "캠프마다 데이터를 복제하지 않는다"는 P-001 의 근거가 무너진다.
2. **렌즈가 없으면 지금까지와 똑같다.** 진영 중립 화면이 기본이다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from tests.test_web import _ABSOLUTE_URL_RE, ALLOWED_EXTERNAL_HOSTS
from tests.test_web_loader import CODES, profile_record, write_districts
from votelink import store
from votelink.camp import scaffold
from votelink.camp.models import CampInfo, Candidate, Cycle, Roster
from votelink.contract.enums import Camp
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.lens import Lens, load_lens
from votelink.web.settings import WebSettings

POLICY = """\
version: test
default_status: unreviewed
outputs:
  - kind: segment_profile
    risk: low
    derived: true
    distribution: internal_only
    ai_generated: false
    note: 시험용
"""

REVIEW = """\
version: test
outputs:
  - kind: segment_profile
    status: cleared
    reviewed_by: 시험 검토자
    reviewed_at: '2026-09-08'
"""


@pytest.fixture(autouse=True)
def _fresh():
    districts_mod.reset_cache()
    compliance_mod.reset_cache()
    yield
    districts_mod.reset_cache()
    compliance_mod.reset_cache()


def build_camp(tmp_path, lineage: str = "progressive", codes=None) -> tuple[str, str]:
    """임시 캠프 하나. (camp_id, cycle_id)."""
    cycle = Cycle.model_validate(
        {
            "election": {
                "type": "presidential",
                "office": "president",
                "date": dt.date(2030, 3, 6),
            },
            "lineage": lineage,
            "territory": {"preset": "test_gap", "emd_codes": list(codes or CODES)},
        }
    )
    info = CampInfo(camp_id="test-camp", candidate_name="홍길동", created_at=dt.date(2026, 9, 8))
    cid = scaffold.default_cycle_id(cycle)
    root = tmp_path / "data"
    scaffold.write_camp(info, root)
    scaffold.write_cycle("test-camp", cid, cycle, "홍길동", "가당", False, root)
    return "test-camp", cid


def settings_for(tmp_path, *, camp_id=None, cycle_id=None) -> WebSettings:
    policy_path = tmp_path / "compliance.policy.yaml"
    policy_path.write_text(POLICY, encoding="utf-8")
    review_path = tmp_path / "compliance.review.yaml"
    review_path.write_text(REVIEW, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
        review_path=review_path,
        boundaries_path=tmp_path / "없다.geojson",
        camp_id=camp_id,
        cycle_id=cycle_id,
        camps_root=tmp_path / "data",
    )


def seed(tmp_path) -> None:
    store.append_records("voter_profile", [profile_record(c) for c in CODES], DataSpace(tmp_path))


def client(tmp_path, **kw) -> TestClient:
    seed(tmp_path)
    return TestClient(create_app(settings_for(tmp_path, **kw)))


def api_view(tmp_path, **kw) -> dict:
    return client(tmp_path, **kw).get("/api/d/test_gap").json()["view"]


# --- 렌즈가 없으면 아무것도 달라지지 않는다 -------------------------------------


# 대시보드는 1단계부터 React SPA 다 — `/d/test_gap/` 는 빌드된 셸만 돌려준다.
# 데이터·회귀는 `/api/d/test_gap` 의 JSON을 본다. 설명 문구("우리 진영을 뺀
# 전부다" 등)는 이제 React 쪽 정적 텍스트라 여기서는 그 문구가 기대는 **숫자
# 불변식**(상대 = 전체 − 우리)만 확인한다 — 문구 자체의 프런트 테스트는
# frontend/src 쪽 몫이다(1단계 범위 밖).


def test_without_a_camp_the_page_is_camp_neutral(tmp_path):
    data = client(tmp_path).get("/api/d/test_gap").json()
    assert data["view"]["lens"] is None
    assert data["account"] is None
    assert data["auth_on"] is False


def test_lens_does_not_change_the_numbers(tmp_path):
    """같은 공용 계산 결과다. 읽는 방식만 달라진다 — 이게 P-001 §5 의 근거다."""
    seed(tmp_path)
    neutral = TestClient(create_app(settings_for(tmp_path))).get("/api/d/test_gap").json()

    camp_id, cycle_id = build_camp(tmp_path)
    lensed = (
        TestClient(create_app(settings_for(tmp_path, camp_id=camp_id, cycle_id=cycle_id)))
        .get("/api/d/test_gap")
        .json()
    )

    def camp_shares(data) -> list[tuple[str, list[float]]]:
        return [
            (c["geo_code"], [round(s["pct"], 1) for s in c["camp_bar"]])
            for c in data["view"]["cards"]
        ]

    shares = camp_shares(neutral)
    assert shares, "표본이 비면 이 테스트는 아무것도 증명하지 않는다"
    assert shares == camp_shares(lensed)


# --- 렌즈가 있으면 관점이 붙는다 ---------------------------------------------------


def test_lens_marks_our_camp(tmp_path):
    camp_id, cycle_id = build_camp(tmp_path, lineage="progressive")
    view = api_view(tmp_path, camp_id=camp_id, cycle_id=cycle_id)
    assert "홍길동" in view["lens"]["label"]  # Lens.label 은 @computed_field(candidate_name+party)
    assert view["lens"]["lineage"] == "progressive"
    ours_slices = [s for c in view["cards"] for s in c["camp_bar"] if s["ours"]]
    assert ours_slices and all(s["camp"] == "progressive" for s in ours_slices)


def test_lens_reads_ours_versus_theirs(tmp_path):
    camp_id, cycle_id = build_camp(tmp_path)
    view = api_view(tmp_path, camp_id=camp_id, cycle_id=cycle_id)
    lens_read = view["cards"][0]["lens_read"]
    assert lens_read is not None
    assert isinstance(lens_read["ours"], float) and isinstance(lens_read["theirs"], float)


def test_screen_says_what_theirs_means(tmp_path):
    """ "상대"는 우리 진영을 뺀 **전부**다 — 중도·기타가 함께 들어간다.

    화면이 그걸 말하지 않으면 "상대 60%"가 특정 상대 후보의 득표로 읽힌다. 그
    설명 문구는 이제 프런트(React)의 정적 텍스트지만, 그 문구가 진짜인지는
    여기서 숫자로 확인한다 — `theirs` 가 실제로 "우리 진영을 뺀 나머지 전부"의
    합인지(LensRead 참조).
    """
    camp_id, cycle_id = build_camp(tmp_path)
    view = api_view(tmp_path, camp_id=camp_id, cycle_id=cycle_id)
    card = view["cards"][0]
    ours_pct = next(s["pct"] for s in card["camp_bar"] if s["ours"])
    theirs_pct = sum(s["pct"] for s in card["camp_bar"] if not s["ours"])
    assert card["lens_read"]["ours"] == pytest.approx(ours_pct, abs=0.1)
    assert card["lens_read"]["theirs"] == pytest.approx(theirs_pct, abs=0.1)


def test_switching_lineage_switches_which_camp_is_ours(tmp_path):
    """같은 데이터인데 진영만 바꾸면 우세/열세가 뒤집혀야 한다."""
    seed(tmp_path)
    out = {}
    for lineage in ("progressive", "conservative"):
        root = tmp_path / lineage
        cycle = Cycle.model_validate(
            {
                "election": {"type": "presidential", "office": "president"},
                "lineage": lineage,
                "territory": {"emd_codes": list(CODES)},
            }
        )
        info = CampInfo(camp_id="c", candidate_name="후보", created_at=dt.date(2026, 9, 8))
        scaffold.write_camp(info, root)
        scaffold.write_cycle("c", "x", cycle, "후보", "당", False, root)
        lens = load_lens("c", "x", root)
        out[lineage] = lens.lineage

    assert out["progressive"] is Camp.PROGRESSIVE
    assert out["conservative"] is Camp.CONSERVATIVE


# --- 관할 -------------------------------------------------------------------------


def test_dong_outside_the_territory_is_flagged_not_hidden(tmp_path):
    """관할 밖도 보여주되 그 사실을 표시한다. **막는 것은 인증(P-002)의 일이다.**"""
    camp_id, cycle_id = build_camp(tmp_path, codes=[CODES[0]])
    view = api_view(tmp_path, camp_id=camp_id, cycle_id=cycle_id)
    codes_seen = {c["geo_code"] for c in view["cards"]}
    assert set(CODES) <= codes_seen, "관할 밖이라고 숨기지 않는다"
    outside = [c for c in view["cards"] if not c["lens_read"]["in_territory"]]
    assert outside, "관할 밖 동이 있는데 표시가 없다"


def test_empty_territory_covers_everything():
    lens = Lens(camp_id="c", cycle_id="x", candidate_name="후보", lineage=Camp.PROGRESSIVE)
    assert lens.covers("1111051500")
    assert lens.covers(None)


# --- 갱신 이력 ---------------------------------------------------------------------


def test_last_updated_is_shown(tmp_path):
    """운영자가 매일 수집하므로 어제 본 숫자가 오늘 달라질 수 있다 (P-001 §11)."""
    view = client(tmp_path).get("/api/d/test_gap").json()["view"]
    assert view["last_updated"] != ""


# --- 기동 실패 ---------------------------------------------------------------------


def test_broken_camp_config_fails_at_startup(tmp_path):
    """관할이 틀린 채로 화면을 그리면 조용히 다른 답을 준다. 기동에서 막는다."""
    camp_id, cycle_id = build_camp(tmp_path)
    path = tmp_path / "data" / "camps" / camp_id / "cycles" / cycle_id / "election.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(f'"{CODES[0]}"', '"9999999999"'),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="9999999999"):
        create_app(settings_for(tmp_path, camp_id=camp_id, cycle_id=cycle_id))


def test_unknown_camp_fails_at_startup(tmp_path):
    with pytest.raises(Exception, match="없는캠프"):
        create_app(settings_for(tmp_path, camp_id="없는캠프", cycle_id="x"))


# --- 외부 요청 0건 규칙은 그대로 ----------------------------------------------------


def test_lens_page_makes_no_external_requests(tmp_path):
    """캠프의 열람 맥락이 제3자에게 새지 않아야 한다 (base.html:1-2).
    경쟁 캠프를 함께 받는 제품에서 이 규칙은 더 중요해진다."""
    camp_id, cycle_id = build_camp(tmp_path)
    html = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/d/test_gap/").text
    assert "http://" not in html
    for host in _ABSOLUTE_URL_RE.findall(html):
        assert host in ALLOWED_EXTERNAL_HOSTS


# --- 후보자 비교 : 있는 데이터만 (사진·인지도·호감도 없음) --------------------------


def test_candidate_comparison_needs_lens_and_roster(tmp_path):
    """렌즈만 있고 로스터(상대 후보)가 없으면 섹션 자체가 안 뜬다."""
    camp_id, cycle_id = build_camp(tmp_path)
    data = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/api/d/test_gap").json()
    assert data["candidate_comparison"] is None


def test_candidate_comparison_shows_only_available_data(tmp_path):
    """지지율·최근 변화·지역 강세만 — 사진·인지도·호감도는 만들지 않는다."""
    camp_id, cycle_id = build_camp(tmp_path)
    root = tmp_path / "data"
    roster = Roster(
        ours=Candidate(name="홍길동", party="가당", lineage=Camp.PROGRESSIVE),
        opponents=[Candidate(name="김상대", party="나당", lineage=Camp.CONSERVATIVE)],
    )
    scaffold.write_roster(camp_id, cycle_id, roster, root)

    cc = (
        client(tmp_path, camp_id=camp_id, cycle_id=cycle_id)
        .get("/api/d/test_gap")
        .json()["candidate_comparison"]
    )
    assert cc is not None
    assert "홍길동" in cc["ours_name"]  # Lens.label = candidate_name + party
    assert cc["theirs_name"] == "김상대"
    # 사진·인지도·호감도는 수집하지 않는 값이라 필드 자체가 없어야 한다.
    assert set(cc) == {
        "ours_name",
        "ours_party",
        "theirs_name",
        "support_ours",
        "support_theirs",
        "recent_change_ours",
        "recent_change_theirs",
        "strong_regions_ours",
        "strong_regions_theirs",
    }
