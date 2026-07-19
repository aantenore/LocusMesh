"""Pure, fail-closed route admission policy."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from locusmesh.canonical import sha256_digest
from locusmesh.crypto import derive_key_id
from locusmesh.models import (
    AdmissionDecision,
    EvidenceLevel,
    ExecutionIntent,
    PeerManifest,
    RoutePlan,
    TopologySnapshot,
)

_SCOPE_RANK = {
    ExecutionIntent.DEVICE_ONLY: 0,
    ExecutionIntent.PRIVATE_MESH: 1,
    ExecutionIntent.PUBLIC_MESH: 2,
}
_EVIDENCE_RANK = {
    EvidenceLevel.OBSERVED: 0,
    EvidenceLevel.PEER_ASSERTED: 1,
    EvidenceLevel.HARDWARE_ATTESTED: 2,
}


class AdmissionPolicy(BaseModel):
    """Operator-owned allowlist and bounded route requirements."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.admission-policy.v1"
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    allowed_intents: frozenset[ExecutionIntent]
    max_hops: int = Field(ge=1, le=64)
    minimum_evidence: dict[ExecutionIntent, EvidenceLevel]
    topology: TopologySnapshot

    @model_validator(mode="after")
    def _complete_and_unique(self) -> AdmissionPolicy:
        if self.schema_version != self.SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {self.SCHEMA_VERSION}")
        missing = self.allowed_intents.difference(self.minimum_evidence)
        if missing:
            raise ValueError("minimum_evidence must cover every allowed intent")
        return self

    @property
    def peers_by_id(self) -> dict[str, PeerManifest]:
        """Return the policy-pinned topology keyed by peer id."""

        return {peer.peer_id: peer for peer in self.topology.peers}


def topology_digest(topology: TopologySnapshot) -> str:
    """Digest a topology independently of input ordering."""

    ordered_peers = sorted(topology.peers, key=lambda peer: peer.peer_id)
    ordered_edges = sorted(
        topology.edges,
        key=lambda edge: (edge.source_peer_id, edge.target_peer_id),
    )
    return sha256_digest(
        {
            "schema_version": topology.schema_version,
            "snapshot_id": topology.snapshot_id,
            "local_peer_id": topology.local_peer_id,
            "captured_at": topology.captured_at.isoformat(),
            "expires_at": topology.expires_at.isoformat(),
            "peers": [peer.model_dump(mode="json") for peer in ordered_peers],
            "edges": [edge.model_dump(mode="json") for edge in ordered_edges],
        }
    )


def policy_digest(policy: AdmissionPolicy) -> str:
    """Digest set-like policy fields in a process-independent order."""

    return sha256_digest(
        {
            "schema_version": policy.schema_version,
            "allowed_intents": sorted(intent.value for intent in policy.allowed_intents),
            "max_hops": policy.max_hops,
            "minimum_evidence": {
                intent.value: policy.minimum_evidence[intent].value
                for intent in sorted(policy.minimum_evidence, key=lambda item: item.value)
            },
            "topology_digest": topology_digest(policy.topology),
        }
    )


def _effective_evidence(claimed: EvidenceLevel) -> EvidenceLevel:
    if claimed is EvidenceLevel.HARDWARE_ATTESTED:
        return EvidenceLevel.PEER_ASSERTED
    return claimed


def _minimum_scope(scopes: list[ExecutionIntent]) -> ExecutionIntent | None:
    if not scopes:
        return None
    return max(scopes, key=_SCOPE_RANK.__getitem__)


def _minimum_evidence(levels: list[EvidenceLevel]) -> EvidenceLevel | None:
    if not levels:
        return None
    return min(levels, key=_EVIDENCE_RANK.__getitem__)


