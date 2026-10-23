"""Claude subprocess contract tests; not a real Claude Code lifecycle test."""
import json
import os
import subprocess
import sys

def test_claude_hook_outage_fails_open_without_transcript_read():
    env={**os.environ,'OPENAPE_TOKEN':'offline-fixture-token-00000000000','OPENAPE_PERSONA':'ape','OPENAPE_MODE':'active','OPENAPE_URL':'http://127.0.0.1:1','CLAUDE_PLUGIN_DATA':os.environ.get('TMPDIR','/tmp')+'/openape-hook-test'}
    payload=dict(hook_event_name='UserPromptSubmit',session_id='fixture',transcript_path='/never/read/unrelated/transcript',prompt='untrusted text ignored by feature encoder')
    result=subprocess.run([sys.executable,'adapters/claude-code/hook.py'],input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=3)
    assert result.returncode==0;assert result.stdout=='';assert result.stderr==''

def test_claude_hook_invalid_json_silent():
    r=subprocess.run([sys.executable,'adapters/claude-code/hook.py'],input='invalid',text=True,capture_output=True,timeout=3)
    assert r.returncode==0;assert r.stdout==''

def test_claude_hook_subagent_and_disabled_emit_nothing(tmp_path):
    env={**os.environ,'OPENAPE_TOKEN':'offline-fixture-token-00000000000','OPENAPE_PERSONA':'ape','OPENAPE_URL':'http://127.0.0.1:1','CLAUDE_PLUGIN_DATA':str(tmp_path)}
    for extra,mode in (({'agent_id':'child'},'active'),({},'disabled')):
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','prompt_id':'p',**extra}
        r=subprocess.run([sys.executable,'adapters/claude-code/hook.py'],input=json.dumps(payload),text=True,capture_output=True,env={**env,'OPENAPE_MODE':mode},timeout=5)
        assert r.returncode==0 and r.stdout==''
    assert list(tmp_path.iterdir())==[]

def test_hermes_registers_persona_feedback_tool(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('openape_hermes',Path('adapters/hermes/__init__.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Ctx:
        hooks={};tools={}
        def register_hook(self,name,fn):self.hooks[name]=fn
        def register_tool(self,name,toolset,schema,handler,check_fn=None,description='',**_):self.tools[name]=(toolset,schema,handler,check_fn)
    for key,value in dict(OPENAPE_TOKEN='offline-fixture-token-00000000000',OPENAPE_PERSONA='ape',OPENAPE_URL='http://127.0.0.1:1',OPENAPE_MODE='active').items():monkeypatch.setenv(key,value)
    ctx=Ctx();module.register(ctx)
    toolset,schema,handler,check=ctx.tools['persona_feedback'];assert toolset=='openape' and schema['name']=='persona_feedback' and check()
    assert handler({'adjustments':{'warmth':'more'},'reason':'user_requested'},session_id='unknown').startswith('Not recorded')
    monkeypatch.setenv('OPENAPE_MODE','shadow');assert not check()

class FakeEngine:
    """Loopback UPAP engine that records request bodies and answers with a valid decision."""
    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from pathlib import Path
        decision=json.loads(Path('protocol/upap/v2/conformance.json').read_text())['decisions'][0]['value'];self.bodies=[];outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['content-length'])));outer.bodies.append((self.path,body))
                reply={**decision,'request_id':body.get('request_id'),'mode':body.get('mode','active')} if self.path=='/v1/express' else {'protocol_version':'upap/2','accepted':1}
                data=json.dumps(reply).encode();self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.url=f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def express(self):return [b for p,b in self.bodies if p=='/v1/express']

def run_hook(env,payload):
    r=subprocess.run([sys.executable,'adapters/claude-code/hook.py'],input=json.dumps(payload),text=True,capture_output=True,env=env,timeout=10)
    assert r.returncode==0 and r.stderr=='';return r.stdout

def test_claude_hook_derives_context_from_metadata_without_reading_prompt(tmp_path):
    engine=FakeEngine();state=tmp_path/'state';project=tmp_path/'project';project.mkdir()
    (project/'.openape.json').write_text(json.dumps({'tags':['expert','not-a-tag'],'channel':'teleport'}))
    env={**os.environ,'OPENAPE_TOKEN':'offline-fixture-token-00000000000','OPENAPE_PERSONA':'ape','OPENAPE_MODE':'active','OPENAPE_URL':engine.url,'CLAUDE_PLUGIN_DATA':str(state)}
    env.pop('OPENAPE_CONTEXT',None);env.pop('OPENAPE_CONTEXT_TEXT',None)
    base=dict(session_id='s',cwd=str(project),transcript_path='/never/read')
    try:
        run_hook(env,{**base,'hook_event_name':'PostToolUse','tool_name':'Edit','tool_input':{'file_path':'zz-private-path'},'tool_response':'zz-private-output'})
        for _ in range(2):run_hook(env,{**base,'hook_event_name':'PostToolUseFailure','tool_name':'Bash','tool_input':{'command':'zz-private-cmd'},'error':'zz-private-error'})
        out=run_hook(env,{**base,'hook_event_name':'UserPromptSubmit','prompt_id':'p1','prompt':'zz-private-prompt please review this PR asap'})
        assert json.loads(out)['hookSpecificOutput']['additionalContext']
        context=engine.express()[-1]['context']
        assert context==dict(task_type='debugging',channel='terminal',stakes='high',turn_origin='user',tags=['technical','expert','error_present'],language='none',repo_kind='unknown')
        run_hook(env,{**base,'hook_event_name':'UserPromptSubmit','prompt_id':'p2','prompt':'zz-private-prompt','permission_mode':'plan'})
        context=engine.express()[-1]['context']  # tool signals were consumed by the previous turn
        assert context==dict(task_type='planning',channel='terminal',stakes='medium',turn_origin='user',tags=['expert'],language='none',repo_kind='unknown')
        sent=json.dumps(engine.bodies);stored=''.join(p.read_text() for p in state.iterdir())
        assert 'zz-private' not in sent and 'zz-private' not in stored
    finally:engine.server.shutdown()

