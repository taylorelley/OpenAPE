"""Warm real HTTP and direct neural latency. No LLM calls. Writes measured report."""
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
import numpy as np
import torch
from engine.neural.policy import Decoder
ROOT=Path(__file__).resolve().parents[1]
def main():
    token='performance-local-token-000000000000'
    env={**os.environ,'OPENAPE_CREDENTIALS':json.dumps([dict(token=token,tenant='local',actor='bench',scopes=['persona:express','persona:admin'],personas=['ape'],users=['alice'])])}
    with tempfile.TemporaryDirectory() as tmp:
        start=time.perf_counter()
        with open(Path(tmp)/'server.log','w') as log:
            proc=subprocess.Popen([sys.executable,'-m','sdk.cli.main','serve','--port','18766','--data',tmp],env=env,cwd=ROOT,stdout=log,stderr=log)
            try:
                with httpx.Client(base_url='http://127.0.0.1:18766',headers={'Authorization':'Bearer '+token},trust_env=False) as c:
                    for _ in range(100):
                        try:
                            if c.get('/health/ready').status_code==200:break
                        except httpx.TransportError:pass
                        time.sleep(.05)
                    else:raise RuntimeError('Startup timeout')
                    cold=time.perf_counter()-start
                    c.post('/v1/personas',json=dict(protocol_version='upap/2',persona_id='ape',archetype='balanced',evolution='manual')).raise_for_status()
                    req=json.loads((ROOT/'examples/express.json').read_text());req['mode']='active';latencies=[]
                    for i in range(520):
                        req['request_id']=f'perf-{i}';req['session']['turn_id']=f'turn-{i}'
                        start=time.perf_counter();r=c.post('/v1/express',json=req);r.raise_for_status()
                        if i>=20:latencies.append((time.perf_counter()-start)*1000)
                    d=Decoder(ROOT/'models/decoder-v3/decoder.safetensors');neural=[]
                    with torch.no_grad():
                        for _ in range(520):
                            start=time.perf_counter();d.logits(torch.zeros(64),torch.zeros(32),req['context'],req['host']);neural.append((time.perf_counter()-start)*1000)
                    def summary(x):return dict(n=len(x),p50_ms=float(np.quantile(x,.5)),p95_ms=float(np.quantile(x,.95)),max_ms=max(x))
                    cpu=next((l.split(':',1)[1].strip() for l in Path('/proc/cpuinfo').read_text().splitlines() if l.startswith('model name')),'unknown')
                    report=dict(platform=platform.platform(),python=platform.python_version(),cpu=cpu,torch=torch.__version__,cold_start_ready_seconds=cold,http_warm=summary(latencies),neural_warm=summary(neural[20:]),targets={'http_p95_ms':75,'neural_p95_ms':25},load='single client, 500 measured requests, SQLite decisions persisted',added_style_tokens='renderer <=150 whitespace tokens; tokenizer-specific costs unmeasured',behavioral_benefit='not measured')
                    (ROOT/'benchmarks/reports/performance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
            finally:proc.terminate();proc.wait(timeout=10)
if __name__=='__main__':main()
