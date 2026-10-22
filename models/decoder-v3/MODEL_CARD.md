# OpenAPE decoder-v3 model card

Status: **experimental, trained on synthetic profile labels only**. CPU PyTorch 2.5.1
(`requirements.lock`). It selects style controls from the audited
behaviour-controls/2 catalogue (a level 0-4 for each of seven traits, from about
52,000 approved configurations, plus up to three of 16 signature habits). It never
selects permissions, objectives, tools, factual certainty or free text, and never
calls an LLM on the expression path. Exact hash, catalogue hash and metrics:
`decoder.json`.

## Architecture

192 inputs = 64 core latent + 32 relationship latent + 16 session (zero; session state
is applied as a latent offset instead) + 64 encoder/3 context one-hots + 16
provider/adapter features → 128 GELU → 64 GELU, then two heads: 7×5 trait-level logits
and 16 habit logits.

Selection is a fixed procedure on top of the heads:

* Per-trait log-probabilities, with a fixed per-level mask: humour at most 1 for high
  stakes or `sensitive`, verbosity at most 2 for `urgent`.
* The approved configuration with the highest summed log-probability (or a seeded
  sample of the joint distribution over approved configurations, with consent).
* Habits: eligible for the chosen levels and the context, probability above one half,
  most likely first, at most three, mutually exclusive pairs respected.

The score of a choice (configuration plus habit set) is the summed trait
log-probability plus the habit-set log-probability. Pairwise learning compares the
scores of two choices. Diagnostics are expected trait levels and habit probabilities
(decoder outputs), not interpretations of latent coordinates.

## Training (auto-decoder)

`python -m scripts.train_decoder` (seed 42, about 5 minutes on one CPU thread):

* 544 synthetic personas, each a random profile over 2–4 traits (target level 0-4 and
  weight) and 0-2 habit preferences, with two relationship profiles each; partitioned
  384 train / 64 calibration / 96 validation **by persona**.
* 28 576 rows: 40 persona contexts + 2×12 relationship contexts per training persona,
  plus 4 000 neutral rows that anchor the zero latent to context-only behaviour.
* Targets per trait: masked softmax over the five levels of (context rules + profile
  pulls) / 0.35, where a pull scores a level by its distance from the target. Habit
  targets: sigmoid of a base rate plus context and profile terms.
* The decoder and per-persona / per-relationship latent tables are fitted jointly
  (Adam, 700 full-batch steps, per-trait cross-entropy plus habit binary
  cross-entropy, an L2 latent prior of 6e-3 calibrated so the median core latent norm
  is about 1.4, the scale the engine's drift budgets assume).

## Evaluation (synthetic; see decoder.json)

Held-out personas are never seen in training. With the decoder frozen, each one's
latent is fitted from 16 pairwise preferences, as runtime learning does (pairwise
logistic loss, L2 anchor and the relationship trust region of 1.5 latent units), then
scored on 32 unseen contexts. The metric is the mean per-trait level agreement between
the configuration the decoder selects and the one the profile prefers. Habit F1
compares the selected habits with the profile's.

| Partition | neutral latent | fixed default | fitted latent | habit F1 neutral → fitted |
|---|---|---|---|---|
| calibration (64) | 0.542 | 0.530 | 0.633 | 0.609 → 0.631 |
| validation (96) | 0.566 | 0.540 | 0.655 | 0.625 → 0.604 |

Seed initialization agreement per single seed is 0.84–1.00 (`decoder.json`).
Training-row trait-level accuracy is 0.990 and habit accuracy 0.999.

These numbers show that the latent channel is learnable and generalises to unseen
synthetic personas. They are **not** evidence of human preference satisfaction,
identity distinctness for real users, or cross-model benefit. They are also not
comparable with decoder-v2's top-1 agreement over 24 rows.

Two weaknesses are visible. Sixteen pairwise preferences barely move habit
selection, and fitted validation personas pick slightly worse habits than the neutral
latent. Without the trust region, few-shot fitting overshoots (latent norm above 4)
and falls below the neutral latent, so the runtime trust region matters.

## Limitations

Synthetic rules and profiles only; no human authors, users, transcripts or provider
outputs. Context vocabulary is small and categorical (no embeddings). Whether each of
the five levels and each habit changes a live model's reply is unmeasured (see the
live evaluation plan in ADR 0005). The session input is always zero. Other
PyTorch/CPU combinations may change the hash; record theirs.

License: source and weights Apache-2.0; generated corpus CC0-1.0
(`benchmarks/data/PROVENANCE.md`).
