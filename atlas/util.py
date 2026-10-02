"""Shared time helpers used across persistence and authentication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_minutes_iso(iso: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso)
    return (dt + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def is_later_than(a: str, b: str) -> bool:
    return datetime.fromisoformat(a) > datetime.fromisoformat(b)
