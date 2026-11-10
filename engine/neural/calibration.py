"""Perceptual style calibration (ADR 0007): the same persona should come across the same
on every model.

A persona's controls are its *intent*: how each trait should come across. Models bend
the same catalogue sentences differently, so a Model Style Profile (`style-profile/1`)
records, per trait, the level a blind judge perceives for each requested level (the
model's response curve) next to a reference curve. Compensation picks the approved
configuration whose predicted percept on this model is nearest the reference percept of
the intent, and the host renders that configuration instead.

Host-independent and data-only: a profile is a hash-checked JSON artifact bound to the
catalogue, like the decoder. Nothing here calls a model. Compensation never leaves the
approved catalogue, never crosses a context mask, never moves a pinned trait, keeps the
chosen habits eligible, and moves a trait by at most its profile's `max_shift`.
"""
import hashlib
import json
import re
from pathlib import Path
import torch
from protocol.catalogue import TRAITS, LEVELS, HABIT_IDS, CATALOGUE_HASH
from engine.neural.policy import APPROVED_LEVELS, INDEX, N_TRAITS, level_mask, habits_allowed

FORMAT = 'style-profile/1'
SHRINK = 4.0          # replies per level at which a measured point counts as much as the reference
DEAD_RANGE = 0.5      # a curve spanning less than this many perceived levels cannot be steered
DEAD_SPEARMAN = 0.3   # nor can a trait whose requested and judged levels correlate less than this
WIDE_SHIFT_N = 20     # replies per level before a trait may move two levels instead of one
SHIFT_COST = 0.15     # perceived-level gain a one-level move must buy
GAMUT_MARGIN = 0.5    # intent further than this outside the reachable range is out of gamut
HABIT_LIFT_MIN = 0.3  # below this lift a habit is reported as weak on the model
_SAFE = re.compile(r'[^a-z0-9_.:-]+')
_ROWS = torch.arange(N_TRAITS)
_LEVELS = torch.arange(LEVELS).expand(N_TRAITS, LEVELS)
ANCHORS = [float(i) for i in range(LEVELS)]  # the catalogue's own level sentences as the scale

def model_key(model_id):
    """A model name as a wire-safe identifier ('z-ai/GLM-5.3' -> 'z-ai:glm-5.3')."""
    key = _SAFE.sub(':', str(model_id).strip().lower()).strip(':')
    return key[:100] or 'unspecified'

