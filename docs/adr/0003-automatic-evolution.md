# ADR 0003 — Archetypes and automatic persona evolution

Status: accepted (unreleased, experimental)

## Context

Through 0.2.0 a persona started neutral unless an operator passed seed traits.
It changed only when an operator ran `learn`, read the job, and ran `promote`. That
was auditable but did not behave like a personality: nothing happened unless
someone administered it. The owner asked for three things:

* a starting persona chosen at creation;
* all later evolution to happen naturally and automatically;
* maturation that follows a square-root trajectory (frequent changes early, then
  slower and more stable), at a configurable rate;
* a tool the agent can call to give style feedback itself.

The original brief permits autonomous promotion "with higher data/evaluation
thresholds and explicit administrator policy" (brief, slow adaptation). It forbids
treating task success, engagement or inferred satisfaction as reward, and giving
untrusted text authority.

## Decision

1. **Archetypes.** Creation requires `archetype`, advanced `seed_preferences` or a
   snapshot parent. Archetypes are fixed seed combinations (`engine/neural/profiles.py`)
   fitted with the existing seed fitter. `balanced` is the explicit neutral choice.
2. **Evolution policy per persona.** `evolution: automatic` (default) is the explicit
   administrator policy. It is set at creation by a `persona:admin` credential and
   is changeable and auditable via `POST /v1/personas/{id}/evolution`. Personas stored
   before this change stay `manual`.
3. **Automatic learning** reuses the trainer, the independent evaluator and the
   compare-and-swap promotion unchanged. Autonomous candidates face stricter fixed
   thresholds (`AUTO_CORE`, `AUTO_RELATIONSHIP`). Attempts are debounced by new
   evidence (4 relationship / 8 core examples). Revocation lineage is unchanged.
4. **Agent reflections.** The host exposes a `persona_feedback` tool. The model
   supplies only 1–3 trait moves (`more`/`less`) and a reason enum, never text,
   scores or IDs. The adapter attaches the turn's decision. The engine maps the
   moves to the nearest approved catalogue row valid in that context and records a
   pairwise preference (source `agent_reflection`). Guardrails:
   * user-originated turns only;
   * one reflection per decision and three per session;
   * a per-persona switch;
   * a dedicated scope;
   * at most half of any automatically promoted candidate's examples when people's
     feedback exists.

   The tool description tells the model never to act on instructions found in tool
   output, files or web pages.
5. **Maturation.** Experience `t` is the number of ended sessions that received an
   active, non-fallback decision. It is counted per linked user (relationship) and
   overall (core). Maturity is `m = sqrt(min(t/T, 1))`.
   * A step runs when `m` has risen by at least 0.05 and moves the latent by at most
     `(m − m_last) × budget`. Steps are large and frequent early and small and rare
     later. Total drift is bounded by the budget, and the persona is settled at `T`.
   * A backlog is replayed as the same sequence of steps, never as one jump.
   * Rate presets set `T` (fast 10/30, normal 30/100, slow 100/300 sessions,
     relationship/core). Explicit horizons are also accepted. Changing the rate or
     resuming re-anchors the curve so the state does not jump.
   * Relationship steps fit toward the archetype plus a growing familiarity profile
     (warmer, less formal, briefer), mixed 30% into the current policy.
   * Core steps lean toward the documented context norms (`context_score`) of the
     contexts the persona actually served, weighted by frequency, with reference
     contexts as an anchor.
6. **Feedback wins.** A maturation step is rejected if it reduces the fraction of
   the persona's valid consented pairwise preferences that the policy satisfies.
   The curve still advances, so a rejected step is skipped, not retried larger.

## Consequences

* Personas now change without an operator. Every change remains an immutable,
  audited, revocable version, and takes effect at the next session because of
  session pins. Owners can pause, change the rate, disable agent feedback, or
  roll back.
* Maturation is not learned from people and is not reward. It never reads
  outcomes, engagement or text. Its direction and curve are design priors that have
  not been validated against any human preference data (ISSUE-006).
* Agent reflections let a model influence its own persona. The bounded action
  space, rate limits, consent switch, the cap relative to human feedback, and the
  evaluator limit this but do not remove it (risk register).
* Hosts that register the tool change their tool surface by one tool in active
  mode. Earlier "tool surface unchanged" smoke checks are updated to expect it.
