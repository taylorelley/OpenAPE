#!/usr/bin/env python3
"""UserPromptSubmit context hook. Exit zero, silent on errors; no transcript I/O."""
import hashlib
import json
import os
import sys
import uuid
from sdk.python.client import Client

def main():
    data=json.load(sys.stdin)
    if data.get('hook_event_name')!='UserPromptSubmit' or not data.get('session_id'):return
    token=os.environ.get('OPENAPE_TOKEN');persona=os.environ.get('OPENAPE_PERSONA')
    if not token or not persona:return
    stable=lambda s:hashlib.sha256(s.encode()).hexdigest()[:48]
    request=dict(request_id=str(uuid.uuid4()),identity=dict(tenant_id=os.environ.get('OPENAPE_TENANT','local'),persona_id=persona),session=dict(id=stable('claude:'+data['session_id']+':'+persona),turn_id=str(uuid.uuid4())),host=dict(adapter_id='upap.claude-code',adapter_version='0.1.0',host_version=os.environ.get('OPENAPE_HOST_VERSION','unverified'),provider_family='anthropic',model_id='host-selected'),context=dict(task_type='general',channel='terminal',stakes='medium',turn_origin='user',tags=[]))
    user=os.environ.get('OPENAPE_LINKED_USER')
    if user:request['identity']['user_id']=user
    c=Client(os.environ.get('OPENAPE_URL','http://127.0.0.1:8765'),token)
    try:
        result=c.express(request,os.environ.get('OPENAPE_MODE','shadow'))
        if result['text']:print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':result['text']}}))
    finally:c.close()
if __name__=='__main__':
    try:main()
    except Exception:pass
