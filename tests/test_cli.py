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
