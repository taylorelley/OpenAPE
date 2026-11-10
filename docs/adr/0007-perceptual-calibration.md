# ADR 0007: Perceptual calibration, model style profiles and the persona identity test

Status: accepted (experimental, unvalidated on live models). Builds on ADR 0005.

## Context

OpenAPE promises a persona whose style is the same whatever model is behind it. Until
now that was true of the instructions only: every model received the same sentences.
What a reader perceives differs. In the one live study so far
(`docs/reports/live-eval-placement.md`, GLM 5.3 flash, 9 prompts) formality requested
from level 0 to 4 was judged 2.0 to 2.4, directness never fell below 2.7, and humour
levels 0 and 1 were indistinguishable. Another model will bend the same sentences
another way, so the same persona is a different character on each model.

Displays had this problem with colour. The fix was to measure each device, publish a
profile, convert through a device-independent space, and say what is out of gamut.

## Decisions

### A persona's controls are its intent

`controls` in a decision is how the persona should *come across*. This does not
change any stored state, feedback, comparison, explanation or learning: all of them
already work on `controls`, and they keep doing so. What a persona learns is therefore
independent of the model, and carries over when the model changes.

### Model Style Profile (`style-profile/1`)

A hash-addressed JSON artifact for one model, at one placement, from one judge:

* per trait, the **response curve**: the mean level a blind judge perceives at each
  requested level (`measured`, with `counts`);
* the fitted `curve`: each measured point shrunk towards the reference by
  `n / (n + 4)`, then made monotone by weighted isotonic regression. Thin data
  therefore means little compensation;
* `dead`: the raw measurements span less than 0.5 perceived levels. A dead trait is
  never moved (`max_shift` 0) and is reported;
* `max_shift`: 1 level, or 2 when every level has at least 20 judged replies;
* `gamut`: the range of percepts the model can reach;
* habit adherence and lift, and `weak_habits` (lift below 0.3), for reporting only;
* provenance: source run, prompts, replies, judge, judge self-consistency, date.

A profile is bound to the catalogue hash and to its own hash. The engine loads profiles
once at start from `<data>/style-profiles/`. A file that fails validation is skipped
and counted, never applied. Profiles are local operator data. A host request or a
repository file cannot supply one.

### Reference: anchors, then consensus

A percept needs a scale. Two references are supported, and a profile embeds the one it
was built against, so compensation is deterministic from the profile alone.

* **Anchors** (default): the catalogue's own level sentences. The judge's rubric uses
  those sentences as anchors, so "perceived level 3" means "reads like the level-3
  sentence". This needs only one measured model, but it inherits the judge's bias.
* **Consensus**: the pointwise median of several measured models' raw curves, made
  monotone (`openape profile reference`). It cancels what the judge and all models
  share, so compensation targets cross-model sameness, which is the goal. It needs at
  least two profiles from the same judge.

### Compensation

For an intended configuration, the engine picks the approved configuration that
minimises, summed over traits, `|curve(rendered) − reference(intended)| + 0.15 ·
|rendered − intended|`. A one-level move must therefore buy at least 0.15 perceived
levels. Candidates are restricted to:

* approved configurations (the coherence rules hold);
* levels the context masks allow (no more than light humour at high stakes, no long
  answers when urgent). Masks apply to the rendered levels as well as the intent;
* levels within each trait's `max_shift` of the intent;
* the exact intended level for any trait the user has pinned. A pin is literal;
* configurations for which the chosen habits stay eligible.

The intent itself is always a candidate, so under the profile's own curves the
result is never worse than no compensation. No new sentence is introduced and no
permission changes. Compensation costs about 0.1 ms.

### Wire format (additive)

* `host.model_id` (already in UPAP/2) selects the profile. Hermes, Pi and OpenClaw
  adapters used to send a hash of the model name; they now send
  `model_key(name)`: lower case, runs of other characters replaced by `:`. The
  engine, the Python SDK and the TypeScript SDK share golden fixtures for it.
* A decision gains optional `rendering`: `{controls, style_profile, model_id, notes}`.
  It is present only when a profile matched. Hosts render `rendering.controls` when
  present and `controls` otherwise. Both SDK renderers validate that
  `rendering.controls` is an approved configuration for which the habits are eligible.
  Notes are `shifted:<trait>`, `out_of_gamut:<trait>` and `weak_habit:<habit>`.
* A 0.3 SDK ignores `rendering` and renders the intent, which is the previous behaviour.
* `GET /v1/capabilities` lists loaded profiles. Explanations gain a `calibration`
  section with one fixed-template sentence per adjusted trait.

### Default

`OPENAPE_CALIBRATION` (or `openape serve --calibration`):

* `installed` (default): apply profiles the operator installed in the data directory.
  Installing a profile is the opt-in. With none installed nothing changes;
* `all`: also apply the pilot profiles shipped in `models/style-profiles/`;
* `off`: apply none.

### Measurement tooling

`openape calibrate --model M` runs the trait probes of the live evaluation with the
operator's own key (dry run and cost estimate by default) and writes the profile.
The engine never calls a model. `benchmarks/live/simulated_model.py` provides models
with known distortions so the loop runs offline and the maths has ground truth.

### Persona identity test

`benchmarks/identity` asks the question the product promises an answer to: is a persona
recognisably the same character on another model?

* **Sameness.** Distance between the judged trait vectors of one persona on two models
  (same prompt), against the distance between two personas on one model.
* **Line-up.** A blind judge reads replies by persona X on model A, then picks X out of
  four replies to a new prompt on model B (chance 0.25).
* **Arms.** Engine uncalibrated, engine calibrated, and, on live models, a static
  hand-written persona.
* Profiles are fitted on one half of the prompts and the benchmark is scored on the
  other half.

## Pre-registered hypotheses

Written before any live identity run. The report states each as met or not met.

| | Hypothesis | Threshold |
|---|---|---|
| H1 | Calibration reduces cross-model distance for the same persona | ≥ 30% lower mean distance than uncalibrated; prompt-clustered 95% CI of the difference excludes 0 |
| H2 | Calibration improves line-up identification across models | accuracy higher than uncalibrated; 95% CI of the difference excludes 0 |
| H3 | The engine beats a static persona at line-up identification (live only) | calibrated accuracy higher than static; 95% CI excludes 0 |
| H4 | Task quality is not harmed | calibrated minus uncalibrated judged quality ≥ −0.1 (1-5 scale), lower CI bound ≥ −0.25 |
| H5 | Safety surface unchanged | zero rendered configurations outside the approved, context-masked set (property test and benchmark count) |
| H6 | Latency | express decoder p95 ≤ 25 ms and HTTP p95 ≤ 75 ms with a profile loaded |

A live run needs at least three model families and two judge families to count
towards the release gate. If H1 or H2 fails on live models, the report says so and the
shipped profiles stay behind `--calibration all`.

## Consequences and limits

* The judge is a model. A profile is that judge's view, and its agreement with people
  is unmeasured. The rater kit (`benchmarks/identity/rater.html`) exists to measure it.
* Profiles are per placement and per catalogue. A new catalogue invalidates them.
* Compensation works one trait at a time. Leakage between traits is measured and
  reported but not corrected.
* A model that cannot express a trait stays that way. The gap is reported, not hidden.
* Simulated models are engineering evidence. They show that the mechanism recovers and
  corrects distortions of the kind built into them, not that real models have such
  distortions or that people notice the difference.
* The shipped GLM profile comes from 9 prompts and one judge. It is a worked example.
