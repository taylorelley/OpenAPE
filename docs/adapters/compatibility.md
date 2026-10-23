# Host compatibility — verified 2026-10-22

All integrations coexist with host instructions. None replaces tool policy, SOUL.md,
CLAUDE.md or AGENTS.md. Provider, sender and user identifiers are never silently
linked; a linked user must be configured explicitly with a scoped token. Fresh
installs default to shadow; set `OPENAPE_MODE=active` intentionally.

"Real host" below means the published host package/CLI ran a full turn with the
plugin loaded, against a **local synthetic model endpoint** that records request
bodies. No live provider model was called. Reports: `docs/reports/*-host-smoke.json`.

| Host (pinned) | Surface | Real-host smoke | Known limits |
|---|---|---|---|
| **Claude Code 2.1.307** | Plugin (`.claude-plugin`, `hooks/hooks.json`): `UserPromptSubmit` → `hookSpecificOutput.additionalContext`; observations from `SessionStart`, `Stop`, `StopFailure`, `PostCompact`, `PostModelSwitch`, `SessionEnd`. Stdlib-only Python hook. | PASS 10/10: style reached the model once per turn, as a per-turn message after the prompt (not the system prompt); resume; compaction observed; shadow; two personas → different controls; linked `turn.completed`; feedback; engine outage fail-open. | Claude Code keeps earlier turns' context in history (2 copies after one resume). `PostModelSwitch` only fires on interactive `/model`; `StopFailure` path not exercised. Subagent contexts (`agent_id`) opt out. |
| **Hermes Agent 0.19.0** | `pre_llm_call` → `{context}` appended to the API copy of the current user message; `post_llm_call`, `on_session_end`; `subagent_start` marks child sessions to opt out. Settings via profile-scoped `get_secret`. | PASS 13/13: once in the current user message; SOUL.md still in the system prompt; resume; **prompt-cache prefix byte-stable** across turns; shadow; linked observation; feedback; migration dry run and apply with backup; doctor; outage fail-open; uninstall. | Hermes has no supported setting to omit SOUL.md while keeping project context files, so coexistence is the default. 0.1.0's plugin called a non-existent `ctx.get_config` and could never inject. |
| **OpenClaw 2026.10.5** (Node ≥24.16) | `before_prompt_build` → `appendContext`; `agent_end`. Manifest `activation.onStartup`; host config must `plugins.allow` it and grant `allowPromptInjection` / `allowConversationAccess`. | PASS 9/9 on the embedded runner (`openclaw agent --local`): once per turn; tool surface identical with/without plugin; disabled makes no call; shadow; linked observation; feedback; outage fail-open. | OpenClaw stores appendContext in each user message (history grows ~1 block per turn). Embedded runner supplies no `currentUserMessageId`; the run id is used instead. Gateway channels and Codex/Copilot harnesses untested. 0.1.0's plugin required the admission id and never injected here. |
| **Pi 1.3.0** (`@earendil-works/pi-coding-agent`) | `before_agent_start` → hidden custom message; `context` removes stale copies; `agent_end`, `session_shutdown`. | PASS (actual SDK session, synthetic transport): single copy per turn across history; model switch; compaction; second concurrent session; one persona version across sessions; outage fail-open. | Child-process lineage unverified; custom/background triggers opt out. Pi 1.4.0 exists but is untested. |
| **OpenCogni 833f4e6** + `adapters/opencogni/upstream/0001-*.patch` | `HttpPlannerOptions.presentationStyle` (patch) fed by the OpenAPE `brain.personality` Cordis service. Delimited user-role data (never a system message) limited to summary/rationale wording, at most 1400 chars, counted in the input budget, 300 ms fail-open. | PASS 4/4 with the real patched `planner.http`: plan validated; style isolated; decision id, persona version and decoder hash logged; outage fail-open. OpenCogni unit suite: 76 passed / 1 skipped (5 new contract tests); typecheck and lint clean. | **Requires the upstream change**, under review as taylorelley/opencogni#8 (not merged). OpenCogni integration/evaluator suites need nats-server and PostgreSQL and were not run. Without the patch the companion has no planner effect. |

## Install / uninstall

`openape adapter install HOST` prints (or, for Hermes, performs) the documented
installation; `openape adapter doctor HOST --persona ID` checks the engine, token,
persona, host binary and plugin files. Use `openape token add --actor HOST
--personas ID` to mint a restricted host token (`persona:express`,
`observations:write`), then restart `openape serve`.

