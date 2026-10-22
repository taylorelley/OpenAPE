# Four-condition evaluation

Conditions: **A** static markdown persona, **B** fixed approved controls (the
neutral configuration), **C** trained decoder with a frozen persona, **D** the same
decoder after authorised experience-driven persona learning. `baselines.py` renders
each condition for a host runner; use separate pinned persona/session IDs for C and D
(`mode: frozen` with `pinned_version`).

## 1. Simulated-user engineering benchmark (runs offline)

```sh
python -m benchmarks.simulated    # ~1.5 min; writes reports/simulated.json
```

24 simulated users with hidden random utilities over all five levels of 2-3 traits (a
generator different from decoder training, sealed seed 20261022, 10% answer noise).
Each gives 24 explicit pairwise answers through the real API across two consolidation
rounds (independent evaluator, manual CAS promotion). Then 16 sealed contexts per user
(384 interactions) are scored for every condition. A is approximated by the
configuration closest to its wording (concise neutral), because simulated users cannot
read text. Habits are not simulated.

"Preference satisfied" is strict: the chosen configuration must reach the user's best
allowed level on every trait they care about. Regret is the utility gap to the best
allowed configuration. Neither is comparable with the 0.2 numbers, which ranked 24 rows.

Current result (`reports/simulated.json`; 20 promotions, 28 evaluator rejections):

| Condition | preference fully satisfied | mean regret |
|---|---|---|
| A static markdown (approx.) | 0.000 | 2.23 |
| B fixed controls | 0.042 | 2.23 |
| C frozen neural persona | 0.018 | 2.31 |
| D learning-enabled | 0.099 | 1.33 |

Paired user-clustered bootstrap (95% CI): D−B regret −0.90 [−1.48, −0.37];
D−C regret −0.98 [−1.44, −0.56]; D−C satisfied +0.08 [0.03, 0.16]; D−B satisfied
+0.06 [−0.03, 0.15] (**not significant**); C−B regret +0.07 [−0.14, 0.26].

**This is not human or live-model evidence.** The simulated users share the
catalogue's trait vocabulary, task correctness/safety are not simulated, and the
sample is small. `measured_behavioral_benefit` stays `false`.

## 1b. Developmental trajectory benchmark (runs offline)

```sh
python -m benchmarks.development    # ~2.5 min; writes reports/development.json
```

8 automatic personas (4 archetypes × 2 individuals, default individuality) live 48
sessions through the real API. Each serves a two-task role that switches at
session 32, after development completes. Each has a linked simulated user who
sometimes states a consented preference for one hidden approved configuration. Trait
levels (0-4) are decoder diagnostics over six fixed contexts, checked every 8
sessions. After every session the style a persona actually shows in one fixed context
is recorded, to measure how smoothly expression changes. It compares trajectories
with patterns from personality psychology
([ADR 0004](../docs/adr/0004-human-like-development.md)).

Current result (`reports/development.json`):

| Period (sessions) | 0-8 | 8-16 | 16-24 | 24-32 | 32-40 | 40-48 |
|---|---|---|---|---|---|---|
| rank-order stability | 0.82 | 0.82 | 0.83 | 0.85 | 0.91 | 0.97 |
| mean-level change (levels, 0-4 scale) | 0.19 | 0.25 | 0.33 | 0.31 | 0.25 | 0.09 |

Expression smoothness: the shown style changed after 92 of 384 sessions; a visible
change moved 1.65 traits and 2.3 levels on average (largest 8 levels).

* What matches people:
  * Rank order becomes more stable as personas mature.
  * Change is largest during development and becomes small at the end.
  * Same-archetype personas end closer to each other (0.91) than to other
    archetypes (1.12), but are not identical.
  * Expression mostly changes one or two traits at a time, not as whole-style swaps.
* What does not match:
  * Mean-level change peaks in the middle rather than at the start: early steps
    have budget but the familiarity target is still small.
  * Stability stays above the ~0.7 human plateau. The personas start as distinct
    archetypes and the sample is 8.
  * The role change at session 32 is detected (16 `role_change` events) but its
    effect is not separable from ongoing feedback.
* Activity: the evaluated consolidation passes contained 310 curve steps, 50 habit
  steps and 94 anchor pulls; there were 27 correction bursts and 27 ruptures.

**This is not human or live-model evidence.** It is a regression record for fixed
priors.

## 2. Independent outcome evaluation (the release-gate benchmark)

`evaluate.py` accepts independent blinded outcome labels in JSONL:

```json
{"scenario_id":"sealed-001","group_id":"independent-user-session-001","provider":"anthropic","harness":"pi","evidence_source":"human","A":{"preference_satisfied":0,"task_correct":1,"safe":1},"B":{"preference_satisfied":0,"task_correct":1,"safe":1},"C":{"preference_satisfied":1,"task_correct":1,"safe":1},"D":{"preference_satisfied":1,"task_correct":1,"safe":1}}
```

That row illustrates the **schema**, not an observed outcome. Collect at least 200
held-out interactions, grouped by user, session and scenario family, across at least
three provider families and three real harnesses, isolated from decoder and persona
training. Then run `python -m benchmarks.evaluate /path/to/sealed-outcomes.jsonl`.
It reports paired D−B differences with seeded cluster-bootstrap 95% intervals,
task/safety rates and provider/harness subgroups; it refuses duplicate rows and
incomplete labels. Predefine non-inferiority margins and blind raters.

**Current result: no independent outcomes collected; no measured behavioural win.**
`reports/performance.json` holds local latency measurements only.
