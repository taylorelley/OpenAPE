import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from sdk.python.client import Client, UPAPError

ALL_SCOPES=['persona:express','observations:write','feedback:write','persona:admin','training:admin','reflection:write','settings:write']
CREDENTIALS=Path('.openape/credentials.json');DOCKER_CREDENTIALS=Path('.openape/docker-credentials.json')

def write_credentials(records):
    for path,mode in ((CREDENTIALS,0o600),(DOCKER_CREDENTIALS,0o444)):
        tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
        os.chmod(tmp,mode);os.replace(tmp,path)

def dashboard_html(data):
    """The dashboard template with the data embedded as inert JSON (no network, no scripts from elsewhere)."""
    payload=json.dumps(data).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return (Path(__file__).with_name('dashboard.html')).read_text().replace('__DATA__',payload)

def answer(client,args):
    """`compare` and `rate`: the user's own feedback on one served decision."""
    import uuid
    from sdk.python.lite import CONTROLS,TRAITS,HABITS
    actor=client.request('GET','/v1/whoami')['actor']
    body=dict(feedback_id='cli-'+uuid.uuid4().hex,decision_id=args.decision,source='explicit_user',actor_id=actor,consent_scope=args.scope,
        learning_consent=args.scope!='record_only',evidence_group='cli-'+args.decision[:90])
    if args.cmd=='rate':
        if not -1<=args.value<=1:raise SystemExit('rating must be between -1 and 1')
        return client.request('POST','/v1/feedback',{**body,'kind':'rating','value':args.value})
    options=client.request('POST','/v1/comparisons',{'decision_id':args.decision})['options']
    for label,o in zip('ab',options):
        lines=[CONTROLS['templates'][t][o['controls'][t]] for t in TRAITS]+[HABITS[h]['text'] for h in o['habits']]
        print(f'--- style {label} ---\n'+'\n'.join(lines)+'\n',file=sys.stderr)
    choice=args.choose or input('Which style did you prefer? [a/b, anything else skips] ').strip().lower()
    if choice not in ('a','b'):return {'skipped':True}
    k='ab'.index(choice)
    return client.request('POST','/v1/feedback',{**body,'kind':'pairwise_preference','preferred':options[k],'rejected':options[1-k]})

