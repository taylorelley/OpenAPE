# Open release issues (0.2.0)

## ISSUE-001 — Live models and remaining host coverage

All five hosts now run real turns with a synthetic model endpoint (see
compatibility.md), but **no live provider model** has been called, so the three
model-family requirement is unmet. Remaining host gaps: OpenCogni needs the
`adapters/opencogni/upstream` patch reviewed and merged, and its integration/evaluator
suites (nats-server + PostgreSQL) run; Claude Code `PostModelSwitch`/`StopFailure`
paths; OpenClaw gateway/channel and Codex/Copilot runners; Pi child-process lineage;
Pi 1.4.0. Strict xfails: `tests/test_release_gates.py`.

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

## ISSUE-004 — Hardening and isolation

Training and evaluation run in one in-process worker thread; the evaluator is a
separate module with fixed thresholds that host credentials cannot change, but it is
not OS-isolated. No CVE/licence audit, penetration test, power-loss artifact GC test,
backup/recovery automation or multi-instance support. Rate limits and job queues are
memory-local. Docker image was verified for 0.1.0 only; no Docker daemon was
available to re-run `scripts/docker_smoke.py` for 0.2.0.

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
