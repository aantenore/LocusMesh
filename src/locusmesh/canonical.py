"""Canonical serialization and digest helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from pydantic import BaseModel

from locusmesh.models import Commitment, Digest


def canonical_json_bytes(value: BaseModel | Any) -> bytes:
    """Serialize a model or JSON-compatible value deterministically."""

    serializable = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        serializable,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_digest(value: BaseModel | Any) -> Digest:
    """Return a typed digest over canonical JSON."""

    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def commit_request(value: Any, *, key: bytes) -> Commitment:
    """Create a caller-keyed commitment resistant to low-entropy guessing."""

    if len(key) < 32:
        raise ValueError("commitment key must contain at least 32 bytes")
    digest = hmac.new(key, canonical_json_bytes(value), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"
