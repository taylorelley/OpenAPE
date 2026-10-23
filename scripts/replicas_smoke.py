"""Run after `openape init` and `docker compose -f compose.replicas.yaml up -d`: two engine
replicas on one PostgreSQL database. Drives both over HTTP. No provider call."""
import json
import sys
import time
import uuid
from pathlib import Path
import httpx
from sdk.python.client import Client

def main(a='http://127.0.0.1:8765', b='http://127.0.0.1:8766'):
    token = json.loads(Path('.openape/credentials.json').read_text())[0];A, B = Client(a, token['token'], timeout=10), Client(b, token['token'], timeout=10)
    try:
        for c in (A, B):
            for _ in range(300):
                try:
                    if c.request('GET', '/health/ready')['engine_status'] == 'experimental_synthetic': break
                except httpx.TransportError: pass
                time.sleep(.2)
            else: raise RuntimeError('replica not ready')
        persona = 'replicas-' + uuid.uuid4().hex[:8];A.request('POST', '/v1/personas', {'persona_id': persona, 'archetype': 'mentor', 'evolution': 'manual'})
        assert B.request('GET', f'/v1/personas/{persona}')['active_version'] == A.request('GET', f'/v1/personas/{persona}')['active_version']
        req = json.loads(Path('examples/express.json').read_text());req['identity']['persona_id'] = persona
        terse = {'controls': dict(directness=3, warmth=1, verbosity=1, humour=0, formality=2, explanation_depth=1, assertiveness=3), 'habits': []}
        for i in range(40):
            d = (A, B)[i % 2].request('POST', '/v1/express', {**req, 'request_id': f'r-{i}', 'session': {'id': f's{i % 20}', 'turn_id': str(i)}})
            served = {'controls': d['controls'], 'habits': d['habits']}
            (B, A)[i % 2].request('POST', '/v1/feedback', dict(protocol_version='upap/2', feedback_id=f'{persona}-{i}', decision_id=d['decision_id'], source='owner', kind='pairwise_preference',
                actor_id=token['actor'], consent_scope='core', learning_consent=True, preferred=terse if served != terse else {**terse, 'habits': ['next_step']}, rejected=served, evidence_group=f's{i % 20}'))
        job = A.request('POST', '/v1/consolidations', dict(protocol_version='upap/2', persona_id=persona, scope='core'))['job_id']
        for _ in range(600):
            state = B.request('GET', '/v1/consolidations/' + job)
            if state['status'] != 'queued': break
            time.sleep(.2)
        report = dict(replicas=[a, b], database='postgres:16', persona_id=persona, job_seen_from_other_replica=state['status'] in ('evaluated', 'failed'), evaluator=state.get('report', {}).get('evaluator'), eligible=state.get('eligible'))
        if state.get('eligible'):
            base = A.request('GET', f'/v1/personas/{persona}')['active_version'];codes = []
            for c in (B, A):
                try: c.request('POST', f'/v1/personas/{persona}/promotions', dict(protocol_version='upap/2', candidate_id=job, expected_version=base));codes.append(200)
                except Exception as exc: codes.append(getattr(exc, 'status', 'error'))
            report['promotion_codes'] = codes;report['compare_and_swap'] = sorted(map(str, codes)) == ['200', '409']
            after = A.request('POST', '/v1/express', {**req, 'request_id': 'after', 'session': {'id': 'after', 'turn_id': '1'}})
            report['promoted_version_served_by_other_replica'] = after['persona_version'] != base
        Path('docs/reports').mkdir(parents=True, exist_ok=True);Path('docs/reports/replicas-smoke.json').write_text(json.dumps(report, indent=2) + '\n');print(json.dumps(report, indent=2))
        if not report['job_seen_from_other_replica'] or report.get('compare_and_swap') is False: sys.exit(1)
    finally: A.close();B.close()
if __name__ == '__main__': main()
