import json
from pathlib import Path
from engine.api import contracts as c
from engine.api.app import create_app
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'protocol/upap/v2'
for name in ['Express','Decision','Create','Feedback','Observations','Consolidate','Promote','Rollback','Export','Import','Evolution','Reflection','Settings']:
 (P/'schema'/f'{name.lower()}.json').write_text(json.dumps(getattr(c,name).model_json_schema(),indent=2)+'\n')
import tempfile
with tempfile.TemporaryDirectory(prefix='openape-schema-') as tmp:
 app=create_app(tmp,credentials=[dict(token='schema-generator-not-a-real-secret',tenant='schema',actor='schema',scopes=[],personas=[],users=[])])
 (P/'openapi.json').write_text(json.dumps(app.openapi(),indent=2)+'\n');app.state.store.db.close()
from protocol.catalogue import SPEC, NEUTRAL, CATALOGUE_HASH
(ROOT/'renderers/controls-v2.json').write_text(json.dumps(SPEC,indent=2)+'\n')
req=dict(protocol_version='upap/2',request_id='req-conformance',identity={'tenant_id':'local','persona_id':'ape','user_id':'alice'},session={'id':'s','turn_id':'t'},host={'adapter_id':'custom','adapter_version':'0.1','host_version':'fixture','provider_family':'other','model_id':'fixture'},context={'task_type':'general','channel':'terminal','stakes':'low','turn_origin':'user','tags':[]})
d=c.Decision(request_id=req['request_id'],decision_id='decision-1',persona_version='version-1',decoder_hash='sha256:'+'0'*64,catalogue_hash=CATALOGUE_HASH,controls=c.Controls(**NEUTRAL),habits=[],mode='active',policy=c.Policy(eligible=True,mask_reason=None),engine_status='experimental_synthetic').model_dump()
from sdk.python.client import render
warm={**d,'controls':{**NEUTRAL,'warmth':4,'verbosity':3},'habits':['next_step','recap_end']}
extreme={**d,'mode':'frozen','controls':{'directness':4,'warmth':3,'verbosity':4,'humour':4,'formality':0,'explanation_depth':4,'assertiveness':4},'habits':['acknowledge_constraints','acknowledge_progress','light_aside']}
prefs={**warm,'preferences':{'spelling':'british','format':'code_first','units':'metric','address':'informal','dates':'iso'}}
valid=[('valid active neutral',d),('valid habits',warm),('valid shadow',{**d,'mode':'shadow'}),('valid frozen extreme with three habits',extreme),('valid with every preference',prefs),
 ('valid formal and reserved',{**d,'controls':{**NEUTRAL,'warmth':0,'formality':4}})]
invalid=[('ineligible policy',{**d,'policy':{'eligible':False,'mask_reason':None}}),('missing control',{**d,'controls':{k:v for k,v in d['controls'].items() if k!='humour'}}),
 ('level out of range',{**d,'controls':{**NEUTRAL,'warmth':5}}),('level as text',{**d,'controls':{**NEUTRAL,'warmth':'high'}}),('level as boolean',{**d,'controls':{**NEUTRAL,'humour':False}}),
 ('incoherent configuration',{**d,'controls':{**NEUTRAL,'verbosity':0,'explanation_depth':4}}),('unknown habit',{**d,'habits':['summarise_everything']}),
 ('habits out of catalogue order',{**warm,'habits':['recap_end','next_step']}),('duplicate habit',{**d,'habits':['next_step','next_step']}),
 ('habit ineligible for levels',{**d,'habits':['light_aside']}),('mutually exclusive habits',{**d,'habits':['plain_words','precise_terms']}),
 ('four habits',{**warm,'habits':['risks_first','next_step','structured','recap_end']}),('habits missing',{k:v for k,v in d.items() if k!='habits'}),
 ('cache ttl above bound',{**d,'cache_ttl_ms':999999}),('disabled is not a wire mode',{**d,'mode':'disabled'}),('wrong protocol',{**d,'protocol_version':'upap/1'}),
 ('wrong control schema',{**d,'control_schema':'behaviour-controls/1'}),('unknown preference slot',{**d,'preferences':{'tone':'snarky'}}),
 ('unknown preference value',{**d,'preferences':{'spelling':'klingon'}}),('preferences missing',{k:v for k,v in d.items() if k!='preferences'}),('wrong catalogue hash',{**d,'catalogue_hash':'sha256:'+'1'*64})]
