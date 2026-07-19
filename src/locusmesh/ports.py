"""Provider-neutral ports used by the pure LocusMesh core."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from locusmesh.models import FabricObservation, TopologySnapshot


@runtime_checkable
class TopologyProvider(Protocol):
    """Supply a bounded topology snapshot without granting trust."""

    def snapshot(self) -> TopologySnapshot: ...


@runtime_checkable
class FabricObserver(Protocol):
    """Return a bounded provider observation that cannot grant admission."""

    def observe(self, *, now: datetime) -> FabricObservation: ...


@runtime_checkable
class SignerProvider(Protocol):
    """Sign bytes while keeping the private key behind the adapter boundary."""

    @property
    def key_id(self) -> str: ...

    @property
    def public_key(self) -> str: ...

    def sign(self, payload: bytes) -> str: ...


@runtime_checkable
class ReplayStore(Protocol):
    """Atomically remember a verified nonce and reject reuse."""

    def record_if_new(self, nonce: str, request_commitment: str, attestation_digest: str) -> bool:
        """Return true only when this nonce was absent and is now stored."""
