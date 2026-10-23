# ADR 0005 — Expressive controls: derived context, five-level traits and habits

Status: accepted (0.3.0, experimental)

## Context

Up to 0.2 the engine's rich state reached the model through a narrow channel:

* **24 rows.** Each turn picked one of 24 joint rows by argmax and rendered seven
  fixed sentences. That is under five bits per turn, with three levels per trait.
* **Fixed context.** Every adapter sent the same context (`general`, `terminal`,
  `medium`, `user`, no tags), so a persona produced one paragraph per provider.
* **Jumps, not growth.** Maturation, temperament, habits and fading all moved the
  latents smoothly, but the model saw that as rare swaps of the whole paragraph.

The safety design has to stay. The engine sends no free text. Every sentence comes
from a reviewed template. The Python and TypeScript renderers must produce
byte-identical text, failures must inject nothing, and learning must use consented
feedback only.

## Decision

**1. Context derived from host metadata (shipped first, no decoder change).**
* One rule table (`context-rules.json`, generated from `sdk/python/lite.py`) maps
  signals to the context vocabulary. Both SDKs apply it identically, and
  conformance fixtures enforce that.
* Signals: the previous turn's tool names and failure count (never arguments or
  results), plan mode, the host's channel, and the user's declared context
  (`OPENAPE_CONTEXT` or `.openape.json`).
* Classifying the user's message is opt-in (`OPENAPE_CONTEXT_TEXT=local`). It runs on
  the host, and only labels are sent.

**2. behaviour-controls/2.**
* Each trait has five levels with one reviewed sentence each (35 sentences).
  Reviewed coherence rules forbid six contradictory level pairs. Every passing
  combination is approved: 51 788 of 5^7.
* Sixteen reviewed signature habits, such as "Flag important risks or caveats
  early.", carry static eligibility on trait levels and exclusions. A turn uses at
  most three.
* Context masks act per level (humour ≤ 1 under high stakes, verbosity ≤ 2 when
  urgent) and per habit.
* A `catalogue_hash` binds decisions to the exact catalogue. The SDKs validate
  coherence, habit eligibility and the hash before rendering. Worst-case text is
  594 characters, under the 900 bound.

**3. decoder-v3 and encoder/3.**
* The same trunk with a 7×5 trait head and a 16-habit head.
* Selection is the best approved, unmasked configuration by summed per-trait
  log-probability, then eligible habits above one half.
* The context vocabulary adds the `debugging`, `planning` and `writing` task types
  and the `error_present`, `first_turn` and `long_session` tags. The engine sets the
  last two from its own session record and ignores host values.
* Training is factorised (per-trait cross-entropy plus habit binary cross-entropy).
  The latent prior is recalibrated so latent norms match the scale the drift
  budgets, character radius and state budget were set for.

**4. Learning in choice space.**
* Feedback options are `{controls, habits}` choices. A pairwise loss compares their
  scores.
* Reflections move named traits at least one level to the nearest approved,
  allowed configuration, and add or drop named habits.
* Session states, maturation (familiarity, accommodation, habituation) and the
  evaluator all use per-trait and per-habit targets.
* The logged-bandit term trains the configuration only, because habits are selected
  deterministically.

**5. upap/2, clean break.**
* The wire changes are not backward compatible: integer levels, habits,
  `catalogue_hash`, choice-valued feedback and the larger vocabulary.
* `upap/1` requests are rejected, and old clients fail open.
* Latents belong to their decoder, so a 0.2 store is reset rather than converted.
  `openape migrate --reset` re-creates each persona from its recorded archetype,
  seeds and individuality seed (the same temperament) and keeps its settings. Old
  decisions and feedback stay as untrainable history. The engine refuses to start
  on an unreset store.

## Consequences

* A persona now expresses a policy over contexts with graded traits and a few
  characteristic habits, instead of one paragraph. Archetypes differ in habits as
  well as tone. The development benchmark shows expression changing about 1.75
  traits at a time on average, rather than in whole-paragraph swaps
  (`benchmarks/reports/development.json`).
* Few-shot learning over the larger space needs the runtime trust region: without
  it, fitting from 16 preferences overshoots and does worse than the neutral latent
  (model card). Habits learn slowly from few preferences.
* All evidence remains synthetic. Whether five levels and 16 habits produce
  distinguishable live-model behaviour is unmeasured. The live-model harness in
  `benchmarks/live` (rendered controls → model → blind judge, measuring per-level
  distinguishability, habit adherence and task-quality parity) is built and tested
  offline. Running it is the gate for revising any template that a model does not
  distinguish.
* Learned state from 0.2 is lost at upgrade, by design.
