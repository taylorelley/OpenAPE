# ADR 0002: persona-conditioned decoder-v2, independent evaluator, lineage revocation

Status: accepted for 0.2.0. Supersedes the neural, learning and revocation parts of ADR 0001.

## Context (review of 0.1.0 against the brief)

* decoder-v1 was trained with random latent noise and labels that did not depend on
  the latent, so it learned to ignore persona state: every neutral persona chose the
  same controls, and seed preferences could not be applied. That failed §3.3 ("a
  randomly initialised decoder cannot create meaningful behaviour") and §13 demo 2.
* Hashed context features collided; the 20-row catalogue never used low directness,
  varied assertiveness or high humour.
* The trainer computed its own held-out metrics and called the evaluator itself.
* Revoking any core evidence reset the persona to its root and deleted every version,
  even when the evidence had never been used.

## Decisions

* **Catalogue behaviour-controls/1 (24 rows).** Hand-reviewed, append-only table in
  `protocol/catalogue.py`; row 0 is the neutral fallback and is never masked.
  Constraint layer: high stakes/sensitive mask humour, `urgent` masks high verbosity.
* **encoder/2.** Explicit one-hot slots (task, channel, stakes, origin, tags) and
  provider family plus an 8-bucket adapter hash; unused slots are reserved zeros.
* **Auto-decoder training.** The shared MLP (192→128→64→24) and a table of per-persona
  (64-d) and per-relationship (32-d) latents are fitted jointly on soft targets from
  synthetic persona profiles plus context rules; 4 000 neutral rows anchor z=0 to
  context-only behaviour. Personas are partitioned (384 train / 64 calibration /
  96 validation). Validation personas are never seen by the decoder: their latents
  are fitted from 16 pairwise preferences with the decoder frozen (the runtime path)
  and scored on 32 unseen contexts. The decoder is frozen during persona learning.
* **Seed initialization.** `seed_preferences` map to declared profiles; a core latent
  is fitted deterministically against the frozen decoder and labelled
  `initialization: seed_preferences` (never "learned").
* **Snapshot personas (subagents).** `parent_persona_id` copies the parent's active,
  immutable core artifact into a new persona; nothing mutable is shared.
* **Independent evaluator.** `engine/evaluation` owns the grouped split, re-scores the
  candidate on held-out groups and applies fixed thresholds. `engine/learning` only
  fits on the training split it is given and cannot supply metrics or thresholds.
* **Drift budget.** KL between distinct personas is large because the decoder is
  sharp, so KL is reported only. The enforced budget is a latent trust region:
  per-candidate delta norm ≤1.0 (core) / ≤1.5 (relationship), plus an absolute state
  norm ≤ `latent_norm_limit` (1.25 × 99th percentile of trained persona norms).
* **REINFORCE baseline.** Logged sampled ratings use clipped importance weights with
  a mean-reward baseline. Duplicate judgements (same decision, actor, kind) under new
  feedback IDs count once.
* **Lineage revocation.** Versions record the candidate (`job`) that produced them
  and, for relationships, the core version they were trained against. Revoking
  evidence invalidates only candidates that used it and versions derived from them
  (and descendants); those versions are marked revoked (artifacts garbage-collected,
  rollback refused) and active pointers move to the nearest clean ancestor.
  Re-derivation is an explicit admin consolidation on the remaining evidence.
* **Frozen pinning.** `mode: frozen` may name `pinned_version` for evaluation.

## Consequences

* Existing 0.1.0 databases migrate additively, but their sessions pin the old decoder
  hash and return `DECODER_INCOMPATIBLE` until a new session starts; 0.1.0 exports
  cannot be imported (decoder hash mismatch).
* Training the decoder takes ~6.5 min on one CPU thread (was seconds).
* All supervision remains synthetic. Held-out-persona metrics show the latent channel
  works as designed; they are not evidence of human preference satisfaction.
