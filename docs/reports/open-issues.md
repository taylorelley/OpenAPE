# Open release issues

## ISSUE-001 — Remaining actual host lifecycle and model verification

Pi 1.3.0 native SDK lifecycle passes with synthetic model transport. Actual
provider behavior is untested. Hermes, Claude Code and OpenClaw examples lack
actual full host turn tests. OpenCogni exposes a companion service only and has
no planner injection. Add real pinned installation/doctor/uninstall tests,
compaction/resume/provider-switch/subagent coverage, approved explicit feedback
flows and engine-outage turns. Keep OpenCogni planner boundary changes in a
separate review and run its PostgreSQL/NATS/runtime/evaluator suites.
`tests/test_release_gates.py` retains strict expected failures for four hosts.

## ISSUE-002 — Independent behavioral evidence

No >=200 interaction sealed human/evaluator corpus, blinded identity-distinction
study, three-provider/three-harness efficacy evaluation, predefined safety/task
non-inferiority suite or measured benefit. Decoder corpus is synthetic.
Benchmark evaluator exists; do not invent outcomes. Strict xfail preserves gate.

## ISSUE-003 — Protocol/SDK completeness

Clients are manual; no generated clients or full identical negative corpus for
all API responses. Python client packaging depends on OpenAPE contracts, TS
package on sibling catalogue JSON. Missing SDK distribution artifacts, capability
handshake enforcement, broad compatibility migrations, adapter install/doctor,
subagent snapshot creation, session-vector learning/checkpoints, independently
trained diagnostic probes and explicit seed preference initialization. Neutral
creation is implemented; seed preferences are recorded only and labeled unapplied.

## ISSUE-004 — Hardening and isolation

One in-process bounded worker thread; no OS-isolated trainer/evaluator.
Policy thresholds are fixed code, not changeable by host credentials, but trusted
process compromise could alter them. No exhaustive dependency CVE/license audit,
formal penetration test, crash-consistent artifact GC under power loss, adversarial
load study, automated backup/recovery test, or production multi-instance support.
Rate-limit and job queues are memory-local. Raw transcripts are never accepted.

## ISSUE-005 — Provenance and deletion sophistication

Source reliability is a credential/source class, not a full attestation service.
Actors may supply repeated low-quality labels; canonical session grouping blocks
obvious row leakage but cannot prove independent human evidence. Relationship
revocation resets that relationship to prior; core revocation resets all derived
persona state conservatively. No automatic clean-evidence re-derivation. Candidate
metadata remains for audit, including feedback IDs; revoked candidate artifacts
must be garbage-collected after their reference is removed. Exports only support
same-tenant core; opting into relationship export is explicitly rejected.
