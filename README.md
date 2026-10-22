# OpenAPE — Agent Personality Engine

A local, CPU-only neural style policy behind a versioned **UPAP/1** HTTP API. A
persistent persona latent (plus optional per-user relationship latent) conditions a
frozen decoder that picks one of 24 audited style configurations; hosts render it
as short, approved context text. Learning comes only from explicit, consented,
attributable feedback, through isolated candidates, an independent held-out
evaluator, manual compare-and-swap promotion, version pinning and rollback.

**Experimental 0.2.0, not the completed v1 release gate.** The decoder is trained
on original synthetic persona profiles; held-out synthetic personas can be fitted
from 16 preferences (top-1 0.66 vs 0.12 neutral). All five host adapters run real
host turns against a synthetic model endpoint. There is still **no live-model and
no independent human evidence** of preference gains, cross-provider portability or
task/safety non-inferiority. See [release status](docs/reports/release-status.md).

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
