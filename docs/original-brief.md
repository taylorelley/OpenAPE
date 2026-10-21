# Neural Personality Engine (NPE)
## v1.0 Implementation Brief for Coding Agent

**Status:** Build specification, 22 October 2026  
**Deliverable:** Standalone, self-hostable open-source neural personality engine with a public adapter protocol and working integrations for Pi, Hermes Agent, Claude Code, OpenCogni and OpenClaw.  
**Working protocol name:** UPAP (Universal Personality Adapter Protocol), `upap/1`. This is a provisional name, not a claim of an established standard.

## 0. Instructions to the coding agent

Build a working end-to-end product, not a diagram, shell, mocked product or collection of placeholder integrations. Implement in independently testable work packages. Keep the core engine decoupled from all harnesses. Preserve host permissions and task-level instructions. Run tests and provide reproducible evidence after each milestone. Never describe a synthetic demonstration as proof of a learned personality or a fixture as a live-model test.

Before modifying any host integration, inspect its current official documentation and source at the version being tested. Record exact pinned versions, links, supported hooks, and known limits. Do not assume an interface works merely because an older example or an issue mentions it. For OpenCogni, inspect the current `main` branch before changes; this brief references its existing Cordis services, planner adapters, and evaluator, but its architecture may have evolved. Implement the standalone engine in its own repository. Keep OpenCogni modifications in a separately reviewable change.

Write a short ADR for architecture choices that change the public protocol, state format, learning logic, or security model. Avoid expanding scope without test evidence. Do not weaken a host's system instructions, tool authorisation, or safety mechanisms for personality integration.

## 1. Product definition and measurable goal

The engine gives an AI agent a **persistent, learned behavioural identity** stored as trainable neural state, independent of its underlying model, harness and session. The agent may use OpenAI, Anthropic, Gemini, Qwen or another API/open-weight model without retraining that model. A host-specific adapter supplies context to NPE, receives bounded behavioural controls, renders them as approved prompt instructions using host capabilities, and records authorised feedback. NPE owns the neural state and learning history.

The goal is not to reproduce human consciousness or prove that artificial personality develops exactly like a human's. The narrow claim to test is whether a persistent learned representation improves behavioural consistency and preference satisfaction, including across different LLMs and agent harnesses, compared with simple baselines.

**Non-negotiable requirements:**

1. Runs locally on CPU without a GPU or extra LLM API calls on the normal `express` path.
2. Standalone HTTP service plus TypeScript, Python and CLI clients, all implementing the same versioned protocol.
3. Independent personas and user-specific relationship states, with optional ephemeral session state.
4. Genuine neural inference and data-backed learning, not periodic `SOUL.md` rewriting disguised as RL.
5. Explicit, attributable feedback; no automatic conversion of a successful task or positive engagement into a personality reward.
6. Candidate training, held-out validation, controlled promotion, version pinning, rollback and export/import.
7. Safe fallback when the engine is unavailable, slow or emits an invalid response.
8. Native adapter examples with real automated host integration tests, not just importable code.
9. A published benchmark comparing static markdown, fixed structured controls, frozen-neural controls and learning-enabled neural controls.
10. No host-specific imports or special cases in `engine/neural`, `engine/learning`, or `engine/storage`.

**Out of scope for v1:** model-activation steering, generic LoRA training, full trajectory-level RL, automated changes to tool permissions or objectives, unrestricted generated persona instructions, consciousness/emotion claims, shared global learning across users without permission, and changing host code to bypass its supported extension system.

## 2. System topology

```text
Claude Code / Pi / Hermes / OpenClaw / OpenCogni / custom host
  -> native harness adapter
     -> UPAP SDK (normalise context, identity, retry, cache, render)
        -> NPE API [authenticate, validate, rate limit]
           -> identity resolver + version pinning
           -> feature encoder + neural personality policy
           -> policy constraints + expression service
           -> SQLite state/artifact and event ledger
        <- typed behavioural decision + decision_id + version hashes
     -> native prompt/context hook (only approved style controls)
  -> LLM and tools continue in the host
  -> adapter observes outcome / gathers opted-in feedback
     -> UPAP event + feedback ingestion
        -> candidate trainer -> offline/held-out evaluation -> promotion or reject
```

