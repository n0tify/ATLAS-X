"""Authentication tests (Phase 7)."""

from __future__ import annotations

import pytest

from atlas.auth.service import (
    AuthenticationFailed,
    AuthService,
    LoginLockedError,
    UsernameAlreadyExists,
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


def test_register_rejects_short_password(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(ValueError):
        svc.register("bob", "short")


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
    svc.register("dave", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed) as exc:
        svc.login("dave", "wrong-password")
    assert str(exc.value) == "invalid username or password"


def test_login_unknown_user_same_generic_error(tmp_path) -> None:
    svc = _service(tmp_path)
    with pytest.raises(AuthenticationFailed) as exc:
        svc.login("no-such-user", "correct-horse-battery")
    assert str(exc.value) == "invalid username or password"


def test_password_stored_as_argon2_not_plaintext(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("erin", "correct-horse-battery")

    stored = _user_row(svc)
    assert stored["password_hash"].startswith("$argon2id$")
    assert "correct-horse-battery" not in stored["password_hash"]


def _user_row(svc: AuthService):
    from atlas.storage.repositories import UserRepo

    user_repo = UserRepo()
    with svc._db.transaction() as conn:
        return user_repo.get_by_username(conn, "erin")


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
    svc.register("ivan", "correct-horse-battery")
    result = svc.login("ivan", "correct-horse-battery")
    expired = add_minutes_iso(utcnow_iso(), -5)
    with svc._db.transaction() as conn:
        conn.execute("UPDATE sessions SET expires_at = ?", (expired,))
    assert svc.validate_session(result["token"]) is None


def test_logout_revokes_session(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("judy", "correct-horse-battery")
    result = svc.login("judy", "correct-horse-battery")
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
    svc.register("kyle", "correct-horse-battery")
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            svc.login("kyle", "wrong-password")
    with pytest.raises(LoginLockedError):
        svc.login("kyle", "wrong-password")
    with pytest.raises(LoginLockedError):
        svc.login("kyle", "correct-horse-battery")


def test_lockout_resets_on_successful_login(tmp_path) -> None:
    svc = _service(
        tmp_path,
        auth_max_login_attempts=3,
        auth_lockout_minutes=60,
        auth_failure_delay_seconds=0.0,
    )
    svc.register("leah", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed):
        svc.login("leah", "wrong-one")
    with pytest.raises(AuthenticationFailed):
        svc.login("leah", "wrong-two")
    assert svc.login("leah", "correct-horse-battery")["user"]["username"] == "leah"
    for _ in range(3):
        with pytest.raises(AuthenticationFailed):
            svc.login("leah", "wrong-again")
    with pytest.raises(LoginLockedError):
        svc.login("leah", "correct-horse-battery")


def test_change_password_wrong_old_rejected(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("mike", "correct-horse-battery")
    result = svc.login("mike", "correct-horse-battery")
    with pytest.raises(AuthenticationFailed):
        svc.change_password(result["user"]["id"], "not-the-password", "new-password-1")


def test_change_password_then_old_password_fails(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("nina", "correct-horse-battery")
    result = svc.login("nina", "correct-horse-battery")
    user_id = result["user"]["id"]
    svc.change_password(user_id, "correct-horse-battery", "brand-new-password-9")
    with pytest.raises(AuthenticationFailed):
        svc.login("nina", "correct-horse-battery")
    assert svc.login("nina", "brand-new-password-9")["user"]["username"] == "nina"
    assert svc.validate_session(result["token"]) is None


def test_cross_user_session_isolation(tmp_path) -> None:
    svc = _service(tmp_path)
    svc.register("oscar", "correct-horse-battery")
    svc.register("pat", "correct-horse-battery")
    oscar = svc.login("oscar", "correct-horse-battery")
    pat = svc.login("pat", "correct-horse-battery")

    oscar_user = svc.validate_session(oscar["token"])
    pat_user = svc.validate_session(pat["token"])
    assert oscar_user["id"] != pat_user["id"]
    assert oscar_user["username"] == "oscar"
    assert pat_user["username"] == "pat"

    from atlas.storage.repositories import TaskRepo

    tasks = TaskRepo()
    with svc._db.transaction() as conn:
        task_id = tasks.create(conn, user_id=oscar_user["id"], title="private", goal="g")
        assert tasks.get(conn, pat_user["id"], task_id) is None
        assert tasks.get(conn, oscar_user["id"], task_id) is not None
