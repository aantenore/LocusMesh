# ADR 0002: Add live fabric observation without granting route authority

- **Status:** Accepted
- **Date:** 2026-07-19
- **Applies to:** LocusMesh `0.2.0a1`

## Context

ADR 0001 deliberately separated offline route admission from inference
execution. That boundary remains correct, but operators still need a real,
replaceable way to see which nodes and models an inference fabric currently
reports before they can review candidates.

Mesh-LLM `0.73.1` exposes a local management endpoint at `/api/status`. The
payload includes node, peer, model, ownership, release, publication, and
discovery signals, but it has no schema-version field and is not bound to the
peer that will serve a later inference request. The same process exposes an
OpenAI-compatible endpoint on loopback that may route beyond the device.

Turning this status directly into `TopologySnapshot` would let a provider
enroll its own peers and apparent trust properties. Refusing all live
observation would keep the trust core safe but leave the product disconnected
from real fabrics.

## Decision

Add a read-only `FabricObserver` port and a replaceable
`MeshLlmStatusObserver` adapter. The adapter returns versioned
`FabricObservation` and `FabricCandidateObservation` values that are
structurally separate from topology and policy authority.

### Network boundary

- Accept only an HTTP(S) loopback origin with no credential, path, query, or
  fragment.
- Append the fixed `/api/status` path.
- Deny redirects.
- Bound timeout to 0.1–30 seconds and the response to 1 MiB.
- Require strict UTF-8 JSON without duplicate keys.
- Perform GET only; never invoke inference or a management mutation.

This prevents the adapter from becoming a general network scanner. Loopback
still proves only the first HTTP hop and is not locality evidence.

### Projection boundary

Project only:

- provider version;
- local and peer identifiers;
- node state;
- serving-model identifiers;
- provider-claimed owner-verification booleans;
- publication and discovery signals needed for conservative scope comparison.

Do not project the invite token, hostnames, addresses, raw owner material,
release detail, runtime paths, hardware inventory, metrics, or the raw payload.
Compute `projection_digest` only over the selected projection, so the token is
not even a digest input.

The upstream contract is labeled `mesh-llm.api-status.unversioned`. Unknown
required fields, node states, duplicate candidates/models, invalid JSON, and
oversized responses fail closed.

### Scope boundary

The caller must provide `requested_max_scope`. The adapter derives a
conservative status signal:

- `private_mesh` only when publication is private, discovery scope is
  private/LAN/local, discovery mode is mDNS/private/local, and Nostr discovery
  is disabled;
- `public_mesh` otherwise, including unknown or mixed signals;
- never `device_only` for a Mesh transport.

Scope compatibility only filters or displays candidates. It is not admission.
The observation explains the classification with
`PRIVATE_LAN_STATUS_SIGNAL` or `PUBLIC_OR_AMBIGUOUS_STATUS_SIGNAL`.

### Authority boundary

Every observation and candidate has:

- `evidence_level=observed`;
- `admission_authority=false`;
- explicit missing-policy and missing-request-binding reasons;
- a 1–60 second lifetime, five seconds by default.

There is no conversion helper from observation to `TopologySnapshot`, no
policy write path, and no call from the observer into admission. Operators must
establish peer keys, model/runtime digests, edges, validity, scope, and evidence
floors through an independent authority process.

## Consequences

### Benefits

- LocusMesh now touches a real distributed-inference fabric without pretending
  provider status is proof.
- The adapter is replaceable behind a provider-neutral port, leaving room for
  llm-d, LLMKube, InferenceX, or another fabric without changing policy logic.
- Scope mismatch becomes visible before any future invocation integration.
- Tokens and unrelated status details stay outside the portable artifact.
- Tests can exercise a real loopback HTTP exchange without running a model.

### Costs and limitations

- The status payload can lie or change incompatibly.
- Conservative classification may reject a safe private deployment when its
  discovery signals are ambiguous.
- A compatible observation still cannot reserve a route, identify the next
  serving peer, authenticate a receipt, or prove execution.
- There is no live multi-node Mesh-LLM conformance run in this slice.

## Alternatives considered

### Build the adapter directly into myMoE

Rejected. myMoE is the application control plane. Fabric observation and route
evidence remain a separate trust component below it, and myMoE must stay
fail-closed until request-bound evidence exists.

### Convert status into operator topology automatically

Rejected. It would collapse provider observation and authority, allowing the
fabric to grant itself peers, keys, edges, and scope.

### Call `/v1/models` only

Rejected as insufficient. A model catalog says less about the fabric boundary
than `/api/status` and still cannot prove route placement.

### Add reservation or inference now

Deferred. Mesh-LLM status is not request-bound. Reservation, invocation, and
post-run evidence require a separate contract and ADR rather than an HTTP
adapter improvised from operational status.

## Validation

The release must prove:

- private and public status signals compare correctly with explicit maximum
  scope;
- Mesh transport never becomes device-only;
- observations cannot validate as topology;
- provider tokens do not appear in output or projection digests;
- loopback URL, redirect, payload, collection, and time bounds fail closed;
- scope mismatch exits nonzero while returning only a non-authoritative
  observation;
- a real loopback HTTP fixture exercises the CLI adapter without invoking a
  model.

## References

- [Mesh-LLM v0.73.1](https://github.com/Mesh-LLM/mesh-llm/releases/tag/v0.73.1)
- [Mesh-LLM status payload](https://github.com/Mesh-LLM/mesh-llm/blob/v0.73.1/crates/mesh-llm-host-runtime/src/api/status.rs)
- [llm-d architecture](https://llm-d.ai/docs/0.7)
- [LMCache architecture](https://docs.lmcache.ai/developer_guide/architecture.html)
