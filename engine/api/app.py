"""OpenAPE UPAP/2 API. Run with `openape serve`, not a permissive default app."""
import hashlib
import json
import os
import time
import uuid
import threading
from collections import Counter, defaultdict, deque
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
from protocol.catalogue import SCHEMA, CATALOGUE_HASH, HABIT_IDS
from engine.neural.policy import Decoder, ACTIONS, NEUTRAL_ACTION, CORE_DIM, REL_DIM, VOCAB, ENGINE_TAGS, mask_reason, joint, select_habits, levels_of, choice
from engine.neural.profiles import fit_seed_latent, seed_profile, ARCHETYPES, ARCHETYPE_HABITS
from engine.learning.trainer import fit_candidate, state_norm_limit
from engine.learning import maturation, development as dev
from engine.learning.reflection import adjusted_choice
from engine.evaluation.policy import group_split, evaluate_candidate, evaluate_maturation, policy_for

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_DECODER=ROOT/'models/decoder-v3/decoder.safetensors'
PROTOCOL='upap/2'
LONG_SESSION=20  # turns after which the engine tags a session long_session
def uid(): return str(uuid.uuid4())
def wire(**kwargs): return {'protocol_version':PROTOCOL,**kwargs}
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

class LegacyStore(RuntimeError):
    pass
