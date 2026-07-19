from __future__ import annotations

from datetime import timedelta

from conftest import MODEL_DIGEST, NOW, RUNTIME_DIGEST, deterministic_signer, make_plan
from locusmesh.models import (
    EvidenceLevel,
    ExecutionIntent,
    PeerManifest,
    TopologyEdge,
    TopologySnapshot,
)
from locusmesh.policy import AdmissionPolicy, admit_plan, policy_digest, topology_digest


def _reasons(plan: object, policy: AdmissionPolicy) -> tuple[str, ...]:
    return admit_plan(plan, policy, now=NOW).reason_codes  # type: ignore[arg-type]


def test_allows_exact_local_and_private_routes(policy: AdmissionPolicy) -> None:
    local = make_plan()
    private = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "private-a"),
    )

    assert admit_plan(local, policy, now=NOW).admitted
    decision = admit_plan(private, policy, now=NOW)
    assert decision.admitted
    assert decision.effective_scope is ExecutionIntent.PRIVATE_MESH
    assert decision.decision_kind == "plan_admission"


def test_scope_unknown_edge_duplicate_and_max_hops_fail_closed(
    policy: AdmissionPolicy,
) -> None:
    remote_device = make_plan(hops=("private-a",))
    unknown = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "missing-peer"),
    )
    reverse = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("private-a", "device-local"),
    )
    duplicate = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "device-local"),
    )
    one_hop_policy = policy.model_copy(update={"max_hops": 1})
    private = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "private-a"),
    )

    assert "DEVICE_ONLY_REQUIRES_LOCAL_SINGLE_HOP" in _reasons(remote_device, policy)
    assert "SCOPE_WIDENING:private-a" in _reasons(remote_device, policy)
    assert "PEER_UNKNOWN:missing-peer" in _reasons(unknown, policy)
    assert any(reason.startswith("EDGE_NOT_ALLOWED:") for reason in _reasons(reverse, policy))
    assert "DUPLICATE_PEER" in _reasons(duplicate, policy)
    assert "MAX_HOPS_EXCEEDED" in _reasons(private, one_hop_policy)


def test_expiry_digest_key_and_evidence_checks(policy: AdmissionPolicy) -> None:
    plan = make_plan()
    expired = plan.model_copy(update={"expires_at": NOW})
    future = plan.model_copy(update={"created_at": NOW + timedelta(seconds=1)})
    stale_topology = policy.model_copy(
        update={
            "topology": policy.topology.model_copy(update={"expires_at": NOW}),
        }
    )
    wrong_model = plan.model_copy(update={"model_digest": MODEL_DIGEST[:-1] + "0"})
    local = policy.topology.peers[0]
    bad_key = local.model_copy(update={"key_id": "ed25519:sha256:" + "0" * 64})
    bad_key_policy = policy.model_copy(
        update={
            "topology": policy.topology.model_copy(
                update={"peers": (bad_key, *policy.topology.peers[1:])}
            )
        }
    )
    hardware_policy = policy.model_copy(
        update={
            "minimum_evidence": {
                **policy.minimum_evidence,
                ExecutionIntent.DEVICE_ONLY: EvidenceLevel.HARDWARE_ATTESTED,
            }
        }
    )

    assert "PLAN_EXPIRED" in _reasons(expired, policy)
    assert "PLAN_NOT_YET_VALID" in _reasons(future, policy)
    assert "TOPOLOGY_EXPIRED" in _reasons(plan, stale_topology)
    assert any(
        reason.startswith("MODEL_DIGEST_MISMATCH") for reason in _reasons(wrong_model, policy)
    )
    assert any(
        reason.startswith("PEER_KEY_BINDING_INVALID") for reason in _reasons(plan, bad_key_policy)
    )
    assert "HARDWARE_ATTESTATION_UNSUPPORTED" in _reasons(plan, hardware_policy)


def test_policy_and_topology_digests_ignore_set_and_snapshot_order(
    policy: AdmissionPolicy,
) -> None:
    reordered_topology = policy.topology.model_copy(
        update={
            "peers": tuple(reversed(policy.topology.peers)),
            "edges": tuple(reversed(policy.topology.edges)),
        }
    )
    reordered_policy = policy.model_copy(update={"topology": reordered_topology})

    assert topology_digest(policy.topology) == topology_digest(reordered_topology)
    assert policy_digest(policy) == policy_digest(reordered_policy)


def test_observed_topology_cannot_expand_operator_pinned_authority(
    policy: AdmissionPolicy,
) -> None:
    observed_signer = deterministic_signer("observed-only-peer")
    observed_peer = PeerManifest(
        peer_id="observed-only",
        execution_scope=ExecutionIntent.PRIVATE_MESH,
        model_digest=MODEL_DIGEST,
        runtime_digest=RUNTIME_DIGEST,
        evidence_level=EvidenceLevel.PEER_ASSERTED,
        key_id=observed_signer.key_id,
        public_key=observed_signer.public_key,
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    observed_topology = TopologySnapshot(
        snapshot_id="untrusted-provider-observation",
        local_peer_id=policy.topology.local_peer_id,
        captured_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=1),
        peers=(*policy.topology.peers, observed_peer),
        edges=(
            *policy.topology.edges,
            TopologyEdge(source_peer_id="device-local", target_peer_id="observed-only"),
        ),
    )
    plan = make_plan(
        intent=ExecutionIntent.PRIVATE_MESH,
        hops=("device-local", "observed-only"),
    )

    assert any(peer.peer_id == "observed-only" for peer in observed_topology.peers)
    decision = admit_plan(plan, policy, now=NOW)
    assert not decision.admitted
    assert "PEER_UNKNOWN:observed-only" in decision.reason_codes
    assert "EDGE_NOT_ALLOWED:device-local->observed-only" in decision.reason_codes