def isotonic(values, weights=None):
    """Weighted pool-adjacent-violators: the non-decreasing sequence closest to `values`."""
    weights = list(weights) if weights is not None else [1.0] * len(values)
    blocks = []  # [mean, weight, count]
    for v, w in zip(values, weights):
        blocks.append([float(v), max(float(w), 1e-9), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2, c2 = blocks.pop(); m1, w1, c1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    return [m for m, _, c in blocks for _ in range(c)]

def fit_curve(means, counts, reference):
    """A model's monotone response curve from the mean judged level per requested level.

    Each measured point is shrunk towards the reference by its sample size, so thin
    data means little compensation; unmeasured levels take the reference value."""
    shrunk = []; weights = []
    for level in range(LEVELS):
        m, n = means[level], counts[level] if means[level] is not None else 0
        w = n / (n + SHRINK)
        shrunk.append(reference[level] if m is None else w * float(m) + (1 - w) * reference[level]); weights.append(n + SHRINK)
    return [round(min(max(v, 0.0), LEVELS - 1.0), 4) for v in isotonic(shrunk, weights)]

def trait_entry(means, counts, reference, spearman=None):
    measured = [m for m in means if m is not None]
    curve = fit_curve(means, counts, reference)
    # Deadness is judged on the raw measurement: shrinking a flat curve towards the
    # reference would otherwise make an unresponsive trait look steerable.
    # A trait is also dead when requested and judged levels barely correlate, which catches
    # a flat curve whose noisy means happen to span more than DEAD_RANGE.
    dead = len(measured) >= 3 and ((max(measured) - min(measured)) < DEAD_RANGE or (spearman is not None and spearman < DEAD_SPEARMAN))
    n = min((c for m, c in zip(means, counts) if m is not None), default=0)
    max_shift = 0 if dead or not measured else 2 if n >= WIDE_SHIFT_N else 1
    return dict(curve=curve, reference=[round(float(r), 4) for r in reference], measured=[None if m is None else round(float(m), 4) for m in means],
        counts=[int(c) for c in counts], spearman=spearman, dead=dead, max_shift=max_shift, gamut=[curve[0], curve[-1]])

def profile_hash(profile):
    body = {k: v for k, v in profile.items() if k != 'hash'}
    return 'sha256:' + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def seal(profile):
    profile = dict(profile); profile['hash'] = profile_hash(profile); return profile

def validate(profile):
    """Raise ValueError unless this is a well-formed, untampered profile for this catalogue."""
    if not isinstance(profile, dict) or profile.get('format') != FORMAT: raise ValueError('not a style-profile/1 artifact')
    if profile.get('hash') != profile_hash(profile): raise ValueError('style profile checksum mismatch')
    if profile.get('catalogue_hash') != CATALOGUE_HASH: raise ValueError('style profile was measured against another catalogue')
    if not isinstance(profile.get('model_id'), str) or profile['model_id'] != model_key(profile['model_id']): raise ValueError('style profile model id')
    traits = profile.get('traits')
    if not isinstance(traits, dict) or set(traits) != set(TRAITS): raise ValueError('style profile traits')
    for t in TRAITS:
        e = traits[t]
        for name in ('curve', 'reference'):
            c = e.get(name)
            if not isinstance(c, list) or len(c) != LEVELS or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= LEVELS - 1 for v in c): raise ValueError(f'style profile {name}')
            if any(b < a for a, b in zip(c, c[1:])): raise ValueError(f'style profile {name} is not monotone')
        if e.get('max_shift') not in (0, 1, 2) or type(e.get('dead')) is not bool: raise ValueError('style profile bounds')
        if e['dead'] and e['max_shift']: raise ValueError('a dead trait cannot be shifted')
    weak = profile.get('weak_habits', [])
    if not isinstance(weak, list) or any(h not in HABIT_IDS for h in weak): raise ValueError('style profile habits')
    return profile

class Profiles:
    """Profiles by model key. A file that fails validation is skipped and reported, never applied."""
    def __init__(self, directories=()):
        self.by_model = {}; self.rejected = []
        for directory in directories:
            for path in sorted(Path(directory).glob('*.json')) if Path(directory).is_dir() else ():
                if path.name == 'reference.json': continue
                try:
                    p = validate(json.loads(path.read_text())); self.by_model[p['model_id']] = _compiled(p)
                except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
                    self.rejected.append(dict(path=str(path), reason=str(exc)[:200]))
    def get(self, model_id):
        return self.by_model.get(model_key(model_id)) if model_id else None
    def summary(self):
        return [dict(model_id=k, hash=p['hash'], placement=p.get('placement'), judge=p.get('judge'),
            dead=[t for t in TRAITS if p['traits'][t]['dead']], max_shift={t: p['traits'][t]['max_shift'] for t in TRAITS}) for k, p in sorted(self.by_model.items())]

def _compiled(profile):
    """Attach the tensors compensation needs (not part of the artifact)."""
    p = dict(profile)
    p['_curve'] = torch.tensor([profile['traits'][t]['curve'] for t in TRAITS], dtype=torch.float)
    p['_reference'] = torch.tensor([profile['traits'][t]['reference'] for t in TRAITS], dtype=torch.float)
    p['_shift'] = torch.tensor([profile['traits'][t]['max_shift'] for t in TRAITS])
    return p

def compiled(profile):
    return profile if '_curve' in profile else _compiled(validate(profile))

def predict(profile, levels):
    """Perceived level of each trait when `levels` ({trait: level}) is rendered on this model."""
    p = compiled(profile)
    return {t: float(p['_curve'][i, levels[t]]) for i, t in enumerate(TRAITS)}

def intent(profile, levels):
    """The percept the intent stands for: the reference curve at each intended level."""
    p = compiled(profile)
    return {t: float(p['_reference'][i, levels[t]]) for i, t in enumerate(TRAITS)}

def compensate(action, habits, context, profile, pins=None):
    """The approved configuration to render for intended `action` on this model.

    Returns (rendered action, notes). Candidates are approved configurations allowed in
    this context, within each trait's max_shift of the intent, that leave pinned traits
    alone and keep the chosen habits eligible. The intent itself is always a candidate,
    so the result is never worse than no compensation under the profile's own curves."""
    p = compiled(profile); intended = APPROVED_LEVELS[action]
    target = p['_reference'][_ROWS, intended]                         # (7,)
    shift_limit = p['_shift'].clone()
    for t in (pins or {}): shift_limit[TRAITS.index(t)] = 0           # a user's pin is literal
    moved = (_LEVELS - intended.unsqueeze(1)).abs()                   # (7, 5): levels each candidate level is from the intent
    table = (p['_curve'] - target.unsqueeze(1)).abs() + SHIFT_COST * moved
    table = table.masked_fill((moved > shift_limit.unsqueeze(1)) | ~level_mask(context), float('inf'))
    notes = []; best = action
    # Each trait's own best level is the answer whenever together they form an approved
    # configuration that keeps the habits eligible; otherwise search every approved one.
    greedy = INDEX.get(tuple(table.argmin(1).tolist()))
    if greedy is not None and (greedy == action or habits_allowed(list(habits), greedy, context)): best = greedy
    else:
        cost = table[_ROWS, APPROVED_LEVELS].sum(1)                   # (ACTIONS,); inf where not allowed
        for candidate in torch.topk(cost, 16, largest=False).indices.tolist():
            if not torch.isfinite(cost[candidate]): break
            if candidate == action or habits_allowed(list(habits), candidate, context): best = candidate; break
    rendered = APPROVED_LEVELS[best]
    shifted = [t for i, t in enumerate(TRAITS) if int(rendered[i]) != int(intended[i])]
    lo, hi = p['_curve'][:, 0], p['_curve'][:, -1]
    out = [t for i, t in enumerate(TRAITS) if float(target[i]) < float(lo[i]) - GAMUT_MARGIN or float(target[i]) > float(hi[i]) + GAMUT_MARGIN]
    notes += [f'shifted:{t}' for t in shifted] + [f'out_of_gamut:{t}' for t in out]
    notes += [f'weak_habit:{h}' for h in habits if h in p.get('weak_habits', [])]
    return best, notes

def rendering(action, habits, context, profile, pins=None):
    """The wire `rendering` object for a decision, or None when there is no profile."""
    if profile is None: return None
    best, notes = compensate(action, habits, context, profile, pins)
    return dict(controls=dict(zip(TRAITS, APPROVED_LEVELS[best].tolist())), style_profile=profile['hash'], model_id=profile['model_id'], notes=notes)

def build(model_id, traits, habits=None, placement='turn', judge=None, source=None, reference=None, reference_kind='anchors'):
    """Assemble and seal a profile.

    `traits`: {trait: dict(means=[5 means or None], counts=[5 ints], spearman=float|None)}.
    `habits`: {habit: dict(adherence, control_rate, lift)} (optional).
    `reference`: {trait: [5 perceived levels]}; default is the catalogue anchors."""
    reference = reference or {t: ANCHORS for t in TRAITS}
    entries = {t: trait_entry(traits[t]['means'], traits[t]['counts'], reference[t], traits[t].get('spearman')) for t in TRAITS}
    habits = habits or {}
    weak = [h for h in HABIT_IDS if h in habits and habits[h].get('lift') is not None and habits[h]['lift'] < HABIT_LIFT_MIN]
    return seal(dict(format=FORMAT, model_id=model_key(model_id), catalogue_hash=CATALOGUE_HASH, placement=placement, judge=judge,
        reference_kind=reference_kind, traits=entries, habits={h: habits[h] for h in HABIT_IDS if h in habits}, weak_habits=weak, source=source or {}))

def consensus(profiles):
    """A reference from several measured profiles: the pointwise median of their raw
    curves, made monotone. It cancels what the judge and all models have in common, so
    compensation targets cross-model sameness rather than the judge's absolute scale."""
    out = {}
    for t in TRAITS:
        points = []
        for level in range(LEVELS):
            vals = sorted(float(p['traits'][t]['measured'][level]) for p in profiles if p['traits'][t]['measured'][level] is not None)
            if not vals: points.append(ANCHORS[level]); continue
            mid = len(vals) // 2; points.append(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2)
        out[t] = [round(v, 4) for v in isotonic(points)]
    return out

def rebase(profile, reference, reference_kind='consensus'):
    """The same measurement against another reference (a new artifact with a new hash)."""
    traits = {t: dict(means=profile['traits'][t]['measured'], counts=profile['traits'][t]['counts'], spearman=profile['traits'][t].get('spearman')) for t in TRAITS}
    return build(profile['model_id'], traits, profile.get('habits'), profile.get('placement', 'turn'), profile.get('judge'), profile.get('source'), reference, reference_kind)
