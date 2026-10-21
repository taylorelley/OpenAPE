# WP1: Protocol and SDK

Status: **PARTIAL**.

Implemented: Strict request/decision models, generated JSON Schemas/OpenAPI, shared decision fixtures, Python/TypeScript clients, CLI and renderers.

Evidence/limits: Shared fixture and fail-open tests pass; clients are manual, not fully generated.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: protocol/upap/v1; ISSUE-003.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
