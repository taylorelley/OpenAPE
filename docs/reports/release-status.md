# OpenAPE 0.3.0 experimental handoff

**Release decision: experimental engineering build; full v1 gate NOT met.**
0.3.0 widens what a persona can express (ADR 0005). Adapters now derive the turn
context from host metadata. The engine returns a level 0-4 for each of seven traits
plus up to three signature habits, chosen from an audited catalogue, instead of one
of 24 rows, using decoder-v3 over upap/2. All four re-run host adapters pass real
host turns. There is still no live-model run and no independent human evidence of
benefit. Upgrading a 0.2 data directory requires `openape migrate --reset`.

Source: branch `ccr-4c4b257a-78qokn` (`git rev-parse HEAD`). Tested OS: managed Linux
x86_64 only. OpenCogni boundary change: `adapters/opencogni/upstream/` (not pushed
or merged upstream).

## Verification matrix (2026-10-22)

| Check | Result | Level | Evidence |
|---|---|---|---|
| Python suites | 120 passed, 3 strict xfail (open gates) | implemented, unit/integration | `python-tests.txt` |
| Node SDK + adapter fixtures | 58 passed | verified with mocks | `node-tests.txt` |
| Golden conformance (Python + TS render identical text, validate the same 22 decisions and derive the same 25 contexts) | PASS | protocol | `protocol/upap/v2/conformance.json` |
| Catalogue: every one of 5^7 configurations classified identically by catalogue and SDK; worst-case text 594 ≤ 900 chars | PASS | protocol | `tests/test_conformance.py` |
| Decoder reproduction from clean checkout (pinned lockfile) | exact hash `sha256:74f8d394…6cde` | reproducible training | `decoder-reproduction.txt` |
| Held-out synthetic personas (16 pairs → 32 unseen contexts) | per-trait level agreement 0.655 vs 0.566 neutral; habit F1 0.604 vs 0.625 neutral | synthetic learning | `models/decoder-v3/decoder.json` |
| Real HTTP feedback → candidate → evaluator → promote → export → rollback → restart | PASS | synthetic labels | `offline-smoke.json` |
| 0.2 store → `openape migrate --reset` → same temperament, feedback kept as history | PASS | implemented, integration | `tests/test_engine.py` |
| Claude Code 2.1.308 real CLI + plugin | PASS 11/11 | actual host, synthetic model | `claude-code-host-smoke.json` |
| Hermes Agent 0.19.0 real CLI + plugin, SOUL migration | PASS 15/15 | actual host, synthetic model | `hermes-host-smoke.json` |
| OpenClaw 2026.10.5 real CLI + plugin (Node 24.22) | PASS 10/10 | actual host, synthetic model | `openclaw-host-smoke.json` |
| Pi 1.3.0 real SDK session (switch, compaction, multi-session, outage) | PASS | actual host, synthetic model | `pi-native-smoke.txt` |
| Derived turn context in real hosts (tool-event signals) | not exercised: the synthetic model never calls tools | unit/integration only | manifests `unverified` |
| OpenCogni real `planner.http` + patch | not re-run for 0.3.0 (needs a patched OpenCogni checkout) | — | ISSUE-001 |
| Simulated-user A/B/C/D (384 sealed interactions) | D−B regret −0.90 [−1.48, −0.37]; D−B fully satisfied +0.06 [−0.03, 0.15] **n.s.** | simulated, not human | `benchmarks/reports/simulated.json` |
| Development trajectories (8 personas × 48 sessions) | visible style changes move 1.65 traits on average | simulated, fixed priors | `benchmarks/reports/development.json` |
| Live-model style evaluation harness | built; offline tests pass; not run (no provider key) | harness only | `benchmarks/live`, `tests/test_live_harness.py` |
| Live LLM families | none tested | — | ISSUE-001 |
| Independent ≥200-interaction human study | not run | — | ISSUE-002 |
| Docker image | verified for 0.1.0 only; no daemon available since | — | `docker-smoke.json`, ISSUE-004 |

A strict xfail is a known failing release gate, not a pass. No fixture is reported
as a live-model test.

## Measured local performance

Linux x86_64, Python 3.13, PyTorch 2.5.1+cpu, single client, 20 warm-up + 500
measured real-HTTP expressions persisted to SQLite: HTTP p95 **10.4 ms** (target ≤75),
decoder plus joint selection over 51 788 configurations p95 **4.0 ms** (target ≤25). Single
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

See [open-issues.md](open-issues.md) and ADR 0005: run the live-model harness
(`benchmarks/live`, built and tested offline) to check whether each trait level and
habit changes model replies, and revise templates that do not; live-model runs across three provider families, an independent blinded A/B/C/D study, OpenCogni upstream review plus
integration suites, Docker re-verification, OS-isolated evaluator, and audits.