def create_app(data_dir=None,credentials=None,decoder_path=None,rate_limit_per_minute=600):
    auth=Auth(credentials); store=Store(data_dir or os.environ.get('OPENAPE_DATA','.openape'))
    if store.legacy:
        store.db.close()
        raise LegacyStore('This data directory holds personas from an earlier OpenAPE release (behaviour-controls/1). '
            'Run `openape migrate --reset` to re-create them from their recorded archetypes, then start the engine again.')
    decoder_location=decoder_path or os.environ.get('OPENAPE_DECODER',str(DEFAULT_DECODER))
    try:decoder=Decoder(decoder_location)
    except (ValueError,OSError,RuntimeError,KeyError):decoder=Decoder('/nonexistent-openape-approved-fallback')
    engine_status='experimental_synthetic' if decoder.model else 'baseline_fallback'
    app=FastAPI(title='OpenAPE — Agent Personality Engine',version='0.3.0')
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
        return JSONResponse(status_code=422,content=wire(error=dict(code=code,message='Request does not conform to UPAP/2',retryable=False,request_id=getattr(request.state,'request_id',None))))
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
                if data.get('protocol_version')!=PROTOCOL:
                    return JSONResponse(status_code=422,content=wire(error={'code':'UNSUPPORTED_PROTOCOL','message':'Explicit upap/2 required','retryable':False,'request_id':request.state.request_id}))
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
        return wire(protocol_versions=[PROTOCOL],control_schema=SCHEMA,catalogue_hash=CATALOGUE_HASH,controls=ACTIONS,habits=list(HABIT_IDS),encoder=decoder.meta.get('encoder'),decoder_hash=decoder.hash,engine_status=engine_status,
            max_payload_bytes=65536,modes=['disabled','shadow','active','frozen'],initializations=['archetype','seed_preferences','snapshot','imported','neutral_prior'],
            archetypes={k:list(v) for k,v in ARCHETYPES.items()},archetype_habits={k:list(v) for k,v in ARCHETYPE_HABITS.items()},maturation_rates={k:dict(relationship_horizon=v[0],core_horizon=v[1]) for k,v in maturation.RATES.items()},
            features=['pairwise_learning','logged_bandit_learning','independent_evaluator','cas_promotion','rollback','lineage_revocation','core_export','subagent_snapshot','automatic_evolution','maturation','agent_reflection',
                'temperament','individuality','session_state','habit_consolidation','life_events','relationship_accommodation','relationship_cooling','elastic_self','maturity_weighted_influence'],
            session_state='ephemeral latent offset from consented in-session preferences; sampled at session end, never a version',automatic_promotion='persona_policy')
    def insert_persona(db,p,id,artifact,initialization,parent=None,archetype=None,seeds=(),evolution='manual',rate=None,agent_feedback=False,individuality=None):
        if db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(p.tenant,id)).fetchone():raise Fault('VERSION_CONFLICT','Persona already exists',409)
        v=uid()
        # The creation version is the persona's temperament: automatic change stays near it.
        db.execute('INSERT INTO personas(tenant,id,active,initialization,parent,archetype,seeds,evolution,maturation,agent_feedback,temperament,individuality) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (p.tenant,id,v,initialization,parent,archetype,json.dumps(sorted(seeds)),evolution,json.dumps(maturation.horizons(rate)),int(agent_feedback),v,individuality and json.dumps(individuality)))
        db.execute(f'INSERT INTO versions{VERSION_COLUMNS} VALUES(?,?,?,?,?,?,?,?,?)',(p.tenant,id,v,artifact,None,'core',None,None,None))
        return v
    @app.post('/v1/personas')
    def create(req:Create,p=Depends(principal)):
        scope(p,'persona:admin',req.persona_id)
        chosen=[x for x in (req.archetype,req.seed_preferences,req.parent_persona_id) if x]
        if len(chosen)>1:raise Fault('INVALID_CONTEXT','Choose one of archetype, seed preferences or a snapshot parent')
        if not chosen:raise Fault('INVALID_CONTEXT','Choose a starting archetype ('+', '.join(ARCHETYPES)+'), seed preferences or a snapshot parent')
        parent=None; archetype=req.archetype; individuality=None
        if req.parent_persona_id:
            # Subagent semantics: a new scoped identity holding an immutable copy of the
            # parent's approved core version. No mutable weights are shared.
            scope(p,'persona:admin',req.parent_persona_id); src=persona(p,req.parent_persona_id)
            x=latent(p,req.parent_persona_id,src['active'],CORE_DIM); initialization='snapshot'; parent=f"{req.parent_persona_id}@{src['active']}"
            archetype=src['archetype']; seeds=json.loads(src['seeds'] or '[]'); individuality=json.loads(src['individuality'] or 'null')
        else:
            seeds=list(ARCHETYPES[archetype]) if archetype else req.seed_preferences
            individuality=dict(amount=req.individuality,seed=dev.default_seed(p.tenant,req.persona_id) if req.individuality_seed is None else req.individuality_seed)
            try:x=fit_seed_latent(decoder,seeds,profile=dev.individual_profile(seed_profile(seeds,archetype),individuality['seed'],individuality['amount']))
            except ValueError as exc:raise Fault('INVALID_CONTEXT',str(exc))
            initialization='archetype' if archetype else 'seed_preferences'
        rate=req.maturation_rate.model_dump() if isinstance(req.maturation_rate,BaseModel) else req.maturation_rate or os.environ.get('OPENAPE_MATURATION_RATE')
        h=store.put(x)
        with store.tx() as db:
            v=insert_persona(db,p,req.persona_id,h,initialization,parent,archetype,seeds,req.evolution,rate,req.agent_feedback,individuality)
            store.audit(db,p.tenant,req.persona_id,'created',{'actor':p.actor,'initialization':initialization,'archetype':archetype,'seed_preferences':req.seed_preferences,'parent':parent,
                'evolution':req.evolution,'maturation_rate':maturation.public_rate(maturation.horizons(rate)),'agent_feedback':req.agent_feedback,'individuality':individuality})
        return wire(persona_id=req.persona_id,active_version=v,initialization=initialization,archetype=archetype,seed_preferences_applied=initialization=='seed_preferences',parent=parent,
            evolution=req.evolution,maturation_rate=maturation.public_rate(maturation.horizons(rate)),agent_feedback=req.agent_feedback,individuality=individuality)
    @app.get('/v1/personas')
    def list_personas(p=Depends(principal)):
        scope(p,'persona:express')
        rows=store.all('SELECT id,active,initialization,parent FROM personas WHERE tenant=?',(p.tenant,))
        return wire(personas=[dict(r) for r in rows if p.allows(r['id'])])
    @app.get('/v1/personas/{id}')
    def inspect(id:str,user_id:str|None=None,p=Depends(principal)):
        scope(p,'persona:express',id,user_id); r=persona(p,id); hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None)
        def level(user,horizon):
            row=store.one('SELECT experience,effective,life FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,user))
            t=row['experience'] if row else 0; e=row['effective'] if row and row['effective'] is not None else t; life=json.loads(row['life'] or '{}') if row else {}
            m=maturation.maturity(e,horizon); boost=life.get('boost',1.0)
            return dict(experience=t,effective_experience=round(e,3),horizon=horizon,maturity=round(m,4),growth=round(maturation.growth(e,horizon),4),plasticity=round(dev.plasticity(m,boost),4),boost=boost)
        growth=dict(core=level('',hz['core']))
        if user_id:growth['relationship']=level(user_id,hz['relationship'])
        try:character=round(float((latent(p,id,r['active'],CORE_DIM)-temperament_latent(p.tenant,id)).norm()),4)
        except (Fault,ValueError,OSError,TypeError):character=None
        return wire(persona_id=id,active_version=r['active'],initialization=r['initialization'],archetype=r['archetype'],parent=r['parent'],evolution=r['evolution'],
            maturation_rate=maturation.public_rate(hz),agent_feedback=bool(r['agent_feedback']),growth=growth,temperament_version=temperament_version(p.tenant,id),
            individuality=json.loads(r['individuality'] or 'null'),character_drift=character,character_radius=dev.CHARACTER_RADIUS,decoder_hash=decoder.hash,engine_status=engine_status)
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
                if not pin:db.execute('INSERT INTO sessions(tenant,persona,user_id,adapter,id,version,rel_version,decoder,turns) VALUES(?,?,?,?,?,?,?,?,0)',(p.tenant,i.persona_id,user,req.host.adapter_id,req.session.id,cv,rv,decoder.hash))
                turns=pin['turns'] if pin else 0
                db.execute('UPDATE sessions SET turns=turns+1 WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',(p.tenant,i.persona_id,user,req.host.adapter_id,req.session.id))
            # Session-position tags come from the engine's own session record, never the host.
            context=req.context.model_dump();context['tags']=[t for t in context['tags'] if t not in ENGINE_TAGS]
            if not req.pinned_version:context['tags']+=(['first_turn'] if turns==0 else [])+(['long_session'] if turns>=LONG_SESSION else [])
            context['tags']=[t for t in VOCAB['tags'] if t in context['tags']]
            host=req.host.model_dump()
            status=engine_status; diagnostics=None; session_state=None; habits=[]
            try:
                core=latent(p,i.persona_id,cv,CORE_DIM); relationship=latent(p,i.persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
                if req.mode!='frozen' and not req.pinned_version:
                    # Ephemeral session state: an offset from this session's consented preferences.
                    st=db.execute('SELECT delta FROM states WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND session=?',(p.tenant,i.persona_id,user,req.host.adapter_id,req.session.id)).fetchone()
                    if st:
                        offset=torch.tensor(json.loads(st['delta']));session_state=round(float(offset.norm()),4)
                        if user:relationship=relationship+offset
                        else:core=core+offset
                with torch.no_grad():
                    traits,habit_logits=decoder.heads(core,relationship,context,host); logits=joint(traits); probs=torch.softmax(logits,0)
                    action=int(torch.multinomial(probs,1,generator=torch.Generator().manual_seed(req.seed)).item()) if req.selection=='sample' else int(logits.argmax())
                    habits=select_habits(habit_logits,action,context)
                    if req.debug:diagnostics=decoder.diagnostics(core,relationship,context,host)
            except (ValueError,OSError,RuntimeError,KeyError,Fault):
                # Corrupt/missing artifacts fail closed to the approved neutral configuration.
                action=NEUTRAL_ACTION;probs=torch.zeros(ACTIONS);probs[action]=1;status='baseline_fallback';habits=[]
            propensity=float(probs[action]) if req.selection=='sample' and status!='baseline_fallback' else None
            response=Decision(request_id=req.request_id,decision_id=uid(),persona_version=cv,relationship_version=rv,decoder_hash=decoder.hash,catalogue_hash=CATALOGUE_HASH,controls=Controls(**levels_of(action)),habits=habits,mode=req.mode,policy=Policy(eligible=True,mask_reason=mask_reason(context)),engine_status=status,
                propensity=propensity if req.debug else None,diagnostics=diagnostics).model_dump()
            data=dict(response=response,context=context,host=host,session=req.session.model_dump(),fingerprint=fingerprint,action=action,habits=habits,selection=req.selection,propensity=propensity,session_state=session_state)
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
        if req.kind!='rating':
            if req.preferred is None or req.rejected is None or req.preferred==req.rejected:raise Fault('INVALID_CONTEXT','Distinct preference options required')
            for c in (req.preferred,req.rejected):
                if choice(c.controls.model_dump(),c.habits) is None:raise Fault('INVALID_CONTEXT','Preference options must be approved configurations')
        if req.occurred_at:
            try:
                stamp=datetime.fromisoformat(req.occurred_at.replace('Z','+00:00'))
                if stamp.utcoffset() is None or stamp.utcoffset().total_seconds()!=0:raise ValueError()
            except ValueError:raise Fault('INVALID_CONTEXT','occurred_at must be a UTC ISO-8601 timestamp')
        raw=req.model_dump_json(); adapted=False
        with store.tx() as db:
            old=db.execute('SELECT data FROM feedback WHERE tenant=? AND id=?',(p.tenant,req.feedback_id)).fetchone()
            if old and old['data']!=raw:raise Fault('VERSION_CONFLICT','Feedback id reused',409)
            if not old:
                db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(p.tenant,req.feedback_id,d['persona'],d['user_id'],p.actor,raw))
                store.audit(db,p.tenant,d['persona'],'feedback_recorded',{'feedback_id':req.feedback_id,'actor':p.actor,'source':req.source,'kind':req.kind,'consent_scope':req.consent_scope,'learning_consent':req.learning_consent,'received_at':datetime.now(timezone.utc).isoformat()})
                if req.learning_consent and req.kind!='rating' and req.consent_scope!='record_only':
                    data=json.loads(d['data']);adapted=adapt_session(db,p.tenant,d['persona'],d['user_id'],data['host']['adapter_id'],data['session']['id'])
        learning=req.learning_consent and req.consent_scope not in ('record_only','session')
        if learning and not old:maybe_learn(p.tenant,d['persona'],req.consent_scope,d['user_id'] if req.consent_scope=='relationship' else None)
        return wire(feedback_id=req.feedback_id,deduplicated=bool(old),learning_recorded=learning,session_adapted=adapted)
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
        # Session states and state samples built on the evidence are refitted or dropped.
        uses="EXISTS (SELECT 1 FROM json_each({}.feedback) WHERE value=?)"
        for st in db.execute('SELECT user_id,adapter,session FROM states WHERE tenant=? AND persona=? AND '+uses.format('states'),(p.tenant,persona_id,feedback_id)).fetchall():
            adapt_session(db,p.tenant,persona_id,st['user_id'] or None,st['adapter'],st['session'])
        db.execute('DELETE FROM samples WHERE tenant=? AND persona=? AND '+uses.format('samples'),(p.tenant,persona_id,feedback_id))
        if reset:db.execute('UPDATE maturation SET anchor=NULL WHERE tenant=? AND persona=?',(p.tenant,persona_id))
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
                    if e.session_id:due.update(record_experience(db,p.tenant,e.persona_id,e.user_id,req.adapter_id,e.session_id))
                    db.execute('DELETE FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',(p.tenant,e.persona_id,e.user_id or '',req.adapter_id,e.session_id))
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',(p.tenant,req.adapter_id,e.event_id,e.persona_id,raw));inserted+=1
        for persona_id,scope_name,user in sorted(due,key=str):submit_auto(p.tenant,persona_id,'maturation',scope_name,user,mature)
        return wire(inserted=inserted,deduplicated=len(req.events)-inserted)
    def record_experience(db,tenant,persona_id,user_id,adapter,session):
        """Count an ended session that received an active decision as experience (core,
        and the linked user's relationship): update each scope's life record and
        effective experience, keep the session state as a sample, and return the
        consolidation passes now due."""
        key=(tenant,persona_id,user_id or '',adapter,session)
        state_row=db.execute('SELECT * FROM states WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND session=?',key).fetchone()
        db.execute('DELETE FROM states WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND session=?',key)
        rows=db.execute("""SELECT id,data FROM decisions WHERE tenant=? AND persona=? AND user_id IS ? AND json_extract(data,'$.session.id')=? AND json_extract(data,'$.host.adapter_id')=?
            AND json_extract(data,'$.response.mode')='active' AND json_extract(data,'$.response.engine_status')!='baseline_fallback'""",(tenant,persona_id,user_id,session,adapter)).fetchall()
        if not rows:return set()
        served=[json.loads(r['data']) for r in rows]
        signatures=Counter(dev.signature(d['context']) for d in served)
        hosts=sorted({d['host']['provider_family']+'/'+d['host']['adapter_id'] for d in served})
        tags={t:sum(t in d['context']['tags'] for d in served)/len(served) for t in VOCAB['tags']}
        q=','.join('?'*len(rows))
        corrections=sum(1 for f in (json.loads(x['data']) for x in db.execute(f"SELECT data FROM feedback WHERE tenant=? AND persona=? AND valid=1 AND json_extract(data,'$.decision_id') IN ({q})",(tenant,persona_id,*[r['id'] for r in rows])))
            if f['learning_consent'] and f['kind']!='rating' and f['source'] in ('explicit_user','owner') and f['consent_scope'] in ('core','relationship'))
        # The session state becomes a habit sample only from durably consented feedback.
        sample=None;pin=db.execute('SELECT * FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',key).fetchone()
        if state_row and pin and decoder.model and pin['decoder']==decoder.hash:
            examples=session_examples(tenant,persona_id,user_id,adapter,session,('relationship','core'))
            ids=sorted(e['feedback_id'] for e in examples)
            if ids==json.loads(state_row['feedback']):sample=(state_row['delta'],state_row['feedback'])
            elif examples:sample=(json.dumps([round(v,6) for v in dev.fit_state(decoder,*pinned_latents(db,tenant,persona_id,pin),'relationship' if user_id else 'core',examples).tolist()]),json.dumps(ids))
        r=db.execute('SELECT evolution,maturation FROM personas WHERE tenant=? AND id=?',(tenant,persona_id)).fetchone(); hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None); due=set()
        now=datetime.now(timezone.utc)
        for user,scope_name in (('','core'),)+(((user_id,'relationship'),) if user_id else ()):
            if db.execute('INSERT OR IGNORE INTO experience VALUES(?,?,?,?,?)',(tenant,persona_id,user,adapter,session)).rowcount==0:continue
            db.execute('INSERT OR IGNORE INTO maturation(tenant,persona,user_id,effective) VALUES(?,?,?,0)',(tenant,persona_id,user))
            st=db.execute('SELECT * FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user)).fetchone()
            life=json.loads(st['life'] or '{}')
            weight,events=dev.observe(life,signatures,hosts,tags,corrections,now,scope_name=='relationship')
            db.execute('UPDATE maturation SET experience=experience+1,effective=?,life=? WHERE tenant=? AND persona=? AND user_id=?',(round((st['effective'] or 0)+weight,4),json.dumps(life),tenant,persona_id,user))
            if sample and (scope_name=='relationship')==bool(user_id):
                db.execute('INSERT INTO samples(tenant,persona,user_id,session,delta,feedback) VALUES(?,?,?,?,?,?)',(tenant,persona_id,user,short_id(adapter+':'+session),*sample))
            for event in events:store.audit(db,tenant,persona_id,'life_event',{'scope':scope_name,'event':event,'boost':life['boost'],'experience':st['experience']+1})
            if r['evolution']=='automatic' and decoder.model and sleep_due(tenant,persona_id,user,scope_name,hz[scope_name]):due.add((persona_id,scope_name,user or None))
        return due
    def session_examples(tenant,persona_id,user_id,adapter,session,scopes):
        """The newest valid consented preferences on one session's decisions, weighted by source influence."""
        rows=store.all("""SELECT f.data,d.data AS decision FROM feedback f JOIN decisions d ON d.tenant=f.tenant AND d.id=json_extract(f.data,'$.decision_id')
            WHERE f.tenant=? AND f.persona=? AND f.valid=1 AND f.user_id IS ? AND json_extract(d.data,'$.session.id')=? AND json_extract(d.data,'$.host.adapter_id')=? ORDER BY f.rowid DESC""",(tenant,persona_id,user_id,session,adapter))
        m=maturity_of(tenant,persona_id,user_id);out=[];seen=set()
        for row in rows:
            f=json.loads(row['data']);d=json.loads(row['decision'])
            if not f['learning_consent'] or f['consent_scope'] not in scopes or f['kind']=='rating':continue
            if d['response']['mode']=='frozen' or d['response']['engine_status']=='baseline_fallback' or d['response']['decoder_hash']!=decoder.hash:continue
            # As in training, one judgement per (decision, actor, kind) counts once; newest wins.
            if (f['decision_id'],f['actor_id'],f['kind']) in seen:continue
            seen.add((f['decision_id'],f['actor_id'],f['kind']))
            out.append({**f,'weight':dev.influence(f['source'],m),**{k:d[k] for k in ('context','host','action','habits')}})
            if len(out)==dev.STATE_WINDOW:break
        return out[::-1]
    def pinned_latents(db,tenant,persona_id,pin):
        def load(v,dim):return store.get(db.execute('SELECT hash FROM versions WHERE tenant=? AND persona=? AND id=?',(tenant,persona_id,v)).fetchone()['hash'],dim)
        return load(pin['version'],CORE_DIM),(load(pin['rel_version'],REL_DIM) if pin['rel_version'] else torch.zeros(REL_DIM))
    def adapt_session(db,tenant,persona_id,user_id,adapter,session):
        """Refit an open session's state from its consented in-session preferences. The
        state is applied at express and sampled at session end; it is never a version."""
        key=(tenant,persona_id,user_id or '',adapter,session)
        pin=db.execute('SELECT * FROM sessions WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND id=?',key).fetchone()
        examples=session_examples(tenant,persona_id,user_id,adapter,session,('session','relationship','core')) if pin and decoder.model and pin['decoder']==decoder.hash else []
        delta=dev.fit_state(decoder,*pinned_latents(db,tenant,persona_id,pin),'relationship' if user_id else 'core',examples) if examples else None
        if delta is None or float(delta.norm())==0:
            db.execute('DELETE FROM states WHERE tenant=? AND persona=? AND user_id=? AND adapter=? AND session=?',key);return False
        db.execute('INSERT OR REPLACE INTO states VALUES(?,?,?,?,?,?,?,?)',(*key,json.dumps([round(v,6) for v in delta.tolist()]),json.dumps(sorted(e['feedback_id'] for e in examples)),len(examples)))
        return True
    def maturity_of(tenant,persona_id,user_id=None):
        r=store.one('SELECT maturation FROM personas WHERE tenant=? AND id=?',(tenant,persona_id));hz=json.loads(r['maturation'] or 'null') if r else None
        row=store.one('SELECT effective FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user_id or ''))
        return maturation.maturity(row['effective'] or 0 if row else 0,(hz or maturation.horizons(None))['relationship' if user_id else 'core'])
    def temperament_version(tenant,persona_id):
        r=store.one('SELECT temperament FROM personas WHERE tenant=? AND id=?',(tenant,persona_id))
        return (r and r['temperament']) or store.one("SELECT id FROM versions WHERE tenant=? AND persona=? AND scope='core' ORDER BY rowid LIMIT 1",(tenant,persona_id))['id']
    def temperament_latent(tenant,persona_id):
        """The fixed creation latent that automatic character change stays near."""
        return store.get(store.one('SELECT hash FROM versions WHERE tenant=? AND persona=? AND id=?',(tenant,persona_id,temperament_version(tenant,persona_id)))['hash'],CORE_DIM)
    def active_latent(tenant,persona_id,user,scope_name):
        if scope_name=='core':v=store.one('SELECT active FROM personas WHERE tenant=? AND id=?',(tenant,persona_id))['active']
        else:
            rr=store.one('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user))
            if not rr:return torch.zeros(REL_DIM)
            v=rr['active']
        return store.get(store.one('SELECT hash FROM versions WHERE tenant=? AND persona=? AND id=?',(tenant,persona_id,v))['hash'],CORE_DIM if scope_name=='core' else REL_DIM)
    def profile_of(r):
        """The persona's declared profile with its recorded individual variation."""
        ind=json.loads(r['individuality'] or 'null') or dict(amount=0,seed=0)
        return dev.individual_profile(seed_profile(json.loads(r['seeds'] or '[]'),r['archetype']),ind['seed'],ind['amount'])
    def habit_window(tenant,persona_id,user):
        """Newest unconsumed state samples within the habit window, and older ones."""
        rows=store.all('SELECT rowid,delta,feedback FROM samples WHERE tenant=? AND persona=? AND user_id=? AND consumed=0 ORDER BY rowid DESC',(tenant,persona_id,user))
        return rows[:dev.HABIT_WINDOW],rows[dev.HABIT_WINDOW:]
    def sleep_due(tenant,persona_id,user,scope_name,horizon):
        """A consolidation pass is due for a curve step, pending cooling, a consistent
        habit, or (every few sessions) learned change the self anchor has not absorbed."""
        st=store.one('SELECT * FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user));life=json.loads(st['life'] or '{}')
        if maturation.due(st['effective'] or 0,horizon,st['last_m'],st['last_e'] or 0) is not None or (scope_name=='relationship' and life.get('cooling')):return True
        window,_=habit_window(tenant,persona_id,user)
        if dev.habit_step([torch.tensor(json.loads(w['delta'])) for w in window],0.0,1.0) is not None:return True
        if not st['anchor'] or st['experience']-life.get('last_sleep',0)<dev.SLEEP_EVERY:return False
        return float((active_latent(tenant,persona_id,user,scope_name)-torch.tensor(json.loads(st['anchor']))).norm())>=dev.ELASTIC_MIN
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
            examples.append({**f,'evidence_group':data['host']['adapter_id']+':'+data['session']['id'],**{k:data[k] for k in ('context','host','action','habits','selection','propensity')}})
        if auto:
            # Newer evidence weighs more; owners weigh more early and users later; agent
            # reflections gain weight and share with maturity and never outweigh
            # people's own feedback (newest reflections are kept).
            m=maturity_of(tenant,persona_id,user_id if scope_name=='relationship' else None)
            for rank,e in enumerate(examples):e['weight']=dev.recency(rank)*dev.influence(e['source'],m)
            explicit=[e for e in examples if e['source']!='agent_reflection'];reflections=[e for e in examples if e['source']=='agent_reflection']
            if explicit:examples=explicit+reflections[:int(len(explicit)*dev.reflection_share(m))]
        return examples
    def state(tenant,persona_id,user_id):
        r=store.one('SELECT * FROM personas WHERE tenant=? AND id=?',(tenant,persona_id))
        rr=store.one('SELECT active FROM relationships WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,user_id)) if user_id else None
        rv=rr['active'] if rr else None; p=system_principal(tenant,persona_id,AUTO_ACTOR)
        return r,rv,latent(p,persona_id,r['active'],CORE_DIM),latent(p,persona_id,rv,REL_DIM) if rv else torch.zeros(REL_DIM)
    def run_job(p,jid,scope_name,user_id,seed,base,relbase,core,rel,examples,auto=False):
        train,valid=group_split(examples)
        x,fit=fit_candidate(decoder,core,rel,train,scope_name,seed,policy_for(scope_name,auto).maximum_drift)
        if auto and scope_name=='core':
            # Automatic character change stays near temperament (non-expansive, so drift never grows).
            temp=temperament_latent(p.tenant,store.one('SELECT persona FROM jobs WHERE tenant=? AND id=?',(p.tenant,jid))['persona'])
            x=dev.within(x,temp,max(dev.CHARACTER_RADIUS,float((core-temp).norm())))
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
        """One sleep-like consolidation pass (engine.learning.maturation, .development):
        pending cooling, the next step on the growth curve, a consistent habit and the
        pull of the self anchor, composed into one evaluated version."""
        r,rv,core,rel=state(tenant,persona_id,user_id)
        if r is None or r['evolution']!='automatic':return skip(tenant,jid,'evolution not automatic')
        hz=json.loads(r['maturation'] or 'null') or maturation.horizons(None);horizon=hz[scope_name];key=user_id or ''
        st=store.one('SELECT * FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,key))
        life=json.loads(st['life'] or '{}');e=st['effective'] or 0;m=maturation.maturity(e,horizon)
        current=core if scope_name=='core' else rel;x=current.clone();absorbed=torch.zeros_like(x);budget=0.0;parts={};summary={};evidence=[]
        anchor=torch.tensor(json.loads(st['anchor'])) if st['anchor'] else current.clone()
        last_decision=st['last_decision'];g,at=st['last_m'],st['last_e'] or 0
        # Deliberate changes (cooling, development, habits) are absorbed into the self anchor.
        cooling=life.get('cooling',0) if scope_name=='relationship' else 0
        if cooling:
            y=x*(1-cooling);budget+=float((y-x).norm());absorbed+=y-x;x=y;parts['cooling']=cooling
        step=maturation.due_step(e,horizon,st['last_m'],at)
        if step:
            at_step,g_step=step;mm=maturation.maturity(at_step,horizon);b=maturation.step_budget(scope_name,g_step,st['last_m']);weights=dev.trait_plasticity(mm);y=None
            if scope_name=='relationship':y=maturation.familiarize(decoder,core,x,profile_of(r),mm,b,dev.accommodation_profile(life.get('tags',{}),mm),weights)
            else:
                counts={};fed={row['d'] for row in store.all("SELECT json_extract(data,'$.decision_id') AS d FROM feedback WHERE tenant=? AND persona=? AND valid=1",(tenant,persona_id))}
                for row in store.all("SELECT rowid,id,data FROM decisions WHERE tenant=? AND persona=? AND rowid>? AND json_extract(data,'$.response.mode')='active' AND json_extract(data,'$.response.engine_status')!='baseline_fallback'",(tenant,persona_id,last_decision)):
                    d=json.loads(row['data']);last_decision=max(last_decision,row['rowid'])
                    if d['response']['decoder_hash']!=decoder.hash:continue
                    # Salience-weighted replay: high stakes and decisions people gave feedback on count more.
                    host={k:d['host'][k] for k in ('provider_family','adapter_id')};k=json.dumps([d['context'],host],sort_keys=True)
                    counts[k]=counts.get(k,0)+1+(d['context']['stakes']=='high')+2*(row['id'] in fed);summary[d['context']['task_type']]=summary.get(d['context']['task_type'],0)+1
                if counts:y=maturation.habituate(decoder,x,[(*json.loads(k),c) for k,c in counts.items()],b,weights)
            if y is None:step=None  # no active decisions to habituate to: the step waits
            else:
                at,g=at_step,g_step;budget+=b;absorbed+=y-x;x=y;parts['curve']=dict(experience=at,growth=round(g,4))
        window,older=habit_window(tenant,persona_id,key);consumed=[w['rowid'] for w in older]
        deltas=[torch.tensor(json.loads(w['delta'])) for w in window];h=dev.habit_step(deltas,m,life.get('boost',1.0))
        if h is not None:
            x=x+h;absorbed+=h;budget+=float(h.norm());consumed+=[w['rowid'] for w in window]
            parts['habit']=dict(sessions=len(window),consistency=round(dev.habit(deltas)[1],3));evidence=sorted({i for w in window for i in json.loads(w['feedback'])})
        # Fade unless reinforced: learned change the anchor has not absorbed is pulled back a little.
        pull=-dev.ELASTIC*(current-anchor)
        if not parts and float((current-anchor).norm())<dev.ELASTIC_MIN:
            with store.tx() as db:
                if consumed:db.execute(f"UPDATE samples SET consumed=1 WHERE rowid IN ({','.join('?'*len(consumed))})",consumed)
            return skip(tenant,jid,'nothing to consolidate')
        temp=temperament_latent(tenant,persona_id) if scope_name=='core' else None
        def bound(v):
            if temp is not None:v=dev.within(v,temp,max(dev.CHARACTER_RADIUS,float((current-temp).norm())))
            return v*min(1.0,state_norm_limit(decoder,scope_name)/(float(v.norm())+1e-8))
        feedback=collect_examples(tenant,persona_id,scope_name,user_id)
        candidate=bound(x+pull);report=evaluate_maturation(decoder,core,rel,candidate,scope_name,budget+float(pull.norm()),feedback)
        if float(pull.norm())>=1e-6:
            parts['elastic']=round(float(pull.norm()),4)
            if not report['checks']['feedback_preserved']:
                candidate=bound(x);report=evaluate_maturation(decoder,core,rel,candidate,scope_name,budget,feedback);parts['elastic']='withheld: feedback wins'
        eligible=report['eligible'] and float((candidate-current).norm())>=1e-6
        h_artifact=store.put(candidate);p=system_principal(tenant,persona_id,MATURATION_ACTOR)
        data=dict(scope=scope_name,user_id=user_id,auto=True,kind='maturation',base_version=r['active'],base_relationship_version=rv,artifact=h_artifact,report=report,eligible=eligible,evidence_ids=evidence,
            experience=at,horizon=horizon,maturity=maturation.maturity(at,horizon),growth=g,previous_maturity=min(1.0,st['last_m']),components=parts,decoder_hash=decoder.hash)
        more=step is not None and maturation.due(e,horizon,g,at) is not None
        with store.tx() as db:
            if not db.execute('SELECT 1 FROM personas WHERE tenant=? AND id=?',(tenant,persona_id)).fetchone():store.gc();return
            db.execute('UPDATE jobs SET status=?,data=? WHERE tenant=? AND id=?',('evaluated',json.dumps(data),tenant,jid))
            life=json.loads(db.execute('SELECT life FROM maturation WHERE tenant=? AND persona=? AND user_id=?',(tenant,persona_id,key)).fetchone()['life'] or '{}')
            if cooling:life['cooling']=round(max(0.0,life.get('cooling',0)-cooling),4)
            life['last_sleep']=st['experience']
            if eligible:base=anchor+absorbed;anchor=base+dev.ANCHOR_RATE*(candidate-base)
            else:anchor=anchor+dev.ANCHOR_RATE*(current-anchor)
            # The curve advances whether or not the step was accepted: a rejected step is skipped, not retried larger.
            # While replaying a backlog, later steps reuse the same window of decisions.
            db.execute('UPDATE maturation SET last_m=?,last_e=?,last_decision=?,life=?,anchor=? WHERE tenant=? AND persona=? AND user_id=?',
                (g,at,st['last_decision'] if more else last_decision,json.dumps(life),json.dumps([round(v,6) for v in anchor.tolist()]),tenant,persona_id,key))
            if consumed:db.execute(f"UPDATE samples SET consumed=1 WHERE rowid IN ({','.join('?'*len(consumed))})",consumed)
            store.audit(db,tenant,persona_id,'matured',{'job':jid,'scope':scope_name,'maturity':round(maturation.maturity(at,horizon),4),'growth':round(g,4),'previous_maturity':round(min(1.0,st['last_m']),4),'experience':at,
                'drift':round(float((candidate-current).norm()),4),'eligible':eligible,'checks':report['checks'],'task_counts':summary,'components':parts})
            if eligible:promote_automatically(db,p,persona_id,jid,r['active'])
        # Replay any backlog, including sessions that ended while this pass ran.
        if sleep_due(tenant,persona_id,key,scope_name,horizon):submit_auto(tenant,persona_id,'maturation',scope_name,user_id,mature)
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
        if not data.get('auto'):db.execute('UPDATE maturation SET anchor=NULL WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,data.get('user_id') or ''))
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
                for row in db.execute('SELECT user_id,experience,effective FROM maturation WHERE tenant=? AND persona=?',(p.tenant,id)).fetchall():
                    e=row['effective'] if row['effective'] is not None else row['experience']
                    db.execute('UPDATE maturation SET last_m=?,last_e=? WHERE tenant=? AND persona=? AND user_id=?',(maturation.growth(e,hz['relationship' if row['user_id'] else 'core']),e,p.tenant,id,row['user_id']))
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
        if data['response']['mode']=='frozen' or data['response']['engine_status']=='baseline_fallback' or data['response']['decoder_hash']!=decoder.hash:raise Fault('INVALID_CONTEXT','Decision cannot be learned from')
        scope_name=req.scope or ('relationship' if d['user_id'] else 'core')
        if scope_name=='relationship' and not d['user_id']:raise Fault('INVALID_CONTEXT','Relationship reflection requires linked user')
        if scope_name=='core' and d['user_id'] and 'training:admin' not in p.scopes:raise Fault('FORBIDDEN_SCOPE','Core reflections on a linked user\'s turn require training administrator',403)
        served=(data['action'],tuple(data['habits']))
        moved=adjusted_choice(served,req.adjustments,data['context'],req.habits)
        if moved is None:raise Fault('INVALID_CONTEXT','No approved style moves that way in this context')
        as_choice=lambda c:Choice(controls=Controls(**levels_of(c[0])),habits=list(c[1]))
        preferred,rejected=as_choice(moved),as_choice(served)
        group=short_id(data['host']['adapter_id']+':'+data['session']['id']);fid=short_id('reflection:'+req.reflection_id);adapted=False
        f=Feedback(protocol_version=PROTOCOL,feedback_id=fid,decision_id=req.decision_id,source='agent_reflection',kind='pairwise_preference',actor_id=p.actor,consent_scope=scope_name,
            learning_consent=True,preferred=preferred,rejected=rejected,evidence_group=group,occurred_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
        with store.tx() as db:
            old=db.execute('SELECT data FROM feedback WHERE tenant=? AND id=?',(p.tenant,fid)).fetchone()
            if old:
                prior=json.loads(old['data'])
                if (prior['decision_id'],prior['preferred'],prior['consent_scope'])!=(req.decision_id,preferred.model_dump(),scope_name):raise Fault('VERSION_CONFLICT','Reflection id reused',409)
            else:
                reflected="SELECT COUNT(*) FROM feedback WHERE tenant=? AND persona=? AND json_extract(data,'$.source')='agent_reflection' AND "
                if db.execute(reflected+"json_extract(data,'$.decision_id')=?",(p.tenant,d['persona'],req.decision_id)).fetchone()[0]:raise Fault('RATE_LIMITED','One reflection per decision',429)
                if db.execute(reflected+"json_extract(data,'$.evidence_group')=?",(p.tenant,d['persona'],group)).fetchone()[0]>=REFLECTIONS_PER_SESSION:raise Fault('RATE_LIMITED',f'At most {REFLECTIONS_PER_SESSION} reflections per session',429)
                db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(p.tenant,fid,d['persona'],d['user_id'],p.actor,f.model_dump_json()))
                store.audit(db,p.tenant,d['persona'],'reflection_recorded',{'feedback_id':fid,'actor':p.actor,'reason':req.reason,'adjustments':req.adjustments,'habits':req.habits,'consent_scope':scope_name,
                    'preferred':preferred.model_dump(),'rejected':rejected.model_dump(),'received_at':datetime.now(timezone.utc).isoformat()})
                adapted=adapt_session(db,p.tenant,d['persona'],d['user_id'],data['host']['adapter_id'],data['session']['id'])
        if not old:maybe_learn(p.tenant,d['persona'],scope_name,d['user_id'] if scope_name=='relationship' else None)
        return wire(reflection_id=req.reflection_id,feedback_id=fid,deduplicated=bool(old),scope=scope_name,preferred=preferred.model_dump(),rejected=rejected.model_dump(),
            learning_recorded=True,session_adapted=adapted)
    @app.post('/v1/personas/{id}/rollbacks')
    def rollback(id:str,req:Rollback,p=Depends(principal)):
        scope(p,'persona:admin',id);persona(p,id);v=version(p,id,req.version);scope(p,'persona:admin',id,v['user_id'])
        store.get(v['hash'],CORE_DIM if v['scope']=='core' else REL_DIM)
        with store.tx() as db:
            if v['scope']=='core':db.execute('UPDATE personas SET active=? WHERE tenant=? AND id=?',(v['id'],p.tenant,id))
            else:db.execute('INSERT OR REPLACE INTO relationships VALUES(?,?,?,?)',(p.tenant,id,v['user_id'],v['id']))
            db.execute('UPDATE maturation SET anchor=NULL WHERE tenant=? AND persona=? AND user_id=?',(p.tenant,id,v['user_id'] or ''))
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
            for table in ('versions','relationships','sessions','requests','decisions','feedback','observations','jobs','experience','maturation','states','samples'):
                counts[table]=db.execute(f'DELETE FROM {table} WHERE tenant=? AND persona=?',(p.tenant,id)).rowcount
            db.execute('DELETE FROM audit WHERE tenant=? AND persona=?',(p.tenant,id))
            db.execute('DELETE FROM personas WHERE tenant=? AND id=?',(p.tenant,id));store.gc()
            store.audit(db,p.tenant,id,'deletion_completed',{'counts':counts})
        return wire(deleted=True,counts=counts,artifacts_collected=True)
    return app