def main():
    parser=argparse.ArgumentParser(prog='openape',description='OpenAPE — Agent Personality Engine')
    parser.add_argument('--url',default=os.environ.get('OPENAPE_URL','http://127.0.0.1:8765'))
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init')
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8765);serve.add_argument('--data',default='.openape');serve.add_argument('--host',default='127.0.0.1')
    token=sub.add_parser('token',help='add a scoped credential (restart serve to load it)');token.add_argument('action',choices=['add'])
    token.add_argument('--actor',required=True);token.add_argument('--scopes',default='persona:express,observations:write,reflection:write');token.add_argument('--personas',required=True);token.add_argument('--users',default='');token.add_argument('--tenant',default='local')
    persona=sub.add_parser('persona');persona.add_argument('action',choices=['create','list','inspect','history','delete','archetypes','evolution']);persona.add_argument('id',nargs='?')
    persona.add_argument('--archetype',help='starting persona: balanced, mentor, pragmatic_engineer, concierge, collaborator, analyst, critic (see `persona archetypes`)')
    persona.add_argument('--seed',action='append',default=[],help='advanced: seed preference instead of an archetype (repeatable): concise, detailed, warm, reserved, formal, casual, direct, gentle, playful, serious')
    persona.add_argument('--parent',help='create a snapshot copy of this persona (subagent identity)')
    persona.add_argument('--maturation-rate',choices=['fast','normal','slow'],help='how quickly natural maturation runs its course (default normal)')
    persona.add_argument('--manual',action='store_true',help='create: no automatic evolution; an operator runs learn/promote')
    persona.add_argument('--no-agent-feedback',action='store_true',help='create: refuse persona_feedback tool calls from agents')
    persona.add_argument('--individuality',type=float,help='create: temperament variation around the archetype, 0-1 (default 0.3; 0 = the exact archetype)')
    persona.add_argument('--individuality-seed',type=int,help='create: reproduce a specific individual variation')
    persona.add_argument('--pause',action='store_true',help='evolution: stop automatic evolution');persona.add_argument('--resume',action='store_true',help='evolution: resume automatic evolution')
    persona.add_argument('--agent-feedback',choices=['on','off'],help='evolution: allow or refuse agent persona_feedback')
    persona.add_argument('--user',help='inspect: include growth with this linked user')
    for name in ['express','preview','feedback','learn','promote','rollback','export','import','observe']:
        p=sub.add_parser(name);p.add_argument('--file',default='-');p.add_argument('--persona')
        if name=='preview':p.add_argument('--mode',default='active',choices=['shadow','active','frozen'])
    sub.add_parser('job').add_argument('id')
    adapter=sub.add_parser('adapter',help='install guidance, doctor checks and Hermes SOUL.md migration')
    adapter.add_argument('action',choices=['install','uninstall','doctor','migrate-soul']);adapter.add_argument('host',nargs='?',choices=['claude-code','hermes','pi','openclaw','opencogni'],default='hermes')
    adapter.add_argument('--hermes-home');adapter.add_argument('--persona');adapter.add_argument('--apply',action='store_true');adapter.add_argument('--force',action='store_true')
    sub.add_parser('bridge')
    st=sub.add_parser('settings',help="a linked user's own settings for a persona: preferences, pins, habit vetoes, freeze, cohort consent")
    st.add_argument('action',choices=['get','set']);st.add_argument('persona');st.add_argument('user')
    st.add_argument('--prefer',action='append',default=[],help='slot=value, e.g. spelling=british, units=metric, format=code_first (slot= clears it)')
    st.add_argument('--pin',action='append',default=[],help='trait=min-max (0-4), e.g. humour=0-0 for never humorous; trait= clears it')
    st.add_argument('--veto',action='append',default=[],help='habit id never to use (repeatable); --veto none clears vetoes')
    st.add_argument('--freeze',action='store_true');st.add_argument('--unfreeze',action='store_true')
    st.add_argument('--cohort',choices=['on','off'],help="contribute this relationship to the persona's cohort prior")
    st.add_argument('--explore',choices=['on','off'],help='occasionally try a nearby style on low-stakes turns so you can compare')
    cmp=sub.add_parser('compare',help='which style did you prefer? Shows the served style and an alternative, records your choice')
    cmp.add_argument('decision');cmp.add_argument('--choose',choices=['a','b'],help='answer without prompting')
    cmp.add_argument('--scope',choices=['relationship','session','core'],default='relationship',help='where your answer may be learned (default relationship)')
    dash=sub.add_parser('dashboard',help="write a self-contained HTML page: the persona's trait timeline and why its latest style was chosen")
    dash.add_argument('persona');dash.add_argument('--user');dash.add_argument('--decision',help='explain this decision');dash.add_argument('--out',default='openape-dashboard.html')
    rate=sub.add_parser('rate',help='rate a served style from -1 (disliked) to 1 (liked)');rate.add_argument('decision');rate.add_argument('value',type=float)
    rate.add_argument('--scope',choices=['relationship','session','core','record_only'],default='relationship')
    migrate=sub.add_parser('migrate',help='reset a data directory from an earlier release for decoder-v3 (learned state is dropped)')
    migrate.add_argument('--reset',action='store_true',required=True,help='re-create personas from their recorded archetypes');migrate.add_argument('--data',default='.openape')
    args=parser.parse_args()
    if args.cmd=='migrate':
        from engine.api.app import DEFAULT_DECODER
        from engine.storage.migrate import reset
        print(json.dumps(reset(args.data,os.environ.get('OPENAPE_DECODER',str(DEFAULT_DECODER))),indent=2));return
    if args.cmd=='init':
        root=Path('.openape');root.mkdir(mode=0o700,exist_ok=True);root.chmod(0o700)
        if CREDENTIALS.exists():parser.error('Credentials already exist; refusing overwrite')
        records=[dict(token=secrets.token_urlsafe(32),tenant='local',actor='owner',scopes=ALL_SCOPES,personas=['*'],users=['*'])]
        fd=os.open(CREDENTIALS,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
        fd=os.open(DOCKER_CREDENTIALS,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
        os.fchmod(fd,0o444)  # Explicit mode despite restrictive process umask; parent is 0700.
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
        print('Created local and Docker credentials inside private .openape/ (0700). Never commit these files.');return
    if args.cmd=='token':
        records=json.loads(CREDENTIALS.read_text());scopes=[s for s in args.scopes.split(',') if s]
        if not set(scopes)<=set(ALL_SCOPES):parser.error('unknown scope')
        if any(r['actor']==args.actor and r['tenant']==args.tenant for r in records):parser.error('actor already has a credential')
        new=dict(token=secrets.token_urlsafe(32),tenant=args.tenant,actor=args.actor,scopes=scopes,personas=[p for p in args.personas.split(',') if p],users=[u for u in args.users.split(',') if u])
        write_credentials(records+[new])
        print(json.dumps({'actor':args.actor,'token':new['token'],'scopes':scopes,'personas':new['personas'],'users':new['users'],'note':'Shown once. Restart `openape serve` to load it.'},indent=2));return
    if args.cmd=='serve':
        if not os.environ.get('OPENAPE_CREDENTIALS'):
            os.environ['OPENAPE_CREDENTIALS']=Path(os.environ.get('OPENAPE_CREDENTIALS_FILE',str(CREDENTIALS))).read_text()
        from engine.api.app import create_app
        import uvicorn
        uvicorn.run(create_app(args.data),host=args.host,port=args.port);return
    if args.cmd=='adapter' and args.action in ('install','uninstall'):
        from sdk.cli import adapters
        result=adapters.install(args.host,args.hermes_home,args.force) if args.action=='install' else adapters.uninstall(args.host,args.hermes_home)
        print(json.dumps(result,indent=2));return
    token=os.environ.get('OPENAPE_TOKEN')
    if not token:
        try:token=json.loads(CREDENTIALS.read_text())[0]['token']
        except (OSError,ValueError):parser.error('Run openape init or set OPENAPE_TOKEN')
    client=Client(args.url,token,timeout=10)
    try:
        if args.cmd=='bridge':
            # One canonical express request per line; failures never emit style text.
            # {"op":"reflect","decision_id":...,"arguments":{...}} records a persona_feedback tool call.
            from sdk.python.lite import reflect
            for line in sys.stdin:
                try:
                    data=json.loads(line)
                    if data.get('op')=='reflect':out={'text':reflect(args.url,token,data.get('decision_id'),data.get('arguments') or {})}
                    else:out=client.express(data,data.get('mode','shadow'))
                except (ValueError,TypeError,AttributeError):out={'text':'','status':'invalid_request','decision':None}
                print(json.dumps(out),flush=True)
            return
        if args.cmd=='adapter':
            from sdk.cli import adapters
            result=adapters.doctor(args.host,client,args.persona or os.environ.get('OPENAPE_PERSONA'),args.hermes_home) if args.action=='doctor' else adapters.migrate_soul(client,args.hermes_home,args.persona,args.apply)
        elif args.cmd=='persona':
            if args.action=='create':
                if not (args.archetype or args.seed or args.parent):parser.error('choose a starting persona with --archetype (see `openape persona archetypes`)')
                body={'persona_id':args.id,'seed_preferences':args.seed,'evolution':'manual' if args.manual else 'automatic','agent_feedback':not args.no_agent_feedback}
                if args.archetype:body['archetype']=args.archetype
                if args.parent:body['parent_persona_id']=args.parent
                if args.maturation_rate:body['maturation_rate']=args.maturation_rate
                if args.individuality is not None:body['individuality']=args.individuality
                if args.individuality_seed is not None:body['individuality_seed']=args.individuality_seed
                result=client.request('POST','/v1/personas',body)
            elif args.action=='archetypes':result=client.request('GET','/v1/capabilities')['archetypes']
            elif args.action=='evolution':
                if args.pause and args.resume:parser.error('choose --pause or --resume')
                body={}
                if args.pause or args.resume:body['evolution']='manual' if args.pause else 'automatic'
                if args.maturation_rate:body['maturation_rate']=args.maturation_rate
                if args.agent_feedback:body['agent_feedback']=args.agent_feedback=='on'
                result=client.request('POST',f'/v1/personas/{args.id}/evolution',body) if body else client.request('GET',f'/v1/personas/{args.id}')
            elif args.action=='list':result=client.request('GET','/v1/personas')
            elif args.action=='inspect' and args.user:result=client.request('GET',f'/v1/personas/{args.id}?user_id={args.user}')
            else:result=client.request('DELETE' if args.action=='delete' else 'GET',f'/v1/personas/{args.id}'+('/history' if args.action=='history' else ''))
        elif args.cmd=='job':result=client.request('GET',f'/v1/consolidations/{args.id}')
        elif args.cmd=='settings':
            path=f'/v1/personas/{args.persona}/users/{args.user}/settings';current=client.request('GET',path)
            if args.action=='get':result=current
            else:
                body={k:current[k] for k in ('preferences','pins','vetoes','frozen','cohort_contribution','exploration')}
                for item in args.prefer:
                    slot,_,value=item.partition('=');body['preferences'][slot]=value or None
                for item in args.pin:
                    trait,_,span=item.partition('=')
                    if not span:body['pins'].pop(trait,None);continue
                    lo,_,hi=span.partition('-');body['pins'][trait]={'min':int(lo),'max':int(hi or lo)}
                if args.veto==['none']:body['vetoes']=[]
                else:body['vetoes']=sorted(set(body['vetoes'])|set(args.veto))
                if args.freeze and args.unfreeze:parser.error('choose --freeze or --unfreeze')
                if args.freeze or args.unfreeze:body['frozen']=args.freeze
                if args.cohort:body['cohort_contribution']=args.cohort=='on'
                if args.explore:body['exploration']=args.explore=='on'
                result=client.request('PUT',path,body)
        elif args.cmd in ('compare','rate'):result=answer(client,args)
        elif args.cmd=='dashboard':
            from urllib.parse import quote
            data={'timeline':client.request('GET',f'/v1/personas/{quote(args.persona)}/timeline'+(f'?user_id={quote(args.user)}' if args.user else '')),
                'explanation':client.request('GET',f'/v1/decisions/{quote(args.decision)}/explanation') if args.decision else None}
            Path(args.out).write_text(dashboard_html(data));result={'written':args.out,'versions':len(data['timeline']['versions'])}
        else:
            data=json.load(sys.stdin) if args.file=='-' else json.loads(Path(args.file).read_text())
            if args.cmd=='preview':
                # Exactly the text an adapter would inject for this request (decision is ledgered).
                out=client.express(data,args.mode)
                if out['status']=='unavailable':raise SystemExit('engine unavailable or request rejected; no style would be injected')
                result={'status':out['status'],'injected_text':out['text'],'controls':out['decision']['controls'],'habits':out['decision']['habits'],'persona_version':out['decision']['persona_version']}
            else:
                route={'express':'express','feedback':'feedback','learn':'consolidations','observe':'observations','import':'personas/import'}.get(args.cmd)
                if route is None:
                    if not args.persona:parser.error('--persona required')
                    route=f'personas/{args.persona}/'+{'promote':'promotions','rollback':'rollbacks','export':'export'}[args.cmd]
                result=client.request('POST','/v1/'+route,data)
        print(json.dumps(result,indent=2))
    except UPAPError as exc:
        print(json.dumps({'error':{'status':exc.status,'code':exc.code,'message':str(exc)}},indent=2),file=sys.stderr);raise SystemExit(1)
    finally:client.close()
if __name__=='__main__':main()
