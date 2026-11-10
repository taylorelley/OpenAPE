# One Voice: colour management for personality

> Status: milestones 1-6 and 8 are implemented; milestone 7 (the live run) is open.
> One change from this plan: `controls` stays the persona's intent and a new
> `rendering.controls` is what hosts render, the reverse of what is written below.
> ADR 0007 is the authoritative design.

## Context

OpenAPE's headline promise is a persona whose style "stays the same whatever model or
provider is behind" it. Today that promise is only true of the *instructions*: the
engine sends byte-identical style sentences to every model. What the user actually
*hears* differs per model, and the repo's own evidence shows it
(`docs/reports/live-eval-placement.md`, GLM 5.3): formality requested 0→4 is judged
2.00→2.11 (Spearman 0.25), humour levels 0-1 and 2-3 are indistinguishable, directness
saturates at level 2. Another model will bend the same sentences differently. So the
same persona is a different character on each model, and the three open release gates
(ISSUE-001 live families, ISSUE-002 behavioural evidence, ISSUE-006) all sit on this gap.

Screens had the same problem: the same RGB numbers look different on every display.
The fix was colour management: measure each device, publish a profile, convert through
a device-independent space, and report what is out of gamut.

## The goal

**Make an OpenAPE persona perceptually the same character on any model, and prove it
with a blinded identity test: a judge who has met a persona on model A can pick it out
of a line-up on model B.**

Concretely, by the end:

1. Persona state lives in a **perceptual style space** ("how it should come across"),
   not instruction space ("which sentence to send").
2. Every model can have a measured **Model Style Profile** (its response curve per
   trait, its habit adherence, its gamut), produced by one command with the user's own
   key. The engine still never calls an LLM.
3. The engine **compensates** per model inside the audited catalogue: it picks the
   approved configuration whose *predicted perceived* style is nearest the persona's
   intent. No new text, no new permissions, all safety masks intact.
4. A **persona identity benchmark** measures cross-model sameness and line-up
   identification, calibrated vs uncalibrated vs a static markdown persona, with
   hypotheses and thresholds written down before any live run.
5. A **human rater kit** lets people (not just a judge model) run the same blinded
   test, giving the first judge-vs-human agreement number.

Success criteria (pre-registered in ADR 0007, reported whichever way they fall):
cross-model perceptual distance for the same persona drops ≥30% with calibration;
line-up identification beats both the uncalibrated engine and the static persona with
a prompt-clustered 95% CI excluding zero; task quality non-inferior (drop ≤0.1 on the
1-5 scale); zero safety-mask or catalogue violations; express p95 stays ≤25 ms decoder
/ ≤75 ms HTTP.

## Design

### Model Style Profile (`style-profile/1`)
A small hash-addressed JSON artifact per `(model id, placement, catalogue hash, judge)`:

* per trait, the 5-point response curve (mean judged level per requested level) with
  sample counts, fitted monotone by isotonic regression (numpy PAV) and **shrunk to
  identity by sample size**, so thin data means no compensation;
* per trait `gamut` (min/max reachable percept) and a `dead` flag when the curve is
  flat (formality on GLM): the trait is reported, never "corrected";
* per habit adherence and lift; leakage matrix (recorded, used only for reporting in v1);
* provenance: run id, prompts, judge model(s), judge self-consistency, date.

Judges have their own scale bias (GLM "directness 0" is judged 3.1), so targets are not
absolute judge numbers. A **reference observer curve** `R` (median curve across
calibrated models for that judge, shipped as `models/style-profiles/reference.json`) is
the profile connection space: the percept intended by level `L` is `R(L)`; on model `m`
the engine requests the level `l` minimising `|M_m(l) − R(L)|`.

### Compensation (engine, host-independent)
New `engine/neural/calibration.py`, pure functions, no host special cases (profiles are
data, like the decoder):

* `load_profiles(dir)`: hash-checked, catalogue-hash bound, from `models/style-profiles/`
  and `<data>/style-profiles/`.
