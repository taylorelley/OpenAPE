# WP5: Pi and Hermes

**0.2.0 update:** Hermes plugin fixed and verified on hermes-agent 0.19.0 (docs/reports/hermes-host-smoke.json), including SOUL migration with backup. Pi smoke extended with model switch, compaction and multi-session.

Status: **PARTIAL**.

Implemented: Pi native extension plus Hermes source-inspected coexistence plugin. No SOUL edits.

Evidence/limits: Actual Pi SDK lifecycle, two-turn deduplication and engine-outage synthetic-transport turn pass. Hermes actual runtime unverified.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: docs/reports/pi-native-smoke.txt; ISSUE-001.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
