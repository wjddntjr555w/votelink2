"""계정과 비밀번호. 제안서: `docs/proposals/P-002-auth-and-camp-approval.md` §5·§8.

**비밀번호는 stdlib `hashlib.scrypt` 로 해싱한다.** `passlib`·`bcrypt`·`argon2-cffi` 를
쓰지 않는다 — `pyproject.toml` 이 "uvloop 는 Windows 에서 안 깔린다"며 순수 휠을 선호하는
기조를 이미 적어두었고, scrypt 는 그 기조에서 의존성 0으로 얻어진다.

**캠프 = 계정 1개**다. 캠프원끼리 공유한다. 대가는 P-002 §7 에 정직하게 적혀 있다 —
감사 로그가 "이 캠프의 누군가"까지만 말하고, 시스템이 법률 검토 서명을 보증하지 못한다.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from votelink.control.db import connect, now

# scrypt 파라미터. RFC 7914 가 대화형 로그인에 권하는 값(N=2^14, r=8, p=1)이다.
# 해시 문자열에 함께 담으므로 나중에 올려도 옛 해시가 그대로 검증된다.
_N, _R, _P = 2**14, 8, 1
_DKLEN = 32


class Role(StrEnum):
    CAMP = "camp"
    OPERATOR = "operator"
    """운영자는 모든 캠프를 볼 수 있다. **단일 신뢰 지점이다** (P-003 §6) —
    계정 수를 최소로 유지하는 것이 유일한 통제다."""


class Status(StrEnum):
    PENDING = "pending"
    """가입 신청은 했으나 아직 승인되지 않았다. `/pending` 만 볼 수 있다."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class AccountError(ValueError):
    """계정을 만들거나 고칠 수 없는 상태."""


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    role: Role
    camp_id: str | None
    status: Status
    created_at: str
    last_login_at: str | None

    @property
    def is_operator(self) -> bool:
        return self.role is Role.OPERATOR

    @property
    def is_active(self) -> bool:
        return self.status is Status.ACTIVE


def hash_password(raw: str) -> str:
    """`scrypt$N$r$p$salt$hash`. 파라미터를 문자열에 함께 담는다."""
    if not raw:
        raise AccountError("비밀번호가 비었다")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(raw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(raw: str, stored: str) -> bool:
    """`compare_digest` 로 비교한다 — 문자열 `==` 는 앞자리부터 달라지는 시점이 다르다."""
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    dk = hashlib.scrypt(
        raw.encode(),
        salt=bytes.fromhex(salt_hex),
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(hash_hex) // 2,
    )
    return secrets.compare_digest(dk.hex(), hash_hex)


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        id=row["id"],
        email=row["email"],
        role=Role(row["role"]),
        camp_id=row["camp_id"],
        status=Status(row["status"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def create(
    email: str,
    password: str,
    *,
    role: Role = Role.CAMP,
    status: Status = Status.PENDING,
    camp_id: str | None = None,
    path: Path | None = None,
) -> Account:
    email = email.strip().lower()
    if not email:
        raise AccountError("이메일이 비었다")
    if role is Role.CAMP and status is Status.ACTIVE and not camp_id:
        raise AccountError(
            "활성 캠프 계정에는 camp_id 가 있어야 한다 — 어느 캠프 공간을 보는지 "
            "정하지 않은 채로 열면 격리가 성립하지 않는다"
        )
    with connect(path) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO accounts (email, password_hash, role, camp_id, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (email, hash_password(password), role.value, camp_id, status.value, now()),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountError(f"이미 있는 이메일이다: {email}") from exc
        return get(cur.lastrowid, path=path)  # type: ignore[arg-type]


def get(account_id: int, *, path: Path | None = None) -> Account:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise AccountError(f"계정 {account_id} 이 없다")
    return _row_to_account(row)


def by_email(email: str, *, path: Path | None = None) -> Account | None:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return _row_to_account(row) if row else None


def authenticate(email: str, password: str, *, path: Path | None = None) -> Account | None:
    """이메일·비밀번호가 맞으면 계정, 아니면 None.

    **없는 계정과 틀린 비밀번호를 구분해 알려주지 않는다.** 구분하면 어느 이메일이
    등록돼 있는지 알려주는 셈이고, 경쟁 캠프를 함께 받는 제품에서 그건 정보 누출이다.
    """
    account = by_email(email, path=path)
    if account is None:
        # 계정이 없어도 해시를 한 번 계산한다 — 응답 시간으로 존재 여부가 새지 않게.
        verify_password(password, hash_password("dummy"))
        return None
    with connect(path) as conn:
        row = conn.execute(
            "SELECT password_hash FROM accounts WHERE id = ?", (account.id,)
        ).fetchone()
    if not verify_password(password, row["password_hash"]):
        return None
    return account


def touch_login(account_id: int, *, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE accounts SET last_login_at = ? WHERE id = ?", (now(), account_id))


def set_status(account_id: int, status: Status, *, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE accounts SET status = ? WHERE id = ?", (status.value, account_id))


def set_camp(account_id: int, camp_id: str, *, path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("UPDATE accounts SET camp_id = ? WHERE id = ?", (camp_id, account_id))


def set_password(account_id: int, password: str, *, path: Path | None = None) -> None:
    """운영자가 임시 비밀번호를 발급하는 통로.

    메일 발송 인프라가 없어 자가 재설정은 범위 밖이다 (P-002 §14·§15).
    """
    with connect(path) as conn:
        conn.execute(
            "UPDATE accounts SET password_hash = ? WHERE id = ?",
            (hash_password(password), account_id),
        )


def listing(*, role: Role | None = None, path: Path | None = None) -> list[Account]:
    sql = "SELECT * FROM accounts"
    args: tuple = ()
    if role is not None:
        sql += " WHERE role = ?"
        args = (role.value,)
    sql += " ORDER BY id"
    with connect(path) as conn:
        return [_row_to_account(r) for r in conn.execute(sql, args)]


def has_operator(*, path: Path | None = None) -> bool:
    """운영자가 하나라도 있는가. 기동 점검이 이걸 본다."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT 1 FROM accounts WHERE role = ? LIMIT 1", (Role.OPERATOR.value,)
        ).fetchone()
    return row is not None
