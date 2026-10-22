# Changelog

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
