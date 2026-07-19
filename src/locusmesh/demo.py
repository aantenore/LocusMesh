"""Deterministic offline scenarios used by the CLI demo and tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from locusmesh.adapters.local_signer import LocalEd25519Signer
from locusmesh.attestation import build_attestation, verify_attestation
from locusmesh.canonical import commit_request, sha256_digest
from locusmesh.models import (
    EvidenceLevel,
    ExecutionIntent,
    PeerManifest,
    RoutePlan,
    TopologyEdge,
    TopologySnapshot,
)
from locusmesh.policy import AdmissionPolicy, admit_plan
from locusmesh.replay import SQLiteReplayStore

_DEMO_TIME = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
_COMMITMENT_KEY = b"locusmesh-demo-commitment-key-v1-32-bytes"


def _signer(name: str) -> LocalEd25519Signer:
    return LocalEd25519Signer.from_private_bytes(hashlib.sha256(name.encode()).digest())


def _manifest(
    peer_id: str,
    scope: ExecutionIntent,
    signer: LocalEd25519Signer,
    *,
    address_hint: str | None = None,
) -> PeerManifest:
    return PeerManifest(
        peer_id=peer_id,
        execution_scope=scope,
        model_digest=sha256_digest({"model": "demo-model-v1"}),
        runtime_digest=sha256_digest({"runtime": "demo-runtime-v1"}),
        evidence_level=EvidenceLevel.PEER_ASSERTED,
        key_id=signer.key_id,
        public_key=signer.public_key,
        valid_from=_DEMO_TIME - timedelta(days=1),
        expires_at=_DEMO_TIME + timedelta(days=1),
        address_hint=address_hint,
    )


def _plan(
    request_id: str,
    nonce: str,
    intent: ExecutionIntent,
    hops: tuple[str, ...],
) -> RoutePlan:
    return RoutePlan(
        request_id=request_id,
        nonce=nonce,
        request_commitment=commit_request(
            {"operation": "classify", "request_id": request_id},
            key=_COMMITMENT_KEY,
        ),
        intent=intent,
        model_digest=sha256_digest({"model": "demo-model-v1"}),
        runtime_digest=sha256_digest({"runtime": "demo-runtime-v1"}),
        hop_peer_ids=hops,
        created_at=_DEMO_TIME - timedelta(minutes=5),
        expires_at=_DEMO_TIME + timedelta(minutes=5),
    )


def run_demo() -> dict[str, Any]:
    """Run positive, scope-escape, tamper and replay cases entirely offline."""

    local_signer = _signer("device-local")
    private_signer = _signer("private-peer")
    loopback_signer = _signer("loopback-public-peer")
    signers = {
        "device-local": local_signer,
        "private-peer": private_signer,
        "loopback-public": loopback_signer,
    }
    topology = TopologySnapshot(
        snapshot_id="demo-topology-v1",
        local_peer_id="device-local",
        captured_at=_DEMO_TIME - timedelta(hours=1),
        expires_at=_DEMO_TIME + timedelta(hours=1),
        peers=(
            _manifest("device-local", ExecutionIntent.DEVICE_ONLY, local_signer),
            _manifest("private-peer", ExecutionIntent.PRIVATE_MESH, private_signer),
            _manifest(
                "loopback-public",
                ExecutionIntent.PUBLIC_MESH,
                loopback_signer,
                address_hint="http://127.0.0.1:8080",
            ),
        ),
        edges=(
            TopologyEdge(source_peer_id="device-local", target_peer_id="private-peer"),
            TopologyEdge(source_peer_id="device-local", target_peer_id="loopback-public"),
        ),
    )
    policy = AdmissionPolicy(
        allowed_intents=frozenset({ExecutionIntent.DEVICE_ONLY, ExecutionIntent.PRIVATE_MESH}),
        max_hops=3,
        minimum_evidence={
            ExecutionIntent.DEVICE_ONLY: EvidenceLevel.OBSERVED,
            ExecutionIntent.PRIVATE_MESH: EvidenceLevel.PEER_ASSERTED,
        },
        topology=topology,
    )

    device_plan = _plan(
        "demo-device",
        "nonce-device-0001",
        ExecutionIntent.DEVICE_ONLY,
        ("device-local",),
    )
    private_plan = _plan(
        "demo-private",
        "nonce-private-001",
        ExecutionIntent.PRIVATE_MESH,
        ("device-local", "private-peer"),
    )
    escape_plan = _plan(
        "demo-loopback-escape",
        "nonce-loopback-01",
        ExecutionIntent.DEVICE_ONLY,
        ("loopback-public",),
    )
    device_attestation = build_attestation(
        device_plan,
        policy,
        signers,
        observed_at=_DEMO_TIME,
    )
    private_attestation = build_attestation(
        private_plan,
        policy,
        signers,
        observed_at=_DEMO_TIME,
    )
    device_result = verify_attestation(device_attestation, policy, now=_DEMO_TIME)
    private_result = verify_attestation(private_attestation, policy, now=_DEMO_TIME)
    escape_result = admit_plan(escape_plan, policy, now=_DEMO_TIME)

    first_receipt = device_attestation.receipts[0]
    replacement = "A" if not first_receipt.signature.startswith("A") else "B"
    tampered_receipt = first_receipt.model_copy(
        update={"signature": replacement + first_receipt.signature[1:]}
    )
    tampered = device_attestation.model_copy(update={"receipts": (tampered_receipt,)})
    tampered_result = verify_attestation(tampered, policy, now=_DEMO_TIME)

    with SQLiteReplayStore(":memory:") as replay_store:
        first_replay_result = verify_attestation(
            device_attestation,
            policy,
            now=_DEMO_TIME,
            replay_store=replay_store,
        )
        second_replay_result = verify_attestation(
            device_attestation,
            policy,
            now=_DEMO_TIME,
            replay_store=replay_store,
        )

    def serialized(value: Any) -> Any:
        return value.model_dump(mode="json")

    return {
        "device-local": serialized(device_result),
        "private-mesh": serialized(private_result),
        "loopback-escape": serialized(escape_result),
        "tampered": serialized(tampered_result),
        "replay": {
            "first": serialized(first_replay_result),
            "second": serialized(second_replay_result),
        },
    }