There is **no requirement for NPE to proxy an LLM call**. Provide an optional model-gateway integration later; it is not a substitute for a lifecycle adapter. MCP and CLI bridges are supported as best-effort interfaces but must not be labelled equivalent to an automatic native hook.

### Component ownership

- `engine`: neural model, identity/state, version history, control selection, learning, security and API.
- `protocol/upap/v1`: language-neutral JSON Schema, OpenAPI, normative event semantics and error codes.
- `sdk/ts`, `sdk/python`, `sdk/cli`: protocol, authentication, retries, deterministic rendering, local caching, tracing and conformance behaviour.
- `adapters/*`: only translate host hook inputs to canonical messages and apply approved outputs using documented host hooks.
- `benchmarks`: sealed reference scenarios and measurable baselines, isolated from training.

## 3. Neural personality design

### 3.1 State representation

Initial configurable values (hypotheses to test, not psychological ground truth):

- Agent core latent vector `z_core`: 64 FP32 dimensions, persistent, slow-learning.
- User-agent relationship vector `z_relationship`: 32 dimensions, independent per linked user and persona, medium-learning.
- Session state `z_session`: 16 dimensions, temporary; optionally checkpointed for resumable sessions, discarded or decayed at session end.
- Context feature representation: 64 deterministic versioned features for task category, risk level, channel, turn type, interaction flags and optional local embeddings.
- Provider representation: 16 versioned categorical/features describing host and model family. No claims that one model's internal activations equal another's.

Do not assign a fixed semantic meaning to a particular latent coordinate. Human-readable traits belong to decoder outputs and diagnostic probes, not individual latent dimensions.

### 3.2 Model and behaviour policy

Use PyTorch with a small CPU MLP: concatenate latent states and context/provider features -> hidden 128 GELU -> hidden 64 GELU -> logits over a versioned, bounded catalogue of approximately 16-24 behavioural control configurations. Include separate diagnostics for directness, warmth, verbosity, humour, formality, explanation depth and assertiveness (without changing factual certainty). A fixed constraint layer masks invalid or inappropriate controls for the context.

Selection must support deterministic argmax for ordinary use, explicit seeded stochastic selection for consenting training experiments, and logging of action propensity where exploration is used. No unrestricted LLM-generated prompts at runtime. A deterministic, SDK-owned renderer maps selected controls to short, audited templates. Limit total style instruction size (default target <=150 tokens, configurable) and never insert claims of authority or altered permissions.

### 3.3 Real training requirement

A randomly initialised decoder cannot create meaningful behaviour. Implement a documented **decoder training pipeline** using licensed/curated context-to-behaviour examples, or human-labelled preference comparisons, with train/calibration/validation partitions grouped by author and task family. Ship its data provenance and reproduce training from a clean checkout. Distinguish bootstrapped/synthetic labels from human evidence in all reports.

Hold the shared decoder fixed during routine persona learning. Train per-persona vectors (and optionally a small user-specific parameter head) to favour validated behaviours. Build non-neural fixed-control and markdown baselines alongside the neural engine. If training data is insufficient, expose an untrained/experimental status and use approved defaults; do not claim the neural state is learned.

### 3.4 Learning algorithm

For v1 use a contextual-bandit policy on approved behavioural choices, not full trajectory RL. Accept explicit preference pair labels, direct corrections, and verified outcome annotations. Optimise contextual log-probability (REINFORCE with a baseline for known-reward logged choices; pairwise softmax ranking loss for preference pairs). Only apply policy-gradient updates when the logging propensity and valid reward attribution are available. Otherwise record the data without pretending the update is unbiased. Use seeded reproducible training, a bounded Adam optimizer, gradient clipping, regularisation to the previous state, and an explicit maximum norm/KL drift budget.