* `compensate(intended_levels, profile, allowed) -> rendered_levels, notes`: search
  `APPROVED_LEVELS` (already a tensor in `engine/neural/policy.py`) for the configuration
  minimising summed perceptual error, subject to `policy.mask(context)` (hard safety,
  applied to the *rendered* levels), coherence (implicit in `APPROVED`), and a bound of
  ±1 level per trait (`±2` only above a sample-size threshold). Habits whose measured
  lift is below threshold on this model are noted as `habit_weak_on_model`, not dropped.
* No profile, stale catalogue hash, or `calibration: off` → identity. Fully reversible.

Wire-up in `engine/api/app.py` `express` (line ~235), after joint selection and user
settings: user pins and learning operate on **intended** levels; safety masks are
enforced on both intended and rendered levels.

### Protocol (additive, ADR 0007)
* `express.host.model_id` (optional string, bounded) selects the profile;
  `provider_family` alone falls back to a family-level profile if one exists.
* Decision keeps `controls` = what to render (so both SDK renderers and every adapter
  stay byte-identical and unchanged in behaviour) and gains optional
  `intended_controls` and `style_profile` (hash). Feedback, reflections, session state,
  the trainer and the evaluator read `intended_controls` when present, so everything a
  persona learns is model-independent and carries over when the model is switched.
* Regenerate schemas/OpenAPI/conformance with `scripts/generate_protocol.py`; add golden
  fixtures for calibrated decisions to `protocol/upap/v2/conformance.json`; update both
  SDK validators (`sdk/python/lite.py`, `sdk/python/client.py`, `sdk/typescript/client.ts`)
  and `adapters/*/upap_lite.py` copies. Adapters pass the host's model id where the host
  exposes it (Claude Code, Hermes, OpenClaw, Pi).
* `engine/explain.py`: "formality shown one level higher because this model
  under-expresses it (profile …)"; `dashboard.html` shows intended vs rendered.

### Calibration tooling (reuses `benchmarks/live`)
* `benchmarks/live/profile.py`: builds a profile from run records using the existing
  `analysis.trait_metrics` / `habit_metrics` / `bootstrap`; emits the gamut report.
* `benchmarks/live/design.py`: a `calibration` design (baseline, neutral, 28 trait
  probes, optionally habits) so a profile costs a fraction of a full evaluation.
* CLI in `sdk/cli/main.py`: `openape calibrate --model M [--base-url …] [--execute]`
  (dry run with cost estimate by default, exactly like `benchmarks.live.run`),
  `openape profile list | inspect | install | remove`.
* `benchmarks/live/simulated_model.py`: a synthetic provider behind the existing
  `providers.py` interface with *known* distortions (compression, offset, saturation,
  dead trait, leakage) and a noisy synthetic judge. This makes the whole loop
  testable in CI without keys and gives ground truth for the calibration maths.

### Persona identity benchmark (`benchmarks/identity/`)
7 archetype personas × M models × the 36 CC0 prompts; three arms: static markdown
persona (`benchmarks/baselines.py`), engine uncalibrated, engine calibrated.

* **Sameness:** distance between judged trait vectors of the same persona on different
  models, against the distance between different personas on the same model
  (an identity signal-to-noise ratio).
* **Line-up:** the blind judge reads three replies by persona X on model A, then picks
  X from k=4 replies to a new prompt on model B. Accuracy vs chance 0.25.
* **Guardrails:** task quality and refusal parity vs no style (existing judge fields).
* Analysis with the existing prompt-clustered bootstrap; profiles are fitted on one
  prompt split and the benchmark scored on the other, so calibration is never tested on
  the prompts it was fitted on.
* Runs offline end-to-end against simulated models (engineering evidence, labelled so);
  the live run is the real result.

### Human rater kit
`benchmarks/identity/rater.html`: single static file in the style of
`sdk/cli/dashboard.html`. Loads an exported blinded item set, collects line-up choices
and trait ratings, downloads a JSON results file. `benchmarks/identity/humans.py`
computes human accuracy and human-judge agreement (weighted kappa). No data leaves the
rater's browser.

