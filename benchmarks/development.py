"""Developmental trajectory benchmark (ADR 0004). NOT human or live-model evidence.

Drives personas through simulated lives over the real API (in-process ASGI) with
automatic evolution, and compares their trajectories with patterns that personality
psychology reports for people. The comparisons are qualitative; the numbers are a
regression record for these fixed priors, not a validation of them.

* Rank-order stability: how consistently personas keep their order on each trait
  between checkpoints (Spearman across personas, averaged over traits). In people it
  rises with age and levels off below 1 (about 0.5 in youth to 0.7 in adulthood,
  Roberts & DelVecchio 2000).
* Mean-level change per period: largest while development runs (in people, young
  adulthood), small once mature, briefly larger after a life event (here a role
  change after development is complete).
* Individuality: personas of the same archetype stay closer to each other than to
  other archetypes, but are not identical.

Each persona has a linked simulated user with a hidden preference for one catalogue
row; in some sessions that user states a consented relationship preference for it.
"""
import json
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from engine.api.app import create_app
from engine.neural.policy import CATALOGUE, VOCAB, mask

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261022
TOKEN = 'development-benchmark-token-0000000000'
ARCHETYPES = ('mentor', 'pragmatic_engineer', 'analyst', 'collaborator')
INDIVIDUALS, SESSIONS, ROLE_SWITCH, CHECK_EVERY = 2, 48, 32, 8
HORIZONS = dict(relationship_horizon=12, core_horizon=20)
FEEDBACK_RATE = 0.3
EVAL_CONTEXTS = [dict(task_type=t, channel='terminal', stakes='low', turn_origin='user', tags=tags)
                 for t, tags in (('general', []), ('coding', []), ('support', []), ('research', ['beginner']), ('code_review', ['expert']), ('creative', []))]
TRAITS = list(CATALOGUE[0])

def role(rng):
    tasks = rng.sample(VOCAB['task_type'], 2)
    return lambda: dict(task_type=rng.choice(tasks), channel='terminal', stakes=rng.choice(('low', 'medium')), turn_origin='user', tags=rng.sample(['technical', 'expert', 'beginner'], rng.choice((0, 1))))

def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1]) if ra.std() and rb.std() else 1.0

