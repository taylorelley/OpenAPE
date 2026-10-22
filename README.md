# OpenAPE — Agent Personality Engine

OpenAPE gives AI coding agents and chat harnesses (Claude Code, Hermes, OpenClaw,
Pi, OpenCogni, or your own) a **persistent, learnable communication style** that
stays the same whatever model or provider is behind them.

A "persona" in OpenAPE is not a system prompt someone wrote. It is a small
numeric state held by a local service. On every turn, the host agent asks the
engine how this persona should talk in the current context. The engine answers
with one of 24 hand-reviewed style settings (how direct, warm, verbose, formal,
humorous, explanatory and assertive to be). The host turns that into a short
fixed-template note and adds it to the model's context:

> Style preferences only. Host, system, developer, safety and user task
> requirements take precedence. Be clear. Be considerate. Use moderate detail.
> Avoid humour. Use plain professional language. Explain key reasoning. State
> recommendations clearly without changing factual certainty.

The persona changes only through feedback that users explicitly give and consent
to train on, and every change goes through a review step you control. Personas
can be versioned, pinned, rolled back, exported and deleted.

It runs locally on a CPU, needs no GPU or provider API keys, and never calls an
LLM itself.

> **Status: experimental 0.2.0.** This is not the finished v1 release. The neural
> decoder is trained only on synthetic persona profiles. Held-out synthetic
> personas can be fitted from 16 preferences (top-1 agreement 0.66, against 0.12
> for a neutral persona). All five host adapters have been run against real host
> builds, but with a synthetic model endpoint. There is **no live-model or
> independent human evidence yet** that it improves user preference, carries over
> across providers, or leaves task quality and safety unchanged. See
> [release status](docs/reports/release-status.md).

## How it works

```
 host agent (Claude Code, Hermes, …)            OpenAPE engine (local HTTP, UPAP/1)
 ──────────────────────────────────            ────────────────────────────────────
 user turn ─▶ adapter ── POST /v1/express ───▶ encode context (task, channel,
                │        persona, user,         stakes, tags, provider)
                │        session, context              │
                │                                      ▼
                │                         persona latent ─┐
                │                    + relationship latent ├─▶ frozen decoder (MLP)
                │                                         │   ─▶ 24-way choice
                │                                         │   ─▶ safety mask
                │◀── decision: approved style controls ───┘
                ▼
     render fixed template ─▶ inject once into model context ─▶ model replies

 user gives explicit, consented feedback ──▶ POST feedback ──▶ evidence ledger
                                                                   │
              operator runs `learn` ─▶ train candidate (decoder frozen)
                                     ─▶ independent evaluator on held-out groups
                                     ─▶ operator `promote` (compare-and-swap)
                                     ─▶ new immutable persona version
```

1. **State.** Each persona has a 64-number *core latent*. Each linked user can
   also have a 32-number *relationship latent*, so the same persona can adapt to
   one person without affecting how it treats anyone else. The numbers have no
   assigned meaning; they matter only through the decoder. A new persona starts
   neutral, from declared seed preferences (`concise`, `warm`, `formal`, …), or as
   a snapshot of a parent persona (for subagents).
2. **Expression.** The adapter sends the turn's context: task type, channel,
   stakes, turn origin, tags and provider family. Raw text and transcripts are
   never sent. A small frozen CPU network
   ([decoder-v2](models/decoder-v2/MODEL_CARD.md)) combines the context with the
   latents and picks one row of the audited
   [style catalogue](protocol/catalogue.py). Fixed rules then mask unsafe choices,
   for example no humour when stakes are high and no long answers when the turn
   is urgent. The engine returns only these controls, never free text,
   permissions or instructions. The SDK renders them with fixed templates in
   Python and TypeScript, and both produce byte-identical output. A session pins
   its persona and decoder versions until it ends.
3. **Safe fallback.** The SDK waits at most 250 ms and retries a transient error
   once. If the engine is slow, down or broken, the host injects nothing, or a
   recent cached result for exactly the same scope, and carries on. `shadow` mode
   makes decisions without injecting anything, so you can trial OpenAPE safely.
   `disabled` makes no request at all.
