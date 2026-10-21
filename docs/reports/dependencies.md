# Dependency and artifact inventory

Exact tested Python distributions are pinned in `requirements.lock`. PyTorch
uses the CPU-only index; no CUDA/GPU/provider dependency is required. Node SDK and
adapters use Node built-ins and the checked-in catalogue; no runtime npm package
is required by those sources. The optional real-host test pins Pi 1.3.0 in
`.host-test`, excluded from distribution. Download it with README instructions.

Direct runtime licenses (upstream package metadata; not a legal opinion):
FastAPI MIT, Uvicorn BSD-3-Clause, Pydantic MIT, PyTorch BSD-3-Clause,
safetensors Apache-2.0, HTTPX BSD-3-Clause, NumPy BSD-3-Clause. Source build
uses setuptools MIT and packaging BSD/Apache. Full installed license metadata
is available using `importlib.metadata`; dependency sources retain their licenses.
Original corpus is CC0-1.0; weights are Apache-2.0. No upstream host source or
HTML documentation is redistributed; source/document fetch checksums are retained.

No comprehensive CVE scanner, transitive-license legal review, signed SBOM or
supply-chain attestation has been performed. That release gate remains open.
Locked versions improve reproducibility, not a claim of zero vulnerabilities.
