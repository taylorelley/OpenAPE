#!/usr/bin/env python3
"""OpenAPE Claude Code plugin hook (all lifecycle events). Python stdlib only.

Fail-open: always exits 0; on any failure it prints nothing. Never reads the
transcript, prompt text, CLAUDE.md or AGENTS.md. Only UserPromptSubmit emits
`hookSpecificOutput.additionalContext`; every other event is a best-effort
observation carrying IDs and status only.
"""
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import upap_lite  # noqa: E402  (vendored, byte-identical to sdk/python/lite.py)

ADAPTER = 'upap.claude-code'
VERSION = '0.2.0'

def stable(value): return hashlib.sha256(value.encode()).hexdigest()[:48]
def safe_id(value, default): return (re.sub(r'[^A-Za-z0-9_.:-]', '-', value or '')[:100]) or default

def config():
    token, persona = os.environ.get('OPENAPE_TOKEN'), os.environ.get('OPENAPE_PERSONA')
    if not token or not persona: return None
    return dict(token=token, persona=persona, url=os.environ.get('OPENAPE_URL', 'http://127.0.0.1:8765'), tenant=os.environ.get('OPENAPE_TENANT', 'local'),
        user=os.environ.get('OPENAPE_LINKED_USER'), mode=os.environ.get('OPENAPE_MODE', 'shadow'), host_version=safe_id(os.environ.get('OPENAPE_HOST_VERSION'), 'unverified'))

def state_path(session_key):
    root = Path(os.environ.get('CLAUDE_PLUGIN_DATA') or Path.home() / '.openape' / 'claude-code-state')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / f'{session_key}.json'

def load(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}

def save(path, state):
    tmp = path.with_suffix(f'.{os.getpid()}.tmp'); tmp.write_text(json.dumps(state)); os.replace(tmp, path)

def event(cfg, session_key, kind, status='ok', decision_id=None):
    e = dict(event_id=str(uuid.uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(), persona_id=cfg['persona'], session_id=session_key, type=kind, status=status)
    if cfg['user']: e['user_id'] = cfg['user']
    if decision_id: e['decision_id'] = decision_id
    return e

def main():
    data = json.load(sys.stdin)
    cfg = config(); name = data.get('hook_event_name'); session = data.get('session_id')
    if not cfg or not session or cfg['mode'] == 'disabled': return
    # Subagents opt out by default: no injection into child contexts and no learning
    # signal attributed to the parent. Bind a separately scoped child persona instead.
    if data.get('agent_id'): return
    key = stable(f'claude-code:{session}:{cfg["persona"]}'); path = state_path(key); state = load(path)
    observe = lambda *events: upap_lite.observe(cfg['url'], cfg['token'], ADAPTER, list(events))
    if name == 'SessionStart':
        if data.get('model'): state['model'] = safe_id(data['model'], 'host-selected')
        save(path, state)
        observe(event(cfg, key, 'session.compacted' if data.get('source') == 'compact' else 'session.started'))
    elif name == 'UserPromptSubmit':
        prompt_id = data.get('prompt_id') or str(uuid.uuid4())
        if state.get('prompt_id') == prompt_id: return  # never inject twice for one prompt
        request = dict(request_id=stable(f'{key}:{prompt_id}'), identity=dict(tenant_id=cfg['tenant'], persona_id=cfg['persona']),
            session=dict(id=key, turn_id=stable(prompt_id)),
            host=dict(adapter_id=ADAPTER, adapter_version=VERSION, host_version=cfg['host_version'], provider_family='anthropic', model_id=state.get('model', 'host-selected')),
            context=dict(task_type='general', channel='terminal', stakes='medium', turn_origin='user', tags=[]))
        if cfg['user']: request['identity']['user_id'] = cfg['user']
        result = upap_lite.express(cfg['url'], cfg['token'], request, cfg['mode'])
        state.update(prompt_id=prompt_id, decision_id=(result['decision'] or {}).get('decision_id'), applied=bool(result['text'])); save(path, state)
        if result['text']:
            # Context tier wording: a factual statement of user-configured preferences.
            text = 'OpenAPE persona style preferences configured by the user for this session. ' + result['text']
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}))
    elif name in ('Stop', 'StopFailure'):
        if data.get('stop_hook_active') or not state.get('decision_id'): return
        observe(event(cfg, key, 'turn.completed' if name == 'Stop' else 'turn.failed', 'ok' if name == 'Stop' else 'failed', state['decision_id']))
    elif name == 'PostCompact':
        observe(event(cfg, key, 'session.compacted'))
    elif name == 'PostModelSwitch':
        state['model'] = safe_id(data.get('to_model'), 'host-selected'); save(path, state)
        observe(event(cfg, key, 'model.changed'))  # persona identity is unchanged by provider switches
    elif name == 'SessionEnd':
        observe(event(cfg, key, 'session.ended'))
        path.unlink(missing_ok=True)

if __name__ == '__main__':
    try: main()
    except Exception: pass
    sys.exit(0)
