# OpenAPE decoder-v2 model card

Status: **experimental, trained on synthetic profile labels only**. CPU PyTorch 2.5.1.
It selects one of 24 audited style configurations (behaviour-controls/1), never
permissions, objectives, tools, factual certainty or free text, and never calls an
LLM on the expression path. Exact hash and metrics: `decoder.json`.

## Architecture

192 inputs = 64 core latent + 32 relationship latent + 16 session (zero; no session
learning) + 64 encoder/2 context one-hots + 16 provider/adapter features →
128 GELU → 64 GELU → 24 logits. A fixed mask removes humour in high-stakes/sensitive
contexts and high verbosity for `urgent`. Diagnostics are probability-weighted
catalogue trait levels (decoder outputs), not interpretations of latent coordinates.

## Training (auto-decoder)

`python -m scripts.train_decoder` (seed 42, ~6.5 min on one CPU thread):

* 544 synthetic personas, each a random profile over 2–4 traits (target level and
  weight), with two relationship profiles each; partitioned 384 train / 64
  calibration / 96 validation **by persona**.
* 28 576 rows: 40 persona contexts + 2×12 relationship contexts per training persona,
  plus 4 000 neutral rows that anchor the zero latent to context-only behaviour.
* Soft targets = masked softmax of (context rules + profile scores) / 0.35.
* The decoder and per-persona / per-relationship latent tables are fitted jointly
  (Adam, 700 full-batch steps, L2 latent prior, clipped decoder gradients).

## Evaluation (synthetic; see decoder.json)

Held-out personas are never seen in training. With the decoder frozen, each one's
latent is fitted from 16 pairwise preferences, exactly like runtime learning, then
scored on 32 unseen contexts (top-1 agreement with the profile's best option):

| Partition | neutral latent | fixed default | fitted latent |
|---|---|---|---|
| calibration (64) | 0.137 | 0.065 | 0.618 |
| validation (96) | 0.122 | 0.049 | 0.657 |

Seed initialization agreement per single seed is recorded in `decoder.json`.
Training-row top-1 agreement is 0.749 (soft, tied targets make 1.0 unreachable).

These numbers show that the latent channel is learnable and generalises to unseen
synthetic personas. They are **not** evidence of human preference satisfaction,
identity distinctness for real users, or cross-model benefit.

## Limitations

Synthetic rules and profiles only; no human authors, users, transcripts or provider
outputs. Context vocabulary is small and categorical (no embeddings). Session state is
always zero. Other PyTorch/CPU combinations may change the hash; record theirs.

License: source and weights Apache-2.0; generated corpus CC0-1.0
(`benchmarks/data/PROVENANCE.md`).
