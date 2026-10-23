"""Conditions for the live-model evaluation: which style text goes with which prompt.

Every prompt gets:

* `baseline`: no style text (task-quality and refusal reference).
* `static`: the hand-written markdown persona of condition A (`benchmarks/baselines.py`).
* `neutral`: the neutral configuration (every trait at its neutral level, no habits).
* Trait probes: the neutral configuration with one trait moved to each other level.
  Comparing a trait's five probes on the same prompt measures whether its levels
  produce distinguishable replies.
* Habit probes: the neutral configuration plus one habit, with the smallest trait
  change that makes the habit eligible. Its matched control is the same configuration
  without the habit (the neutral or a trait probe), so the habit's effect is not
  confounded with a level change.

The engine's per-level and per-habit context masks apply: a probe the engine could
never serve in a prompt's context (for example humour above 1 at high stakes) is
skipped for that prompt. Style text comes from the SDK renderer, byte-identical to
what adapters inject.
"""
import json
from pathlib import Path
from protocol.catalogue import TRAITS, LEVELS, NEUTRAL, HABITS, CATALOGUE_HASH, SCHEMA, coherent, habit_allowed
from sdk.python.lite import render
from engine.neural.policy import level_mask, habit_mask, HABIT_IDS

ROOT = Path(__file__).resolve().parent
PROMPTS = ROOT / 'prompts.jsonl'

def load_prompts(path=PROMPTS):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]

def context_of(prompt):
    return dict(task_type=prompt['task_type'], channel='terminal', stakes=prompt['stakes'], turn_origin='user', tags=prompt['tags'])

def style_text(controls, habits=(), example=False):
    """The text an adapter would inject for these controls (active mode); `example`
    appends the reviewed tone example, as with OPENAPE_STYLE_EXAMPLE=1."""
    return render(dict(protocol_version='upap/2', request_id='live-eval', decision_id='live-eval', persona_version='live-eval', decoder_hash='live-eval',
        control_schema=SCHEMA, catalogue_hash=CATALOGUE_HASH, controls=dict(controls), habits=list(habits), preferences={}, mode='active',
        applies_to='next_model_request', policy={'eligible': True}, cache_ttl_ms=0), example)

def condition_id(controls, habits=()):
    return 'c' + ''.join(str(controls[t]) for t in TRAITS) + ('+' + '+'.join(habits) if habits else '')

def _enabling(habit):
    """The neutral configuration with the smallest change that makes the habit eligible."""
    controls = dict(NEUTRAL)
    for t, (lo, hi) in habit['requires'].items():
        controls[t] = min(max(controls[t], lo), hi)
    return controls

def conditions(example=False):
    """All conditions independent of context: dicts with id, kind, controls, habits, text."""
    style = lambda c, hs=(): style_text(c, hs, example)
    from benchmarks.baselines import STATIC_MARKDOWN
    out = [dict(id='baseline', kind='baseline', controls=None, habits=[], text=''),
           dict(id='static', kind='static', controls=None, habits=[], text=STATIC_MARKDOWN),
           dict(id=condition_id(NEUTRAL), kind='neutral', controls=dict(NEUTRAL), habits=[], text=style(NEUTRAL))]
    for t in TRAITS:
        for level in range(LEVELS):
            if level == NEUTRAL[t]: continue
            c = dict(NEUTRAL, **{t: level})
            if coherent(c): out.append(dict(id=condition_id(c), kind='trait', trait=t, level=level, controls=c, habits=[], text=style(c)))
    for h in HABITS:
        c = _enabling(h)
        assert coherent(c) and habit_allowed(h, c), h['id']
        out.append(dict(id=condition_id(c, [h['id']]), kind='habit', habit=h['id'], controls=c, habits=[h['id']], text=style(c, [h['id']]),
            control_id=condition_id(c)))
    return out

def allowed(condition, context):
    """Whether the engine could serve this condition in this context."""
    if condition['controls'] is None: return True
    lm = level_mask(context); hm = habit_mask(context)
    return all(bool(lm[i, condition['controls'][t]]) for i, t in enumerate(TRAITS)) and all(bool(hm[HABIT_IDS.index(h)]) for h in condition['habits'])

def plan(prompts, selected=None, example=False):
    """(prompt, condition) pairs to run. `selected` limits condition kinds or ids."""
    conds = conditions(example); rows = []
    keep = {c['id'] for c in conds if not selected or c['kind'] in selected or c['id'] in selected or c['kind'] in ('baseline', 'neutral')}
    keep |= {c['control_id'] for c in conds if c['kind'] == 'habit' and c['id'] in keep}  # matched controls
    for p in prompts:
        ctx = context_of(p)
        for c in conds:
            if c['id'] not in keep: continue
            if not allowed(c, ctx): continue
            # A habit probe needs its matched control on the same prompt.
            if c['kind'] == 'habit' and not allowed(dict(c, habits=[]), ctx): continue
            rows.append((p, c))
    return rows
