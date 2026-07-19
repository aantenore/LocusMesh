# LocusMesh `0.1` runbook

## 1. Operating boundary

LocusMesh is an offline CLI and Python library. The current commands:

- inspect a fixture topology;
- evaluate a route plan against an operator-selected policy;
- verify an existing signed route attestation;
- optionally persist nonce replay state;
- run built-in positive and negative scenarios;
- export public JSON Schemas.

They do not call an inference provider, discover a live topology, reserve a
route, or generate runtime proof. A successful decision describes the supplied
artifacts at the verification time; it is not authorization for a later
invocation.

## 2. Prerequisites

- Python 3.12 or newer;
- `uv`;
- a local source checkout or installed package;
- no network at runtime;
- no credential or secret for admission/verification.

From the repository:

```bash
uv sync --dev
uv run locusmesh --version
uv run locusmesh --json doctor
```

`doctor` should report `offline: true`, `network_required: false`, and
`secret_required: false`.

## 3. Files and permissions

### Read-only inputs

| Input | Format | Used by |
| --- | --- | --- |
| Operator policy | YAML | `admit`, `verify` |
| Route plan | JSON | `admit` |
| Route attestation | JSON | `verify` |
| Fixture topology | JSON | `probe` |

Each input is UTF-8, limited to 1 MiB, rejects duplicate keys, and must match
its versioned contract. Commands never modify these files. Mount directories
containing policies, plans, attestations, and probe topologies read-only where
practical.

### Writable outputs

| Output | Created by | Requirement |
| --- | --- | --- |
| JSON Schema directory | `schema export` | Parent or target directory must be writable. |
| SQLite replay database and side files | `verify --nonce-store` | Parent directory must be writable and access-restricted. |
| Redirected CLI result | Shell redirection | Destination directory must be writable. |

Keep output paths separate from read-only input directories. The parent of
`--out` and the parent of `--nonce-store` must be writable by the verification
process; the input directories do not need write permission.

The replay database is created lazily only after a complete valid attestation
reaches replay recording. Do not place it in an ephemeral directory when
cross-run replay detection is required.

## 4. Global CLI conventions

`--json` is a global flag and must appear before the subcommand:

```bash
uv run locusmesh --json doctor
```

Machine-readable mode emits one `locusmesh.cli-output.v1` envelope to stdout:

```json
{
  "schema_version": "locusmesh.cli-output.v1",
  "command": "admit",
  "ok": true,
  "data": {},
  "error": null
}
```

On a valid policy denial or attestation denial, `data` contains an
`AdmissionDecision`, `ok` is false, and `error` remains null. Input failures
use `error.code = "INPUT_INVALID"`; an unavailable configured replay store
uses `error.code = "STATE_UNAVAILABLE"`. An unexpected exception handled at
the CLI boundary uses `error.code = "INTERNAL_ERROR"`. All three carry
`data = null`; internal details are not emitted. Diagnostics go to stderr.

Always check the process exit code and the typed payload:

| Exit | Meaning |
| --- | --- |
| `0` | Command succeeded, or an admission/verification decision admitted. |
| `1` | Redacted internal failure; no admission was granted. |
| `2` | Invalid arguments, file, encoding, JSON/YAML, contract, or unavailable configured state. |
| `3` | Route-plan policy denial. |
| `4` | Attestation or replay denial. |

A handled internal failure returns a non-admission error envelope. A crash
outside the CLI boundary produces no valid artifact. Treat either as denial
and never fall back to a saved admission.

## 5. Inspect runtime readiness

```bash
uv run locusmesh --json doctor
```

This checks installed versions of the runtime dependencies. It does not check a
network, inference server, key service, or live mesh.

## 6. Inspect a fixture topology

```bash
uv run locusmesh --json probe \
  --topology tests/fixtures/topology.json
```

The output contains:

- snapshot and local-peer identifiers;
- peer and edge counts;
- validity against the CLI's current UTC time;
- the recomputed topology digest;
- peer IDs, declared scopes, declared evidence levels, and key IDs.

`probe` never creates or changes a policy. Its output is observation, not
authority. Admission uses only the topology embedded in the policy selected by
`--policy`.

## 7. Evaluate a route plan

```bash
uv run locusmesh --json admit \
  --policy tests/fixtures/policy.yaml \
  --plan tests/fixtures/plan.json
```

