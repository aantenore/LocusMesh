"""JSON Schema export for public contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from locusmesh.models import (
    AdmissionDecision,
    EvidenceLevel,
    ExecutionIntent,
    FabricCandidateObservation,
    FabricObservation,
    HopReceipt,
    PeerManifest,
    RouteAttestation,
    RoutePlan,
    TopologyEdge,
    TopologySnapshot,
)
from locusmesh.policy import AdmissionPolicy

_SCHEMAS: dict[str, Any] = {
    "execution-intent": ExecutionIntent,
    "evidence-level": EvidenceLevel,
    "fabric-candidate-observation": FabricCandidateObservation,
    "fabric-observation": FabricObservation,
    "peer-manifest": PeerManifest,
    "topology-edge": TopologyEdge,
    "topology-snapshot": TopologySnapshot,
    "route-plan": RoutePlan,
    "hop-receipt": HopReceipt,
    "route-attestation": RouteAttestation,
    "admission-policy": AdmissionPolicy,
    "admission-decision": AdmissionDecision,
}


def export_schemas(output_dir: Path) -> tuple[Path, ...]:
    """Write deterministic JSON Schema files and return their paths."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, contract in _SCHEMAS.items():
        path = output_dir / f"{name}.schema.json"
        schema = TypeAdapter(contract).json_schema()
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return tuple(written)
