# Risk register

| Risk | Mitigation implemented | Remaining evidence |
|---|---|---|
| Synthetic decoder mistaken for human-learned identity | experimental status in API/model card/README; no behavioral win claim | Independent blinded study ISSUE-002 |
| Host hook/interface drift | pinned host versions; real-host smokes for all five hosts (two 0.1.0 adapters were found non-functional this way) | Live-model runs, untested runner paths, OpenCogni upstream merge ISSUE-001 |
| Unattributable reward / malicious tool text | scoped authenticated explicit feedback; no transcript/metadata instruction field; sampled propensity required for gradient | Attestation and independent source reliability ISSUE-005 |
| Cross-user contamination | credential user allowlists; independent relationship versions; scoped cache and revocation tests | Broader adversarial multi-profile host suite |
| One-off online drift | isolated candidates, independent evaluator, group thresholds, latent trust region and state-norm bound, CAS promotion; automatic promotion only under per-persona policy with stricter thresholds; pause/rollback | Long-session and independent task-regression evaluation |
| Compromised trainer/evaluator | fixed thresholds, no host modification API, bounded jobs | OS/process isolation ISSUE-004 |
| SQLite/artifact crash consistency | WAL, atomic artifact rename, hashes, short transactions | Power-loss/GC and backup recovery fault injection |
| Host stalls on engine outage | deadline, max retry, cached or empty injection; outage turns verified in all five host smokes | Long outages under load |
| Secret/raw experience leakage | random credentials, scope binding, no raw text collection, core-only export | Formal privacy/CVE/legal audit |
| Resource exhaustion | bounded request bytes/events, per-actor rate limit, queue4/worker1, 1000 recent evidence rows/job, cache128 | Load/security tests with hostile concurrent clients |
| Over-broad revocation destroying history | lineage-based revocation; revoked versions marked, not silently deleted | Automated re-derivation |
| SOUL.md loss during migration | dry run default; exclusive timestamped backup; operational lines retained | Heuristic classification needs human review |
| Agent steering its own persona (persona_feedback) | trait moves only, no text; user-originated turns; 1 per decision, 3 per session; per-persona switch and `reflection:write` scope; ≤50% of auto-promoted examples when human feedback exists; evaluator; revocable | How models use the tool in practice ISSUE-006 |
| Maturation drifting away from what users want | bounded sqrt-curve budget; settles at horizon; rejected if it reduces agreement with consented preferences; pause/rate controls | Human validation of the prior ISSUE-006 |
