"""Versioned, immutable public contracts for LocusMesh."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Commitment = Annotated[str, StringConstraints(pattern=r"^hmac-sha256:[0-9a-f]{64}$")]
PeerId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
RequestId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Nonce = Annotated[
    str,
    StringConstraints(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$"),
]
KeyId = Annotated[str, StringConstraints(pattern=r"^ed25519:sha256:[0-9a-f]{64}$")]
ProviderId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ModelId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
StateLabel = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]


class ExecutionIntent(StrEnum):
    """Maximum permitted execution locality for a route."""

    DEVICE_ONLY = "device_only"
    PRIVATE_MESH = "private_mesh"
    PUBLIC_MESH = "public_mesh"


class EvidenceLevel(StrEnum):
    """Strength of the evidence attached to one hop."""

    OBSERVED = "observed"
    PEER_ASSERTED = "peer_asserted"
    HARDWARE_ATTESTED = "hardware_attested"


_EXECUTION_SCOPE_RANK = {
    ExecutionIntent.DEVICE_ONLY: 0,
    ExecutionIntent.PRIVATE_MESH: 1,
    ExecutionIntent.PUBLIC_MESH: 2,
}


class ContractModel(BaseModel):
    """Strict base class shared by all wire contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)
    schema_version: str

    @field_validator("schema_version")
    @classmethod
    def _known_schema_version(cls, value: str) -> str:
        expected = getattr(cls, "SCHEMA_VERSION", None)
        if expected is not None and value != expected:
            raise ValueError(f"schema_version must be {expected}")
        return value


class PeerManifest(ContractModel):
    """Policy-pinned identity, locality and runtime declaration for one peer."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.peer-manifest.v1"

    schema_version: str = SCHEMA_VERSION
    peer_id: PeerId
    execution_scope: ExecutionIntent
    model_digest: Digest
    runtime_digest: Digest
    evidence_level: EvidenceLevel
    key_id: KeyId
    public_key: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    valid_from: datetime
    expires_at: datetime
    address_hint: str | None = Field(default=None, max_length=512)

    @field_validator("valid_from", "expires_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    @model_validator(mode="after")
    def _valid_interval(self) -> PeerManifest:
        if self.valid_from >= self.expires_at:
            raise ValueError("valid_from must be earlier than expires_at")
        return self


class TopologyEdge(ContractModel):
    """One directed execution edge in an operator-supplied topology snapshot."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.topology-edge.v1"

    schema_version: str = SCHEMA_VERSION
    source_peer_id: PeerId
    target_peer_id: PeerId


class TopologySnapshot(ContractModel):
    """Bounded peer/edge snapshot trusted only when operator-pinned by policy."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.topology-snapshot.v1"

    schema_version: str = SCHEMA_VERSION
    snapshot_id: RequestId
    local_peer_id: PeerId
    captured_at: datetime
    expires_at: datetime
    peers: tuple[PeerManifest, ...] = Field(min_length=1, max_length=256)
    edges: tuple[TopologyEdge, ...] = Field(default=(), max_length=1024)

    @field_validator("captured_at", "expires_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    @model_validator(mode="after")
    def _coherent_snapshot(self) -> TopologySnapshot:
        if self.captured_at >= self.expires_at:
            raise ValueError("captured_at must be earlier than expires_at")
        peer_ids = [peer.peer_id for peer in self.peers]
        if len(peer_ids) != len(set(peer_ids)):
            raise ValueError("peers must contain unique peer_id values")
        known = set(peer_ids)
        if self.local_peer_id not in known:
            raise ValueError("local_peer_id must reference a peer in the snapshot")
        edge_pairs = [(edge.source_peer_id, edge.target_peer_id) for edge in self.edges]
        if len(edge_pairs) != len(set(edge_pairs)):
            raise ValueError("edges must be unique")
        if any(source not in known or target not in known for source, target in edge_pairs):
            raise ValueError("every edge endpoint must reference a peer in the snapshot")
        return self


class FabricCandidateObservation(ContractModel):
    """One provider-reported candidate that carries no admission authority."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.fabric-candidate-observation.v1"

    schema_version: str = SCHEMA_VERSION
    provider: ProviderId
    candidate_id: PeerId
    local_node: bool
    state: StateLabel
    serving_models: tuple[ModelId, ...] = Field(default=(), max_length=256)
    provider_claimed_owner_verified: bool
    observed_scope: Literal[
        ExecutionIntent.PRIVATE_MESH,
        ExecutionIntent.PUBLIC_MESH,
    ]
    evidence_level: Literal[EvidenceLevel.OBSERVED] = EvidenceLevel.OBSERVED
    admission_authority: Literal[False] = False
    reason_codes: tuple[ReasonCode, ...] = (
        "PROVIDER_STATUS_ONLY",
        "REQUEST_BINDING_MISSING",
        "POLICY_PIN_MISSING",
    )

    @model_validator(mode="after")
    def _unique_models_and_reasons(self) -> FabricCandidateObservation:
        if len(self.serving_models) != len(set(self.serving_models)):
            raise ValueError("serving_models must be unique")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason_codes must be unique")
        required_reasons = {
            "PROVIDER_STATUS_ONLY",
            "REQUEST_BINDING_MISSING",
            "POLICY_PIN_MISSING",
        }
        if not required_reasons.issubset(self.reason_codes):
            raise ValueError("observation-only candidates require boundary reason codes")
        return self


