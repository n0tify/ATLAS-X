"""Password hashing via Argon2id (argon2-cffi). No custom cryptography."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32


def hash_password(plaintext: str) -> str:
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, plaintext: str) -> bool:
    try:
        return _hasher.verify(password_hash, plaintext)
    except Argon2Error:
        return False


def validate_username(username: str) -> bool:
    if not (USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH):
        return False
    return all(c.isalnum() or c in "_-" for c in username)
