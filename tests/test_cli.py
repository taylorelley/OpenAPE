import json
import os
import stat
import subprocess
import sys
from pathlib import Path

def test_init_private_credentials_and_refuses_overwrite(tmp_path):
    command=[sys.executable,'-m','sdk.cli.main','init']
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
    result=subprocess.run(command,cwd=tmp_path,env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    folder=tmp_path/'.openape';local=folder/'credentials.json';docker=folder/'docker-credentials.json'
    assert stat.S_IMODE(folder.stat().st_mode)==0o700
    assert stat.S_IMODE(local.stat().st_mode)==0o600
    assert stat.S_IMODE(docker.stat().st_mode)==0o444
    assert json.loads(local.read_text())==json.loads(docker.read_text())
    assert json.loads(local.read_text())[0]['token'] not in result.stdout
    repeat=subprocess.run(command,cwd=tmp_path,env=env,text=True,capture_output=True)
    assert repeat.returncode!=0;assert 'refusing overwrite' in repeat.stderr.lower()

def test_token_add_appends_scoped_credential(tmp_path):
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
    run=lambda *a:subprocess.run([sys.executable,'-m','sdk.cli.main',*a],cwd=tmp_path,env=env,text=True,capture_output=True)
    assert run('init').returncode==0
    r=run('token','add','--actor','pi-host','--personas','ape');assert r.returncode==0,r.stderr
    token=json.loads(r.stdout)['token'];records=json.loads((tmp_path/'.openape/credentials.json').read_text())
    assert records[1]==dict(token=token,tenant='local',actor='pi-host',scopes=['persona:express','observations:write'],personas=['ape'],users=[])
    assert stat.S_IMODE((tmp_path/'.openape/credentials.json').stat().st_mode)==0o600
    assert stat.S_IMODE((tmp_path/'.openape/docker-credentials.json').stat().st_mode)==0o444
    assert json.loads((tmp_path/'.openape/docker-credentials.json').read_text())==records
    assert run('token','add','--actor','pi-host','--personas','ape').returncode!=0
    assert run('token','add','--actor','x','--personas','ape','--scopes','root').returncode!=0

def test_soul_analysis_keeps_operational_lines():
    from sdk.cli.adapters import analyse_soul
    a=analyse_soul('You are Hermes.\nBe warm and friendly.\nKeep answers concise.\nAlways run tests before you commit code.\nBe concise when reporting tool results.\nBe detailed and thorough.')
    assert a['seeds']==['warm'] and a['conflicting_dropped']==['concise','detailed']
    assert 'Always run tests before you commit code.' in a['retained_lines'] and 'Be concise when reporting tool results.' in a['retained_lines']
    assert 'Be warm and friendly.' in a['style_lines']