class FabricObservation(ContractModel):
    """Bounded provider status projection, intentionally distinct from topology authority."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.fabric-observation.v1"

    schema_version: str = SCHEMA_VERSION
    provider: ProviderId
    provider_version: str = Field(min_length=1, max_length=64)
    provider_contract: str = Field(min_length=1, max_length=128)
    source_endpoint: str = Field(min_length=1, max_length=512)
    projection_digest: Digest
    observed_at: datetime
    expires_at: datetime
    requested_max_scope: ExecutionIntent
    observed_scope: Literal[
        ExecutionIntent.PRIVATE_MESH,
        ExecutionIntent.PUBLIC_MESH,
    ]
    within_requested_scope: bool
    admission_authority: Literal[False] = False
    candidates: tuple[FabricCandidateObservation, ...] = Field(min_length=1, max_length=256)
    reason_codes: tuple[ReasonCode, ...]

    @field_validator("observed_at", "expires_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    @model_validator(mode="after")
    def _coherent_observation(self) -> FabricObservation:
        if self.observed_at >= self.expires_at:
            raise ValueError("observed_at must be earlier than expires_at")
        if (self.expires_at - self.observed_at).total_seconds() > 60:
            raise ValueError("observation lifetime cannot exceed 60 seconds")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidates must contain unique candidate_id values")
        if any(candidate.provider != self.provider for candidate in self.candidates):
            raise ValueError("candidate provider must match observation provider")
        if any(candidate.observed_scope != self.observed_scope for candidate in self.candidates):
            raise ValueError("candidate scope must match the fabric observation")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason_codes must be unique")
        expected_scope_reason = (
            "SCOPE_SIGNAL_WITHIN_MAXIMUM"
            if self.within_requested_scope
            else "SCOPE_SIGNAL_EXCEEDS_MAXIMUM"
        )
        if expected_scope_reason not in self.reason_codes:
            raise ValueError("reason_codes must explain the scope comparison")
        expected_signal_reason = (
            "PRIVATE_LAN_STATUS_SIGNAL"
            if self.observed_scope is ExecutionIntent.PRIVATE_MESH
            else "PUBLIC_OR_AMBIGUOUS_STATUS_SIGNAL"
        )
        if expected_signal_reason not in self.reason_codes:
            raise ValueError("reason_codes must explain the provider scope signal")
        actual_within_scope = (
            _EXECUTION_SCOPE_RANK[self.observed_scope]
            <= _EXECUTION_SCOPE_RANK[self.requested_max_scope]
        )
        if self.within_requested_scope != actual_within_scope:
            raise ValueError("within_requested_scope must match the scope lattice")
        if "OBSERVATION_ONLY" not in self.reason_codes:
            raise ValueError("reason_codes must preserve the observation-only boundary")
        return self


class RoutePlan(ContractModel):
    """Immutable planned path and the exact request it is allowed to carry."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.route-plan.v1"

    schema_version: str = SCHEMA_VERSION
    request_id: RequestId
    nonce: Nonce
    request_commitment: Commitment
    intent: ExecutionIntent
    model_digest: Digest
    runtime_digest: Digest
    hop_peer_ids: tuple[PeerId, ...] = Field(min_length=1, max_length=64)
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    @model_validator(mode="after")
    def _valid_interval(self) -> RoutePlan:
        if self.created_at >= self.expires_at:
            raise ValueError("created_at must be earlier than expires_at")
        return self


