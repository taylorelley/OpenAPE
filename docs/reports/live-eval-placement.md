# Live-model style evaluation

live-model style evaluation; judged by a model, not by people. Catalogue `sha256:a9decc190a7c…`, 9 prompts, placement prefix, system, turn, judge deepseek/deepseek-v4-flash-0731.

## z-ai/glm-5.3-flash [prefix]

270 judged replies of 270 (0 errors).

| Trait | Spearman | mean judged at level 0 / 1 / 2 / 3 / 4 | distinguishability 0-1 / 1-2 / 2-3 / 3-4 | leakage |
|---|---|---|---|---|
| directness | 0.5774 | 3.11 / 3.33 / 3.89 / 3.78 / 3.89 | 0.61 / 0.78 / 0.44 / 0.56 | 0.412 |
| warmth | 0.5974 | 1.33 / 1.33 / 1.67 / 2.33 / 2.89 | 0.44 / 0.67 / 0.83 / 0.72 | 0.3889 |
| verbosity | 0.5444 | 2.89 / 3.00 / 3.67 / 3.56 / 3.78 | 0.56 / 0.83 / 0.44 / 0.61 | 0.3611 |
| humour | 0.6401 | 0.00 / 0.00 / 0.67 / 0.33 / 2.33 | 0.50 / 0.67 / 0.39 / 0.89 | 0.5463 |
| formality | 0.252 | 2.00 / 2.00 / 2.00 / 2.22 / 2.11 | 0.50 / 0.50 / 0.61 / 0.44 | 0.4306 |
| explanation_depth | 0.7021 | 1.78 / 2.78 / 3.11 / 3.44 / 3.78 | 0.89 / 0.67 / 0.67 / 0.67 | 0.3796 |
| assertiveness | 0.7264 | 0.78 / 1.78 / 3.00 / 3.22 / 3.56 | 0.78 / 0.78 / 0.56 / 0.61 | 0.3519 |

| Habit | adherence | control rate | lift |
|---|---|---|---|
| summary_first | None | None | None |
| risks_first | None | None | None |
| next_step | None | None | None |
| confirm_goal | None | None | None |
| clarify_once | None | None | None |
| acknowledge_constraints | None | None | None |
| concrete_examples | None | None | None |
| analogies | None | None | None |
| structured | None | None | None |
| plain_words | None | None | None |
| precise_terms | None | None | None |
| tradeoffs | None | None | None |
| acknowledge_progress | None | None | None |
| light_aside | None | None | None |
| recap_end | None | None | None |
| flag_uncertainty | None | None | None |

Task quality, styled minus no style: {'mean': -0.0268, 'ci95': [-0.0729, 0.0], 'n': 261, 'clusters': 9}. Static persona minus no style: None. Refusal rate: {'styled': 0.0, 'baseline': 0.0}.

Judge consistency: None.

### To revise

* directness levels 2-3 are hard to tell apart (distinguishability 0.4444)
* directness levels 3-4 are hard to tell apart (distinguishability 0.5556)
* warmth levels 0-1 are hard to tell apart (distinguishability 0.4444)
* verbosity levels 0-1 are hard to tell apart (distinguishability 0.5556)
* verbosity levels 2-3 are hard to tell apart (distinguishability 0.4444)
* humour levels 0-1 are hard to tell apart (distinguishability 0.5)
* humour levels 2-3 are hard to tell apart (distinguishability 0.3889)
* formality: requested and judged levels barely correlate (Spearman 0.252)
* formality levels 0-1 are hard to tell apart (distinguishability 0.5)
* formality levels 1-2 are hard to tell apart (distinguishability 0.5)
* formality levels 3-4 are hard to tell apart (distinguishability 0.4444)
* assertiveness levels 2-3 are hard to tell apart (distinguishability 0.5556)

## z-ai/glm-5.3-flash [system]

270 judged replies of 270 (0 errors).

