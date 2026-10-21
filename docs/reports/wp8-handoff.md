# WP8: Benchmark/hardening/release

Status: **NOT RELEASE READY**.

Implemented: A/B/C/D interfaces, independent-outcome clustered-bootstrap evaluator, measured local latency, security regressions, CI and deployment files.

Evidence/limits: No independent behavioral outcomes or safety non-inferiority evidence; formal security/dependency audit incomplete.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: benchmarks/README.md; docs/reports/release-status.md; ISSUE-002/004.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
