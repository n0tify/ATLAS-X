"""Logging filter that redacts configured secret values before they reach handlers."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable


class SecretsRedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        non_empty = tuple(s for s in secrets if s)
        self._pattern = (
            re.compile("|".join(re.escape(s) for s in non_empty)) if non_empty else None
        )

    def filter(self, record: logging.LogRecord) -> bool:
        if self._pattern is None:
            return True
        message = record.getMessage()
        if self._pattern.search(message):
            record.msg = self._pattern.sub("[REDACTED]", message)
            record.args = ()
        return True
