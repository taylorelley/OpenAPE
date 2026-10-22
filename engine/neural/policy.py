"""Host-independent CPU policy (decoder-v3). Latent coordinates carry no assigned meanings.

The decoder predicts each style trait's level (0-4) and each habit's probability.
A choice is one approved trait configuration (protocol.catalogue.APPROVED, indexed as
an action) plus a habit set. Its score is the sum of the per-trait log-probabilities
of its levels plus the log-probability of the habit set; selection is the best
approved, context-allowed configuration, then the eligible habits above one half.
"""
import hashlib
import json
from pathlib import Path
import torch
from torch import nn
import torch.nn.functional as F
from safetensors.torch import load_file

torch.set_num_threads(1)
from protocol.catalogue import APPROVED, TRAITS, LEVELS, NEUTRAL, HABITS, HABIT_IDS, MAX_HABITS, CATALOGUE_HASH, SCHEMA

CORE_DIM, REL_DIM, SESSION_DIM, CONTEXT_DIM, PROVIDER_DIM = 64, 32, 16, 64, 16
INPUT_DIM = CORE_DIM + REL_DIM + SESSION_DIM + CONTEXT_DIM + PROVIDER_DIM
N_TRAITS, N_HABITS = len(TRAITS), len(HABITS)
ACTIONS = len(APPROVED)
APPROVED_LEVELS = torch.tensor([[c[t] for t in TRAITS] for c in APPROVED])  # (ACTIONS, 7)
INDEX = {tuple(c[t] for t in TRAITS): i for i, c in enumerate(APPROVED)}
NEUTRAL_ACTION = INDEX[tuple(NEUTRAL[t] for t in TRAITS)]
ENCODER = 'encoder/3'
# encoder/3: explicit one-hot slots (no hash collisions). Unused slots are reserved
# zeros so later encoder versions can add features without reshaping the decoder.
VOCAB = {
    'task_type': ('general', 'code_review', 'coding', 'support', 'creative', 'research', 'debugging', 'planning', 'writing'),
    'channel': ('terminal', 'chat', 'voice', 'background'),
    'stakes': ('low', 'medium', 'high'),
    'turn_origin': ('user', 'system', 'tool', 'subagent'),
    'tags': ('technical', 'review', 'sensitive', 'urgent', 'beginner', 'expert', 'error_present', 'first_turn', 'long_session'),
}
ENGINE_TAGS = ('first_turn', 'long_session')  # set by the engine from the session, never by hosts
PROVIDERS = ('openai', 'anthropic', 'google', 'qwen', 'other')
ADAPTER_BUCKETS = 8
_ROWS = torch.arange(N_TRAITS)
_HABIT = {h['id']: h for h in HABITS}

class Policy(nn.Module):
    def __init__(self):
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(INPUT_DIM, 128), nn.GELU(), nn.Linear(128, 64), nn.GELU())
        self.traits = nn.Linear(64, N_TRAITS * LEVELS)
        self.habits = nn.Linear(64, N_HABITS)
    def forward(self, x):
        h = self.trunk(x)
        return self.traits(h).view(*x.shape[:-1], N_TRAITS, LEVELS), self.habits(h)

def context_features(context):
    x = torch.zeros(CONTEXT_DIM); offset = 0
    for key, values in VOCAB.items():
        val = context.get(key)
        for v in val if isinstance(val, list) else [val]:
            if v in values: x[offset + values.index(v)] = 1
        offset += len(values)
    return x

def adapter_bucket(adapter_id):
    return int.from_bytes(hashlib.sha256(f'adapter:{adapter_id}'.encode()).digest()[:4], 'big') % ADAPTER_BUCKETS

def provider_features(host):
    """Provider family and adapter are data features only; no host special cases."""
    x = torch.zeros(PROVIDER_DIM)
    family = host.get('provider_family', 'other')
    x[PROVIDERS.index(family if family in PROVIDERS else 'other')] = 1
    x[len(PROVIDERS) + adapter_bucket(host.get('adapter_id', 'other'))] = 1
    return x

