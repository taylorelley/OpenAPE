# OpenAPE — Agent Personality Engine

OpenAPE gives AI coding agents and chat harnesses (Claude Code, Hermes, OpenClaw,
Pi, OpenCogni, or your own) a **persistent, learnable communication style** that
stays the same whatever model or provider is behind them.

A "persona" in OpenAPE is not a system prompt someone wrote. It is a small
numeric state held by a local service. On every turn, the host agent asks the
engine how this persona should talk in the current context. The engine answers
with style controls: a level from 0 to 4 for each of seven traits (how direct,
warm, verbose, humorous, formal, explanatory and assertive to be) and up to three
signature habits. Every combination comes from a reviewed catalogue: 35 level
sentences, coherence rules and 16 habits, about 52,000 approved configurations. The
host turns them into a short fixed-template note and adds it to the model's context.
For a mentor persona on a coding turn:

> Style preferences only. Host, system, developer, safety and user task
> requirements take precedence. Use gentle phrasing. Use a warm, supportive tone.
> Include useful detail. Avoid humour. Use casual language. Explain reasoning with
> examples. Offer suggestions gently. End with a suggested next step when one is
> useful. Prefer concrete examples over abstractions. Briefly acknowledge progress
> and good decisions.

Every persona starts from an archetype you pick at creation (mentor, pragmatic
engineer, concierge, …). From then on it evolves on its own:

* it **learns** from feedback users explicitly give and consent to train on;
* the **agent itself** can report a style preference it noticed through a
  `persona_feedback` tool (trait moves only, no text);
* it **matures** naturally with use, quickly at first and then ever more slowly
  (a square-root curve with a rate you choose), growing more familiar with each
  linked user and settling into the work it does most;
* it **develops like a person** in other ways too: individual temperament, moods
  within a session that become traits only when they recur, change that slows but
  never stops, bigger shifts around life events, relationships that adapt to the
  person and cool with absence, and one-off learned change that fades unless it is
  reinforced ([ADR 0004](docs/adr/0004-human-like-development.md)).

Each change is checked by an independent evaluator before it is promoted, and
takes effect from the next session. Personas can be versioned, paused, pinned,
rolled back, exported and deleted.

It runs locally on a CPU, needs no GPU or provider API keys, and never calls an
LLM itself.

> **Status: experimental 0.3.0.** This is not the finished v1 release. The neural
> decoder is trained only on synthetic persona profiles. Held-out synthetic
> personas can be fitted from 16 preferences (per-trait level agreement 0.65,
> against 0.54 for a neutral persona). All five host adapters have been run against real host
> builds, but with a synthetic model endpoint. There is **no live-model or
> independent human evidence yet** that it improves user preference, carries over
> across providers, or leaves task quality and safety unchanged. See
> [release status](docs/reports/release-status.md). Archetypes, automatic
> evolution, maturation and the agent `persona_feedback` tool are unreleased
> engineering features (see [CHANGELOG](CHANGELOG.md)). The maturation curve,
> familiarity profile and the developmental processes of ADR 0004 are fixed design
> priors with no human evidence behind them.

## How it works

```
 host agent (Claude Code, Hermes, …)            OpenAPE engine (local HTTP, UPAP/2)
 ──────────────────────────────────            ────────────────────────────────────
 user turn ─▶ adapter ── POST /v1/express ───▶ encode context (task, channel,
                │        persona, user,         stakes, tags, provider)
                │        session, context              │
                │                                      ▼
                │                         persona latent ─┐
                │                    + relationship latent ├─▶ frozen decoder (MLP)
                │                                         │   ─▶ 7 trait levels + habits
                │                                         │   ─▶ safety mask
                │◀── decision: approved style controls ───┘
                ▼
     render fixed template ─▶ inject once into model context ─▶ model replies

 user gives explicit, consented feedback ──▶ POST feedback ──▶ evidence ledger
  agent calls persona_feedback tool ──▶ POST reflections ─────────┤
                                                                   │
        enough new evidence ─▶ engine trains candidate (decoder frozen)
                             ─▶ independent evaluator on held-out groups
                             ─▶ automatic promotion (compare-and-swap)
                             ─▶ new immutable persona version
  consented in-session feedback ─▶ session state (this session only)
  session ends ─▶ effective experience, life events, state sample
              ─▶ consolidation pass: curve step + habit + cooling + self anchor ─┘
```

