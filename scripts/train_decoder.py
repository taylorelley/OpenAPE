"""Reproduce decoder-v3 from original CC0 synthetic persona profiles (auto-decoder).

The shared decoder and a table of per-persona/per-relationship latents are fitted
jointly, so latent state genuinely conditions behaviour. The decoder predicts each
trait's level (0-4) and each habit's probability (behaviour-controls/2). Held-out
personas are then fitted from a few pairwise preferences with the decoder frozen
(exactly the runtime learning path) and evaluated on unseen contexts. All labels are
synthetic rules; no human evidence, provider outputs or behavioural-efficacy claims.
"""
import hashlib
import json
import random
from pathlib import Path
import torch
import torch.nn.functional as F
from safetensors.torch import save_file
from protocol.catalogue import CATALOGUE_HASH, SCHEMA, HABIT_IDS
from engine.neural.policy import (Policy, Decoder, features, level_mask, mask, habits_allowed, habit_vector, choice_score, digest,
    APPROVED_LEVELS, NEUTRAL_ACTION, CORE_DIM, REL_DIM, SESSION_DIM, ENCODER, ACTIONS)
from engine.evaluation.policy import RELATIONSHIP
from engine.neural.profiles import (trait_targets, habit_targets, target_choice, random_context, random_profile, agreement, selected,
    fit_seed_latent, distribution_loss, seed_profile, SEEDS)

ROOT=Path(__file__).resolve().parents[1]
SEED=42
PRIOR=6e-3
PARTITIONS=dict(train=384,calibration=64,validation=96)
HOSTS=[dict(provider_family=p,adapter_id=a) for p in ('openai','anthropic','google','qwen','other') for a in ('upap.pi','upap.hermes','upap.claude-code','upap.openclaw','upap.opencogni','custom')]
OUT=ROOT/'models/decoder-v3'

def corpus():
    rng=random.Random(SEED); personas=[]
    for part,count in PARTITIONS.items():
        for _ in range(count):
            personas.append(dict(group=f'synthetic-persona-{len(personas):04d}',partition=part,profile=random_profile(rng),
                users=[random_profile(rng,(1,2),(0,1)) for _ in range(2)]))
    rows=[]
    for i,p in enumerate(personas):
        if p['partition']!='train':continue
        for _ in range(40):rows.append(dict(persona=i,user=None,context=random_context(rng),host=rng.choice(HOSTS)))
        for u in range(2):
            for _ in range(12):rows.append(dict(persona=i,user=u,context=random_context(rng),host=rng.choice(HOSTS)))
    for _ in range(4000):rows.append(dict(persona=None,user=None,context=random_context(rng),host=rng.choice(HOSTS)))
    return personas,rows

def profiles_of(personas,row):
    profiles=[]
    if row['persona'] is not None:
        p=personas[row['persona']];profiles.append(p['profile'])
        if row['user'] is not None:profiles.append(p['users'][row['user']])
    return profiles

def rival(rng,c,a):
    """A different allowed choice: another configuration, or the same one with one habit changed."""
    action,habits=a
    if rng.random()<0.5:
        allowed=mask(c).nonzero().flatten().tolist()
        while True:
            b=rng.choice(allowed)
            if b!=action:return b,tuple(h for h in habits if habits_allowed([h],b,c))
    flips=[h for h in HABIT_IDS if h in habits or habits_allowed(sorted(set(habits)|{h},key=HABIT_IDS.index),action,c)]
    h=rng.choice(flips);other=tuple(sorted(set(habits)^{h},key=HABIT_IDS.index))
    return action,other

def pairwise_fit(decoder,support,steps=100):
    """Mirror of the runtime candidate fit (engine.learning.trainer.fit_candidate): pairwise
    logistic loss, Adam, L2 anchor and the relationship trust region on drift."""
    feats=torch.stack([features(c,h) for c,h,_,_ in support]);lm=torch.stack([level_mask(c) for c,*_ in support])
    la=torch.stack([APPROVED_LEVELS[a[0]] for *_,a,_ in support]);lb=torch.stack([APPROVED_LEVELS[b[0]] for *_,b in support])
    ha=torch.stack([habit_vector(a[1]) for *_,a,_ in support]);hb=torch.stack([habit_vector(b[1]) for *_,b in support])
    z=torch.zeros(CORE_DIM,requires_grad=True);opt=torch.optim.Adam([z],lr=0.05)
    for _ in range(steps):
        opt.zero_grad();t,h=decoder.batch(z,torch.zeros(REL_DIM),feats,lm)
        loss=-F.logsigmoid(choice_score(t,h,la,ha)-choice_score(t,h,lb,hb)).mean()
        (loss+0.01*z.square().mean()).backward();torch.nn.utils.clip_grad_norm_([z],1.0);opt.step()
        with torch.no_grad():z.mul_(min(1.0,RELATIONSHIP.maximum_drift*0.98/(float(z.norm())+1e-8)))
    return z.detach()

def habit_f1(decoder,z,profile,contexts,host):
    tp=fp=fn=0
    with torch.no_grad():
        for c in contexts:
            got=set(selected(decoder,z,c,host)[1]);want=set(target_choice(c,profile)[1])
            tp+=len(got&want);fp+=len(got-want);fn+=len(want-got)
    return 2*tp/(2*tp+fp+fn) if tp+fp+fn else 1.0

