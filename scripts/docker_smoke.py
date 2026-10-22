"""Run after openape init && docker compose up --build -d. No provider call."""
import json
import time
import uuid
from pathlib import Path
import httpx
from sdk.python.client import Client

def main():
    credentials=json.loads(Path('.openape/credentials.json').read_text())
    c=Client('http://127.0.0.1:8765',credentials[0]['token'],timeout=5)
    try:
        for _ in range(100):
            try:
                ready=c.request('GET','/health/ready')
                if ready['engine_status']=='experimental_synthetic':break
            except httpx.TransportError:pass
            time.sleep(.1)
        else:raise RuntimeError('Trained decoder not ready')
        assert c.request('GET','/v1/capabilities')['engine_status']=='experimental_synthetic'
        persona='docker-smoke-'+uuid.uuid4().hex[:8]
        c.request('POST','/v1/personas',{'persona_id':persona,'archetype':'balanced'})
        req=json.loads(Path('examples/express.json').read_text());req['identity']['persona_id']=persona
        decision=c.request('POST','/v1/express',req)
        assert decision['engine_status']=='experimental_synthetic'
        assert httpx.get('http://127.0.0.1:8765/v1/capabilities',trust_env=False).status_code==401
        report=dict(image='openape:0.2.0',health='PASS',auth='PASS',create='PASS',neural_express='PASS',decoder_hash=decision['decoder_hash'],persona_id=persona,evidence='Actual Docker HTTP service; no LLM/model-provider call')
        Path('docs/reports/docker-smoke.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:c.close()
if __name__=='__main__':main()
