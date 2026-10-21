# OpenAPE decoder-v1 model card

Status: **experimental, trained on synthetic labels only**. CPU PyTorch 2.5.1.
No measured human/persona/LLM efficacy. The model selects one of 20 bounded style
configurations, not permissions, objectives, tools, factual certainty or arbitrary
instructions. It never calls an LLM on the expression path.

Architecture: 192 inputs = 64 core + 32 relationship + 16 zero session + 64
encoder/1 context features + 16 provider/adapter features. 128 GELU, 64 GELU, 20
logits. Safetensors artifact and SHA-256 manifest. Decoding applies a fixed mask
against humour for high-stakes/sensitive contexts. Diagnostic outputs are the seven
catalogue controls; no psychological interpretation of latent coordinates.

Training source: `scripts/train_decoder.py` creates 432 original rule-labeled
examples, grouped by 36 synthetic scenario families. 288 train, 48 calibration,
96 validation. There are no human authors, real users, transcripts, proprietary
provider outputs or independent task-family validation. Synthetic family grouping
protects fixture separation only; it does not establish real-world generalization.
Training uses seed 42, Adam .006, 180 full-batch steps, clipped gradients and
small random latent perturbations. Calibration is reported, not used for tuning.

`decoder.json` records exact hash and metrics. Reproduce from checkout:

```sh
python -m scripts.train_decoder
```

On the pinned toolchain/CPU, rerunning should reproduce the hash and metrics.
Other PyTorch/hardware versions can differ; record their hashes before deployment.
Routine learning freezes these shared weights and fits only a core or relationship
latent from explicitly consenting feedback. It never mutates active state until
administrator promotion passes evaluation. Session adaptation is not implemented.

Limitations: tiny deterministic rule corpus, context hash collisions, no semantic
embeddings, no independently labeled author/task partitions, no three-provider
behavior study, no benchmark win. Synthetic preference tests demonstrate the
optimizer works and can be rejected; they do not prove learned personality.

License: source and weights Apache-2.0; the original generated corpus is dedicated
to the public domain under CC0-1.0. See `benchmarks/data/PROVENANCE.md`.
