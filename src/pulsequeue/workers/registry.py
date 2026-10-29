"""Builds the handler registry: task type name -> callable.

Kept separate from ``handlers.py`` because ``processFile`` needs its
controlled base directory bound in (from Settings) before it can match
the uniform ``HandlerFunc`` signature every other handler already has.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any

from pulsequeue.domain.errors import UnsupportedTaskTypeError
from pulsequeue.workers import handlers

# Each handler's first parameter is actually its own specific payload model
# (see handlers.py), not a plain BaseModel - the registry dispatches by
# taskType string, which is the runtime invariant that keeps that safe.
# `Any` here is what lets a dict of otherwise-incompatible callables share
# one type; TASK_TYPE_REGISTRY/HANDLER_REGISTRY key parity is what's actually
# enforced, by test_handlers.py.
HandlerFunc = Callable[[Any, int], Awaitable[dict[str, object]]]


def buildHandlerRegistry(processFileDirectory: Path) -> dict[str, HandlerFunc]:
    return {
        "generateReport": handlers.generateReport,
        "calculateMetrics": handlers.calculateMetrics,
        "processFile": partial(handlers.processFile, baseDirectory=processFileDirectory),
        "sendNotification": handlers.sendNotification,
        "simulateFailure": handlers.simulateFailure,
    }


def getHandler(registry: dict[str, HandlerFunc], taskType: str) -> HandlerFunc:
    handler = registry.get(taskType)
    if handler is None:
        raise UnsupportedTaskTypeError(taskType)
    return handler