def features(context, host):
    return torch.cat((context_features(context), provider_features(host)))

def inputs(core, rel, context, host, session=None):
    return torch.cat((core, rel, session if session is not None else torch.zeros(SESSION_DIM), features(context, host)))

def _constraints(context):
    tags = context.get('tags', [])
    return (context.get('stakes') == 'high' or 'sensitive' in tags, 'urgent' in tags)

def _level_mask(serious, urgent):
    m = torch.ones(N_TRAITS, LEVELS, dtype=torch.bool)
    if serious: m[TRAITS.index('humour'), 2:] = False
    if urgent: m[TRAITS.index('verbosity'), 3:] = False
    return m

# The constraint layer depends only on two context flags, so all four masks are fixed.
_LEVEL_MASKS = {k: _level_mask(*k) for k in ((a, b) for a in (False, True) for b in (False, True))}
_MASKS = {k: m[_ROWS, APPROVED_LEVELS].all(1) for k, m in _LEVEL_MASKS.items()}

def level_mask(context):
    """Fixed per-level constraint layer: (7, 5) allowed levels. The neutral fallback is never masked."""
    return _LEVEL_MASKS[_constraints(context)].clone()

def mask(context):
    """Allowed approved configurations (ACTIONS,) in this context."""
    return _MASKS[_constraints(context)]

def habit_mask(context):
    m = torch.ones(N_HABITS, dtype=torch.bool); tags = context.get('tags', [])
    off = set()
    if context.get('stakes') == 'high' or 'sensitive' in tags: off.add('light_aside')
    if 'urgent' in tags: off.update(('confirm_goal', 'clarify_once', 'recap_end'))
    if context.get('turn_origin', 'user') != 'user': off.update(('confirm_goal', 'clarify_once'))
    if context.get('channel') == 'voice': off.add('structured')
    for h in off: m[HABIT_IDS.index(h)] = False
    return m

def mask_reason(context):
    tags = context.get('tags', []); reasons = []
    if context.get('stakes') == 'high' or 'sensitive' in tags: reasons.append('high_stakes_or_sensitive')
    if 'urgent' in tags: reasons.append('urgent')
    return ','.join(reasons) or None

def levels_of(action):
    return dict(zip(TRAITS, APPROVED_LEVELS[action].tolist()))

def habit_vector(ids):
    v = torch.zeros(N_HABITS, dtype=torch.bool)
    for i in ids: v[HABIT_IDS.index(i)] = True
    return v

def habits_allowed(ids, action, context):
    """Eligible for these trait levels, allowed in this context, not exclusive, at most MAX_HABITS."""
    if len(ids) > MAX_HABITS or len(set(ids)) != len(ids) or any(i not in _HABIT for i in ids): return False
    levels = levels_of(action); hm = habit_mask(context)
    return all(hm[HABIT_IDS.index(i)] and all(lo <= levels[t] <= hi for t, (lo, hi) in _HABIT[i]['requires'].items())
        and not set(_HABIT[i]['excludes']) & set(ids) for i in ids)

def select_habits(habit_logits, action, context):
    """Eligible habits with probability above one half, most likely first, at most
    MAX_HABITS, returned in catalogue order."""
    chosen = []
    for k in torch.argsort(habit_logits, descending=True).tolist():
        if len(chosen) == MAX_HABITS or float(habit_logits[k]) <= 0: break
        if habits_allowed(chosen + [HABIT_IDS[k]], action, context): chosen.append(HABIT_IDS[k])
    return sorted(chosen, key=HABIT_IDS.index)

def choice(controls, habits=()):
    """(action, habit tuple) for a {trait: level} mapping, or None if not approved."""
    action = INDEX.get(tuple(controls.get(t) for t in TRAITS)) if isinstance(controls, dict) else None
    return None if action is None else (action, tuple(sorted(habits, key=lambda h: HABIT_IDS.index(h) if h in HABIT_IDS else -1)))

