# LocusMesh 0.2 Delivery Contract

## 1. Purpose

This contract defines the executable `0.2.0a1` vertical slice and its release
gates.

LocusMesh observes bounded candidate status from a loopback Mesh-LLM management
endpoint, evaluates an independently operator-pinned route plan, and verifies
direct Ed25519-signed hop receipts. It does not execute or proxy inference.

## 2. Product claim

For a configured Mesh-LLM endpoint, LocusMesh emits short-lived candidate and
scope signals that explicitly carry no admission authority. For supplied
policy, topology, route, time, and receipt artifacts, it then:

- applies an explicit `device_only`, `private_mesh`, or `public_mesh` boundary;
- fails closed on unknown, stale, widened, inconsistent, or unsupported input;
- verifies one receipt for every exact hop;
- binds the receipt chain to the request, route, policy, topology, model,
  runtime, peers, and previous receipt;
- reports a typed `plan_admission` or `attestation_verification` decision.

The result is evidence about supplied artifacts. It is not proof of correct
compute, runtime integrity, physical locality, or confidentiality.

## 3. Current components

| Component | Required behavior |
| --- | --- |
| Pydantic contracts | Strict `extra="forbid"`, frozen models, version checks, typed limits, timezone-aware dates. |
| Canonical serializer | Compact, sorted-key, UTF-8 JSON with non-finite numbers forbidden. |
| Policy engine | Pure route admission with explicit `now`. |
| Attestation verifier | Pure receipt-chain and signature verification with optional replay port. |
| Fixture adapter | Bounded local topology JSON with duplicate-key rejection. |
| Local signer | In-memory Ed25519 for fixtures and embedding. |
| Replay adapter | Optional lazy SQLite nonce store. |
| Mesh-LLM observer | Loopback-only, bounded, redirect-denying status projection with no enrollment or invocation. |
| CLI | Offline admission plus explicit live observation, JSON envelope v1, stable exit mapping. |
| Schema exporter | Deterministic Pydantic JSON Schema files. |

## 4. Explicit boundary

### Included

- `ExecutionIntent` and `EvidenceLevel` contracts;
- `FabricObservation` and `FabricCandidateObservation` contracts with
  `admission_authority=false`;
- read-only Mesh-LLM `/api/status` projection from an HTTP(S) loopback origin;
- policy-pinned topology, peer manifests, keys, model/runtime digests, and
  evidence floors;
- strict JSON and safe YAML parsing up to one MiB per input;
- keyed HMAC-SHA-256 request commitments;
- SHA-256 object digests;
- Ed25519 signatures over the current LocusMesh canonical JSON payload;
- route plan admission;
- route-attestation verification;
- optional persistent local replay detection;
- fixture probe, demo, schema export, CLI, and Python library.

### Excluded

- OpenAI-compatible proxy;
- Mesh-LLM inference, route reservation, policy enrollment, or receipt adapter;
- authoritative live topology discovery or pre-invocation admission;
- IAM, token exchange, secret management, or online revocation;
- TEE and hardware-attestation verification;
- proof of correct compute;
- confidentiality enforcement;
- provider routing or model capability selection.

DSSE, in-toto, and RFC 8785 are not used by `0.2.0a1`. They are future
interoperability candidates only.

## 5. Operator authority

`AdmissionPolicy` is the current operator-pinned policy bundle. It contains:

- allowed intents;
- maximum hops;
- minimum evidence by allowed intent;
- one `TopologySnapshot`;
- `local_peer_id`;
- directed edges;
- peer manifests with scope class, model/runtime digests, evidence level,
  key identifier, raw Ed25519 public key, and validity interval.

Provider status is not independently trusted. `FabricObservation` is a
different contract from `TopologySnapshot` and cannot be passed to admission.
The operator must establish and pin the policy separately. An observation or
receipt cannot add a peer, key, edge, scope permission, or evidence floor.

## 6. Contracts and bounds

### `PeerManifest`

- peer ID uses a constrained 1–128 character identifier;
- public key is canonical unpadded base64url for exactly 32 raw Ed25519 bytes;
- `key_id` is `ed25519:sha256:<digest of raw public key>`;
- model and runtime use `sha256:<64 lowercase hex>`;
- validity dates must be timezone-aware and ordered;
- `address_hint` is optional metadata and grants no locality.

### `TopologySnapshot`

