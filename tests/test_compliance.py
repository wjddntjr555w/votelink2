"""산출물 검증 — 절대 규칙 5의 집행 근거.

여기서 지키는 것은 하나다: **모르면 통과시키지 않는다.**
정책표에 없거나, 검토 기록에 없거나, 서명이 없거나, 선거일을 몰라 기간을 계산할 수
없으면 전부 `unreviewed` 로 떨어져야 한다. 그래야 새 산출물이 조용히 무경고로
표시되지 않는다.

**2026-09-08 (P-001 §13): 정책과 검토 기록이 갈라졌다.**
- 무엇이 위험한가(위험도·배포범위·기간제한)는 공용 `compliance.policy.yaml`
- 검토했는가(서명)는 캠프별 `cycles/<주기>/compliance.review.yaml`
그래서 이 파일의 헬퍼도 둘을 갈라 받는다.

판정 엔진은 kind를 가리지 않으므로 여기서는 conftest 의 `news_article` 레코드를 쓴다.
실제 배포 정책표가 유효한지는 맨 아래 절이 따로 본다.
"""

import pytest
from pydantic import ValidationError

from tests.conftest import make_record
from votelink.reference import compliance as mod
from votelink.reference.compliance import (
    Compliance,
    OutputPolicy,
    OutputReview,
    Policy,
    Review,
    ReviewStatus,
    review,
    review_with,
)


@pytest.fixture(autouse=True)
def fresh_cache():
    mod.reset_cache()
    yield
    mod.reset_cache()


def write(tmp_path, body: str):
    path = tmp_path / "compliance.policy.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def compliance_with(*, election_day=None, review_fields=None, **policy_fields) -> Compliance:
    """news_article 항목 하나짜리 (정책 + 검토 기록).

    정책 필드는 키워드로, 검토 필드(status·reviewed_by·reviewed_at·note)는
    `review_fields=` 로 받는다 — 두 파일이 갈라진 것을 헬퍼도 드러낸다.
    `review_fields=None` 이면 **검토 기록이 아예 없는 상태**다(캠프가 아직 안 봤다).
    """
    policy_fields.setdefault("risk", "low")
    policy = Policy(outputs=[OutputPolicy(kind="news_article", **policy_fields)])
    rev = Review(
        outputs=[OutputReview(kind="news_article", **review_fields)] if review_fields else []
    )
    return Compliance(policy=policy, review=rev, election_day=election_day)


def verdict_for(record=None, **kw):
    return review_with(compliance_with(**kw), record or make_record())


# --- fail-closed: 모르면 통과시키지 않는다 ----------------------------------------


def test_kind_not_in_policy_is_unreviewed():
    """정책표에 없는 kind 는 unreviewed 다.

    이게 이 모듈의 존재 이유다. 새 분석기가 새 산출물을 내면 아무도 코드를 고치지
    않아도 자동으로 경고가 붙어야 한다. 블랙리스트였다면 조용히 통과했을 것이다.
    """
    verdict = review_with(Compliance(policy=Policy()), make_record())
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert verdict.reasons  # 왜 unreviewed 인지 말해야 한다
    assert "news_article" in verdict.reasons[0]


def test_kind_in_policy_but_not_reviewed_is_unreviewed():
    """정책표에는 있는데 **이 캠프가 아직 검토하지 않은** 경우.

    분리 이후 새로 생긴 상태다. 사유가 "정책표에 없다"와 달라야 한다 —
    사용자가 할 일이 다르기 때문이다(정책 추가 vs 법률 검토).
    """
    verdict = verdict_for()
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert "검토 기록" in verdict.reasons[0]
    assert "compliance.review.yaml" in verdict.reasons[0]


def test_cleared_without_signature_is_unreviewed():
    """서명 없는 서명란은 서명이 아니다.

    cleared 는 시스템의 판단이 아니라 사람의 서명을 옮겨 적은 것이다. reviewed_by 가
    비어 있으면 아무도 검토하지 않았다는 뜻이므로 통과시키지 않는다.
    """
    verdict = verdict_for(review_fields={"status": "cleared", "reviewed_by": ""})
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert "reviewed_by" in verdict.reasons[0]


def test_whitespace_signature_does_not_count():
    """공백만 넣어서 통과시킬 수 없다."""
    verdict = verdict_for(review_fields={"status": "cleared", "reviewed_by": "   "})
    assert verdict.status is ReviewStatus.UNREVIEWED


