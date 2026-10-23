# Changelog

## Unreleased: relationship controls, separate habit learning, multi-replica (ADR 0006)

### Learning
* Habits learn beside the latent. A per-version habit bias comes from consented habit
  evidence and is promoted by a new automatic `habit` job with lineage, so revocation
  reverts it. A session habit offset applies in-session requests at once.
* Trait learning (candidates, session states, evaluator) is trait-only. Session
  states keep unmentioned traits and habits where they were (KL anchor).
* A person's habit request counts in full. An agent's reflections alone move a habit
  at most halfway and may not weaken `flag_uncertainty` or `risks_first`.
* Cohort prior: a new relationship starts from the shrunk mean of at least five
  opted-in relationships.
* Opt-in exploration logs an ε-mixture policy with true propensities.
  `POST /v1/comparisons` asks "which style did you prefer?". New CLI commands:
  `openape compare` and `openape rate`.
* Decoder retrained. Held-out fitted trait agreement is 0.742 (was 0.655).
  Episodic meta-training is available (`--episodic-steps`) but off: it showed no gain.

### Relationship controls
* `GET/PUT /v1/personas/{id}/users/{user}/settings` (scope `settings:write`):
  * enumerated preferences (address, spelling, units, format, dates), each one
    reviewed sentence;
  * trait pins (context safety masks win);
  * habit vetoes;
  * freeze;
  * cohort and exploration consent.

  Decisions carry `preferences` and `exploration`. CLI: `openape settings`.

### Context
* Adapters send file languages and repository kind (marker names only). The engine
  tags `returning` and `corrected`.
* The opt-in text classifier is a hashed-feature linear model with Python and
  TypeScript parity. It replaces the keyword rules (held-out task accuracy 0.60 vs
  0.33).
* Reviewed tone examples, opt-in via `OPENAPE_STYLE_EXAMPLE=1`.
* Security: a repository's `.openape.json` is untrusted. It is read as a regular file
  of at most 64 KB, without following links or blocking, and can only add task,
  language, repo kind and tags or raise stakes.

### Visibility
* `GET /v1/decisions/{id}/explanation` (why this style, by layer) and
  `GET /v1/personas/{id}/timeline`.
* `openape dashboard` writes a self-contained page; `scripts/demo_dashboard.py`.
* `GET /v1/whoami`.

### Production
* PostgreSQL backend (`OPENAPE_DATABASE_URL`, `postgres` extra) for several replicas,
  with `compose.replicas.yaml`. The full suite runs on both backends
  (`OPENAPE_TEST_DATABASE_URL`).
* Candidate and maturation evaluation run in a spawned evaluator process.
* Docker image 0.3.0 re-verified (hardened compose, isolated evaluator, two replicas
  on PostgreSQL).
* Live tool-calling smokes (`scripts/live_tool_smoke.py`, Hermes and OpenClaw) on a
  real model.
* The live harness adds `prefix` placement, `--example` and per-arm comparison, and
  survives a torn record line.