def run(data_dir):
    rng = random.Random(SEED)
    creds = [dict(token=TOKEN, tenant='local', actor='sim', scopes=['persona:express', 'observations:write', 'feedback:write', 'persona:admin', 'training:admin'], personas=['*'], users=['*'])]
    with TestClient(create_app(data_dir, credentials=creds, rate_limit_per_minute=100000), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        post = lambda path, body: api.post(path, json={'protocol_version': 'upap/1', **body}).json()
        def express(persona, rid, session, ctx, mode='active', debug=False):
            return post('/v1/express', dict(request_id=rid, identity=dict(tenant_id='local', persona_id=persona, user_id='user'), session=dict(id=session, turn_id=rid),
                host=dict(adapter_id='benchmark', adapter_version='0.2.0', host_version='simulated', provider_family='other', model_id='simulated'), context=ctx, mode=mode, debug=debug))
        def traits(persona, k):
            levels = [express(persona, f'{persona}-eval-{k}-{i}', f'{persona}-eval-{k}-{i}', ctx, 'shadow', True)['diagnostics'] for i, ctx in enumerate(EVAL_CONTEXTS)]
            return [float(np.mean([d[t] for d in levels])) for t in TRAITS]
        personas = []
        for name in ARCHETYPES:
            for i in range(INDIVIDUALS):
                persona = f'{name}-{i}'; post('/v1/personas', dict(persona_id=persona, archetype=name, maturation_rate=HORIZONS))
                personas.append(dict(id=persona, archetype=name, roles=(role(rng), role(rng)), liked=rng.randrange(len(CATALOGUE))))
        checkpoints = [[traits(p['id'], 0) for p in personas]]
        for s in range(1, SESSIONS + 1):
            for p in personas:
                session = f"{p['id']}-s{s}"; ctx = p['roles'][s > ROLE_SWITCH]()
                for turn in range(2):
                    d = express(p['id'], f'{session}-{turn}', session, ctx); shown = int(d['control_set_id'][-2:])
                    if rng.random() < FEEDBACK_RATE and shown != p['liked'] and mask(ctx)[p['liked']]:
                        post('/v1/feedback', dict(feedback_id=f'{session}-f{turn}', decision_id=d['decision_id'], source='explicit_user', kind='pairwise_preference', actor_id='sim',
                            consent_scope='relationship', learning_consent=True, preferred_control=p['liked'], rejected_control=shown, evidence_group=session))
                post('/v1/observations', dict(adapter_id='benchmark', events=[dict(event_id=f'{session}-end', occurred_at=datetime.now(timezone.utc).isoformat(),
                    persona_id=p['id'], user_id='user', session_id=session, type='session.ended')]))
                api.app.state.drain()
            if s % CHECK_EVERY == 0: checkpoints.append([traits(p['id'], s) for p in personas])
        events = {}; growth = {}
        for p in personas:
            for a in api.get(f"/v1/personas/{p['id']}/history").json()['audit']:
                if a['action'] == 'life_event': e = json.loads(a['data'])['event']; events[e] = events.get(e, 0) + 1
                if a['action'] == 'matured':
                    for part in json.loads(a['data'])['components']: growth[part] = growth.get(part, 0) + 1
            info = api.get(f"/v1/personas/{p['id']}?user_id=user").json(); p['growth'] = info['growth']; p['character_drift'] = info['character_drift']
    return personas, np.array(checkpoints), events, growth

def main():
    with tempfile.TemporaryDirectory() as tmp: personas, cp, events, growth = run(tmp)
    periods = [f'{k * CHECK_EVERY}-{(k + 1) * CHECK_EVERY}' for k in range(len(cp) - 1)]
    stability = [round(float(np.mean([spearman(cp[k][:, t], cp[k + 1][:, t]) for t in range(len(TRAITS))])), 4) for k in range(len(cp) - 1)]
    change = [round(float(np.abs(cp[k + 1] - cp[k]).mean()), 4) for k in range(len(cp) - 1)]
    end = cp[-1]; same, other = [], []
    for i in range(len(personas)):
        for j in range(i + 1, len(personas)):
            (same if personas[i]['archetype'] == personas[j]['archetype'] else other).append(float(np.abs(end[i] - end[j]).mean()))
    report = dict(kind='developmental trajectory engineering benchmark; NOT human or live-model evidence', seed=SEED, personas=len(personas), sessions=SESSIONS,
        role_switch_after_session=ROLE_SWITCH, horizons=HORIZONS, periods=periods, rank_order_stability=stability, mean_level_change=change,
        individuality=dict(same_archetype_distance=round(float(np.mean(same)), 4), different_archetype_distance=round(float(np.mean(other)), 4)),
        life_events=events, consolidation_components=growth,
        final_growth={p['id']: dict(core=p['growth']['core']['maturity'], relationship=p['growth']['relationship']['maturity'], character_drift=p['character_drift']) for p in personas},
        human_reference='rank-order stability rises with age and plateaus near 0.7 (Roberts & DelVecchio 2000); mean-level change is largest in young adulthood and small later (Roberts, Walton & Viechtbauer 2006)',
        limitations=['Synthetic users and fixed priors; no human raters or live LLM outputs', 'Trait levels are decoder diagnostics over six fixed contexts',
            f'{len(personas)} personas over {SESSIONS} sessions; qualitative comparison only'])
    out = ROOT / 'benchmarks/reports/development.json'; out.write_text(json.dumps(report, indent=2) + '\n'); print(json.dumps(report, indent=2))

if __name__ == '__main__': sys.exit(main())