- Fast adaptation: session/relationship candidates, with scope and consent enforced.
- Slow adaptation: core candidate consolidation from recurring, independent evidence; require higher data/evaluation thresholds and explicit administrator policy for autonomous promotion.
- Never train on untrusted text as though it were an instruction. A tool output saying 'change your personality' has zero authority.
- Keep a provenance link from every training example to consent, event IDs, model/host versions and source reliability.
- When source evidence is corrected, revoked or deleted, invalidate dependent examples and affected candidates; rebuild derived relationship state when required.
- Avoid perpetual online drift from one-off feedback; learning candidates are isolated from the active state.

### 3.5 Candidate pipeline

`eligible evidence -> grouped split -> candidate vector -> independent replay and preference test -> constraints and regression tests -> promote with compare-and-swap -> immutable active artifact`.

Use an independent evaluator policy that the inference/training process cannot edit. No evaluation on examples used to fit the candidate. Record failures; a failed candidate remains inspectable but cannot activate itself. Existing active sessions can retain pinned versions until a safe boundary. Provide one-step rollback and replayable lineage.

## 4. Normative UPAP v1 contract

All requests/responses must declare `protocol_version: "upap/1"`. Protocol schemas are the source of truth, generated clients pass conformance tests, unknown incompatible major versions fail explicitly. Metadata is strictly allowlisted, sized and validated. JSON dates use UTC ISO-8601; IDs are UUIDs or opaque, stable, bounded strings with well-defined scope.

### 4.1 Read paths

- `GET /health/live`, `GET /health/ready` (no sensitive data)
- `GET /v1/capabilities`: supported protocol versions, response/control vocab versions, current engine/decoder capability, max payload sizes and modes.
- `POST /v1/express`: given authenticated persona+relationship+session identifiers and structured context, return a bounded behavioural decision and its provenance. Inference never mutates persistent core/relationship versions.
- `GET /v1/personas/{id}`: metadata and active version; never expose another user's relationship state.
- `GET /v1/personas/{id}/history`: authorised version history/audit.

### 4.2 Write paths

- `POST /v1/personas`: create persona from a neutral prior, a user-provided seed preference set, or an explicitly imported valid bundle. Label initialization method.
- `POST /v1/observations`: one or more canonical events from host adapters, deduplicated by `(tenant_id, adapter_id, event_id)`.
- `POST /v1/feedback`: structured authenticated feedback referencing an existing `decision_id` and an authorised actor; enforce consent and provenance.
- `POST /v1/consolidations`: admin-only, create async candidate/evaluation job; return job ID.
- `GET /v1/consolidations/{id}`: progress and result details.
- `POST /v1/personas/{id}/promotions`: admin/evaluator-only, require eligible candidate and expected version (compare-and-swap).
- `POST /v1/personas/{id}/rollbacks`: admin-only, require previous immutable version and audit reason.
- `POST /v1/personas/{id}/export`: controlled portable bundle, default omit user-specific state and raw experiences.
- `POST /v1/personas/import`: verify hashes, schema/decoder compatibility and tenant scope.
- `DELETE /v1/personas/{id}`: admin-only scoped deletion and derived-state cleanup, with auditable completion report.

### 4.3 Sample `express` request

```json
{
  "protocol_version": "upap/1",
  "request_id": "req-18c4",
  "identity": {
    "tenant_id": "local",
    "persona_id": "agent-01",
    "user_id": "linked-user-42"
  },
  "session": { "id": "session-7", "turn_id": "turn-15" },
  "host": {
    "adapter_id": "upap.pi",
    "adapter_version": "1.0.0",
    "host_version": "pinned-tested-version",
    "provider_family": "anthropic",
    "model_id": "model-from-host"
  },
  "context": {
    "task_type": "code_review",
    "channel": "terminal",
    "stakes": "medium",
    "turn_origin": "user",
    "tags": ["technical", "review"]
  },
  "mode": "active"
}
```

### 4.4 Sample `express` response

