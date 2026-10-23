# OpenAPE 0.3.0 experimental handoff

**Release decision: experimental engineering build; full v1 gate NOT met.**
0.3.0 widens what a persona can express (ADR 0005). The current branch adds:

* user-controlled relationship settings;
* habit learning separate from the latent;
* an opt-in cohort prior and exploration;
* "why this style" explanations;
* PostgreSQL for several replicas and an evaluator in its own process (ADR 0006).

Live-model evidence is still a pilot: one model under test and one judge. There is
no independent human evidence of benefit. Upgrading a 0.2 data directory requires
`openape migrate --reset`.

Source: branch `ccr-4c4b257a-78qokn` (`git rev-parse HEAD`). Tested OS: managed Linux
x86_64 only. OpenCogni boundary change: under review upstream (taylorelley/opencogni#8).

## Verification matrix (2026-10-23)

| Check | Result | Level | Evidence |
|---|---|---|---|
| Python suites, SQLite | 176 passed, 1 skipped, 3 strict xfail (open gates) | unit/integration | `python-tests.txt` |
| Python suites, PostgreSQL 16 | 175 passed, 2 skipped (SQLite-only), 3 strict xfail | unit/integration | `python-tests.txt` |
| Node SDK + adapter fixtures | 94 passed | verified with mocks | `node-tests.txt` |
| Golden conformance: Python and TS render the same text, validate the same decisions, derive the same contexts (incl. untrusted project files) and classify text identically | PASS | protocol | `protocol/upap/v2/conformance.json` |
| Decoder reproduction from the pinned lockfile | exact hash `sha256:7b514e00…7609` | reproducible training | `decoder-reproduction.txt` |
| Held-out synthetic personas (16 pairs → 32 unseen contexts) | trait agreement 0.742 vs 0.594 neutral; habit F1 with learned bias 0.625 vs 0.635 neutral | synthetic learning | model card, `decoder.json` |
| Episodic meta-training | no gain (0.742 → 0.742 at weight 0.1; 0.580 at 1.0); off | synthetic learning | model card |
| On-host text classifier vs keyword rules (held-out template families) | task accuracy 0.60 vs 0.33; tag F1 0.92–1.0 | synthetic | `context-classifier.json` |
| Docker 0.3.0 (hardened compose): health, auth, neural express, consolidation judged by the evaluator process | PASS | actual container | `docker-smoke.json` |
| Two replicas on PostgreSQL 16 (Docker): shared state, job seen from either replica, compare-and-swap (200 / 409), promoted version served by the other replica | PASS | actual containers | `replicas-smoke.json` |
| Live tool calls, Hermes 0.19.0 + z-ai/glm-5.3-flash | the model called `persona_feedback`; a refusal led it to a valid move; recorded | live model, one model | `live-tool-smoke.json` |
| Live tool calls, OpenClaw 2026.10.5 + z-ai/glm-5.3-flash | the model found and called `persona_feedback` with the requested moves; next turn verbosity 3 → 1 via session state | live model, one model | `live-tool-smoke-openclaw.json` |
| Style placement study (9 prompts × 30 conditions × 4 arms, judge deepseek-v4-flash) | after the task (current) best: mean Spearman 0.63 vs prefix 0.58, tone example 0.54, system prompt 0.47; quality −0.01 to −0.03 | live model, one model and judge | `live-eval-placement.md` |
| OpenCogni `planner.http` with the boundary change (cap 1400) | PASS 4/4; OpenCogni typecheck, lint, 74 unit tests + 3 contract tests pass | actual host, synthetic model | `opencogni-host-smoke.json`, PR #8 |
| Claude Code 2.1.308, Hermes 0.19.0, OpenClaw 2026.10.5, Pi 1.3.0 synthetic host smokes | PASS (0.3.0) | actual hosts, synthetic model | `*-host-smoke.json` |
| Simulated-user A/B/C/D (384 sealed interactions) | D−B regret −0.90 [−1.48, −0.37]; fully satisfied +0.06 [−0.03, 0.15] **n.s.** | simulated, not human | `benchmarks/reports/simulated.json` |
| Live LLM families | one (GLM via OpenRouter) | — | ISSUE-001 |
| Independent ≥200-interaction human study | not run | — | ISSUE-002 |

A strict xfail is a known failing release gate, not a pass.

## Measured local performance

Linux x86_64, Python 3.13, PyTorch 2.5.1+cpu, single client, 20 warm-up + 500
measured real-HTTP expressions persisted to SQLite: HTTP p95 **13.3 ms** (was 10.4 before habit biases, settings and cohort lookups) (target ≤75),
decoder plus joint selection over 51 788 configurations p95 **4.2 ms** (target ≤25). Single
run on a shared machine; data in `benchmarks/reports/performance.json`. Rendered style
text is 50-90 words; provider token/cache costs were not measured with live models.
Prompt-cache impact: Hermes keeps byte-stable request prefixes across turns; Claude
Code and OpenClaw keep one style block per historical turn.

## Security and data handling

Loopback by default; Bearer credentials bind tenant, actor, persona and user
allowlists and scopes (`openape token add` mints restricted host tokens). No raw
transcript, prompt text or tool output is sent to the engine. Adapters read tool
names and failure counts only; they read the user's message only with
`OPENAPE_CONTEXT_TEXT=local`, classify it in memory and send labels only. Strict
schemas, body/rate/queue bounds. No implicit reward. Hash-checked safetensors, CAS
promotion, independent evaluator with fixed thresholds, manual activation, scoped
fallback cache, core-only same-tenant export, lineage revocation, deletion cleanup.
Linked users control their relationship (preferences, pins, vetoes, freeze, cohort and
exploration consent); context safety masks always win over pins. A repository's
`.openape.json` is untrusted (regular file ≤64 KB, no links, cannot lower stakes or set
channel/origin). Agent reflections cannot weaken `flag_uncertainty`/`risks_first` and
alone move a habit at most halfway. Candidates are judged in a separate evaluator
process. Limits: per-replica rate limiter, writes serialized by one database lock, no
formal audit.

## Reproduce

```sh
bash scripts/check_all.sh
python -m scripts.check_reproducibility
python -m scripts.offline_smoke
python -m benchmarks.simulated
npm --prefix .host-test install --no-audit --no-fund @earendil-works/pi-coding-agent@1.3.0
python -m scripts.real_host_smoke
python -m scripts.claude_code_host_smoke          # needs claude 2.1.307 on PATH
python -m scripts.hermes_host_smoke               # installs hermes-agent 0.19.0
OPENCLAW_NODE_BIN=/path/to/node24/bin python -m scripts.openclaw_host_smoke
OPENCOGNI_DIR=/path/to/patched/opencogni python -m scripts.opencogni_host_smoke
python -m scripts.performance
docker compose up --build -d && python -m scripts.docker_smoke
docker compose -f compose.replicas.yaml up --build -d && python -m scripts.replicas_smoke
OPENAPE_TEST_DATABASE_URL=postgresql://... python -m pytest -q
OPENROUTER_API_KEY=... python -m scripts.live_tool_smoke --model MODEL --base-url https://openrouter.ai/api/v1 [--host openclaw]
```

## Next release work

See [open-issues.md](open-issues.md):
* live-model runs across three provider families with a stronger judge;
* an independent blinded A/B/C/D study;
* OpenCogni review, merge and integration suites;
* per-persona write locks if one writer becomes the bottleneck;
* OS-level sandboxing of the evaluator process;
* audits.
