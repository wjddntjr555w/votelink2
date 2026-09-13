"""control plane — 계정·세션·승인·감사 (P-002 §5·§8).

여기서 지키는 것:

- **원문 비밀번호도 원문 세션 토큰도 DB 에 없다.** DB 가 새도 그 자체로 로그인이 되지 않는다.
- **없는 계정과 틀린 비밀번호를 구분해 알려주지 않는다.** 구분하면 어느 이메일이
  등록돼 있는지 새고, 경쟁 캠프를 함께 받는 제품에서 그건 정보 누출이다.
- **승인이 DB↔디스크 인계점이다.** 승인 전에는 캠프 공간이 없다.
"""

from __future__ import annotations

import pytest

from votelink import control
from votelink.camp import load_camp
from votelink.control import accounts as acc
from votelink.control import audit, sessions, signup
from votelink.control.db import connect


@pytest.fixture
def db(tmp_path):
    """빈 control.db 하나. 루트 conftest 가 실제 파일을 이미 막고 있지만
    테스트끼리도 섞이지 않게 각자 파일을 쓴다."""
    path = tmp_path / "control.db"
    control.init(path)
    return path


@pytest.fixture
def operator(db):
    return acc.create("op@test", "pw", role=acc.Role.OPERATOR, status=acc.Status.ACTIVE, path=db)


# --- 비밀번호 ---------------------------------------------------------------------


def test_password_round_trip():
    stored = acc.hash_password("비밀번호")
    assert acc.verify_password("비밀번호", stored)
    assert not acc.verify_password("틀린값", stored)


def test_same_password_hashes_differently():
    """소금이 매번 다르다. 같은 해시가 두 번 나오면 레인보우 테이블이 통한다."""
    assert acc.hash_password("같은값") != acc.hash_password("같은값")


def test_hash_carries_its_parameters():
    """파라미터를 문자열에 담으므로 나중에 올려도 옛 해시가 검증된다."""
    assert acc.hash_password("x").startswith("scrypt$16384$8$1$")


def test_malformed_hash_does_not_crash():
    for junk in ("", "plaintext", "scrypt$bad", "bcrypt$1$2$3$4$5"):
        assert not acc.verify_password("x", junk)


def test_empty_password_is_refused():
    with pytest.raises(acc.AccountError):
        acc.hash_password("")


def test_raw_password_is_not_stored(db):
    account = acc.create("a@test", "평문비밀번호", path=db)
    with connect(db) as conn:
        row = conn.execute(
            "SELECT password_hash FROM accounts WHERE id = ?", (account.id,)
        ).fetchone()
    assert "평문비밀번호" not in row["password_hash"]


# --- 계정 -------------------------------------------------------------------------


def test_email_is_normalised(db):
    acc.create("  MiXeD@Test.COM ", "pw", path=db)
    assert acc.by_email("mixed@test.com", path=db) is not None


def test_duplicate_email_is_refused(db):
    acc.create("a@test", "pw", path=db)
    with pytest.raises(acc.AccountError, match="이미 있는"):
        acc.create("a@test", "pw2", path=db)


def test_active_camp_account_needs_a_camp(db):
    """어느 캠프 공간을 보는지 정하지 않은 채 열면 격리가 성립하지 않는다."""
    with pytest.raises(acc.AccountError, match="camp_id"):
        acc.create("a@test", "pw", status=acc.Status.ACTIVE, path=db)


def test_new_signup_account_is_pending(db):
    account = acc.create("a@test", "pw", path=db)
    assert account.status is acc.Status.PENDING
    assert not account.is_active
    assert account.camp_id is None


def test_authenticate_accepts_the_right_password(db):
    made = acc.create("a@test", "pw", path=db)
    assert acc.authenticate("a@test", "pw", path=db).id == made.id


def test_authenticate_rejects_the_wrong_password(db):
    acc.create("a@test", "pw", path=db)
    assert acc.authenticate("a@test", "틀림", path=db) is None


