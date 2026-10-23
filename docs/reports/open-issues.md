# Open release issues (0.3.0, u## ISSUE-001: Live models and remaining host coverage

Live-model evidence is still thin. There were one OpenRouter pilot and one placement
study (one model under test, one judge), plus live tool-calling smokes on Hermes and
OpenClaw with the same model. Three model families are still unmet. OpenCogni's
boundary change is up for review (taylorelley/opencogni#8). Its integration and
evaluator suites (nats-server + PostgreSQL) have not been run. Remaining host gaps:

* Claude Code `PostModelSwitch`/`StopFailure` paths;
* OpenClaw gateway/channel and Codex/Copilot runners;
* Pi child-process lineage and Pi 1.4.0.

Strict xfails: `tests/test_release_gates.py`.

release_gates.py`.

## ISSUE-002 — Independent behavioural evidence

No sealed human/evaluator corpus, blinded identity-distinction study, three-provider ×
three-harness efficacy study or task/safety non-inferiority suite. The simulated-user
benchmark (`benchmarks/reports/simulated.json`) is engineering evidence only: learning
beats the frozen persona, but its preference-satisfaction gain over fixed controls has
a 95% CI that crosses zero. The decoder corpus is synthetic.

## ISSUE-003 — Protocol/SDK completeness

Clients are hand-written and conformance is fixture-based (golden decisions and
rendered text shared by Python and TypeScript), not generated. No published SDK
packages. Session-vector learning/checkpoints are not implemented (session state is
zero). Diagnostic traits are decoder outputs, not independently trained probes.
Seed initialization uses declared synthetic profiles, not learned evidence.

## ISSUE-004: Hardening and isolation

Training runs in an in-process worker thread. Candidate and maturation evaluation run
in a separate spawned process that loads the decoder from disk, but there is no
seccomp or user separation. Several replicas are supported on PostgreSQL. Writes
serialize through one advisory lock, so write throughput is that of one writer. Rate
limits stay per replica, and a lost replica's queued job is abandoned after 15
minutes. Docker 0.3.0 was re-verified (hardened compose, two replicas on PostgreSQL).
Still missing:

* a CVE/licence audit and a penetration test;
* a power-loss artifact GC test;
* backup and recovery automation.

## ISSUE-005 — Provenance and re-derivation

Source reliability is a credential/source class, not an attestation service.
Revocation follows candidate lineage and resets to the nearest clean ancestor, but
re-deriving state from the remaining evidence needs an explicit admin consolidation.
Exports support same-tenant core state only; relationship export is rejected.
Hermes SOUL migration uses keyword heuristics and is always a reviewed dry run first.

## ISSUE-006 — Automatic evolution is unvalidated

Maturation (square-root curve, familiarity profile, context habituation) and the
developmental processes of ADR 0004 (individuality, session state and habits,
novelty, life events, accommodation, cooling, the self anchor, maturity-weighted
influence) are fixed design priors. `benchmarks/development.py` records their
trajectories against qualitative patterns from personality psychology; it is not
human evidence. It is not learned from or validated against people, and no study shows
users prefer a maturing persona. The agent `persona_feedback` tool is offered in
the real Claude Code, Hermes, Pi and OpenClaw builds (host smokes, synthetic model),
and a Pi call is recorded end to end. No live model has used it, so there is no
evidence yet on how often models call it, or how accurately. Autonomous
promotion thresholds were tuned on synthetic labels only.
