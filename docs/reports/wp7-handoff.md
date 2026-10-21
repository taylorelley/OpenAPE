# WP7: Operations and portability

Status: **PARTIAL**.

Implemented: CLI/JSONL bridge, operational walkthrough, offline HTTP/restart runbook and restricted-token adapter installation instructions.

Evidence/limits: Offline lifecycle and actual Pi SDK path pass. Three-model/three-harness portability unmeasured; install/doctor automation missing.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: README.md; docs/walkthrough.md; ISSUE-001/003.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