def test_unknown_email_and_wrong_password_look_the_same(db):
    """구분해 알려주면 어느 이메일이 등록돼 있는지 새어 나간다."""
    acc.create("a@test", "pw", path=db)
    assert acc.authenticate("없는@test", "pw", path=db) is None
    assert acc.authenticate("a@test", "틀림", path=db) is None


def test_has_operator(db, operator):
    assert acc.has_operator(path=db)


def test_no_operator_on_a_fresh_db(db):
    assert not acc.has_operator(path=db)


# --- 부트스트랩 운영자 ---------------------------------------------------------------


def test_the_bootstrap_operator_is_an_active_operator(db):
    """`serve --auth` 가 운영자 없는 서버에서 만드는 계정. 곧바로 쓸 수 있어야 한다."""
    account = acc.create_bootstrap_operator(path=db)
    assert account.email == acc.BOOTSTRAP_ID
    assert account.role is acc.Role.OPERATOR
    assert account.is_active


def test_the_bootstrap_password_is_detected(db):
    """**아는 비밀번호가 서버에 있으면 인증이 없는 것과 같다.** 기동 점검이 이걸 보고
    로컬 밖 바인딩을 거부한다 (P-002 §8-1)."""
    assert not acc.uses_bootstrap_password(path=db)
    acc.create_bootstrap_operator(path=db)
    assert acc.uses_bootstrap_password(path=db)


def test_changing_it_clears_the_detection(db):
    account = acc.create_bootstrap_operator(path=db)
    acc.set_password(account.id, "제대로된비번", path=db)
    assert not acc.uses_bootstrap_password(path=db)


def test_putting_it_back_is_detected_again(db):
    """플래그 컬럼이 아니라 **검사가 진실이라서** 되돌려도 잡힌다.
    플래그였다면 그때 거짓말을 한다."""
    account = acc.create_bootstrap_operator(path=db)
    acc.set_password(account.id, "제대로된비번", path=db)
    acc.set_password(account.id, acc.BOOTSTRAP_PASSWORD, path=db)
    assert acc.uses_bootstrap_password(path=db)


def test_a_camp_using_the_same_password_does_not_count(db):
    """판정은 **운영자** 계정만 본다. 캠프가 무엇을 쓰든 서버가 열리는 것과 무관하다."""
    acc.create("a@test", acc.BOOTSTRAP_PASSWORD, path=db)
    assert not acc.uses_bootstrap_password(path=db)


def test_one_stale_operator_among_many_still_counts(db):
    """운영자가 여럿이면 **하나라도** 기본 비밀번호면 막는다. 그 하나로 뚫린다."""
    acc.create_bootstrap_operator(path=db)
    acc.create(
        "ops2@test", "제대로된비번", role=acc.Role.OPERATOR, status=acc.Status.ACTIVE, path=db
    )
    assert acc.uses_bootstrap_password(path=db)


# --- 세션 -------------------------------------------------------------------------


def test_session_round_trip(db):
    account = acc.create("a@test", "pw", path=db)
    token = sessions.start(account.id, ip="127.0.0.1", path=db)
    resolved = sessions.resolve(token, path=db)
    assert resolved is not None
    assert resolved.account_id == account.id


def test_raw_token_is_not_stored(db):
    """DB 가 새도 남의 세션을 탈취할 수 없다."""
    account = acc.create("a@test", "pw", path=db)
    token = sessions.start(account.id, path=db)
    with connect(db) as conn:
        stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert token not in stored


def test_unknown_token_resolves_to_nothing(db):
    assert sessions.resolve("아무말", path=db) is None
    assert sessions.resolve(None, path=db) is None


def test_expired_session_is_rejected_and_cleaned(db):
    account = acc.create("a@test", "pw", path=db)
    token = sessions.start(account.id, path=db)
    with connect(db) as conn:
        conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+09:00'")

    assert sessions.resolve(token, path=db) is None
    assert sessions.active_count(account.id, path=db) == 0, "만료된 세션은 조회 때 치운다"