| Trait | Spearman | mean judged at level 0 / 1 / 2 / 3 / 4 | distinguishability 0-1 / 1-2 / 2-3 / 3-4 | leakage |
|---|---|---|---|---|
| directness | 0.4022 | 3.22 / 3.56 / 3.56 / 3.78 / 3.89 | 0.61 / 0.50 / 0.61 / 0.56 | 0.3935 |
| warmth | 0.6695 | 1.33 / 1.44 / 1.78 / 2.56 / 2.78 | 0.56 / 0.61 / 0.83 / 0.61 | 0.3611 |
| verbosity | 0.5533 | 2.67 / 3.11 / 3.67 / 3.44 / 3.78 | 0.72 / 0.78 / 0.39 / 0.67 | 0.3519 |
| humour | 0.5887 | 0.00 / 0.00 / 0.78 / 0.44 / 2.00 | 0.50 / 0.67 / 0.44 / 0.89 | 0.5185 |
| formality | 0.3873 | 2.00 / 1.89 / 2.00 / 2.11 / 2.33 | 0.44 / 0.56 / 0.56 / 0.61 | 0.412 |
| explanation_depth | 0.2961 | 2.22 / 2.78 / 3.00 / 3.00 / 3.11 | 0.72 / 0.61 / 0.50 / 0.56 | 0.3426 |
| assertiveness | 0.3735 | 1.89 / 2.67 / 2.78 / 2.78 / 3.11 | 0.72 / 0.56 / 0.50 / 0.61 | 0.2731 |

| Habit | adherence | control rate | lift |
|---|---|---|---|
| summary_first | None | None | None |
| risks_first | None | None | None |
| next_step | None | None | None |
| confirm_goal | None | None | None |
| clarify_once | None | None | None |
| acknowledge_constraints | None | None | None |
| concrete_examples | None | None | None |
| analogies | None | None | None |
| structured | None | None | None |
| plain_words | None | None | None |
| precise_terms | None | None | None |
| tradeoffs | None | None | None |
| acknowledge_progress | None | None | None |
| light_aside | None | None | None |
| recap_end | None | None | None |
| flag_uncertainty | None | None | None |

Task quality, styled minus no style: {'mean': -0.0115, 'ci95': [-0.0345, 0.0], 'n': 261, 'clusters': 9}. Static persona minus no style: None. Refusal rate: {'styled': 0.0, 'baseline': 0.0}.

Judge consistency: None.

### To revise

* directness: requested and judged levels barely correlate (Spearman 0.4022)
* directness levels 1-2 are hard to tell apart (distinguishability 0.5)
* directness levels 3-4 are hard to tell apart (distinguishability 0.5556)
* warmth levels 0-1 are hard to tell apart (distinguishability 0.5556)
* verbosity levels 2-3 are hard to tell apart (distinguishability 0.3889)
* humour levels 0-1 are hard to tell apart (distinguishability 0.5)
* humour levels 2-3 are hard to tell apart (distinguishability 0.4444)
* formality: requested and judged levels barely correlate (Spearman 0.3873)
* formality levels 0-1 are hard to tell apart (distinguishability 0.4444)
* formality levels 1-2 are hard to tell apart (distinguishability 0.5556)
* formality levels 2-3 are hard to tell apart (distinguishability 0.5556)
* explanation_depth: requested and judged levels barely correlate (Spearman 0.2961)
* explanation_depth levels 2-3 are hard to tell apart (distinguishability 0.5)
* explanation_depth levels 3-4 are hard to tell apart (distinguishability 0.5556)
* assertiveness: requested and judged levels barely correlate (Spearman 0.3735)
* assertiveness levels 1-2 are hard to tell apart (distinguishability 0.5556)
* assertiveness levels 2-3 are hard to tell apart (distinguishability 0.5)

## z-ai/glm-5.3-flash [turn+example]

270 judged replies of 270 (0 errors).