- 1–256 unique peers;
- 0–1024 unique directed edges;
- all edge endpoints reference known peers;
- exactly one `local_peer_id` referencing a listed peer;
- timezone-aware ordered capture and expiry;
- topology digest sorts peers and edges independently of input order.

### `FabricCandidateObservation`

- identifies one provider-reported local node or peer and its serving models;
- carries the conservative fabric-level scope signal and only `observed`
  evidence;
- records provider-claimed owner verification as a claim, not a trust root;
- always carries `admission_authority=false` plus reasons for missing request,
  policy, and authoritative-route bindings.

### `FabricObservation`

- contains 1–256 unique candidates and a projection digest that excludes the
  provider invite token and unselected fields;
- records provider version while labeling `/api/status` as an unversioned
  provider contract;
- expires after a configured 1–60 second lifetime, five seconds by default;
- compares conservative observed scope with explicit `requested_max_scope`;
- never reports Mesh transport as `device_only`;
- always carries `admission_authority=false` and `OBSERVATION_ONLY`.
- explains classification as `PRIVATE_LAN_STATUS_SIGNAL` or
  `PUBLIC_OR_AMBIGUOUS_STATUS_SIGNAL`.

### `RoutePlan`

- 1–64 hops;
- nonce length 16–128 with constrained syntax;
- request commitment format `hmac-sha256:<64 lowercase hex>`;
- explicit intent, model/runtime digests, creation, and expiry;
- plan digest covers the complete Pydantic JSON representation.

### `HopReceipt`

- hop index 0–63 and hop count 1–64;
- direct `ed25519` signature in canonical unpadded base64url;
- complete binding fields listed in section 9;
- timezone-aware `observed_at`.

### `RouteAttestation`

- exact `RoutePlan` plus 1–64 ordered `HopReceipt` values.

### `AdmissionDecision`

- `decision_kind` distinguishes `plan_admission` from
  `attestation_verification`;
- admitted decisions contain only `ADMITTED`;
- denied decisions contain one or more non-admitted reason codes;
- admitted decisions require route, policy, and topology lineage;
- verified admitted decisions also require an attestation digest;
- requested/effective scope and required/effective evidence remain explicit.

## 7. Canonical bytes and digests

The current serializer is exactly:

```text
json.dumps(
  value,
  ensure_ascii=False,
  allow_nan=False,
  separators=(",", ":"),
  sort_keys=True,
).encode("utf-8")
```

This is deterministic for supported Pydantic/JSON values but is not claimed to
implement RFC 8785.

Object digests are `sha256:` plus lowercase SHA-256 hex over these bytes.
Set-like policy fields, topology peers, and topology edges are sorted before
digesting.

## 8. Request commitment

`commit_request(value, key=...)` requires at least 32 key bytes and returns:

```text
hmac-sha256:<HMAC-SHA-256 over current canonical JSON bytes>
```

Raw request content and the HMAC key are not receipt fields. A caller must not
substitute an unkeyed request hash and describe it as privacy-preserving.

## 9. Receipt signature and binding

`HopReceipt.signing_payload()` is the complete receipt body without
`signature`. `LocalEd25519Signer` signs its canonical bytes directly.

Every receipt binds:

- `request_id`, `nonce`, and `request_commitment`;
- `route_plan_digest`, `policy_digest`, and `topology_digest`;
- `intent`;
- `hop_index` and `hop_count`;
- `peer_id`, `previous_peer_id`, and `next_peer_id`;
- `previous_receipt_digest`;
- `model_digest` and `runtime_digest`;
- `evidence_level` and `observed_at`;
- `key_id` and `signature_algorithm`.

The first receipt has no previous peer or receipt digest. The final receipt has
no next peer. Each intermediate receipt must match route adjacency and the
digest of the previous complete receipt.

Public keys are taken only from the policy-pinned peer manifest. The verifier
derives and compares `key_id` before checking the signature.

## 10. Plan admission rules

`admit_plan(plan, policy, now=...)` must:

1. require timezone-aware `now`;
2. require the intent to be allowed;
3. enforce plan and topology validity windows;
4. enforce policy hop limit and unique peer IDs;
5. require `device_only` to be one hop equal to `local_peer_id`;
6. require every adjacent hop to be a directed policy edge;
7. deny a required `hardware_attested` floor as unsupported;
8. require every peer to exist and be valid;
9. deny peer scope wider than the plan intent;
10. match peer model/runtime digests to the plan;
11. derive and verify every peer key binding;
12. enforce the effective evidence floor.

