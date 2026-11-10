# Persona identity benchmark

Live models, judged by a model, not by people.

Models: z-ai/glm-5.3-flash, openai/gpt-6-luna, anthropic/claude-haiku-5.5. Judge: deepseek/deepseek-v4.1-flash-1017. 7 personas, 18 prompts to fit profiles, 18 other prompts scored, 378 line-ups. Reference: consensus. Calibration changed the rendered style in 13% of calibrated replies.

| Arm | same persona, two models (distance) | same, averaged over prompts | two personas, one model (distance) | identity ratio | distance from intent | line-up accuracy | task quality |
|---|---|---|---|---|---|---|---|
| calibrated | 0.63 [0.54, 0.72] | 0.45 | 0.60 [0.54, 0.66] | 0.956 | 0.89 [0.83, 0.95] | 0.44 [0.33, 0.54] | 4.88 [4.78, 4.97] |
| static | 0.74 [0.67, 0.82] | 0.57 | 0.84 [0.79, 0.90] | 1.144 | - | 0.81 [0.73, 0.89] | 4.90 [4.77, 4.98] |
| uncalibrated | 0.63 [0.54, 0.72] | 0.47 | 0.62 [0.56, 0.68] | 0.989 | 0.89 [0.83, 0.95] | 0.44 [0.34, 0.53] | 4.88 [4.78, 4.97] |

Distances are mean absolute differences in judged trait levels (0-4), with prompt-clustered 95% intervals. Line-up chance is 0.25. "Averaged over prompts" compares each persona's mean judged style on two models, which removes reply and judge noise and leaves the systematic difference between models. The identity ratio is the distance between two personas over the per-reply distance of one persona across models: above 1, a persona differs less from itself on another model than from another persona.

## Differences between arms (paired)

| Comparison | cross-model distance | relative change | averaged over prompts | relative change | line-up accuracy | task quality |
|---|---|---|---|---|---|---|
| calibrated minus uncalibrated | -0.00 [-0.02, 0.02] | -0% | -0.02 [-0.05, 0.01] | -5% | 0.00 [-0.04, 0.05] | 0.00 [0.00, 0.00] |
| calibrated minus static | -0.11 [-0.17, -0.03] | -15% | -0.13 [-0.21, -0.02] | -22% | -0.42 [-0.59, -0.27] | -0.02 [-0.12, 0.07] |
| uncalibrated minus static | -0.11 [-0.17, -0.04] | -14% | -0.10 [-0.19, -0.01] | -18% | -0.37 [-0.52, -0.23] | -0.02 [-0.12, 0.07] |

## Pre-registered hypotheses (ADR 0007)

* **H1 cross-model distance at least 30% lower: not met** (reduction 0%)
* **H2 line-up accuracy higher than uncalibrated: not met**
* **H4 task quality not harmed: met**
* **H3 line-up accuracy higher than a static persona: not met**
* **H5 nothing rendered outside the approved, masked set: met**

## What each model does to the catalogue

| Model | cannot steer | perceived warmth at levels 0-4 | perceived formality at levels 0-4 |
|---|---|---|---|
| z-ai:glm-5.3-flash | - | 0.8 0.8 1.1 2.1 3.1 | 1.9 1.9 2.4 3.0 3.0 |
| openai:gpt-6-luna | directness, warmth, verbosity, humour, formality, explanation_depth, assertiveness | 0.7 0.8 1.0 1.1 1.5 | 2.0 2.0 2.1 2.2 2.3 |
| anthropic:claude-haiku-5.5 | - | 0.7 0.8 1.3 1.8 2.6 | 2.0 2.0 2.3 2.8 2.9 |

## Limitations

* A model judges style and picks line-ups; agreement with human raters is unmeasured (see benchmarks/identity/rater.html).
* Single-turn prompts; no sessions, tools or host harness.
* Personas are the seven archetypes with no individual variation and no learned state.
* Profiles are fitted on half of the prompts and scored on the other half, from the same prompt set and judge.

Counts towards the live-model release gate on its own: **no** (needs at least three model families and the same run rated by a second judge family).

## Run notes (2026-11-10)

* The gateway account ran out of credit before the run finished. Of 810 persona
  replies, 671 were rated; of 378 planned line-ups, 240 were answered (87 uncalibrated,
  78 calibrated, 75 static), drawn in shuffled order. Paired comparisons use the
  line-ups answered in both arms (67 and 45). Total spend was about $5.
* One judge family only, so this run does not count towards the release gate.
* `openai/gpt-6-luna` barely changed its replies for any trait when the style text was
  placed after the task: every trait was classed as dead, so calibration left it alone.
* The static personas name a role ("You are a patient mentor…") as well as a style. That
  is how such prompts are written in practice, and it is part of why they are easy to
  recognise.
* Records (replies, judgements, line-ups, profiles, blinded rater items and key) are in
  `benchmarks/identity/data/live-2026-11-10.tar.gz`. Unpack it into
  `benchmarks/identity/runs/` to resume, or to add a second judge without regenerating
  replies.