def test_using_a_session_extends_it(db):
    account = acc.create("a@test", "pw", path=db)
    token = sessions.start(account.id, path=db)
    with connect(db) as conn:
        conn.execute("UPDATE sessions SET expires_at = '2030-01-01T00:00:00+09:00'")
    sessions.resolve(token, path=db)
    with connect(db) as conn:
        after = conn.execute("SELECT expires_at FROM sessions").fetchone()["expires_at"]
    assert after != "2030-01-01T00:00:00+09:00", "쓰는 동안에는 끊기지 않는다"


def test_logout_ends_one_session(db):
    account = acc.create("a@test", "pw", path=db)
    a, b = sessions.start(account.id, path=db), sessions.start(account.id, path=db)
    sessions.end(a, path=db)
    assert sessions.resolve(a, path=db) is None
    assert sessions.resolve(b, path=db) is not None


def test_force_logout_ends_them_all(db):
    """비밀번호가 샜을 때의 즉시 대응. 2FA 를 두지 않기로 한 결정의 보완책이다."""
    account = acc.create("a@test", "pw", path=db)
    tokens = [sessions.start(account.id, path=db) for _ in range(3)]
    assert sessions.end_all(account.id, path=db) == 3
    assert all(sessions.resolve(t, path=db) is None for t in tokens)


def test_password_change_is_independent_of_sessions(db):
    """비밀번호만 바꾸면 기존 세션은 살아 있다 — CLI 가 둘을 함께 하는 이유다."""
    account = acc.create("a@test", "pw", path=db)
    token = sessions.start(account.id, path=db)
    acc.set_password(account.id, "새비번", path=db)
    assert sessions.resolve(token, path=db) is not None


# --- 가입 → 승인 -------------------------------------------------------------------


def test_signup_creates_a_pending_account(db):
    req = signup.request("a@test", "pw", "홍길동", "010-0000-0000", "2028 총선", path=db)
    assert req.is_pending
    assert acc.by_email("a@test", path=db).status is acc.Status.PENDING


def test_signup_needs_a_name_and_contact(db):
    with pytest.raises(signup.SignupError, match="후보 이름"):
        signup.request("a@test", "pw", "  ", "010", path=db)
    with pytest.raises(signup.SignupError, match="연락처"):
        signup.request("b@test", "pw", "홍길동", "", path=db)


def test_approval_creates_the_camp_space_on_disk(db, operator, tmp_path):
    """**승인이 DB↔디스크 인계점이다.** 승인 전에는 캠프 공간이 없다."""
    root = tmp_path / "data"
    req = signup.request("hong@test", "pw", "홍길동", "010", path=db)
    assert not (root / "camps").exists()

    camp_id = signup.approve(req.id, operator.id, path=db, camps_root=root)

    assert camp_id == "hong"
    info = load_camp(camp_id, root)
    assert info.candidate_name == "홍길동"
    assert acc.by_email("hong@test", path=db).status is acc.Status.ACTIVE
    assert acc.by_email("hong@test", path=db).camp_id == camp_id


def test_camp_id_is_path_safe(db, operator, tmp_path):
    """한글 이름을 경로에 쓰지 않는다 — 인코딩이 제각각이라 같은 캠프가 둘이 된다."""
    req = signup.request("kim.chul_su@test", "pw", "김철수", "010", path=db)
    camp_id = signup.approve(req.id, operator.id, path=db, camps_root=tmp_path / "data")
    assert camp_id == "kim-chul-su"


def test_approving_twice_is_refused(db, operator, tmp_path):
    root = tmp_path / "data"
    req = signup.request("a@test", "pw", "홍길동", "010", path=db)
    signup.approve(req.id, operator.id, path=db, camps_root=root)
    with pytest.raises(signup.SignupError, match="이미"):
        signup.approve(req.id, operator.id, path=db, camps_root=root)


def test_rejection_needs_a_reason(db, operator):
    """신청자가 무엇을 고쳐야 하는지 알아야 한다."""
    req = signup.request("a@test", "pw", "홍길동", "010", path=db)
    with pytest.raises(signup.SignupError, match="사유"):
        signup.reject(req.id, operator.id, note="  ", path=db)