def test_blackout_without_election_day_is_unreviewed():
    """선거일을 모르면 기간을 계산할 수 없다. 계산할 수 없으면 통과시키지 않는다.

    선거일은 이제 캠프의 `election.yaml` 에서 온다 — 캠프마다 나가는 선거가 다르므로
    공표 금지기간 판정도 캠프마다 다르다.
    """
    verdict = verdict_for(
        blackout="poll_publication",
        review_fields={"status": "cleared", "reviewed_by": "법률검토자"},
    )
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert "선거일" in verdict.reasons[0]


def test_blackout_with_election_day_passes():
    verdict = verdict_for(
        blackout="poll_publication",
        election_day="2028-04-12",
        review_fields={"status": "cleared", "reviewed_by": "법률검토자"},
    )
    assert verdict.status is ReviewStatus.CLEARED


def test_default_status_cleared_is_rejected_at_load(tmp_path):
    """`default_status: cleared` 는 규칙 5를 끄는 것이라 로딩 자체가 실패한다.

    파일 한 줄로 검증 전체를 무력화할 수 있으면 안 된다.
    """
    path = write(tmp_path, "default_status: cleared\noutputs: []\n")
    with pytest.raises(ValidationError, match="cleared"):
        mod.load_policy(path)


def test_per_kind_default_status_cleared_is_also_rejected(tmp_path):
    """항목별 기본값으로도 통과시킬 수 없다. cleared 는 서명으로만 들어간다."""
    path = write(
        tmp_path,
        "outputs:\n  - kind: news_article\n    risk: low\n    default_status: cleared\n",
    )
    with pytest.raises(ValidationError, match="cleared"):
        mod.load_policy(path)


def test_missing_policy_file_is_an_error(tmp_path):
    """정책 파일이 없으면 조용히 통과시키지 않고 터진다."""
    with pytest.raises(FileNotFoundError):
        mod.load_policy(tmp_path / "없다.yaml")


def test_missing_review_file_is_empty_not_an_error(tmp_path):
    """검토 기록이 **없는 것은 정상이다** — 아직 아무것도 검토하지 않았다는 뜻이고,
    그 상태에서 전부 unreviewed 로 떨어지는 것이 fail-closed 다.

    정책 파일과 다르다. 정책이 없으면 무엇이 위험한지조차 모르므로 터져야 한다.
    """
    assert mod.load_review(tmp_path / "없다.yaml").outputs == []


def test_duplicate_kind_is_rejected(tmp_path):
    """같은 kind 가 둘이면 어느 쪽이 적용되는지 알 수 없다."""
    path = write(
        tmp_path,
        "outputs:\n  - kind: news_article\n    risk: low\n  - kind: news_article\n    risk: high\n",
    )
    with pytest.raises(ValidationError, match="두 번"):
        mod.load_policy(path)


def test_duplicate_kind_in_review_is_rejected():
    with pytest.raises(ValidationError, match="두 번"):
        Review(
            outputs=[
                OutputReview(kind="news_article"),
                OutputReview(kind="news_article", status="cleared"),
            ]
        )


# --- 통과와 차단 -----------------------------------------------------------------


def test_signed_cleared_passes_and_carries_the_signature():
    verdict = verdict_for(
        review_fields={
            "status": "cleared",
            "reviewed_by": "법률검토자",
            "reviewed_at": "2026-09-10",
        }
    )
    assert verdict.status is ReviewStatus.CLEARED
    assert verdict.is_cleared
    assert verdict.reasons == ()  # 통과에는 사유가 필요 없다
    assert verdict.reviewed_by == "법률검토자"  # 화면이 검토자를 보여줄 수 있어야 한다
    assert verdict.reviewed_at == "2026-09-10"


def test_blocked_hides_content():
    verdict = verdict_for(review_fields={"status": "blocked", "note": "선거일 전 6일 공표 금지"})
    assert verdict.status is ReviewStatus.BLOCKED
    assert not verdict.shows_content  # 웹앱이 수치를 그리지 않는 근거
    assert "공표 금지" in verdict.reasons[0]


def test_high_risk_starts_blocked_without_a_camp_review():
    """**분리하면서 잃을 뻔한 것.**

    `docs/90-compliance.md §5` 는 고위험 산출물(메시지 자산·게시물 배치안)이 기본
    `blocked` 라고 정한다. 검토 기록을 캠프 쪽으로 옮기면서 정책 쪽에 바닥이 없으면,
    검토 기록이 아직 없는 새 캠프에서 고위험이 unreviewed(내용 표시)로 떨어진다.
    """
    verdict = verdict_for(risk="high", default_status="blocked", note="직접 선거운동 자료")
    assert verdict.status is ReviewStatus.BLOCKED
    assert not verdict.shows_content
    assert "선거운동" in verdict.reasons[0]


