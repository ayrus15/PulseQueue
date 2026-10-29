"""Structured JSON logging setup."""

from __future__ import annotations

import logging
import sys

from pythonjsonlogger.json import JsonFormatter

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configureLogging(level: str = "INFO") -> None:
    """Configure the root logger to emit structured JSON lines to stdout.

    Safe to call more than once (e.g. once at import time in tests and once
    at application startup) - it replaces any handlers it previously added
    instead of stacking duplicates.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        if getattr(handler, "_pulsequeueManaged", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    renameFields = {"asctime": "timestamp", "levelname": "level"}
    handler.setFormatter(JsonFormatter(_LOG_FORMAT, rename_fields=renameFields))
    handler._pulsequeueManaged = True  # type: ignore[attr-defined]
    root.addHandler(handler)