def test_rejection_suspends_the_account(db, operator):
    req = signup.request("a@test", "pw", "홍길동", "010", path=db)
    signup.reject(req.id, operator.id, note="계약 미체결", path=db)
    assert acc.by_email("a@test", path=db).status is acc.Status.SUSPENDED


def test_pending_queue_lists_only_undecided(db, operator, tmp_path):
    a = signup.request("a@test", "pw", "가", "010", path=db)
    signup.request("b@test", "pw", "나", "010", path=db)
    signup.approve(a.id, operator.id, path=db, camps_root=tmp_path / "data")
    assert [r.candidate_name for r in signup.pending(path=db)] == ["나"]


# --- 감사 로그 ---------------------------------------------------------------------


def test_audit_records_who_did_what_where(db):
    audit.log("login", account_id=1, camp_id="c", ip="1.2.3.4", path=db)
    entry = audit.recent(path=db)[0]
    assert (entry.action, entry.camp_id, entry.ip) == ("login", "c", "1.2.3.4")


def test_audit_survives_an_account_that_is_gone(db):
    """감사 로그는 **이력**이라 현재 상태에 묶이지 않는다.

    account_id 에 외래키를 걸면 계정이 사라질 때 그 계정의 흔적도 사라지거나
    기록 자체가 실패한다. "유출이 없었다"를 증명해야 하는 표에서 그건 최악이다.
    """
    account = acc.create("gone@test", "pw", path=db)
    audit.log("login", account_id=account.id, path=db)
    with connect(db) as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account.id,))
    assert audit.recent(path=db)[0].account_id == account.id


def test_audit_filters_by_camp(db):
    audit.log("view", camp_id="a", path=db)
    audit.log("view", camp_id="b", path=db)
    assert [e.camp_id for e in audit.recent(camp_id="a", path=db)] == ["a"]


def test_audit_failure_does_not_raise(tmp_path, capsys):
    """감사 기록 실패가 서비스를 죽이면, 로그가 없는 것보다 나쁘다.
    대신 조용히 삼키지 않고 드러낸다."""
    audit.log("x", path=tmp_path / "없는디렉터리" / "nope.db" / "더깊이" / "a.db")
    assert "감사 기록 실패" in capsys.readouterr().err


def test_audit_is_newest_first(db):
    for i in range(3):
        audit.log(f"a{i}", path=db)
    assert [e.action for e in audit.recent(path=db)] == ["a2", "a1", "a0"]


# --- 스키마 진화 --------------------------------------------------------------------


def test_init_adds_a_missing_column_to_an_existing_table(tmp_path, monkeypatch):
    """`CREATE TABLE IF NOT EXISTS` 는 이미 있는 테이블에 새 컬럼을 추가하지 않는다.

    `jobs.note` 가 그런 사례다 — 이 컬럼이 생기기 전에 이미 `control.init()` 을
    돌려본 적 있는 실제 배포판은, 마이그레이션 없이 새 코드를 올리면 `note` 를
    쓰거나 읽는 순간(`jobs.start`/`jobs.get`) 그대로 터진다.
    """
    path = tmp_path / "control.db"
    control.init(path)  # 지금 스키마로 처음 만든다(이미 note 가 있다)

    # "옛 스키마"를 흉내낸다: note 컬럼이 없던 시절의 jobs 테이블로 되돌린다.
    with connect(path) as conn:
        conn.executescript(
            """
            DROP TABLE jobs;
            CREATE TABLE jobs (
              id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
              args TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
              finished_at TEXT, exit_code INTEGER, log_path TEXT, started_by INTEGER
            );
            """
        )

    control.init(path)  # 새 코드가 다시 기동하며 이 함수를 부른다

    with connect(path) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    assert "note" in columns

    import sys

    from votelink.control import jobs

    monkeypatch.setattr(jobs, "_command", lambda kind, target, args: [sys.executable, "-c", "pass"])
    job = jobs.start(
        "collect", "naver_news", [], 1, path=path, log_dir=tmp_path, note="이관 후 정상 동작"
    )
    assert jobs.get(job.id, path).note == "이관 후 정상 동작"