def heldout(decoder,personas,part,rng):
    stats=dict(personas=0,neutral=0.0,fixed_default=0.0,fitted=0.0,habit_f1_neutral=0.0,habit_f1_fitted=0.0)
    for p in personas:
        if p['partition']!=part:continue
        support=[];query=[random_context(rng) for _ in range(32)];host=rng.choice(HOSTS)
        for _ in range(16):
            c=random_context(rng);a=target_choice(c,p['profile']);support.append((c,rng.choice(HOSTS),a,rival(rng,c,a)))
        z=pairwise_fit(decoder,support)
        stats['personas']+=1
        stats['neutral']+=agreement(decoder,torch.zeros(CORE_DIM),p['profile'],query)
        stats['fixed_default']+=sum(float((APPROVED_LEVELS[NEUTRAL_ACTION]==APPROVED_LEVELS[target_choice(c,p['profile'])[0]]).float().mean()) for c in query)/len(query)
        stats['fitted']+=agreement(decoder,z,p['profile'],query)
        stats['habit_f1_neutral']+=habit_f1(decoder,torch.zeros(CORE_DIM),p['profile'],query,host);stats['habit_f1_fitted']+=habit_f1(decoder,z,p['profile'],query,host)
    n=stats.pop('personas')
    return dict(personas=n,support_pairs_per_persona=16,query_contexts_per_persona=32,metric='mean per-trait level agreement of the selected configuration',
        **{(f'trait_agreement_{k}' if not k.startswith('habit') else k):round(v/n,4) for k,v in stats.items()})

def main():
    torch.manual_seed(SEED);personas,rows=corpus()
    feats=torch.stack([features(r['context'],r['host']) for r in rows])
    lmasks=torch.stack([level_mask(r['context']) for r in rows])
    tt=torch.stack([trait_targets(r['context'],*profiles_of(personas,r)) for r in rows])
    ht=torch.stack([habit_targets(r['context'],*profiles_of(personas,r)) for r in rows])
    n_personas=len(personas)
    core_idx=torch.tensor([r['persona']+1 if r['persona'] is not None else 0 for r in rows])
    rel_idx=torch.tensor([r['persona']*2+r['user']+1 if r['user'] is not None else 0 for r in rows])
    model=Policy()
    core_table=torch.nn.Parameter(torch.randn(n_personas,CORE_DIM)*0.01)
    rel_table=torch.nn.Parameter(torch.randn(n_personas*2,REL_DIM)*0.01)
    opt=torch.optim.Adam([dict(params=model.parameters(),lr=3e-3),dict(params=[core_table,rel_table],lr=2e-2)])
    def forward():
        core=torch.cat((torch.zeros(1,CORE_DIM),core_table))[core_idx];rel=torch.cat((torch.zeros(1,REL_DIM),rel_table))[rel_idx]
        t,h=model(torch.cat((core,rel,torch.zeros(len(rows),SESSION_DIM),feats),1))
        return torch.log_softmax(t.masked_fill(~lmasks,float('-inf')),-1),h
    for step in range(700):
        opt.zero_grad();t,h=forward()
        loss=distribution_loss(t,h,tt,ht).mean()
        # Calibrated so latent norms match the scale the engine constants assume (median core ~1.4).
        prior=PRIOR*(core_table.square().sum(1).mean()+rel_table.square().sum(1).mean())
        (loss+prior).backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step()
    model.eval()
    with torch.no_grad():
        trained=[i for i,p in enumerate(personas) if p['partition']=='train']
        norms=core_table[trained].norm(dim=1);rel_norms=rel_table[[2*i+u for i in trained for u in (0,1)]].norm(dim=1)
        t,h=forward()
        trait_acc=float((t.argmax(-1)==tt.argmax(-1)).float().mean());habit_acc=float(((h>0)==(ht>0.5)).float().mean())
    OUT.mkdir(parents=True,exist_ok=True);path=OUT/'decoder.safetensors';save_file(model.state_dict(),str(path))
    corpus_hash=hashlib.sha256(json.dumps(dict(personas=personas,rows=rows),sort_keys=True).encode()).hexdigest()
    meta=dict(hash=digest(path),seed=SEED,encoder=ENCODER,catalogue=SCHEMA,catalogue_hash=CATALOGUE_HASH,actions=ACTIONS,habits=len(HABIT_IDS),status='experimental_synthetic',
        latent_norm_limit=round(float(norms.quantile(.99))*1.25,3),
        training=dict(rows=len(rows),train_personas=PARTITIONS['train'],relationship_rows=sum(r['user'] is not None for r in rows),neutral_rows=sum(r['persona'] is None for r in rows),
            steps=700,trait_level_accuracy_train=round(trait_acc,4),habit_accuracy_train=round(habit_acc,4),core_latent_norm_median=round(float(norms.median()),3),
            relationship_latent_norm_median=round(float(rel_norms.median()),3),corpus_sha256=corpus_hash),
        license='Apache-2.0 weights; original CC0 synthetic corpus',limitations=['Synthetic rule/profile labels only','No independent human validation','No measured cross-model benefit'])
    path.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    decoder=Decoder(path);rng=random.Random(SEED+1)
    # Held-out personas are never seen by the decoder; only their few-shot latents are fitted.
    meta['heldout_persona_fewshot']={part:heldout(decoder,personas,part,rng) for part in ('calibration','validation')}
    seeds={}
    for name in sorted(SEEDS):
        z=fit_seed_latent(decoder,[name]);seeds[name]=round(agreement(decoder,z,seed_profile([name]),[random_context(rng) for _ in range(64)]),4)
    meta['seed_initialization_trait_agreement']=seeds
    path.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    (ROOT/'benchmarks/data/decoder-corpus.jsonl').write_text(''.join(json.dumps(dict(group=p['group'],partition=p['partition'],profile=p['profile'],relationship_profiles=p['users'],provenance='original CC0 synthetic persona profile; not human feedback'))+'\n' for p in personas))
    print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
