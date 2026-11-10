# Persona identity benchmark

Simulated models with built-in distortions; engineering evidence, not live-model or human evidence.

Models: sim-faithful, sim-compressed, sim-effusive, sim-stiff, sim-dramatic. Judge: simulated-judge. 7 personas, 18 prompts to fit profiles, 18 other prompts scored, 840 line-ups. Reference: consensus. Calibration changed the rendered style in 52% of calibrated replies.

| Arm | same persona, two models (distance) | same, averaged over prompts | two personas, one model (distance) | identity ratio | distance from intent | line-up accuracy | task quality |
|---|---|---|---|---|---|---|---|
| calibrated | 0.62 [0.60, 0.63] | 0.39 | 1.04 [1.01, 1.07] | 1.691 | 0.45 [0.43, 0.47] | 0.82 [0.79, 0.86] | 4.00 [4.00, 4.00] |
| uncalibrated | 0.73 [0.71, 0.75] | 0.55 | 0.96 [0.93, 0.99] | 1.317 | 0.51 [0.49, 0.53] | 0.64 [0.60, 0.68] | 4.00 [4.00, 4.00] |

Distances are mean absolute differences in judged trait levels (0-4), with prompt-clustered 95% intervals. Line-up chance is 0.25. "Averaged over prompts" compares each persona's mean judged style on two models, which removes reply and judge noise and leaves the systematic difference between models. The identity ratio is the distance between two personas over the per-reply distance of one persona across models: above 1, a persona differs less from itself on another model than from another persona.

## Differences between arms (paired)

| Comparison | cross-model distance | relative change | averaged over prompts | relative change | line-up accuracy | task quality |
|---|---|---|---|---|---|---|
| calibrated minus uncalibrated | -0.11 [-0.14, -0.09] | -15% | -0.16 [-0.18, -0.12] | -29% | 0.19 [0.14, 0.23] | 0.00 [0.00, 0.00] |

## Pre-registered hypotheses (ADR 0007)

* **H1 cross-model distance at least 30% lower: not met** (reduction 15%)
* **H2 line-up accuracy higher than uncalibrated: met**
* **H4 task quality not harmed: met**
* **H3 line-up accuracy higher than a static persona: not tested**
* **H5 nothing rendered outside the approved, masked set: met**

## What each model does to the catalogue

| Model | cannot steer | perceived warmth at levels 0-4 | perceived formality at levels 0-4 |
|---|---|---|---|
| sim-faithful | - | 0.3 0.9 2.0 3.1 3.8 | 0.3 1.2 2.3 2.9 3.7 |
| sim-compressed | - | 0.9 1.1 2.0 2.7 3.1 | 0.8 1.6 2.0 2.6 3.1 |
| sim-effusive | - | 0.7 1.8 2.8 3.5 3.8 | 0.4 0.6 1.2 2.3 3.2 |
| sim-stiff | formality | 0.2 0.8 1.6 2.4 3.0 | 2.6 2.7 2.7 3.1 3.3 |
| sim-dramatic | - | 0.2 0.8 2.0 3.3 3.8 | 0.3 0.7 2.1 3.4 3.7 |

## Limitations

* Simulated models: their distortions were built in, and the simulated judge reads percepts directly. This tests the mechanism, not real models.
* Task quality is constant in simulation, so H4 is not informative here.
* The static-persona arm (H3) cannot be simulated: a simulated model does not read free prose.
* Personas are the seven archetypes with no individual variation and no learned state.
* Profiles are fitted on half of the prompts and scored on the other half, from the same prompt set and judge.

Counts towards the live-model release gate: **no**.
