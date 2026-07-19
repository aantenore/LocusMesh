# LocusMesh market and technology scan

- **Research date:** 2026-07-19
- **Question:** Is a separate project justified, and what is the smallest
  non-duplicative product boundary?
- **Source rule:** Prefer project repositories, specifications, official
  documentation, model cards, and original research.

## Executive conclusion

The reviewed landscape already contains credible projects for:

- coding-agent orchestration;
- premium-to-local task offload;
- model difficulty, cost, and performance routing;
- distributed inference;
- context graphs and document retrieval;
- skill optimization;
- agent discovery;
- identity, policy, and secret lifecycle.

Combining all of those into another general AI gateway would duplicate mature
work and create an incoherent trust boundary.

The narrower gap is an independent **execution-scope admission and signed route
evidence boundary** for distributed inference:

- explicit `device_only`, `private_mesh`, and `public_mesh` intent;
- operator-selected topology, peers, keys, and policy;
- one cryptographically bound receipt per declared hop;
- honest `observed`, `peer_asserted`, and `hardware_attested` semantics;
- content-free, deterministic decision lineage.

LocusMesh `0.2.0a1` adds a bounded, read-only Mesh-LLM status observer to the
offline CLI/API trust core. The observation cannot grant admission and the
project does not claim fresh runtime enforcement.

## Method

Each project was evaluated against four questions:

1. What problem does its primary material say it solves?
2. Which trust or product boundary does it own?
3. Would a new implementation merely repeat that boundary?
4. What function remains necessary between an application control plane and a
   distributed inference fabric?

Repository popularity and producer-reported benchmarks are signals, not
independent validation. This is a time-bounded technical scan, not a patent,
commercial-product, or exhaustive academic review.

## 1. Agent harnesses are not the opportunity

### oh-my-opencode

