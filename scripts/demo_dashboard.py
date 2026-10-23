"""A demo persona's life in a throwaway engine, for the dashboard.

A mentor persona works with one linked user over a number of sessions. The user sets
preferences and a humour pin, prefers shorter answers a few times, and the agent
reflects that the user wants risks flagged first. Sessions end, so the persona matures.
Writes the timeline, the explanation of the last decision and a few totals as JSON.

    python -m scripts.demo_dashboard --out demo.json [--html demo.html]

All data is synthetic; nothing leaves the process.
"""
import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from engine.api.app import create_app
from protocol.catalogue import NEUTRAL

TOKEN = 'demo-owner-token-not-a-secret-000000'
CREDS = [dict(token=TOKEN, tenant='local', actor='owner', personas=['*'], users=['*'],
    scopes=['persona:express', 'observations:write', 'feedback:write', 'persona:admin', 'training:admin', 'reflection:write', 'settings:write'])]

def body(**kw): return {'protocol_version': 'upap/2', **kw}

def request(rid, session, task='coding', stakes='low', tags=()):
    return body(request_id=rid, identity={'tenant_id': 'local', 'persona_id': 'sage', 'user_id': 'alice'}, session={'id': session, 'turn_id': rid},
        host={'adapter_id': 'upap.claude-code', 'adapter_version': '0.3.0', 'host_version': 'demo', 'provider_family': 'anthropic', 'model_id': 'demo'},
        context={'task_type': task, 'channel': 'terminal', 'stakes': stakes, 'turn_origin': 'user', 'tags': list(tags), 'language': 'python', 'repo_kind': 'software'}, mode='active')

def run(sessions=14):
    with tempfile.TemporaryDirectory(prefix='openape-demo-') as tmp, TestClient(create_app(tmp, credentials=CREDS), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        post = lambda path, data: api.post(path, json=body(**data))
        assert post('/v1/personas', dict(persona_id='sage', archetype='mentor', maturation_rate='fast', individuality=0.3, individuality_seed=7)).status_code == 200
        api.put('/v1/personas/sage/users/alice/settings', json=body(preferences={'spelling': 'british', 'format': 'code_first'}, pins={'humour': {'min': 0, 'max': 1}}))
        tasks = ['coding', 'debugging', 'code_review', 'coding', 'planning']; last = None
        for s in range(sessions):
            sid = f'demo-{s}'
            for turn in range(3):
                d = post('/v1/express', request(f'{sid}-{turn}', sid, tasks[(s + turn) % len(tasks)], 'high' if (s, turn) == (6, 1) else 'low')).json();last = d
                served = {'controls': d['controls'], 'habits': d['habits']}
                if turn == 0 and s % 3 == 0 and d['controls']['verbosity'] > 1:
                    shorter = {'controls': {**d['controls'], 'verbosity': d['controls']['verbosity'] - 1, 'explanation_depth': min(d['controls']['explanation_depth'], 3)}, 'habits': [h for h in d['habits'] if h not in ('confirm_goal', 'recap_end')]}
                    post('/v1/feedback', dict(feedback_id=f'{sid}-short', decision_id=d['decision_id'], source='explicit_user', kind='pairwise_preference', actor_id='owner',
                        consent_scope='relationship', learning_consent=True, preferred=shorter, rejected=served, evidence_group=sid))
                if turn == 1 and s % 4 == 1 and 'risks_first' not in d['habits']:
                    post('/v1/reflections', dict(reflection_id=f'{sid}-risks', decision_id=d['decision_id'], adjustments={}, habits={'risks_first': 'more_often'}, reason='observed_preference'))
            post('/v1/observations', dict(adapter_id='upap.claude-code', events=[dict(event_id=f'{sid}-end', occurred_at=datetime.now(timezone.utc).isoformat(), persona_id='sage',
                user_id='alice', session_id=sid, type='session.ended')]))
            api.app.state.drain()
        final = post('/v1/express', request('final', 'demo-final', 'coding')).json()
        return dict(generated_at=datetime.now(timezone.utc).isoformat(), synthetic=True, sessions=sessions, final_decision=final,
            timeline=api.get('/v1/personas/sage/timeline?user_id=alice').json(), explanation=api.get(f"/v1/decisions/{final['decision_id']}/explanation").json(),
            inspect=api.get('/v1/personas/sage?user_id=alice').json())

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sessions', type=int, default=14);ap.add_argument('--out', default='-');ap.add_argument('--html')
    a = ap.parse_args(argv);data = run(a.sessions)
    text = json.dumps(data, indent=2)
    if a.out == '-': print(text)
    else: Path(a.out).write_text(text + '\n')
    if a.html:
        from sdk.cli.main import dashboard_html
        Path(a.html).write_text(dashboard_html(data))

if __name__ == '__main__': main()
