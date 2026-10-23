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
* User settings narrow both heads after the context masks: trait pins restrict levels
  (context masks win), habit vetoes remove habits.
* Habits: the habit logits plus the learned habit bias of the core and relationship
  versions and this session's habit offset; then eligible for the chosen levels and
  the context, probability above one half, most likely first, at most three, mutually
  exclusive pairs respected.

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
latent is fitted from 16 pairwise preferences, as runtime learning does (a trait-only
pairwise logistic loss, L2 anchor and the relationship trust region of 1.5 latent
units), then scored on 32 unseen contexts. The metric is the mean per-trait level
agreement between the configuration the decoder selects and the one the profile
prefers. Habit F1 compares the selected habits with the profile's: from the fitted
latent alone, and with the habit bias the runtime learns from the same pairs
(engine/learning/habits.py, weighted as a new user's feedback).

| Partition | neutral latent | fixed default | fitted latent | habit F1 neutral / fitted / fitted + bias |
|---|---|---|---|---|
| calibration (64) | 0.567 | 0.526 | 0.735 | 0.646 / 0.477 / 0.517 |
| validation (96) | 0.594 | 0.535 | 0.742 | 0.635 / 0.408 / 0.625 |

Seed initialization agreement per single seed is 0.84–1.00 (`decoder.json`).
Training-row trait-level accuracy is 0.991 and habit accuracy 0.9995.

The previous decoder-v3 build fitted traits and habits together (validation 0.655).
Fitting traits only, with habits learned separately as a bias, raises fitted
agreement to 0.742. The latent fit alone still moves habit selection away from the
profile (0.408); the learned habit bias brings it back to the neutral level (0.625),
not above it. Sixteen pairs carry little habit evidence.

### Episodic training (tried, off by default)

`--episodic-steps 300` adds a MAML-style phase after the main one: episodes of 16
support pairs and 24 query contexts from training personas, 8 differentiable inner
steps from a zero latent with a learned step size and the trust region, the query
loss back-propagated into the decoder. Results on the validation partition:

| Run | fitted | neutral | habit F1 fitted |
|---|---|---|---|
| no episodic phase (shipped) | 0.742 | 0.594 | 0.408 |
| episodic, query weight 0.1 | 0.742 | 0.557 | 0.334 |
| episodic, query weight 1.0 | 0.580 | 0.376 | 0.483 |

It brought no gain at weight 0.1 and hurt at weight 1.0, so it ships off. The code
stays for comparison.

These numbers show that the latent channel is learnable and generalises to unseen
synthetic personas. They are **not** evidence of human preference satisfaction,
identity distinctness for real users, or cross-model benefit.

## Limitations

Synthetic rules and profiles only; no human authors, users, transcripts or provider
outputs. Context vocabulary is small and categorical; the optional on-host text
classifier is a hashed-feature linear model trained on a templated corpus
(`docs/reports/context-classifier.json`). Live-model checks so far are small pilots
with one model and one judge (`docs/reports/live-eval*`). The session input is always zero. Other
PyTorch/CPU combinations may change the hash; record theirs.

License: source and weights Apache-2.0; generated corpus CC0-1.0
(`benchmarks/data/PROVENANCE.md`).
