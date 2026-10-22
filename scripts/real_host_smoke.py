"""Start a real HTTP engine, then exercise the installed Pi host with synthetic model I/O."""
import json
import os
import subprocess
import sys
import tempfile
import time
import httpx
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOKEN='offline-host-smoke-token-000000000000'
def main():
    env={**os.environ,'OPENAPE_CREDENTIALS':json.dumps([dict(token=TOKEN,tenant='local',actor='host-smoke',scopes=['persona:express','persona:admin','observations:write','reflection:write'],personas=['host-smoke'],users=[])]),'OPENAPE_TOKEN':TOKEN,'OPENAPE_URL':'http://127.0.0.1:18765'}
    with tempfile.TemporaryDirectory() as tmp:
        log=open(Path(tmp)/'server.log','w')
        proc=subprocess.Popen([sys.executable,'-m','sdk.cli.main','serve','--port','18765','--data',tmp],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url=env['OPENAPE_URL'],headers={'Authorization':'Bearer '+TOKEN},trust_env=False) as c:
                for _ in range(100):
                    try:
                        if c.get('/health/ready').status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.1)
                else:raise RuntimeError('engine startup timed out')
                c.post('/v1/personas',json={'protocol_version':'upap/1','persona_id':'host-smoke','archetype':'balanced','evolution':'manual'}).raise_for_status()
                result=subprocess.run(['node','scripts/pi_host_smoke.mjs'],cwd=ROOT,env={**env,'OPENAPE_SMOKE_ENGINE_PID':str(proc.pid)},capture_output=True,text=True,timeout=45)
                print(result.stdout);print(result.stderr,file=sys.stderr)
                if result.returncode:raise SystemExit(result.returncode)
                import sqlite3
                db=sqlite3.connect(Path(tmp)/'openape.sqlite')
                assert db.execute('SELECT count(*) FROM decisions').fetchone()[0]>=1
                assert db.execute('SELECT count(*) FROM observations').fetchone()[0]>=1
                sessions=db.execute("SELECT count(DISTINCT json_extract(data,'$.session.id')) FROM decisions").fetchone()[0]
                versions=db.execute("SELECT count(DISTINCT json_extract(data,'$.response.persona_version')) FROM decisions").fetchone()[0]
                assert sessions>=2 and versions==1,(sessions,versions)
                assert db.execute("SELECT count(*) FROM feedback WHERE json_extract(data,'$.source')='agent_reflection'").fetchone()[0]==1
                db.close();print('PASS: real engine recorded host decisions for 2 sessions on one persona version, plus canonical observations')
                (ROOT/'docs/reports/pi-native-smoke.txt').write_text(result.stdout.strip()+'\nPASS: engine ledger: >=2 host sessions, one persona version, observations recorded\n')
        finally:proc.terminate();proc.wait(timeout=10);log.close()
if __name__=='__main__':main()
