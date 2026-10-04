"""Authentication tests (Phase 7)."""

from __future__ import annotations

import sqlite3
from typing import cast

import pytest

from atlas.auth.password import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    PasswordProblem,
    UsernameProblem,
    hash_password,
    password_problem,
    username_problem,
)
from atlas.auth.service import (
    DUPLICATE_USERNAME_MESSAGE,
    AuthenticationFailed,
    AuthError,
    AuthService,
    LoginLockedError,
    PasswordRejected,
    UsernameAlreadyExists,
    UsernameRejected,
)
from atlas.auth.sessions import hash_token
from atlas.config.settings import Settings
from atlas.storage.db import Database
from atlas.util import add_minutes_iso, utcnow_iso


def _service(tmp_path, **settings_kwargs) -> AuthService:
    settings = Settings(**settings_kwargs)
    db = Database(tmp_path / "atlas.db")
    db.initialize()
    service = AuthService(db, settings)
    service.bootstrap()
    return service


def test_register_returns_public_user_only(tmp_path) -> None:
    svc = _service(tmp_path)
    user = svc.register("alice", "correct-horse-battery")
    assert user["username"] == "alice"
    assert user["id"] > 0
    assert "password_hash" not in user


def test_register_duplicate_username_rejected(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("alice", "correct-horse-battery")
    with pytest.raises(UsernameAlreadyExists):
        svc.register("alice", "another-password-1")


def test_register_rejects_password_below_minimum(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(PasswordRejected) as exc:
        svc.register("bobby", "four")
    assert str(exc.value) == "Password must be at least 5 characters."


def test_login_success_returns_token_and_user(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("carol", "correct-horse-battery")
    result = svc.login("carol", "correct-horse-battery")
    assert result["user"]["username"] == "carol"
    assert len(result["token"]) >= 40
    assert "password_hash" not in result["user"]
    assert "password" not in result


def test_login_wrong_password_generic_error(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("david", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed) as exc:
        svc.login("david", "wrong-password")
    assert str(exc.value) == "invalid username or password"


def test_login_unknown_user_same_generic_error(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AuthenticationFailed) as exc:
        svc.login("no-such-user", "correct-horse-battery")
    assert str(exc.value) == "invalid username or password"


def test_password_stored_as_argon2_not_plaintext(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("erika", "correct-horse-battery")

    stored = _user_row(svc)
    assert stored["password_hash"].startswith("$argon2id$")
    assert "correct-horse-battery" not in stored["password_hash"]


def _user_row(svc: AuthService):
    from atlas.storage.repositories import UserRepo

    user_repo = UserRepo()
    with svc._db.transaction() as conn:
        return user_repo.get_by_username(conn, "erika")


def test_session_token_only_stored_hashed(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("frank", "correct-horse-battery")
    result = svc.login("frank", "correct-horse-battery")
    token = result["token"]
    assert token != hash_token(token)
    with svc._db.transaction() as conn:
        row = conn.execute(
            "SELECT token_hash FROM sessions WHERE token_hash = ?", (hash_token(token),)
        ).fetchone()
        assert row is not None
        raw = conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert all(r["token_hash"] != token for r in raw)


def test_no_auth_secrets_in_logs(tmp_path, caplog) -> None:
    svc = _service(tmp_path)
    with caplog.at_level("DEBUG"):
        svc.register("grace", "correct-horse-battery")
        result = svc.login("grace", "correct-horse-battery")
        with pytest.raises(AuthenticationFailed):
            svc.login("grace", "definitely-wrong-pw")
        svc.logout(result["token"])
    log_text = caplog.text
    assert "correct-horse-battery" not in log_text
    assert "$argon2id$" not in log_text
    assert result["token"] not in log_text


def test_session_validation_round_trip(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("heidi", "correct-horse-battery")
    result = svc.login("heidi", "correct-horse-battery")
    user = svc.validate_session(result["token"])
    assert user is not None and user["username"] == "heidi"


def test_invalid_session_returns_none(tmp_path) -> None:
    svc = _service(tmp_path)
    assert svc.validate_session("totally-made-up-token-abcdef") is None


def test_expired_session_returns_none(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("ivana", "correct-horse-battery")
    result = svc.login("ivana", "correct-horse-battery")
    expired = add_minutes_iso(utcnow_iso(), -5)
    with svc._db.transaction() as conn:
        conn.execute("UPDATE sessions SET expires_at = ?", (expired,))
    assert svc.validate_session(result["token"]) is None


def test_logout_revokes_session(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("judith", "correct-horse-battery")
    result = svc.login("judith", "correct-horse-battery")
    assert svc.validate_session(result["token"]) is not None
    assert svc.logout(result["token"]) is True
    assert svc.validate_session(result["token"]) is None
    assert svc.logout(result["token"]) is False


def test_lockout_after_max_attempts(tmp_path) -> None:
    svc = _service(
        tmp_path,
        auth_max_login_attempts=3,
        auth_lockout_minutes=60,
        auth_failure_delay_seconds=0.0,
    )
    svc.register("kevin", "correct-horse-battery")
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            svc.login("kevin", "wrong-password")
    with pytest.raises(LoginLockedError):
        svc.login("kevin", "wrong-password")
    with pytest.raises(LoginLockedError):
        svc.login("kevin", "correct-horse-battery")


def test_lockout_resets_on_successful_login(tmp_path) -> None:
    svc = _service(
        tmp_path,
        auth_max_login_attempts=3,
        auth_lockout_minutes=60,
        auth_failure_delay_seconds=0.0,
    )
    svc.register("leona", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed):
        svc.login("leona", "wrong-one")
    with pytest.raises(AuthenticationFailed):
        svc.login("leona", "wrong-two")
    assert svc.login("leona", "correct-horse-battery")["user"]["username"] == "leona"
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            svc.login("leona", "wrong-again")
    with pytest.raises(LoginLockedError):
        svc.login("leona", "correct-horse-battery")


def test_change_password_wrong_old_rejected(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("michael", "correct-horse-battery")
    result = svc.login("michael", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed):
        svc.change_password(result["user"]["id"], "not-the-password", "new-password-1")


def test_change_password_then_old_password_fails(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("nadia", "correct-horse-battery")
    result = svc.login("nadia", "correct-horse-battery")
    user_id = result["user"]["id"]
    svc.change_password(user_id, "correct-horse-battery", "brand-new-password-9")
    with pytest.raises(AuthenticationFailed):
        svc.login("nadia", "correct-horse-battery")
    assert svc.login("nadia", "brand-new-password-9")["user"]["username"] == "nadia"
    assert svc.validate_session(result["token"]) is None


def test_cross_user_session_isolation(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("oscar", "correct-horse-battery")
    svc.register("patricia", "correct-horse-battery")
    oscar = svc.login("oscar", "correct-horse-battery")
    patricia = svc.login("patricia", "correct-horse-battery")

    oscar_user = svc.validate_session(oscar["token"])
    pat_user = svc.validate_session(patricia["token"])
    assert oscar_user["id"] != pat_user["id"]
    assert oscar_user["username"] == "oscar"
    assert pat_user["username"] == "patricia"

    from atlas.storage.repositories import TaskRepo

    tasks = TaskRepo()
    with svc._db.transaction() as conn:
        task_id = tasks.create(conn, user_id=oscar_user["id"], title="private", goal="g")
        assert tasks.get(conn, pat_user["id"], task_id) is None
        assert tasks.get(conn, oscar_user["id"], task_id) is not None


# --- Registration identifier and credential policy ----------------------------
#
# A username is an opaque label, not an address and not an email field. These
# tests pin both halves of that: the printable characters that must be accepted,
# and the characters that are refused because they cannot be shown back to the
# owner or would make two different names look identical.


ACCEPTED_USERNAMES = [
    "anushka",
    "e1838910@gmail.com",
    "hello.world",
    "hello-world",
    "hello_world",
    "user@example",
    "my-user",
    "a b c d",
    "\u00dcn\u00efc\u00f6d\u00e9",
    "\u30e6\u30fc\u30b6\u30fc\u540d",
    "\U0001f642\U0001f642\U0001f642\U0001f642\U0001f642",
]

REJECTED_USERNAMES = [
    ("", UsernameProblem.EMPTY),
    ("abcd", UsernameProblem.TOO_SHORT),
    ("a" * (USERNAME_MAX_LENGTH + 1), UsernameProblem.TOO_LONG),
    ("alice\nsmith", UsernameProblem.NOT_PRINTABLE),
    ("alice\rsmith", UsernameProblem.NOT_PRINTABLE),
    ("ali\tce", UsernameProblem.NOT_PRINTABLE),
    ("alice\x00smith", UsernameProblem.NOT_PRINTABLE),
    ("alice\x1bsmith", UsernameProblem.NOT_PRINTABLE),
    ("admin\u200b", UsernameProblem.NOT_PRINTABLE),
    ("admin\u202ereversed", UsernameProblem.NOT_PRINTABLE),
    ("\n\n\n\n\n", UsernameProblem.NOT_PRINTABLE),
    (" alice1", UsernameProblem.SURROUNDING_WHITESPACE),
    ("alice1 ", UsernameProblem.SURROUNDING_WHITESPACE),
    (" alice1 ", UsernameProblem.SURROUNDING_WHITESPACE),
    ("     ", UsernameProblem.SURROUNDING_WHITESPACE),
]


@pytest.mark.parametrize("username", ACCEPTED_USERNAMES)
def test_username_policy_accepts_printable_identifiers(username: str) -> None:
    assert username_problem(username) is None


@pytest.mark.parametrize(("username", "problem"), REJECTED_USERNAMES)
def test_username_policy_rejects_unsafe_identifiers(
    username: str, problem: UsernameProblem
) -> None:
    assert username_problem(username) == problem


def test_username_policy_rejects_non_text() -> None:
    assert username_problem(cast(str, 12345)) == UsernameProblem.NOT_TEXT


def test_username_length_bounds_are_inclusive() -> None:
    assert username_problem("a" * USERNAME_MIN_LENGTH) is None
    assert username_problem("a" * USERNAME_MAX_LENGTH) is None
    assert username_problem("a" * (USERNAME_MIN_LENGTH - 1)) == UsernameProblem.TOO_SHORT
    assert username_problem("a" * (USERNAME_MAX_LENGTH + 1)) == UsernameProblem.TOO_LONG


def test_username_is_never_silently_trimmed() -> None:
    # Two names that differ only by surrounding whitespace must not collapse
    # into one account, so the whitespace is refused rather than stripped.
    assert username_problem(" alice") is not None
    assert username_problem("alice ") is not None
    assert username_problem("alice ") is not None


def test_documented_policy_constants() -> None:
    assert (USERNAME_MIN_LENGTH, USERNAME_MAX_LENGTH) == (5, 32)
    assert MIN_PASSWORD_LENGTH == 5


ACCEPTED_PASSWORDS = [
    "12345",
    "abcde",
    "hello world",
    " leading and trailing spaces are secret ",
    "\u00dcn\u00efc\u00f6d\u00e9-pw",
    "\U0001f642\U0001f642\U0001f642\U0001f642\U0001f642",
    "k" * MAX_PASSWORD_LENGTH,
]

REJECTED_PASSWORDS = [
    ("", PasswordProblem.EMPTY),
    ("1", PasswordProblem.TOO_SHORT),
    ("1234", PasswordProblem.TOO_SHORT),
    ("four", PasswordProblem.TOO_SHORT),
    ("pass\tword", PasswordProblem.NOT_PRINTABLE),
    ("pass\nword", PasswordProblem.NOT_PRINTABLE),
    ("pass\rword", PasswordProblem.NOT_PRINTABLE),
    ("pass\x00word", PasswordProblem.NOT_PRINTABLE),
    ("k" * (MAX_PASSWORD_LENGTH + 1), PasswordProblem.TOO_LONG),
]


@pytest.mark.parametrize("password", ACCEPTED_PASSWORDS)
def test_password_policy_accepts_five_or_more_printable_characters(password: str) -> None:
    assert password_problem(password) is None


@pytest.mark.parametrize(("password", "problem"), REJECTED_PASSWORDS)
def test_password_policy_rejects_short_or_unprintable(
    password: str, problem: PasswordProblem
) -> None:
    assert password_problem(password) == problem


def test_password_policy_rejects_non_text() -> None:
    assert password_problem(cast(str, 12345)) == PasswordProblem.NOT_TEXT


def test_password_policy_has_no_character_class_rules() -> None:
    # Length and printability only: no case, digit, or symbol requirements.
    assert password_problem("aaaaa") is None
    assert password_problem("AAAAA") is None
    assert password_problem("     ") is None


def test_hash_password_guard_stays_generic() -> None:
    # The guard inside hash_password is for internal bugs, so its text names no
    # threshold and no rejected value.
    with pytest.raises(ValueError) as exc:
        hash_password("abc")
    assert str(exc.value) == "password does not satisfy the credential policy"
    assert "abc" not in str(exc.value)


def test_register_accepts_email_style_username(tmp_path) -> None:
    svc = _service(tmp_path)
    user = svc.register("e1838910@gmail.com", "short")
    assert user["username"] == "e1838910@gmail.com"
    assert "password_hash" not in user


def test_email_style_username_registers_logs_in_and_sessions(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("e1838910@gmail.com", "pass1")
    result = svc.login("e1838910@gmail.com", "pass1")
    assert result["user"]["username"] == "e1838910@gmail.com"
    session = svc.validate_session(result["token"])
    assert session is not None
    assert session["username"] == "e1838910@gmail.com"


def test_duplicate_email_style_username_refused_with_safe_message(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("e1838910@gmail.com", "pass1")
    with pytest.raises(UsernameAlreadyExists) as exc:
        svc.register("e1838910@gmail.com", "other-pass")
    assert str(exc.value) == DUPLICATE_USERNAME_MESSAGE
    assert str(exc.value) == "That username is already in use."


def test_email_style_username_is_still_hashed_with_argon2id(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("e1838910@gmail.com", "pass1")
    with svc._db.transaction() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            ("e1838910@gmail.com",),
        ).fetchone()
    assert row is not None
    assert row["password_hash"].startswith("$argon2id$")
    assert "pass1" not in row["password_hash"]


@pytest.mark.parametrize(
    ("username", "message"),
    [
        ("abcd", "Username must be at least 5 characters."),
        ("a" * 33, "Username must be at most 32 characters."),
        ("admin\u200b", "Username may only contain printable characters."),
        (" alice1", "Username must not start or end with whitespace."),
        ("alice1 ", "Username must not start or end with whitespace."),
        ("alice\nsmith", "Username may only contain printable characters."),
    ],
)
def test_register_refuses_bad_username_with_safe_message(
    tmp_path, username: str, message: str
) -> None:
    svc = _service(tmp_path)
    with pytest.raises(UsernameRejected) as exc:
        svc.register(username, "pass1")
    assert str(exc.value) == message

    from atlas.storage.repositories import UserRepo

    with svc._db.transaction() as conn:
        assert UserRepo().get_by_username(conn, username) is None


def test_register_refuses_bad_password_with_safe_message(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(PasswordRejected) as exc:
        svc.register("alice1", "four")
    assert str(exc.value) == "Password must be at least 5 characters."

    with pytest.raises(PasswordRejected) as exc:
        svc.register("alice1", "pass\tword")
    assert str(exc.value) == "Password may only contain printable characters."


def test_register_policy_failures_are_auth_errors_not_value_errors(tmp_path) -> None:
    svc = _service(tmp_path)
    for username, password in [("abcd", "pass1"), ("alice1", "four")]:
        with pytest.raises(AuthError) as exc:
            svc.register(username, password)
        assert not isinstance(exc.value, ValueError)


def test_rejection_messages_never_leak_the_rejected_password(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(PasswordRejected) as exc:
        svc.register("alice1", "sup3r\tsecret")
    assert "sup3r" not in str(exc.value)
    assert "\t" not in str(exc.value)


def test_username_case_sensitivity_is_preserved(tmp_path) -> None:
    # 'Casey', 'casey' and 'CASEY' stay three identities, because the existing
    # unique index compares stored names byte for byte. Folding case would mean
    # migrating that index, so it is left alone and pinned by this test instead.
    svc = _service(tmp_path)
    for name in ("Casey", "casey", "CASEY"):
        assert svc.register(name, "pass1")["username"] == name
        assert svc.login(name, "pass1")["user"]["username"] == name
    for name in ("Casey", "casey", "CASEY"):
        with pytest.raises(UsernameAlreadyExists):
            svc.register(name, "pass1")


def test_unique_index_blocks_duplicate_when_the_service_check_is_bypassed(tmp_path) -> None:
    # The exists() lookup in register() is only a fast path; the unique index is
    # the real guarantee, which is what stops a concurrent double registration.
    svc = _service(tmp_path)
    svc.register("racer", "pass1")

    from atlas.storage.repositories import UserRepo

    with pytest.raises(sqlite3.IntegrityError), svc._db.transaction() as conn:
        UserRepo().create(conn, username="racer", password_hash=hash_password("pass1"))


def test_legacy_short_username_still_authenticates(tmp_path) -> None:
    # 'abc' was valid under the old 3-character policy. Registration now refuses
    # it, but the row is left alone and sign-in still works.
    svc = _service(tmp_path)

    from atlas.storage.repositories import UserRepo

    with svc._db.transaction() as conn:
        UserRepo().create(conn, username="abc", password_hash=hash_password("pass1"))

    result = svc.login("abc", "pass1")
    assert result["user"]["username"] == "abc"
    with pytest.raises(UsernameRejected):
        svc.register("abc", "pass1")


def test_legacy_password_longer_than_the_new_bound_still_authenticates(tmp_path) -> None:
    # The upper bound is enforced when a credential is set, never at login, so a
    # secret that predates the bound is not invalidated by it.
    svc = _service(tmp_path)
    long_secret = "k" * (MAX_PASSWORD_LENGTH + 50)

    import argon2

    from atlas.storage.repositories import UserRepo

    with svc._db.transaction() as conn:
        UserRepo().create(
            conn,
            username="legacy",
            password_hash=argon2.PasswordHasher().hash(long_secret),
        )

    assert svc.login("legacy", long_secret)["user"]["username"] == "legacy"
    with pytest.raises(PasswordRejected):
        svc.register("newcomer", long_secret)


def test_change_password_accepts_five_character_password(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("alice", "correct-horse-battery")
    result = svc.login("alice", "correct-horse-battery")
    user_id = result["user"]["id"]
    svc.change_password(user_id, "correct-horse-battery", "five5")
    assert svc.login("alice", "five5")["user"]["username"] == "alice"


def test_change_password_refuses_password_below_minimum(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("alice", "correct-horse-battery")
    result = svc.login("alice", "correct-horse-battery")
    with pytest.raises(PasswordRejected) as exc:
        svc.change_password(result["user"]["id"], "correct-horse-battery", "four")
    assert str(exc.value) == "Password must be at least 5 characters."
    assert svc.login("alice", "correct-horse-battery")["user"]["username"] == "alice"