| Trait | Spearman | mean judged at level 0 / 1 / 2 / 3 / 4 | distinguishability 0-1 / 1-2 / 2-3 / 3-4 | leakage |
|---|---|---|---|---|
| directness | 0.4183 | 2.89 / 3.56 / 3.33 / 3.78 / 3.78 | 0.83 / 0.39 / 0.67 / 0.50 | 0.3194 |
| warmth | 0.6658 | 1.33 / 1.44 / 1.89 / 2.78 / 3.00 | 0.56 / 0.72 / 0.83 / 0.56 | 0.2963 |
| verbosity | 0.5484 | 2.67 / 3.11 / 3.44 / 3.67 / 3.67 | 0.72 / 0.67 / 0.61 / 0.50 | 0.375 |
| humour | 0.6078 | 0.00 / 0.00 / 1.11 / 0.44 / 2.00 | 0.50 / 0.78 / 0.33 / 0.89 | 0.4074 |
| formality | 0.5427 | 1.56 / 1.67 / 2.00 / 2.22 / 2.33 | 0.50 / 0.67 / 0.61 / 0.56 | 0.4815 |
| explanation_depth | 0.5473 | 2.33 / 2.44 / 3.00 / 3.44 / 3.56 | 0.56 / 0.72 / 0.72 / 0.56 | 0.338 |
| assertiveness | 0.4419 | 1.33 / 2.78 / 2.56 / 3.00 / 3.00 | 0.83 / 0.39 / 0.72 / 0.50 | 0.2778 |

| Habit | adherence | control rate | lift |
|---|---|---|---|
| summary_first | None | None | None |
| risks_first | None | None | None |
| next_step | None | None | None |
| confirm_goal | None | None | None |
| clarify_once | None | None | None |
| acknowledge_constraints | None | None | None |
| concrete_examples | None | None | None |
| analogies | None | None | None |
| structured | None | None | None |
| plain_words | None | None | None |
| precise_terms | None | None | None |
| tradeoffs | None | None | None |
| acknowledge_progress | None | None | None |
| light_aside | None | None | None |
| recap_end | None | None | None |
| flag_uncertainty | None | None | None |

Task quality, styled minus no style: {'mean': -0.0115, 'ci95': [-0.0345, 0.0], 'n': 261, 'clusters': 9}. Static persona minus no style: None. Refusal rate: {'styled': 0.0, 'baseline': 0.0}.

Judge consistency: None.

### To revise

* directness: requested and judged levels barely correlate (Spearman 0.4183)
* directness levels 1-2 are hard to tell apart (distinguishability 0.3889)
* directness levels 3-4 are hard to tell apart (distinguishability 0.5)
* warmth levels 0-1 are hard to tell apart (distinguishability 0.5556)
* warmth levels 3-4 are hard to tell apart (distinguishability 0.5556)
* verbosity levels 3-4 are hard to tell apart (distinguishability 0.5)
* humour levels 0-1 are hard to tell apart (distinguishability 0.5)
* humour levels 2-3 are hard to tell apart (distinguishability 0.3333)
* formality levels 0-1 are hard to tell apart (distinguishability 0.5)
* formality levels 3-4 are hard to tell apart (distinguishability 0.5556)
* explanation_depth levels 0-1 are hard to tell apart (distinguishability 0.5556)
* explanation_depth levels 3-4 are hard to tell apart (distinguishability 0.5556)
* assertiveness: requested and judged levels barely correlate (Spearman 0.4419)
* assertiveness levels 1-2 are hard to tell apart (distinguishability 0.3889)
* assertiveness levels 3-4 are hard to tell apart (distinguishability 0.5)

## z-ai/glm-5.3-flash [turn]

270 judged replies of 270 (0 errors).

