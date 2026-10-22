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
| **OpenCogni 833f4e6** + `adapters/opencogni/upstream/0001-*.patch` | `HttpPlannerOptions.presentationStyle` (patch) fed by the OpenAPE `brain.personality` Cordis service. Separate lower-priority system message limited to summary/rationale wording, counted in the input budget, 300 ms fail-open. | PASS 4/4 with the real patched `planner.http`: plan validated; style isolated; decision id, persona version and decoder hash logged; outage fail-open. OpenCogni unit suite: 74 passed / 1 skipped (3 new tests); typecheck and lint clean. | **Requires the upstream patch** (not merged; kept separately reviewable). OpenCogni integration/evaluator suites need nats-server and PostgreSQL and were not run. Without the patch the companion has no planner effect. |

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
