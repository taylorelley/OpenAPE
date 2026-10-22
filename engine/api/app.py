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
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from engine.api.contracts import *
from engine.security.auth import Auth
from engine.storage.store import Store
from engine.neural.policy import Decoder, CATALOGUE, ACTIONS, CORE_DIM, REL_DIM, mask_reason
from engine.neural.profiles import fit_seed_latent
from engine.learning.trainer import fit_candidate
from engine.evaluation.policy import group_split, evaluate_candidate, policy_for

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_DECODER=ROOT/'models/decoder-v2/decoder.safetensors'
def uid(): return str(uuid.uuid4())
def wire(**kwargs): return {'protocol_version':'upap/1',**kwargs}
class Fault(Exception):
    def __init__(self,code,message,status=400,retryable=False): self.code,self.message,self.status,self.retryable=code,message,status,retryable
VERSION_COLUMNS='(tenant,persona,id,hash,parent,scope,user_id,job,core_base)'

def create_app(data_dir=None,credentials=None,decoder_path=None,rate_limit_per_minute=600):
    auth=Auth(credentials); store=Store(data_dir or os.environ.get('OPENAPE_DATA','.openape'))
    decoder_location=decoder_path or os.environ.get('OPENAPE_DECODER',str(DEFAULT_DECODER))
    try:decoder=Decoder(decoder_location)
    except (ValueError,OSError,RuntimeError,KeyError):decoder=Decoder('/nonexistent-openape-approved-fallback')
    engine_status='experimental_synthetic' if decoder.model else 'baseline_fallback'
    app=FastAPI(title='OpenAPE — Agent Personality Engine',version='0.2.0')
    app.state.store=store; app.state.decoder=decoder
    pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='openape-training')
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
            max_payload_bytes=65536,modes=['disabled','shadow','active','frozen'],initializations=['neutral_prior','seed_preferences','snapshot','imported'],
            features=['pairwise_learning','logged_bandit_learning','independent_evaluator','cas_promotion','rollback','lineage_revocation','core_export','subagent_snapshot'],
            session_state='zero ephemeral; no checkpoints',automatic_promotion=False)
    def insert_persona(db,p,id,artifact,initialization,parent=None):
        if db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(p.tenant,id)).fetchone():raise Fault('VERSION_CONFLICT','Persona already exists',409)
        v=uid()
        db.execute('INSERT INTO personas(tenant,id,active,initialization,parent) VALUES(?,?,?,?,?)',(p.tenant,id,v,initialization,parent))
        db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,artifact,None,'core',None,None,None))
        return v
    @app.post('/v1/personas')
    def create(req:Create,p=Depends(principal)):
        scope(p,'persona:admin',req.persona_id)
        if req.parent_persona_id and req.seed_preferences:raise Fault('INVALID_CONTEXT','Choose a snapshot parent or seed preferences, not both')
        parent=None
        if req.parent_persona_id:
            # Subagent semantics: a new scoped identity holding an immutable copy of the
            # parent's approved core version. No mutable weights are shared.
            scope(p,'persona:admin',req.parent_persona_id); src=persona(p,req.parent_persona_id)
            x=latent(p,req.parent_persona_id,src['active'],CORE_DIM); initialization='snapshot'; parent=f"{req.parent_persona_id}@{src['active']}"
        elif req.seed_preferences:
            try:x=fit_seed_latent(decoder,req.seed_preferences)
            except ValueError as exc:raise Fault('INVALID_CONTEXT',str(exc))
            initialization='seed_preferences'
        else:x=torch.zeros(CORE_DIM); initialization='neutral_prior'
        h=store.put(x)
        with store.tx() as db:
            v=insert_persona(db,p,req.persona_id,h,initialization,parent)
            store.audit(db,p.tenant,req.persona_id,'created',{'actor':p.actor,'initialization':initialization,'seed_preferences':req.seed_preferences,'parent':parent})
        return wire(persona_id=req.persona_id,active_version=v,initialization=initialization,seed_preferences_applied=initialization=='seed_preferences',parent=parent)
    @app.get('/v1/personas')
    def list_personas(p=Depends(principal)):
        scope(p,'persona:express')
        rows=store.all('SELECT id,active,initialization,parent FROM personas WHERE tenant=?',(p.tenant,))
        return wire(personas=[dict(r) for r in rows if p.allows(r['id'])])
    @app.get('/v1/personas/{id}')
    def inspect(id:str,p=Depends(principal)):
        scope(p,'persona:express',id); r=persona(p,id)
        return wire(persona_id=id,active_version=r['active'],initialization=r['initialization'],parent=r['parent'],decoder_hash=decoder.hash,engine_status=engine_status)
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
        return wire(feedback_id=req.feedback_id,deduplicated=bool(old),learning_recorded=req.learning_consent and req.consent_scope not in ('record_only','session'))
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
        scope(p,'observations:write'); inserted=0
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
                if e.type=='session.ended':db.execute('DELETE FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',(p.tenant,e.persona_id,e.user_id or '',req.adapter_id,e.session_id))
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',(p.tenant,req.adapter_id,e.event_id,e.persona_id,raw));inserted+=1
        return wire(inserted=inserted,deduplicated=len(req.events)-inserted)
    def run_job(p,req,jid,base,relbase,core,rel,examples):
        try:
            train,valid=group_split(examples)
            x,fit=fit_candidate(decoder,core,rel,train,req.scope,req.seed,policy_for(req.scope).maximum_drift)
            report=evaluate_candidate(decoder,core,rel,x,req.scope,train,valid)
            ids=[e['feedback_id'] for e in examples]
            h=store.put(x)
            data=dict(scope=req.scope,user_id=req.user_id,base_version=base,base_relationship_version=relbase,artifact=h,fit=fit,report=report,eligible=report['eligible'],evidence_ids=ids,seed=req.seed,decoder_hash=decoder.hash)
            with store.tx() as db:
                valid_ids={r['id'] for r in db.execute('SELECT id FROM feedback WHERE tenant=? AND persona=? AND valid=1',(p.tenant,req.persona_id))}
                if not set(ids)<=valid_ids:data.update(eligible=False,invalidated_by='concurrent_revocation')
                if not db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(p.tenant,req.persona_id)).fetchone():store.gc();return
                db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('evaluated',json.dumps(data),p.tenant,jid))
                store.audit(db,p.tenant,req.persona_id,'candidate_evaluated',{'job':jid,'eligible':data['eligible'],'checks':report['checks'],'policy_hash':report['policy_hash']})
        except Exception as exc:
            with store.tx() as db:db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('failed',json.dumps({'eligible':False,'reason':str(exc)[:300]}),p.tenant,jid))
        finally:pending.release()
    @app.post('/v1/consolidations',status_code=202)
    def consolidate(req:Consolidate,p=Depends(principal)):
        scope(p,'training:admin',req.persona_id,req.user_id); r=persona(p,req.persona_id)
        if req.scope=='relationship' and not req.user_id:raise Fault('INVALID_CONTEXT','Linked user required')
        rows=store.all('SELECT * FROM feedback WHERE tenant=? AND persona=? AND valid=1 ORDER BY rowid DESC LIMIT 1000',(p.tenant,req.persona_id));examples=[];seen=set()
        for row in rows:
            f=json.loads(row['data'])
            if not f['learning_consent'] or f['consent_scope']!=req.scope or (req.scope=='relationship' and row['user_id']!=req.user_id):continue
            # One training example per (decision, actor, kind): resubmitting the same
            # judgement under a new feedback_id cannot double its weight. Newest wins.
            key=(f['decision_id'],f['actor_id'],f['kind'])
            if key in seen:continue
            d=store.one('SELECT data FROM decisions WHERE tenant=? AND id=?',(p.tenant,f['decision_id']))
            if not d:continue
            data=json.loads(d['data'])
            if data['response']['decoder_hash']!=decoder.hash:continue
            if data['response']['mode']=='frozen' or data['response']['engine_status']=='baseline_fallback':continue
            seen.add(key)
            examples.append({**f,'evidence_group':data['host']['adapter_id']+':'+data['session']['id'],**{k:data[k] for k in ('context','host','action','selection','propensity')}})
        rr=store.one('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,req.persona_id,req.user_id))
        rv=rr['active'] if rr else None
        core=latent(p,req.persona_id,r['active'],CORE_DIM); rel=latent(p,req.persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
        if not pending.acquire(blocking=False):raise Fault('RATE_LIMITED','Training queue full',429,True)
        jid=uid()
        with store.tx() as db:db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(p.tenant,jid,req.persona_id,'queued',json.dumps({'scope':req.scope,'user_id':req.user_id})))
        pool.submit(run_job,p,req,jid,r['active'],rv,core,rel,examples)
        return wire(job_id=jid,status='queued')
    @app.get('/v1/consolidations/{id}')
    def job(id:str,p=Depends(principal)):
        scope(p,'training:admin');r=store.one('SELECT * FROM jobs WHERE tenant=? AND id=?',(p.tenant,id))
        if not r:raise Fault('INVALID_CONTEXT','Unknown job',404)
        scope(p,'training:admin',r['persona']); data=json.loads(r['data'])
        if data.get('user_id'):scope(p,'training:admin',r['persona'],data['user_id'])
        return wire(job_id=id,status=r['status'],**data)
    @app.post('/v1/personas/{id}/promotions')
    def promote(id:str,req:Promote,p=Depends(principal)):
        scope(p,'training:admin',id)
        with store.tx() as db:
            r=persona(p,id)
            row=db.execute('SELECT * FROM jobs WHERE tenant=? AND id=? AND persona=?',(p.tenant,req.candidate_id,id)).fetchone()
            data=json.loads(row['data']) if row else {}
            if not row or row['status']!='evaluated' or not data.get('eligible'):raise Fault('NOT_ELIGIBLE_FOR_PROMOTION','Candidate failed evaluation or was invalidated',409)
            scope(p,'training:admin',id,data.get('user_id'))
            if data['base_version']!=r['active'] or req.expected_version!=r['active']:raise Fault('VERSION_CONFLICT','Active version changed',409)
            rel=db.execute('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,data['user_id'])).fetchone()
            if data['scope']=='relationship' and (rel['active'] if rel else None)!=data['base_relationship_version']:raise Fault('VERSION_CONFLICT','Relationship version changed',409)
            valid={r['id'] for r in db.execute('SELECT id FROM feedback WHERE tenant=? AND valid=1',(p.tenant,))}
            if not set(data['evidence_ids'])<=valid:raise Fault('NOT_ELIGIBLE_FOR_PROMOTION','Evidence revoked',409)
            store.get(data['artifact'],CORE_DIM if data['scope']=='core' else REL_DIM)
            v=uid()
            if data['scope']=='core':
                db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,data['artifact'],r['active'],'core',None,req.candidate_id,None))
                db.execute('UPDATE personas SET active=? WHERE tenant=? AND id=?',(v,p.tenant,id))
            else:
                db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,data['artifact'],data['base_relationship_version'],'relationship',data['user_id'],req.candidate_id,r['active']))
                db.execute('INSERT OR REPLACE INTO relationships VALUES(?,?,?,?)',(p.tenant,id,data['user_id'],v))
            db.execute('UPDATE jobs SET status=? WHERE tenant=? AND id=?',('promoted',p.tenant,req.candidate_id))
            store.audit(db,p.tenant,id,'promoted',{'candidate':req.candidate_id,'version':v,'actor':p.actor})
        return wire(version=v,scope=data['scope'])
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
            v=insert_persona(db,p,req.persona_id,artifact,'imported');store.audit(db,p.tenant,req.persona_id,'imported',{'actor':p.actor,'bundle_sha256':b['sha256']})
        return wire(persona_id=req.persona_id,active_version=v)
    @app.delete('/v1/personas/{id}')
    def delete(id:str,p=Depends(principal)):
        scope(p,'persona:admin',id);persona(p,id)
        # Deletion spans all user-linked ledger rows, including users without trained state.
        if '*' not in p.users:raise Fault('FORBIDDEN_SCOPE','Deleting a persona requires authority over all linked users',403)
        with store.tx() as db:
            counts={}
            for table in ('versions','relationships','sessions','requests','decisions','feedback','observations','jobs'):
                counts[table]=db.execute(f'DELETE FROM {table} WHERE tenant=? AND persona=?',(p.tenant,id)).rowcount
            db.execute('DELETE FROM audit WHERE tenant=? AND persona=?',(p.tenant,id))
            db.execute('DELETE FROM personas WHERE tenant=? AND id=?',(p.tenant,id));store.gc()
            store.audit(db,p.tenant,id,'deletion_completed',{'counts':counts})
        return wire(deleted=True,counts=counts,artifacts_collected=True)
    return app
