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
express, observations, feedback, reflections, consolidations, promotion, rollback,
evolution settings, deletion.
Path and exact request schemas are in OpenAPI. Metadata and raw transcript fields
are deliberately absent in this profile. Observations never imply reward.

Creation requires exactly one starting point: an `archetype` (balanced, mentor,
pragmatic_engineer, concierge, collaborator, analyst, critic; each a fixed seed
combination listed in capabilities), advanced `seed_preferences` (concise,
detailed, warm, reserved, formal, casual, direct, gentle, playful, serious;
conflicting pairs are rejected), or a `parent_persona_id` snapshot (new scoped
identity with an immutable copy of the parent's active core and its archetype;
used for subagents). Neither is INVALID_CONTEXT; `balanced` is the explicit neutral
start. Import creates a persona with manual evolution. The response labels the
initialization method. Creation also sets the evolution policy: `evolution`
(`automatic`, default, or `manual`), `maturation_rate` (`fast`, `normal`, default,
`slow`, or `{relationship_horizon, core_horizon}` in ended sessions, 3-1000; the
engine default can be set with OPENAPE_MATURATION_RATE) and `agent_feedback`
(default true). `POST /v1/personas/{id}/evolution` (persona:admin) changes them; a
rate change or resume re-anchors the maturation curve at current experience, so
the state never jumps. `GET /v1/personas/{id}?user_id=` reports growth (experience,
horizon, maturity) for the core and, when scoped to that user, the relationship.
Personas stored by 0.2.0 keep manual evolution and no agent feedback until changed.

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

Agent reflections (`POST /v1/reflections`, scope `reflection:write`) are how a host
exposes the `persona_feedback` tool (`tools/persona_feedback.json`) to its agent.
The body names a decision, 1-3 `adjustments` (trait to `more`/`less`) and a `reason`
enum; there is no free text. The engine moves the served catalogue row one level
per trait, picks the nearest approved row valid under that context's mask, and
records it as a consented pairwise preference with source `agent_reflection` (that
source is refused on `/v1/feedback`). Rules: only user-originated, non-frozen,
non-fallback decisions by the same actor; one reflection per decision (replaying
the same one deduplicates) and 3 per session (RATE_LIMITED); the persona's
`agent_feedback` must be on; scope defaults to relationship when a user is linked,
and core reflections on a linked user's turn need training:admin. Reflections are
revocable like other evidence.

Automatic evolution (personas with `evolution: automatic`) needs no operator:
1. Feedback. Once enough new consented core/relationship examples exist since the
   last attempt (4 relationship, 8 core), the engine queues a consolidation, runs
   the same trainer and independent evaluator under stricter autonomous thresholds
   (relationship 6 train/3 held-out groups, core 12/6 and drift 1.0 -> 0.6, held-out
   gain >= 0.005) and promotes an eligible candidate itself via the same
   compare-and-swap (audit actor `openape:auto-evolution`). Agent reflections never
   exceed half of the examples in an automatically promoted candidate when people's
   feedback exists. A lost compare-and-swap marks the job `superseded`.
2. Maturation. An ended session that received an active, non-fallback decision
   counts as experience for the core and, with a linked user, that relationship.
   Maturity is m(t) = sqrt(min(t/T, 1)) for horizon T. A step is due when m has
   risen by 0.05 since the last step (or reaches 1), and may move the latent at most
   (m - m_last) x budget (relationship 1.0, core 0.6), so changes are frequent and
   larger early, rarer and smaller later, and stop at T. A backlog is replayed step
   by step. Relationship steps grow a fixed familiarity profile (warmer, less
   formal, briefer) on the archetype, mixed 30% into the current policy; core steps
   lean toward the documented context norms of the contexts actually served,
   weighted by frequency. A step is promoted only if it is finite, within budget
   and the norm bound, and does not reduce agreement with the persona's valid
   consented preferences (feedback wins). Audit actor `openape:maturation`,
   action `matured`. Maturation is a fixed prior, never reward; outcomes,
   engagement and text are never read.
Manual personas keep the operator path below. Session pins mean every automatic
change applies from the next session.

Consolidation returns 202/job_id. The independent evaluator splits evidence by
actor/session group; the trainer fits only the training split; the evaluator
re-scores held-out groups and applies fixed thresholds (held-out gain, minimum
groups, latent drift trust region, state-norm bound). Repeated judgements on the
same decision by the same actor count once. No candidate can promote itself.
Operator promotion requires training:admin, an eligible non-revoked candidate, matching
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
