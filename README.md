# OpenAPE — Agent Personality Engine

A local, CPU-only neural style policy with a versioned **UPAP/1** HTTP API,
scoped explicit feedback, isolated latent candidates, held-out validation,
manual compare-and-swap promotion, version pinning and rollback.

**Experimental 0.1.0, not the completed v1 release gate.** The decoder is trained
on original synthetic rule labels. Offline tests demonstrate neural inference
and directional latent learning; they do **not** establish a learned personality,
human preference gains, cross-provider portability or task/safety non-inferiority.
See [release status](docs/reports/release-status.md) for every unfulfilled gate.

## Run locally (Python 3.12+, no GPU or provider credentials)

From this repository root:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock
pip install --no-deps -e .
openape init
openape serve
```

In another terminal, activate the same environment:

```sh
openape persona create ape
openape persona inspect ape
openape express --file examples/express.json
python -m scripts.offline_demo
```

`init` creates a unique owner credential in `.openape/credentials.json` with mode
0600; CLI commands use it locally. A Docker-readable copy is created at
`.openape/docker-credentials.json` (0444) inside the private 0700 directory, for
the unprivileged container secret mount. The example request is shadow mode by default.
The demo explicitly opts into active expressions and synthetic learning, creates
an isolated demo persona, records preference pairs, trains/evaluates a candidate,
promotes it, exports core state, and rolls back. Actor `owner` is the default init
credential; custom actors must adjust the demo. No transcript or LLM call is used.
Restart the service and `openape persona history <demo-id>` to inspect persistence.

Docs at `http://127.0.0.1:8765/docs` expose the complete interactive API.

## Verify

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
python -m scripts.train_decoder
python -m scripts.performance
```

A real Pi lifecycle test uses the **actual pinned Pi SDK** and a **synthetic model
transport**, not a live provider:

```sh
npm --prefix .host-test install --no-audit --no-fund @earendil-works/pi-coding-agent@1.3.0
python -m scripts.real_host_smoke
```

See [compatibility](docs/adapters/compatibility.md) before installing any host
adapter. Only Pi's native lifecycle is tested here. The other adapters are
experimental examples or explicitly unsupported. Real model tests need separately
configured providers and independent outcomes; none are silently substituted.

## Use from a custom harness

```python
from sdk.python.client import Client
client = Client('http://127.0.0.1:8765', token='YOUR_SCOPED_TOKEN')
# request follows examples/express.json
result = client.express(request, mode='shadow')
# At an approved context hook, inject result['text'] once if nonempty.
# Task success is never feedback. Submit explicit authorized feedback separately.
client.close()
```

TypeScript (Node 24+) exports `Client`, `render`, and `PersonalityAdapter` from
`sdk/typescript/client.ts`. The Python client currently depends on this package's
contracts/catalogue; an independently packaged lightweight SDK remains a v1 gap.
`openape bridge` is a JSONL stdin/stdout bridge, not an automatic native hook.

## Operations

Commands: `persona create/list/inspect/history/delete`, `express`, `feedback`,
`observe`, `learn`, `promote`, `rollback`, `export`, `import`, and `bridge`.
Write commands accept `--file request.json` (or stdin); promotion, rollback and
export need `--persona ID`. All API bodies explicitly declare `upap/1`.
The engine never automatically promotes. Feedback defaults to record-only;
learning requires `learning_consent: true`, an authorized scope and existing
decision. Pairwise corrections identify approved catalogue options, not free text.

For Docker, run `openape init` first, then `docker compose up --build`.
Use `-f compose.yaml -f compose.limits.yaml` for resource limits. The container
runs unprivileged with a read-only filesystem and a writable data volume. The
published port is loopback-only. Verify the running container with
`python -m scripts.docker_smoke`. Remote deployments require TLS at a trusted
reverse proxy and authenticated connections. Shared SQLite replicas are unsupported.
If your Docker build uses an intercepting proxy, supply its CA with BuildKit
`--secret id=proxy_ca,src=/path/to/combined-ca.pem`; never disable TLS verification.

## Design and evidence

* [Architecture and security decisions](docs/adr/0001-architecture.md)
* [Protocol semantics](protocol/upap/v1/specification.md), JSON Schemas and OpenAPI
* [10-minute walkthrough](docs/walkthrough.md)
* [Model card and provenance](models/decoder-v1/MODEL_CARD.md)
* [Test and benchmark evidence](docs/reports/release-status.md)
* [Independent A/B/C/D benchmark instructions](benchmarks/README.md)

Apache-2.0 source/weights; original synthetic corpus CC0-1.0. No provider-generated
or proprietary training data is included. The original brief is preserved in
`docs/original-brief.md`; the project and CLI are renamed **OpenAPE**.
