# WP3: Decoder

Status: **IMPLEMENTED SYNTHETIC**.

Implemented: CPU MLP, deterministic encoder, 20-control catalogue, high-stakes masks, seed42 corpus generator/training, safetensors and hash.

Evidence/limits: Exact reproducibility hash; 96 synthetic validation examples, 0.9167 accuracy; no human efficacy evidence.

Reproduce from repository root:

```sh
pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
```

Additional commands, host versions and limitations: models/decoder-v1/MODEL_CARD.md; docs/reports/decoder-reproduction.txt.

All results distinguish synthetic engineering evidence from actual host/model
verification and independently measured behavioral benefit. No skipped host gate
is treated as complete. See open-issues.md for the next risks.