def admit_plan(plan: RoutePlan, policy: AdmissionPolicy, *, now: datetime) -> AdmissionDecision:
    """Evaluate a route using only explicit inputs and stable reason codes."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware verification time required")

    reasons: list[str] = []
    peers = policy.peers_by_id
    scopes: list[ExecutionIntent] = []
    evidence: list[EvidenceLevel] = []
    policy_hash = policy_digest(policy)
    topology_hash = topology_digest(policy.topology)
    required = policy.minimum_evidence.get(plan.intent)

    if plan.intent not in policy.allowed_intents:
        reasons.append("INTENT_NOT_ALLOWED")
    if now < plan.created_at:
        reasons.append("PLAN_NOT_YET_VALID")
    if now >= plan.expires_at:
        reasons.append("PLAN_EXPIRED")
    if now < policy.topology.captured_at:
        reasons.append("TOPOLOGY_NOT_YET_VALID")
    if now >= policy.topology.expires_at:
        reasons.append("TOPOLOGY_EXPIRED")
    if len(plan.hop_peer_ids) > policy.max_hops:
        reasons.append("MAX_HOPS_EXCEEDED")
    if len(plan.hop_peer_ids) != len(set(plan.hop_peer_ids)):
        reasons.append("DUPLICATE_PEER")
    if plan.intent is ExecutionIntent.DEVICE_ONLY and (
        len(plan.hop_peer_ids) != 1 or plan.hop_peer_ids[0] != policy.topology.local_peer_id
    ):
        reasons.append("DEVICE_ONLY_REQUIRES_LOCAL_SINGLE_HOP")
    allowed_edges = {(edge.source_peer_id, edge.target_peer_id) for edge in policy.topology.edges}
    for source, target in zip(plan.hop_peer_ids, plan.hop_peer_ids[1:], strict=False):
        if (source, target) not in allowed_edges:
            reasons.append(f"EDGE_NOT_ALLOWED:{source}->{target}")
    if required is EvidenceLevel.HARDWARE_ATTESTED:
        reasons.append("HARDWARE_ATTESTATION_UNSUPPORTED")

    for peer_id in plan.hop_peer_ids:
        peer = peers.get(peer_id)
        if peer is None:
            reasons.append(f"PEER_UNKNOWN:{peer_id}")
            continue
        scopes.append(peer.execution_scope)
        effective = _effective_evidence(peer.evidence_level)
        evidence.append(effective)
        if now < peer.valid_from:
            reasons.append(f"PEER_NOT_YET_VALID:{peer_id}")
        if now >= peer.expires_at:
            reasons.append(f"PEER_EXPIRED:{peer_id}")
        if _SCOPE_RANK[peer.execution_scope] > _SCOPE_RANK[plan.intent]:
            reasons.append(f"SCOPE_WIDENING:{peer_id}")
        if peer.model_digest != plan.model_digest:
            reasons.append(f"MODEL_DIGEST_MISMATCH:{peer_id}")
        if peer.runtime_digest != plan.runtime_digest:
            reasons.append(f"RUNTIME_DIGEST_MISMATCH:{peer_id}")
        try:
            bound_key_id = derive_key_id(peer.public_key)
        except ValueError:
            reasons.append(f"PEER_PUBLIC_KEY_INVALID:{peer_id}")
        else:
            if bound_key_id != peer.key_id:
                reasons.append(f"PEER_KEY_BINDING_INVALID:{peer_id}")
        if required is not None and _EVIDENCE_RANK[effective] < _EVIDENCE_RANK[required]:
            reasons.append(f"EVIDENCE_BELOW_FLOOR:{peer_id}")

    admitted = not reasons
    return AdmissionDecision(
        decision_kind="plan_admission",
        admitted=admitted,
        reason_codes=("ADMITTED",) if admitted else tuple(dict.fromkeys(reasons)),
        evaluated_at=now,
        checked_hops=len(plan.hop_peer_ids),
        route_digest=sha256_digest(plan),
        policy_digest=policy_hash,
        topology_digest=topology_hash,
        requested_intent=plan.intent,
        effective_scope=_minimum_scope(scopes),
        required_evidence=required,
        effective_evidence=_minimum_evidence(evidence),
    )