[oh-my-opencode](https://github.com/opensoft/oh-my-opencode) provides an
opinionated coding-agent environment with specialized agents, model
configuration, background work, context management, hooks, and developer
tooling.

**Direction:** coding assistants are becoming configurable orchestration
environments rather than single chat loops.

**Decision:** do not build another agent harness. LocusMesh stays below the
harness and exposes a small admission/verification contract.

### Vercel EVE

[EVE](https://vercel.com/blog/introducing-eve) presents an open framework for
production agents around durable execution, filesystem-oriented work, skills,
subagents, schedules, sandboxes, channels, and human approval.

**Direction:** lifecycle, durability, and orchestration primitives are
consolidating in general agent runtimes.

**Decision:** no scheduling, task graph, sandbox, approval, or subagent
orchestration belongs in LocusMesh.

## 2. Difficulty and cost routing are active categories

### Houtini LM

[Houtini LM](https://github.com/houtini-ai/lm) delegates bounded assistant work
to local or cloud OpenAI-compatible models and profiles model/runtime behavior.

**Direction:** using a premium orchestrator only where needed is already an
active product pattern.

**Decision:** LocusMesh does not choose a model or decide which task deserves a
paid endpoint.

### LLMRouter, RouteLLM, and vLLM Semantic Router

- [LLMRouter](https://github.com/ulab-uiuc/LLMRouter) collects learned and
  heuristic model-routing approaches and evaluation support.
- [RouteLLM](https://github.com/lm-sys/RouteLLM) focuses on routing between
  stronger and weaker models and measuring the quality/cost trade-off.
- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router)
  addresses routing across heterogeneous models and deployment preferences.

**Direction:** query complexity, quality, latency, and cost are becoming
explicit routing inputs.

**Decision:** accept an already selected route; do not learn or optimize one.
Model-routing quality can be a caller concern without entering the trust core.

## 3. Distributed inference exposes the relevant gap

### Mesh-LLM

[Mesh-LLM](https://github.com/Mesh-LLM/mesh-llm) is a distributed inference
fabric with an OpenAI-compatible surface and modes that can involve a single
machine, peers, split layers or experts, and public participation.

**Direction:** the endpoint visible to an application and the compute path
behind it are increasingly different things. A loopback transport can be only
the first hop.

**Gap:** the consumer still needs its own vocabulary for the maximum permitted
execution boundary and evidence about the exact declared route. Provider
status cannot safely choose its own trust roots and approve itself.

**Decision:** a distributed-inference system is an observation/execution
adapter, not a dependency or authority. `0.2` implements only the read-only
observation half: a short-lived, loopback status projection that is a different
contract from operator topology and cannot enable live mesh admission.

### llm-d and LMCache

[llm-d](https://llm-d.ai/) is a composable inference-serving stack whose router
separates endpoint discovery, scoring, and the data-plane proxy. It supports
prefix-cache-aware routing, disaggregated prefill/decode, flow control, and
heterogeneous accelerators. [LMCache](https://docs.lmcache.ai/developer_guide/architecture.html)
is a vendor-neutral KV-cache layer spanning GPU, CPU, local, and remote storage
and transport modes.

**Direction:** distributed inference is decomposing into reusable discovery,
routing, execution, and cache layers rather than converging on one application
control plane.

**Decision:** do not reproduce endpoint scoring, scheduling, serving, or cache
movement in LocusMesh. Future adapters may observe those fabrics, but admission
continues to require independent policy and request-bound evidence.

### PlanetServe

The original [PlanetServe NSDI 2026
publication](https://www.usenix.org/conference/nsdi26/presentation/fang)
studies decentralized LLM serving and treats overlay organization,
communication privacy, forwarding efficiency, and serving-quality verification
as substantive research problems.

**Direction:** decentralization does not automatically supply privacy or
verifiable execution.

**Decision:** LocusMesh limits its claim to policy admission and authenticated
peer statements. It does not claim communication privacy, serving-quality
proof, or correct compute.

## 4. Local model artifacts should remain replaceable

The supplied [Gemma coder GGUF model
card](https://huggingface.co/yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF)
describes a quantized local coding model, runtime expectations, and
producer-reported evaluations.

**Direction:** specialized local models are increasingly deployable behind
common inference interfaces.

**Decision:** do not hardcode a model family. LocusMesh binds an exact
operator-selected model digest and runtime digest, but does not infer
capability, safety, or correctness from a model card.

## 5. Context systems are becoming specialized

### ktx

[ktx](https://github.com/Kaelio/ktx-ai-data-agents-mcp-context-skills)
organizes enterprise data-agent context across databases, BI, documentation,
and related metadata.

### Graphify

[Graphify](https://graphify.net/) builds knowledge graphs from code,
documents, papers, and diagrams for coding assistants.

### PageIndex

[PageIndex](https://github.com/VectifyAI/PageIndex) uses hierarchical document
structures and reasoning-based retrieval instead of treating every source as
an undifferentiated vector collection.

**Direction:** context infrastructure is fragmenting into domain-specific
graphs, trees, skills, and provenance-aware representations.

**Decision:** do not add ingestion, graph construction, retrieval, prompt
assembly, intent normalization, or token compression to LocusMesh. Those are
valuable separate context-plane concerns; mixing them with route authority
would weaken both products.

## 6. Skill optimization is becoming measurable

[SkillOpt](https://github.com/microsoft/SkillOpt) treats compact agent skills as
artifacts that can be improved from trajectories and evaluated before
acceptance.

**Direction:** skills are becoming versioned, portable optimization artifacts,
not only prompt snippets.

**Decision:** no skill generation or optimization belongs in the route
verifier. A future skill may call LocusMesh, but skill quality is unrelated to
execution-scope evidence.

## 7. Identity and secrets already have mature primitives

### Keycloak

[Keycloak Authorization
Services](https://www.keycloak.org/docs/latest/authorization_services/index.html)
provides centralized policy administration, decision, and enforcement
concepts. [Keycloak DPoP
documentation](https://www.keycloak.org/securing-apps/dpop) covers
sender-constrained tokens.

### OpenBao

[OpenBao Agent](https://openbao.org/docs/agent-and-proxy/agent/) provides
auto-authentication, renewal, templating, proxying, caching, and
process-oriented secret delivery.

**Direction:** workload identity and secret lifecycle should be integrated
through established systems.

**Decision:** do not create another IAM or secret daemon. The current policy
contains static public verification keys only. Future identity, revocation, or
remote signing belongs behind explicit ports after a separate threat-model
revision.

## 8. Agent capability discovery overlaps only at the taxonomy edge

[OASF](https://github.com/agntcy/oasf) defines an open schema framework for
describing agent domains, skills, and capabilities.

**Direction:** agent records and capability taxonomies are moving toward
shared schemas.

**Decision:** do not invent a competing capability registry. LocusMesh's
contract is per-route execution scope and receipt verification, not discovery.
Compatible identifiers can be adopted later without making a registry part of
the verifier.

## 9. Evidence standards are future interoperability options

- [in-toto Attestation
  Framework](https://github.com/in-toto/attestation) defines extensible
  statement and predicate conventions.
- [DSSE](https://github.com/secure-systems-lab/dsse) defines a signed envelope
  and pre-authentication encoding.
- [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) defines a JSON
  canonicalization scheme.

**Direction:** interoperable evidence should prefer precise existing
specifications over vaguely compatible proprietary claims.

**Current decision:** `0.2.0a1` does **not** implement these standards. It uses
direct Ed25519 signatures over a compact sorted-key JSON Pydantic payload.
in-toto/DSSE and RFC 8785 are candidates for a separately versioned future
profile only after conformance vectors and migration semantics exist.

## Gap assessment

| Candidate project | Saturation | Boundary fit | Decision |
| --- | --- | --- | --- |
| General coding-agent harness | High | Duplicates established runtimes | Reject |
| Premium/local assistant offload | High and growing | Model/task routing, not route trust | Reject |
| Difficulty/cost/performance model router | High and growing | Complementary caller concern | Reject |
| Distributed inference engine | Active | Provider layer, not independent admission | Reuse through future adapter |
| Local model catalog or benchmark | High | Capability plane, not trust plane | Reject |
| Generic context graph/retriever | High | Separate context plane | Reject |
| Intent normalization/token compression | Active | Separate context efficiency product | Keep separate |
| Skill optimizer | Active | Separate optimization loop | Reject |
| Generic agent capability registry | Medium-high | Shared taxonomy already emerging | Reuse |
| IAM or secret broker | High and mature | Infrastructure adapter concern | Reuse |
| Execution-scope admission plus exact signed hop lineage | Low in reviewed set | Narrow, complementary trust boundary | Select |

## Selected product boundary

LocusMesh is:

- a local-first Python library and CLI with an offline trust core;
- policy- and schema-first;
- provider-neutral;
- content-free;
- fail-closed for supplied artifacts;
- explicit about the difference between a peer assertion and proof.

LocusMesh is not:

- an inference server;
- a model or task router;
- a live proxy in `0.2`;
- an agent runtime;
- a context engine;
- an intent normalizer;
- a token compressor;
- an IAM or secret platform;
- a benchmark;
- a TEE verifier;
- proof of confidential or correct compute.

## Why a separate repository is justified

The component belongs between application/control-plane policy and
provider-specific inference fabrics. Keeping it separate:

- prevents one inference provider from defining the portable trust contract;
- allows multiple callers and future adapters;
- keeps routing quality independent from route admissibility;
- makes negative, tamper, and replay behavior testable without a model runtime;
- avoids accumulating context, identity, orchestration, and inference
  responsibilities in one project.

The repository remains justified only while the boundary stays narrow. A
generic "AI gateway" expansion would erase the differentiation found in this
scan.

## Defensible current novelty statement

The reviewed sources did not expose the same narrow combination of:

1. an explicit distributed-inference execution-scope lattice;
2. operator-selected topology and peer-key authority;
3. exact one-receipt-per-declared-hop verification;
4. bindings across request commitment, route, policy, topology, model,
   runtime, adjacency, and previous receipt;
5. claimed-versus-effective evidence semantics;
6. a deterministic, provider-neutral offline decision;
7. a typed, non-authoritative live fabric observation that cannot auto-enroll
   provider status.

This is a positioning hypothesis, not proof of worldwide novelty. It must be
rechecked before a public novelty, patent, or security claim.

## Roadmap implications

The scan supports this sequence:

1. harden and publish the offline contract with negative vectors;
2. validate portability with a second-language verifier or formal conformance
   fixtures;
3. validate the read-only Mesh-LLM observer against a real multi-node lab;
4. specify fresh route reservation before any live enforcement claim;
5. integrate established identity/revocation systems through ports;
6. evaluate a standard attestation profile separately;
7. add hardware evidence only with a real verifier and revised threat model.

It does not support merging model routing, context optimization, skill
optimization, or secret management into the core.

## Research limitations

- The scan is time-bounded and not exhaustive.
- Source documentation can change after the research date.
- Producer security and performance claims were not independently reproduced.
- Absence of an exact equivalent in reviewed sources does not prove that none
  exists.
- Candidate observation is proven against the supported HTTP projection; live
  route feasibility remains unproven until a multi-node request-bound test exists.
- The current market conclusion should be refreshed before major investment or
  public differentiation claims.

## Primary source index

- [oh-my-opencode](https://github.com/opensoft/oh-my-opencode)
- [Vercel EVE](https://vercel.com/blog/introducing-eve)
- [Houtini LM](https://github.com/houtini-ai/lm)
- [LLMRouter](https://github.com/ulab-uiuc/LLMRouter)
- [RouteLLM](https://github.com/lm-sys/RouteLLM)
- [vLLM Semantic Router](https://github.com/vllm-project/semantic-router)
- [Mesh-LLM](https://github.com/Mesh-LLM/mesh-llm)
- [llm-d](https://llm-d.ai/)
- [LMCache architecture](https://docs.lmcache.ai/developer_guide/architecture.html)
- [PlanetServe](https://www.usenix.org/conference/nsdi26/presentation/fang)
- [Gemma coder GGUF model card](https://huggingface.co/yuxinlu1/gemma-4-12B-coder-fable5-composer2.5-v1-GGUF)
- [ktx](https://github.com/Kaelio/ktx-ai-data-agents-mcp-context-skills)
- [Graphify](https://graphify.net/)
- [PageIndex](https://github.com/VectifyAI/PageIndex)
- [SkillOpt](https://github.com/microsoft/SkillOpt)
- [Keycloak Authorization Services](https://www.keycloak.org/docs/latest/authorization_services/index.html)
- [Keycloak DPoP](https://www.keycloak.org/securing-apps/dpop)
- [OpenBao Agent](https://openbao.org/docs/agent-and-proxy/agent/)
- [OASF](https://github.com/agntcy/oasf)
- [in-toto Attestation Framework](https://github.com/in-toto/attestation)
- [DSSE](https://github.com/secure-systems-lab/dsse)
- [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)
