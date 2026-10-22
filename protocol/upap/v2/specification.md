# UPAP/2 — OpenAPE experimental profile

JSON Schemas in `schema/` and `openapi.json` describe this implementation. Regenerate
with `python -m scripts.generate_protocol`; common positive/negative fixtures are
in `conformance.json`. This is not an established standard or full v1 conformance.

Every write body MUST declare `protocol_version: "upap/2"`; `upap/1` bodies are
rejected with UNSUPPORTED_PROTOCOL. Every response,
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
The context (encoder/3) is task type (general, code_review, coding, support, creative,
research, debugging, planning, writing), channel, stakes, turn origin and tags
(technical, review, sensitive, urgent, beginner, expert, error_present, first_turn,
long_session). `first_turn` and `long_session` (20 or more earlier turns) are set by
the engine from its session record; host values are ignored. Adapters derive the
rest from host metadata with the shared `context-rules.json`.

Decisions carry `control_schema: "behaviour-controls/2"`, the `catalogue_hash` of
`protocol/catalogue.py`, `controls` (an integer level 0-4 for each of seven traits:
directness, warmth, verbosity, humour, formality, explanation_depth, assertiveness)
and `habits` (at most 3 habit ids in catalogue order). Controls must form an approved
configuration (no forbidden level pair); each habit must be eligible for those levels
and not exclusive with another. Context masks cap humour at 1 for high stakes or
`sensitive`, verbosity at 2 for `urgent`, and drop habits that do not fit (for example
no clarifying question on urgent or non-user turns). SDKs validate all of this
before rendering, and render the prefix, one sentence per trait and one per habit.
Versions pin per scoped session. Ordinary inference changes neither persistent
core nor relationship state; it writes a decision/audit ledger and session pin.
`selection: sample` requires seed and exploration_consent; propensity stays in
server ledger. `frozen` disallows exploration and its decisions cannot train; it may
name `pinned_version` to evaluate an explicit immutable core version. `debug: true`
(training:admin only) returns the logging propensity and decoder diagnostics
(expected trait levels 0-4 and `habit:<id>` probabilities).
Disabled is SDK-local and makes no HTTP call. Shadow decisions render to empty.

Request deduplication is scoped `(tenant, persona, actor, request_id)` with a full
request fingerprint. Same key/different body returns VERSION_CONFLICT. Observation
keys are `(tenant, adapter_id, event_id)`; feedback keys `(tenant, feedback_id)`.
Conflicting replay fails transactionally. Feedback binds an existing authorized
decision and authenticated actor; owner/evaluator sources require training admin.
Feedback may carry a UTC `occurred_at` and up to 8 `evidence_refs`.
Learning requires explicit consent and core/relationship scope. Session and
record-only feedback is retained but not trained in this release. Consented
pairwise preferences and corrections in any scope but record-only also refit the
open session's ephemeral state (response `session_adapted`); see Development. Pairwise
options (`preferred`, `rejected`) are distinct `{controls, habits}` choices whose
controls form approved configurations. Latent learning uses canonical
adapter/session groups, not caller-supplied claims of independent evidence.

Agent reflections (`POST /v1/reflections`, scope `reflection:write`) are how a host
exposes the `persona_feedback` tool (`tools/persona_feedback.json`) to its agent.
The body names a decision, up to 3 `adjustments` (trait to `more`/`less`), up to 2
`habits` (habit id to `more_often`/`less_often`; at least one move in total) and a
`reason` enum; there is no free text. The engine moves the served configuration at
least one level per named trait to the nearest approved configuration valid under
that context's mask, adds or drops the named habits, and records the result against
the served choice as a consented pairwise preference with source `agent_reflection` (that
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
3. Development (docs/adr/0004-human-like-development.md).
   * Creation records `individuality` {amount, seed} (request fields `individuality`
     0-1, default 0.3, and optional `individuality_seed`). The creation version is
     the temperament, and automatic core change stays within 1.6 latent units of
     it.
   * A session state is a bounded latent offset (relationship latent with a linked
     user, else core) refitted from the newest 12 deduplicated consented
     preferences of an open session. It is applied at express until the session
     ends and is never a version.
   * At session end the state, refitted from relationship/core-consented feedback
     only, becomes a sample. Three or more consistent recent samples produce a
     habit step whose evidence ids follow revocation lineage.
   * Experience t is effective experience: novel context signatures count more,
     and life events (`role_change`, `new_host`, `correction_burst`, `rupture`,
     `long_absence`, audited as `life_event`) raise it and plasticity for a while.
   * Growth is m(t) + 0.15·max(0, t−T)/T, so adult steps continue slowly.
   * A maturation job is one consolidation pass, evaluated and promoted once. It
     combines relationship cooling after 14+ days without a session (server
     time), the next curve step (with per-trait sensitive periods and, for
     relationships, accommodation to the user's tag mix), a consistent habit, and
     a 25% pull toward a self anchor that absorbs deliberate change. The pull is
     withheld if it would reduce feedback agreement.
   * Rollback and operator promotion reset the anchor.
   * Automatic candidates weight examples by recency and by source influence at
     the scope's maturity (owner 2−m, users 0.5+0.5m, reflections 0.3+0.7m, with
     reflection share 0.2+0.8m).
Manual personas keep the operator path below. Session pins mean every automatic
version change applies from the next session; session state is the only
within-session change.

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
session state is a latent offset, not the decoder's (untrained) session input, and
is not checkpointed. Cross-major migration is a reset (`openape migrate --reset`), not
a state conversion. See docs/reports/open-issues.md.