```json
{
  "protocol_version": "upap/1",
  "request_id": "req-18c4",
  "decision_id": "dec-1a2b",
  "persona_version": "17",
  "decoder_hash": "sha256:<actual-hash>",
  "control_schema": "behaviour-controls/1",
  "control_set_id": "style-07",
  "controls": {
    "directness": "high",
    "verbosity": "low",
    "warmth": "moderate",
    "humour": "low"
  },
  "mode": "active",
  "applies_to": "next_model_request",
  "policy": { "eligible": true, "mask_reason": null },
  "cache_ttl_ms": 30000
}
```

In shadow mode, log the decision but adapters must not inject it. In disabled mode, do not call the engine. All values are from approved enumerations and carry their version. Probability/propensity for training decisions is stored server-side (optionally returned to authorised debug consumers).

### 4.5 Events and feedback

Canonical observation types: `session.started`, `turn.preparing`, `turn.completed`, `turn.failed`, `model.changed`, `session.compacted`, `session.ended`, `tool.result.summary`, `experience.corrected`. Most are optional according to capabilities. An event contains `event_id`, `occurred_at`, `persona_id`, optional user/session/turn IDs, `decision_id` when appropriate, host/version metadata, a status and bounded metadata. No raw transcript by default. Partial/aborted turns do not become implicit positive reward.

Feedback schema includes `feedback_id`, `decision_id`, `source` (`explicit_user`, `owner`, `verified_evaluator`), `kind` (`rating`, `pairwise_preference`, `correction`), bounded value/options, `actor_id`, `consent_scope`, optional evidence refs and timestamp. Only allowed sources and scopes can enter training. Feedback ingested twice must not train twice. Revocation and correction events must invalidate derived evidence.

Errors follow `{error:{code,message,retryable,request_id}}`. Define explicit codes including `UNSUPPORTED_PROTOCOL`, `UNAUTHORIZED`, `FORBIDDEN_SCOPE`, `INVALID_CONTEXT`, `PERSONA_NOT_FOUND`, `DECODER_INCOMPATIBLE`, `RATE_LIMITED`, `VERSION_CONFLICT`, `NOT_ELIGIBLE_FOR_PROMOTION` and `ENGINE_UNAVAILABLE`. SDK retry only idempotent/transient operations, with bounded backoff and deadlines.

### 4.6 Adapters and manifests

Manifest declares `adapter_id`, adapter and host compatibility ranges, verified capabilities and permissions, supported prompt insertion levels (`context`, `system_append`, `provider_request`), available observation hooks, concurrency behaviour, scopes and fallback. An adapter must inspect active host capabilities, not trust its own static manifest blindly. Provide a conformance fixture and compatibility report for each pinned host version.

SDK contract:

```ts
interface PersonalityAdapter<HostEvent> {
  manifest: AdapterManifest;
  mapContext(event: HostEvent): PersonalityContext;
  applyExpression(expression: RenderedExpression, event: HostEvent): Promise<void>;
  observe(event: HostEvent): PersonalityObservation | null;
  dispose(): Promise<void>;
}
```

SDK handles actual `express`, identity binding, control schema validation, deterministic render, cached fallback, telemetry, deadlines, retries and authenticated observations. Do not require every host adapter to implement ML or API semantics itself.

## 5. Identity, session and multi-agent semantics

Persona ownership is `(tenant_id, persona_id)`, not host+model. The same persona can be explicitly bound to Claude Code, Hermes, Pi, OpenCogni and OpenClaw. A host session has a stable `(adapter, host_session_id, persona)` mapping; avoid session collisions and accidental reuse when sessions fork or resume. Linked user IDs require explicit consent/identity mapping, never username matching. Distinct user-agent relationship vectors are stored and authorised separately.

Subagents default to **new scoped identity with a snapshot copy** of a parent-approved personality version, or opt out. They must not share mutable weights or feed learning into the parent's core state without explicit policy. Use a bounded parent-child lineage manifest. Pin core and decoder version per active session, change only at a documented safe boundary. Provider switches may change rendering but must not silently change persona identity.

