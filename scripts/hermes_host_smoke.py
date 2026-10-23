"""Real Hermes Agent CLI + OpenAPE plugin against a synthetic OpenAI-compatible endpoint.

Installs hermes-agent==0.19.0 into .host-test/hermes-venv (once), copies the plugin
with `openape adapter install hermes` into an isolated HERMES_HOME, enables it in
config, and runs `hermes chat -q`. Proves which style text reached the model
transport, SOUL.md coexistence, prompt-cache prefix stability, migration with
backup, observations and outage fail-open. NOT live-model evidence.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from scripts.hostkit import ROOT, Engine, SyntheticModel, count_marker, write_report

HERMES_VERSION='0.19.0'
SOUL='You are Hermes, the project assistant.\nBe warm and friendly.\nAlways run tests before you commit code.\n'
def hermes_bin():
    if os.environ.get('HERMES_BIN'):return os.environ['HERMES_BIN']
    venv=ROOT/'.host-test/hermes-venv'
    if not (venv/'bin/hermes').exists():
        subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
        subprocess.run([str(venv/'bin/pip'),'install','-q',f'hermes-agent=={HERMES_VERSION}'],check=True)
    return str(venv/'bin/hermes')

def main():
    hermes=hermes_bin();tmp=tempfile.mkdtemp(prefix='openape-hermes-');home=Path(tempfile.mkdtemp(prefix='openape-hermes-home-'))
    engine=Engine(tmp,'hermes-smoke-token-0000000000000000',['hz','hz-migrated']);model=SyntheticModel()
    cli_env={**os.environ,'OPENAPE_TOKEN':engine.token,'OPENAPE_URL':engine.url,'HERMES_HOME':str(home),'HERMES_BIN':hermes}
    cli=lambda *a:subprocess.run([sys.executable,'-m','sdk.cli.main',*a],cwd=ROOT,env=cli_env,capture_output=True,text=True)
    try:
        engine.post('/v1/personas',{'persona_id':'hz','seed_preferences':['concise','direct']})
        installed=cli('adapter','install','hermes');assert installed.returncode==0,installed.stderr
        (home/'config.yaml').write_text(f'model:\n  default: synthetic-model\n  provider: custom\n  base_url: {model.url}/v1\nplugins:\n  enabled: [openape]\n')
        (home/'SOUL.md').write_text(SOUL)
        def run(prompt,mode='active',resume=None,persona='hz'):
            env={'PATH':os.environ['PATH'],'HOME':str(home),'HERMES_HOME':str(home),'OPENAI_API_KEY':'synthetic-transport-not-a-key','NO_PROXY':'127.0.0.1,localhost',
                'OPENAPE_TOKEN':engine.token,'OPENAPE_PERSONA':persona,'OPENAPE_URL':engine.url,'OPENAPE_MODE':mode}
            before=len(model.model_requests())
            r=subprocess.run([hermes,'chat','-Q','-q',prompt]+(['--resume',resume] if resume else []),cwd=tmp,env=env,capture_output=True,text=True,timeout=240,stdin=subprocess.DEVNULL)
            session=next((l.split(':',1)[1].strip() for l in (r.stdout+r.stderr).splitlines() if l.strip().startswith('session_id:')),None)
            return dict(code=r.returncode,out=r.stdout,session=session,requests=model.model_requests()[before:])
        def messages(req):return req['body'].get('messages',[])
        def last_user(req):return [m for m in messages(req) if m.get('role')=='user'][-1]
        def decisions(persona='hz'):return [json.loads(r['data'])['response'] for r in engine.rows(f"SELECT data FROM decisions WHERE persona='{persona}' ORDER BY rowid")]
        report=dict(host='Hermes Agent',host_version=HERMES_VERSION,plugin='adapters/hermes via `openape adapter install hermes`',model='synthetic OpenAI-compatible endpoint; no provider call',checks={})
        c=report['checks']
        first=run('Fixture request one. Reply briefly.')
        req=first['requests'][-1];system=next((m['content'] for m in messages(req) if m.get('role')=='system'),'')
        c['turn_completes']=first['code']==0 and 'Synthetic host transport response.' in first['out']
        c['style_in_current_user_message_once']=count_marker(last_user(req))==1 and count_marker(req['body'])==1
        c['soul_md_coexists_in_system_prompt']='Be warm and friendly.' in system and count_marker(system)==0
        tool_names=lambda r:sorted(t.get('function',{}).get('name','') for t in r['body'].get('tools') or [])
        report['tools_active']=tool_names(req)
        second=run('Fixture request two.',resume=first['session'])
        r2=second['requests'][-1];prefix=messages(req)
        c['resume_one_copy_in_current_turn']=second['code']==0 and first['session'] is not None and count_marker(last_user(r2))==1
        c['prompt_cache_prefix_byte_stable']=json.dumps(messages(r2)[:len(prefix)])==json.dumps(prefix)
        report['resume_history_style_copies']=count_marker(r2['body'])
        shadow=run('Shadow fixture request.',mode='shadow')
        c['persona_feedback_only_in_active_mode']='persona_feedback' in tool_names(req) and 'persona_feedback' not in tool_names(shadow['requests'][-1])
        c['shadow_records_without_injection']=shadow['code']==0 and count_marker(shadow['requests'][-1]['body'])==0 and decisions()[-1]['mode']=='shadow'
        obs=[json.loads(r['data']) for r in engine.rows('SELECT data FROM observations ORDER BY rowid')]
        report['observations']=sorted({o['type'] for o in obs})
        c['decision_linked_turn_completed']=any(o['type']=='turn.completed' and o['decision_id']==decisions()[0]['decision_id'] for o in obs)
        fb=engine.post('/v1/feedback',dict(feedback_id='hermes-smoke-feedback',decision_id=decisions()[0]['decision_id'],source='owner',kind='pairwise_preference',actor_id='host-smoke',consent_scope='core',learning_consent=True,preferred={'controls':dict(directness=2,warmth=3,verbosity=3,humour=0,formality=1,explanation_depth=3,assertiveness=1),'habits':[]},rejected={'controls':decisions()[0]['controls'],'habits':decisions()[0]['habits']},evidence_group='hermes-smoke'))
        c['approved_feedback_linked_to_host_decision']=fb['learning_recorded'] is True
        dry=json.loads(cli('adapter','migrate-soul').stdout)
        c['migration_dry_run_writes_nothing']=dry['seeds']==['warm'] and (home/'SOUL.md').read_text()==SOUL and not list(home.glob('SOUL.md.openape-backup-*'))
        applied=json.loads(cli('adapter','migrate-soul','--apply','--persona','hz-migrated').stdout)
        backups=list(home.glob('SOUL.md.openape-backup-*'))
        c['migration_backs_up_and_keeps_operational']=len(backups)==1 and backups[0].read_text()==SOUL and 'Always run tests before you commit code.' in (home/'SOUL.md').read_text() and 'Be warm and friendly.' not in (home/'SOUL.md').read_text() and applied['persona']['initialization']=='seed_preferences'
        migrated=run('Fixture after migration.',persona='hz-migrated')
        c['migrated_persona_expressed']=migrated['code']==0 and count_marker(last_user(migrated['requests'][-1]))==1 and decisions('hz-migrated')[-1]['controls']['warmth']>=3
        doctor=json.loads(cli('adapter','doctor','hermes','--persona','hz').stdout);report['doctor']=doctor;c['doctor_ok']=doctor['ok']
        engine.stop()
        outage=run('Engine outage fixture request.')
        c['engine_outage_fail_open']=outage['code']==0 and 'Synthetic host transport response.' in outage['out'] and count_marker(outage['requests'][-1]['body'])==0
        uninstalled=cli('adapter','uninstall','hermes');c['uninstall_removes_plugin']=uninstalled.returncode==0 and not (home/'plugins/openape').exists()
        report['status']='PASS' if all(c.values()) else 'FAIL'
        write_report('hermes-host-smoke',report)
        if report['status']!='PASS':raise SystemExit(1)
    finally:
        engine.close();model.close();shutil.rmtree(home,ignore_errors=True)
if __name__=='__main__':main()
