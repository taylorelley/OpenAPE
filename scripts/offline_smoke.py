"""Real HTTP offline lifecycle + service restart, no provider credentials."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from sdk.python.client import Client
from scripts.offline_demo import demo
ROOT=Path(__file__).resolve().parents[1]
TOKEN='offline-smoke-owner-token-00000000000'
def main():
    env={**os.environ,'OPENAPE_CREDENTIALS':json.dumps([dict(token=TOKEN,tenant='local',actor='owner',scopes=['persona:express','persona:admin','feedback:write','training:admin'],personas=['*'],users=['*'])])}
    with tempfile.TemporaryDirectory() as tmp:
        def launch():
            log=open(Path(tmp)/'server.log','a')
            proc=subprocess.Popen([sys.executable,'-m','sdk.cli.main','serve','--port','18767','--data',tmp],cwd=ROOT,env=env,stdout=log,stderr=log)
            client=Client('http://127.0.0.1:18767',TOKEN,timeout=10)
            for _ in range(100):
                try:
                    client.request('GET','/health/ready');return proc,client,log
                except httpx.TransportError:time.sleep(.05)
            proc.terminate();raise RuntimeError('startup timeout')
        proc,c,log=launch()
        try:
            c.request('POST','/v1/personas',dict(persona_id='neutral-two'))
            result=demo(c)
        finally:c.close();proc.terminate();proc.wait(timeout=10);log.close()
        proc,c,log=launch()
        try:
            state=c.request('GET','/v1/personas/'+result['persona']);assert state['active_version']==result['prior']
            result['restart_persistence']='PASS';result['two_independent_personas']='PASS'
            (ROOT/'docs/reports/offline-smoke.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result,indent=2))
        finally:c.close();proc.terminate();proc.wait(timeout=10);log.close()
if __name__=='__main__':main()