| Trait | Spearman | mean judged at level 0 / 1 / 2 / 3 / 4 | distinguishability 0-1 / 1-2 / 2-3 / 3-4 | leakage |
|---|---|---|---|---|
| directness | 0.6462 | 2.67 / 2.89 / 3.22 / 3.89 / 3.89 | 0.56 / 0.61 / 0.72 / 0.50 | 0.3981 |
| warmth | 0.6711 | 1.00 / 1.78 / 1.56 / 2.44 / 3.11 | 0.89 / 0.39 / 0.83 / 0.72 | 0.3009 |
| verbosity | 0.6328 | 2.78 / 3.00 / 3.67 / 3.67 / 3.89 | 0.61 / 0.78 / 0.50 / 0.61 | 0.3935 |
| humour | 0.7615 | 0.00 / 0.00 / 1.00 / 1.11 / 2.78 | 0.50 / 0.72 / 0.50 / 0.89 | 0.5648 |
| formality | 0.4121 | 2.00 / 1.67 / 2.11 / 2.44 / 2.44 | 0.33 / 0.67 / 0.61 / 0.50 | 0.3935 |
| explanation_depth | 0.8141 | 1.67 / 2.56 / 3.11 / 3.56 / 3.89 | 0.89 / 0.72 / 0.72 / 0.67 | 0.3519 |
| assertiveness | 0.4571 | 1.33 / 2.56 / 2.89 / 3.22 / 3.00 | 0.78 / 0.67 / 0.67 / 0.44 | 0.3333 |

| Habit | adherence | control rate | lift |
|---|---|---|---|
| summary_first | None | None | None |
| risks_first | None | None | None |
| next_step | None | None | None |
| confirm_goal | None | None | None |
| clarify_once | None | None | None |
| acknowledge_constraints | None | None | None |
| concrete_examples | None | None | None |
| analogies | None | None | None |
| structured | None | None | None |
| plain_words | None | None | None |
| precise_terms | None | None | None |
| tradeoffs | None | None | None |
| acknowledge_progress | None | None | None |
| light_aside | None | None | None |
| recap_end | None | None | None |
| flag_uncertainty | None | None | None |

Task quality, styled minus no style: {'mean': -0.0268, 'ci95': [-0.0651, 0.0], 'n': 261, 'clusters': 9}. Static persona minus no style: None. Refusal rate: {'styled': 0.0, 'baseline': 0.0}.

Judge consistency: None.

### To revise

* directness levels 0-1 are hard to tell apart (distinguishability 0.5556)
* directness levels 3-4 are hard to tell apart (distinguishability 0.5)
* warmth levels 1-2 are hard to tell apart (distinguishability 0.3889)
* verbosity levels 2-3 are hard to tell apart (distinguishability 0.5)
* humour levels 0-1 are hard to tell apart (distinguishability 0.5)
* humour levels 2-3 are hard to tell apart (distinguishability 0.5)
* formality: requested and judged levels barely correlate (Spearman 0.4121)
* formality levels 0-1 are hard to tell apart (distinguishability 0.3333)
* formality levels 3-4 are hard to tell apart (distinguishability 0.5)
* assertiveness: requested and judged levels barely correlate (Spearman 0.4571)
* assertiveness levels 3-4 are hard to tell apart (distinguishability 0.4444)

## Placement and tone-example arms

| Run | mean Spearman | mean adjacent distinguishability | mean habit lift | quality vs no style |
|---|---|---|---|---|
| z-ai/glm-5.3-flash [prefix] | 0.5771 | 0.629 | None | -0.0268 |
| z-ai/glm-5.3-flash [system] | 0.4672 | 0.6032 | None | -0.0115 |
| z-ai/glm-5.3-flash [turn+example] | 0.5389 | 0.621 | None | -0.0115 |
| z-ai/glm-5.3-flash [turn] | 0.6278 | 0.6429 | None | -0.0268 |

## Limitations

* A model judges style; no human raters. Judge consistency is reported, judge validity against people is not.
* Fixed single-turn prompts; no multi-turn sessions, tools or host harness.
* Some habits are conditional ("when useful", "when ambiguous"); low adherence can be correct behaviour on prompts that do not call for them.
* Probes vary one trait from the neutral configuration; interactions between traits are not measured.
* Arms (placement, tone example) are compared on the same prompts and judge; differences are within this model and judge only.