The effective scope is the widest peer scope in the route. Effective evidence
is the weakest level across admitted peers. A hardware claim is capped to
effective `peer_asserted`.

## 11. Attestation verification rules

`verify_attestation` first runs plan admission. Receipt verification proceeds
only for an admissible plan.

It must then:

1. require receipt count to match route hop count;
2. compare every bound receipt field with the expected plan/policy/topology;
3. enforce exact peer order, neighbors, and previous receipt digest;
4. enforce plan, topology, manifest, current-time, and monotonic receipt time;
5. verify manifest key derivation and direct Ed25519 signature;
6. deny receipt evidence above the manifest claim;
7. apply the policy evidence floor to effective receipt evidence;
8. return `attestation_verification` with attestation digest;
9. if a replay port is supplied, record only after complete verification and
   deny an already-recorded nonce.

An attestation denial does not become a plan admission. The decision kind keeps
the two operations explicit.

## 12. Evidence semantics

| Level | Current effect |
| --- | --- |
| `observed` | Lowest policy-selectable floor. It is not authenticated locality or compute evidence. |
| `peer_asserted` | Highest level the direct peer signature can establish. It proves signer provenance and payload integrity only. |
| `hardware_attested` | Claimed values are capped to `peer_asserted`; a policy requiring this level denies as unsupported. |

The project must not describe `peer_asserted` as proof of execution,
confidentiality, model loading, or physical locality.

## 13. Replay behavior

Verification without a `ReplayStore` is stateless.

`SQLiteReplayStore`:

- creates its parent and database lazily;
- uses a nonce primary key and atomic `INSERT OR IGNORE`;
- stores nonce, request commitment, and attestation digest;
- is invoked only after all other checks pass;
- denies subsequent reuse as `REPLAY_DETECTED`.

It is a local persistence adapter, not a distributed replay service.

## 14. CLI contract

| Command | Input | Success output |
| --- | --- | --- |
| `doctor` | None | Runtime version, dependencies, offline admission/live observation split, and secret status. |
| `probe --topology FILE` | Strict bounded topology JSON | Counts, validity, digest, and content-free peer summary. |
| `observe mesh-llm --management-url URL --max-scope SCOPE` | Loopback Mesh-LLM status | `FabricObservation`; never an admission. |
| `admit --policy FILE --plan FILE` | Policy YAML and route-plan JSON | `AdmissionDecision`. |
| `verify --policy FILE --attestation FILE [--nonce-store FILE]` | Policy YAML and attestation JSON | `AdmissionDecision`. |
| `demo` | None | Device, private, scope-escape, tamper, and replay scenarios. |
| `schema export --out DIR` | Writable directory | Deterministic Pydantic JSON Schema files. |

Policy, plan, attestation, and probe-topology files are read-only inputs. Their
directories may be mounted read-only. Schema-export and replay-state paths are
separate outputs whose parent directories must be writable by the process;
output paths must not be placed inside a read-only input directory.

`--json` emits `locusmesh.cli-output.v1`. Input failures return exit `2` with
`INPUT_INVALID`; an unavailable configured replay store also returns exit `2`
with `STATE_UNAVAILABLE`. Plan denials return `3`, attestation/replay denials
`4`, a provider scope signal above `--max-scope` returns `5`, redacted internal
failures return `1` with `INTERNAL_ERROR`, and success returns `0`. Provider
transport or projection failure returns exit `2` with redacted
`OBSERVATION_UNAVAILABLE` and no observation data.

In JSON mode, an internal failure handled by the CLI produces an error envelope
with `ok=false` and `data=null`, never an `AdmissionDecision`; text mode emits
only the redacted diagnostic. A process failure outside that boundary produces
no valid artifact. Callers must treat all of these outcomes as denial and must
never reuse an earlier admission.

## 15. Acceptance matrix

