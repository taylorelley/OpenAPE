#!/usr/bin/env bash
# Fast offline checks. Decoder reproduction (~6.5 min) is separate:
#   python -m scripts.check_reproducibility
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pytest -q
node --test sdk/typescript/test.ts tests/adapters.test.ts
python -m scripts.generate_protocol
git diff --exit-code -- protocol examples || { echo 'protocol artifacts out of date; commit regenerated files'; exit 1; }
