"""Real Claude Code CLI + OpenAPE plugin lifecycle against a synthetic model endpoint.

Runs the installed `claude` binary headless with `--plugin-dir adapters/claude-code`,
an isolated HOME, a real OpenAPE engine and ANTHROPIC_BASE_URL pointing at a local
synthetic Messages endpoint. Proves which style text reached the model transport.
NOT live-model evidence; no provider credential or call is used.
"""
import json
import os
import shutil
import subprocess
import tempfile
from scripts.hostkit import ROOT, Engine, SyntheticModel, count_marker, write_report

PLUGIN=str(ROOT/'adapters/claude-code')
def main():
    claude=shutil.which('claude')
    if not claude:raise SystemExit('SKIP: claude CLI not installed')
    version=subprocess.run([claude,'--version'],capture_output=True,text=True).stdout.strip()
    tmp=tempfile.mkdtemp(prefix='openape-cc-');home=tempfile.mkdtemp(prefix='openape-cc-home-')
    engine=Engine(tmp,'claude-code-smoke-token-00000000000',['cc-terse','cc-kind']);model=SyntheticModel()
    try:
        engine.post('/v1/personas',{'persona_id':'cc-terse','seed_preferences':['concise','direct','serious']})
        engine.post('/v1/personas',{'persona_id':'cc-kind','seed_preferences':['warm','detailed','playful']})
        def run(prompt,persona='cc-terse',mode='active',resume=None):
            env={'PATH':os.environ['PATH'],'HOME':home,'ANTHROPIC_API_KEY':'synthetic-transport-not-a-key','ANTHROPIC_BASE_URL':model.url,
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','DISABLE_AUTOUPDATER':'1','NO_PROXY':'127.0.0.1,localhost',
                'OPENAPE_TOKEN':engine.token,'OPENAPE_PERSONA':persona,'OPENAPE_URL':engine.url,'OPENAPE_MODE':mode,'OPENAPE_HOST_VERSION':version.split()[0]}
            args=[claude,'-p',prompt,'--plugin-dir',PLUGIN,'--output-format','json','--model','claude-sonnet-5-5']+(['--resume',resume] if resume else [])
            before=len(model.model_requests())
            r=subprocess.run(args,cwd=tmp,env=env,capture_output=True,text=True,timeout=180,stdin=subprocess.DEVNULL)
            out=json.loads(r.stdout) if r.stdout.strip().startswith('{') else {}
            return dict(code=r.returncode,result=out.get('result'),session=out.get('session_id'),requests=model.model_requests()[before:])
        def current_turn(req):
            # Claude Code 2.1.x delivers hook additionalContext as a per-turn message
            # placed after the user's prompt; count only the messages of this turn.
            msgs=req['body'].get('messages',[]);idx=max((i for i,m in enumerate(msgs) if m.get('role')=='user'),default=0)
            while idx>0 and msgs[idx-1].get('role')!='assistant':idx-=1
            return msgs[idx:]
        def decisions(persona):
            return [json.loads(r['data'])['response'] for r in engine.rows(f"SELECT data FROM decisions WHERE persona='{persona}' ORDER BY rowid")]
        report=dict(host='Claude Code',host_version=version,plugin='adapters/claude-code (--plugin-dir)',model='synthetic Anthropic Messages endpoint; no provider call',checks={})
        c=report['checks']
        first=run('Fixture request one. Reply briefly.')
        c['turn_completes']=first['code']==0 and first['result']=='Synthetic host transport response.'
        c['style_reached_model_once']=count_marker(first['requests'][-1]['body'])==1
        c['context_in_current_turn_not_system_prompt']=count_marker(current_turn(first['requests'][-1]))==1 and count_marker(first['requests'][-1]['body'].get('system',''))==0
        resumed=run('Fixture request two after resume.',resume=first['session'])
        c['resume_one_copy_in_new_turn']=resumed['code']==0 and count_marker(current_turn(resumed['requests'][-1]))==1
        report['resume_history_style_copies']=count_marker(resumed['requests'][-1]['body'])
        compact=run('/compact',resume=first['session'])
        report['compact_exit_code']=compact['code']
        shadow=run('Shadow fixture request.',mode='shadow')
        # The plugin's stdio MCP server offers persona_feedback in active mode and nothing in shadow
        # (Claude Code may list it as a deferred tool rather than a direct schema).
        offered=lambda r:'mcp__plugin_openape_openape__persona_feedback' in json.dumps(r['body'])
        c['persona_feedback_tool_only_in_active_mode']=offered(first['requests'][-1]) and not offered(shadow['requests'][-1])
        c['shadow_records_without_injection']=shadow['code']==0 and count_marker(shadow['requests'][-1]['body'])==0 and decisions('cc-terse')[-1]['mode']=='shadow'
        kind=run('Fixture request one. Reply briefly.',persona='cc-kind')
        terse_choice=decisions('cc-terse')[0]['controls'];kind_choice=decisions('cc-kind')[0]['controls']
        c['two_personas_distinct_controls']=terse_choice!=kind_choice and kind['code']==0
        report['controls']={'cc-terse':decisions('cc-terse')[0]['controls'],'cc-kind':decisions('cc-kind')[0]['controls']}
        obs=[(json.loads(r['data'])['type'],json.loads(r['data']).get('decision_id')) for r in engine.rows('SELECT data FROM observations ORDER BY rowid')]
        report['observations']=sorted({t for t,_ in obs})
        c['decision_linked_turn_completed']=any(t=='turn.completed' and d==decisions('cc-terse')[0]['decision_id'] for t,d in obs)
        c['session_lifecycle_observed']={'session.started','turn.completed','session.ended'}<=set(report['observations'])
        report['compaction_observed']='session.compacted' in report['observations']
        fb=engine.post('/v1/feedback',dict(feedback_id='cc-smoke-feedback',decision_id=decisions('cc-terse')[0]['decision_id'],source='owner',kind='pairwise_preference',actor_id='host-smoke',consent_scope='core',learning_consent=True,preferred={'controls':dict(directness=2,warmth=3,verbosity=3,humour=0,formality=1,explanation_depth=3,assertiveness=1),'habits':[]},rejected={'controls':terse_choice,'habits':decisions('cc-terse')[0]['habits']},evidence_group='cc-smoke'))
        c['approved_feedback_linked_to_host_decision']=fb['learning_recorded'] is True
        engine.stop()
        outage=run('Engine outage fixture request.')
        c['engine_outage_fail_open']=outage['code']==0 and outage['result']=='Synthetic host transport response.' and count_marker(outage['requests'][-1]['body'])==0
        report['status']='PASS' if all(c.values()) else 'FAIL'
        write_report('claude-code-host-smoke',report)
        if report['status']!='PASS':raise SystemExit(1)
    finally:
        engine.close();model.close();shutil.rmtree(home,ignore_errors=True)
if __name__=='__main__':main()