| ID | Case | Expected result |
| --- | --- | --- |
| A01 | Valid single local hop under `device_only` | Plan admit |
| A02 | `device_only` with a different or additional peer | Deny `DEVICE_ONLY_REQUIRES_LOCAL_SINGLE_HOP` |
| A03 | Valid directed local-to-private route | Plan admit |
| A04 | Missing directed edge | Deny `EDGE_NOT_ALLOWED:*` |
| A05 | Public peer under `private_mesh`, including loopback address hint | Deny `SCOPE_WIDENING:*` |
| A06 | Public route without allowed `public_mesh` intent | Deny `INTENT_NOT_ALLOWED` |
| A07 | Unknown, duplicate, expired, or not-yet-valid peer | Deny with the specific peer/duplicate code |
| A08 | Stale/future topology or route | Deny with topology/plan time code |
| A09 | Model or runtime digest mismatch | Deny with digest mismatch code |
| A10 | Malformed public key or key identifier mismatch | Deny with key-binding code |
| A11 | Evidence below policy floor | Deny `EVIDENCE_BELOW_FLOOR:*` |
| A12 | Policy requires hardware attestation | Deny `HARDWARE_ATTESTATION_UNSUPPORTED` |
| A13 | Valid signed receipt for every exact hop | Attestation admit with attestation digest |
| A14 | Missing or surplus receipt | Deny receipt-count/extra-receipt code |
| A15 | Any request/route/policy/topology/intent/hop/model/runtime binding changed | Deny corresponding `RECEIPT_*_MISMATCH` |
| A16 | Previous receipt digest or neighbor changed | Deny corresponding route-chain mismatch |
| A17 | Receipt outside plan/topology/manifest window, future, or time-reversed | Deny specific receipt-time code |
| A18 | Receipt key differs or signature is altered | Deny key/signature code |
| A19 | Receipt evidence exceeds manifest or falls below floor | Deny evidence code |
| A20 | Valid nonce stored once then replayed | First admit, second deny `REPLAY_DETECTED` |
| A21 | Invalid receipt must not create replay state | Deny; later valid use of nonce can still be recorded |
| A22 | JSON/YAML duplicate key or input over one MiB | Exit `2` before policy/crypto result |
| A23 | Unknown contract field or schema version | Exit `2` |
| A24 | Same semantic policy/topology ordering | Same policy/topology digest |
| A25 | Admission decision claims success without complete lineage | Pydantic validation rejects it |
| A26 | Schema export repeated to separate directories | Byte-identical schema files |
| A27 | CLI executed without network | Offline admission, verification, fixture, demo, and schema commands remain functional |
| A28 | A probed topology injects a peer, edge, scope class, or key absent from or different to the selected policy | Probe remains descriptive; admission and verification ignore probe output, preserve policy authority, and deny any route not admitted by that policy |
| A29 | Configured replay store cannot be opened or used | Exit `2` with redacted `STATE_UNAVAILABLE`; no admission artifact |
| A30 | An unexpected internal exception crosses the command implementation boundary | Exit `1` with redacted `INTERNAL_ERROR`, `ok=false`, and `data=null` |
| A31 | Private LAN status observed under `private_mesh` maximum | Observation succeeds with `observed_scope=private_mesh` and `admission_authority=false` |
| A32 | Public/discovery status observed under `private_mesh` maximum | Exit `5`, retain observation with `SCOPE_SIGNAL_EXCEEDS_MAXIMUM`, grant no admission |
| A33 | Any Mesh status observed under `device_only` maximum | Exit `5`; Mesh transport is never classified as device-only |
| A34 | Non-loopback management URL, embedded credential, query, fragment, or path | Exit `2` before network access |
| A35 | Redirect, unavailable endpoint, malformed/duplicate JSON, unknown node state, or response over one MiB | Exit `2` with redacted `OBSERVATION_UNAVAILABLE` and no data |
| A36 | Provider invite token changes | Secret is absent from output and does not change projection digest |
| A37 | Observation is parsed as `TopologySnapshot` | Contract validation rejects it |
| A38 | Duplicate peer IDs or model IDs | Observation rejects the provider payload |
| A39 | Observation lifetime is missing, naive, zero, or above the configured bound | Construction/configuration rejects it |
| A40 | Real loopback HTTP fixture serves supported Mesh-LLM status | CLI acquires and projects the status without invoking inference |

## 16. Release gates

Before release:

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv export --locked --all-groups --no-emit-project --no-hashes \
  --output-file /tmp/locusmesh-audit-requirements.txt
uv run pip-audit --strict \
  --requirement /tmp/locusmesh-audit-requirements.txt
uv build --no-build-isolation
uv run locusmesh --json doctor
uv run locusmesh --json demo
```

Tests must cover positive routes, every fail-closed boundary in the acceptance
matrix, strict input parsing, deterministic digests/schema export, CLI exit
codes/envelopes, tamper, and replay.

Passing these gates establishes only bounded candidate observation plus offline
artifact admission and verification. It does not establish live route
authority or correct inference.
