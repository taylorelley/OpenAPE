# UPAP/1 — OpenAPE experimental profile

JSON Schemas in `schema/` and `openapi.json` describe this implementation. Regenerate
with `python -m scripts.generate_protocol`; common positive/negative fixtures are
in `conformance.json`. This is not an established standard or full v1 conformance.

Every write body MUST declare `protocol_version: "upap/1"`. Every response,
including errors and health, declares the version. Unknown fields are rejected.
IDs are bounded ASCII strings. Observation dates must carry UTC offsets and be
within seven days; clocks outside that window receive INVALID_CONTEXT.

Authenticate with Bearer credentials configured via OPENAPE_CREDENTIALS (JSON list)
or OPENAPE_CREDENTIALS_FILE (CLI). A record binds token, tenant, actor, scopes,
allowed personas and allowed linked user IDs. No username inference or implicit
user linking. Missing or invalid authentication returns 401; forbidden scopes 403.
600 requests per authenticated actor per minute; 64 KiB body, 100 events/batch.

Reads: health/live, health/ready; authenticated capabilities, persona list,
metadata/history, consolidation status. Writes: persona creation/import/export,
express, observations, feedback, consolidations, promotion, rollback, deletion.
Path and exact request schemas are in OpenAPI. Metadata and raw transcript fields
are deliberately absent in this profile. Observations never imply reward.

Personas are created from a neutral prior, from declared `seed_preferences`
(concise, detailed, warm, reserved, formal, casual, direct, gentle, playful,
serious; conflicting pairs are rejected), as a `parent_persona_id` snapshot (new
scoped identity with an immutable copy of the parent's active core; used for
subagents), or by import. The response labels the initialization method.

Express requests identify tenant/persona/user, adapter, provider, session and turn.
Versions pin per scoped session. Ordinary inference changes neither persistent
core nor relationship state; it writes a decision/audit ledger and session pin.
`selection: sample` requires seed and exploration_consent; propensity stays in
server ledger. `frozen` disallows exploration and its decisions cannot train; it may
name `pinned_version` to evaluate an explicit immutable core version. `debug: true`
(training:admin only) returns the logging propensity and decoder diagnostics
(probability-weighted trait levels).
Disabled is SDK-local and makes no HTTP call. Shadow decisions render to empty.

Request deduplication is scoped `(tenant, persona, actor, request_id)` with a full
request fingerprint. Same key/different body returns VERSION_CONFLICT. Observation
keys are `(tenant, adapter_id, event_id)`; feedback keys `(tenant, feedback_id)`.
Conflicting replay fails transactionally. Feedback binds an existing authorized
decision and authenticated actor; owner/evaluator sources require training admin.
Feedback may carry a UTC `occurred_at` and up to 8 `evidence_refs`.
Learning requires explicit consent and core/relationship scope. Session and
record-only feedback is retained but not trained in this release. Pairwise
options must be distinct approved catalogue indices. Latent learning uses canonical
adapter/session groups, not caller-supplied claims of independent evidence.

Consolidation returns 202/job_id. The independent evaluator splits evidence by
actor/session group; the trainer fits only the training split; the evaluator
re-scores held-out groups and applies fixed thresholds (held-out gain, minimum
groups, latent drift trust region, state-norm bound). Repeated judgements on the
same decision by the same actor count once. No candidate can promote itself.
Promotion requires training:admin, an eligible non-revoked candidate, matching
expected core version and relationship parent. A candidate promotes only once.
Rollback requires persona:admin, valid immutable artifact and reason. Active
sessions retain pins. Revoke evidence with an experience.corrected observation;
only the evidence actor or training admin can do so. Revocation follows lineage:
only candidates that used the evidence, versions promoted from them and their
descendants are invalidated (marked revoked, artifacts collected, rollback refused);
active pointers move to the nearest clean ancestor. Unused evidence revokes nothing. Deletion
removes persona state, user state, decisions, evidence, jobs and unused artifacts;
a minimal count-only completion audit remains. No raw text is collected.

Errors: `{protocol_version,error:{code,message,retryable,request_id}}`.
Codes include UNSUPPORTED_PROTOCOL, UNAUTHORIZED, FORBIDDEN_SCOPE, INVALID_CONTEXT,
PERSONA_NOT_FOUND, DECODER_INCOMPATIBLE, RATE_LIMITED, VERSION_CONFLICT,
NOT_ELIGIBLE_FOR_PROMOTION. SDK unavailability returns local empty/cached fallback;
HTTP ENGINE_UNAVAILABLE is reserved for a future remote worker failure profile.

Rendering: `sdk/python/lite.py` (stdlib) and `sdk/typescript/client.ts` must render
byte-identical text; `conformance.json` carries golden `rendered` strings for both.

Known conformance gaps: SDKs are hand-written (golden fixtures, not generated
clients); write/read envelopes beyond decisions are not all modeled; source
reliability is a credential class only; explicit relationship export unsupported;
session vector adaptation/checkpointing not implemented; no cross-major migration
system. See docs/reports/open-issues.md.
