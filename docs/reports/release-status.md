# OpenAPE 0.2.0 experimental handoff

**Release decision: experimental engineering build; full v1 gate NOT met.**
The neural personality now genuinely conditions behaviour and learns from explicit
feedback, and all five host adapters run real host turns. There is still no
live-model run and no independent human evidence of benefit. What changed since
0.1.0 and why: [v0.2-review.md](v0.2-review.md).

Source: branch `ccr-3980d449-iflypl` (`git rev-parse HEAD`). Tested OS: managed Linux
x86_64 only. OpenCogni boundary change: `adapters/opencogni/upstream/` (not pushed
or merged upstream).

## Verification matrix (2026-10-22)

| Check | Result | Level | Evidence |
|---|---|---|---|
| Python suites | 44 passed, 3 strict xfail (open gates) | implemented, unit/integration | `python-tests.txt` |
| Node SDK + adapter fixtures | 19 passed | verified with mocks | `node-tests.txt` |
| Golden conformance (Python + TS render identical text) | PASS | protocol | `protocol/upap/v1/conformance.json` |
| Decoder reproduction from clean checkout | exact hash `sha256:dda6b844…b643` | reproducible training | `decoder-reproduction.txt` |
| Held-out synthetic personas (16 pairs → 32 unseen contexts) | top-1 0.657 vs 0.122 neutral | synthetic learning | `models/decoder-v2/decoder.json` |
| Real HTTP feedback → candidate → evaluator → promote → export → rollback → restart | PASS | synthetic labels | `offline-smoke.json` |
| Claude Code 2.1.307 real CLI + plugin | PASS 10/10 | actual host, synthetic model | `claude-code-host-smoke.json` |
| Hermes Agent 0.19.0 real CLI + plugin, SOUL migration | PASS 13/13 | actual host, synthetic model | `hermes-host-smoke.json` |
| OpenClaw 2026.10.5 real CLI + plugin | PASS 9/9 | actual host, synthetic model | `openclaw-host-smoke.json` |
| Pi 1.3.0 real SDK session (switch, compaction, multi-session, outage) | PASS | actual host, synthetic model | `pi-native-smoke.txt` |
| OpenCogni real `planner.http` + patch; OpenCogni unit suite | PASS 4/4; 74 passed / 1 skipped | actual planner code, synthetic model | `opencogni-host-smoke.json` |
| OpenCogni integration/evaluator suites | not run (need nats-server, PostgreSQL) | — | ISSUE-001 |
| Simulated-user A/B/C/D (384 sealed interactions) | D−C +0.29 [0.14, 0.42]; D−B +0.09 [−0.11, 0.29] **n.s.** | simulated, not human | `benchmarks/reports/simulated.json` |
| Live LLM families | none tested | — | ISSUE-001 |
| Independent ≥200-interaction human study | not run | — | ISSUE-002 |
| Docker image | verified for 0.1.0 only; no daemon available for 0.2.0 | — | `docker-smoke.json`, ISSUE-004 |

A strict xfail is a known failing release gate, not a pass. No fixture is reported
as a live-model test.

## Measured local performance

Linux x86_64, Python 3.12, PyTorch 2.5.1+cpu, single client, 20 warm-up + 500
measured real-HTTP expressions persisted to SQLite: HTTP p95 **9.4 ms** (target ≤75),
direct neural p95 **0.34 ms** (target ≤25), process start to ready **2.1 s**. Single
run on a shared machine; data in `benchmarks/reports/performance.json`. Rendered style
text is ~60 words; provider token/cache costs were not measured with live models.
Prompt-cache impact: Hermes keeps byte-stable request prefixes across turns; Claude
Code and OpenClaw keep one style block per historical turn.

## Security and data handling

Loopback by default; Bearer credentials bind tenant, actor, persona and user
allowlists and scopes (`openape token add` mints restricted host tokens). No raw
transcript, prompt text or tool output is accepted or read by any adapter. Strict
schemas, body/rate/queue bounds. No implicit reward. Hash-checked safetensors, CAS
promotion, independent evaluator with fixed thresholds, manual activation, scoped
fallback cache, core-only same-tenant export, lineage revocation, deletion cleanup.
Limits: in-process worker thread, memory-local rate limiter, no formal audit.

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
```

## Next release work

See [open-issues.md](open-issues.md): live-model runs across three provider
families, an independent blinded A/B/C/D study, OpenCogni upstream review plus
integration suites, Docker re-verification, OS-isolated evaluator, and audits.
