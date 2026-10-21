"""Native coexistence plugin; never reads, rewrites or overrides SOUL.md."""
import hashlib
import uuid
from datetime import datetime, timezone
from sdk.python.client import Client

def stable(value):return hashlib.sha256(value.encode()).hexdigest()[:48]
def register(ctx):
    if not callable(getattr(ctx,'register_hook',None)):raise RuntimeError('Hermes hooks unavailable')
    def settings():
        # Resolve secrets in the owning profile on EVERY call. Never cache across
        # Hermes profiles, inspect global environment, or infer linked users.
        from agent.secret_scope import get_secret
        token=get_secret('OPENAPE_TOKEN')
        persona=ctx.get_config('persona')
        if not token or not persona:return None
        return dict(token=token,persona=persona,url=ctx.get_config('url','http://127.0.0.1:8765'),tenant=ctx.get_config('tenant','local'),user=ctx.get_config('linked_user'),mode=ctx.get_config('mode','shadow'))
    def prepare(session_id='',turn_id='',model='',parent_session_id='',**kwargs):
        if parent_session_id or not session_id:return None
        cfg=settings()
        if not cfg:return None
        req=dict(request_id=stable(session_id+':'+(turn_id or str(uuid.uuid4()))),identity=dict(tenant_id=cfg['tenant'],persona_id=cfg['persona']),session=dict(id=stable('hermes:'+session_id+':'+cfg['persona']),turn_id=stable(turn_id or str(uuid.uuid4()))),host=dict(adapter_id='upap.hermes',adapter_version='0.1.0',host_version='3fa571a51a6bf1220dfe9a7a23fcd5bb9482a1af',provider_family='other',model_id=stable(model)),context=dict(task_type='general',channel='terminal',stakes='medium',turn_origin='user',tags=[]))
        if cfg['user']:req['identity']['user_id']=cfg['user']
        with_client=Client(cfg['url'],cfg['token'])
        try:
            out=with_client.express(req,cfg['mode'])
            if out['text']:return {'context':out['text']}
        finally:with_client.close()
    def ended(session_id='',completed=False,interrupted=False,**kwargs):
        cfg=settings()
        if not cfg or cfg['mode']=='disabled' or not session_id:return
        client=Client(cfg['url'],cfg['token'])
        try:
            event=dict(event_id=str(uuid.uuid4()),occurred_at=datetime.now(timezone.utc).isoformat(),persona_id=cfg['persona'],session_id=stable('hermes:'+session_id+':'+cfg['persona']),type='session.ended',status='aborted' if interrupted else ('ok' if completed else 'failed'))
            if cfg['user']:event['user_id']=cfg['user']
            client.request('POST','/v1/observations',dict(adapter_id='upap.hermes',events=[event]))
        except Exception:pass
        finally:client.close()
    ctx.register_hook('pre_llm_call',prepare)
    ctx.register_hook('on_session_end',ended)
