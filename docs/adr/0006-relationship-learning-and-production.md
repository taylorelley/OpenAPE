# ADR 0006: Relationship controls, separate habit learning and multi-replica operation

Status: accepted (experimental). Builds on ADR 0005.

## Context

0.3.0 made a persona's state expressible (seven five-level traits, signature habits).
Several gaps remained. Habit evidence dragged the traits. A new relationship
started from nothing. Users could not state hard preferences or stop a relationship
from changing. Nobody could see why a style was chosen. The engine ran as one
process with an in-process evaluator.

## Decisions

### Learning

* **Habits learn beside the latent.** A habit preference moves a per-version habit
  bias, not the latent (`engine/learning/habits.py`):
  `clip(4 · Σ weight · ±1, ±4)` over the scope's valid habit evidence. A habit-only
  pair no longer reaches the trait fit. A new automatic `habit` job promotes a version
  with the same latent and the new bias, gated on finiteness, bounds and a real change.
  Its evidence ids give it lineage, so revocation reverts it.
* **A person's request counts in full; an agent's does not.** A person's habit
  request has weight at least 1, so one request reaches the cap. An agent's
  reflections alone move a habit at most halfway (±2), because text the agent reads
  can steer them. Reflections may never weaken `flag_uncertainty` or `risks_first`.
* **Session state is anchored.** The session's latent offset fits the stated trait
  preference with a KL anchor on the traits and habits the preference does not
  mention. A request for "shorter" changes verbosity, not formality. Habits asked
  for in a session apply at once through a session habit offset.
* **Cohort prior, opt-in.** A relationship without a version starts from the mean of
  at least five relationships whose users opted in (`cohort_contribution`), shrunk by
  `n/(n+5)`. Frozen relationships do not contribute. No single user's state is ever
  used.
* **Exploration, opt-in.** With `exploration` set, low-stakes user turns are logged
  under an ε-mixture policy (ε = 0.15) with true propensities, so ratings on them are
  usable bandit evidence. `POST /v1/comparisons` returns the served style and the
  persona's best different configuration in a blind order. The answer is ordinary
  pairwise feedback.
* **Episodic meta-training stays off.** It gave no held-out gain (model card).

### Relationship controls (user settings)

`GET/PUT /v1/personas/{id}/users/{user}/settings`, scope `settings:write`, only for
a credential allowed to act for that user. The settings are:

* `preferences`: enumerated slots, each rendering one reviewed sentence.
* `pins`: allowed level ranges per trait. Context safety masks always win, and pins
  no approved configuration satisfies are refused.
* `vetoes`: habits never used.
* `frozen`: stops relationship learning, maturation and session state. The core
  still matures.
* `cohort_contribution` and `exploration`.

There is no free text anywhere.

### Context

* Adapters add file languages and the repository kind (marker names only) to the
  derived context. The engine adds `returning` and `corrected`.
* The opt-in text classifier is a hashed-feature linear model evaluated identically
  in Python and TypeScript (argmax and sign only).
* A repository's `.openape.json` is **untrusted**. It is read as a regular file of at
  most 64 KB, without following links or blocking. It may name the task, language,
  repo kind and tags and raise stakes. It may never lower stakes or set channel or
  turn origin.

### Visibility

* `GET /v1/decisions/{id}/explanation` attributes each trait to a layer by
  recomputing the decoder's expected level as each layer is added: temperament,
  character, relationship, session. It reports limits (context, pins) and gives each
  habit's decoder probability, learned bias and state.
* `GET /v1/personas/{id}/timeline` lists versions with expected levels in a
  reference context.
* `openape dashboard` writes a self-contained page.
* Sentences come from fixed templates and are never injected into a model.

### Production

* **Isolated evaluator.** Candidate and maturation evaluation run in a spawned
  process that loads the decoder from disk and checks its hash. The report records
  the isolation mode (`OPENAPE_EVALUATOR=inline` for tools).
* **PostgreSQL for several replicas.** `OPENAPE_DATABASE_URL` selects it. The
  engine's SQLite SQL is translated at the store boundary. Artifacts live in a table,
  and every write transaction takes one advisory lock, so writes serialize across
  replicas as they do in SQLite. A queued automatic job older than 15 minutes counts
  as lost with its replica. Rate limits stay per replica.
* `compose.replicas.yaml` runs two replicas on PostgreSQL 16.

## Consequences

* Writes serialize globally. This is simple and correct, and throughput is bounded
  by one writer at a time; per-persona locks are the next step if needed.
* `openape migrate --reset` remains SQLite-only.
* The cohort prior and exploration are off unless users opt in. Without five
  contributors the prior does nothing.
* Habit learning is a bounded rule, not a fitted model. It is transparent and
  revocable, and it does not generalise across contexts.
