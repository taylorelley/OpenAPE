# OpenAPE 0.1.0 experimental handoff

**Release decision: experimental engineering build; full v1 gate NOT met.**
OpenAPE is implemented and runnable locally. Do not interpret its synthetic
learning tests as proof of learned personality or measured user benefit.

Source repository: this standalone directory; local branch `main`, tag
`v0.1.0-experimental`. Use `git rev-parse HEAD` and `git show
v0.1.0-experimental` for exact final source identity. No remote repository, PR or
public release was created. No upstream host code was modified. OpenCogni
planner modifications remain a separately reviewable future task.

## Verification matrix

| Check | Result | Evidence |
|---|---|---|
| Python local suites | 25 passed | `python-tests.txt` |
| Node SDK + adapter fixtures | 12 passed | `node-tests.txt` |
| Four remaining native-host gates + independent behavioral gate | 5 strict expected failures | `tests/test_release_gates.py`, ISSUE-001/002 |
| Decoder reproduction | exact hash reproduced | `decoder-reproduction.txt` |
| Real HTTP feedback -> train -> validate -> promote -> export -> rollback -> restart | PASS, synthetic preference pairs | `offline-smoke.json` |
| Native Pi 1.3.0 SDK session | PASS with synthetic model transport, controls reached transport | `pi-native-smoke.txt` |
| Pi repeated turns / engine outage | PASS; deduplicated old style; host continued with engine stopped | same Pi report |
| Claude Code subprocess hook outage/invalid input | PASS fixture; actual host unavailable | `tests/test_hook.py` |
| Hermes / OpenClaw | source-inspected examples; actual host unverified | compatibility matrix |
| OpenCogni | source-inspected companion service only; planner unsupported | compatibility matrix |
| Docker build/start/auth/CPU neural inference/restart | PASS; UID10001, read-only root, persistent volume | `docker-smoke.json` |
| Live LLM families | none tested | No configured provider credentials |
| Independent >=200 interaction A/B/C/D study | not run | No independent outcome corpus |
| Security/CVE/legal audit | regression tests only; formal release audit incomplete | risk register, ISSUE-004 |

A strict xfail is a known **failing release gate**, not a successful compatibility
check. No actual live-model test is substituted with a fixture.

## Measured local performance

Linux x86_64, Python 3.12.14, PyTorch 2.5.1+cpu, AMD EPYC 9V74. Single
real-HTTP client, 20 warm-up + 500 measured expressions persisted to SQLite:
HTTP p95 **2.68 ms**, direct neural p95 **0.17 ms**; process-start-to-ready
**1.26 s** in this run. Maximum HTTP was 77.29 ms. These are single-run local
measurements, not a sustained-load guarantee. Full data:
`benchmarks/reports/performance.json`. Provider token/cache/cost effects unmeasured.

## Learning evidence

Seed42 decoder: 288 synthetic train /48 calibration /96 validation rows;
synthetic validation accuracy 0.9167. Artifact hash:
`sha256:934d9e8665386fb4819d8102cdb579e34884f5ea22c24c2757c9316feca3c30a`.

Offline latent experiment: 26 training session groups /10 held-out groups,
pairwise loss 2.2696 -> 1.3120, norm drift 0.4682, KL 0.0610. Core promotion
passed fixed evaluator and rollback/restart passed. Labels were deliberately
synthetic. There is **no measured behavioral benefit** over markdown/fixed controls,
no independent identity-distinction result, no cross-provider continuity result
and no safety/task non-inferiority claim. A/B/C/D runner interfaces and a clustered
bootstrap outcome evaluator are provided for independent evidence collection.

## Security and data handling

Loopback default; explicit Bearer credentials bind tenant/actor/persona/user and
scope. Host tokens need only expression/observation scopes; feedback/admin rights
are separate. No raw transcript or tool text accepted. Strict schemas and body,
rate, job and cache limits. No implicit success reward. Hash-checked safetensors,
CAS promotion, independent fixed evaluator thresholds, manual activation, scoped
fallback, core-only same-tenant exports, revocation/reset and deletion cleanup.

Limits: trusted single process with a worker thread, memory-local rate limiter,
no crash/power-loss artifact proof, no production security certification. SQLite
replication unsupported. No automatically generated instructions or tool authority.

## Reproduce

Use README for clean installation and credential setup, then:

```sh
bash scripts/check_all.sh
python -m scripts.offline_smoke
npm --prefix .host-test install --no-audit --no-fund @earendil-works/pi-coding-agent@1.3.0
python -m scripts.real_host_smoke
python -m scripts.performance
python -m benchmarks.evaluate /path/to/independent-outcomes.jsonl
```

The final command needs genuinely independent outcomes; no result is supplied.
Docker verification passed and is recorded in `docker-smoke.json` and
`container-runtime.txt`. The dedicated test container and volume were removed;
the verified local image `openape:0.1.0` is retained.
Tested OS is the managed Linux environment only; macOS/Windows unverified.

## Next release work

The detailed list is [open-issues.md](open-issues.md): four remaining actual
native-host integrations, live model and independent blinded outcome study,
complete generated protocol SDKs/conformance and distribution, session/subagent
state semantics, OS trainer/evaluator isolation, stronger provenance/re-derivation,
and formal threat/dependency/license/backup audits. WP reports explicitly label
partial delivery; v1 completeness is not claimed.