* The OpenCogni boundary change was raised upstream as a PR (taylorelley/opencogni#8);
  its cap is now 1400 chars.

## Unreleased — live-model style evaluation harness

* `benchmarks/live`: 36 fixed CC0 prompts × baseline, static persona, neutral, 28
  trait-level probes and 16 habit probes with matched controls; style text rendered by
  the SDK; engine context masks respected.
* A blind Claude judge (official `anthropic` SDK, optional `live` extra) rates traits,
  habits, task quality and refusals under a JSON schema; 10% are judged twice for
  consistency. The judge uses `fallbacks: "default"`; the model under test never
  falls back.
* Reports trait fidelity, adjacent-level distinguishability, leakage, habit lift,
  quality and refusal parity, cross-model agreement, and flags templates to revise
  (`docs/reports/live-eval.*`).
* Dry run with cost estimate by default; resumable. Any OpenAI-compatible endpoint, through
  the official `openai` SDK (also in the `live` extra), can be the model under test or the
  judge (`--judge-provider`, `--judge-base-url`, `--judge-key-env`,
  `--judge-response-format json_schema|json_object|none`).
* Offline tests: a mock provider that injects known defects, fake clients, and both
  official SDKs against a local stub server to check the HTTP requests they send.

## 0.3.0 — expressive controls, decoder-v3, upap/2 (see docs/adr/0005-expressive-controls.md)

Breaking: a clean break from upap/1 and behaviour-controls/1.

* behaviour-controls/2 (`protocol/catalogue.py`): seven traits on a five-level scale
  with one reviewed sentence per level, six reviewed coherence rules (51 788
  approved configurations), and 16 signature habits with eligibility and
  exclusions (at most three per turn). `catalogue_hash` binds decisions to the
  catalogue; `renderers/controls-v2.json` is generated from it.
* decoder-v3 / encoder/3 (`models/decoder-v3`): trait-level and habit heads, joint
  selection over approved configurations, eligible habits above one half. New
  context values: `debugging`, `planning`, `writing`, `error_present`, and the
  engine-set `first_turn` and `long_session` tags. Archetypes carry signature habits.
* Learning works on `{controls, habits}` choices: pairwise feedback, reflections
  (now also `habits: {id: more_often|less_often}`), session states, maturation and
  the evaluator. Constraint masks are cached (four fixed variants).
* upap/2: decisions carry integer `controls`, `habits` and `catalogue_hash`;
  feedback carries `preferred`/`rejected` choices; reflections `adjustments` and/or
  `habits`. upap/1 requests are rejected; 0.2 clients fail open.
* `openape migrate --reset` re-creates personas of a 0.2 data directory from their
  recorded archetype, seeds and individuality; the engine refuses an unreset store.
* Context rules add `debugging` (two or more failed tool calls or error words),
  `planning` (plan mode, planning words), `writing`, and `error_present`.
* Benchmarks: the simulated-user benchmark scores five-level utilities; the
  development benchmark adds expression smoothness. Python and TypeScript SDKs,
  adapters (0.3.0) and the agent tool definition are updated.

## 0.3.0 groundwork — derived turn context (expressiveness upgrade, phase 1)

* Adapters no longer send a fixed context. They derive task type, stakes, channel
  and tags from host metadata with one shared rule table
  (`protocol/upap/v1/context-rules.json`, generated from `sdk/python/lite.py`) and
  `derive_context` / `deriveContext`, which conformance fixtures keep byte-identical.
* Signals: previous-turn tool names and failure counts (Claude Code `PostToolUse` /
  `PostToolUseFailure`, Hermes `post_tool_call`, OpenClaw `after_tool_call`, Pi
  `tool_execution_end`), Claude Code plan mode, Hermes platform and OpenClaw channel,
  and the user's declared context (`OPENAPE_CONTEXT`, or `.openape.json` for Claude
  Code). Tool arguments and results are never read.
* Opt-in `OPENAPE_CONTEXT_TEXT=local`: the user's message is matched against fixed
  keyword rules on the host; only the derived labels are sent. Tests assert that no
  prompt, tool argument or result text reaches requests or adapter state.
* Same vocabulary and decoder-v2; no engine or protocol change.

## Unreleased — human-like development (see docs/adr/0004-human-like-development.md)

* Temperament and individuality: the creation version is the persona's temperament
  and automatic core change stays within a radius of it; `individuality` (0-1,
  default 0.3) and `individuality_seed` vary the archetype profile reproducibly, so
  personas of one archetype are alike but not identical (`individuality: 0` is the
  exact archetype). CLI `--individuality`, `--individuality-seed`.
* Session state: consented in-session preferences (including `consent_scope:
  session`) fit an ephemeral latent offset applied for the rest of that session;
  feedback and reflection responses report `session_adapted`. Durably consented
  states are sampled at session end, and consistent states become a habit step.
* Lifelong plasticity: growth continues after the horizon at a slow adult rate;
  surface traits settle before interpersonal ones. Experience is weighted by
  novelty, and life events (role change, new host, correction bursts/ruptures)
  temporarily raise plasticity; audited as `life_event`.
