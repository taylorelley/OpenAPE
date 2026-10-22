"""OpenAPE Hermes plugin (coexistence mode). Verified against hermes-agent 0.19.0.

* `pre_llm_call` returns `{"context": ...}`; Hermes appends it to the API copy of
  the current user message only (not the cached system prompt, not the stored
  transcript). SOUL.md stays Hermes's identity slot and is never read or changed
  here; see `openape adapter migrate-soul` for the explicit, backed-up migration.
* `post_llm_call` / `on_session_end` send ID-and-status observations only.
* Subagent sessions (announced by `subagent_start`) opt out by default.
* Settings resolve per call through Hermes's profile-scoped `get_secret`, so one
  Hermes profile can never use another profile's token or persona.
Stdlib only (vendored `upap_lite`), so it runs in Hermes's own interpreter.
"""
import hashlib
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import upap_lite  # noqa: E402  (vendored, byte-identical to sdk/python/lite.py)

ADAPTER = 'upap.hermes'
VERSION = '0.2.0'
HOST_VERSION = '0.19.0'

def stable(value): return hashlib.sha256(value.encode()).hexdigest()[:48]

def settings():
    try:
        from agent.secret_scope import get_secret
    except ImportError:  # older Hermes: plain environment
        import os; get_secret = lambda name, default=None: os.environ.get(name, default)
    token, persona = get_secret('OPENAPE_TOKEN'), get_secret('OPENAPE_PERSONA')
    if not token or not persona: return None
    return dict(token=token, persona=persona, url=get_secret('OPENAPE_URL') or 'http://127.0.0.1:8765', tenant=get_secret('OPENAPE_TENANT') or 'local',
        user=get_secret('OPENAPE_LINKED_USER'), mode=get_secret('OPENAPE_MODE') or 'shadow')

def register(ctx):
    if not callable(getattr(ctx, 'register_hook', None)): raise RuntimeError('Hermes hooks unavailable')
    decisions = OrderedDict(); children = OrderedDict()
    def remember(store, key, value):
        store[key] = value; store.move_to_end(key)
        while len(store) > 256: store.popitem(last=False)
    def session_key(cfg, session_id): return stable(f'hermes:{session_id}:{cfg["persona"]}')
    def event(cfg, session_id, kind, status='ok', decision_id=None):
        e = dict(event_id=str(uuid.uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(), persona_id=cfg['persona'], session_id=session_key(cfg, session_id), type=kind, status=status)
        if cfg['user']: e['user_id'] = cfg['user']
        if decision_id: e['decision_id'] = decision_id
        return e
    def subagent_start(child_session_id=None, **_):
        if child_session_id: remember(children, child_session_id, True)
    def prepare(session_id='', turn_id='', model='', **_):
        if not session_id or session_id in children: return None
        cfg = settings()
        if not cfg or cfg['mode'] == 'disabled': return None
        turn = turn_id or str(uuid.uuid4())
        request = dict(request_id=stable(f'{session_id}:{turn}'), identity=dict(tenant_id=cfg['tenant'], persona_id=cfg['persona']),
            session=dict(id=session_key(cfg, session_id), turn_id=stable(turn)),
            host=dict(adapter_id=ADAPTER, adapter_version=VERSION, host_version=HOST_VERSION, provider_family='other', model_id=stable(model or 'unspecified')),
            context=dict(task_type='general', channel='terminal', stakes='medium', turn_origin='user', tags=[]))
        if cfg['user']: request['identity']['user_id'] = cfg['user']
        out = upap_lite.express(cfg['url'], cfg['token'], request, cfg['mode'])
        if out['decision']: remember(decisions, session_id, out['decision']['decision_id'])
        return {'context': out['text']} if out['text'] else None
    def completed(session_id='', **_):
        cfg = settings(); decision = decisions.get(session_id)
        if cfg and decision and cfg['mode'] != 'disabled':
            upap_lite.observe(cfg['url'], cfg['token'], ADAPTER, [event(cfg, session_id, 'turn.completed', decision_id=decision)])
    def ended(session_id='', completed=False, interrupted=False, **_):
        cfg = settings()
        if not cfg or cfg['mode'] == 'disabled' or not session_id or session_id in children: return
        upap_lite.observe(cfg['url'], cfg['token'], ADAPTER, [event(cfg, session_id, 'session.ended', 'aborted' if interrupted else ('ok' if completed else 'failed'))])
    ctx.register_hook('subagent_start', subagent_start)
    ctx.register_hook('pre_llm_call', prepare)
    ctx.register_hook('post_llm_call', completed)
    ctx.register_hook('on_session_end', ended)
