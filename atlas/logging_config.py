"""Logging configuration with secret redaction."""

from __future__ import annotations

import logging
import sys

from atlas.config.settings import Settings
from atlas.security.logging import SecretsRedactionFilter


def configure_logging(settings: Settings | None = None) -> None:
    """Configure application logging with secret redaction.

    Attaches a handler with SecretsRedactionFilter to the root logger.
    Call once at application startup.
    """
    if settings is None:
        settings = Settings.from_environ()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplication
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.addFilter(SecretsRedactionFilter(settings.secret_values()))
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the application's configuration."""
    return logging.getLogger(name)
