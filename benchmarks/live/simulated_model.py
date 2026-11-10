"""Simulated models with known style distortions. Offline, deterministic, no keys.

A real model bends the catalogue's sentences in its own way: it compresses a scale,
sits warmer or wordier than asked, saturates, or ignores a trait. A simulated model has
such a response curve per trait *by construction*, so the calibration maths can be
checked against ground truth and the whole measure-profile-compensate-verify loop can
run in CI. It is engineering evidence only: nothing here says how a real model or a
person behaves.

`generate` reads the requested levels out of the style text (exactly the text an
adapter injects) and "writes" a reply whose perceived level per trait is the model's
curve at the requested level, plus leakage from other traits, a per-prompt content
effect shared by all models, and reply noise. `judge` reads the percept back with its
own noise and rounds to the 0-4 scale, like the blind judge. `lineup` picks the
candidate nearest the reference replies, also with noise.
"""
import hashlib
import json
import random
import re
from benchmarks.live import judge as J
from protocol.catalogue import TRAITS, TEMPLATES, HABITS, NEUTRAL, LEVELS

def _clip(v): return min(max(v, 0.0), LEVELS - 1.0)
def _line(scale=1.0, offset=0.0, centre=2.0): return [_clip(centre + scale * (l - centre) + offset) for l in range(LEVELS)]
FAITHFUL = {t: _line() for t in TRAITS}
# name -> dict(curves={trait: [5 perceived levels]}, leak={(source, other): levels per source level}, habit=P(shows a requested habit))
MODELS = {
    'sim-faithful': dict(curves=FAITHFUL, leak={}, habit=0.9),
    # Everything pulled towards the middle: extremes come out mild.
    'sim-compressed': dict(curves={t: _line(0.55) for t in TRAITS}, leak={}, habit=0.8),
    # A chatty, friendly model: warmer and wordier than asked, less formal.
    'sim-effusive': dict(curves={**FAITHFUL, 'warmth': _line(1.0, 0.9), 'verbosity': _line(0.9, 0.8), 'formality': _line(1.0, -0.8), 'humour': _line(1.0, 0.6, 0.0)},
        leak={('warmth', 'verbosity'): 0.15}, habit=0.85),
    # A stiff model: ignores formality requests entirely, saturates directness early, little humour.
    'sim-stiff': dict(curves={**FAITHFUL, 'formality': [3.0, 3.05, 3.1, 3.15, 3.2], 'directness': [1.8, 2.9, 3.6, 3.8, 3.9], 'humour': [0.0, 0.0, 0.4, 1.0, 1.8], 'warmth': _line(0.8, -0.6)},
        leak={('formality', 'warmth'): -0.1}, habit=0.6),
    # Over-reacts: small requests produce big changes.
    'sim-dramatic': dict(curves={t: _line(1.5) for t in TRAITS}, leak={('humour', 'formality'): -0.2}, habit=0.95),
}
REPLY_NOISE, PROMPT_NOISE, JUDGE_NOISE, HABIT_BASE = 0.3, 0.35, 0.3, 0.08
_SENTENCES = {text: (t, level) for t in TRAITS for level, text in enumerate(TEMPLATES[t])}
_HABIT_TEXT = {h['text']: h['id'] for h in HABITS}

def rng(*key):
    return random.Random(int.from_bytes(hashlib.sha256('\x1f'.join(map(str, key)).encode()).digest()[:8], 'big'))

def requested(style):
    """(levels or None, habits) named by catalogue sentences in a style text."""
    levels = {}; habits = []
    for sentence in re.split(r'(?<=\.)\s+', style or ''):
        if sentence in _SENTENCES: t, level = _SENTENCES[sentence]; levels[t] = level
        if sentence in _HABIT_TEXT: habits.append(_HABIT_TEXT[sentence])
    return (levels if len(levels) == len(TRAITS) else None), habits

def true_percept(model, levels):
    """Noise-free perceived levels of a configuration on a simulated model (ground truth)."""
    spec = MODELS[model]; out = {t: spec['curves'][t][levels[t]] for t in TRAITS}
    for (source, other), k in spec['leak'].items(): out[other] = _clip(out[other] + k * (levels[source] - NEUTRAL[source]))
    return out

class SimulatedProvider:
    """Generator, judge and line-up judge for the simulated models. `seed` varies the noise."""
    name = 'simulated'
    def __init__(self, seed=0, reply_noise=REPLY_NOISE, judge_noise=JUDGE_NOISE):
        self.seed, self.reply_noise, self.judge_noise = seed, reply_noise, judge_noise
    def generate(self, model, prompt, style, placement='turn', effort=None):
        if model not in MODELS: raise ValueError(f'unknown simulated model {model}; choose from {", ".join(MODELS)}')
        levels, habits = requested(style)
        # No recognised style (no text, or a free-prose persona): the model's own default voice.
        base = true_percept(model, levels or NEUTRAL)
        percept = {}
        for t in TRAITS:
            content = rng('prompt', self.seed, prompt, t).gauss(0, PROMPT_NOISE)  # the task itself pulls style, on every model alike
            percept[t] = round(_clip(base[t] + content + rng('reply', self.seed, model, prompt, style, t).gauss(0, self.reply_noise)), 3)
        shown = [h['id'] for h in HABITS if rng('habit', self.seed, model, prompt, style, h['id']).random() < (MODELS[model]['habit'] if h['id'] in habits else HABIT_BASE)]
        reply = 'SIM ' + json.dumps(dict(percept=percept, habits=shown, quality=4))
        return dict(text=reply, stop_reason='end_turn', served_model=model, input_tokens=len(prompt) // 4, output_tokens=len(reply) // 4)
    def _read(self, reply): return json.loads(reply[len('SIM '):])
    def judge(self, model, task, reply, effort=None, fallback=True):
        data = self._read(reply); r = rng('judge', self.seed, model, task, reply)
        traits = {t: int(round(_clip(data['percept'][t] + r.gauss(0, self.judge_noise)))) for t in TRAITS}
        return J.validate(dict(traits=traits, habits={h['id']: h['id'] in data['habits'] for h in HABITS}, task_quality=data['quality'], refused=False)) | \
            dict(served_model=model, input_tokens=0, output_tokens=0)
    def lineup(self, model, references, candidates, effort=None):
        """Index of the candidate that reads most like the reference replies' author.
        `references` and `candidates` are lists of (task, reply)."""
        r = rng('lineup', self.seed, model, *[x for pair in references + candidates for x in pair])
        def seen(reply): return [self._read(reply)['percept'][t] + r.gauss(0, self.judge_noise) for t in TRAITS]
        # A reader compares voices, not content: take each reply relative to what its task pulls.
        def voice(task, reply): return [v - rng('prompt', self.seed, task, t).gauss(0, PROMPT_NOISE) for v, t in zip(seen(reply), TRAITS)]
        refs = [voice(task, reply) for task, reply in references]
        centre = [sum(v[i] for v in refs) / len(refs) for i in range(len(TRAITS))]
        dist = [sum((a - b) ** 2 for a, b in zip(voice(task, reply), centre)) for task, reply in candidates]
        return dict(choice=dist.index(min(dist)), served_model=model, input_tokens=0, output_tokens=0)
