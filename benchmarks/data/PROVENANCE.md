# Corpus provenance

`decoder-corpus.jsonl` is generated entirely by the original, inspectable
`corpus()` rules in `scripts/train_decoder.py`. Creator: OpenAPE project build,
2026-10-21. Dedication: **CC0-1.0** (https://creativecommons.org/publicdomain/zero/1.0/).
No external text, model/provider completions, real feedback or personal data.
All labels are **synthetic rule labels**. They are not human evidence.

Scenario families are grouped before train/calibration/validation splitting.
The same task vocabulary and labeling rules appear across these partitions;
these metrics measure reproduction of the rule generator only. A sealed,
independent benchmark must be separately collected. Never train on those outcomes.
