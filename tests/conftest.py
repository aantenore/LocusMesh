from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from locusmesh.adapters.local_signer import LocalEd25519Signer
from locusmesh.attestation import build_attestation
from locusmesh.canonical import commit_request, sha256_digest
from locusmesh.models import (
    EvidenceLevel,
    ExecutionIntent,
    PeerManifest,
    RouteAttestation,
    RoutePlan,
    TopologyEdge,
    TopologySnapshot,
)
from locusmesh.policy import AdmissionPolicy

NOW = datetime(2030, 4, 5, 12, 0, tzinfo=UTC)
MODEL_DIGEST = sha256_digest({"model": "tests-v1"})
RUNTIME_DIGEST = sha256_digest({"runtime": "tests-v1"})
COMMITMENT_KEY = b"locusmesh-tests-commitment-key-v1-32-bytes"


def deterministic_signer(name: str) -> LocalEd25519Signer:
    return LocalEd25519Signer.from_private_bytes(hashlib.sha256(name.encode()).digest())


@pytest.fixture
def signers() -> dict[str, LocalEd25519Signer]:
    return {
        "device-local": deterministic_signer("test-device-local"),
        "private-a": deterministic_signer("test-private-a"),
        "public-a": deterministic_signer("test-public-a"),
    }


@pytest.fixture
def policy(signers: dict[str, LocalEd25519Signer]) -> AdmissionPolicy:
    def peer(peer_id: str, scope: ExecutionIntent) -> PeerManifest:
        signer = signers[peer_id]
        return PeerManifest(
            peer_id=peer_id,
            execution_scope=scope,
            model_digest=MODEL_DIGEST,
            runtime_digest=RUNTIME_DIGEST,
            evidence_level=EvidenceLevel.PEER_ASSERTED,
            key_id=signer.key_id,
            public_key=signer.public_key,
            valid_from=NOW - timedelta(hours=2),
            expires_at=NOW + timedelta(hours=2),
        )

    topology = TopologySnapshot(
        snapshot_id="tests-topology-v1",
        local_peer_id="device-local",
        captured_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        peers=(
            peer("device-local", ExecutionIntent.DEVICE_ONLY),
            peer("private-a", ExecutionIntent.PRIVATE_MESH),
            peer("public-a", ExecutionIntent.PUBLIC_MESH),
        ),
        edges=(
            TopologyEdge(source_peer_id="device-local", target_peer_id="private-a"),
            TopologyEdge(source_peer_id="private-a", target_peer_id="public-a"),
        ),
    )
    return AdmissionPolicy(
        allowed_intents=frozenset(ExecutionIntent),
        max_hops=3,
        minimum_evidence={
            ExecutionIntent.DEVICE_ONLY: EvidenceLevel.OBSERVED,
            ExecutionIntent.PRIVATE_MESH: EvidenceLevel.PEER_ASSERTED,
            ExecutionIntent.PUBLIC_MESH: EvidenceLevel.PEER_ASSERTED,
        },
        topology=topology,
    )


def make_plan(
    *,
    intent: ExecutionIntent = ExecutionIntent.DEVICE_ONLY,
    hops: tuple[str, ...] = ("device-local",),
    request_id: str = "tests-request",
    nonce: str = "tests-nonce-00001",
) -> RoutePlan:
    return RoutePlan(
        request_id=request_id,
        nonce=nonce,
        request_commitment=commit_request(
            {"request_id": request_id},
            key=COMMITMENT_KEY,
        ),
        intent=intent,
        model_digest=MODEL_DIGEST,
        runtime_digest=RUNTIME_DIGEST,
        hop_peer_ids=hops,
        created_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=5),
    )


@pytest.fixture
def device_plan() -> RoutePlan:
    return make_plan()


@pytest.fixture
def private_plan() -> RoutePlan:
    return make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "private-a"),
        request_id="tests-private-request",
        nonce="tests-private-001",
    )


@pytest.fixture
def device_attestation(
    device_plan: RoutePlan,
    policy: AdmissionPolicy,
    signers: dict[str, LocalEd25519Signer],
) -> RouteAttestation:
    return build_attestation(device_plan, policy, signers, observed_at=NOW)


@pytest.fixture
def private_attestation(
    private_plan: RoutePlan,
    policy: AdmissionPolicy,
    signers: dict[str, LocalEd25519Signer],
) -> RouteAttestation:
    return build_attestation(private_plan, policy, signers, observed_at=NOW)
