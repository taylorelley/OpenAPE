# Native adapter kit

Implement `PersonalityAdapter<HostEvent>` from sdk/typescript/client.ts, or wrap
the Python client in a documented native host hook. Adapters only map structured
context, inject `result.text` once at an approved context point, and emit bounded
canonical observations. No ML, prompt generation, reward inference or permission
changes belong in an adapter. Reuse `adapters/common.ts` where applicable.

Start from Pi or Hermes source examples; don't copy their hook names to unknown
hosts. Inspect the current official source, pin it, test the real lifecycle and
publish manifest verification levels. SDK fixtures live in protocol/upap/v1;
`tests/adapters.test.ts` is the mock-host harness. Mock tests never establish native
compatibility or provider behavioral efficacy. Integration manifests must distinguish
source-inspected, fixture-tested, actual host-tested and actual model-tested.
