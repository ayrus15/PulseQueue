"""Stable request fingerprinting for idempotency (ADR 0004).

Two submissions are "the same logical request" if their fingerprint
matches - computed from exactly the fields that matter, independent of
JSON key order or incidental whitespace, so semantically identical
requests always fingerprint identically.
"""

from __future__ import annotations

import hashlib
import json


def computeRequestFingerprint(taskType: str, payload: dict[str, object], maxAttempts: int) -> str:
    canonical = json.dumps(
        {"taskType": taskType, "payload": payload, "maxAttempts": maxAttempts},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