To retain the decision:

```bash
mkdir -p .local/results
uv run locusmesh --json admit \
  --policy tests/fixtures/policy.yaml \
  --plan tests/fixtures/plan.json \
  > .local/results/admission.json
```

The command checks:

- allowed intent and the scope lattice;
- `device_only` exact local single-hop rule;
- plan, topology, and peer validity windows;
- maximum hops and duplicate peers;
- directed edges;
- known peer manifests;
- model/runtime digests;
- Ed25519 public-key-to-key-ID bindings;
- policy evidence floor;
- explicit rejection of a required hardware-attested floor.

The CLI evaluates against current UTC. Use the Python API with an explicit
`now` for deterministic replay or audit.

## 8. Verify a signed attestation

Stateless verification:

```bash
uv run locusmesh --json verify \
  --policy policy.yaml \
  --attestation attestation.json
```

Verification with persistent nonce replay detection:

```bash
mkdir -p .local/state
chmod 700 .local/state
uv run locusmesh --json verify \
  --policy policy.yaml \
  --attestation attestation.json \
  --nonce-store .local/state/replay.sqlite3
```

The verifier first admits the embedded plan. If that succeeds, it checks:

- receipt count equals plan hop count;
- every receipt matches its exact peer and index;
- previous/next peers and previous-receipt digest form one chain;
- request ID, nonce, HMAC commitment, route, policy, topology, intent, model,
  and runtime bindings;
- receipt time is inside plan, topology, and peer windows, not future, and
  monotonic;
- key ID matches the policy manifest;
- direct Ed25519 signature over the complete receipt body;
- receipt evidence does not exceed the manifest and meets policy;
- optional replay nonce is new.

Run the same command twice with the same valid attestation and persistent
database to test replay behavior. The first run exits `0`; the second exits `4`
with `REPLAY_DETECTED`.

The SQLite database is a local replay domain. Multiple verifier instances must
share the same durable store, or use a future external adapter, if they must
share replay knowledge.

## 9. Run the deterministic demo

```bash
uv run locusmesh --json demo
```

The demo runs entirely in memory and covers:

- admitted single-hop device route;
- admitted two-hop private route;
- denied public peer disguised by a loopback address hint;
- denied signature tamper;
- admitted first nonce use and denied replay.

Use it as a smoke test, not as proof that a real provider integration works.

## 10. Export contract schemas

```bash
mkdir -p .local/schemas
uv run locusmesh --json schema export --out .local/schemas
```

The command writes ten sorted Pydantic JSON Schema files:

- `execution-intent.schema.json`;
- `evidence-level.schema.json`;
- `peer-manifest.schema.json`;
- `topology-edge.schema.json`;
- `topology-snapshot.schema.json`;
- `route-plan.schema.json`;
- `hop-receipt.schema.json`;
- `route-attestation.schema.json`;
- `admission-policy.schema.json`;
- `admission-decision.schema.json`.

Schema export overwrites files with those names in the selected directory. Use
a generated-artifact directory, not the policy input directory.

## 11. Python API

### Plan admission

```python
from datetime import UTC, datetime
from pathlib import Path

from locusmesh.io import load_json_model, load_yaml_model
from locusmesh.models import RoutePlan
from locusmesh.policy import AdmissionPolicy, admit_plan

policy = load_yaml_model(Path("policy.yaml"), AdmissionPolicy)
plan = load_json_model(Path("plan.json"), RoutePlan)
assert isinstance(policy, AdmissionPolicy)
assert isinstance(plan, RoutePlan)

decision = admit_plan(plan, policy, now=datetime.now(tz=UTC))
if not decision.admitted:
    raise RuntimeError(decision.reason_codes)
```

### Attestation verification with replay state

```python
from datetime import UTC, datetime
from pathlib import Path

from locusmesh.attestation import verify_attestation
from locusmesh.io import load_json_model, load_yaml_model
from locusmesh.models import RouteAttestation
from locusmesh.policy import AdmissionPolicy
from locusmesh.replay import SQLiteReplayStore

policy = load_yaml_model(Path("policy.yaml"), AdmissionPolicy)
attestation = load_json_model(Path("attestation.json"), RouteAttestation)
assert isinstance(policy, AdmissionPolicy)
assert isinstance(attestation, RouteAttestation)

with SQLiteReplayStore(Path(".local/state/replay.sqlite3")) as replay:
    decision = verify_attestation(
        attestation,
        policy,
        now=datetime.now(tz=UTC),
        replay_store=replay,
    )

if not decision.admitted:
    raise RuntimeError(decision.reason_codes)
```