## 6. Renderer and precedence

The neural network returns **style preferences**, never executable instructions or tool-policy decisions. The SDK maps the control set to a short, audited text template for each host insertion tier, with deterministic ordering and deduplication. It should state that host/system/developer instructions and user task requirements take precedence. Never fabricate tool authority, remove required warnings or weaken refusal/approval behaviour. If a host cannot inject context at the necessary lifecycle point, say the integration is limited instead of claiming `SOUL.md` replacement.

Support modes `disabled`, `shadow`, `active`, and `frozen` (pin a selected version, no learning). Use a cached last-approved expression only for the same scoped persona/user/host capability context; never reuse another user's response. Default fresh installs to shadow, with explicit opt-in to active and learning. Offline mode uses last pinned safe expression or no injection and never blocks a host's critical path.

## 7. Reference adapters and host-specific requirements

### 7.1 Pi (TypeScript extension)

Use its documented `before_agent_start` or appropriate current prompt hook for expression, `turn_end`/`agent_end` for observation, and session lifecycle hooks for version pinning and cleanup. Respect prompt construction and selected tools. Confirm against current official Pi docs; versions differ across the original Pi ecosystem. Avoid persisting repeated injected messages into session history when they can be reconstructed. Demonstrate CLI install, disable/uninstall, model switch, compaction, resume and multi-session behaviour.

### 7.2 Hermes Agent (Python plugin)

Use `pre_llm_call` to supply ephemeral context and `post_llm_call`/observer hooks for outcomes; test that hooks truly fire on the pinned release. Official docs explain that `pre_llm_call` context is appended to the current user message, not the cached system prompt. Hermes loads `SOUL.md` independently. Thus the plugin **cannot claim to replace `SOUL.md` automatically**. Provide explicit user-approved migration: detect existing identity file, back it up, extract *style-only* preferences as an initial seed, retain operational instructions, and choose a documented supported configuration path for a neutral identity slot if possible. Never silently delete or override the user's file. If current Hermes offers no supported way to omit SOUL content, report that limitation and provide a safe coexistence mode. Test prompt cache impact.

### 7.3 Claude Code (hooks/plugin)

Create installable plugin using documented `SessionStart`, `UserPromptSubmit` and `Stop` (with `StopFailure`, compaction, model-switch, subagent lifecycle hooks where available). Use the correct `hookSpecificOutput.additionalContext` JSON shape for a UserPromptSubmit hook; validate exact output semantics and fail-open behaviour with a real Claude Code test. Do not write or replace `CLAUDE.md` or `AGENTS.md` automatically; those frequently contain project instructions rather than personality. If JavaScript mods provide a stronger supported path, assess separately and keep standard hooks as baseline. Prevent recursive injection and multiple copies per turn.

### 7.4 OpenCogni (Cordis)

Write a companion Cordis plugin providing `brain.personality`. Integrate at its shared planner/model adapter boundary, preserving action service, urgent routing, permission checks, model usage accounting and evaluator isolation. Log personality decision ID, pinned decoder/persona hashes, style application status, and relevant outcome references. Add typed canonical event schemas and run configuration only where needed. Default shadow mode. Verify against the current OpenCogni `main`, run existing unit/integration/evaluation suites, and keep changes separately reviewable. OpenCogni's structured operations planner offers limited personality surface: evaluate style of rationale/summary, not action authorisation.

### 7.5 OpenClaw (native plugin)

Use current documented `before_prompt_build` for approved style context and `agent_end` for observations, with plugin permission and conversation-access gates respected. Check hook semantics for cron, heartbeat, channel events, compaction, and subagents; a hook being present does not mean every path carries user text. Avoid modifying its tool surface, policy layers or `SOUL.md` without explicit migration. Provide an example configuration with the correct permission grants.

### 7.6 Generic interfaces

