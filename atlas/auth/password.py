"""Password hashing via Argon2id (argon2-cffi) plus the local credential policy.

The policy here is deliberately narrow: it decides whether a value is safe to
store and safe to show back to the person who typed it. It says nothing about
who is allowed to register -- that is ownership and authorization, handled in
``atlas.auth.service``.
"""

from __future__ import annotations

from enum import StrEnum

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 5
# There was no upper bound before this policy. A bound is kept so one oversized
# request cannot hand an unbounded payload to Argon2, but it is only applied
# when a credential is set and never at login, so no existing password stops
# working. 256 sits far above the 64 characters NIST SP 800-63B asks systems to
# accept, so this does not constrain any real secret.
MAX_PASSWORD_LENGTH = 256

USERNAME_MIN_LENGTH = 5
USERNAME_MAX_LENGTH = 32


class UsernameProblem(StrEnum):
    NOT_TEXT = "not_text"
    EMPTY = "empty"
    NOT_PRINTABLE = "not_printable"
    SURROUNDING_WHITESPACE = "surrounding_whitespace"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"


class PasswordProblem(StrEnum):
    NOT_TEXT = "not_text"
    EMPTY = "empty"
    NOT_PRINTABLE = "not_printable"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"


def username_problem(username: str) -> UsernameProblem | None:
    """The first way a username breaks the policy, or None when it is fine.

    A username is an opaque label, not an address, so every printable character
    is accepted -- '@' and '.' included, which is what makes an email-style name
    such as 'e1838910@gmail.com' a normal username rather than a special case.
    What is refused is anything that cannot be echoed back safely or that turns
    ambiguous once stored:

    * control and format characters, which also refuses zero-width look-alikes
      such as U+200B that would render as a different name than the one stored;
    * leading or trailing whitespace, which would otherwise make two names that
      look identical on screen compare unequal in the database.

    The name is measured in code points, compared exactly as given -- never
    trimmed, never case folded, never Unicode-normalized. 'UserName' and
    'username' are therefore two distinct identities, matching the case
    sensitive unique index in the schema.
    """
    if not isinstance(username, str):
        return UsernameProblem.NOT_TEXT
    if not username:
        return UsernameProblem.EMPTY
    if not username.isprintable():
        return UsernameProblem.NOT_PRINTABLE
    if username != username.strip():
        return UsernameProblem.SURROUNDING_WHITESPACE
    if len(username) < USERNAME_MIN_LENGTH:
        return UsernameProblem.TOO_SHORT
    if len(username) > USERNAME_MAX_LENGTH:
        return UsernameProblem.TOO_LONG
    return None


def password_problem(plaintext: str) -> PasswordProblem | None:
    """The first way a password breaks the policy, or None when it is fine.

    Length and printable characters, nothing else. No character-class rules and
    no trimming: a password is an opaque secret, so rewriting it would change
    what the person believes they stored.
    """
    if not isinstance(plaintext, str):
        return PasswordProblem.NOT_TEXT
    if not plaintext:
        return PasswordProblem.EMPTY
    if not plaintext.isprintable():
        return PasswordProblem.NOT_PRINTABLE
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        return PasswordProblem.TOO_SHORT
    if len(plaintext) > MAX_PASSWORD_LENGTH:
        return PasswordProblem.TOO_LONG
    return None


def hash_password(plaintext: str) -> str:
    # Guard, not a user-facing check. Callers validate first and report the
    # specific problem through AuthService, so this only ever fires on an
    # internal bug and its text is never meant to be shown.
    if password_problem(plaintext) is not None:
        raise ValueError("password does not satisfy the credential policy")
    return _hasher.hash(plaintext)


def verify_password(password_hash: str, plaintext: str) -> bool:
    try:
        return _hasher.verify(password_hash, plaintext)
    except Argon2Error:
        return False
