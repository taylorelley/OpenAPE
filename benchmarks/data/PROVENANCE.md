# Corpus provenance

`decoder-corpus.jsonl` lists the 544 synthetic personas (group, partition, persona
profile and two relationship profiles) that `scripts/train_decoder.py` generates
from seed 42. Training rows are regenerated deterministically from the same seed;
their SHA-256 is recorded as `training.corpus_sha256` in `models/decoder-v2/decoder.json`.

Creator: OpenAPE project build, 2026-10-22. Dedication: **CC0-1.0**
(https://creativecommons.org/publicdomain/zero/1.0/). No external text, model or
provider completions, real feedback or personal data. All labels are **synthetic
profile/rule labels**, not human evidence.

Partitions are grouped by persona, so validation personas never appear in decoder
training. Context rules are shared across partitions, so these metrics measure the
decoder's ability to represent and fit synthetic profiles, not real-world validity.

`benchmarks/simulated.py` uses a different generator (continuous per-level utilities,
sealed seed 20261022, noisy answers) and never feeds decoder training.
