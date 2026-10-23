"""Live tool-calling smoke: a real host (Hermes Agent, or OpenClaw with --host openclaw) with
the OpenAPE plugin, a real
model behind an OpenAI-compatible provider (for example OpenRouter), and a real engine.

The user states a style preference; the check is whether the model calls the plugin's
persona_feedback tool, whether the engine records it as a bounded agent reflection, and
whether the next turn's injected style moved that way. Requests pass through a local
recording relay that adds the key; the key is never written to the report.

    OPENROUTER_API_KEY=... python -m scripts.live_tool_smoke --model z-ai/glm-5.3-flash \\
        --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY

Live-model evidence for one model on a few turns, not a benchmark.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from scripts.hostkit import ROOT, Engine, RelayModel, count_marker, write_report
from scripts.hermes_host_smoke import hermes_bin, HERMES_VERSION

def tool_results(requests):
    """What the host returned to the model for its persona_feedback calls."""
    out = []
    for r in requests:
        msgs = r['body'].get('messages') or [];names = {}
        for m in msgs:
            for call in m.get('tool_calls') or []: names[call.get('id')] = call.get('function', {}).get('name')
        for m in msgs:
            if m.get('role') == 'tool' and names.get(m.get('tool_call_id')) == 'persona_feedback':
                text = m['content'] if isinstance(m['content'], str) else json.dumps(m['content'])
                if text not in out: out.append(text[:300])
    return out

PREFERENCE = ('Please note for the future: I want much shorter answers from you, and always end with a suggested next step. '
    'If you have a tool for recording my style preferences, use it. Then say in one sentence what a Python list comprehension is.')

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', required=True);ap.add_argument('--base-url', required=True);ap.add_argument('--key-env', default='OPENROUTER_API_KEY')
    ap.add_argument('--host', choices=['hermes', 'openclaw'], default='hermes')
    a = ap.parse_args(argv)
    if a.host == 'openclaw': return openclaw(a)
    hermes = hermes_bin();tmp = tempfile.mkdtemp(prefix='openape-live-');home = Path(tempfile.mkdtemp(prefix='openape-live-home-'))
    engine = Engine(tmp, 'live-tool-smoke-token-000000000000000', ['live'], scopes=('persona:express', 'persona:admin', 'observations:write', 'feedback:write', 'training:admin', 'reflection:write'))
    relay = RelayModel(a.base_url, a.key_env)
    try:
        engine.post('/v1/personas', {'persona_id': 'live', 'archetype': 'mentor', 'individuality': 0, 'evolution': 'manual'})
        subprocess.run([sys.executable, '-m', 'sdk.cli.main', 'adapter', 'install', 'hermes'], cwd=ROOT, env={**os.environ, 'OPENAPE_TOKEN': engine.token, 'OPENAPE_URL': engine.url, 'HERMES_HOME': str(home)}, check=True, capture_output=True)
        (home / 'config.yaml').write_text(f'model:\n  default: {a.model}\n  provider: custom\n  base_url: {relay.url}/v1\nplugins:\n  enabled: [openape]\n')
        def run(prompt, resume=None):
            env = {'PATH': os.environ['PATH'], 'HOME': str(home), 'HERMES_HOME': str(home), 'OPENAI_API_KEY': 'relay-adds-the-real-key', 'NO_PROXY': '127.0.0.1,localhost',
                'HTTPS_PROXY': os.environ.get('HTTPS_PROXY', ''), 'OPENAPE_TOKEN': engine.token, 'OPENAPE_PERSONA': 'live', 'OPENAPE_URL': engine.url, 'OPENAPE_MODE': 'active'}
            before = len(relay.model_requests())
            r = subprocess.run([hermes, 'chat', '-Q', '-q', prompt] + (['--resume', resume] if resume else []), cwd=tmp, env=env, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
            session = next((l.split(':', 1)[1].strip() for l in (r.stdout + r.stderr).splitlines() if l.strip().startswith('session_id:')), None)
            return dict(code=r.returncode, out=r.stdout, session=session, requests=relay.model_requests()[before:])
        decisions = lambda: [json.loads(r['data'])['response'] for r in engine.rows("SELECT data FROM decisions ORDER BY rowid")]
        report = dict(host='Hermes Agent', host_version=HERMES_VERSION, model=a.model, provider=a.base_url, kind='live model; a few turns, not a benchmark', checks={}, observed={})
        c, o = report['checks'], report['observed']
        first = run(PREFERENCE)
        reqs = first['requests'];tools = sorted({t.get('function', {}).get('name', '') for r in reqs for t in r['body'].get('tools') or []})
        c['turn_completes'] = first['code'] == 0 and bool(first['out'].strip())
        c['provider_calls_succeed'] = bool(reqs) and all(r['status'] == 200 for r in reqs)
        c['style_reached_provider'] = bool(reqs) and count_marker(reqs[0]['body']) == 1
        c['persona_feedback_offered'] = 'persona_feedback' in tools
        called = [r for r in reqs if 'persona_feedback' in r['reply']]
        reflections = [json.loads(r['data']) for r in engine.rows("SELECT data FROM feedback ORDER BY rowid") if json.loads(r['data'])['source'] == 'agent_reflection']
        o['model_called_persona_feedback'] = bool(called);o['reflections_recorded'] = len(reflections)
        o['reflection_moves'] = [dict(preferred=f['preferred'], rejected=f['rejected']) for f in reflections]
        audit = [json.loads(r['data']) for r in engine.rows("SELECT data FROM audit WHERE action='reflection_recorded' ORDER BY seq")]
        o['reflection_audit'] = [dict(reason=x['reason'], adjustments=x['adjustments'], habits=x['habits']) for x in audit]
        o['tool_results'] = tool_results(reqs)
        before = decisions()[0]
        second = run('And what is a Python generator?', resume=first['session'])
        c['second_turn_completes'] = second['code'] == 0 and bool(second['out'].strip())
        after = decisions()[-1]
        o['style_before'] = dict(controls=before['controls'], habits=before['habits']);o['style_after'] = dict(controls=after['controls'], habits=after['habits'])
        o['note'] = ('Each `hermes chat -q` process ends its session on exit, so the engine discards the session state and the resumed '
            'run starts a new engine session: the reflection is evidence for later learning, not for this second run. The in-session '
            'effect is covered by tests/test_habits.py and the session-state tests.')
        o['requested_moves_only'] = all(set(x['adjustments']) <= {'verbosity'} and set(x['habits']) <= {'next_step'} for x in o['reflection_audit'])
        o['reply_chars'] = [len(first['out']), len(second['out'])]
        o['decisions'] = [dict(session=json.loads(r['data'])['session']['id'][:12], session_state=json.loads(r['data'])['session_state'], verbosity=json.loads(r['data'])['response']['controls']['verbosity'],
            tags=json.loads(r['data'])['context']['tags']) for r in engine.rows('SELECT data FROM decisions ORDER BY rowid')]
        dump = json.dumps(report) + ''.join(p.read_text(errors='replace') for p in Path(tmp).rglob('*.log'))
        c['key_not_recorded'] = os.environ[a.key_env] not in dump and os.environ[a.key_env] not in json.dumps(engine.rows('SELECT data FROM decisions'))
        report['status'] = 'PASS' if all(c.values()) else 'FAIL'
        write_report('live-tool-smoke', report)
        if report['status'] != 'PASS': raise SystemExit(1)
    finally:
        engine.close();relay.close();shutil.rmtree(home, ignore_errors=True)

def openclaw(a):
    """The same check with OpenClaw (`openclaw agent --local`), whose plugin tools are listed
    in its Tool Search directory, so the model must find persona_feedback itself."""
    from scripts.openclaw_host_smoke import environment, OPENCLAW_VERSION
    path, binary = environment();tmp = tempfile.mkdtemp(prefix='openape-live-oc-');home = Path(tempfile.mkdtemp(prefix='openape-live-oc-home-'))
    engine = Engine(tmp, 'live-tool-smoke-token-000000000000000', ['live'], scopes=('persona:express', 'persona:admin', 'observations:write', 'feedback:write', 'training:admin', 'reflection:write'))
    relay = RelayModel(a.base_url, a.key_env)
    try:
        engine.post('/v1/personas', {'persona_id': 'live', 'archetype': 'mentor', 'individuality': 0, 'evolution': 'manual'})
        config = {'models': {'mode': 'merge', 'providers': {'relay': {'baseUrl': relay.url + '/v1', 'apiKey': 'relay-adds-the-real-key', 'api': 'openai-completions',
                'models': [{'id': a.model, 'name': a.model, 'reasoning': False, 'input': ['text'], 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}, 'contextWindow': 100000, 'maxTokens': 4000}]}}},
            'agents': {'defaults': {'model': {'primary': 'relay/' + a.model}}},
            'plugins': {'allow': ['openape'], 'load': {'paths': [str(ROOT / 'adapters/openclaw')]}, 'entries': {'openape': {'enabled': True, 'hooks': {'allowPromptInjection': True, 'allowConversationAccess': True}}}}}
        (home / '.openclaw').mkdir();(home / '.openclaw/openclaw.json').write_text(json.dumps(config))
        def run(prompt, session):
            env = {'PATH': path, 'HOME': str(home), 'OPENCLAW_HOME': str(home), 'NO_PROXY': '127.0.0.1,localhost', 'OPENAPE_TOKEN': engine.token, 'OPENAPE_PERSONA': 'live', 'OPENAPE_URL': engine.url, 'OPENAPE_MODE': 'active'}
            before = len(relay.model_requests())
            r = subprocess.run([binary, 'agent', '--local', '--message', prompt, '--session-id', session, '--json'], cwd=tmp, env=env, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
            return dict(code=r.returncode, out=r.stdout, requests=relay.model_requests()[before:])
        report = dict(host='OpenClaw', host_version=OPENCLAW_VERSION, model=a.model, provider=a.base_url, kind='live model; a few turns, not a benchmark', checks={}, observed={})
        c, o = report['checks'], report['observed']
        first = run(PREFERENCE, 'live-1');reqs = first['requests']
        c['turn_completes'] = first['code'] == 0 and bool(first['out'].strip())
        c['provider_calls_succeed'] = bool(reqs) and all(r['status'] == 200 for r in reqs)
        c['style_reached_provider'] = bool(reqs) and count_marker(reqs[0]['body']) >= 1
        c['persona_feedback_discoverable'] = bool(reqs) and 'persona_feedback' in json.dumps(reqs[0]['body'])
        o['model_called_persona_feedback'] = any('persona_feedback' in r['reply'] for r in reqs)
        audit = [json.loads(r['data']) for r in engine.rows("SELECT data FROM audit WHERE action='reflection_recorded' ORDER BY seq")]
        o['reflections_recorded'] = len(audit);o['reflection_audit'] = [dict(reason=x['reason'], adjustments=x['adjustments'], habits=x['habits']) for x in audit]
        o['requested_moves_only'] = all(set(x['adjustments']) <= {'verbosity'} and set(x['habits']) <= {'next_step'} for x in o['reflection_audit'])
        o['tool_results'] = tool_results(reqs)
        second = run('And what is a Python generator?', 'live-1')
        c['second_turn_completes'] = second['code'] == 0 and bool(second['out'].strip())
        rows = [json.loads(r['data']) for r in engine.rows('SELECT data FROM decisions ORDER BY rowid')]
        o['decisions'] = [dict(session_state=d['session_state'], verbosity=d['response']['controls']['verbosity'], habits=d['response']['habits'], tags=d['context']['tags']) for d in rows]
        o['model_requests'] = [len(first['requests']), len(second['requests'])]
        dump = json.dumps(report) + ''.join(p.read_text(errors='replace') for p in Path(tmp).rglob('*.log'))
        c['key_not_recorded'] = os.environ[a.key_env] not in dump
        report['status'] = 'PASS' if all(c.values()) else 'FAIL'
        write_report('live-tool-smoke-openclaw', report)
        if report['status'] != 'PASS': raise SystemExit(1)
    finally:
        engine.close();relay.close();shutil.rmtree(home, ignore_errors=True)

if __name__ == '__main__': main()
