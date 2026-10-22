# WP4: Learning and evaluation

**0.2.0 update:** Independent evaluator, latent trust region, REINFORCE baseline, lineage revocation and directional-learning tests (tests/test_learning.py). Simulated A/B/C/D in benchmarks/reports/simulated.json.

Status: **IMPLEMENTED EXPERIMENTAL**.

Implemented: Consent-scoped pairwise/bandit loss, canonical session grouping, frozen decoder, bounded jobs, fixed evaluator, drift limits, isolated candidates and manual promotion.

Evidence/limits: Synthetic held-out pairwise gain 0.9576, KL0.0610; independent user benefit and OS worker isolation unverified.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: docs/reports/offline-smoke.json; ISSUE-002/004/005.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
