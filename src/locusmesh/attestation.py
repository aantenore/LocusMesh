"""Signed receipt construction and exact route verification."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from locusmesh.canonical import canonical_json_bytes, sha256_digest
from locusmesh.crypto import derive_key_id, verify_ed25519
from locusmesh.models import (
    AdmissionDecision,
    EvidenceLevel,
    HopReceipt,
    RouteAttestation,
    RoutePlan,
)
from locusmesh.policy import AdmissionPolicy, admit_plan, policy_digest, topology_digest
from locusmesh.ports import ReplayStore, SignerProvider

_EVIDENCE_RANK = {
    EvidenceLevel.OBSERVED: 0,
    EvidenceLevel.PEER_ASSERTED: 1,
    EvidenceLevel.HARDWARE_ATTESTED: 2,
}


def _effective_evidence(level: EvidenceLevel) -> EvidenceLevel:
    if level is EvidenceLevel.HARDWARE_ATTESTED:
        return EvidenceLevel.PEER_ASSERTED
    return level


def build_attestation(
    plan: RoutePlan,
    policy: AdmissionPolicy,
    signers: Mapping[str, SignerProvider],
    *,
    observed_at: datetime,
    evidence_levels: Mapping[str, EvidenceLevel] | None = None,
) -> RouteAttestation:
    """Build a deterministic signed chain for fixtures and local embedding."""

    route_hash = sha256_digest(plan)
    policy_hash = policy_digest(policy)
    topology_hash = topology_digest(policy.topology)
    manifests = policy.peers_by_id
    receipts: list[HopReceipt] = []

    for index, peer_id in enumerate(plan.hop_peer_ids):
        signer = signers[peer_id]
        manifest = manifests[peer_id]
        evidence_level = (
            evidence_levels[peer_id]
            if evidence_levels is not None and peer_id in evidence_levels
            else manifest.evidence_level
        )
        unsigned = HopReceipt(
            request_id=plan.request_id,
            nonce=plan.nonce,
            request_commitment=plan.request_commitment,
            route_plan_digest=route_hash,
            policy_digest=policy_hash,
            topology_digest=topology_hash,
            intent=plan.intent,
            hop_index=index,
            hop_count=len(plan.hop_peer_ids),
            peer_id=peer_id,
            previous_peer_id=plan.hop_peer_ids[index - 1] if index else None,
            next_peer_id=(
                plan.hop_peer_ids[index + 1] if index + 1 < len(plan.hop_peer_ids) else None
            ),
            previous_receipt_digest=sha256_digest(receipts[-1]) if receipts else None,
            model_digest=plan.model_digest,
            runtime_digest=plan.runtime_digest,
            evidence_level=evidence_level,
            observed_at=observed_at,
            key_id=signer.key_id,
            signature="A" * 86,
        )
        signature = signer.sign(canonical_json_bytes(unsigned.signing_payload()))
        receipts.append(unsigned.model_copy(update={"signature": signature}))

    return RouteAttestation(plan=plan, receipts=tuple(receipts))


def _deny(
    base: AdmissionDecision,
    reasons: list[str],
    *,
    checked_hops: int,
    attestation_digest: str,
) -> AdmissionDecision:
    return base.model_copy(
        update={
            "admitted": False,
            "decision_kind": "attestation_verification",
            "reason_codes": tuple(dict.fromkeys(reasons)),
            "checked_hops": checked_hops,
            "attestation_digest": attestation_digest,
        }
    )


def verify_attestation(
    attestation: RouteAttestation,
    policy: AdmissionPolicy,
    *,
    now: datetime,
    replay_store: ReplayStore | None = None,
) -> AdmissionDecision:
    """Verify policy, exact path, key binding, signatures and optional replay state."""

    plan = attestation.plan
    base = admit_plan(plan, policy, now=now)
    attestation_hash = sha256_digest(attestation)
    if not base.admitted:
        return base.model_copy(
            update={
                "decision_kind": "attestation_verification",
                "attestation_digest": attestation_hash,
            }
        )

    reasons: list[str] = []
    receipts = attestation.receipts
    manifests = policy.peers_by_id
    expected_route_hash = sha256_digest(plan)
    expected_policy_hash = policy_digest(policy)
    expected_topology_hash = topology_digest(policy.topology)

    if len(receipts) != len(plan.hop_peer_ids):
        reasons.append("RECEIPT_COUNT_MISMATCH")

    previous_receipt: HopReceipt | None = None
    effective_receipt_evidence: list[EvidenceLevel] = []
    for index, receipt in enumerate(receipts):
        if index >= len(plan.hop_peer_ids):
            reasons.append("EXTRA_RECEIPT")
            break

        expected_peer = plan.hop_peer_ids[index]
        expected_previous = plan.hop_peer_ids[index - 1] if index else None
        expected_next = plan.hop_peer_ids[index + 1] if index + 1 < len(plan.hop_peer_ids) else None
        expected_previous_digest = (
            sha256_digest(previous_receipt) if previous_receipt is not None else None
        )

        exact_fields = {
            "REQUEST_ID": receipt.request_id == plan.request_id,
            "NONCE": receipt.nonce == plan.nonce,
            "REQUEST_COMMITMENT": receipt.request_commitment == plan.request_commitment,
            "ROUTE_PLAN_DIGEST": receipt.route_plan_digest == expected_route_hash,
            "POLICY_DIGEST": receipt.policy_digest == expected_policy_hash,
            "TOPOLOGY_DIGEST": receipt.topology_digest == expected_topology_hash,
            "INTENT": receipt.intent == plan.intent,
            "HOP_INDEX": receipt.hop_index == index,
            "HOP_COUNT": receipt.hop_count == len(plan.hop_peer_ids),
            "PEER_ID": receipt.peer_id == expected_peer,
            "PREVIOUS_PEER": receipt.previous_peer_id == expected_previous,
            "NEXT_PEER": receipt.next_peer_id == expected_next,
            "PREVIOUS_RECEIPT_DIGEST": (
                receipt.previous_receipt_digest == expected_previous_digest
            ),
            "MODEL_DIGEST": receipt.model_digest == plan.model_digest,
            "RUNTIME_DIGEST": receipt.runtime_digest == plan.runtime_digest,
        }
        reasons.extend(
            f"RECEIPT_{field}_MISMATCH" for field, matches in exact_fields.items() if not matches
        )

        manifest = manifests.get(expected_peer)
        if manifest is None:
            reasons.append(f"PEER_UNKNOWN:{expected_peer}")
            previous_receipt = receipt
            continue

        if not (plan.created_at <= receipt.observed_at < plan.expires_at):
            reasons.append("RECEIPT_OUTSIDE_PLAN_WINDOW")
        if receipt.observed_at > now:
            reasons.append("RECEIPT_FROM_FUTURE")
        if not (policy.topology.captured_at <= receipt.observed_at < policy.topology.expires_at):
            reasons.append("RECEIPT_OUTSIDE_TOPOLOGY_WINDOW")
        if previous_receipt is not None and receipt.observed_at < previous_receipt.observed_at:
            reasons.append("RECEIPT_TIME_REVERSED")
        if not (manifest.valid_from <= receipt.observed_at < manifest.expires_at):
            reasons.append("RECEIPT_OUTSIDE_PEER_WINDOW")
        if receipt.key_id != manifest.key_id:
            reasons.append("RECEIPT_KEY_ID_MISMATCH")
        try:
            key_id = derive_key_id(manifest.public_key)
        except ValueError:
            reasons.append("PEER_PUBLIC_KEY_INVALID")
        else:
            if key_id != manifest.key_id:
                reasons.append("PEER_KEY_BINDING_INVALID")
            if not verify_ed25519(
                manifest.public_key,
                canonical_json_bytes(receipt.signing_payload()),
                receipt.signature,
            ):
                reasons.append("SIGNATURE_INVALID")

        if _EVIDENCE_RANK[receipt.evidence_level] > _EVIDENCE_RANK[manifest.evidence_level]:
            reasons.append("RECEIPT_EVIDENCE_EXCEEDS_MANIFEST")
        required = policy.minimum_evidence[plan.intent]
        effective = _effective_evidence(receipt.evidence_level)
        effective_receipt_evidence.append(effective)
        if _EVIDENCE_RANK[effective] < _EVIDENCE_RANK[required]:
            reasons.append("RECEIPT_EVIDENCE_BELOW_FLOOR")

        previous_receipt = receipt

    if reasons:
        return _deny(
            base,
            reasons,
            checked_hops=min(len(receipts), len(plan.hop_peer_ids)),
            attestation_digest=attestation_hash,
        )

    if replay_store is not None and not replay_store.record_if_new(
        plan.nonce,
        plan.request_commitment,
        attestation_hash,
    ):
        return _deny(
            base,
            ["REPLAY_DETECTED"],
            checked_hops=len(receipts),
            attestation_digest=attestation_hash,
        )
    effective = min(effective_receipt_evidence, key=_EVIDENCE_RANK.__getitem__)
    return base.model_copy(
        update={
            "decision_kind": "attestation_verification",
            "attestation_digest": attestation_hash,
            "effective_evidence": effective,
        }
    )
