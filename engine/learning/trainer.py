"""Isolated latent candidate fitting. Decoder stays frozen; active state is untouched."""
import torch
from engine.neural.policy import mask

def loss_for(decoder,core,rel,e,baseline=0.0):
    logits=decoder.logits(core,rel,e['context'],e['host'])
    if e['kind'] in ('pairwise_preference','correction'):
        a,b=e['preferred_control'],e['rejected_control']
        if a is None or b is None or a==b or not mask(e['context'])[a] or not mask(e['context'])[b]: return None
        return -torch.log_softmax(logits[[a,b]],0)[0]
    # Only seeded sampled actions carry a meaningful logging propensity.
    if e.get('selection')!='sample' or (e.get('propensity') or 0)<=0 or e.get('value') is None: return None
    action=e['action']
    current=torch.softmax(logits,0)[action]
    ratio=(current.detach()/e['propensity']).clamp(max=5)
    # Clipped importance-weighted REINFORCE with a mean-reward baseline.
    return -ratio*(e['value']-baseline)*torch.log_softmax(logits,0)[action]

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
