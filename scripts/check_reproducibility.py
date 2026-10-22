"""Rebuild decoder and assert exact pinned-toolchain hash stability."""
from pathlib import Path
from scripts.train_decoder import main
from engine.neural.policy import digest
p=Path('models/decoder-v2/decoder.safetensors');before=digest(p);main();after=digest(p)
assert before==after,(before,after)
print('PASS: decoder reproduction hash',after)