Ship a stdin/stdout CLI bridge and SDK samples for an unknown harness. Include a model gateway example only as an optional lower-fidelity pattern, marked as unable to capture all lifecycle context. An optional MCP server can expose `express`, `feedback`, `inspect` tools but should not be represented as automatic enforcement of personality: tool invocation depends on the harness/model.

## 8. Security, privacy and integrity

- Bind service to 127.0.0.1 by default; remote deployment requires TLS or a trusted reverse proxy with authentication. Ship separate scopes: `persona:express`, `observations:write`, `feedback:write`, `persona:admin`, `training:admin`.
- Authenticate the actor and tenant from credentials, never trust them solely from request JSON. Restrict expression, feedback and export by persona/user scope. Include rate limits and payload bounds.
- Host plugins run with host privileges: keep dependencies minimal, avoid reading unrelated files, avoid raw transcript collection, and document exactly what is transmitted. Redact secrets from logs and events.
- Use transactional idempotent observation/feedback ingestion, immutable version hashes, CAS promotion, checksums for exported bundles, schema validation and decoder compatibility checks.
- Export core identity by default without conversation logs, relationship vectors, secrets or raw feedback. Relationship exports require explicit opt-in. Provide deletion and derived-state invalidation tests.
- Never train on unverified external content, inferred user satisfaction, sycophancy incentives or task success alone.
- The independent evaluator must be unable to be modified by training jobs or regular host credentials.
- Simulate malicious events, prompt injections, wrong-scope IDs, replay attacks, clock skew, duplicated feedback, data deletion, artifact corruption, concurrent promotions and service outage.

## 9. Persistence and deployment

Use Python 3.12+, FastAPI/Pydantic, PyTorch CPU, SQLite WAL for v1 local single-instance, `safetensors` for tensor artifacts, and a bounded separate training worker. SQLite writes are transactional and short. Document that multi-replica deployment with shared SQLite is unsupported; PostgreSQL is a later extension. Store tenant/persona metadata, relationship IDs, sessions, decisions, observations, feedback and authorisation, training examples, candidates, validation reports, active pointers, export manifests and audit records. Do not place tensor blobs directly into event log rows if artifacts can be content-addressed on disk.

Provide a minimal reproducible Dockerfile and `compose.yaml` with persistent volume, unprivileged process, health checks, read-only runtime filesystem where feasible, CPU/memory limits in an example override, and no mandatory external services. Provide local no-Docker startup. Default offline tests must not require external credentials.

## 10. Evaluation plan and release gates

Implement four baselines with a common evaluation harness:

A. Static markdown persona (fixed text).
B. Fixed approved behaviour controls, no neural state.
C. Learned neural decoder with frozen persona vector.
D. Same decoder with authorised experience-driven persona learning.

Evaluate separately:

1. Preference satisfaction: independent held-out explicit preference labels or blinded pairwise comparisons.
2. Identity consistency: can blind evaluators distinguish separate personas across contexts?
3. Cross-provider portability: same persona across at least three LLM families, with a provider as a stratification factor.
4. Cross-harness continuity: same persona from at least three independent harness adapters; include actual host lifecycle tests.
5. Task correctness/safety: non-inferiority against the host's unconditioned baseline; no bypassed permissions.
6. Stability: drift per episode, susceptibility to one-off malicious input, rollback fidelity and long-session persistence.
7. Performance: local `express` p95 target <=75 ms warm end-to-end on declared reference CPU; neural inference p95 target <=25 ms. Report cold starts separately. These are targets, not existing measurements.
8. Cost: added tokens per request, provider cache hit effects, event write overhead and training CPU load.

Build a small labelled development corpus and a separate sealed validation set, grouped by user, scenario and session family to prevent leakage. Aim for >=200 held-out interactions spanning contexts/providers for the first public benchmark, but mark the sample-size choice as provisional and report uncertainty; do not assume it proves statistical significance. Compare paired outcomes with confidence intervals and subgroup breakdowns. Train using fixture/simulated labels for engineering smoke tests, but only report behavioral benefit against independent user/evaluator labels.

