"""Human raters for the identity line-up (ADR 0007).

`export` writes blinded items (texts only) for `rater.html`, and the answer key to a
separate file that raters must not see. `score` turns downloaded rater results into
accuracy per arm, agreement with the model judge, and agreement between raters.

    python -m benchmarks.identity.humans score ITEMS.key.json RESULTS.json [RESULTS2.json ...]
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
import numpy as np

def export(trials, items, path, seed=0, limit=120):
    """`trials`: line-up trials with `key`; `items`: {key: (references, candidates)}.
    Identical line-ups shared by several arms are shown once."""
    rng = random.Random(seed); unique = {}
    for t in trials: unique.setdefault(t['key'], []).append(t)
    keys = sorted(unique); rng.shuffle(keys); keys = keys[:limit]
    public = dict(format='openape-identity-items/1', instructions='Read the reference replies: they are all in one voice. Then pick the candidate written in the same voice. Judge voice, not topic or correctness.',
        items=[dict(id=k, references=[dict(task=task, reply=reply) for task, reply in items[k][0]], candidate_task=items[k][1][0][0], candidates=[reply for _, reply in items[k][1]]) for k in keys])
    key = dict(format='openape-identity-key/1', items={k: dict(correct=unique[k][0]['correct'], arms=sorted({t['arm'] for t in unique[k]}), judge=unique[k][0].get('answer'),
        persona=unique[k][0]['persona'], source_model=unique[k][0]['source_model'], target_model=unique[k][0]['target_model'], target_prompt=unique[k][0]['target_prompt']) for k in keys})
    path = Path(path); path.write_text(json.dumps(public, indent=2) + '\n'); Path(str(path) + '.key.json').write_text(json.dumps(key, indent=2) + '\n')
    return len(keys)

def kappa(a, b):
    """Cohen's kappa for two raters' categorical answers."""
    a, b = np.asarray(a), np.asarray(b)
    if len(a) == 0: return None
    po = float(np.mean(a == b)); cats = sorted(set(a) | set(b)); pe = sum(float(np.mean(a == c)) * float(np.mean(b == c)) for c in cats)
    return None if pe >= 1 else round((po - pe) / (1 - pe), 4)

def score(key, results):
    """`results`: list of rater files ({rater, answers: {item id: 0-based choice}})."""
    items = key['items']; by_arm = defaultdict(list); human = defaultdict(dict)
    for r in results:
        for item, answer in r['answers'].items():
            if item not in items or type(answer) is not int: continue
            human[r.get('rater', 'anonymous')][item] = answer
            for arm in items[item]['arms']: by_arm[arm].append(float(answer == items[item]['correct']))
    raters = sorted(human); pooled = [(human[r][i], items[i]['judge']) for r in raters for i in human[r] if items[i]['judge'] is not None]
    pairs = [(human[x][i], human[y][i]) for n, x in enumerate(raters) for y in raters[n + 1:] for i in human[x] if i in human[y]]
    return dict(kind='human raters on blinded line-ups', raters=len(raters), answers=sum(len(v) for v in human.values()),
        accuracy={arm: dict(mean=round(float(np.mean(v)), 4), n=len(v)) for arm, v in sorted(by_arm.items())},
        judge_accuracy_on_rated_items=round(float(np.mean([items[i]['judge'] == items[i]['correct'] for r in raters for i in human[r] if items[i]['judge'] is not None])), 4) if pooled else None,
        human_judge_agreement=dict(same_choice=round(float(np.mean([h == j for h, j in pooled])), 4), kappa=kappa([h for h, _ in pooled], [j for _, j in pooled])) if pooled else None,
        inter_rater=dict(pairs=len(pairs), same_choice=round(float(np.mean([x == y for x, y in pairs])), 4), kappa=kappa([x for x, _ in pairs], [y for _, y in pairs])) if pairs else None)

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3 or argv[0] != 'score': print(__doc__); return 2
    print(json.dumps(score(json.loads(Path(argv[1]).read_text()), [json.loads(Path(f).read_text()) for f in argv[2:]]), indent=2)); return 0

if __name__ == '__main__': sys.exit(main())
