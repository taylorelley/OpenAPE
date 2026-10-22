"""persona_feedback tool through the Claude Code plugin: real HTTP engine, real hook
and MCP server subprocesses. Synthetic; no Claude Code binary or model involved."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx
import pytest
from sdk.python.client import Client
from sdk.python.lite import TOOL

ROOT=Path(__file__).resolve().parents[1]
OWNER='agent-tool-owner-token-000000000000';HOST='agent-tool-host-token-0000000000000'

@pytest.fixture
def engine(tmp_path):
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    creds=[dict(token=OWNER,tenant='local',actor='owner',scopes=['persona:express','persona:admin','feedback:write','training:admin'],personas=['*'],users=['*']),
        dict(token=HOST,tenant='local',actor='claude-host',scopes=['persona:express','observations:write','reflection:write'],personas=['ape'],users=[])]
    proc=subprocess.Popen([sys.executable,'-m','sdk.cli.main','serve','--port',str(port),'--data',str(tmp_path/'data')],cwd=ROOT,env={**os.environ,'OPENAPE_CREDENTIALS':json.dumps(creds)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    url=f'http://127.0.0.1:{port}';owner=Client(url,OWNER,timeout=10)
    try:
        for _ in range(200):
            try:owner.request('GET','/health/ready');break
            except httpx.TransportError:time.sleep(.05)
        yield url,owner
    finally:owner.close();proc.terminate();proc.wait(timeout=10)

def run(script,payload,env):
    return subprocess.run([sys.executable,str(ROOT/'adapters/claude-code'/script)],input=payload,text=True,capture_output=True,env=env,timeout=20)

def mcp(env,*messages):
    out=run('mcp_server.py','\n'.join(json.dumps(m) for m in messages)+'\n',env).stdout
    return {r['id']:r for r in map(json.loads,out.splitlines())}

def test_claude_code_agent_records_style_feedback(engine,tmp_path):
    url,owner=engine
    owner.request('POST','/v1/personas',dict(persona_id='ape',archetype='mentor'))
    env={**os.environ,'OPENAPE_TOKEN':HOST,'OPENAPE_PERSONA':'ape','OPENAPE_URL':url,'OPENAPE_MODE':'active','CLAUDE_PLUGIN_DATA':str(tmp_path/'plugin')}
    calls=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'persona_feedback','arguments':{'adjustments':{'verbosity':'less'},'reason':'user_requested'}}}]
    before=mcp(env,*calls);assert before[2]['result']['tools'][0]['inputSchema']==TOOL['parameters']
    assert before[3]['result']['isError']  # no decision yet: nothing to attach to
    hook=run('hook.py',json.dumps(dict(hook_event_name='UserPromptSubmit',session_id='cc-1',prompt_id='p1',prompt='please be brief')),env)
    assert 'additionalContext' in hook.stdout,hook
    after=mcp(env,*calls);assert not after[3]['result']['isError'],after[3]
    audit=[json.loads(a['data']) for a in owner.request('GET','/v1/personas/ape/history')['audit'] if a['action']=='reflection_recorded']
    assert audit and audit[0]['actor']=='claude-host' and audit[0]['adjustments']=={'verbosity':'less'} and audit[0]['consent_scope']=='core'
    again=mcp(env,calls[2])[3]['result'];assert not again['isError']  # same decision: idempotent
    assert len([a for a in owner.request('GET','/v1/personas/ape/history')['audit'] if a['action']=='reflection_recorded'])==1
    shadow=mcp({**env,'OPENAPE_MODE':'shadow'},calls[1]);assert shadow[2]['result']['tools']==[]
    assert mcp({**env,'OPENAPE_AGENT_FEEDBACK':'0'},calls[1])[2]['result']['tools']==[]
