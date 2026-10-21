# WP2: Engine and persistence

Status: **IMPLEMENTED EXPERIMENTAL**.

Implemented: Scoped auth, persona creation/list/metadata/history, sessions/relationships, event/feedback idempotency, immutable artifacts, core export/import, rollback and deletion.

Evidence/limits: Restart, scope denial, corrupt state, replay, export, deletion and CAS tests pass.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: tests/test_engine.py; docs/reports/offline-smoke.json.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