* Claude Code: `claude plugin marketplace add /path/to/OpenAPE` and
  `claude plugin install openape@openape`, or `claude --plugin-dir adapters/claude-code`
  per session. Configure `OPENAPE_*` via the environment or settings `env`.
* Hermes: `openape adapter install hermes` copies the plugin to
  `$HERMES_HOME/plugins/openape`; then `hermes plugins enable openape`. Store
  `OPENAPE_*` in the profile's secrets. `openape adapter migrate-soul` is a dry run;
  `--apply --persona ID` writes `SOUL.md.openape-backup-<UTC>` first, keeps
  operational lines, removes style-only lines and creates a seeded persona.
* OpenClaw: `openclaw plugins install adapters/openclaw` (or `plugins.load.paths`),
  add `openape` to `plugins.allow`, grant the hooks shown in `config.example.json`.
* Pi: `pi -e /path/to/OpenAPE/adapters/pi/index.ts`; keep the repository layout.
* OpenCogni: apply the upstream patch in the OpenCogni repository (separate review),
  then pass `personalityPlugin(client, cfg).presentationStyle` as
  `http.presentationStyle` in the models configuration.

Outcome observations carry IDs and status only, never rewards or transcript text,
and have no learning authority.

## Turn context

Each adapter derives the turn context with the SDK's `derive_context` /
`deriveContext` from the shared
[`context-rules.json`](../../protocol/upap/v2/context-rules.json) (parity fixtures in
`conformance.json`). Signals are tool names and failure counts from the previous
turn, host state and the user's declared context (`OPENAPE_CONTEXT`). Tool arguments
and results are never read. The user's message is classified only with
`OPENAPE_CONTEXT_TEXT=local`, in memory on the host; only enum labels are sent.

| Host | Tool signal | Other signals | Message (opt-in) |
|---|---|---|---|
| Claude Code | `PostToolUse` / `PostToolUseFailure` (`tool_name`) | plan mode (`permission_mode`), `.openape.json` in `cwd` | `prompt` |
| Hermes | `post_tool_call` (`tool_name`, `status`) | `platform` → terminal / chat / background | `user_message` |
| OpenClaw | `after_tool_call` (`toolName`, `error`) | run `channel` / `messageProvider` → chat | `currentUserMessage` |
| Pi | `tool_execution_end` (`toolName`, `isError`) | — | `prompt` |
| OpenCogni | — | fixed planner context | — |

The hook and field names were checked against the pinned host packages' sources
and types. Derived context has not yet been exercised in the real-host smokes;
each manifest lists it under `unverified`.

## Agent feedback tool (`persona_feedback`)

In active mode, adapters offer the agent one tool, defined in
[`protocol/upap/v2/tools/persona_feedback.json`](../../protocol/upap/v2/tools/persona_feedback.json).
The model supplies trait and habit moves only; the adapter attaches the turn's decision.
`OPENAPE_AGENT_FEEDBACK=0` disables it, and the host token needs `reflection:write`.

| Host | How the tool is offered | Smoke evidence (synthetic model) |
|---|---|---|
| Claude Code | stdio MCP server bundled with the plugin (`mcp_server.py`, declared in `plugin.json`); reads the latest decision the UserPromptSubmit hook recorded for the persona | Listed as deferred tool `mcp__plugin_openape_openape__persona_feedback` in active mode, absent in shadow (2.1.308). `tests/test_agent_tool.py` drives hook + MCP server against a real HTTP engine. |
| Hermes | `ctx.register_tool` in toolset `openape` (`provides_tools` in plugin.yaml); `check_fn` hides it outside active mode | Offered as a direct tool in active mode, absent in shadow (0.19.0) |
| Pi | `pi.registerTool` | Registered and called through Pi's tool wrapper; reflection recorded by the engine (1.3.0) |
| OpenClaw | `api.registerTool` factory; `contracts.tools` declares it | Direct tool schemas unchanged; listed in the embedded runner's Tool Search catalog in active mode only (2026.10.5) |
| OpenCogni | not offered: the planner patch has no tool hook | — |

Limitation: in Claude Code the MCP server cannot see the host session ID, so with
several concurrent sessions on one persona a call attaches to the most recent
decision (within one hour). The engine still enforces the actor, the
one-per-decision limit and the three-per-session limit.

