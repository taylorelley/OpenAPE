# Four-condition evaluation

Conditions: **A** static markdown persona, **B** fixed approved controls (style-00),
**C** trained decoder with a frozen persona, **D** the same decoder after authorised
experience-driven persona learning. `baselines.py` renders each condition for a host
runner; use separate pinned persona/session IDs for C and D (`mode: frozen` with
`pinned_version`).

## 1. Simulated-user engineering benchmark (runs offline)

```sh
python -m benchmarks.simulated    # ~1.5 min; writes reports/simulated.json
```

24 simulated users with hidden random per-level trait utilities (a generator
different from decoder training, sealed seed 20261022, 10% answer noise). Each gives
24 explicit pairwise answers through the real API across two consolidation rounds
(independent evaluator, manual CAS promotion). Then 16 sealed contexts per user
(384 interactions) are scored for every condition. A is approximated by its closest
catalogue row because simulated users cannot read text.

Current result (`reports/simulated.json`; 20 promotions, 28 evaluator rejections):

| Condition | preference satisfied (top-4) | mean regret |
|---|---|---|
| A static markdown (approx.) | 0.013 | 1.69 |
| B fixed controls | 0.344 | 1.31 |
| C frozen neural persona | 0.143 | 1.68 |
| D learning-enabled | 0.430 | 0.82 |

Paired user-clustered bootstrap (95% CI): D−C satisfied +0.29 [0.14, 0.42];
D−B satisfied +0.09 [−0.11, 0.29] (**not significant**), D−B regret −0.49
[−1.02, −0.02]; C−B satisfied −0.20 [−0.37, −0.03] (the neutral neural persona's
context rules fit these simulated users worse than the neutral default).

**This is not human or live-model evidence.** The simulated users share the
catalogue's trait vocabulary, task correctness/safety are not simulated, and the
sample is small. `measured_behavioral_benefit` stays `false`.

## 1b. Developmental trajectory benchmark (runs offline)

```sh
python -m benchmarks.development    # ~1.5 min; writes reports/development.json
```

8 automatic personas (4 archetypes × 2 individuals, default individuality) live 48
sessions through the real API. Each serves a two-task role that switches at
session 32, after development completes. Each has a linked simulated user who
sometimes states a consented preference for one hidden catalogue row. Trait levels
are decoder diagnostics over six fixed contexts, checked every 8 sessions. It
compares trajectories with patterns from personality psychology
([ADR 0004](../docs/adr/0004-human-like-development.md)).

Current result (`reports/development.json`):

| Period (sessions) | 0-8 | 8-16 | 16-24 | 24-32 | 32-40 | 40-48 |
|---|---|---|---|---|---|---|
| rank-order stability | 0.96 | 0.88 | 0.87 | 0.98 | 0.99 | 0.99 |
| mean-level change | 0.03 | 0.19 | 0.21 | 0.04 | 0.02 | 0.02 |

* What matches people:
  * Change concentrates in the developmental period and then becomes small.
  * Rank order is least stable while personas develop and stabilises after.
  * Same-archetype personas end closer to each other (0.49) than to other
    archetypes (0.77), but are not identical.
* What does not match:
  * Stability stays well above the ~0.7 human plateau. The personas start as
    distinct archetypes and the sample is 8.
  * The role change at session 32 is detected (14 `role_change` events: core and
    relationship scopes for 7 of 8 personas). Its effect on traits is not
    visible, because adult steps are small.
  * The first period changes little: the familiarity target grows with maturity,
    so early steps have budget but little to move toward.
* Activity: the evaluated consolidation passes contained 286 curve steps, 42
  habit steps and 75 anchor pulls; there were 15 correction bursts and 15
  ruptures.

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
