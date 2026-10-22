"""Human-like development around the maturation curve (ADR 0004).

Findings from personality psychology, mapped onto bounded, audited engine processes.
None of this is reward: it never reads task outcomes, engagement, inferred
satisfaction or text, only structured context, host identity, consented feedback
and server time. Every durable change is still an evaluated, revocable version.

* Temperament and individuality. The creation latent is a fixed temperament anchor;
  automatic change (character) stays within CHARACTER_RADIUS of it. A recorded
  individuality seed varies the archetype profile, so two mentors are alike but not
  identical.
* State to trait (TESSERA, Whole Trait Theory). Consented in-session preferences
  move a short-lived session state, a bounded latent offset. Each ended session
  leaves a state sample; only states that recur consistently become a habit step.
* Plasticity never reaches zero, and surface style settles before interpersonal
  traits (sensitive periods).
* Life events. A shift in the work served, a new host or a burst of corrections
  temporarily raises plasticity. Novel sessions count as more experience than the
  hundredth identical one.
* Relationships accommodate to the user's own pattern of work, cool after long
  gaps, and change most around ruptures (corrections).
* Fade unless reinforced. A slow self anchor follows the persona's deliberate
  changes; learned change it has not absorbed is pulled back a little at each
  consolidation, unless that would undo valid feedback.
* Influence. Owner feedback weighs more early and users' later; agent reflections
  gain weight with maturity; older feedback weighs less.
"""
import hashlib
import math
import random
from datetime import datetime
import torch
import torch.nn.functional as F
from protocol.catalogue import TRAITS
from engine.neural.policy import features, level_mask, habit_vector, choice_score, APPROVED_LEVELS
from engine.learning.trainer import pair

SURFACE = ('verbosity', 'formality', 'explanation_depth')
INTERPERSONAL = ('warmth', 'directness', 'assertiveness', 'humour')
PLASTICITY_FLOOR = 0.2
INDIVIDUALITY = 0.3
CHARACTER_RADIUS = 1.6  # core latent units from temperament (median persona norm ~1.4)
# Within-person state variation is about as large as between-person differences
# (Fleeson 2001), so a session state may move about one median persona norm.
STATE_BUDGET = 1.4
STATE_WINDOW = 12  # a state reflects the session's recent preferences
HABIT_WINDOW, HABIT_MIN, HABIT_CONSISTENCY, HABIT_GAIN = 6, 3, 0.6, 0.5
NOVELTY_FLOOR = 0.5
SHORT_RATE, LONG_RATE, TAG_RATE = 0.3, 0.05, 0.15
SHIFT, SETTLED_SESSIONS = 0.5, 12  # a role change needs an established role first
EVENT_BOOST, BOOST_DECAY = 3.0, 0.6
COOL_AFTER_DAYS, COOL_PER_30_DAYS, MAX_COOL = 14, 0.1, 0.3
ELASTIC, ANCHOR_RATE, ELASTIC_MIN, SLEEP_EVERY = 0.25, 0.15, 0.1, 3
RECENCY_HALF_LIFE = 300  # examples

def trait_plasticity(m):
    """Sensitive periods: surface style settles early, interpersonal traits stay open
    longer, and neither reaches zero."""
    w = {t: max(PLASTICITY_FLOOR, 1 - 0.8 * m) for t in SURFACE}
    w.update({t: max(PLASTICITY_FLOOR, 1 - 0.4 * m) for t in INTERPERSONAL})
    return w

def plasticity(m, boost=1.0):
    return min(1.5, (PLASTICITY_FLOOR + (1 - PLASTICITY_FLOOR) * (1 - m)) * boost)

def scaled(profile, weights):
    return {t: (target, w * weights.get(t, 1.0)) for t, (target, w) in profile.items()}

def default_seed(tenant, persona_id):
    return int.from_bytes(hashlib.sha256(f'individuality:{tenant}:{persona_id}'.encode()).digest()[:4], 'big') & 0x7fffffff