class HopReceipt(ContractModel):
    """Peer-signed evidence for one exact position in a route."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.hop-receipt.v1"

    schema_version: str = SCHEMA_VERSION
    request_id: RequestId
    nonce: Nonce
    request_commitment: Commitment
    route_plan_digest: Digest
    policy_digest: Digest
    topology_digest: Digest
    intent: ExecutionIntent
    hop_index: int = Field(ge=0, le=63)
    hop_count: int = Field(ge=1, le=64)
    peer_id: PeerId
    previous_peer_id: PeerId | None
    next_peer_id: PeerId | None
    previous_receipt_digest: Digest | None
    model_digest: Digest
    runtime_digest: Digest
    evidence_level: EvidenceLevel
    observed_at: datetime
    key_id: KeyId
    signature_algorithm: Literal["ed25519"] = "ed25519"
    signature: str = Field(min_length=86, max_length=86, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("observed_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    def signing_payload(self) -> dict[str, Any]:
        """Return the complete signed body without the signature field."""

        return self.model_dump(mode="json", exclude={"signature"})


class RouteAttestation(ContractModel):
    """A route plan plus the ordered signed receipts that executed it."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.route-attestation.v1"

    schema_version: str = SCHEMA_VERSION
    plan: RoutePlan
    receipts: tuple[HopReceipt, ...] = Field(min_length=1, max_length=64)


class AdmissionDecision(ContractModel):
    """Stable fail-closed decision returned by admission and verification."""

    SCHEMA_VERSION: ClassVar[str] = "locusmesh.admission-decision.v1"

    schema_version: str = SCHEMA_VERSION
    decision_kind: Literal["plan_admission", "attestation_verification"]
    admitted: bool
    reason_codes: tuple[str, ...]
    evaluated_at: datetime
    checked_hops: int = Field(ge=0, le=64)
    route_digest: Digest | None = None
    attestation_digest: Digest | None = None
    policy_digest: Digest | None = None
    topology_digest: Digest | None = None
    requested_intent: ExecutionIntent | None = None
    effective_scope: ExecutionIntent | None = None
    required_evidence: EvidenceLevel | None = None
    effective_evidence: EvidenceLevel | None = None

    @field_validator("evaluated_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone-aware datetime required")
        return value

    @model_validator(mode="after")
    def _decision_is_self_consistent(self) -> AdmissionDecision:
        lineage = (self.route_digest, self.policy_digest, self.topology_digest)
        if self.admitted:
            if self.reason_codes != ("ADMITTED",):
                raise ValueError("admitted decisions must contain only ADMITTED")
            if any(value is None for value in lineage) or self.requested_intent is None:
                raise ValueError("admitted decisions require complete lineage")
            if self.decision_kind == "attestation_verification" and self.attestation_digest is None:
                raise ValueError("verified decisions require an attestation digest")
        elif not self.reason_codes or "ADMITTED" in self.reason_codes:
            raise ValueError("denied decisions require non-ADMITTED reason codes")
        if self.decision_kind == "plan_admission" and self.attestation_digest is not None:
            raise ValueError("plan admission cannot carry an attestation digest")
        return self
