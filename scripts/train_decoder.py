"""Reproduce an experimental decoder from original CC0 synthetic labels.
No human labels, provider outputs or behavioral efficacy claims.
"""
import json
from pathlib import Path
import torch
from engine.neural.policy import Policy, inputs, CATALOGUE, digest

ROOT=Path(__file__).resolve().parents[1]
def corpus():
    rows=[]
    for family in range(36):
        # Groups are original scenario families, not random rows.
        for task in ('general','code_review','coding','support','creative','research'):
            for stakes in ('low','high'):
                c=dict(task_type=task,channel='chat' if family%2 else 'terminal',stakes=stakes,turn_origin='user',tags=['beginner'] if family%3==0 else ['expert'])
                h=dict(provider_family=['openai','anthropic','google'][family%3],adapter_id='reference')
                warmth='high' if task=='support' else 'moderate'
                verbosity='high' if 'beginner' in c['tags'] else 'low'
                def score(item):
                    return 3*(item['verbosity']==verbosity)+2*(item['warmth']==warmth)+(item['directness']=='high')-10*(stakes=='high' and item['humour']!='low')
                label=max(range(20),key=lambda i:score(CATALOGUE[i]))
                rows.append(dict(group=f'original-scenario-{family}',partition='train' if family<24 else ('calibration' if family<28 else 'validation'),context=c,host=h,label=label,provenance='original CC0 synthetic rule labels; not human feedback'))
    return rows

def main():
    torch.manual_seed(42); model=Policy();rows=corpus()
    # Small seeded latent perturbations teach a smooth decoder surface; these are
    # synthetic training variation, not evidence that a latent has personality.
    def batch(part):
        subset=[r for r in rows if r['partition']==part]
        x=torch.stack([inputs(torch.randn(64)*0.15,torch.randn(32)*0.15,r['context'],r['host']) for r in subset])
        return x,torch.tensor([r['label'] for r in subset])
    x,y=batch('train');opt=torch.optim.Adam(model.parameters(),lr=.006)
    for _ in range(180):
        opt.zero_grad();loss=torch.nn.functional.cross_entropy(model(x),y);loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step()
    model.eval();metrics={}
    for part in ('train','calibration','validation'):
        xx,yy=batch(part)
        with torch.no_grad():metrics[part]={'examples':len(yy),'accuracy':float((model(xx).argmax(-1)==yy).float().mean()),'cross_entropy':float(torch.nn.functional.cross_entropy(model(xx),yy))}
    from safetensors.torch import save_file
    path=ROOT/'models/decoder-v1/decoder.safetensors';save_file(model.state_dict(),str(path))
    meta=dict(hash=digest(path),seed=42,encoder='encoder/1',catalogue='behaviour-controls/1',status='experimental_synthetic',metrics=metrics,license='Apache-2.0 weights; original CC0 corpus',limitations=['Synthetic rule labels only','No independent human validation','No measured cross-model benefit'])
    path.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    (ROOT/'benchmarks/data/decoder-corpus.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (ROOT/'renderers/controls-v1.json').write_text(json.dumps(CATALOGUE,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
