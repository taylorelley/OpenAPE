"""Isolated latent candidate fitting. Decoder stays frozen; active state is untouched."""
import torch
import torch.nn.functional as F
from engine.neural.policy import choice, choice_allowed, choice_score, habit_vector, APPROVED_LEVELS

def pair(e):
    """(preferred, rejected) choices of a pairwise preference/correction that are both
    approved, allowed in its context and different; otherwise None."""
    if e['kind'] not in ('pairwise_preference','correction') or not e.get('preferred') or not e.get('rejected'): return None
    a=choice(e['preferred']['controls'],e['preferred'].get('habits',[]));b=choice(e['rejected']['controls'],e['rejected'].get('habits',[]))
    if a is None or b is None or a==b or not choice_allowed(a,e['context']) or not choice_allowed(b,e['context']): return None
    return a,b

def trait_pair(e):
    """A pair whose trait configurations differ; habit-only pairs belong to the habit
    bias (engine.learning.habits), so they never drag the latent."""
    p=pair(e)
    return p if p is not None and p[0][0]!=p[1][0] else None

def margin(t,h,a,b):
    return choice_score(t,h,APPROVED_LEVELS[a[0]],habit_vector(a[1]))-choice_score(t,h,APPROVED_LEVELS[b[0]],habit_vector(b[1]))

def trait_margin(t,a,b):
    """Score difference of the trait configurations alone (habits excluded)."""
    return (t.gather(-1,APPROVED_LEVELS[a[0]].unsqueeze(-1)).sum()-t.gather(-1,APPROVED_LEVELS[b[0]].unsqueeze(-1)).sum())

def loss_for(decoder,core,rel,e,baseline=0.0):
    if e['kind'] in ('pairwise_preference','correction'):
        p=trait_pair(e)
        if p is None: return None
        t,_=decoder.heads(core,rel,e['context'],e['host'])
        return -F.logsigmoid(trait_margin(t,*p))
    # Only seeded sampled actions carry a meaningful logging propensity. Habits are
    # selected deterministically, so the logged-bandit term trains the configuration only.
    if e.get('selection')!='sample' or (e.get('propensity') or 0)<=0 or e.get('value') is None: return None
    action=e['action']
    logits=decoder.logits(core,rel,e['context'],e['host'])
    if not torch.isfinite(logits[action]): return None
    logp=logits[action]-torch.logsumexp(logits,0)
    ratio=(logp.detach().exp()/e['propensity']).clamp(max=5)
    # Clipped importance-weighted REINFORCE with a mean-reward baseline.
    return -ratio*(e['value']-baseline)*logp

def fit_candidate(decoder,core,rel,train,scope,seed,maximum_drift):
    """Fit only on training groups. Held-out scoring and promotion rules live in
    engine.evaluation, which this module cannot configure."""
    if decoder.model is None: raise ValueError('trained decoder required')
    torch.manual_seed(seed)
    original=core.clone() if scope=='core' else rel.clone()
    absolute_limit=state_norm_limit(decoder,scope)
    candidate=original.clone().requires_grad_(True)
    optimizer=torch.optim.Adam([candidate],lr=0.04)
    def states(x): return (x,rel) if scope=='core' else (core,x)
    ratings=[e['value'] for e in train if e['kind']=='rating' and e.get('selection')=='sample' and e.get('value') is not None]
    baseline=sum(ratings)/len(ratings) if ratings else 0.0
    usable=[e for e in train if loss_for(decoder,core,rel,e) is not None]
    if not usable: raise ValueError('need eligible training groups')
    # Optional per-example weights (recency, source influence); all 1 is the plain mean.
    weights=torch.tensor([float(e.get('weight',1.0)) for e in usable]);weights=weights/weights.sum()
    for _ in range(100):
        optimizer.zero_grad()
        loss=(weights*torch.stack([loss_for(decoder,*states(candidate),e,baseline) for e in usable])).sum()+0.01*(candidate-original).square().mean()
        loss.backward(); torch.nn.utils.clip_grad_norm_([candidate],1.0); optimizer.step()
        with torch.no_grad():
            # Trust region: per-candidate drift budget, then absolute state-norm bound.
            delta=candidate-original
            candidate.copy_(original+delta*min(1.0,maximum_drift*0.98/(float(delta.norm())+1e-8)))
            candidate.mul_(min(1.0,absolute_limit/(float(candidate.norm())+1e-8)))
    return candidate.detach(),dict(train_examples=len(usable),reward_baseline=baseline,optimizer='adam',steps=100,seed=seed)

def state_norm_limit(decoder,scope):
    return decoder.meta.get('latent_norm_limit',2.4)*(1.0 if scope=='core' else 0.85)