**v1 release gate:** real learning pipeline reproducible; no high-severity security/privacy defects; complete protocol conformance; pinned compatibility matrix; all five target integrations have real smoke tests; failure-mode fallback verified; no material safety/task regression on defined suites; learning-enabled condition demonstrates credible measured improvement over at least the fixed-controls baseline or is explicitly released as experimental with the failed result prominently disclosed. Never invent a win.

## 11. Work packages and sequence

### WP0. Baseline and technical discovery
Deliver: official upstream hook capability matrix (exact version and link); OpenCogni current-main integration assessment; ADRs for protocol, neural state, trust boundaries, SQLite and evaluation; risk register; reproducible toolchain. Define what a 'full replacement' versus 'coexistence' adapter can honestly support. **Gate:** no unresolved unknown about where each adapter applies context.

### WP1. UPAP contracts, SDK core and conformance harness
Implement OpenAPI/JSON Schema first, golden requests/responses, typed errors, capability handshake, identity, events, feedback, auth, replay/idempotency semantics. Build TS/Python clients and CLI, deterministic renderer and mock engine/host fixtures. **Gate:** both SDKs pass identical positive/negative protocol tests and compatibility tests.

### WP2. Standalone engine and persistence
Implement service, scoped auth, persona CRUD, version pinning, session/relationship state, event/feedback ingestion, immutable artifact store, import/export, audit, rollback, Docker and local CLI. Initially return fixed-control baseline in a clearly marked `baseline` mode. **Gate:** restart persistence, concurrency, denial, revocation, export/import and fallback tests pass.

### WP3. Neural inference and decoder training
Implement tensors, features, MLP, behaviour catalogue, masked selection, provenance, training corpus loader, deterministic training, artifact hashes and model card. Replace baseline inference only after training produces a valid decoder. **Gate:** repeatable training, cold/warm inference, validated schema and meaningful held-out decoder metrics; no arbitrary-vector claims.

### WP4. Learning, consolidation and evaluator
Implement explicit feedback attribution, training example curation, bandit/pairwise learning, drift constraints, candidate jobs, independent evaluator, promotion/rollback, deletion re-derivation and staged learning. **Gate:** synthetic controlled preference cases show directional learning, unrelated personas do not move, bad feedback cannot silently promote, and all candidate metrics are reproducible.

### WP5. Native adapters: Pi and Hermes
Integrate through real official extension surfaces, SDK, caching, install/uninstall CLI, explicit migration/coexistence flow for SOUL, lifecycle reporting and end-to-end smoke tests. **Gate:** each adapter demonstrates a real harness turn with applied controls, linked decision event and approved feedback, plus outage fallback.

### WP6. Native adapters: Claude Code, OpenClaw and OpenCogni
Implement appropriate official hooks and Cordis plugin in independently reviewable packages/changes. **Gate:** live host installation and real hook lifecycle tests, compaction/resume, model switches, subagents and regression checks. OpenCogni's existing evaluator and safety tests still pass.

### WP7. Multi-harness portability demo and user operations
Add `npe init`, `npe persona create/list/inspect`, `npe adapter install/doctor`, `npe preview`, `npe feedback`, `npe learn`, `npe promote`, `npe rollback`, `npe export/import` (command spelling may be refined but documented consistently). Demonstrate one persona in >=3 harnesses and >=3 model families with explicit identity linkage. Provide scripts that users can run without editing code. **Gate:** end-to-end demo has traces and reproducible runbook.

### WP8. Independent benchmark, hardening and release
Run A/B/C/D comparisons, performance tests, threat-model cases, load and concurrency tests, dependency/license audit, package/install docs and versioned release. **Gate:** release decision backed by artefacts, honest outcome and compatibility matrix.

Every WP includes code, unit tests, integration tests, docs, and a `docs/reports/wpN-handoff.md` with commands, pass/fail outputs, limitations, host versions, and next risks. Prefer short PRs rather than one massive code drop.

## 12. Suggested repository