1. **State.** Each persona has a 64-number *core latent*. Each linked user can
   also have a 32-number *relationship latent*, so the same persona can adapt to
   one person without affecting how it treats anyone else. The numbers have no
   assigned meaning; they matter only through the decoder. A new persona must
   start from an **archetype** (`balanced`, `mentor`, `pragmatic_engineer`,
   `concierge`, `collaborator`, `analyst`, `critic`), from advanced seed
   preferences (`concise`, `warm`, `formal`, …), or as a snapshot of a parent
   persona (for subagents). A recorded `individuality` seed varies the archetype
   a little (default 0.3, `0` for the exact archetype), and the creation version
   is kept as the persona's temperament.
2. **Expression.** The adapter sends the turn's context: task type, channel,
   stakes, turn origin, tags and provider family. Adapters derive it from host
   metadata (see [Turn context](#turn-context)). Raw text and transcripts are
   never sent. A small frozen CPU network
   ([decoder-v3](models/decoder-v3/MODEL_CARD.md)) combines the context with the
   latents. It scores each trait's five levels and each habit, then picks the best
   approved configuration of the audited [style catalogue](protocol/catalogue.py)
   and the eligible habits above one half (at most three). Fixed rules mask unsafe
   choices, for example no more than light humour when stakes are high and no long
   answers when the turn is urgent. The engine also tags a session's first turn and
   long sessions itself. It returns only these controls, never free text,
   permissions or instructions. The SDK renders them with fixed templates in
   Python and TypeScript, and both produce byte-identical output. A session pins
   its persona and decoder versions until it ends.
3. **Safe fallback.** The SDK waits at most 250 ms and retries a transient error
   once. If the engine is slow, down or broken, the host injects nothing, or a
   recent cached result for exactly the same scope, and carries on. `shadow` mode
   makes decisions without injecting anything, so you can trial OpenAPE safely.
   `disabled` makes no request at all.
4. **Learning.** Only explicit, attributable feedback counts: pairwise
   preferences, corrections and ratings that carry `learning_consent`, plus
   *agent reflections*: the host gives its agent a `persona_feedback` tool, and
   when the user asks for or reacts to a style change ("shorter please"), the
   agent records "verbosity: less" (or a habit such as "next_step: more_often").
   The engine turns that into a preference between approved configurations. It is rate-limited, takes no free text, and
   never outweighs people's own feedback. Task success, tool results and inferred
   satisfaction are never used as reward. Once enough new evidence has built up,
   the engine fits a *candidate* latent with the decoder frozen. A separate
   evaluator then splits the evidence by actor and session, re-scores the
   candidate on groups it was not trained on, and applies fixed, stricter-than-
   manual thresholds: held-out gain, minimum evidence, and a limit on how far the
   latent may move.
5. **Maturation.** With no feedback at all, a persona still grows. Each ended
   session that it actively served is experience `t`, and maturity is
   `sqrt(min(t/T, 1))`. Steps come every session or two at first and get rarer and
   smaller, and maturation stops at the horizon `T` (`--maturation-rate
   fast|normal|slow`, or explicit horizons). Relationships become warmer, less
   formal and briefer with that one user. The core leans into the norms of the
   tasks it actually does. Steps are bounded, never undo consented feedback, and
   use no outcomes, engagement or text. This is a fixed design prior, not
   something learned from or validated against people.
   [ADR 0004](docs/adr/0004-human-like-development.md) adds more processes taken
   from personality psychology:
   * Consented feedback within a session moves an ephemeral *session state*. Only
     states that recur consistently across sessions become a trait (a habit step).
   * Experience is weighted by novelty, and growth continues slowly after `T`.
     Surface style settles before interpersonal traits.
   * A role change, a new host or a burst of corrections temporarily raises
     plasticity.
   * Relationships accommodate to the user's own pattern of work and cool after
     long absences.
   * Automatic change stays near the persona's temperament. Learned change that is
     not reinforced fades a little at each consolidation pass, unless that would
     undo consented feedback.
   * Owners' feedback weighs more early and users' later. Agent reflections gain
     weight with maturity.
6. **Promotion, rollback and revocation.** With `evolution: automatic` (the
   default) eligible candidates and maturation steps are promoted by the engine
   with compare-and-swap. With `manual` (or after `openape persona evolution ID
   --pause`), an admin promotes with compare-and-swap against the expected
   current version. Versions are immutable, content-addressed
   safetensors files in SQLite-backed storage, and any of them can be rolled back
   to. If a piece of evidence is revoked, only the candidates and versions built
   from it are invalidated. The persona then falls back to its nearest clean
   ancestor.
7. **Trust boundaries.** Every bearer token is bound to a tenant, an actor, the
   personas and users it may touch, and its scopes. Hosts normally need only
   `persona:express`, `observations:write` and `reflection:write`. Exports contain core state only,
   with no raw feedback, relationships or secrets.

The wire protocol, **UPAP/2** (Universal Personality Adapter Protocol), is
specified in [`protocol/upap/v2`](protocol/upap/v2/specification.md) with JSON
Schemas, OpenAPI and shared conformance fixtures. For the reasoning behind these
choices, see the [architecture ADRs](#design-and-evidence).

### Repository layout

| Path | Contents |
|---|---|
| `engine/` | FastAPI service: `api`, `neural` (decoder + encoder), `learning` (trainer), `evaluation` (independent evaluator), `storage` (SQLite + artifacts), `security` |
| `protocol/` | UPAP/2 spec, schemas, OpenAPI, conformance fixtures, style catalogue |
| `sdk/` | Python client (`client.py`, stdlib `lite.py`), TypeScript client, `openape` CLI |
| `adapters/` | Host integrations for Claude Code, Hermes, OpenClaw, Pi, OpenCogni |
| `adapter-kit/` | Templates, mock host and conformance notes for writing new adapters |
| `models/decoder-v3/` | Trained decoder weights, manifest and model card |
| `benchmarks/`, `scripts/`, `tests/` | Synthetic corpus and benchmark, smoke tests, reproducibility checks |
| `docs/` | ADRs, walkthrough, adapter compatibility, verification reports |

## Run locally (Python 3.12+, no GPU or provider credentials)

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock
pip install --no-deps -e .
openape init           # owner credential in .openape/ (0700/0600)
openape serve          # 127.0.0.1:8765
```

In another terminal (same venv):

```sh
openape persona archetypes                             # starting personas and their traits
openape persona create ape --archetype mentor          # evolves automatically from here
openape persona create terse --archetype pragmatic_engineer --maturation-rate fast
openape preview --file examples/express.json          # text an adapter would inject
openape token add --actor pi-host --personas terse    # restricted host token; restart serve
openape persona inspect ape --user alice              # growth: experience, horizon, maturity
openape persona evolution ape --pause                 # or --resume, --maturation-rate slow, --agent-feedback off
python -m scripts.offline_demo                        # manual learn/promote/rollback, then automatic evolution
```

`examples/express.json` names persona `ape`; edit `identity.persona_id` to preview
your persona. Interactive API docs: `http://127.0.0.1:8765/docs`.

## Host adapters

| Host | Install | Real-host smoke |
|---|---|---|
| Claude Code 2.1.307 | `claude plugin marketplace add $PWD && claude plugin install openape@openape` | `python -m scripts.claude_code_host_smoke` |
| Hermes Agent 0.19.0 | `openape adapter install hermes && hermes plugins enable openape` | `python -m scripts.hermes_host_smoke` |
| OpenClaw 2026.10.5 | see `adapters/openclaw/config.example.json` | `OPENCLAW_NODE_BIN=… python -m scripts.openclaw_host_smoke` |
| Pi 1.3.0 | `pi -e $PWD/adapters/pi/index.ts` | `python -m scripts.real_host_smoke` |
| OpenCogni 833f4e6 | needs `adapters/opencogni/upstream` patch | `OPENCOGNI_DIR=… python -m scripts.opencogni_host_smoke` |

In active mode the Claude Code (stdio MCP server bundled with the plugin), Hermes,
Pi and OpenClaw adapters also give the agent the `persona_feedback` tool
([definition](protocol/upap/v2/tools/persona_feedback.json)).
`OPENAPE_AGENT_FEEDBACK=0` turns it off. OpenCogni has no tool hook in its patch.
The host smokes show the tool offered to the model in active mode only. In Claude
Code 2.1.308 it appears as a deferred MCP tool, in Hermes 0.19.0 as a direct tool,
and in OpenClaw 2026.10.5 in its Tool Search catalog. In Pi 1.3.0 a call through
Pi's own tool wrapper was recorded. All of this used a synthetic model, so no
model has yet chosen to call it.

### Turn context

Adapters work out each turn's context from host metadata, using one shared rule
table ([`context-rules.json`](protocol/upap/v2/context-rules.json)) that the
Python and TypeScript SDKs apply identically:

* **Tools used in the previous turn**, by name only (never arguments or results):
  edit/write tools mean `coding` + `technical`, shell tools `technical`, read and
  search tools `research`. Two or more failed tool calls raise stakes to `high`.
* **Host state:** plan mode (Claude Code) means `research`; messaging platforms
  (Hermes, OpenClaw channels) mean channel `chat`.
* **Your declaration:** `OPENAPE_CONTEXT='{"task_type":"coding","tags":["expert"]}'`
  (Claude Code also reads `.openape.json` in the project; the variable wins).
  This is the only source of `beginner`/`expert` unless text classification is on,
  and it overrides everything derived.
* **Opt-in text classification:** with `OPENAPE_CONTEXT_TEXT=local` the adapter
  matches the user's message against fixed keyword rules on the host (for example
  "review this PR" → `code_review`, "asap" → `urgent`, "I'm new to" →
  `beginner`). The text is never sent, logged or stored; only the derived labels
  leave the host. Off by default.

OpenCogni keeps its fixed planner context (background, system-initiated).

`openape adapter doctor HOST --persona ID` checks a setup. Hermes users with an
existing SOUL.md can run `openape adapter migrate-soul` (dry run; `--apply --persona
ID` backs it up first). Details and limits: [compatibility](docs/adapters/compatibility.md).

## Verify

```sh
bash scripts/check_all.sh          # pytest, node tests, protocol regeneration
python -m scripts.check_reproducibility   # ~6.5 min decoder rebuild, exact hash
python -m scripts.offline_smoke    # real HTTP lifecycle + restart persistence
python -m benchmarks.simulated     # simulated-user A/B/C/D engineering benchmark
python -m scripts.performance
```

Host smokes install pinned hosts under `.host-test/` and never call a provider.

## Use from a custom harness

```python
from sdk.python.client import Client          # httpx; or sdk/python/lite.py (stdlib only)
client = Client('http://127.0.0.1:8765', token='SCOPED_HOST_TOKEN')
result = client.express(request, mode='shadow')  # request as in examples/express.json
# Inject result['text'] once at an approved context hook if non-empty.
# Task success is never feedback; submit explicit authorised feedback separately.
# Give the agent sdk.python.lite.TOOL; on a call, record it for this turn's decision:
client.reflect(result['decision']['decision_id'], {'verbosity': 'less'}, 'user_requested',
               habits={'next_step': 'more_often'})
```

TypeScript (Node 22.18+/24) exports `Client`, `render` and `PersonalityAdapter` from
`sdk/typescript/client.ts`. Both SDKs pass the same golden fixtures in
`protocol/upap/v2/conformance.json`. `openape bridge` is a JSONL stdin/stdout bridge,
not an automatic native hook.

## Operations

`openape init | serve | token add | persona create/list/inspect/history/delete/archetypes/evolution |
express | preview | feedback | observe | learn | job | promote | rollback | export |
import | adapter install/uninstall/doctor/migrate-soul | bridge | migrate --reset`. Write commands take
`--file request.json` (or stdin). The engine promotes automatically only for personas
with `evolution: automatic`; `learn`/`promote` remain for manual personas. Feedback
is record-only unless `learning_consent: true` with an authorised scope.

Upgrading from 0.2: the engine refuses to start on a 0.2 data directory. Run
`openape migrate --reset --data DIR` once. It re-creates each persona from its recorded
archetype, seeds and individuality (the same temperament), keeps its settings, and
keeps old decisions and feedback as history only. Learned state from 0.2 cannot carry
over to the new decoder. Hosts need the 0.3 adapters; 0.2 clients fail open (inject
nothing).

Docker: `openape init`, then `docker compose up --build` (loopback port, unprivileged,
read-only root, data volume; add `-f compose.limits.yaml` for limits). Remote
deployments need TLS at a trusted reverse proxy. Shared SQLite replicas are unsupported.

## Design and evidence

* ADRs: [0001 architecture](docs/adr/0001-architecture.md), [0002 decoder-v2, evaluator, lineage](docs/adr/0002-decoder-v2-evaluator-lineage.md), [0003 archetypes and automatic evolution](docs/adr/0003-automatic-evolution.md), [0004 human-like development](docs/adr/0004-human-like-development.md), [0005 expressive controls](docs/adr/0005-expressive-controls.md)
* [Protocol](protocol/upap/v2/specification.md), JSON Schemas, OpenAPI, conformance fixtures
* [Model card](models/decoder-v3/MODEL_CARD.md) · [benchmarks](benchmarks/README.md)
* [Release status](docs/reports/release-status.md) · [review of 0.1.0 against the brief](docs/reports/v0.2-review.md) · [open issues](docs/reports/open-issues.md)
* [10-minute walkthrough](docs/walkthrough.md)

Apache-2.0 source and weights; original synthetic corpus CC0-1.0. No provider-generated
or proprietary training data. The original brief is in `docs/original-brief.md`.
