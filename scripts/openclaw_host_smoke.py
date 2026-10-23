"""Real OpenClaw CLI (`openclaw agent --local`) + OpenAPE plugin against a synthetic
OpenAI-compatible endpoint. Requires Node >=24.16 (set OPENCLAW_NODE_BIN to its bin
directory if `node` on PATH is older). Installs openclaw@2026.10.5 into
.host-test/openclaw once. NOT live-model evidence.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from scripts.hostkit import ROOT, Engine, SyntheticModel, count_marker, write_report

OPENCLAW_VERSION='2026.10.5'
def environment():
    path=(os.environ['OPENCLAW_NODE_BIN']+':' if os.environ.get('OPENCLAW_NODE_BIN') else '')+os.environ['PATH']
    major,minor=map(int,subprocess.run(['node','--version'],capture_output=True,text=True,env={'PATH':path}).stdout.strip().lstrip('v').split('.')[:2])
    if (major,minor)<(24,16):raise SystemExit('SKIP: OpenClaw needs Node >=24.16; set OPENCLAW_NODE_BIN')
    target=ROOT/'.host-test/openclaw'
    if not (target/'node_modules/.bin/openclaw').exists():
        target.mkdir(parents=True,exist_ok=True)
        subprocess.run(['npm','install','--no-audit','--no-fund','--prefix',str(target),f'openclaw@{OPENCLAW_VERSION}'],check=True,env={**os.environ,'PATH':path})
    return path,str(target/'node_modules/.bin/openclaw')

def main():
    path,openclaw=environment();tmp=tempfile.mkdtemp(prefix='openape-openclaw-');home=Path(tempfile.mkdtemp(prefix='openape-openclaw-home-'))
    engine=Engine(tmp,'openclaw-smoke-token-00000000000000',['oc']);model=SyntheticModel()
    try:
        engine.post('/v1/personas',{'persona_id':'oc','seed_preferences':['concise','direct']})
        config={'models':{'mode':'merge','providers':{'fixture':{'baseUrl':model.url+'/v1','apiKey':'synthetic-transport-not-a-key','api':'openai-completions',
                'models':[{'id':'synthetic-model','name':'Synthetic','reasoning':False,'input':['text'],'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0},'contextWindow':100000,'maxTokens':1000}]}}},
            'agents':{'defaults':{'model':{'primary':'fixture/synthetic-model'}}},
            # Mirrors adapters/openclaw/config.example.json; grants stay in host config.
            'plugins':{'allow':['openape'],'load':{'paths':[str(ROOT/'adapters/openclaw')]},'entries':{'openape':{'enabled':True,'hooks':{'allowPromptInjection':True,'allowConversationAccess':True}}}}}
        (home/'.openclaw').mkdir();(home/'.openclaw/openclaw.json').write_text(json.dumps(config))
        def run(prompt,session,mode='active'):
            env={'PATH':path,'HOME':str(home),'OPENCLAW_HOME':str(home),'NO_PROXY':'127.0.0.1,localhost','OPENAPE_TOKEN':engine.token,'OPENAPE_PERSONA':'oc','OPENAPE_URL':engine.url,'OPENAPE_MODE':mode}
            before=len(model.model_requests())
            r=subprocess.run([openclaw,'agent','--local','--message',prompt,'--session-id',session,'--json'],cwd=tmp,env=env,capture_output=True,text=True,timeout=300,stdin=subprocess.DEVNULL)
            return dict(code=r.returncode,out=r.stdout,requests=model.model_requests()[before:])
        def tools(req):return sorted(t.get('function',{}).get('name','') for t in req['body'].get('tools') or [])
        def decisions():return [json.loads(r['data'])['response'] for r in engine.rows("SELECT data FROM decisions ORDER BY rowid")]
        report=dict(host='OpenClaw',host_version=OPENCLAW_VERSION,runner='embedded (openclaw agent --local)',model='synthetic OpenAI-compatible endpoint; no provider call',checks={})
        c=report['checks']
        first=run('Fixture request one. Reply briefly.','smoke-1')
        c['turn_completes']=first['code']==0 and 'Synthetic host transport response.' in first['out']
        c['style_reached_model_once']=count_marker(first['requests'][-1]['body'])==1
        system=' '.join(m['content'] for m in first['requests'][-1]['body']['messages'] if m.get('role')=='system' and isinstance(m.get('content'),str))
        report['style_location']='system' if count_marker(system) else 'conversation'
        second=run('Fixture request two.','smoke-1')
        last_user=[m for m in second['requests'][-1]['body']['messages'] if m.get('role')=='user'][-1]
        c['second_turn_single_copy']=second['code']==0 and count_marker(last_user)==1
        # OpenClaw persists appendContext inside each stored user message, so earlier
        # turns keep their copy (history growth ~1 style block per turn).
        report['history_style_copies_turn_two']=count_marker(second['requests'][-1]['body'])
        disabled=run('Disabled fixture request.','smoke-2',mode='disabled')
        # Direct tool schemas are unchanged; OpenClaw's Tool Search directory (embedded default)
        # lists OpenAPE's one plugin tool, persona_feedback, in active mode only.
        c['tool_surface_unchanged']=tools(first['requests'][-1])==tools(disabled['requests'][-1])
        c['persona_feedback_in_tool_catalog']='persona_feedback' in json.dumps(first['requests'][-1]['body']) and 'persona_feedback' not in json.dumps(disabled['requests'][-1]['body'])
        c['disabled_makes_no_engine_call']=count_marker(disabled['requests'][-1]['body'])==0 and len(decisions())==2
        shadow=run('Shadow fixture request.','smoke-3',mode='shadow')
        c['shadow_records_without_injection']=count_marker(shadow['requests'][-1]['body'])==0 and decisions()[-1]['mode']=='shadow'
        obs=[json.loads(r['data']) for r in engine.rows('SELECT data FROM observations ORDER BY rowid')]
        report['observations']=sorted({o['type'] for o in obs})
        c['decision_linked_turn_completed']=any(o['type']=='turn.completed' and o['decision_id']==decisions()[0]['decision_id'] for o in obs)
        fb=engine.post('/v1/feedback',dict(feedback_id='openclaw-smoke-feedback',decision_id=decisions()[0]['decision_id'],source='owner',kind='pairwise_preference',actor_id='host-smoke',consent_scope='core',learning_consent=True,preferred={'controls':dict(directness=2,warmth=3,verbosity=3,humour=0,formality=1,explanation_depth=3,assertiveness=1),'habits':[]},rejected={'controls':decisions()[0]['controls'],'habits':decisions()[0]['habits']},evidence_group='openclaw-smoke'))
        c['approved_feedback_linked_to_host_decision']=fb['learning_recorded'] is True
        engine.stop()
        outage=run('Engine outage fixture request.','smoke-4')
        c['engine_outage_fail_open']=outage['code']==0 and 'Synthetic host transport response.' in outage['out'] and count_marker(outage['requests'][-1]['body'])==0
        report['status']='PASS' if all(c.values()) else 'FAIL'
        write_report('openclaw-host-smoke',report)
        if report['status']!='PASS':raise SystemExit(1)
    finally:
        engine.close();model.close();shutil.rmtree(home,ignore_errors=True)
if __name__=='__main__':main()