def individual_profile(profile, seed, amount):
    """Seeded, recorded variation of a declared profile: each declared preference is a
    little stronger or weaker and one or two mild leanings are added."""
    if amount <= 0: return dict(profile)
    rng = random.Random(seed)
    out = {t: (target, round(w * rng.uniform(1 - 0.4 * amount, 1 + 0.4 * amount), 3)) for t, (target, w) in sorted(profile.items())}
    free = [t for t in TRAITS if t not in out]
    for t in rng.sample(free, min(len(free), rng.randint(1, 2))):
        out[t] = (rng.choice([0, 0, 1]) if t == 'humour' else rng.choice([1, 2, 3]), round(rng.uniform(0.3, 0.9) * amount, 3))
    return out

def within(x, centre, radius):
    d = x - centre; n = float(d.norm())
    return x if n <= radius else centre + d * (radius / n)

def influence(source, m):
    """Caregivers first: owner feedback weighs double at birth and users' half; both
    reach 1 at maturity. Agent reflections grow with self-insight."""
    if source == 'owner': return 2.0 - m
    if source == 'explicit_user': return 0.5 + 0.5 * m
    if source == 'agent_reflection': return 0.3 + 0.7 * m
    return 1.0

def reflection_share(m):
    """Reflections allowed per example of people's feedback in an automatic candidate."""
    return 0.2 + 0.8 * m

def recency(rank):
    return 0.5 ** (rank / RECENCY_HALF_LIFE)

def fit_state(decoder, core, rel, scope, examples, steps=20):
    """Session state: a bounded latent offset fitted to one session's consented
    pairwise preferences (one batched decoder pass per step). Never stored as a
    version; discarded when the session ends."""
    base = core if scope == 'core' else rel
    usable = [(e, p) for e in examples if (p := pair(e)) is not None]
    if not usable or decoder.model is None: return torch.zeros_like(base)
    weights = torch.tensor([e.get('weight', 1.0) for e, _ in usable]); weights = weights / weights.sum()
    feats = torch.stack([features(e['context'], e['host']) for e, _ in usable]); lm = torch.stack([level_mask(e['context']) for e, _ in usable])
    la, lb = (torch.stack([APPROVED_LEVELS[p[k][0]] for _, p in usable]) for k in (0, 1))
    ha, hb = (torch.stack([habit_vector(p[k][1]) for _, p in usable]) for k in (0, 1))
    x = torch.zeros_like(base).requires_grad_(True)
    optimizer = torch.optim.Adam([x], lr=0.15)
    for _ in range(steps):
        optimizer.zero_grad()
        c, r = (core + x, rel) if scope == 'core' else (core, rel + x)
        t, h = decoder.batch(c, r, feats, lm)
        loss = -(weights * F.logsigmoid(choice_score(t, h, la, ha) - choice_score(t, h, lb, hb))).sum() + 0.01 * x.square().sum()
        loss.backward(); optimizer.step()
        with torch.no_grad(): x.mul_(min(1.0, STATE_BUDGET / (float(x.norm()) + 1e-8)))
    return x.detach()

def habit(deltas):
    """Mean of recent session states and their consistency: the length of the mean over
    the mean length, 1 when every session leaned the same way, near 0 when they cancel."""
    x = torch.stack(deltas); mean = x.mean(0); spread = float(x.norm(dim=1).mean())
    return mean, (float(mean.norm()) / spread if spread > 1e-8 else 0.0)

def habit_step(deltas, m, boost):
    """A trait step from consistent states, or None."""
    if len(deltas) < HABIT_MIN: return None
    mean, consistency = habit(deltas)
    if consistency < HABIT_CONSISTENCY: return None
    step = mean * HABIT_GAIN * plasticity(m, boost)
    return within(step, torch.zeros_like(step), STATE_BUDGET * HABIT_GAIN)

def signature(context):
    return context['task_type'] + '|' + ','.join(sorted(context.get('tags', [])))

def _ema(old, new, rate):
    keys = set(old) | set(new)
    out = {k: (1 - rate) * old.get(k, 0.0) + rate * new.get(k, 0.0) for k in keys}
    return {k: round(v, 5) for k, v in out.items() if v >= 1e-3}