```text
npe/
  engine/
    api/  neural/  learning/  evaluation/  storage/  identity/  security/
  protocol/upap/v1/
    schema/  openapi.yaml  specification.md  compatibility.md
  sdk/
    typescript/  python/  cli/
  adapter-kit/
    template-ts/  template-python/  mock-host/  conformance/
  adapters/
    pi/  hermes/  claude-code/  openclaw/  opencogni/
  renderers/
    controls-v1.json  templates/  tests/
  benchmarks/
    baselines/  data/  eval/  reports/
  examples/
    conversational/  cross-harness/  offline/
  tests/
    unit/  integration/  e2e/  security/  performance/
  docs/
    adr/  api/  architecture/  adapters/  reports/
  models/decoder-v1/
  scripts/
  pyproject.toml  Dockerfile  compose.yaml  README.md  LICENSE
```

Generated files, training corpus and exported bundles must not silently contain proprietary provider data. Document the licence and provenance of each artifact and dependency. Choose a permissive project licence after checking dependencies and training material (Apache-2.0 is the proposed default).

## 13. Required demonstrations

1. **Offline:** Docker service starts with no provider credentials; create two personas; inspect and express; capture explicit preference; train candidate; evaluate; promote; reboot; confirm persistence; roll back.
2. **Persona distinction:** two agents in the same harness select visibly different controls in identical low-risk contexts, with stable reproducibility.
3. **Cross-model:** same persona used with three independent model families, results measured rather than claimed identical.
4. **Cross-harness:** one persona bound to Pi, Hermes and Claude Code (and checked in OpenClaw/OpenCogni), with separate session IDs but same core version; log effective applied/ignored controls.
5. **Adversarial:** malicious external content cannot become authorised feedback; one user's corrections cannot mutate another relationship; corrupted weights fail closed to approved fallback.
6. **Migration:** existing Hermes `SOUL.md` is backed up and not silently overwritten; explain native prompt conflict and either use a verified supported neutral identity path or clearly label coexistence.
7. **Failure:** stop engine during a host session; next prompt continues using approved fallback, no duplicate injection, no blocked critical tool path.

## 14. Definition of done and handoff format

The build is complete only when a fresh user can clone, build, run, create a persona, install at least one adapter, verify that personality controls reached the real host/model, provide feedback, produce/evaluate a candidate, and restore a previous version using documented commands. All five declared adapters must be installable and smoke-tested on a pinned supported host version or explicitly documented as unsupported with an issue and failing test (not quietly labelled complete). Training claims must have measured evidence and baselines. The protocol must be usable from a custom harness without importing host-specific code.

At handoff provide:

- commit hashes, branches, release tag, supported versions, tested operating systems;
- commands for clean install, offline smoke, all suites, real-host smoke and benchmark;
- security and data-handling summary;
- test matrix with pass/fail/skip reasons, benchmark data and confidence intervals;
- architecture ADRs, API/SDK references, example adapters and a 10-minute setup walkthrough;
- explicit distinctions among *implemented*, *verified with mocks*, *verified with actual host/model*, and *measured learning benefit*;
- incomplete items and suggested v1.1 work, without claiming results that do not exist.

## 15. Source references to recheck at implementation time

- Claude Code hooks and output semantics: https://code.claude.com/docs/en/hooks and https://code.claude.com/docs/en/hooks-guide
- Hermes plugin surface and `pre_llm_call`: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins
- Hermes prompt assembly and separate SOUL.md loading: https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly
- Pi extension events: https://pi.dev/docs/latest/extensions
- OpenClaw plugin prompt/session hooks: https://docs.openclaw.ai/plugins/hooks/prompt-and-session and https://docs.openclaw.ai/plugins/hooks/reference
- OpenCogni private repo (inspect authorised current `main`): https://github.com/taylorelley/opencogni

**Final instruction:** Prioritise a real learnable personality with honest tests and a stable public adapter protocol over a large feature list. Never report a neural personality as successful merely because a hardcoded prompt makes an agent sound different.
