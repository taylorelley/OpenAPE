# ADR 0004 — Human-like development

Status: accepted (unreleased, experimental)

## Context

ADR 0003 made personas evolve without an operator. The persona still developed on
one clock with one setting. Every archetype was born identical. Maturation stopped
completely at the horizon. A session counted the same whether it was novel or the
hundredth repeat. Every relationship grew warmer, less formal and briefer on the
same schedule whoever the user was. Learned change stayed until someone rolled it
back. The owner asked for evolution that resembles how people's personalities
develop from birth into adulthood.

The brief's limits still apply. Evolution must not use task success, engagement,
inferred satisfaction or text as reward. Untrusted text has no authority. Every
durable change must stay an evaluated, audited, revocable version, and session pins
must hold.

## Decision

Each process is modelled on a finding from personality psychology. All processes
live in `engine/learning/development.py` and use only structured context, host
identity, consented feedback and server time.

1. **Temperament and individuality.** Temperament is present from birth and is
   relatively stable; character builds on it.
   * The creation version is recorded as the persona's `temperament`.
   * Automatic changes to the core are projected to stay within
     `CHARACTER_RADIUS` (1.6 latent units) of it. These are feedback candidates
     and consolidation passes. The projection is non-expansive and never pulls an
     operator-set state back.
   * At creation a recorded `individuality` seed (and an amount, default 0.3)
     varies the archetype's profile. The seed is derived from tenant and persona
     id unless one is given. The variation strengthens or weakens each declared
     preference and adds one or two mild leanings. Two mentors are therefore
     recognisably mentors but not identical. `individuality: 0` gives the exact
     archetype, and snapshots inherit their parent's individuality.

2. **State to trait** (Whole Trait Theory; TESSERA).
   * Consented in-session preferences (`consent_scope` session, relationship or
     core) refit a **session state**: a bounded offset of the relationship latent
     (core latent without a linked user).
   * The state is applied at express for that session only and is never a version.
     The session pin is unchanged.
   * The budget (1.4) follows the finding that within-person state variation is
     about as large as between-person differences (Fleeson 2001).
   * Its inputs follow training's rules: judgements are deduplicated by (decision,
     actor, kind) and limited to the newest 12, with source influence weights.
   * At session end, the state refitted on durably consented feedback only
     (relationship or core scope) is kept as a sample. Session-only consent never
     lasts.
   * When three or more recent samples are consistent, a habit step moves the
     latent toward their mean. Consistency is the mean's length over the mean
     length, at least 0.6. The step is scaled by plasticity and capped.
   * Habit steps carry their feedback ids as evidence, so revocation follows
     lineage. Revoking evidence also refits open session states and deletes
     samples that used it.

3. **Lifelong plasticity and sensitive periods.** Personality is most changeable
   when young but keeps changing through adulthood. The ADR 0003 square-root curve
   still sets development.
   * Growth is `g(t) = sqrt(min(t/T,1)) + 0.15 · max(0, t−T)/T`. After the horizon,
     steps continue at a slow adult rate and never stop.
   * Steps fall on whole units of effective experience, so a backlog still replays
     in order.
   * Surface traits (verbosity, formality, explanation depth) lose plasticity
     faster with maturity than interpersonal traits (warmth, directness,
     assertiveness, humour). Both keep a floor of 0.2. These per-trait weights
     scale the maturation targets.

4. **Novelty and life events.** People change most around role transitions.
   * Experience is *effective*: a session's weight is 0.5 + 0.5 × novelty, where
     novelty is 1/√(1+times its context signature was seen). The hundredth
     identical session counts about half as much as a new one.
   * Each scope (core, and each relationship) keeps a life record, from which
     events are detected.
   * **role_change:** the recent and long-run mix of task types diverge (total
     variation ≥ 0.5). The averages are bias-corrected, the check needs an
     established role (12 sessions), and hysteresis gives one event per
     transition. In simulation, a switch to new work is detected 3–4 sessions in,
     and random alternation within a stable role triggers it in under 4% of
     60-session lives.
   * **new_host:** core only.
   * **correction_burst / rupture:** at least two durably consented preferences
     from people in one session.
   * An event sets a boost of 3. The boost multiplies session weight and plasticity
     and decays by 0.6 per session. Events are audited as `life_event`.

5. **Relationships.**
   * **Accommodation.** Relationship steps also fit an accommodation profile drawn
     from the user's tag mix over time (an exponential moving average), growing
     with relationship maturity. Expert or urgent work leans brief. Beginner work
     leans patient and deep. Sensitive or beginner work leans warm. When a user's
     tags change, the relationship follows.
   * **Cooling.** After 14 or more days without a session (server time), the next
     consolidation shrinks the relationship latent toward zero: 0.1 per 30 days,
     at most 0.3. Continued use warms it again along the curve.
   * **Rupture and repair.** Corrections raise that relationship's plasticity
     through the event boost.

6. **Fade unless reinforced, and sleep consolidation.**
   * Maturation runs as one consolidation pass per due job, applying pending
     cooling, the next curve step, a consistent habit and the self anchor. The pass
     is evaluated once and promoted once.
   * The **self anchor** is a moving average of the persona's state. Deliberate
     change (cooling, curve steps, habits) is absorbed into it. Learned change it
     has not absorbed, such as automatically promoted feedback candidates, is
     pulled back by 25% of the difference at each pass. The anchor then moves 15%
     toward the result.
   * A pull that would reduce agreement with valid consented feedback is withheld,
     so feedback still wins. Rollbacks and operator promotions reset the anchor.
   * A pass with only the pull is due every three sessions while the gap is at
     least 0.1.
   * Core habituation replays the decisions since the last step weighted by
     salience: high stakes +1, and +2 when people gave feedback on the decision.

7. **Influence by maturity.** In automatic candidates and session states:
   * owner feedback weighs 2 − m and users' feedback 0.5 + 0.5m ("caregivers
     first");
   * agent reflections weigh 0.3 + 0.7m, and their allowed share relative to
     people's feedback grows from 0.2 to 1;
   * examples lose weight with recency rank (half-life of 300 examples).

   The independent evaluator still scores held-out evidence unweighted.

## Consequences

* Personas differ from birth and change more like people do. Every durable change
  is still one audited version gated by `evaluate_maturation` or the candidate
  evaluator, and every one can be revoked or rolled back.
* Session state is new behaviour within a pinned session. The version pin and
  decoder are unchanged, but the served controls can shift during the session after
  consented feedback. `capabilities.session_state` describes this.
* The constants are design priors chosen to be qualitatively plausible.
  `benchmarks/development.py` records trajectory metrics for them: rank-order
  stability, mean-level change, how far personas of the same archetype drift
  apart, and life events. Those metrics are a regression record, not validation
  against people (ISSUE-006).
* The decoder's 16 session-state input dimensions were never trained (always zero),
  so session state is an offset in the relationship or core latent instead.
  Retraining the decoder to use that slot is left for a future decoder version.
* New ledger tables (`states`, `samples`) and columns (persona `temperament` and
  `individuality`; maturation `effective`, `last_e`, `life`, `anchor`) are additive.
  Existing experience counts one effective unit per session. Personas without a
  recorded temperament use their first core version.