def _normalized(d):
    total = sum(d.values()) or 1.0
    return {k: v / total for k, v in d.items()}

def observe(life, signatures, hosts, tags, corrections, now, relationship):
    """Update one scope's life record for an ended session; returns (experience weight,
    events). `signatures` counts the session's context signatures, `tags` is the share
    of its decisions carrying each tag, `corrections` counts its consented preferences
    from people, and `now` is server time."""
    events = []
    total = sum(signatures.values()) or 1; share = {k: v / total for k, v in signatures.items()}
    seen = life.setdefault('seen', {})
    novelty = sum(p / math.sqrt(1 + seen.get(k, 0)) for k, p in share.items()) if share else 1.0
    for k in share: seen[k] = seen.get(k, 0) + 1
    # A role is the kind of work (task type); tags vary within a role and only add novelty.
    roles = {}
    for k, p in share.items(): roles[k.split('|')[0]] = roles.get(k.split('|')[0], 0) + p
    # Bias-corrected: a running mean until each average has enough history.
    n = life.get('sessions', 0) + 1
    life['short'] = _ema(life.get('short', {}), roles, max(SHORT_RATE, 1 / n)); life['long'] = _ema(life.get('long', {}), roles, max(LONG_RATE, 1 / n))
    short, long = _normalized(life['short']), _normalized(life['long'])
    shift = 0.5 * sum(abs(short.get(k, 0) - long.get(k, 0)) for k in set(short) | set(long))
    # Hysteresis: one event per transition, re-armed once the mix has settled again.
    if life.get('sessions', 0) >= SETTLED_SESSIONS and shift >= SHIFT and not life.get('shifted'): events.append('role_change'); life['shifted'] = True
    elif shift < SHIFT * 0.6: life['shifted'] = False
    known = life.setdefault('hosts', [])
    if not relationship and known and set(hosts) - set(known): events.append('new_host')
    life['hosts'] = sorted(set(known) | set(hosts))[-32:]
    if corrections >= 2: events.append('rupture' if relationship else 'correction_burst')
    if relationship:
        life['tags'] = _ema(life.get('tags', {}), tags, TAG_RATE)
        last = life.get('last_seen')
        days = (now - datetime.fromisoformat(last)).total_seconds() / 86400 if last else 0
        if days >= COOL_AFTER_DAYS:
            life['cooling'] = round(min(MAX_COOL, life.get('cooling', 0) + COOL_PER_30_DAYS * days / 30), 4); events.append('long_absence')
    life['boost'] = round(1 + (life.get('boost', 1.0) - 1) * BOOST_DECAY, 4)
    if set(events) - {'long_absence'}: life['boost'] = EVENT_BOOST
    life['sessions'] = life.get('sessions', 0) + 1; life['last_seen'] = now.isoformat()
    return (NOVELTY_FLOOR + (1 - NOVELTY_FLOOR) * novelty) * life['boost'], events

def accommodation_profile(tags, m):
    """Relationship drift toward the user's own pattern of work, from structured tags
    only: expert or urgent work leans brief, beginner work leans patient and deep,
    sensitive or beginner work leans warm. Grows with the relationship's maturity."""
    brief = tags.get('expert', 0) + tags.get('urgent', 0); teach = tags.get('beginner', 0)
    care = tags.get('sensitive', 0) + 0.5 * teach; net = teach - brief; out = {}
    if net > 0.05: out.update({'explanation_depth': (3, 1.2 * min(1, net) * m), 'verbosity': (2, 0.4 * min(1, net) * m), 'habit:concrete_examples': (1, 0.6 * min(1, net) * m)})
    if net < -0.05: out.update({'verbosity': (1, 1.2 * min(1, -net) * m), 'explanation_depth': (1, 0.6 * min(1, -net) * m), 'habit:summary_first': (1, 0.4 * min(1, -net) * m)})
    if care > 0.05: out['warmth'] = (3, 0.8 * min(1, care) * m)
    return out
