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
from engine.learning.trainer import loss_for, state_norm_limit, pair, margin
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
# Autonomous promotion (persona evolution policy 'automatic') needs more independent
# evidence, a larger held-out gain and, for the core, a tighter trust region.
AUTO_CORE=EvaluationPolicy(minimum_train_groups=12,minimum_validation_groups=6,maximum_drift=0.6,minimum_gain=0.005)
AUTO_RELATIONSHIP=EvaluationPolicy(minimum_train_groups=6,minimum_validation_groups=3,minimum_gain=0.005)
def policy_for(scope,auto=False):
    if auto: return AUTO_CORE if scope=='core' else AUTO_RELATIONSHIP
    return CORE if scope=='core' else RELATIONSHIP

def _mean(decoder,states,rows):
    losses=[loss_for(decoder,*states,e) for e in rows]
    losses=[float(l) for l in losses if l is not None]
    return sum(losses)/len(losses)

def evaluate_candidate(decoder,core,rel,candidate,scope,train,valid,auto=False):
    policy=policy_for(scope,auto)
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

def preference_agreement(decoder,states,rows):
    """Fraction of explicit pairwise preferences/corrections the policy satisfies."""
    pairs=[(e,p) for e in rows if (p:=pair(e)) is not None]
    if not pairs:return None,0
    hits=0
    for e,p in pairs:
        t,h=decoder.heads(*states,e['context'],e['host']);hits+=int(margin(t,h,*p)>0)
    return hits/len(pairs),len(pairs)

def evaluate_maturation(decoder,core,rel,candidate,scope,step_budget,feedback):
    """Gate for a maturation step: bounded, finite, and feedback wins. Maturation is a
    fixed prior, not learning, so it may never reduce how many of the persona's valid
    consented preferences the policy satisfies."""
    with torch.no_grad():
        original=core if scope=='core' else rel; limit=state_norm_limit(decoder,scope)
        new=(candidate,rel) if scope=='core' else (core,candidate)
        before,count=preference_agreement(decoder,(core,rel),feedback);after,_=preference_agreement(decoder,new,feedback)
        drift=float((candidate-original).norm())
        checks={'finite':bool(torch.isfinite(candidate).all()) and candidate.shape==original.shape,
            'step_budget':drift<=step_budget+1e-4,'state_norm':float(candidate.norm())<=limit+1e-4,
            'feedback_preserved':before is None or after>=before}
    return {'eligible':all(checks.values()),'checks':checks,'metrics':dict(drift=drift,step_budget=step_budget,state_norm=float(candidate.norm()),state_norm_limit=limit,
        feedback_examples=count,feedback_agreement_before=before,feedback_agreement_after=after),'evidence':'fixed maturation prior; not learned from or validated against people'}
