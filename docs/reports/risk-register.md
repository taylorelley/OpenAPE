# Risk register

| Risk | Mitigation implemented | Remaining evidence |
|---|---|---|
| Synthetic decoder mistaken for human-learned identity | experimental status in API/model card/README; no behavioral win claim | Independent blinded study ISSUE-002 |
| Host hook/interface drift | exact source pins and native Pi 1.3.0 test | Four unsupported host gates ISSUE-001 |
| Unattributable reward / malicious tool text | scoped authenticated explicit feedback; no transcript/metadata instruction field; sampled propensity required for gradient | Attestation and independent source reliability ISSUE-005 |
| Cross-user contamination | credential user allowlists; independent relationship versions; scoped cache and revocation tests | Broader adversarial multi-profile host suite |
| One-off online drift | isolated candidates, group thresholds, KL/norm limits, manual CAS promotion | Long-session and independent task-regression evaluation |
| Compromised trainer/evaluator | fixed thresholds, no host modification API, bounded jobs | OS/process isolation ISSUE-004 |
| SQLite/artifact crash consistency | WAL, atomic artifact rename, hashes, short transactions | Power-loss/GC and backup recovery fault injection |
| Host stalls on engine outage | deadline, max retry, cached or empty injection; actual Pi outage turn | Other native-host outage tests |
| Secret/raw experience leakage | random credentials, scope binding, no raw text collection, core-only export | Formal privacy/CVE/legal audit |
| Resource exhaustion | bounded request bytes/events, per-actor rate limit, queue4/worker1, 1000 recent evidence rows/job, cache128 | Load/security tests with hostile concurrent clients |
