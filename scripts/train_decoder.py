"""Reproduce decoder-v2 from original CC0 synthetic persona profiles (auto-decoder).

The shared decoder and a table of per-persona/per-relationship latents are fitted
jointly, so latent state genuinely conditions behaviour. Held-out personas are then
fitted from a few pairwise preferences with the decoder frozen (exactly the runtime
learning path) and evaluated on unseen contexts. All labels are synthetic rules;
no human evidence, provider outputs or behavioural-efficacy claims.
"""
import hashlib
import json
import random
from pathlib import Path
import torch
from safetensors.torch import save_file
from engine.neural.policy import Policy, Decoder, features, mask, digest, CATALOGUE, CORE_DIM, REL_DIM, SESSION_DIM, ENCODER, ACTIONS
from engine.neural.profiles import target_distribution, random_context, random_profile, agreement, fit_seed_latent, SEEDS

ROOT=Path(__file__).resolve().parents[1]
SEED=42
PARTITIONS=dict(train=384,calibration=64,validation=96)
HOSTS=[dict(provider_family=p,adapter_id=a) for p in ('openai','anthropic','google','qwen','other') for a in ('upap.pi','upap.hermes','upap.claude-code','upap.openclaw','upap.opencogni','custom')]

def corpus():
    rng=random.Random(SEED); personas=[]
    for part,count in PARTITIONS.items():
        for _ in range(count):
            personas.append(dict(group=f'synthetic-persona-{len(personas):04d}',partition=part,profile=random_profile(rng),
                users=[random_profile(rng,(1,2)) for _ in range(2)]))
    rows=[]
    for i,p in enumerate(personas):
        if p['partition']!='train':continue
        for _ in range(40):rows.append(dict(persona=i,user=None,context=random_context(rng),host=rng.choice(HOSTS)))
        for u in range(2):
            for _ in range(12):rows.append(dict(persona=i,user=u,context=random_context(rng),host=rng.choice(HOSTS)))
    for _ in range(4000):rows.append(dict(persona=None,user=None,context=random_context(rng),host=rng.choice(HOSTS)))
    return personas,rows

def target(personas,row):
    profiles=[]
    if row['persona'] is not None:
        p=personas[row['persona']];profiles.append(p['profile'])
        if row['user'] is not None:profiles.append(p['users'][row['user']])
    return target_distribution(row['context'],*profiles)

def pairwise_fit(decoder,support,steps=100):
    """Mirror of the runtime candidate fit: pairwise softmax loss, Adam, L2 anchor."""
    z=torch.zeros(CORE_DIM,requires_grad=True);opt=torch.optim.Adam([z],lr=0.05);rel=torch.zeros(REL_DIM)
    for _ in range(steps):
        opt.zero_grad()
        loss=torch.stack([-torch.log_softmax(decoder.logits(z,rel,c,h)[[a,b]],0)[0] for c,h,a,b in support]).mean()
        (loss+0.01*z.square().mean()).backward();torch.nn.utils.clip_grad_norm_([z],1.0);opt.step()
    return z.detach()

def heldout(decoder,personas,part,rng):
    stats=dict(personas=0,neutral=0.0,fixed_default=0.0,fitted=0.0)
    for p in personas:
        if p['partition']!=part:continue
        support=[];query=[random_context(rng) for _ in range(32)]
        for _ in range(16):
            c=random_context(rng);h=rng.choice(HOSTS);t=target_distribution(c,p['profile']);a=int(t.argmax())
            options=[i for i in range(ACTIONS) if mask(c)[i] and i!=a];support.append((c,h,a,rng.choice(options)))
        z=pairwise_fit(decoder,support)
        stats['personas']+=1
        stats['neutral']+=agreement(decoder,torch.zeros(CORE_DIM),p['profile'],query)
        stats['fixed_default']+=sum(int(target_distribution(c,p['profile']).argmax())==0 for c in query)/len(query)
        stats['fitted']+=agreement(decoder,z,p['profile'],query)
    n=stats.pop('personas');return dict(personas=n,support_pairs_per_persona=16,query_contexts_per_persona=32,**{f'top1_agreement_{k}':round(v/n,4) for k,v in stats.items()})

