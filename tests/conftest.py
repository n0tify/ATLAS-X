"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.storage.db import Database


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "data" / "atlas.db")
    database.initialize()
    return database


@pytest.fixture
def auth(db: Database, settings: Settings) -> AuthService:
    service = AuthService(db, settings)
    service.bootstrap()
    return service