Use a fixed timezone-aware `now` in tests. Do not make application behavior
depend on parsing human-readable CLI text.

## 12. Interpret decisions

`decision_kind` distinguishes:

- `plan_admission`: only the route plan was evaluated;
- `attestation_verification`: the plan and signed receipts were evaluated.

For an admitted decision, verify:

- `reason_codes == ["ADMITTED"]` in JSON;
- `route_digest`, `policy_digest`, and `topology_digest` are present;
- `attestation_digest` is also present for attestation verification;
- requested and effective scope are acceptable;
- required and effective evidence are acceptable for the caller.

Never infer hardware proof from a claimed receipt level. Current effective
hardware evidence is impossible.

For a denial, use exact `reason_codes`. Do not scrape stderr or match partial
human messages.

## 13. Common denial triage

| Reason | Likely cause | Safe action |
| --- | --- | --- |
| `DEVICE_ONLY_REQUIRES_LOCAL_SINGLE_HOP` | Route has another or additional peer. | Correct the plan or explicitly choose a wider allowed intent. |
| `SCOPE_WIDENING:<peer>` | Policy classifies a peer above requested intent. | Do not relabel based on address; review route and policy authority. |
| `EDGE_NOT_ALLOWED:<source>-><target>` | Directed edge is absent. | Review topology provenance; do not auto-add an observed edge. |
| `PEER_UNKNOWN:<peer>` | Plan references an unpinned peer. | Establish identity out of band before changing policy. |
| `PLAN_EXPIRED` / `TOPOLOGY_EXPIRED` | Artifact validity ended. | Issue a newly reviewed plan/policy; do not extend timestamps blindly. |
| `PEER_KEY_BINDING_INVALID:<peer>` | Key ID does not derive from pinned public key. | Reconcile key material through the operator authority process. |
| `HARDWARE_ATTESTATION_UNSUPPORTED` | Policy asks for an unimplemented verifier. | Keep denial; do not lower the floor silently. |
| `RECEIPT_*_MISMATCH` | Receipt does not bind the selected plan/policy/position. | Regenerate evidence from the intended inputs; do not edit signed fields. |
| `SIGNATURE_INVALID` | Signed bytes, signature, or pinned key differ. | Investigate tamper/key selection; never copy a key from untrusted evidence. |
| `RECEIPT_EVIDENCE_BELOW_FLOOR` | Receipt claim is weaker than policy. | Obtain appropriate evidence or deny. |
| `REPLAY_DETECTED` | Nonce already exists in replay domain. | Reject and investigate; do not delete state merely to retry. |
| `STATE_UNAVAILABLE` | Configured replay state cannot be opened or written. | Keep the request denied; restore the configured durable state before retrying. |

Multiple reason codes may be returned for one malformed bundle.

## 14. Verification and release checks

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

For a network-denied release exercise, install dependencies first, disconnect
network access, then run the test suite and all current CLI commands against
local fixtures.

## 15. Backup, recovery, and rotation

### Replay database

- back up and restore it as security state, not disposable cache;
- restrict filesystem ownership and permissions;
- preserve it across process restarts;
- test that recovery does not roll back accepted nonces;
- fail closed if the configured store is unavailable.

### Policy and peer keys

The current release has no online revocation or rotation service. Issue a new
reviewed policy with new validity windows and key bindings, distribute it
through deployment controls, and ensure callers select it. Receipts bound to a
different policy digest will deny.

Do not use `probe` output as an automatic key-enrollment mechanism.

## 16. Escalation boundaries

Stop and redesign before using `0.1` as a live enforcement gate if the
deployment requires:

- fresh pre-invocation route authority;
- proof that the declared route was used;
- hidden-hop detection;
- distributed replay consensus;
- online identity, revocation, or secret issuance;
- TEE evidence;
- confidentiality guarantees;
- proof of correct model execution.

Each changes the trust model and requires a new ADR, threat-model revision, and
acceptance tests.
