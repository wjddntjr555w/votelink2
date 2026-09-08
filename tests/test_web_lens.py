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

from tests.test_web_loader import CODES, profile_record, write_districts
from votelink import store
from votelink.camp import scaffold
from votelink.camp.models import CampInfo, Cycle
from votelink.contract.enums import Camp
from votelink.reference import compliance as compliance_mod
from votelink.reference import districts as districts_mod
from votelink.store import DataSpace
from votelink.web.app import create_app
from votelink.web.lens import Lens, load_lens
from votelink.web.settings import WebSettings

POLICY = """\
version: test
election_day: null
default_status: unreviewed
outputs:
  - kind: segment_profile
    risk: low
    derived: true
    distribution: internal_only
    ai_generated: false
    status: cleared
    reviewed_by: 시험 검토자
    reviewed_at: '2026-09-08'
    note: 시험용
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
    policy_path = tmp_path / "compliance.yaml"
    policy_path.write_text(POLICY, encoding="utf-8")
    return WebSettings(
        districts_path=write_districts(tmp_path),
        data_root=tmp_path,
        policy_path=policy_path,
        boundaries_path=tmp_path / "없다.geojson",
        camp_id=camp_id,
        cycle_id=cycle_id,
        camps_root=tmp_path / "data",
    )


def seed(tmp_path) -> None:
    store.append_records(
        "voter_profile", [profile_record(c) for c in CODES], DataSpace(tmp_path)
    )


def client(tmp_path, **kw) -> TestClient:
    seed(tmp_path)
    return TestClient(create_app(settings_for(tmp_path, **kw)))


# --- 렌즈가 없으면 아무것도 달라지지 않는다 -------------------------------------


def test_without_a_camp_the_page_is_camp_neutral(tmp_path):
    html = client(tmp_path).get("/d/test_gap/").text
    assert "캠프의 관점" not in html
    assert 'class="lens' not in html
    assert "진영 중립 보기" in html


def test_lens_does_not_change_the_numbers(tmp_path):
    """같은 공용 계산 결과다. 읽는 방식만 달라진다 — 이게 P-001 §5 의 근거다."""
    seed(tmp_path)
    neutral = TestClient(create_app(settings_for(tmp_path))).get("/d/test_gap/").text

    camp_id, cycle_id = build_camp(tmp_path)
    lensed = (
        TestClient(create_app(settings_for(tmp_path, camp_id=camp_id, cycle_id=cycle_id)))
        .get("/d/test_gap/")
        .text
    )

    import re

    def pcts(html: str) -> list[str]:
        # 진영 구성 범례의 퍼센트만 뽑는다.
        return re.findall(r"(진보|중도|보수|기타) (\d+\.\d)%", html)

    assert pcts(neutral), "표본이 비면 이 테스트는 아무것도 증명하지 않는다"
    assert pcts(neutral) == pcts(lensed)


# --- 렌즈가 있으면 관점이 붙는다 ---------------------------------------------------


def test_lens_marks_our_camp(tmp_path):
    camp_id, cycle_id = build_camp(tmp_path, lineage="progressive")
    html = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/d/test_gap/").text
    assert "캠프의 관점" in html
    assert "홍길동" in html
    assert "tag--ours" in html
    assert 'class="lens' in html


def test_lens_reads_ours_versus_theirs(tmp_path):
    camp_id, cycle_id = build_camp(tmp_path)
    html = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/d/test_gap/").text
    assert "우리" in html and "상대" in html
    assert "%p" in html


def test_screen_says_what_theirs_means(tmp_path):
    """"상대"는 우리 진영을 뺀 **전부**다 — 중도·기타가 함께 들어간다.

    화면이 그걸 말하지 않으면 "상대 60%"가 특정 상대 후보의 득표로 읽힌다.
    이 시스템은 개별 후보 득표를 모르고 진영 단위 값만 안다 (LensRead 참조).
    """
    camp_id, cycle_id = build_camp(tmp_path)
    html = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/d/test_gap/").text
    assert "우리 진영을 뺀 전부" in html
    assert "중도·기타" in html


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
    html = client(tmp_path, camp_id=camp_id, cycle_id=cycle_id).get("/d/test_gap/").text
    assert "관할 밖" in html, "관할 밖 동이 있는데 표시가 없다"
    for code in CODES:
        assert code in html, "관할 밖이라고 숨기지 않는다"


def test_empty_territory_covers_everything():
    lens = Lens(
        camp_id="c", cycle_id="x", candidate_name="후보", lineage=Camp.PROGRESSIVE
    )
    assert lens.covers("1111051500")
    assert lens.covers(None)


# --- 갱신 이력 ---------------------------------------------------------------------


def test_last_updated_is_shown(tmp_path):
    """운영자가 매일 수집하므로 어제 본 숫자가 오늘 달라질 수 있다 (P-001 §11)."""
    html = client(tmp_path).get("/d/test_gap/").text
    assert "마지막 갱신" in html


# --- 기동 실패 ---------------------------------------------------------------------


def test_broken_camp_config_fails_at_startup(tmp_path):
    """관할이 틀린 채로 화면을 그리면 조용히 다른 답을 준다. 기동에서 막는다."""
    camp_id, cycle_id = build_camp(tmp_path)
    path = (tmp_path / "data" / "camps" / camp_id / "cycles" / cycle_id / "election.yaml")
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
    assert "https://" not in html
    assert "//" not in html.replace("</", "").replace("<!--", "")
