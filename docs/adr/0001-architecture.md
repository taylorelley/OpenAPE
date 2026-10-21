# ADR 0001: UPAP/1 experimental local architecture

Status: accepted for 0.1.0 experiment; not final v1 conformance.

* **Protocol:** UPAP remains provisional `upap/1`. Strict Pydantic wire models
  generate JSON Schemas and OpenAPI (`python -m scripts.generate_protocol`).
  All request bodies explicitly include protocol_version; authenticated GETs have
  versioned URLs and versioned responses. Unknown fields are rejected. No remote
  prompt strings are returned. JSON OpenAPI is used instead of YAML to avoid
  another parser dependency. Compatibility extensions are listed in the contract.
* **Neural state:** CPU PyTorch MLP 192->128 GELU->64 GELU->20. Core 64,
  relationship 32, session 16 (zero ephemeral prior only), context 64 and provider
  16; deterministic SHA-256 categorical encoder. Host metadata enters only
  through versioned data features. Latent axes have no assigned semantics.
  Decoder weights freeze during persona learning. Diagnostic traits are catalogue
  controls; no independent learned diagnostic probes are claimed.
* **Learning:** explicit pairwise preferences/corrections train log-softmax
  ranking loss; logged seeded stochastic ratings use clipped importance-weighted
  REINFORCE with a fixed zero baseline. Argmax ratings are recorded without policy
  gradient. Adam, clipping, L2 anchor, 1.95 norm projection and training-context
  KL projection. Actor/session groups split before fitting; validation labels
  never enter optimization. No calibration of ordinary persona candidates.
* **Promotion/evaluation:** independent frozen threshold module checks held-out
  improvement, minimum groups, norm, KL and finiteness. Core thresholds are higher
  than relationship thresholds. Single bounded thread worker, four queued/running
  jobs maximum. Thread isolation is logical, **not** OS/process security isolation;
  a separate worker service and tamper-resistant evaluator deployment remain open.
  Sessions pin versions/decoder until end; operator rollback affects new sessions.
* **Persistence:** SQLite WAL + short serialized transactions; immutable
  content-addressed safetensors, no pickle. SHA-256 validates artifacts and
  exports. CAS checks both core and relationship parents. One process/replica.
  Export core only, no raw feedback, relationships or secrets. Same-tenant import
  is required; cross-tenant portability requires an explicit future rebinding flow.
* **Trust:** credential binds tenant, actor, persona allowlist, user allowlist and
  scopes. JSON cannot override these. Feedback never comes from tool results or
  inferred task success. Synthetic/human provenance is not interchangeable.
  Revocation invalidates candidates and resets affected derived state to prior;
  relationship revocation never resets another user's relationship. Core evidence
  requires administrator authority. No automatic re-learning after revocation.
* **Fallback:** 250 ms SDK deadline, at most one transient retry, exact scoped
  short-lived cache or empty injection. Fresh shadow mode, disabled makes no
  request. Artifact failures select an approved neutral baseline, not random
  decoder behavior. Remote SDK endpoints require HTTPS; default service loopback.

Consequences: intentionally modest local architecture; no high-availability,
activation steering, LLM proxy, generated instructions or autonomous promotion.
