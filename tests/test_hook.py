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