fixtures=[dict(name=n,valid=True,value=v,rendered=render(v),rendered_with_example=render(v,example=True)) for n,v in valid]+[dict(name=n,valid=False,value=v) for n,v in invalid]
(ROOT/'examples/express.json').write_text(json.dumps(req,indent=2)+'\n')
from sdk.python.lite import TOOL, CONTEXT_RULES, derive_context
(P/'tools').mkdir(exist_ok=True);(P/'tools/persona_feedback.json').write_text(json.dumps(TOOL,indent=2)+'\n')
(P/'context-rules.json').write_text(json.dumps(CONTEXT_RULES,indent=2)+'\n')
# Context derivation parity: Python and TypeScript SDKs must produce identical contexts.
cases=[('defaults',None,None,None),('one failure tags an error',{'tools':['bash'],'failures':1},None,None),('engine tags cannot be declared',None,{'tags':['first_turn','long_session','expert']},None),
 ('text debugging',None,None,'this test is failing with a traceback'),('text planning',None,None,'help me plan the migration roadmap'),('text writing',None,None,'draft an email to the team'),('edit tools mean coding',{'tools':['Edit','Bash']},None,None),('read-only tools mean research',{'tools':['Read','Grep','WebFetch']},None,None),
 ('edit outranks read',{'tools':['grep','write']},None,None),('plan mode',{'tools':['Edit'],'plan_mode':True},None,None),('one failure keeps stakes',{'tools':['bash'],'failures':1},None,None),
 ('repeated failures raise stakes',{'tools':['bash'],'failures':2},None,None),('host channel and origin',{'channel':'voice','turn_origin':'subagent'},None,None),
 ('unknown signals ignored',{'channel':'fax','turn_origin':'x','tools':'Edit','failures':'9','plan_mode':'yes'},None,None),
 ('declaration wins',{'tools':['Edit'],'failures':3},{'task_type':'support','stakes':'low','tags':['beginner','nonsense']},None),
 ('malformed declaration dropped',None,'{not json',None),('declaration as JSON text',None,'{"tags":["expert"],"channel":"chat"}',None),
 ('text review urgent',None,None,'Please review this PR asap, prod is down'),('text beats tools',{'tools':['Edit']},None,'Can you research how does tokio schedule tasks?'),
 ('text sensitive',None,None,'rotate the production database password'),('text beginner',None,None,"I'm new to Rust, explain like I'm five"),
 ('text expert',None,None,'tl;dr please, just the code'),('text word boundaries',None,None,'prepare the preview of reviewer stats'),
 ('text non-ascii',None,None,'Révisez ce code, ÜRGENT'),('declaration beats text',None,{'task_type':'creative'},'review this')]
cases+=[('edited python and markdown',{'tools':['Edit'],'extensions':['py','PY','md']},None,None),('language tie breaks by vocabulary order',{'extensions':['go','rs']},None,None),
 ('unknown extensions ignored',{'extensions':['exe','','..']},None,None),('infrastructure repo wins over software',{'repo_files':['package.json','main.tf']},None,None),
 ('notebook suffix means data science',{'repo_files':['analysis.ipynb','readme.md']},None,None),('declared language and repo',None,{'language':'rust','repo_kind':'documentation'},None),
 ('classifier sees review',None,None,'could you look over my pull request before I merge it'),('classifier urgent and sensitive raise stakes',None,None,'asap: the production database password leaked'),
 ('classifier beginner',None,None,"I'm new to Kubernetes, how do pods restart?"),('classifier on empty words',None,None,'!!! ??? ...')]
contexts=[dict(name=n,signals=s,declared=d,text=t,context=derive_context(s,d,t)) for n,s,d,t in cases]
# A project file (e.g. a repository's .openape.json) is untrusted: it cannot lower stakes or set channel/origin.
projects=[('project cannot lower stakes or impersonate the host',{'tools':['bash'],'failures':2},None,'{"stakes":"low","channel":"voice","turn_origin":"subagent","tags":["beginner"]}'),
 ('project fills task language and repo kind',None,None,{'task_type':'writing','language':'rust','repo_kind':'documentation','stakes':'medium'}),
 ('host signals outrank the project',{'tools':['Edit'],'extensions':['py'],'repo_files':['main.tf']},None,{'task_type':'writing','language':'rust','repo_kind':'documentation'}),
 ('user declaration outranks the project',None,{'stakes':'low','task_type':'support'},{'stakes':'high','task_type':'writing'}),
 ('malformed project dropped',None,None,'['*3000+']'*3000)]
contexts+=[dict(name=n,signals=s,declared=d,text=None,project=pr,context=derive_context(s,d,None,project=pr)) for n,s,d,pr in projects]
from sdk.python.lite import classify_text
probes=['Review this diff please','write a Go function that retries with backoff','why does my test fail with KeyError','draft an email to the team about the outage',
 'brainstorm names for our CLI','I am stuck and frustrated','compare Postgres and MySQL','plan the migration to Kubernetes','thanks!','URGENT prod is down',
 'Révisez ce code, ÜRGENT','Ǆ ǅ ǆ İstanbul ﬁle KELVIN K','tl;dr just the code','a'*500,' '.join(['word']*400),'']
classifier_cases=[dict(text=t,result=list(r) if (r:=classify_text(t)) else None) for t in probes]
(P/'conformance.json').write_text(json.dumps({'request':req,'decisions':fixtures,'contexts':contexts,'classifier':classifier_cases},indent=2)+'\n')