def main():
    torch.manual_seed(SEED);personas,rows=corpus()
    feats=torch.stack([features(r['context'],r['host']) for r in rows])
    targets=torch.stack([target(personas,r) for r in rows])
    masks=torch.stack([mask(r['context']) for r in rows])
    n_personas=len(personas)
    core_idx=torch.tensor([r['persona']+1 if r['persona'] is not None else 0 for r in rows])
    rel_idx=torch.tensor([r['persona']*2+r['user']+1 if r['user'] is not None else 0 for r in rows])
    model=Policy()
    core_table=torch.nn.Parameter(torch.randn(n_personas,CORE_DIM)*0.01)
    rel_table=torch.nn.Parameter(torch.randn(n_personas*2,REL_DIM)*0.01)
    opt=torch.optim.Adam([dict(params=model.parameters(),lr=3e-3),dict(params=[core_table,rel_table],lr=2e-2)])
    for step in range(700):
        opt.zero_grad()
        core=torch.cat((torch.zeros(1,CORE_DIM),core_table))[core_idx];rel=torch.cat((torch.zeros(1,REL_DIM),rel_table))[rel_idx]
        x=torch.cat((core,rel,torch.zeros(len(rows),SESSION_DIM),feats),1)
        logp=torch.log_softmax(model(x).masked_fill(~masks,-1e9),1)
        loss=-(targets*logp.masked_fill(targets==0,0)).sum(1).mean()
        prior=1e-3*(core_table.square().sum(1).mean()+rel_table.square().sum(1).mean())
        (loss+prior).backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);opt.step()
    model.eval()
    with torch.no_grad():
        trained=[i for i,p in enumerate(personas) if p['partition']=='train']
        norms=core_table[trained].norm(dim=1);rel_norms=rel_table[[2*i+u for i in trained for u in (0,1)]].norm(dim=1)
        core=torch.cat((torch.zeros(1,CORE_DIM),core_table))[core_idx];rel=torch.cat((torch.zeros(1,REL_DIM),rel_table))[rel_idx]
        logits=model(torch.cat((core,rel,torch.zeros(len(rows),SESSION_DIM),feats),1)).masked_fill(~masks,-1e9)
        train_acc=float((logits.argmax(1)==targets.argmax(1)).float().mean())
    path=ROOT/'models/decoder-v2/decoder.safetensors';save_file(model.state_dict(),str(path))
    corpus_hash=hashlib.sha256(json.dumps(dict(personas=personas,rows=rows),sort_keys=True).encode()).hexdigest()
    meta=dict(hash=digest(path),seed=SEED,encoder=ENCODER,catalogue='behaviour-controls/1',actions=ACTIONS,status='experimental_synthetic',
        latent_norm_limit=round(float(norms.quantile(.99))*1.25,3),
        training=dict(rows=len(rows),train_personas=PARTITIONS['train'],relationship_rows=sum(r['user'] is not None for r in rows),neutral_rows=sum(r['persona'] is None for r in rows),
            steps=700,top1_agreement_train=round(train_acc,4),core_latent_norm_median=round(float(norms.median()),3),relationship_latent_norm_median=round(float(rel_norms.median()),3),corpus_sha256=corpus_hash),
        license='Apache-2.0 weights; original CC0 synthetic corpus',limitations=['Synthetic rule/profile labels only','No independent human validation','No measured cross-model benefit'])
    path.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    decoder=Decoder(path);rng=random.Random(SEED+1)
    # Held-out personas are never seen by the decoder; only their few-shot latents are fitted.
    meta['heldout_persona_fewshot']={part:heldout(decoder,personas,part,rng) for part in ('calibration','validation')}
    seeds={}
    for name in sorted(SEEDS):
        z=fit_seed_latent(decoder,[name]);seeds[name]=round(agreement(decoder,z,SEEDS[name],[random_context(rng) for _ in range(64)]),4)
    meta['seed_initialization_top1_agreement']=seeds
    path.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    (ROOT/'benchmarks/data/decoder-corpus.jsonl').write_text(''.join(json.dumps(dict(group=p['group'],partition=p['partition'],profile=p['profile'],relationship_profiles=p['users'],provenance='original CC0 synthetic persona profile; not human feedback'))+'\n' for p in personas))
    (ROOT/'renderers/controls-v1.json').write_text(json.dumps(CATALOGUE,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
