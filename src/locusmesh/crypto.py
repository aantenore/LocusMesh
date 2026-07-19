"""Ed25519 encoding, key binding and verification helpers."""

from __future__ import annotations

import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def encode_base64url(raw: bytes) -> str:
    """Encode bytes as canonical unpadded base64url."""

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_base64url(value: str, *, expected_length: int) -> bytes:
    """Strictly decode canonical unpadded base64url with an exact size."""

    if "=" in value:
        raise ValueError("base64url padding is not allowed")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64url value") from exc
    if len(raw) != expected_length or encode_base64url(raw) != value:
        raise ValueError("non-canonical or incorrectly sized base64url value")
    return raw


def derive_key_id(public_key: str) -> str:
    """Derive the only accepted key identifier from raw Ed25519 key bytes."""

    raw = decode_base64url(public_key, expected_length=32)
    return f"ed25519:sha256:{hashlib.sha256(raw).hexdigest()}"


def verify_ed25519(public_key: str, payload: bytes, signature: str) -> bool:
    """Verify one canonical Ed25519 signature without raising on bad evidence."""

    try:
        raw_key = decode_base64url(public_key, expected_length=32)
        raw_signature = decode_base64url(signature, expected_length=64)
        Ed25519PublicKey.from_public_bytes(raw_key).verify(raw_signature, payload)
    except (InvalidSignature, ValueError):
        return False
    return True
