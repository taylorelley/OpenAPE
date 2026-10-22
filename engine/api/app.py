"""OpenAPE UPAP/1 API. Run with `openape serve`, not a permissive default app."""
import hashlib
import json
import os
import time
import uuid
import threading
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import torch
from fastapi import FastAPI, Depends, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from engine.api.contracts import *
from engine.security.auth import Auth, Principal
from engine.storage.store import Store
from engine.neural.policy import Decoder, CATALOGUE, ACTIONS, CORE_DIM, REL_DIM, mask_reason
from engine.neural.profiles import fit_seed_latent, seed_profile, ARCHETYPES
from engine.learning.trainer import fit_candidate
from engine.learning import maturation
from engine.learning.reflection import adjusted_control
from engine.evaluation.policy import group_split, evaluate_candidate, evaluate_maturation, policy_for

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_DECODER=ROOT/'models/decoder-v2/decoder.safetensors'
def uid(): return str(uuid.uuid4())
def wire(**kwargs): return {'protocol_version':'upap/1',**kwargs}
class Fault(Exception):
    def __init__(self,code,message,status=400,retryable=False): self.code,self.message,self.status,self.retryable=code,message,status,retryable
VERSION_COLUMNS='(tenant,persona,id,hash,parent,scope,user_id,job,core_base)'
# Automatic learning waits for this many new usable examples since its last attempt.
AUTO_EVIDENCE_STEP={'relationship':4,'core':8}
REFLECTIONS_PER_SESSION=3
AUTO_ACTOR='openape:auto-evolution'; MATURATION_ACTOR='openape:maturation'
def system_principal(tenant,persona_id,actor):
    """Engine-internal identity for automatic evolution of one persona."""
    return Principal(tenant,actor,frozenset({'training:admin'}),(persona_id,),('*',))
def short_id(value): return value if len(value)<=100 else hashlib.sha256(value.encode()).hexdigest()

