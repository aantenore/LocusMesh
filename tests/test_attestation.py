from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW
from locusmesh.adapters.local_signer import LocalEd25519Signer
from locusmesh.attestation import build_attestation, verify_attestation
from locusmesh.models import EvidenceLevel, RouteAttestation, RoutePlan
from locusmesh.policy import AdmissionPolicy
from locusmesh.replay import SQLiteReplayStore


def test_valid_signed_device_and_private_chains(
    device_attestation: RouteAttestation,
    private_attestation: RouteAttestation,
    policy: AdmissionPolicy,
) -> None:
    device = verify_attestation(device_attestation, policy, now=NOW)
    private = verify_attestation(private_attestation, policy, now=NOW)

    assert device.admitted and private.admitted
    assert device.decision_kind == "attestation_verification"
    assert device.attestation_digest is not None
    assert private.checked_hops == 2


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("nonce", "tampered-nonce-01", "RECEIPT_NONCE_MISMATCH"),
        ("hop_index", 1, "RECEIPT_HOP_INDEX_MISMATCH"),
        ("hop_count", 2, "RECEIPT_HOP_COUNT_MISMATCH"),
        ("peer_id", "private-a", "RECEIPT_PEER_ID_MISMATCH"),
        ("previous_peer_id", "private-a", "RECEIPT_PREVIOUS_PEER_MISMATCH"),
        ("next_peer_id", "private-a", "RECEIPT_NEXT_PEER_MISMATCH"),
        ("model_digest", "sha256:" + "1" * 64, "RECEIPT_MODEL_DIGEST_MISMATCH"),
        ("runtime_digest", "sha256:" + "2" * 64, "RECEIPT_RUNTIME_DIGEST_MISMATCH"),
        ("policy_digest", "sha256:" + "3" * 64, "RECEIPT_POLICY_DIGEST_MISMATCH"),
        ("topology_digest", "sha256:" + "4" * 64, "RECEIPT_TOPOLOGY_DIGEST_MISMATCH"),
        ("route_plan_digest", "sha256:" + "5" * 64, "RECEIPT_ROUTE_PLAN_DIGEST_MISMATCH"),
    ],
)
def test_tampered_signed_fields_are_denied(
    device_attestation: RouteAttestation,
    policy: AdmissionPolicy,
    field: str,
    value: object,
    reason: str,
) -> None:
    receipt = device_attestation.receipts[0].model_copy(update={field: value})
    tampered = device_attestation.model_copy(update={"receipts": (receipt,)})

    decision = verify_attestation(tampered, policy, now=NOW)

    assert not decision.admitted
    assert reason in decision.reason_codes
    assert "SIGNATURE_INVALID" in decision.reason_codes


def test_signature_key_and_chain_shape_tampering_is_denied(
    private_attestation: RouteAttestation,
    policy: AdmissionPolicy,
) -> None:
    first, second = private_attestation.receipts
    bad_signature = first.model_copy(update={"signature": "A" * 86})
    wrong_key = first.model_copy(update={"key_id": policy.topology.peers[1].key_id})
    wrong_previous = second.model_copy(update={"previous_receipt_digest": "sha256:" + "0" * 64})

    for receipts, expected in (
        ((bad_signature, second), "SIGNATURE_INVALID"),
        ((wrong_key, second), "RECEIPT_KEY_ID_MISMATCH"),
        ((first, wrong_previous), "RECEIPT_PREVIOUS_RECEIPT_DIGEST_MISMATCH"),
        ((second, first), "RECEIPT_PEER_ID_MISMATCH"),
        ((first,), "RECEIPT_COUNT_MISMATCH"),
        ((first, second, second), "RECEIPT_COUNT_MISMATCH"),
    ):
        attestation = private_attestation.model_copy(update={"receipts": receipts})
        decision = verify_attestation(attestation, policy, now=NOW)
        assert not decision.admitted
        assert expected in decision.reason_codes


def test_receipt_time_and_effective_evidence_come_from_verified_receipts(
    private_attestation: RouteAttestation,
    policy: AdmissionPolicy,
) -> None:
    first, second = private_attestation.receipts
    observed_first = first.model_copy(update={"evidence_level": EvidenceLevel.OBSERVED})
    observed_chain = private_attestation.model_copy(update={"receipts": (observed_first, second)})
    reversed_time = second.model_copy(update={"observed_at": NOW - timedelta(seconds=1)})
    reversed_chain = private_attestation.model_copy(update={"receipts": (first, reversed_time)})

    observed = verify_attestation(observed_chain, policy, now=NOW)
    reversed_result = verify_attestation(reversed_chain, policy, now=NOW)

    assert not observed.admitted
    assert "RECEIPT_EVIDENCE_BELOW_FLOOR" in observed.reason_codes
    assert "RECEIPT_TIME_REVERSED" in reversed_result.reason_codes


def test_verified_effective_evidence_is_recomputed_and_hardware_is_capped(
    device_plan: RoutePlan,
    policy: AdmissionPolicy,
    signers: dict[str, LocalEd25519Signer],
) -> None:
    observed_attestation = build_attestation(
        device_plan,
        policy,
        signers,
        observed_at=NOW,
        evidence_levels={"device-local": EvidenceLevel.OBSERVED},
    )
    observed = verify_attestation(observed_attestation, policy, now=NOW)
    assert observed.admitted
    assert observed.effective_evidence is EvidenceLevel.OBSERVED

    local = policy.topology.peers[0].model_copy(
        update={"evidence_level": EvidenceLevel.HARDWARE_ATTESTED}
    )
    hardware_policy = policy.model_copy(
        update={
            "topology": policy.topology.model_copy(
                update={"peers": (local, *policy.topology.peers[1:])}
            )
        }
    )
    hardware_attestation = build_attestation(
        device_plan,
        hardware_policy,
        signers,
        observed_at=NOW,
    )
    hardware = verify_attestation(hardware_attestation, hardware_policy, now=NOW)
    assert hardware.admitted
    assert hardware.effective_evidence is EvidenceLevel.PEER_ASSERTED


def test_replay_store_writes_only_after_valid_verification(
    tmp_path: Path,
    device_attestation: RouteAttestation,
    policy: AdmissionPolicy,
) -> None:
    store_path = tmp_path / "nonce.sqlite3"
    bad_receipt = device_attestation.receipts[0].model_copy(update={"signature": "A" * 86})
    invalid = device_attestation.model_copy(update={"receipts": (bad_receipt,)})

    with SQLiteReplayStore(store_path) as store:
        denied = verify_attestation(invalid, policy, now=NOW, replay_store=store)
    assert not denied.admitted
    assert not store_path.exists()

    with SQLiteReplayStore(store_path) as store:
        first = verify_attestation(device_attestation, policy, now=NOW, replay_store=store)
        second = verify_attestation(device_attestation, policy, now=NOW, replay_store=store)
    assert first.admitted
    assert second.reason_codes == ("REPLAY_DETECTED",)
    assert store_path.exists()
