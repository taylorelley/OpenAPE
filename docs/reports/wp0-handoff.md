# WP0: Baseline/discovery

Status: **PARTIAL**.

Implemented: Exact main source pins, hook capability matrix, current OpenCogni planner assessment, ADR, risk register and pinned Python toolchain.

Evidence/limits: Actual Pi SDK 1.3.0 inspected and exercised; four host integration gates remain open.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: docs/adapters/compatibility.md; ISSUE-001.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
