"""Local Ed25519 signer adapter; private material never crosses the port."""

from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from locusmesh.crypto import derive_key_id, encode_base64url


class LocalEd25519Signer:
    """In-memory Ed25519 signer suitable for local fixtures and embedding."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        raw_public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._public_key = encode_base64url(raw_public_key)
        self._key_id = derive_key_id(self._public_key)

    @classmethod
    def generate(cls) -> LocalEd25519Signer:
        """Create a new local signer without exporting the private key."""

        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_bytes(cls, value: bytes) -> LocalEd25519Signer:
        """Create a signer from exactly 32 private bytes."""

        if len(value) != 32:
            raise ValueError("Ed25519 private key must contain exactly 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(value))

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def public_key(self) -> str:
        return self._public_key

    def sign(self, payload: bytes) -> str:
        return encode_base64url(self._private_key.sign(payload))
