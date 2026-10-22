import json
from pathlib import Path
from engine.api import contracts as c
from engine.api.app import create_app
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'protocol/upap/v1'
for name in ['Express','Decision','Create','Feedback','Observations','Consolidate','Promote','Rollback','Export','Import','Evolution','Reflection']:
 (P/'schema'/f'{name.lower()}.json').write_text(json.dumps(getattr(c,name).model_json_schema(),indent=2)+'\n')
app=create_app('/tmp/openape-schema',credentials=[dict(token='schema-generator-not-a-real-secret',tenant='schema',actor='schema',scopes=[],personas=[],users=[])])
(P/'openapi.json').write_text(json.dumps(app.openapi(),indent=2)+'\n');app.state.store.db.close()
from engine.neural.policy import CATALOGUE
req=dict(protocol_version='upap/1',request_id='req-conformance',identity={'tenant_id':'local','persona_id':'ape','user_id':'alice'},session={'id':'s','turn_id':'t'},host={'adapter_id':'custom','adapter_version':'0.1','host_version':'fixture','provider_family':'other','model_id':'fixture'},context={'task_type':'general','channel':'terminal','stakes':'low','turn_origin':'user','tags':[]})
d=c.Decision(request_id=req['request_id'],decision_id='decision-1',persona_version='version-1',decoder_hash='sha256:'+'0'*64,control_set_id='style-00',controls=c.Controls(**CATALOGUE[0]),mode='active',policy=c.Policy(eligible=True,mask_reason=None),engine_status='experimental_synthetic').model_dump()
from sdk.python.client import render
d23={**d,'control_set_id':'style-23','controls':CATALOGUE[23]}
fixtures=[dict(name='valid active',valid=True,value=d,rendered=render(d)),dict(name='valid shadow',valid=True,value={**d,'mode':'shadow'},rendered=''),dict(name='valid frozen last catalogue row',valid=True,value={**d23,'mode':'frozen'},rendered=render({**d23,'mode':'frozen'})),
 dict(name='ineligible policy',valid=False,value={**d,'policy':{'eligible':False,'mask_reason':None}}),dict(name='missing control',valid=False,value={**d,'controls':{k:v for k,v in d['controls'].items() if k!='humour'}}),
 dict(name='cache ttl above bound',valid=False,value={**d,'cache_ttl_ms':999999}),dict(name='controls from another row',valid=False,value={**d,'controls':CATALOGUE[1]}),dict(name='disabled is not a wire mode',valid=False,value={**d,'mode':'disabled'}),dict(name='wrong protocol',valid=False,value={**d,'protocol_version':'upap/2'}),dict(name='unknown control',valid=False,value={**d,'controls':{**d['controls'],'warmth':'unbounded'}}),dict(name='catalogue mismatch',valid=False,value={**d,'control_set_id':'style-99'}),dict(name='wrong control schema',valid=False,value={**d,'control_schema':'unknown'})]
(P/'conformance.json').write_text(json.dumps({'request':req,'decisions':fixtures},indent=2)+'\n')
(ROOT/'examples/express.json').write_text(json.dumps(req,indent=2)+'\n')
from sdk.python.lite import TOOL
(P/'tools').mkdir(exist_ok=True);(P/'tools/persona_feedback.json').write_text(json.dumps(TOOL,indent=2)+'\n')
