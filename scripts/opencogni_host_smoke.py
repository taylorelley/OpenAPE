"""OpenCogni planner.http + OpenAPE companion smoke. Needs OPENCOGNI_DIR pointing at a
checkout of opencogni 833f4e6 with adapters/opencogni/upstream applied and installed
(pnpm install). Uses a real OpenAPE engine and a synthetic chat endpoint."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from scripts.hostkit import ROOT, Engine, SyntheticModel, count_marker, write_report

PLAN={'decision':'act','reasonCode':'restart_cause','summary':'checkout is down; restart it.','evidenceRefs':[],'steps':[{'stepId':'s1','actionType':'restart_service','args':{'service':'checkout'},'rationale':'down','dependsOnEntities':[]}]}
def main():
    repo=Path(os.environ.get('OPENCOGNI_DIR','../opencogni')).resolve()
    if not (repo/'node_modules/.bin/tsx').exists():raise SystemExit('SKIP: set OPENCOGNI_DIR to an installed opencogni checkout')
    patched='presentationStyle' in (repo/'packages/adapters/src/planner-http.ts').read_text()
    if not patched:raise SystemExit('SKIP: apply adapters/opencogni/upstream/*.patch to the OpenCogni checkout first')
    commit=subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    tmp=tempfile.mkdtemp(prefix='openape-opencogni-')
    engine=Engine(tmp,'opencogni-smoke-token-0000000000000',['cogni']);model=SyntheticModel(reply=json.dumps(PLAN))
    try:
        engine.post('/v1/personas',{'persona_id':'cogni','seed_preferences':['concise','formal']})
        env={**os.environ,'OPENCOGNI_DIR':str(repo),'OPENAPE_ROOT':str(ROOT),'OPENAPE_URL':engine.url,'OPENAPE_TOKEN':engine.token,'MODEL_URL':model.url+'/v1','NO_PROXY':'127.0.0.1,localhost'}
        def run():
            before=len(model.model_requests())
            r=subprocess.run([str(repo/'node_modules/.bin/tsx'),str(ROOT/'scripts/opencogni_host_smoke.mts')],cwd=repo,env=env,capture_output=True,text=True,timeout=120)
            if r.returncode:print(r.stdout,r.stderr)
            return r,model.model_requests()[before:]
        report=dict(host='OpenCogni planner.http',host_commit=commit,base_commit='833f4e6bb77c35f87c139e4944f80424f2ff8a30',boundary_change='adapters/opencogni/upstream/0001-planner-http-presentation-style.patch',model='synthetic chat endpoint; no provider call',checks={})
        c=report['checks']
        r,reqs=run();msgs=reqs[-1]['body']['messages'] if reqs else []
        c['plan_validated']=r.returncode==0
        c['style_separate_lower_priority_message']=[m['role'] for m in msgs]==['system','system','user'] and count_marker(msgs[1])==1 and count_marker(msgs[0])==0
        records=json.loads(r.stdout.strip().splitlines()[-1])['records'] if r.returncode==0 else []
        c['decision_and_versions_logged']=bool(records) and records[-1]['status']=='applied' and records[-1]['decisionId'] is not None and records[-1]['decoderHash'].startswith('sha256:')
        engine.stop()
        r,reqs=run();msgs=reqs[-1]['body']['messages'] if reqs else []
        c['engine_outage_fail_open']=r.returncode==0 and [m['role'] for m in msgs]==['system','user']
        report['opencogni_unit_suite']='run `pnpm test` in OPENCOGNI_DIR; integration suite needs nats-server + PostgreSQL'
        report['status']='PASS' if all(c.values()) else 'FAIL'
        write_report('opencogni-host-smoke',report)
        if report['status']!='PASS':raise SystemExit(1)
    finally:
        engine.close();model.close();shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__':main()