## Milestones

Each lands with tests and a report, and is useful on its own.

1. **ADR 0007 + pre-registration.** Perceptual space, profile format, compensation
   bounds, hypotheses and thresholds. `docs/adr/0007-perceptual-calibration.md`.
2. **Profiles and the maths.** `calibration.py`, `profile.py`, `simulated_model.py`,
   reference curve. Tests: known distortions recovered; identity profile is a no-op;
   dead trait left alone; shrinkage with small n; hash/catalogue binding.
3. **Engine and protocol.** `model_id`, `intended_controls`, `style_profile`; express
   wiring; learning reads intended levels; explanations; regenerated schemas and golden
   fixtures; SDKs and adapters. Tests: masks never violated (property test over all
   mask × profile combinations), pins honoured in intended space, model switch
   mid-persona keeps learned intent, 0.3 clients still validate uncalibrated decisions,
   performance budget.
4. **Self-serve calibration.** `openape calibrate`, `openape profile …`, calibration
   design, docs. Test offline with the simulated provider.
5. **Identity benchmark, simulated.** Harness, analysis, report
   `benchmarks/reports/identity-simulated.json`; added to CI next to
   `benchmarks.simulated`.
6. **Human rater kit.** `rater.html`, export/import, agreement analysis, Node test.
7. **Live run (needs a key from you).** Calibrate ≥3 model families through one
   OpenAI-compatible endpoint, ship their profiles in `models/style-profiles/`, run the
   identity benchmark live with two judge families, publish
   `docs/reports/identity-live.md`. Only if it truly passes does
   `test_live_model_release_gate` in `tests/test_release_gates.py` stop being an xfail.
8. **Release notes.** README section "One voice on every model", CHANGELOG (0.4.0),
   `release-status.md`, `open-issues.md`, `risk-register.md` updated with exactly what
   was and was not shown.

Milestones 1-6 need no credentials. This session has no provider key, so 7 waits for one
(roughly $60-150 at current pilot pricing with flash-class models under test; the dry
run will give the exact estimate before anything is spent).

## Risks and how the plan handles them

* **The judge is not a person.** Two judge families, measured self-consistency, the
  human kit, and reports that keep the repo's "judged by a model, not by people" label.
* **Compensation makes things worse on noisy profiles.** Shrinkage to identity, ±1
  bound, held-out prompt split, and `calibration: off` per persona or per engine.
* **A model cannot express a trait at all.** Reported as out of gamut in the profile,
  the explanation and the dashboard, instead of silently pushed to an extreme.
* **Safety surface.** No new sentences; rendered levels are still an approved
  configuration under the context masks; profiles are local hash-checked data and
  cannot be supplied by a repository or a host request.
* **The hypothesis is false.** Then the report says so, calibration stays off by
  default, and the profiles and identity benchmark still close most of ISSUE-001.

## Verification

```sh
bash scripts/check_all.sh                       # pytest + node + protocol regeneration clean
python -m scripts.offline_smoke                 # lifecycle unchanged with calibration off
python -m benchmarks.live.run --provider simulated --design calibration --execute
openape calibrate --model simulated:compressed --execute && openape profile inspect simulated:compressed
python -m benchmarks.identity.run --simulated   # calibrated arm must beat uncalibrated on known distortions
python -m scripts.performance                   # p95 within the existing targets
python -m scripts.real_host_smoke               # adapters still inject byte-identical text for a given decision
# with a key (milestone 7):
openape calibrate --model MODEL --base-url URL            # dry run, cost estimate
python -m benchmarks.identity.run --models A B C --execute
```

Manual check: create a `mentor` persona, `openape preview` the same context with two
different `model_id`s, and confirm intended controls match while rendered controls
differ only where the profiles say they should, with the reason in
`GET /v1/decisions/{id}/explanation`.
