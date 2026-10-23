# Live-model style evaluation

Does each style control actually change what a model writes? This harness answers that
for the behaviour-controls/2 catalogue ([ADR 0005](../../docs/adr/0005-expressive-controls.md)).
It is the gate for revising templates that models do not follow. It calls real models,
costs money, and is never run in CI. `tests/test_live_harness.py` checks it offline.

## What it runs

There are 36 fixed CC0 task prompts (`prompts.jsonl`), four for each task type. Each
prompt runs under these conditions (`design.py`):

| Condition | Style text | Used for |
|---|---|---|
| `baseline` | none | task-quality and refusal reference |
| `static` | the hand-written persona of condition A | does OpenAPE beat a static prompt? |
| neutral | every trait at its neutral level | anchor for trait probes |
| trait probes (28) | neutral with one trait at another level | is each level distinguishable? |
| habit probes (16) | neutral plus one habit (minimal level change to make it eligible) | does the habit appear, against its matched control? |

The style text is rendered by the SDK, byte-identical to what adapters inject. By
default it goes after the task in the user turn, as Claude Code and Hermes place it;
`--placement system` puts it in the system prompt instead. Probes the engine could
never serve in a prompt's context, such as humour above 1 at high stakes, are skipped.

A blind Claude judge (`judge.py`) sees only the task and the reply. It rates each trait
0-4, using the catalogue sentences as anchors, and marks which habits the reply clearly
shows. It also rates task quality 1-5 ignoring style, and flags refusals. Its output is
constrained to a JSON schema. 10% of replies are judged twice, to measure judge
consistency.

## Metrics (`analysis.py`)

* **Trait fidelity:** Spearman correlation between the requested and judged level, and
  the mean judged level at each requested level.
* **Distinguishability** of adjacent levels: on the same prompt, how often the higher
  level is judged higher (0.5 means the model does not tell them apart).
* **Leakage:** how much moving one trait moves the others.
* **Habit lift:** adherence with the habit minus the rate in its matched control.
* **Task-quality and refusal parity:** each styled condition, and the static persona,
  against no style, with prompt-clustered bootstrap intervals.
* **Cross-model agreement:** when several models share a run.

`flags` lists what to revise. The thresholds are distinguishability < 0.6,
Spearman < 0.5, habit lift < 0.3, quality drop > 0.5, and leakage > 0.75.

## Run it

```sh
pip install -e '.[live]'                                  # anthropic SDK (Claude)
python -m benchmarks.live.run                             # dry run: plan + cost estimate
python -m benchmarks.live.run --per-task 1 --execute      # pilot: 9 prompts, ~423 replies
python -m benchmarks.live.run --execute                   # full: 36 prompts, 1688 replies
python -m benchmarks.live.run --provider openai-compatible --model MODEL \
    --base-url https://… --key-env OTHER_PROVIDER_KEY --execute   # another provider family
python -m benchmarks.live.run --report-only               # recompute docs/reports/live-eval.*
```

Credentials resolve as the Anthropic SDK does: `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile. The model under test and the
judge both default to `claude-opus-5-5`, at effort `medium` for generation and `high`
for judging. Change them with `--model`, `--effort`, `--judge-model` and
`--judge-effort`.

Rough estimates from the dry run, with Opus 5.5 for both roles:

| Run | Replies | Estimate |
|---|---|---|
| Pilot (`--per-task 1`) | 423 | ~$24 |
| Full | 1688 | ~$97 |
| Full with a Sonnet 5.5 judge | 1688 | ~$70 |

The estimate assumes fixed token counts per call; check real usage in the records.

Records go to `benchmarks/live/runs/<name>/records.jsonl` (git-ignored) with every
reply, judgement and token count. An interrupted run resumes where it stopped, and
failed calls are retried by the next run. Each provider family adds its own records to
the same run directory and report.

**Refusals.** The model under test never gets a refusal fallback, because a silent
switch to another model would invalidate the measurement. Refusals are recorded and
counted. The judge uses the server-side `fallbacks: "default"`, and the report names
every model that judged. `--no-judge-fallback` turns that off.

## Limitations

* A model judges style, not people. Judge consistency is measured; agreement with
  human raters is not.
* Prompts are single turn: no sessions, tools or host harness.
* Conditional habits ("when useful", "when ambiguous") can rightly be absent on
  prompts that don't call for them.
* Probes vary one trait at a time, so interactions between traits aren't measured.
