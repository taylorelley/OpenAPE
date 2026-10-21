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

Express requests identify tenant/persona/user, adapter, provider, session and turn.
Versions pin per scoped session. Ordinary inference changes neither persistent
core nor relationship state; it writes a decision/audit ledger and session pin.
`selection: sample` requires seed and exploration_consent; propensity stays in
server ledger. `frozen` disallows exploration and its decisions cannot train.
Disabled is SDK-local and makes no HTTP call. Shadow decisions render to empty.

Request deduplication is scoped `(tenant, persona, actor, request_id)` with a full
request fingerprint. Same key/different body returns VERSION_CONFLICT. Observation
keys are `(tenant, adapter_id, event_id)`; feedback keys `(tenant, feedback_id)`.
Conflicting replay fails transactionally. Feedback binds an existing authorized
decision and authenticated actor; owner/evaluator sources require training admin.
Learning requires explicit consent and core/relationship scope. Session and
record-only feedback is retained but not trained in this release. Pairwise
options must be distinct approved catalogue indices. Latent learning uses canonical
adapter/session groups, not caller-supplied claims of independent evidence.

Consolidation returns 202/job_id. A bounded one-worker queue trains a candidate,
then records fixed-policy validation metrics. No candidate can promote itself.
Promotion requires training:admin, an eligible non-revoked candidate, matching
expected core version and relationship parent. A candidate promotes only once.
Rollback requires persona:admin, valid immutable artifact and reason. Active
sessions retain pins. Revoke evidence with an experience.corrected observation;
only the evidence actor or training admin can do so. Revocation resets derived
state for the affected scope and invalidates dependent candidates. Deletion
removes persona state, user state, decisions, evidence, jobs and unused artifacts;
a minimal count-only completion audit remains. No raw text is collected.

Errors: `{protocol_version,error:{code,message,retryable,request_id}}`.
Codes include UNSUPPORTED_PROTOCOL, UNAUTHORIZED, FORBIDDEN_SCOPE, INVALID_CONTEXT,
PERSONA_NOT_FOUND, DECODER_INCOMPATIBLE, RATE_LIMITED, VERSION_CONFLICT,
NOT_ELIGIBLE_FOR_PROMOTION. SDK unavailability returns local empty/cached fallback;
HTTP ENGINE_UNAVAILABLE is reserved for a future remote worker failure profile.

Known conformance gaps: SDKs are manually implemented rather than generated;
write/read envelopes beyond decisions are not all modeled; source reliability and
per-field consent revocation are limited; explicit relationship export unsupported;
session vector adaptation/checkpointing not implemented; no full cross-major
migration system; no adapter install/doctor commands. See release gate issues.
