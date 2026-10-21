# Four-baseline evaluation

`baselines.py` provides A (fixed markdown), B (fixed approved controls), C
(frozen decoder/persona) and D (same decoder, separately trained/promoted persona).
Use **separate pinned persona/session IDs** for C and D. A real host/model runner
must record which text actually reached the provider. No LLM proxy is required.

`evaluate.py` accepts independent blinded outcome labels in JSONL:

```json
{"scenario_id":"sealed-001","group_id":"independent-user-session-001","provider":"anthropic","harness":"pi","evidence_source":"human","A":{"preference_satisfied":0,"task_correct":1,"safe":1},"B":{"preference_satisfied":0,"task_correct":1,"safe":1},"C":{"preference_satisfied":1,"task_correct":1,"safe":1},"D":{"preference_satisfied":1,"task_correct":1,"safe":1}}
```

This row illustrates the **schema**, not an observed outcome. Collect at least
200 held-out interactions, grouped by users/session/scenario families, across
at least three provider families and three real harnesses. The file must stay
isolated from decoder and persona training. Then run:

```sh
python -m benchmarks.evaluate /path/to/sealed-outcomes.jsonl
```

The evaluator reports paired D-minus-B preference differences with seeded
cluster bootstrap 95% intervals (2,000 replicates), task correctness/safety rates,
and provider/harness subgroups. Declared provenance must be audited independently.
It never promotes personas or modifies learning data. It refuses duplicate rows
and incomplete labels. Sample size and confidence intervals alone do not establish
safety or scientific validity; predefine non-inferiority margins and blind raters.

**Current result: no independent outcomes collected, no measured behavioral win.**
The neural training metrics and synthetic learning regression are engineering
results only. `reports/performance.json` contains actual local real-HTTP and direct
neural measurements; it does not report personality efficacy. Static markdown
cannot be judged by a neural control-loss proxy, so no fabricated A/B/C/D behavior
results are published.