def test_claude_hook_opt_in_text_classification_sends_labels_only(tmp_path):
    engine=FakeEngine()
    env={**os.environ,'OPENAPE_TOKEN':'offline-fixture-token-00000000000','OPENAPE_PERSONA':'ape','OPENAPE_MODE':'active','OPENAPE_URL':engine.url,'CLAUDE_PLUGIN_DATA':str(tmp_path),
        'OPENAPE_CONTEXT_TEXT':'local','OPENAPE_CONTEXT':'{"stakes":"low"}'}
    try:
        run_hook(env,{'hook_event_name':'PostToolUse','session_id':'s','tool_name':'Edit'})
        run_hook(env,{'hook_event_name':'UserPromptSubmit','session_id':'s','prompt_id':'p','prompt':'zz-private-prompt: please review this PR, I am new to Go'})
        context=engine.express()[-1]['context']
        assert context==dict(task_type='code_review',channel='terminal',stakes='low',turn_origin='user',tags=['technical','review','beginner'],language='none',repo_kind='unknown')
        assert 'zz-private' not in json.dumps(engine.bodies) and 'zz-private' not in ''.join(p.read_text() for p in tmp_path.iterdir())
    finally:engine.server.shutdown()

def load_hermes():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('openape_hermes_context',Path('adapters/hermes/__init__.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Ctx:
        def __init__(self):self.hooks={}
        def register_hook(self,name,fn):self.hooks[name]=fn
    ctx=Ctx();module.register(ctx);return module,ctx.hooks

def test_hermes_derives_context_from_tool_calls_and_platform(monkeypatch):
    for key,value in dict(OPENAPE_TOKEN='offline-fixture-token-00000000000',OPENAPE_PERSONA='ape',OPENAPE_URL='http://127.0.0.1:1',OPENAPE_MODE='active').items():monkeypatch.setenv(key,value)
    monkeypatch.delenv('OPENAPE_CONTEXT_TEXT',raising=False);monkeypatch.setenv('OPENAPE_CONTEXT','{"tags":["beginner"]}')
    module,hooks=load_hermes();sent=[]
    monkeypatch.setattr(module.upap_lite,'express',lambda url,token,request,mode,**kw:sent.append(request) or {'text':'','status':'shadow','decision':None})
    hooks['post_tool_call'](session_id='h',tool_name='read_file',args={'path':'zz-private'},result='zz-private',status='ok')
    hooks['post_tool_call'](session_id='h',tool_name='terminal',args={},result='',status='error')
    hooks['post_tool_call'](session_id='h',tool_name='terminal',args={},result='',status='error')
    hooks['pre_llm_call'](session_id='h',turn_id='t1',model='m',user_message='zz-private review this',platform='telegram')
    assert sent[-1]['context']==dict(task_type='debugging',channel='chat',stakes='high',turn_origin='user',tags=['technical','beginner','error_present'],language='none',repo_kind='software')
    hooks['pre_llm_call'](session_id='h',turn_id='t2',model='m',user_message='zz-private review this',platform='cli')
    assert sent[-1]['context']==dict(task_type='general',channel='terminal',stakes='medium',turn_origin='user',tags=['beginner'],language='none',repo_kind='software')
    monkeypatch.setenv('OPENAPE_CONTEXT_TEXT','local')
    hooks['pre_llm_call'](session_id='h',turn_id='t3',model='m',user_message='zz-private review this',platform='cli')
    assert sent[-1]['context']['task_type']=='code_review' and 'zz-private' not in json.dumps(sent)

def test_untrusted_project_file_cannot_lower_stakes_or_hang_the_hook(tmp_path):
    import importlib.util,sys as _sys
    from pathlib import Path
    _sys.path.insert(0,str(Path('adapters/claude-code').resolve()))
    spec=importlib.util.spec_from_file_location('openape_claude_hook',Path('adapters/claude-code/hook.py'));hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
    from sdk.python.lite import derive_context
    project=tmp_path/'repo';project.mkdir();f=project/'.openape.json'
    f.write_text(json.dumps({'stakes':'low','channel':'voice','turn_origin':'subagent','task_type':'writing','language':'rust','tags':['beginner','first_turn']}))
    p=hook.project_context(str(project))
    ctx=derive_context({'tools':['bash'],'failures':2},{},None,project=p)
    assert ctx['stakes']=='high' and ctx['channel']=='terminal' and ctx['turn_origin']=='user'  # cannot lower stakes or impersonate the host
    assert ctx['task_type']=='debugging' and ctx['language']=='rust' and set(ctx['tags'])=={'beginner','technical','error_present'}  # host signals outrank it
    assert derive_context({},{},None,project=p)['task_type']=='writing' and derive_context({},{'stakes':'low'},None,project={'stakes':'high'})['stakes']=='low'  # the user's own declaration still wins
    f.unlink();os.mkfifo(f);assert hook.project_context(str(project))=={}  # a FIFO would block a plain read
    f.unlink();(tmp_path/'secret.json').write_text('{"tags":["expert"]}');f.symlink_to(tmp_path/'secret.json');assert hook.project_context(str(project))=={}
    f.unlink();f.write_text('{"tags":["expert"],"pad":"'+'x'*70000+'"}');assert hook.project_context(str(project))=={}  # over 64 KB
    f.write_text('['*60000+']'*60000);assert hook.project_context(str(project))=={}  # nesting beyond the recursion limit
