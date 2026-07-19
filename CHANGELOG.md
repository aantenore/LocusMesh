# Changelog

All notable changes to LocusMesh are documented here.

## 0.2.0-alpha.1

### Added

- A loopback-only, read-only Mesh-LLM `/api/status` observer with bounded
  response size, strict JSON, redirect denial, short observation lifetime, and
  explicit `private_mesh` / `public_mesh` scope comparison.
- Versioned `FabricObservation` and `FabricCandidateObservation` contracts.
  Both carry `admission_authority=false`; neither is a topology or policy
  enrollment artifact.
- CLI command `observe mesh-llm` and exit `5` when the provider scope signal
  exceeds the requested maximum.

### Trust boundary

- A Mesh transport is never inferred as `device_only`, even when its management
  endpoint uses loopback.
- Provider tokens and unselected status fields are excluded from the projection
  and its digest.
- The observer does not invoke inference, mutate policy, reserve a route, verify
  a peer key, or supply request-bound evidence.

## 0.1.0-alpha.1

### Added

- Strict, versioned contracts for locality intent, topology, route plans, receipts,
  attestations, and admission decisions.
- Fail-closed admission for `device_only`, `private_mesh`, and `public_mesh` routes.
- Ed25519 receipt-chain verification bound to request, route, policy, topology,
  peer, model, runtime, evidence, and time.
- Optional SQLite replay protection, deterministic schema export, offline CLI,
  and executable denial scenarios.
- Cross-platform Python 3.12 through 3.14 gates, dependency audit, package smoke
  test, and checksum-producing release workflow.
- Locked build backend and toolchain, immutable tag checks, and authenticated
  GitHub artifact provenance.

### Trust boundary

- Provider observations do not expand the operator-pinned allowlist.
- Peer signatures prove provenance and integrity of assertions, not correct
  computation, hardware identity, confidentiality, or physical locality.
- `hardware_attested` remains reserved and cannot satisfy a policy until a real
  verifier adapter exists.

### Security

- Runtime dependencies are locked and audited; `cryptography` is constrained to
  the patched 48.x line.
- Replay-store failures return a redacted, machine-readable failure instead of
  leaking an implementation traceback.
- Unexpected CLI exceptions return a redacted `INTERNAL_ERROR` and never carry
  admission data.
