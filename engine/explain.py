"""Why this style: read-only attribution of a served decision, and a persona timeline.

An explanation walks the layers the engine composes, recomputing the decoder's expected
level of each trait as each layer is added: the persona's temperament (its creation
version), its current character (the core version that served the decision), the
linked user's relationship, and this session's state. The largest move names the
layer that shaped the trait; context masks and the user's pins are reported as limits.
Habits are attributed the same way: the decoder's probability, then the learned habit
bias of each version and the session's habit offset, then any veto.

Sentences come from fixed templates over enums and numbers; they are for people reading
a dashboard and are never injected into a model's context.
"""
import math
import torch
from protocol.catalogue import TRAITS, LEVELS, TEMPLATES, HABITS, HABIT_IDS, PREFERENCES
from engine.neural.policy import level_mask, habit_mask, pin_mask, mask_reason

LAYERS = ('temperament', 'character', 'relationship', 'session')
CAUSES = {'temperament': "the persona's temperament", 'character': "how the persona's character has developed",
    'relationship': 'its relationship with this user', 'session': 'feedback earlier in this session'}
MOVE_MIN = 0.25  # expected-level change below which a layer is not named
REFERENCE_CONTEXT = dict(task_type='general', channel='terminal', stakes='low', turn_origin='user', tags=[], language='none', repo_kind='unknown')
REFERENCE_HOST = dict(provider_family='other', adapter_id='custom')
_HABIT = {h['id']: h for h in HABITS}

def _expected(t):
    level = torch.arange(LEVELS, dtype=torch.float)
    return [round(float((t[i].exp() * level).sum()), 3) for i in range(len(TRAITS))]

def _sigmoid(x): return 1 / (1 + math.exp(-x))

def profile(decoder, core, rel, bias=None, context=REFERENCE_CONTEXT, host=REFERENCE_HOST):
    """Expected trait levels and habit probabilities (with the learned habit bias)."""
    with torch.no_grad():
        t, h = decoder.heads(core, rel, context, host)
        if bias is not None: h = h + bias
    return dict(traits=dict(zip(TRAITS, _expected(t))), habits={k: round(_sigmoid(float(h[i])), 3) for i, k in enumerate(HABIT_IDS)})

def explain(decoder, data, layers, biases, settings):
    """`layers`: [(name, core, rel)] in LAYERS order (only those that apply).
    `biases`: {'character', 'relationship', 'session'} habit-logit offsets (tensors)."""
    ctx, host, resp = data['context'], data['host'], data['response']
    with torch.no_grad():
        heads = [(name, *decoder.heads(core, rel, ctx, host)) for name, core, rel in layers]
    path = {name: _expected(t) for name, t, _ in heads}
    lm = level_mask(ctx); pins = settings.get('pins') or {}; pm = pin_mask(pins); reason = mask_reason(ctx)
    traits = {}
    for i, t in enumerate(TRAITS):
        chosen = resp['controls'][t]; values = [path[name][i] for name, *_ in heads]
        moves = [(name, round(values[k] - values[k - 1], 3)) for k, (name, *_) in enumerate(heads) if k]
        allowed = [lv for lv in range(LEVELS) if lm[i, lv]]
        limits = []
        if len(allowed) < LEVELS: limits.append(dict(kind='context', levels=[min(allowed), max(allowed)], reason=reason))
        if t in pins: limits.append(dict(kind='user_pin', levels=[pins[t]['min'], pins[t]['max']]))
        big = max(moves, key=lambda m: abs(m[1]), default=None)
        shaped = big[0] if big and abs(big[1]) >= MOVE_MIN else heads[0][0]
        if shaped == heads[0][0]: why = f'set by {CAUSES[shaped]} (expected {values[0]:.1f})'
        else: why = f"{CAUSES[shaped]} moved it {'up' if big[1] > 0 else 'down'} by {abs(big[1]):.1f}"
        for lim in limits:
            lo, hi = lim['levels']
            span = f'level {lo}' if lo == hi else f'levels {lo}-{hi}'
            why += f'; this context allows only {span}' if lim['kind'] == 'context' else f'; you pinned it to {span}'
        sentence = f"{t.replace('_', ' ').capitalize()} {chosen} (“{TEMPLATES[t][chosen]}”): {why}."
        traits[t] = dict(level=chosen, text=TEMPLATES[t][chosen], expected={name: path[name][i] for name, *_ in heads}, moves=dict(moves), shaped_by=shaped, limits=limits, why=sentence)
    # The summary leads with the traits that a layer or a limit shaped the most.
    ranked = sorted(TRAITS, key=lambda t: (traits[t]['shaped_by'] == heads[0][0] and not traits[t]['limits'], -max([abs(v) for v in traits[t]['moves'].values()] or [0])))
    summary = [traits[t]['why'] for t in ranked[:3]]
    final_h = heads[-1][2]; hm = habit_mask(ctx); vetoes = set(settings.get('vetoes') or [])
    habits = {}
    for k, hid in enumerate(HABIT_IDS):
        parts = {name: round(float(b[k]), 3) for name, b in biases.items() if b is not None and abs(float(b[k])) >= 1e-3}
        logit = float(final_h[k]) + sum(parts.values()); served = hid in resp['habits']
        if not served and not parts and _sigmoid(logit) < 0.3 and hid not in vetoes: continue
        if served: state = 'served'
        elif hid in vetoes: state = 'vetoed by you'
        elif not hm[k]: state = 'off in this context'
        elif not all(lo <= resp['controls'][t] <= hi for t, (lo, hi) in _HABIT[hid]['requires'].items()): state = 'needs other trait levels'
        elif _sigmoid(logit) > 0.5: state = 'outranked (at most three)'
        else: state = 'not likely enough'
        learned = ', '.join(f"{'+' if v > 0 else '-'}{abs(v):.1f} from {CAUSES.get(n, n)}" for n, v in parts.items())
        habits[hid] = dict(state=state, decoder_probability=round(_sigmoid(float(final_h[k])), 3), learned=parts, probability=round(_sigmoid(logit), 3),
            why=f"“{_HABIT[hid]['text']}” {state}" + (f' (learned {learned})' if learned else '') + '.')
    prefs = {k: PREFERENCES[k][v] for k, v in resp.get('preferences', {}).items()}
    return dict(decision_id=resp['decision_id'], context=ctx, layers=[name for name, *_ in heads], traits=traits, habits=habits, preferences=prefs,
        exploration=resp.get('exploration', False), notes=resp['policy'].get('mask_reason'), summary=summary)