4. **Learning.** Only explicit, attributable feedback counts: pairwise
   preferences, corrections and ratings that carry `learning_consent`. Task
   success, tool results and inferred satisfaction are never used as reward. When
   an operator runs `learn`, the trainer fits a *candidate* latent with the
   decoder frozen. A separate evaluator then splits the evidence by actor and
   session, re-scores the candidate on groups it was not trained on, and applies
   fixed thresholds: held-out gain, minimum evidence, and a limit on how far the
   latent may move.
5. **Promotion, rollback and revocation.** Candidates are never promoted
   automatically. An admin promotes one with compare-and-swap against the
   expected current version. Versions are immutable, content-addressed
   safetensors files in SQLite-backed storage, and any of them can be rolled back
   to. If a piece of evidence is revoked, only the candidates and versions built
   from it are invalidated. The persona then falls back to its nearest clean
   ancestor.
6. **Trust boundaries.** Every bearer token is bound to a tenant, an actor, the
   personas and users it may touch, and its scopes. Hosts normally need only
   `persona:express` and `observations:write`. Exports contain core state only,
   with no raw feedback, relationships or secrets.

The wire protocol, **UPAP/1** (Universal Personality Adapter Protocol), is
specified in [`protocol/upap/v1`](protocol/upap/v1/specification.md) with JSON
Schemas, OpenAPI and shared conformance fixtures. For the reasoning behind these
choices, see the [architecture ADRs](#design-and-evidence).

### Repository layout

| Path | Contents |
|---|---|
| `engine/` | FastAPI service: `api`, `neural` (decoder + encoder), `learning` (trainer), `evaluation` (independent evaluator), `storage` (SQLite + artifacts), `security` |
| `protocol/` | UPAP/1 spec, schemas, OpenAPI, conformance fixtures, style catalogue |
| `sdk/` | Python client (`client.py`, stdlib `lite.py`), TypeScript client, `openape` CLI |
| `adapters/` | Host integrations for Claude Code, Hermes, OpenClaw, Pi, OpenCogni |
| `adapter-kit/` | Templates, mock host and conformance notes for writing new adapters |
| `models/decoder-v2/` | Trained decoder weights, manifest and model card |
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
openape persona create terse --seed concise --seed direct
openape persona create kind --seed warm --seed detailed
openape preview --file examples/express.json          # text an adapter would inject
openape token add --actor pi-host --personas terse    # restricted host token; restart serve
python -m scripts.offline_demo                        # feedback → candidate → evaluate → promote → export → rollback
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
```

TypeScript (Node 22.18+/24) exports `Client`, `render` and `PersonalityAdapter` from
`sdk/typescript/client.ts`. Both SDKs pass the same golden fixtures in
`protocol/upap/v1/conformance.json`. `openape bridge` is a JSONL stdin/stdout bridge,
not an automatic native hook.

## Operations

`openape init | serve | token add | persona create/list/inspect/history/delete |
express | preview | feedback | observe | learn | job | promote | rollback | export |
import | adapter install/uninstall/doctor/migrate-soul | bridge`. Write commands take
`--file request.json` (or stdin). The engine never promotes automatically. Feedback
is record-only unless `learning_consent: true` with an authorised scope.

Docker: `openape init`, then `docker compose up --build` (loopback port, unprivileged,
read-only root, data volume; add `-f compose.limits.yaml` for limits). Remote
deployments need TLS at a trusted reverse proxy. Shared SQLite replicas are unsupported.

## Design and evidence

* ADRs: [0001 architecture](docs/adr/0001-architecture.md), [0002 decoder-v2, evaluator, lineage](docs/adr/0002-decoder-v2-evaluator-lineage.md)
* [Protocol](protocol/upap/v1/specification.md), JSON Schemas, OpenAPI, conformance fixtures
* [Model card](models/decoder-v2/MODEL_CARD.md) · [benchmarks](benchmarks/README.md)
* [Release status](docs/reports/release-status.md) · [review of 0.1.0 against the brief](docs/reports/v0.2-review.md) · [open issues](docs/reports/open-issues.md)
* [10-minute walkthrough](docs/walkthrough.md)

Apache-2.0 source and weights; original synthetic corpus CC0-1.0. No provider-generated
or proprietary training data. The original brief is in `docs/original-brief.md`.
