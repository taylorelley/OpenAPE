"""Independent candidate evaluator with fixed promotion rules.

The evaluator owns the grouped split and re-scores every candidate on held-out
groups itself; the trainer only fits on the training split it is handed and can
neither see validation labels nor supply thresholds or metrics that are trusted.

Drift is measured in latent units calibrated against the decoder's training persona
distribution (median core norm ~1.4). KL is reported for audit only: the decoder is
deliberately sharp, so KL between distinct personas is large and is not a useful
safety bound; the latent trust region is the enforced drift budget.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
import torch
from engine.learning.trainer import loss_for, state_norm_limit
from engine.neural.policy import mask

def group_split(examples):
    # Stable grouping by consenting actor + declared session/scenario family.
    train=[]; valid=[]
    for e in examples:
        key=e['actor_id']+':'+e['evidence_group']
        (valid if int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%3==0 else train).append(e)
    return train,valid

@dataclass(frozen=True)
class EvaluationPolicy:
    minimum_train_groups: int = 4
    minimum_validation_groups: int = 2
    maximum_drift: float = 1.5
    minimum_gain: float = 0.001
    def evaluate(self,metrics):
        checks={
            'train_groups':metrics['train_groups']>=self.minimum_train_groups,
            'validation_groups':metrics['validation_groups']>=self.minimum_validation_groups,
            'drift':metrics['drift']<=self.maximum_drift+1e-6,
            'heldout_gain':metrics['heldout_gain']>=self.minimum_gain,
            'constraints':metrics['constraints_ok'],
        }
        return {'eligible':all(checks.values()),'checks':checks,'metrics':metrics,'policy':asdict(self),'policy_hash':hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest(), 'evidence':'synthetic_or_explicit_feedback; not a live-model behavioral evaluation'}

# Slow core consolidation needs more independent evidence and a tighter trust region.
CORE=EvaluationPolicy(minimum_train_groups=8,minimum_validation_groups=4,maximum_drift=1.0)
RELATIONSHIP=EvaluationPolicy()
def policy_for(scope): return CORE if scope=='core' else RELATIONSHIP

def _mean(decoder,states,rows):
    losses=[loss_for(decoder,*states,e) for e in rows]
    losses=[float(l) for l in losses if l is not None]
    return sum(losses)/len(losses)

def evaluate_candidate(decoder,core,rel,candidate,scope,train,valid):
    policy=policy_for(scope)
    with torch.no_grad():
        base=(core,rel); new=(candidate,rel) if scope=='core' else (core,candidate)
        usable_train=[e for e in train if loss_for(decoder,core,rel,e) is not None]
        usable_valid=[e for e in valid if loss_for(decoder,core,rel,e) is not None]
        if not usable_valid: raise ValueError('need eligible disjoint training and held-out groups')
        before=_mean(decoder,base,usable_valid); after=_mean(decoder,new,usable_valid)
        kls=[]
        for e in usable_valid:
            m=mask(e['context']); old=decoder.logits(*base,e['context'],e['host'])[m]; nw=decoder.logits(*new,e['context'],e['host'])[m]
            p=torch.softmax(old,0); kls.append(float((p*(torch.log_softmax(old,0)-torch.log_softmax(nw,0))).sum()))
        original=core if scope=='core' else rel; limit=state_norm_limit(decoder,scope)
        metrics=dict(train_groups=len({(e['actor_id'],e['evidence_group']) for e in usable_train}),validation_groups=len({(e['actor_id'],e['evidence_group']) for e in usable_valid}),
            train_examples=len(usable_train),validation_examples=len(usable_valid),heldout_loss_before=before,heldout_loss_after=after,heldout_gain=before-after,
            drift=float((candidate-original).norm()),state_norm=float(candidate.norm()),state_norm_limit=limit,mean_kl_validation_contexts=sum(kls)/len(kls),
            constraints_ok=bool(torch.isfinite(candidate).all()) and candidate.shape==original.shape and float(candidate.norm())<=limit+1e-4)
    return policy.evaluate(metrics)