* Relationships accommodate to the user's context tags over time and cool after
  long absences.
* Consolidation passes combine cooling, the curve step, habits and a self anchor
  that pulls back learned change it has not absorbed (unless feedback would be
  undone); core habituation replays decisions weighted by salience.
* Influence by maturity: owner feedback weighs more early and users' later, agent
  reflections gain weight and share with maturity, and older feedback weighs less.
* Inspect reports effective experience, growth, plasticity, boost, temperament
  version, individuality and character drift. `benchmarks/development.py` records
  developmental trajectory metrics (engineering only, not human evidence).

## Unreleased — archetypes and automatic evolution (see docs/adr/0003-automatic-evolution.md)

* Breaking: creating a persona requires a starting `archetype` (balanced, mentor,
  pragmatic_engineer, concierge, collaborator, analyst, critic), seed preferences or a
  snapshot parent. There is no implicit neutral default; use `archetype: balanced`.
* Automatic evolution (default for new personas): the engine consolidates consented
  feedback once enough new evidence exists, evaluates under stricter autonomous
  thresholds and promotes eligible candidates itself. Personas from 0.2.0 stay manual.
* Natural maturation on a square-root curve `sqrt(min(t/T,1))` over ended sessions,
  with a configurable rate (`fast`/`normal`/`slow` or explicit horizons):
  relationship familiarity per linked user and core habituation to served contexts.
  The steps are bounded, replayed in order and never undo consented preferences.
* Agent feedback tool: `POST /v1/reflections`, scope `reflection:write`, canonical
  `persona_feedback` tool definition, `reflect()` in the Python, lite and TypeScript
  SDKs, bridge `{"op":"reflect"}`; registered by the Claude Code (bundled stdio MCP
  server), Hermes, Pi and OpenClaw adapters in active mode.
* `POST /v1/personas/{id}/evolution`; inspect reports archetype, evolution policy
  and growth; capabilities list archetypes and maturation rates.
* CLI: `persona create --archetype`, `--maturation-rate`, `--manual`,
  `--no-agent-feedback`; `persona archetypes`; `persona evolution --pause/--resume`;
  `persona inspect --user`. `token add` defaults include `reflection:write`.

## 0.2.0 — experimental (review against the brief; see docs/reports/v0.2-review.md)

* decoder-v2: persona-conditioned auto-decoder on synthetic profiles, encoder/2
  one-hot features, 24-row audited catalogue; held-out persona few-shot metrics.
* Seed-preference initialization, subagent snapshot personas, frozen `pinned_version`,
  admin debug diagnostics, feedback `occurred_at`/`evidence_refs`.
* Independent evaluator owns split/scoring/thresholds; latent trust-region drift
  budget; REINFORCE mean baseline; duplicate judgements counted once.
* Lineage-based revocation replaces reset-everything.
* Stdlib `sdk/python/lite.py`; golden rendered-text conformance for Python and TS.
* Claude Code plugin with lifecycle hooks; Hermes and OpenClaw plugins fixed (both
  previously could not inject); Pi smoke extended; OpenCogni planner boundary patch.
* Real-host smokes for all five hosts against a synthetic model endpoint.
* CLI: token add, preview, job, adapter install/uninstall/doctor/migrate-soul.
* Simulated-user A/B/C/D benchmark (engineering evidence only).
* Breaking: catalogue, encoder and decoder hash changed; 0.1.0 sessions and exports
  are decoder-incompatible.

## 0.1.0 — experimental

* Rename the brief's project to OpenAPE (Agent Personality Engine), retain UPAP/1.
* Add standalone authenticated CPU service, neural decoder, SQLite/safetensors
  ledger, explicit feedback, isolated candidate evaluation, promotion and rollback.
* Add Python/Node clients, deterministic rendering, CLI and JSONL bridge.
* Add actual Pi SDK lifecycle/outage smoke with synthetic model transport;
  source-inspected examples for other hosts and explicit unsupported release gates.
* Publish reproducible synthetic training and local performance measurements.
* Full v1 release gates remain open; no measured personality efficacy claim.
