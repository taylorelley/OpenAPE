import pytest
from fastapi.testclient import TestClient
from engine.api.app import create_app
TOKEN='test-owner-token-0000000000000000'
USER_TOKEN='test-user-token-0000000000000000'
OTHER_TOKEN='other-tenant-token-00000000000000'
CREDENTIALS=[dict(token=TOKEN,tenant='local',actor='owner',scopes=['persona:express','observations:write','feedback:write','persona:admin','training:admin','reflection:write'],personas=['*'],users=['*']),dict(token=USER_TOKEN,tenant='local',actor='alice',scopes=['persona:express','feedback:write','observations:write'],personas=['ape'],users=['alice']),dict(token=OTHER_TOKEN,tenant='other',actor='owner',scopes=['persona:express','persona:admin'],personas=['*'],users=['*'])]
@pytest.fixture
def api(tmp_path):
    app=create_app(tmp_path,credentials=CREDENTIALS)
    with TestClient(app,headers={'Authorization':'Bearer '+TOKEN}) as c:
        yield c

def post(api,path,data):return api.post(path,json={'protocol_version':'upap/1',**data})
def expression(request_id='req-1',persona='ape',user='alice',session='session-1',mode='active'):
    return dict(protocol_version='upap/1',request_id=request_id,identity={'tenant_id':'local','persona_id':persona,'user_id':user},session={'id':session,'turn_id':'turn-1'},host={'adapter_id':'custom','adapter_version':'0.1','host_version':'fixture','provider_family':'anthropic','model_id':'fixture'},context={'task_type':'general','channel':'terminal','stakes':'low','turn_origin':'user','tags':[]},mode=mode)
