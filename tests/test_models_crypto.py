from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import MODEL_DIGEST, RUNTIME_DIGEST, deterministic_signer
from locusmesh import __version__
from locusmesh.adapters.local_signer import LocalEd25519Signer
from locusmesh.canonical import canonical_json_bytes, commit_request
from locusmesh.crypto import decode_base64url, derive_key_id, verify_ed25519
from locusmesh.models import AdmissionDecision, ExecutionIntent, RoutePlan


def test_package_and_runtime_versions_match() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())

    assert __version__ == project["project"]["version"]


def test_canonical_json_and_hmac_commitment_are_deterministic() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    key = b"a" * 32
    assert commit_request({"a": 1}, key=key) == commit_request({"a": 1}, key=key)
    with pytest.raises(ValueError, match="at least 32"):
        commit_request({"a": 1}, key=b"short")


def test_ed25519_key_binding_and_strict_base64url() -> None:
    signer = deterministic_signer("crypto")
    payload = b"canonical payload"
    signature = signer.sign(payload)

    assert derive_key_id(signer.public_key) == signer.key_id
    assert verify_ed25519(signer.public_key, payload, signature)
    assert not verify_ed25519(signer.public_key, payload + b"!", signature)
    with pytest.raises(ValueError):
        decode_base64url(signer.public_key + "=", expected_length=32)
    with pytest.raises(ValueError):
        LocalEd25519Signer.from_private_bytes(b"short")
    assert isinstance(LocalEd25519Signer.generate().key_id, str)


def test_contracts_reject_unknown_schema_and_naive_time() -> None:
    with pytest.raises(ValidationError):
        RoutePlan(
            schema_version="unknown",
            request_id="request",
            nonce="contract-nonce-01",
            request_commitment="hmac-sha256:" + "0" * 64,
            intent=ExecutionIntent.DEVICE_ONLY,
            model_digest=MODEL_DIGEST,
            runtime_digest=RUNTIME_DIGEST,
            hop_peer_ids=("device-local",),
            created_at=datetime(2030, 1, 1),
            expires_at=datetime(2030, 1, 2),
        )


def test_decision_cannot_claim_admission_without_lineage() -> None:
    with pytest.raises(ValidationError, match="complete lineage"):
        AdmissionDecision(
            decision_kind="plan_admission",
            admitted=True,
            reason_codes=("ADMITTED",),
            evaluated_at=datetime(2030, 1, 1, tzinfo=UTC),
            checked_hops=1,
        )
