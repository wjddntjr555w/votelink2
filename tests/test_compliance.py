"""산출물 검증 — 절대 규칙 5의 집행 근거.

여기서 지키는 것은 하나다: **모르면 통과시키지 않는다.**
정책표에 없거나, 서명이 없거나, 선거일을 몰라 기간을 계산할 수 없으면 전부
`unreviewed` 로 떨어져야 한다. 그래야 새 산출물이 조용히 무경고로 표시되지 않는다.

판정 엔진은 kind를 가리지 않으므로 여기서는 conftest 의 `news_article` 레코드를 쓴다.
실제 배포 정책표가 유효한지는 맨 아래 절이 따로 본다.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.conftest import make_record
from votelink.reference import compliance as mod
from votelink.reference.compliance import ReviewStatus, review


@pytest.fixture(autouse=True)
def fresh_cache():
    mod.reset_cache()
    yield
    mod.reset_cache()


def write(tmp_path, body: str):
    path = tmp_path / "compliance.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def policy_with(tmp_path, **fields) -> Path:
    """news_article 항목 하나짜리 정책표. 지정한 필드만 덮어쓴다."""
    base = {"kind": "news_article", "risk": "low"}
    base.update(fields)
    lines = "\n".join(f"    {k}: {_yaml(v)}" for k, v in base.items())
    return write(tmp_path, f"election_day: null\noutputs:\n  -\n{lines}\n")


def _yaml(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


# --- fail-closed: 모르면 통과시키지 않는다 ----------------------------------------


def test_kind_not_in_policy_is_unreviewed(tmp_path):
    """정책표에 없는 kind 는 unreviewed 다.

    이게 이 모듈의 존재 이유다. 새 분석기가 새 산출물을 내면 아무도 코드를 고치지
    않아도 자동으로 경고가 붙어야 한다. 블랙리스트였다면 조용히 통과했을 것이다.
    """
    path = write(tmp_path, "election_day: null\noutputs: []\n")
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert verdict.reasons  # 왜 unreviewed 인지 말해야 한다
    assert "news_article" in verdict.reasons[0]


def test_cleared_without_signature_is_unreviewed(tmp_path):
    """서명 없는 서명란은 서명이 아니다.

    cleared 는 시스템의 판단이 아니라 사람의 서명을 옮겨 적은 것이다. reviewed_by 가
    비어 있으면 아무도 검토하지 않았다는 뜻이므로 통과시키지 않는다.
    """
    path = policy_with(tmp_path, status="cleared", reviewed_by="")
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert "reviewed_by" in verdict.reasons[0]


def test_whitespace_signature_does_not_count(tmp_path):
    """공백만 넣어서 통과시킬 수 없다."""
    path = policy_with(tmp_path, status="cleared", reviewed_by="   ")
    assert review(make_record(), path).status is ReviewStatus.UNREVIEWED


def test_blackout_without_election_day_is_unreviewed(tmp_path):
    """선거일을 모르면 기간을 계산할 수 없다. 계산할 수 없으면 통과시키지 않는다."""
    path = policy_with(
        tmp_path,
        status="cleared",
        reviewed_by="법률검토자",
        blackout="poll_publication",
    )
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert "election_day" in verdict.reasons[0]


def test_default_status_cleared_is_rejected_at_load(tmp_path):
    """`default_status: cleared` 는 규칙 5를 끄는 것이라 로딩 자체가 실패한다.

    파일 한 줄로 검증 전체를 무력화할 수 있으면 안 된다.
    """
    path = write(tmp_path, "default_status: cleared\noutputs: []\n")
    with pytest.raises(ValidationError, match="fail-closed"):
        mod.load_policy(path)


def test_missing_policy_file_is_an_error(tmp_path):
    """정책 파일이 없으면 조용히 통과시키지 않고 터진다."""
    with pytest.raises(FileNotFoundError):
        mod.load_policy(tmp_path / "없다.yaml")


def test_duplicate_kind_is_rejected(tmp_path):
    """같은 kind 가 둘이면 어느 쪽이 적용되는지 알 수 없다."""
    path = write(
        tmp_path,
        "outputs:\n  - kind: news_article\n    risk: low\n  - kind: news_article\n    risk: high\n",
    )
    with pytest.raises(ValidationError, match="두 번"):
        mod.load_policy(path)


# --- 통과와 차단 -----------------------------------------------------------------


def test_signed_cleared_passes_and_carries_the_signature(tmp_path):
    path = policy_with(
        tmp_path, status="cleared", reviewed_by="법률검토자", reviewed_at="2026-09-10"
    )
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.CLEARED
    assert verdict.is_cleared
    assert verdict.reasons == ()  # 통과에는 사유가 필요 없다
    assert verdict.reviewed_by == "법률검토자"  # 화면이 검토자를 보여줄 수 있어야 한다
    assert verdict.reviewed_at == "2026-09-10"


def test_blocked_hides_content(tmp_path):
    path = policy_with(tmp_path, status="blocked", note="선거일 전 6일 공표 금지")
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.BLOCKED
    assert not verdict.shows_content  # 웹앱이 수치를 그리지 않는 근거
    assert "공표 금지" in verdict.reasons[0]


def test_unreviewed_still_shows_content(tmp_path):
    """unreviewed 는 숨기는 게 아니라 경고와 함께 보여주는 것이다 (규칙 5의 문구)."""
    path = policy_with(tmp_path, status="unreviewed")
    verdict = review(make_record(), path)
    assert verdict.status is ReviewStatus.UNREVIEWED
    assert verdict.shows_content


# --- notes: 상태를 바꾸지 않는 경고 ------------------------------------------------


def test_low_confidence_warns_without_changing_status(tmp_path):
    """검토를 통과한 것과 데이터가 튼튼한 것은 다른 문제다."""
    path = policy_with(
        tmp_path,
        status="cleared",
        reviewed_by="법률검토자",
        min_confidence=0.9,
    )
    verdict = review(make_record(confidence=0.7), path)
    assert verdict.status is ReviewStatus.CLEARED  # 상태는 그대로
    assert any("0.70" in n for n in verdict.notes)


def test_confidence_at_threshold_is_not_flagged(tmp_path):
    path = policy_with(tmp_path, min_confidence=0.7)
    assert review(make_record(confidence=0.7), path).notes == ()


def test_derived_without_evidence_is_noted(tmp_path):
    """파생인데 derived_from 이 비면 근거를 추적할 수 없다."""
    path = policy_with(tmp_path, derived=True)
    verdict = review(make_record(derived_from=[]), path)
    assert any("derived_from" in n for n in verdict.notes)


def test_derived_with_evidence_is_quiet(tmp_path):
    path = policy_with(tmp_path, derived=True)
    assert review(make_record(derived_from=["a1b2c3d4e5f60718"]), path).notes == ()


def test_notes_survive_a_blocked_verdict(tmp_path):
    """notes 는 상태와 독립이다. 차단됐다고 데이터 경고가 사라지지 않는다."""
    path = policy_with(tmp_path, status="blocked", derived=True, min_confidence=0.9)
    verdict = review(make_record(confidence=0.1, derived_from=[]), path)
    assert verdict.status is ReviewStatus.BLOCKED
    assert len(verdict.notes) == 2


# --- 순수성 ---------------------------------------------------------------------


def test_review_is_pure(tmp_path):
    """같은 (정책, 레코드)면 같은 판정. 시계도 난수도 쓰지 않는다."""
    path = policy_with(tmp_path, status="cleared", reviewed_by="검토자")
    record = make_record()
    assert review(record, path) == review(record, path)


# --- 실제 배포 정책표 --------------------------------------------------------------


def test_shipped_policy_loads():
    """`data/shared/reference/compliance.yaml` 이 유효하다."""
    policy = mod.load_policy()
    assert policy.default_status is ReviewStatus.UNREVIEWED
    assert policy.for_kind("segment_profile") is not None


def test_shipped_policy_has_not_been_signed_off():
    """아직 아무도 법률 검토를 하지 않았으므로 unreviewed 여야 한다.

    누군가 reviewed_by 없이 cleared 로 바꾸면 review() 가 되돌리지만, 서명까지 넣어
    통과시키는 것은 사람의 결정이다. 이 테스트는 '기본값이 조용히 통과로 바뀌는 일'만 막는다.
    """
    entry = mod.load_policy().for_kind("segment_profile")
    assert entry.status is ReviewStatus.UNREVIEWED
    assert entry.reviewed_by == ""
