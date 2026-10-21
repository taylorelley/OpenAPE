"""Isolated latent candidate fitting. Decoder stays frozen; active state is untouched."""
import hashlib
import torch
from engine.neural.policy import mask
from engine.evaluation.policy import EvaluationPolicy

def group_split(examples):
    # Stable grouping by consenting actor + declared session/scenario family.
    train=[]; valid=[]
    for e in examples:
        key=e['actor_id']+':'+e['evidence_group']
        (valid if int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%3==0 else train).append(e)
    return train,valid

def loss_for(decoder,core,rel,e):
    logits=decoder.logits(core,rel,e['context'],e['host'])
    if e['kind'] in ('pairwise_preference','correction'):
        a,b=e['preferred_control'],e['rejected_control']
        if a is None or b is None or a==b or not mask(e['context'])[a] or not mask(e['context'])[b]: return None
        return -torch.log_softmax(logits[[a,b]],0)[0]
    # Only seeded sampled actions carry a meaningful propensity. Baseline is fixed zero.
    if e.get('selection')!='sample' or (e.get('propensity') or 0)<=0 or e.get('value') is None: return None
    action=e['action']
    current=torch.softmax(logits,0)[action]
    ratio=(current.detach()/e['propensity']).clamp(max=5)
    return -ratio*e['value']*torch.log_softmax(logits,0)[action]

def train_candidate(decoder,core,rel,examples,scope,seed):
    if decoder.model is None: raise ValueError('trained decoder required')
    torch.manual_seed(seed)
    train,valid=group_split(examples)
    original=core.clone() if scope=='core' else rel.clone()
    candidate=original.clone().requires_grad_(True)
    optimizer=torch.optim.Adam([candidate],lr=0.04)
    def states(x): return (x,rel) if scope=='core' else (core,x)
    def avg(rows,x):
        losses=[loss_for(decoder,*states(x),e) for e in rows]
        losses=[l for l in losses if l is not None]
        return torch.stack(losses).mean() if losses else None
    usable_train=[e for e in train if loss_for(decoder,core,rel,e) is not None]
    usable_valid=[e for e in valid if loss_for(decoder,core,rel,e) is not None]
    if not usable_train or not usable_valid: raise ValueError('need eligible disjoint training and held-out groups')
    before=float(avg(usable_valid,original).detach())
    for _ in range(100):
        optimizer.zero_grad()
        loss=avg(usable_train,candidate)+0.01*(candidate-original).square().mean()
        loss.backward(); torch.nn.utils.clip_grad_norm_([candidate],1.0); optimizer.step()
        with torch.no_grad():
            delta=candidate-original
            candidate.copy_(original+delta*min(1.0,1.95/(float(delta.norm())+1e-8)))
    # Project drift using training contexts only. Held-out labels never guide fitting.
    with torch.no_grad():
        for _ in range(24):
            worst=0.0
            for e in usable_train:
                m=mask(e['context'])
                old=decoder.logits(core,rel,e['context'],e['host'])[m]
                new=decoder.logits(*states(candidate),e['context'],e['host'])[m]
                prob=torch.softmax(old,0)
                worst=max(worst,float((prob*(torch.log_softmax(old,0)-torch.log_softmax(new,0))).sum()))
            if worst<=0.12: break
            candidate.copy_(original+(candidate-original)*0.7)
    with torch.no_grad():
        after=float(avg(usable_valid,candidate)); kls=[]
        for e in usable_valid:
            old=decoder.logits(core,rel,e['context'],e['host']); new=decoder.logits(*states(candidate),e['context'],e['host'])
            m=mask(e['context']); p=torch.softmax(old[m],0)
            kls.append(float((p*(torch.log_softmax(old[m],0)-torch.log_softmax(new[m],0))).sum()))
        metrics=dict(train_groups=len({(e['actor_id'],e['evidence_group']) for e in usable_train}), validation_groups=len({(e['actor_id'],e['evidence_group']) for e in usable_valid}), train_examples=len(usable_train),validation_examples=len(usable_valid), heldout_loss_before=before,heldout_loss_after=after,heldout_gain=before-after,drift=float((candidate-original).norm()),kl=max(kls),constraints_ok=bool(torch.isfinite(candidate).all()))
    return candidate.detach(),(EvaluationPolicy(minimum_train_groups=8,minimum_validation_groups=4) if scope=='core' else EvaluationPolicy()).evaluate(metrics),[e['feedback_id'] for e in usable_train+usable_valid]