def choice_allowed(c, context):
    return c is not None and bool(_LEVEL_MASKS[_constraints(context)][_ROWS, APPROVED_LEVELS[c[0]]].all()) and habits_allowed(list(c[1]), c[0], context)

def masked_logp(trait_logits, lmask):
    return torch.log_softmax(trait_logits.masked_fill(~lmask, float('-inf')), -1)

def joint(trait_logp):
    """Unnormalised log-score of every approved configuration (ACTIONS,); masked levels are -inf."""
    return trait_logp[_ROWS, APPROVED_LEVELS].sum(1)

def habit_logp(habit_logits, chosen):
    return torch.where(chosen, F.logsigmoid(habit_logits), F.logsigmoid(-habit_logits)).sum(-1)

def choice_score(trait_logp, habit_logits, levels, habits):
    """Log-score of choices; batched over leading dims. levels (...,7) long, habits (...,H) bool."""
    return trait_logp.gather(-1, levels.unsqueeze(-1)).squeeze(-1).sum(-1) + habit_logp(habit_logits, habits)

def digest(path):
    return 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Decoder:
    def __init__(self, path):
        self.path = Path(path); self.model = None; self.hash = 'untrained'; self.meta = {}
        manifest = self.path.with_suffix('.json')
        if self.path.exists() and manifest.exists():
            meta = json.loads(manifest.read_text())
            if meta['hash'] != digest(self.path): raise ValueError('decoder checksum mismatch')
            if meta.get('encoder') != ENCODER or meta.get('catalogue') != SCHEMA or meta.get('catalogue_hash') != CATALOGUE_HASH: raise ValueError('decoder incompatible with encoder/catalogue')
            self.model = Policy(); self.model.load_state_dict(load_file(str(self.path))); self.model.eval()
            for p in self.model.parameters(): p.requires_grad_(False)
            self.hash = meta['hash']; self.meta = meta
    def heads(self, core, rel, context, host):
        """(trait log-probabilities (7, 5) with context masks, habit logits (H,))."""
        lm = level_mask(context)
        if self.model is None:
            neutral = torch.full((N_TRAITS, LEVELS), -1.0); neutral[_ROWS, APPROVED_LEVELS[NEUTRAL_ACTION]] = 0.0
            return masked_logp(neutral, lm), torch.full((N_HABITS,), -4.0)
        t, h = self.model(inputs(core, rel, context, host))
        return masked_logp(t, lm), h
    def batch(self, core, rel, feats, lmasks, session=None):
        """Batched heads for (B, ...) latents, features and level masks."""
        n = feats.shape[0]
        x = torch.cat((core.expand(n, -1), rel.expand(n, -1), session if session is not None else torch.zeros(n, SESSION_DIM), feats), 1)
        t, h = self.model(x)
        return masked_logp(t, lmasks), h
    def logits(self, core, rel, context, host):
        """Joint log-score over approved configurations; context-masked ones are -inf."""
        t, _ = self.heads(core, rel, context, host)
        return joint(t)
    def score(self, core, rel, context, host, c):
        t, h = self.heads(core, rel, context, host)
        return choice_score(t, h, APPROVED_LEVELS[c[0]], habit_vector(c[1]))
    def diagnostics(self, core, rel, context, host):
        """Expected trait levels (0-4) and habit probabilities. Decoder outputs, not latent axes."""
        t, h = self.heads(core, rel, context, host); level = torch.arange(LEVELS, dtype=torch.float)
        out = {tr: round(float((t[i].exp() * level).sum()), 3) for i, tr in enumerate(TRAITS)}
        out.update({f'habit:{k}': round(float(torch.sigmoid(h[i])), 3) for i, k in enumerate(HABIT_IDS)})
        return out