def create_app(data_dir=None,credentials=None,decoder_path=None,rate_limit_per_minute=600):
    auth=Auth(credentials); store=Store(data_dir or os.environ.get('OPENAPE_DATA','.openape'))
    decoder_location=decoder_path or os.environ.get('OPENAPE_DECODER',str(DEFAULT_DECODER))
    try:decoder=Decoder(decoder_location)
    except (ValueError,OSError,RuntimeError,KeyError):decoder=Decoder('/nonexistent-openape-approved-fallback')
    engine_status='experimental_synthetic' if decoder.model else 'baseline_fallback'
    app=FastAPI(title='OpenAPE — Agent Personality Engine',version='0.2.0')
    app.state.store=store; app.state.decoder=decoder
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='openape-training')
    def drain():
        """Wait until no training/evolution job is queued (single worker; for tests and tools)."""
        while True:
            pool.submit(lambda:None).result()
            if not store.one("SELECT 1 FROM jobs WHERE status='queued'"):return
    app.state.drain=drain
    pending=threading.BoundedSemaphore(4)
    limits=defaultdict(deque); limit_lock=threading.Lock()
    @asynccontextmanager
    async def lifespan(_app):
        yield
        pool.shutdown(wait=True); store.db.close()
    app.router.lifespan_context=lifespan
    @app.exception_handler(Fault)
    async def fault(request,exc):
        return JSONResponse(status_code=exc.status,content=wire(error=dict(code=exc.code,message=exc.message,retryable=exc.retryable,request_id=getattr(request.state,'request_id',None))))
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        code='UNSUPPORTED_PROTOCOL' if any('protocol_version' in e['loc'] for e in exc.errors()) else 'INVALID_CONTEXT'
        return JSONResponse(status_code=422,content=wire(error=dict(code=code,message='Request does not conform to UPAP/1',retryable=False,request_id=getattr(request.state,'request_id',None))))
    @app.middleware('http')
    async def bounds(request,call_next):
        request.state.request_id=uid()
        if request.method in ('POST','PUT','PATCH'):
            body=b''
            async for chunk in request.stream():
                body+=chunk
                if len(body)>65536: return JSONResponse(status_code=413,content=wire(error={'code':'INVALID_CONTEXT','message':'Payload exceeds 65536 bytes','retryable':False,'request_id':request.state.request_id}))
            request._body=body
            try:
                data=json.loads(body)
                if data.get('protocol_version')!='upap/1':
                    return JSONResponse(status_code=422,content=wire(error={'code':'UNSUPPORTED_PROTOCOL','message':'Explicit upap/1 required','retryable':False,'request_id':request.state.request_id}))
            except (ValueError,AttributeError):
                return JSONResponse(status_code=422,content=wire(error={'code':'INVALID_CONTEXT','message':'Expected JSON object','retryable':False,'request_id':request.state.request_id}))
        return await call_next(request)
    def principal(request:Request):
        h=request.headers.get('authorization','')
        p=auth.verify(h[7:]) if h.startswith('Bearer ') else None
        if not p: raise Fault('UNAUTHORIZED','Bearer credentials required',401)
        with limit_lock:
            q=limits[(p.tenant,p.actor)]; now=time.monotonic()
            while q and now-q[0]>60:q.popleft()
            if len(q)>=rate_limit_per_minute: raise Fault('RATE_LIMITED',f'{rate_limit_per_minute} requests per actor per minute',429,True)
            q.append(now)
        return p
    def scope(p,s,persona=None,user=None):
        if s not in p.scopes or (persona is not None and not p.allows(persona,user)): raise Fault('FORBIDDEN_SCOPE','Credential does not permit this operation',403)
    def persona(p,id):
        row=store.one('SELECT * FROM personas WHERE tenant=? AND id=?',(p.tenant,id))
        if not row: raise Fault('PERSONA_NOT_FOUND','Persona not found',404)
        return row
    def version(p,id,v):
        row=store.one('SELECT * FROM versions WHERE tenant=? AND persona=? AND id=? AND revoked=0',(p.tenant,id,v))
        if not row: raise Fault('VERSION_CONFLICT','Version does not exist or was revoked',409)
        return row
    def latent(p,id,v,dim): return store.get(version(p,id,v)['hash'],dim)
    @app.get('/health/live')
    def live(): return wire(status='live')
    @app.get('/health/ready')
    def ready(): return wire(status='ready',engine_status=engine_status)
    @app.get('/v1/capabilities')
    def capabilities(p=Depends(principal)):
        return wire(protocol_versions=['upap/1'],control_schema='behaviour-controls/1',controls=len(CATALOGUE),encoder=decoder.meta.get('encoder'),decoder_hash=decoder.hash,engine_status=engine_status,
            max_payload_bytes=65536,modes=['disabled','shadow','active','frozen'],initializations=['archetype','seed_preferences','snapshot','imported','neutral_prior'],
            archetypes={k:list(v) for k,v in ARCHETYPES.items()},maturation_rates={k:dict(relationship_horizon=v[0],core_horizon=v[1]) for k,v in maturation.RATES.items()},
            features=['pairwise_learning','logged_bandit_learning','independent_evaluator','cas_promotion','rollback','lineage_revocation','core_export','subagent_snapshot','automatic_evolution','maturation','agent_reflection'],
            session_state='zero ephemeral; no checkpoints',automatic_promotion='persona_policy')
    def insert_persona(db,p,id,artifact,initialization,parent=None,archetype=None,seeds=(),evolution='manual',rate=None,agent_feedback=False):
        if db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(p.tenant,id)).fetchone():raise Fault('VERSION_CONFLICT','Persona already exists',409)
        v=uid()
        db.execute('INSERT INTO personas(tenant,id,active,initialization,parent,archetype,seeds,evolution,maturation,agent_feedback) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (p.tenant,id,v,initialization,parent,archetype,json.dumps(sorted(seeds)),evolution,json.dumps(maturation.horizons(rate)),int(agent_feedback)))
        db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,artifact,None,'core',None,None,None))
        return v
    @app.post('/v1/personas')
    def create(req:Create,p=Depends(principal)):
        scope(p,'persona:admin',req.persona_id)
        chosen=[x for x in (req.archetype,req.seed_preferences,req.parent_persona_id) if x]
        if len(chosen)>1:raise Fault('INVALID_CONTEXT','Choose one of archetype, seed preferences or a snapshot parent')
        if not chosen:raise Fault('INVALID_CONTEXT','Choose a starting archetype ('+', '.join(ARCHETYPES)+'), seed preferences or a snapshot parent')
        parent=None; archetype=req.archetype
        if req.parent_persona_id:
            # Subagent semantics: a new scoped identity holding an immutable copy of the
            # parent's approved core version. No mutable weights are shared.
            scope(p,'persona:admin',req.parent_persona_id); src=persona(p,req.parent_persona_id)
            x=latent(p,req.parent_persona_id,src['active'],CORE_DIM); initialization='snapshot'; parent=f"{req.parent_persona_id}@{src['active']}"
            archetype=src['archetype']; seeds=json.loads(src['seeds'] or '[]')
        else:
            seeds=list(ARCHETYPES[archetype]) if archetype else req.seed_preferences
            try:x=fit_seed_latent(decoder,seeds)
            except ValueError as exc:raise Fault('INVALID_CONTEXT',str(exc))
            initialization='archetype' if archetype else 'seed_preferences'
        rate=req.maturation_rate.model_dump() if isinstance(req.maturation_rate,BaseModel) else req.maturation_rate or os.environ.get('OPENAPE_MATURATION_RATE')
        h=store.put(x)
        with store.tx() as db:
            v=insert_persona(db,p,req.persona_id,h,initialization,parent,archetype,seeds,req.evolution,rate,req.agent_feedback)
            store.audit(db,p.tenant,req.persona_id,'created',{'actor':p.actor,'initialization':initialization,'archetype':archetype,'seed_preferences':req.seed_preferences,'parent':parent,
                'evolution':req.evolution,'maturation_rate':maturation.public_rate(maturation.horizons(rate)),'agent_feedback':req.agent_feedback})
        return wire(persona_id=req.persona_id,active_version=v,initialization=initialization,archetype=archetype,seed_preferences_applied=initialization=='seed_preferences',parent=parent,
            evolution=req.evolution,maturation_rate=maturation.public_rate(maturation.horizons(rate)),agent_feedback=req.agent_feedback)
    @app.get('/v1/personas')
    def list_personas(p=Depends(principal)):
        scope(p,'persona:express')
        rows=store.all('SELECT id,active,initialization,parent FROM personas WHERE tenant=?',(p.tenant,))
        return wire(personas=[dict(r) for r in rows if p.allows(r['id'])])
    @app.get('/v1/personas/{id}')
    def inspect(id:str,user_id:str|None=None,p=Depends(principal)):
        scope(p,'persona:express',id,user_id); r=persona(p,id); hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None)
        def level(user,horizon):
            row=store.one('SELECT experience FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,user))
            t=row['experience'] if row else 0
            return dict(experience=t,horizon=horizon,maturity=round(maturation.maturity(t,horizon),4))
        growth=dict(core=level('',hz['core']))
        if user_id:growth['relationship']=level(user_id,hz['relationship'])
        return wire(persona_id=id,active_version=r['active'],initialization=r['initialization'],archetype=r['archetype'],parent=r['parent'],evolution=r['evolution'],
            maturation_rate=maturation.public_rate(hz),agent_feedback=bool(r['agent_feedback']),growth=growth,decoder_hash=decoder.hash,engine_status=engine_status)
    @app.get('/v1/personas/{id}/history')
    def history(id:str,p=Depends(principal)):
        scope(p,'persona:admin',id); persona(p,id)
        return wire(versions=[dict(r) for r in store.all('SELECT id,hash,parent,scope,user_id,job,revoked FROM versions WHERE tenant=? AND persona=?',(p.tenant,id)) if r['user_id'] is None or p.allows(id,r['user_id'])],audit=[dict(r) for r in store.all('SELECT seq,action,data FROM audit WHERE tenant=? AND persona=?',(p.tenant,id))])
    @app.post('/v1/express',response_model=Decision)
    def express(req:Express,p=Depends(principal)):
        i=req.identity; scope(p,'persona:express',i.persona_id,i.user_id)
        if i.tenant_id!=p.tenant: raise Fault('FORBIDDEN_SCOPE','Tenant mismatch',403)
        if req.selection=='sample' and (not req.exploration_consent or req.seed is None or req.mode=='frozen'):raise Fault('INVALID_CONTEXT','Sampling requires explicit consent, seed and non-frozen mode')
        if req.pinned_version and req.mode!='frozen':raise Fault('INVALID_CONTEXT','pinned_version is only valid in frozen mode')
        if req.debug:scope(p,'training:admin',i.persona_id,i.user_id)
        r=persona(p,i.persona_id); user=i.user_id or ''
        with store.tx() as db:
            fingerprint=hashlib.sha256(req.model_dump_json().encode()).hexdigest()
            existing=db.execute('SELECT decision,fingerprint FROM requests WHERE tenant=? AND persona=? AND actor=? AND id=?',(p.tenant,i.persona_id,p.actor,req.request_id)).fetchone()
            if existing:
                if existing['fingerprint']!=fingerprint:raise Fault('VERSION_CONFLICT','request_id reused with different context',409)
                old=db.execute('SELECT data FROM decisions WHERE tenant=? AND id=?',(p.tenant,existing['decision'])).fetchone()
                return json.loads(old['data'])['response']
            rel=db.execute('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,i.persona_id,user)).fetchone() if user else None
            if req.pinned_version:
                # Frozen evaluation of an explicitly selected immutable core version; no session pin.
                pinned=db.execute('SELECT scope FROM versions WHERE tenant=? AND persona=? AND id=? AND revoked=0',(p.tenant,i.persona_id,req.pinned_version)).fetchone()
                if not pinned or pinned['scope']!='core':raise Fault('VERSION_CONFLICT','Pinned core version not found',409)
                cv,rv=req.pinned_version,(rel['active'] if rel else None)
            else:
                pin=db.execute('SELECT * FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',(p.tenant,i.persona_id,user,req.host.adapter_id,req.session.id)).fetchone()
                cv=pin['version'] if pin else r['active']; rv=pin['rel_version'] if pin else (rel['active'] if rel else None)
                if pin and pin['decoder']!=decoder.hash: raise Fault('DECODER_INCOMPATIBLE','Pinned decoder unavailable; start a new session',409)
                if not pin:db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)',(p.tenant,i.persona_id,user,req.host.adapter_id,req.session.id,cv,rv,decoder.hash))
            status=engine_status; diagnostics=None
            try:
                core=latent(p,i.persona_id,cv,CORE_DIM); relationship=latent(p,i.persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
                with torch.no_grad():
                    logits=decoder.logits(core,relationship,req.context.model_dump(),req.host.model_dump()); probs=torch.softmax(logits,0)
                    action=int(torch.multinomial(probs,1,generator=torch.Generator().manual_seed(req.seed)).item()) if req.selection=='sample' else int(logits.argmax())
                    if req.debug:diagnostics=decoder.diagnostics(core,relationship,req.context.model_dump(),req.host.model_dump())
            except (ValueError,OSError,RuntimeError,KeyError,Fault):
                # Corrupt/missing artifacts fail closed to the approved neutral configuration.
                action=0;probs=torch.zeros(ACTIONS);probs[0]=1;status='baseline_fallback'
            propensity=float(probs[action]) if req.selection=='sample' and status!='baseline_fallback' else None
            response=Decision(request_id=req.request_id,decision_id=uid(),persona_version=cv,relationship_version=rv,decoder_hash=decoder.hash,control_set_id=f'style-{action:02}',controls=Controls(**CATALOGUE[action]),mode=req.mode,policy=Policy(eligible=True,mask_reason=mask_reason(req.context.model_dump())),engine_status=status,
                propensity=propensity if req.debug else None,diagnostics=diagnostics).model_dump()
            data=dict(response=response,context=req.context.model_dump(),host=req.host.model_dump(),session=req.session.model_dump(),fingerprint=fingerprint,action=action,selection=req.selection,propensity=propensity)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?)',(p.tenant,i.persona_id,p.actor,req.request_id,response['decision_id'],fingerprint))
            db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?)',(p.tenant,response['decision_id'],i.persona_id,i.user_id,p.actor,json.dumps(data)))
        return response
    @app.post('/v1/feedback')
    def feedback(req:Feedback,p=Depends(principal)):
        scope(p,'feedback:write')
        if req.actor_id!=p.actor:raise Fault('FORBIDDEN_SCOPE','actor_id must match credential',403)
        if req.source in ('owner','verified_evaluator') and 'training:admin' not in p.scopes:raise Fault('FORBIDDEN_SCOPE','Privileged source requires training administrator',403)
        if req.source=='agent_reflection':raise Fault('FORBIDDEN_SCOPE','Agent reflections are recorded only through /v1/reflections',403)
        if req.consent_scope=='core':scope(p,'training:admin')
        d=store.one('SELECT * FROM decisions WHERE tenant=? AND id=?',(p.tenant,req.decision_id))
        if not d:raise Fault('INVALID_CONTEXT','Unknown decision')
        scope(p,'feedback:write',d['persona'],d['user_id'])
        if d['actor']!=p.actor and 'training:admin' not in p.scopes:raise Fault('FORBIDDEN_SCOPE','Decision actor mismatch',403)
        if req.consent_scope=='relationship' and not d['user_id']:raise Fault('INVALID_CONTEXT','Relationship feedback requires linked user')
        if req.kind=='rating' and req.value is None:raise Fault('INVALID_CONTEXT','Rating requires value')
        if req.kind!='rating' and (req.preferred_control is None or req.rejected_control is None or req.preferred_control==req.rejected_control):raise Fault('INVALID_CONTEXT','Distinct preference options required')
        if req.occurred_at:
            try:
                stamp=datetime.fromisoformat(req.occurred_at.replace('Z','+00:00'))
                if stamp.utcoffset() is None or stamp.utcoffset().total_seconds()!=0:raise ValueError()
            except ValueError:raise Fault('INVALID_CONTEXT','occurred_at must be a UTC ISO-8601 timestamp')
        raw=req.model_dump_json()
        with store.tx() as db:
            old=db.execute('SELECT data FROM feedback WHERE tenant=? AND id=?',(p.tenant,req.feedback_id)).fetchone()
            if old and old['data']!=raw:raise Fault('VERSION_CONFLICT','Feedback id reused',409)
            if not old:
                db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(p.tenant,req.feedback_id,d['persona'],d['user_id'],p.actor,raw))
                store.audit(db,p.tenant,d['persona'],'feedback_recorded',{'feedback_id':req.feedback_id,'actor':p.actor,'source':req.source,'kind':req.kind,'consent_scope':req.consent_scope,'learning_consent':req.learning_consent,'received_at':datetime.now(timezone.utc).isoformat()})
        learning=req.learning_consent and req.consent_scope not in ('record_only','session')
        if learning and not old:maybe_learn(p.tenant,d['persona'],req.consent_scope,d['user_id'] if req.consent_scope=='relationship' else None)
        return wire(feedback_id=req.feedback_id,deduplicated=bool(old),learning_recorded=learning)
    def invalidate(db,p,persona_id,feedback_id):
        """Lineage-based revocation: only candidates and versions derived from the
        revoked evidence (and their descendants) are invalidated."""
        db.execute('UPDATE feedback SET valid=0 WHERE tenant=? AND persona=? AND id=?',(p.tenant,persona_id,feedback_id))
        jobs={row['id']:json.loads(row['data']) for row in db.execute('SELECT id,data FROM jobs WHERE tenant=? AND persona=?',(p.tenant,persona_id))}
        tainted_jobs={j for j,data in jobs.items() if feedback_id in data.get('evidence_ids',[])}
        versions=[dict(r) for r in db.execute('SELECT * FROM versions WHERE tenant=? AND persona=?',(p.tenant,persona_id))]
        tainted={v['id'] for v in versions if v['job'] in tainted_jobs}
        changed=True
        while changed:
            changed=False
            for v in versions:
                if v['id'] not in tainted and (v['parent'] in tainted or v['core_base'] in tainted):tainted.add(v['id']);changed=True
        for j,data in jobs.items():
            if j in tainted_jobs or data.get('base_version') in tainted or data.get('base_relationship_version') in tainted:
                data.update(eligible=False,invalidated_by=feedback_id);data.pop('artifact',None)
                db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('invalidated',json.dumps(data),p.tenant,j))
        by_id={v['id']:v for v in versions}
        def clean_ancestor(v):
            while v and v in tainted:v=by_id[v]['parent'] if v in by_id else None
            return v
        reset=[]
        if tainted:
            q=','.join('?'*len(tainted))
            db.execute(f'UPDATE versions SET revoked=1 WHERE tenant=? AND persona=? AND id IN ({q})',(p.tenant,persona_id,*tainted))
            active=db.execute('SELECT active FROM personas WHERE tenant=? AND id=?',(p.tenant,persona_id)).fetchone()['active']
            if active in tainted:
                db.execute('UPDATE personas SET active=? WHERE tenant=? AND id=?',(clean_ancestor(active),p.tenant,persona_id));reset.append('core')
            for rel in db.execute('SELECT user_id,active FROM relationships WHERE tenant=? AND persona=?',(p.tenant,persona_id)).fetchall():
                if rel['active'] in tainted:
                    ancestor=clean_ancestor(rel['active'])
                    if ancestor:db.execute('UPDATE relationships SET active=? WHERE tenant=? AND persona=? AND user_id=?',(ancestor,p.tenant,persona_id,rel['user_id']))
                    else:db.execute('DELETE FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,persona_id,rel['user_id']))
                    reset.append('relationship')
            db.execute(f'DELETE FROM sessions WHERE tenant=? AND persona=? AND (version IN ({q}) OR rel_version IN ({q}))',(p.tenant,persona_id,*tainted,*tainted))
        store.audit(db,p.tenant,persona_id,'evidence_revoked',{'feedback_id':feedback_id,'invalidated_candidates':sorted(tainted_jobs),'revoked_versions':sorted(tainted),'reset':sorted(set(reset)),'rederive':'re-run consolidation on remaining valid evidence'})
        store.gc()
    @app.post('/v1/observations')
    def observations(req:Observations,p=Depends(principal)):
        scope(p,'observations:write'); inserted=0; due=set()
        with store.tx() as db:
            for e in req.events:
                scope(p,'observations:write',e.persona_id,e.user_id); persona(p,e.persona_id)
                try:
                    stamp=datetime.fromisoformat(e.occurred_at.replace('Z','+00:00'))
                    if stamp.utcoffset() is None or stamp.utcoffset().total_seconds()!=0 or abs((datetime.now(timezone.utc)-stamp).total_seconds())>86400*7:raise ValueError()
                except ValueError:raise Fault('INVALID_CONTEXT','Event must have UTC timestamp within seven days')
                if e.decision_id:
                    d=db.execute('SELECT persona,user_id FROM decisions WHERE tenant=? AND id=?',(p.tenant,e.decision_id)).fetchone()
                    if not d or d['persona']!=e.persona_id or d['user_id']!=e.user_id:raise Fault('FORBIDDEN_SCOPE','Decision event binding mismatch',403)
                raw=e.model_dump_json()
                old=db.execute('SELECT data FROM observations WHERE tenant=? AND adapter=? AND id=?',(p.tenant,req.adapter_id,e.event_id)).fetchone()
                if old:
                    if old['data']!=raw:raise Fault('VERSION_CONFLICT','Event id reused',409)
                    continue
                if e.type=='experience.corrected':
                    f=db.execute('SELECT * FROM feedback WHERE tenant=? AND id=?',(p.tenant,e.feedback_id)).fetchone()
                    if not f or f['persona']!=e.persona_id or (f['actor']!=p.actor and 'training:admin' not in p.scopes):raise Fault('FORBIDDEN_SCOPE','Cannot revoke evidence',403)
                    invalidate(db,p,e.persona_id,e.feedback_id)
                if e.type=='session.ended':
                    db.execute('DELETE FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',(p.tenant,e.persona_id,e.user_id or '',req.adapter_id,e.session_id))
                    if e.session_id:due.update(record_experience(db,p.tenant,e.persona_id,e.user_id,req.adapter_id,e.session_id))
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',(p.tenant,req.adapter_id,e.event_id,e.persona_id,raw));inserted+=1
        for persona_id,scope_name,user in sorted(due,key=str):submit_auto(p.tenant,persona_id,'maturation',scope_name,user,mature)
        return wire(inserted=inserted,deduplicated=len(req.events)-inserted)
    def record_experience(db,tenant,persona_id,user_id,adapter,session):
        """Count an ended session that received an active decision as experience
        (core, and the linked user's relationship). Returns maturation steps now due."""
        served=db.execute("""SELECT 1 FROM decisions WHERE tenant=? AND persona=? AND user_id IS ? AND json_extract(data,'$.session.id')=? AND json_extract(data,'$.host.adapter_id')=?
            AND json_extract(data,'$.response.mode')='active' AND json_extract(data,'$.response.engine_status')!='baseline_fallback' LIMIT 1""",(tenant,persona_id,user_id,session,adapter)).fetchone()
        if not served:return set()
        r=db.execute('SELECT evolution,maturation FROM personas WHERE tenant=? AND id=?',(tenant,persona_id)).fetchone(); hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None); due=set()
        for user,scope_name in (('','core'),)+(((user_id,'relationship'),) if user_id else ()):
            if db.execute('INSERT OR IGNORE INTO experience VALUES(?,?,?,?,?)',(tenant,persona_id,user,adapter,session)).rowcount==0:continue
            db.execute('INSERT OR IGNORE INTO maturation(tenant,persona,user_id) VALUES(?,?,?)',(tenant,persona_id,user))
            db.execute('UPDATE maturation SET experience=experience+1 WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user))
            row=db.execute('SELECT experience,last_m FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user)).fetchone()
            if r['evolution']=='automatic' and decoder.model and maturation.due(row['experience'],hz[scope_name],row['last_m']) is not None:due.add((persona_id,scope_name,user or None))
        return due
    def collect_examples(tenant,persona_id,scope_name,user_id,auto=False):
        rows=store.all('SELECT * FROM feedback WHERE tenant=? AND persona=? AND valid=1 ORDER BY rowid DESC LIMIT 1000',(tenant,persona_id));examples=[];seen=set()
        for row in rows:
            f=json.loads(row['data'])
            if not f['learning_consent'] or f['consent_scope']!=scope_name or (scope_name=='relationship' and row['user_id']!=user_id):continue
            # One training example per (decision, actor, kind): resubmitting the same
            # judgement under a new feedback_id cannot double its weight. Newest wins.
            key=(f['decision_id'],f['actor_id'],f['kind'])
            if key in seen:continue
            d=store.one('SELECT data FROM decisions WHERE tenant=? AND id=?',(tenant,f['decision_id']))
            if not d:continue
            data=json.loads(d['data'])
            if data['response']['decoder_hash']!=decoder.hash:continue
            if data['response']['mode']=='frozen' or data['response']['engine_status']=='baseline_fallback':continue
            seen.add(key)
            examples.append({**f,'evidence_group':data['host']['adapter_id']+':'+data['session']['id'],**{k:data[k] for k in ('context','host','action','selection','propensity')}})
        if auto:
            # Agent reflections may never outweigh people's own feedback in an
            # automatically promoted candidate (newest reflections are kept).
            explicit=[e for e in examples if e['source']!='agent_reflection'];reflections=[e for e in examples if e['source']=='agent_reflection']
            if explicit:examples=explicit+reflections[:len(explicit)]
        return examples
    def state(tenant,persona_id,user_id):
        r=store.one('SELECT * FROM personas WHERE tenant=? AND id=?',(tenant,persona_id))
        rr=store.one('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user_id)) if user_id else None
        rv=rr['active'] if rr else None; p=system_principal(tenant,persona_id,AUTO_ACTOR)
        return r,rv,latent(p,persona_id,r['active'],CORE_DIM),latent(p,persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
    def run_job(p,jid,scope_name,user_id,seed,base,relbase,core,rel,examples,auto=False):
        train,valid=group_split(examples)
        x,fit=fit_candidate(decoder,core,rel,train,scope_name,seed,policy_for(scope_name,auto).maximum_drift)
        report=evaluate_candidate(decoder,core,rel,x,scope_name,train,valid,auto)
        ids=[e['feedback_id'] for e in examples]
        h=store.put(x)
        data=dict(scope=scope_name,user_id=user_id,base_version=base,base_relationship_version=relbase,artifact=h,fit=fit,report=report,eligible=report['eligible'],evidence_ids=ids,seed=seed,decoder_hash=decoder.hash)
        if auto:data.update(auto=True,kind='feedback',examples_seen=len(examples))
        with store.tx() as db:
            job_row=db.execute('SELECT persona FROM jobs WHERE tenant=? AND id=?',(p.tenant,jid)).fetchone()
            if not job_row or not db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(p.tenant,job_row['persona'])).fetchone():store.gc();return
            persona_id=job_row['persona']
            valid_ids={r['id'] for r in db.execute('SELECT id FROM feedback WHERE tenant=? AND persona=? AND valid=1',(p.tenant,persona_id))}
            if not set(ids)<=valid_ids:data.update(eligible=False,invalidated_by='concurrent_revocation')
            db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('evaluated',json.dumps(data),p.tenant,jid))
            store.audit(db,p.tenant,persona_id,'candidate_evaluated',{'job':jid,'eligible':data['eligible'],'checks':report['checks'],'policy_hash':report['policy_hash'],'automatic':auto})
            if auto and data['eligible']:promote_automatically(db,p,persona_id,jid,base)
    def promote_automatically(db,p,persona_id,jid,base):
        try:apply_promotion(db,p,persona_id,jid,base)
        except Fault as exc:
            # Another promotion or rollback won the compare-and-swap; evolution resumes from it.
            db.execute('UPDATE jobs SET status=? WHERE tenant=? AND id=?',('superseded',p.tenant,jid))
            store.audit(db,p.tenant,persona_id,'automatic_promotion_skipped',{'job':jid,'reason':exc.code})
    def submit_auto(tenant,persona_id,kind,scope_name,user_id,work):
        """Queue one engine-initiated job; at most one per (persona, kind, scope, user)."""
        with store.tx() as db:
            for row in db.execute("SELECT data FROM jobs WHERE tenant=? AND persona=? AND status='queued'",(tenant,persona_id)):
                d=json.loads(row['data'])
                if d.get('auto') and d.get('kind')==kind and d['scope']==scope_name and d.get('user_id')==user_id:return None
            if not pending.acquire(blocking=False):return None
            jid=uid();db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(tenant,jid,persona_id,'queued',json.dumps({'scope':scope_name,'user_id':user_id,'auto':True,'kind':kind})))
        def guarded():
            try:work(tenant,persona_id,scope_name,user_id,jid)
            except Exception as exc:
                with store.tx() as db:db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('failed',json.dumps({'eligible':False,'auto':True,'kind':kind,'scope':scope_name,'user_id':user_id,'reason':str(exc)[:300]}),tenant,jid))
            finally:pending.release()
        pool.submit(guarded);return jid
    def skip(tenant,jid,reason):
        with store.tx() as db:
            row=db.execute('SELECT data FROM jobs WHERE tenant=? AND id=?',(tenant,jid)).fetchone();data=json.loads(row['data']);data.update(eligible=False,reason=reason)
            db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('skipped',json.dumps(data),tenant,jid))
    def maybe_learn(tenant,persona_id,scope_name,user_id):
        """Automatic evolution from consented feedback: retry once enough new evidence exists."""
        r=store.one('SELECT evolution FROM personas WHERE tenant=? AND id=?',(tenant,persona_id))
        if not r or r['evolution']!='automatic' or decoder.model is None:return
        count=len(collect_examples(tenant,persona_id,scope_name,user_id,auto=True)); last=0
        for row in store.all('SELECT data FROM jobs WHERE tenant=? AND persona=? ORDER BY rowid DESC',(tenant,persona_id)):
            d=json.loads(row['data'])
            if d.get('kind')=='feedback' and d.get('scope')==scope_name and d.get('user_id')==user_id:last=d.get('examples_seen') or 0;break
        if count-last>=AUTO_EVIDENCE_STEP[scope_name]:submit_auto(tenant,persona_id,'feedback',scope_name,user_id,learn)
    def learn(tenant,persona_id,scope_name,user_id,jid):
        r,rv,core,rel=state(tenant,persona_id,user_id)
        if r is None or r['evolution']!='automatic':return skip(tenant,jid,'evolution not automatic')
        examples=collect_examples(tenant,persona_id,scope_name,user_id,auto=True)
        try:run_job(system_principal(tenant,persona_id,AUTO_ACTOR),jid,scope_name,user_id,42,r['active'],rv,core,rel,examples,auto=True)
        except Exception as exc:
            # Too little or unusable evidence is normal early on; wait for more.
            with store.tx() as db:db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('failed',json.dumps({'eligible':False,'auto':True,'kind':'feedback','scope':scope_name,'user_id':user_id,'examples_seen':len(examples),'reason':str(exc)[:300]}),tenant,jid))
        maybe_learn(tenant,persona_id,scope_name,user_id)  # evidence that arrived while this job ran
    def mature(tenant,persona_id,scope_name,user_id,jid):
        """One natural maturation step on the square-root curve (see engine.learning.maturation)."""
        r,rv,core,rel=state(tenant,persona_id,user_id)
        if r is None or r['evolution']!='automatic':return skip(tenant,jid,'evolution not automatic')
        hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None)
        st=store.one('SELECT * FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user_id or ''))
        step=maturation.due_step(st['experience'],hz[scope_name],st['last_m'])
        if step is None:return skip(tenant,jid,'no maturation step due')
        at,m=step;more=maturation.due(st['experience'],hz[scope_name],m) is not None
        budget=maturation.step_budget(scope_name,m,st['last_m']); last_decision=st['last_decision']; summary={}
        if scope_name=='relationship':x=maturation.familiarize(decoder,core,rel,seed_profile(json.loads(r['seeds'] or '[]')),m,budget)
        else:
            counts={}
            for row in store.all("SELECT rowid,data FROM decisions WHERE tenant=? AND persona=? AND rowid>? AND json_extract(data,'$.response.mode')='active' AND json_extract(data,'$.response.engine_status')!='baseline_fallback'",(tenant,persona_id,last_decision)):
                d=json.loads(row['data']);last_decision=max(last_decision,row['rowid'])
                if d['response']['decoder_hash']!=decoder.hash:continue
                host={k:d['host'][k] for k in ('provider_family','adapter_id')};key=json.dumps([d['context'],host],sort_keys=True);counts[key]=counts.get(key,0)+1
            if not counts:return skip(tenant,jid,'no active decisions to habituate to')
            x=maturation.habituate(decoder,core,[(*json.loads(k),c) for k,c in counts.items()],budget)
            for k,c in counts.items():task=json.loads(k)[0]['task_type'];summary[task]=summary.get(task,0)+c
        report=evaluate_maturation(decoder,core,rel,x,scope_name,budget,collect_examples(tenant,persona_id,scope_name,user_id))
        h=store.put(x);p=system_principal(tenant,persona_id,MATURATION_ACTOR)
        data=dict(scope=scope_name,user_id=user_id,auto=True,kind='maturation',base_version=r['active'],base_relationship_version=rv,artifact=h,report=report,eligible=report['eligible'],evidence_ids=[],
            experience=at,horizon=hz[scope_name],maturity=m,previous_maturity=st['last_m'],decoder_hash=decoder.hash)
        with store.tx() as db:
            if not db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(tenant,persona_id)).fetchone():store.gc();return
            db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('evaluated',json.dumps(data),tenant,jid))
            # The curve advances whether or not the step was accepted: a rejected step is skipped, not retried larger.
            # While replaying a backlog, later steps reuse the same window of decisions.
            db.execute('UPDATE maturation SET last_m=?,last_decision=? WHERE tenant=? AND persona=? AND user_id=?',(m,st['last_decision'] if more else last_decision,tenant,persona_id,user_id or ''))
            store.audit(db,tenant,persona_id,'matured',{'job':jid,'scope':scope_name,'maturity':round(m,4),'previous_maturity':round(st['last_m'],4),'experience':at,
                'drift':round(report['metrics']['drift'],4),'eligible':report['eligible'],'checks':report['checks'],'task_counts':summary})
            if report['eligible']:promote_automatically(db,p,persona_id,jid,r['active'])
        # Replay any backlog, including sessions that ended while this step ran.
        now=store.one('SELECT experience FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user_id or ''))
        if now and maturation.due(now['experience'],hz[scope_name],m) is not None:submit_auto(tenant,persona_id,'maturation',scope_name,user_id,mature)
    @app.post('/v1/consolidations',status_code=202)
    def consolidate(req:Consolidate,p=Depends(principal)):
        scope(p,'training:admin',req.persona_id,req.user_id); r=persona(p,req.persona_id)
        if req.scope=='relationship' and not req.user_id:raise Fault('INVALID_CONTEXT','Linked user required')
        examples=collect_examples(p.tenant,req.persona_id,req.scope,req.user_id)
        rr=store.one('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,req.persona_id,req.user_id))
        rv=rr['active'] if rr else None
        core=latent(p,req.persona_id,r['active'],CORE_DIM); rel=latent(p,req.persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
        if not pending.acquire(blocking=False):raise Fault('RATE_LIMITED','Training queue full',429,True)
        jid=uid()
        with store.tx() as db:db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(p.tenant,jid,req.persona_id,'queued',json.dumps({'scope':req.scope,'user_id':req.user_id})))
        def work():
            try:run_job(p,jid,req.scope,req.user_id,req.seed,r['active'],rv,core,rel,examples)
            except Exception as exc:
                with store.tx() as db:db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('failed',json.dumps({'eligible':False,'reason':str(exc)[:300]}),p.tenant,jid))
            finally:pending.release()
        pool.submit(work)
        return wire(job_id=jid,status='queued')
    @app.get('/v1/consolidations/{id}')
    def job(id:str,p=Depends(principal)):
        scope(p,'training:admin');r=store.one('SELECT * FROM jobs WHERE tenant=? AND id=?',(p.tenant,id))
        if not r:raise Fault('INVALID_CONTEXT','Unknown job',404)
        scope(p,'training:admin',r['persona']); data=json.loads(r['data'])
        if data.get('user_id'):scope(p,'training:admin',r['persona'],data['user_id'])
        return wire(job_id=id,status=r['status'],**data)
    def apply_promotion(db,p,id,candidate_id,expected_version):
        """Compare-and-swap promotion shared by operators and automatic evolution."""
        r=db.execute('SELECT * FROM personas WHERE tenant=? AND id=?',(p.tenant,id)).fetchone()
        if not r: raise Fault('PERSONA_NOT_FOUND','Persona not found',404)
        row=db.execute('SELECT * FROM jobs WHERE tenant=? AND id=? AND persona=?',(p.tenant,candidate_id,id)).fetchone()
        data=json.loads(row['data']) if row else {}
        if not row or row['status']!='evaluated' or not data.get('eligible'):raise Fault('NOT_ELIGIBLE_FOR_PROMOTION','Candidate failed evaluation or was invalidated',409)
        scope(p,'training:admin',id,data.get('user_id'))
        if data['base_version']!=r['active'] or expected_version!=r['active']:raise Fault('VERSION_CONFLICT','Active version changed',409)
        rel=db.execute('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,data['user_id'])).fetchone()
        if data['scope']=='relationship' and (rel['active'] if rel else None)!=data['base_relationship_version']:raise Fault('VERSION_CONFLICT','Relationship version changed',409)
        valid={r['id'] for r in db.execute('SELECT id FROM feedback WHERE tenant=? AND valid=1',(p.tenant,))}
        if not set(data['evidence_ids'])<=valid:raise Fault('NOT_ELIGIBLE_FOR_PROMOTION','Evidence revoked',409)
        store.get(data['artifact'],CORE_DIM if data['scope']=='core' else REL_DIM)
        v=uid()
        if data['scope']=='core':
            db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,data['artifact'],r['active'],'core',None,candidate_id,None))
            db.execute('UPDATE personas SET active=? WHERE tenant=? AND id=?',(v,p.tenant,id))
        else:
            db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,data['artifact'],data['base_relationship_version'],'relationship',data['user_id'],candidate_id,r['active']))
            db.execute('INSERT OR REPLACE INTO relationships VALUES(?,?,?,?)',(p.tenant,id,data['user_id'],v))
        db.execute('UPDATE jobs SET status=? WHERE tenant=? AND id=?',('promoted',p.tenant,candidate_id))
        store.audit(db,p.tenant,id,'promoted',{'candidate':candidate_id,'version':v,'actor':p.actor,'kind':data.get('kind','feedback'),'automatic':bool(data.get('auto'))})
        return v,data['scope']
    @app.post('/v1/personas/{id}/promotions')
    def promote(id:str,req:Promote,p=Depends(principal)):
        scope(p,'training:admin',id)
        with store.tx() as db:
            persona(p,id);v,scope_name=apply_promotion(db,p,id,req.candidate_id,req.expected_version)
        return wire(version=v,scope=scope_name)
    @app.post('/v1/personas/{id}/evolution')
    def evolution(id:str,req:Evolution,p=Depends(principal)):
        scope(p,'persona:admin',id)
        with store.tx() as db:
            r=persona(p,id);hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None)
            mode=req.evolution or r['evolution'];feedback=r['agent_feedback'] if req.agent_feedback is None else int(req.agent_feedback)
            if req.maturation_rate is not None:hz=maturation.horizons(req.maturation_rate.model_dump() if isinstance(req.maturation_rate,BaseModel) else req.maturation_rate)
            db.execute('UPDATE personas SET evolution=?,maturation=?,agent_feedback=? WHERE tenant=? AND id=?',(mode,json.dumps(hz),feedback,p.tenant,id))
            if req.maturation_rate is not None or (mode=='automatic' and r['evolution']!='automatic'):
                # Re-anchor the curve at current experience so a rate change or resume never jumps the latent.
                for row in db.execute('SELECT user_id,experience FROM maturation WHERE tenant=? AND persona=?',(p.tenant,id)).fetchall():
                    db.execute('UPDATE maturation SET last_m=? WHERE tenant=? AND persona=? AND user_id=?',(maturation.maturity(row['experience'],hz['relationship' if row['user_id'] else 'core']),p.tenant,id,row['user_id']))
            store.audit(db,p.tenant,id,'evolution_changed',{'actor':p.actor,'evolution':mode,'maturation_rate':maturation.public_rate(hz),'agent_feedback':bool(feedback)})
        return wire(persona_id=id,evolution=mode,maturation_rate=maturation.public_rate(hz),agent_feedback=bool(feedback))
    @app.post('/v1/reflections')
    def reflect(req:Reflection,p=Depends(principal)):
        """Agent-initiated style feedback: bounded trait moves only, never text."""
        scope(p,'reflection:write')
        d=store.one('SELECT * FROM decisions WHERE tenant=? AND id=?',(p.tenant,req.decision_id))
        if not d:raise Fault('INVALID_CONTEXT','Unknown decision')
        scope(p,'reflection:write',d['persona'],d['user_id'])
        if d['actor']!=p.actor and 'training:admin' not in p.scopes:raise Fault('FORBIDDEN_SCOPE','Decision actor mismatch',403)
        r=persona(p,d['persona'])
        if not r['agent_feedback']:raise Fault('FORBIDDEN_SCOPE','Agent feedback is disabled for this persona',403)
        data=json.loads(d['data'])
        if data['context']['turn_origin']!='user':raise Fault('INVALID_CONTEXT','Reflections apply only to user-originated turns')
        if data['response']['mode']=='frozen' or data['response']['engine_status']=='baseline_fallback':raise Fault('INVALID_CONTEXT','Decision cannot be learned from')
        scope_name=req.scope or ('relationship' if d['user_id'] else 'core')
        if scope_name=='relationship' and not d['user_id']:raise Fault('INVALID_CONTEXT','Relationship reflection requires linked user')
        if scope_name=='core' and d['user_id'] and 'training:admin' not in p.scopes:raise Fault('FORBIDDEN_SCOPE','Core reflections on a linked user\'s turn require training administrator',403)
        preferred=adjusted_control(data['action'],req.adjustments,data['context'])
        if preferred is None:raise Fault('INVALID_CONTEXT','No approved style moves that way in this context')
        group=short_id(data['host']['adapter_id']+':'+data['session']['id']);fid=short_id('reflection:'+req.reflection_id)
        f=Feedback(protocol_version='upap/1',feedback_id=fid,decision_id=req.decision_id,source='agent_reflection',kind='pairwise_preference',actor_id=p.actor,consent_scope=scope_name,
            learning_consent=True,preferred_control=preferred,rejected_control=data['action'],evidence_group=group,occurred_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
        with store.tx() as db:
            old=db.execute('SELECT data FROM feedback WHERE tenant=? AND id=?',(p.tenant,fid)).fetchone()
            if old:
                prior=json.loads(old['data'])
                if (prior['decision_id'],prior['preferred_control'],prior['consent_scope'])!=(req.decision_id,preferred,scope_name):raise Fault('VERSION_CONFLICT','Reflection id reused',409)
            else:
                reflected="SELECT COUNT(*) FROM feedback WHERE tenant=? AND persona=? AND json_extract(data,'$.source')='agent_reflection' AND "
                if db.execute(reflected+"json_extract(data,'$.decision_id')=?",(p.tenant,d['persona'],req.decision_id)).fetchone()[0]:raise Fault('RATE_LIMITED','One reflection per decision',429)
                if db.execute(reflected+"json_extract(data,'$.evidence_group')=?",(p.tenant,d['persona'],group)).fetchone()[0]>=REFLECTIONS_PER_SESSION:raise Fault('RATE_LIMITED',f'At most {REFLECTIONS_PER_SESSION} reflections per session',429)
                db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(p.tenant,fid,d['persona'],d['user_id'],p.actor,f.model_dump_json()))
                store.audit(db,p.tenant,d['persona'],'reflection_recorded',{'feedback_id':fid,'actor':p.actor,'reason':req.reason,'adjustments':req.adjustments,'consent_scope':scope_name,
                    'preferred_control':preferred,'rejected_control':data['action'],'received_at':datetime.now(timezone.utc).isoformat()})
        if not old:maybe_learn(p.tenant,d['persona'],scope_name,d['user_id'] if scope_name=='relationship' else None)
        return wire(reflection_id=req.reflection_id,feedback_id=fid,deduplicated=bool(old),scope=scope_name,preferred_control=preferred,rejected_control=data['action'],
            control_set_id=f'style-{preferred:02}',controls=CATALOGUE[preferred],learning_recorded=True)
    @app.post('/v1/personas/{id}/rollbacks')
    def rollback(id:str,req:Rollback,p=Depends(principal)):
        scope(p,'persona:admin',id);persona(p,id);v=version(p,id,req.version);scope(p,'persona:admin',id,v['user_id'])
        store.get(v['hash'],CORE_DIM if v['scope']=='core' else REL_DIM)
        with store.tx() as db:
            if v['scope']=='core':db.execute('UPDATE personas SET active=? WHERE tenant=? AND id=?',(v['id'],p.tenant,id))
            else:db.execute('INSERT OR REPLACE INTO relationships VALUES(?,?,?,?)',(p.tenant,id,v['user_id'],v['id']))
            store.audit(db,p.tenant,id,'rollback',{'version':v['id'],'reason':req.reason,'actor':p.actor})
        return wire(version=v['id'])
    @app.post('/v1/personas/{id}/export')
    def export(id:str,req:Export,p=Depends(principal)):
        scope(p,'persona:admin',id);r=persona(p,id)
        if req.include_relationships:raise Fault('FORBIDDEN_SCOPE','Relationship portability is not supported in this experimental release',403)
        data={'format':'openape-bundle/1','tenant_id':p.tenant,'decoder_hash':decoder.hash,'core':latent(p,id,r['active'],CORE_DIM).tolist(),'initialization':'imported'}
        return wire(bundle={'data':data,'sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
    @app.post('/v1/personas/import')
    def import_persona(req:Import,p=Depends(principal)):
        scope(p,'persona:admin',req.persona_id)
        try:
            b=req.bundle;data=b['data'];h=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if set(b)!={'data','sha256'} or set(data)!={'format','tenant_id','decoder_hash','core','initialization'} or h!=b['sha256']:raise ValueError()
            if data['tenant_id']!=p.tenant:raise Fault('FORBIDDEN_SCOPE','Bundle tenant mismatch',403)
            if data['decoder_hash']!=decoder.hash:raise Fault('DECODER_INCOMPATIBLE','Bundle decoder mismatch',409)
            if data['format']!='openape-bundle/1':raise ValueError()
            x=torch.tensor(data['core'],dtype=torch.float32)
            if x.shape!=(CORE_DIM,) or not torch.isfinite(x).all() or x.norm()>decoder.meta.get('latent_norm_limit',20)+1e-4:raise ValueError()
        except (KeyError,TypeError,ValueError,RuntimeError):raise Fault('INVALID_CONTEXT','Invalid bundle')
        artifact=store.put(x)
        with store.tx() as db:
            v=insert_persona(db,p,req.persona_id,artifact,'imported',rate=os.environ.get('OPENAPE_MATURATION_RATE'));store.audit(db,p.tenant,req.persona_id,'imported',{'actor':p.actor,'bundle_sha256':b['sha256']})
        return wire(persona_id=req.persona_id,active_version=v)
    @app.delete('/v1/personas/{id}')
    def delete(id:str,p=Depends(principal)):
        scope(p,'persona:admin',id);persona(p,id)
        # Deletion spans all user-linked ledger rows, including users without trained state.
        if '*' not in p.users:raise Fault('FORBIDDEN_SCOPE','Deleting a persona requires authority over all linked users',403)
        with store.tx() as db:
            counts={}
            for table in ('versions','relationships','sessions','requests','decisions','feedback','observations','jobs','experience','maturation'):
                counts[table]=db.execute(f'DELETE FROM {table} WHERE tenant=? AND persona=?',(p.tenant,id)).rowcount
            db.execute('DELETE FROM audit WHERE tenant=? AND persona=?',(p.tenant,id))
            db.execute('DELETE FROM personas WHERE tenant=? AND id=?',(p.tenant,id));store.gc()
            store.audit(db,p.tenant,id,'deletion_completed',{'counts':counts})
        return wire(deleted=True,counts=counts,artifacts_collected=True)
    return app