def test_camp_signature_can_lift_a_blocked_default():
    """정책의 기본 blocked 는 바닥이지 천장이 아니다.

    최종 판단자는 캠프의 법률 검토다 (`90-compliance.md §2`). 서명이 있으면 열린다.
    """
    verdict = verdict_for(
        risk="high",
        default_status="blocked",
        review_fields={"status": "cleared", "reviewed_by": "법률검토자"},
    )
    assert verdict.status is ReviewStatus.CLEARED


def test_unreviewed_still_shows_content():
    """unreviewed 는 숨기는 게 아니라 경고와 함께 보여주는 것이다 (규칙 5의 문구)."""
    verdict = verdict_for(review_fields={"status": "unreviewed"})
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert verdict.shows_content


# --- notes: 상태를 바꾸지 않는 경고 ------------------------------------------------


def test_low_confidence_warns_without_changing_status():
    """검토를 통과한 것과 데이터가 튼튼한 것은 다른 문제다."""
    verdict = verdict_for(
        make_record(confidence=0.7),
        min_confidence=0.9,
        review_fields={"status": "cleared", "reviewed_by": "법률검토자"},
    )
    assert verdict.status is ReviewStatus.CLEARED  # 상태는 그대로
    assert any("0.70" in n for n in verdict.notes)


def test_confidence_at_threshold_is_not_flagged():
    assert verdict_for(make_record(confidence=0.7), min_confidence=0.7).notes == ()


def test_derived_without_evidence_is_noted():
    """파생인데 derived_from 이 비면 근거를 추적할 수 없다."""
    verdict = verdict_for(make_record(derived_from=[]), derived=True)
    assert any("derived_from" in n for n in verdict.notes)


def test_derived_with_evidence_is_quiet():
    assert verdict_for(make_record(derived_from=["a1b2c3d4e5f60718"]), derived=True).notes == ()


def test_notes_survive_a_blocked_verdict():
    """notes 는 상태와 독립이다. 차단됐다고 데이터 경고가 사라지지 않는다."""
    verdict = verdict_for(
        make_record(confidence=0.1, derived_from=[]),
        derived=True,
        min_confidence=0.9,
        review_fields={"status": "blocked"},
    )
    assert verdict.status is ReviewStatus.BLOCKED
    assert len(verdict.notes) == 2


# --- 순수성 ---------------------------------------------------------------------


def test_review_is_pure():
    """같은 (정책+검토, 레코드)면 같은 판정. 시계도 난수도 쓰지 않는다."""
    c = compliance_with(review_fields={"status": "cleared", "reviewed_by": "검토자"})
    record = make_record()
    assert review_with(c, record) == review_with(c, record)


# --- 실제 배포 정책표 --------------------------------------------------------------


def test_shipped_policy_loads():
    """`data/shared/reference/compliance.policy.yaml` 이 유효하다."""
    policy = mod.load_policy()
    assert policy.default_status is ReviewStatus.UNREVIEWED
    assert policy.for_kind("segment_profile") is not None


def test_shipped_policy_carries_no_signature():
    """**공용 정책표에는 서명이 없다.** 서명은 캠프 파일에만 있다 (P-001 §13).

    분리 전에는 여기에 status·reviewed_by 가 있었고, 그래서 한 캠프의 서명이
    모든 캠프에 적용되는 구조였다. 그 필드가 되돌아오면 이 테스트가 잡는다.
    """
    entry = mod.load_policy().for_kind("segment_profile")
    assert not hasattr(entry, "status")
    assert not hasattr(entry, "reviewed_by")
    assert entry.default_status is ReviewStatus.UNREVIEWED


def test_shipped_policy_alone_clears_nothing():
    """공용 정책만으로는 아무것도 통과하지 않는다 — 서명이 캠프 파일에만 있기 때문이다.

    항목별 기본 처분이 전부 미검토임을 확인하고(정책표 자체), 실제 판정도 그렇게
    나오는지 news_article 레코드로 한 번 확인한다.
    """
    policy = mod.load_policy()
    for entry in policy.outputs:
        assert entry.default_status is not ReviewStatus.CLEARED, entry.kind

    assert review(make_record()).status is ReviewStatus.UNREVIEWED
