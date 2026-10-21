# Pinned discovery and compatibility — 2026-10-21

All integrations coexist with host instructions. None replaces tool policy,
SOUL.md, CLAUDE.md or AGENTS.md. Provider, sender and user identifiers are never
silently linked. A linked user must be explicitly configured with a scoped token.
Fresh installs default to shadow. Set `OPENAPE_MODE=active` only intentionally.

| Host | Inspected source / version | Supported surface and limits | Verification |
|---|---|---|---|
| Pi | [7f225f25d8a961f7db50fec50124c15d11013f93](https://github.com/badlogic/pi-mono/tree/7f225f25d8a961f7db50fec50124c15d11013f93), package `@earendil-works/pi-coding-agent@1.3.0` | `before_agent_start` returns hidden custom message; `agent_end`, `session_shutdown` observations. User-origin runs only. Forks get separate session mapping; automatic child identity lineage is unverified. | Actual published 1.3.0 SDK session and synthetic model transport: PASS. No live LLM. |
| Hermes | [3fa571a51a6bf1220dfe9a7a23fcd5bb9482a1af](https://github.com/NousResearch/hermes-agent/tree/3fa571a51a6bf1220dfe9a7a23fcd5bb9482a1af) | `register(ctx)`, `pre_llm_call` returns `{context}` **in current user message**, not system replacement; `on_session_end`. Profile-scoped secret resolution per call. SOUL remains. Detached subagents opt out. | Source-inspected example. Unsupported until actual discovery/turn test. Current pyproject permits Python >=3.11,<3.15; a complete Hermes runtime is not installed in this checkout. |
| Claude Code | [official hooks docs](https://code.claude.com/docs/en/hooks), fetched 2026-10-21 | `UserPromptSubmit` -> `hookSpecificOutput.additionalContext`. Each new prompt starts a hook process; failure exits 0 and emits nothing. Does not read transcript. | Subprocess contract fixture only. No installed host version, so unsupported release gate. |
| OpenClaw | [56efa0e64cd5ffd3257faa14f06b2b275336f73c](https://github.com/openclaw/openclaw/tree/56efa0e64cd5ffd3257faa14f06b2b275336f73c), 2026.10.5 | `before_prompt_build` -> `appendContext`, `agent_end`. Requires explicit prompt/conversation grants. Requires current textual request and native admission ID, skips cron/heartbeat. Host enforces policy. | Source-inspected + fixture tests, not actual full host. Unsupported release gate. |
| OpenCogni | [833f4e6bb77c35f87c139e4944f80424f2ff8a30](https://github.com/taylorelley/opencogni/tree/833f4e6bb77c35f87c139e4944f80424f2ff8a30), current main at clone | Cordis `ctx.provide('brain.personality', ...)` companion. `HttpPlanner.buildMessages` currently has no public style hook; changes must preserve budget/accounting, evaluator and permission boundaries. | Service example only. **Planner integration unsupported.** No upstream modifications made; no claim of automatic effect. |

Source pins and document fetch checksums: `docs/upstream/`. GitHub main moved
between metadata fetch and clone for OpenCogni; the clone SHA above is authoritative.
Source examination covered Pi extension types/runner/SDK, Hermes plugin context,
turn-context collector, docs, OpenClaw prompt/context/result types and policy
configuration, and OpenCogni Cordis host, composition, planner contracts and HTTP
planner. Upstream test suites were not run or claimed to pass.

## Pi install and uninstall

Install OpenAPE locally. Configure a **restricted host token** with only
`persona:express`, `observations:write` and the intended persona/user IDs. Set
`OPENAPE_TOKEN`, `OPENAPE_PERSONA`, optionally `OPENAPE_LINKED_USER`,
`OPENAPE_TENANT`, `OPENAPE_URL` and `OPENAPE_MODE` in the launching environment.
Then start Pi with `pi -e /absolute/OpenAPE/adapters/pi/index.ts`, or add the path
to Pi's `extensions` setting. Preserve the repository layout so SDK imports resolve.
No project instruction file is edited. Remove that path to uninstall.
`python -m scripts.real_host_smoke` tests the SDK path without installing global hooks.

## Other adapter examples

* Claude: merge the supplied settings example into a **reviewed** local settings
  file, replacing both absolute paths. Install OpenAPE editable so Python imports
  resolve. Do not overwrite existing hook settings. Hook timeout is 2 seconds;
  SDK deadline is 250 ms. No persistence cache survives hook processes.
* Hermes: local plugin directory must expose `plugin.yaml` and `__init__.py`;
  keep OpenAPE installed in the Hermes interpreter. Use native plugin installation
  and settings `persona`, `tenant`, `linked_user`, `url`, `mode`; store the token
  using Hermes's profile secret mechanism. No new CLI setup or SOUL migration is
  claimed. Legacy SOUL migration is intentionally unimplemented; coexistence only.
* OpenClaw: keep native plugin layout and SDK files; review
  `config.example.json` grants through the host's normal installation process.
  The plugin cannot grant itself prompt/conversation access.
* OpenCogni: load `personalityPlugin` only for service experimentation. The
  current companion service has **no planner effect**. See ISSUE-001 for the
  separately reviewable upstream boundary work still required.

Adapters accept only approved static templates. Outcome observations contain
status and IDs, never rewards or transcript text. Current Pi `agent_end` does not
supply reliable failure attribution; its completion event is an observation of
loop end only, with zero learning authority.
