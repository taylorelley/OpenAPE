"""Paired A/B/C/D benchmark for independently labeled outcomes.
Input JSONL: scenario_id, group_id, provider, harness, evidence_source,
A/B/C/D: {preference_satisfied:0|1,task_correct:0|1,safe:0|1}.
No model judge, provider credential, or training data is silently manufactured.
"""
import argparse
import json
import math
from pathlib import Path
import numpy as np

def evaluate(rows):
    if len({r['scenario_id'] for r in rows})!=len(rows):raise ValueError('Duplicate scenario IDs')
    sources={r['evidence_source'] for r in rows}
    if not sources<={'human','independent_evaluator','synthetic'}:raise ValueError('Unknown evidence source')
    for r in rows:
        for k in 'ABCD':
            if set(r[k])!={'preference_satisfied','task_correct','safe'} or any(v not in (0,1) for v in r[k].values()):raise ValueError('All baselines need complete binary independent labels')
    groups=sorted({r['group_id'] for r in rows});rng=np.random.default_rng(42)
    def stats(subset):
        return {k:{m:sum(r[k][m] for r in subset)/len(subset) for m in ('preference_satisfied','task_correct','safe')} for k in 'ABCD'}
    deltas=[]
    grouped={g:[r['D']['preference_satisfied']-r['B']['preference_satisfied'] for r in rows if r['group_id']==g] for g in groups}
    for _ in range(2000):
        sample=rng.choice(groups,len(groups),replace=True)
        values=[v for g in sample for v in grouped[g]];deltas.append(float(np.mean(values)))
    return dict(interactions=len(rows),independent_groups=len(groups),evidence_sources=sorted(sources),measured_behavioral_benefit='synthetic' not in sources and len(rows)>=200 and float(np.quantile(deltas,.025))>0,summary=stats(rows),learning_minus_fixed_mean=float(np.mean([r['D']['preference_satisfied']-r['B']['preference_satisfied'] for r in rows])),learning_minus_fixed_cluster_bootstrap_95_ci=[float(np.quantile(deltas,q)) for q in (.025,.975)],providers={p:stats([r for r in rows if r['provider']==p]) for p in sorted({r['provider'] for r in rows})},harnesses={h:stats([r for r in rows if r['harness']==h]) for h in sorted({r['harness'] for r in rows})},limitations=['Binary labels and declared groups require independent provenance review','Sample size is provisional, not a proof of significance','Safety/task non-inferiority needs its own predefined margins'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('outcomes');parser.add_argument('--output',default='benchmarks/reports/independent.json');args=parser.parse_args()
    rows=[json.loads(l) for l in Path(args.outcomes).read_text().splitlines() if l.strip()]
    if not rows:raise ValueError('No outcomes')
    result=evaluate(rows);Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
