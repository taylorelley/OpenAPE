import json
from pathlib import Path
from engine.api import contracts as c
from engine.api.app import create_app
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'protocol/upap/v1'
for name in ['Express','Decision','Create','Feedback','Observations','Consolidate','Promote','Rollback','Export','Import']:
 (P/'schema'/f'{name.lower()}.json').write_text(json.dumps(getattr(c,name).model_json_schema(),indent=2)+'\n')
app=create_app('/tmp/openape-schema',credentials=[dict(token='schema-generator-not-a-real-secret',tenant='schema',actor='schema',scopes=[],personas=[],users=[])])
(P/'openapi.json').write_text(json.dumps(app.openapi(),indent=2)+'\n');app.state.store.db.close()
from engine.neural.policy import CATALOGUE
req=dict(protocol_version='upap/1',request_id='req-conformance',identity={'tenant_id':'local','persona_id':'ape','user_id':'alice'},session={'id':'s','turn_id':'t'},host={'adapter_id':'custom','adapter_version':'0.1','host_version':'fixture','provider_family':'other','model_id':'fixture'},context={'task_type':'general','channel':'terminal','stakes':'low','turn_origin':'user','tags':[]})
d=c.Decision(request_id=req['request_id'],decision_id='decision-1',persona_version='version-1',decoder_hash='sha256:'+'0'*64,control_set_id='style-00',controls=c.Controls(**CATALOGUE[0]),mode='active',policy=c.Policy(eligible=True,mask_reason=None),engine_status='experimental_synthetic').model_dump()
fixtures=[dict(name='valid active',valid=True,value=d),dict(name='valid shadow',valid=True,value={**d,'mode':'shadow'}),dict(name='wrong protocol',valid=False,value={**d,'protocol_version':'upap/2'}),dict(name='unknown control',valid=False,value={**d,'controls':{**d['controls'],'warmth':'unbounded'}}),dict(name='catalogue mismatch',valid=False,value={**d,'control_set_id':'style-99'}),dict(name='wrong control schema',valid=False,value={**d,'control_schema':'unknown'})]
(P/'conformance.json').write_text(json.dumps({'request':req,'decisions':fixtures},indent=2)+'\n')
(ROOT/'examples/express.json').write_text(json.dumps(req,indent=2)+'\n')
