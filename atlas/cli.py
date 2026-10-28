"""Command-line entry points: health/smoke check."""

from __future__ import annotations

import sys

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.logging_config import configure_logging
from atlas.storage.db import Database


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_environ()
    configure_logging(settings)
    db = Database(settings.database_path)
    db.initialize()
    AuthService(db, settings).bootstrap()
    print(f"ATLAS-X OK  database={settings.database_path} env={settings.environment}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
