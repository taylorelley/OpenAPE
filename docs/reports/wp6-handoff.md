# WP6: Claude Code/OpenClaw/OpenCogni

**0.2.0 update:** Claude Code plugin verified on 2.1.307 and OpenClaw plugin fixed/verified on 2026.10.5 (docs/reports/*-host-smoke.json). OpenCogni boundary patch in adapters/opencogni/upstream with passing unit suite; integration suites not run.

Status: **PARTIAL / UNSUPPORTED RELEASE GATES**.

Implemented: Claude UserPromptSubmit hook and OpenClaw before_prompt_build examples. OpenCogni Cordis companion service only; no planner effect and no upstream modifications.

Evidence/limits: Fixture and hook-subprocess tests only; actual host/model gates remain strict expected failures.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: docs/adapters/compatibility.md; ISSUE-001.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
