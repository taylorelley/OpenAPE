import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from sdk.python.client import Client

def main():
    parser=argparse.ArgumentParser(prog='openape',description='OpenAPE — Agent Personality Engine')
    parser.add_argument('--url',default=os.environ.get('OPENAPE_URL','http://127.0.0.1:8765'))
    sub=parser.add_subparsers(dest='cmd',required=True)
    sub.add_parser('init')
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=8765);serve.add_argument('--data',default='.openape');serve.add_argument('--host',default='127.0.0.1')
    persona=sub.add_parser('persona');persona.add_argument('action',choices=['create','list','inspect','history','delete']);persona.add_argument('id',nargs='?')
    for name in ['express','feedback','learn','promote','rollback','export','import','observe']:
        p=sub.add_parser(name);p.add_argument('--file',default='-');p.add_argument('--persona')
    sub.add_parser('bridge')
    args=parser.parse_args()
    if args.cmd=='init':
        root=Path('.openape');root.mkdir(mode=0o700,exist_ok=True);root.chmod(0o700)
        path=root/'credentials.json'
        if path.exists():parser.error('Credentials already exist; refusing overwrite')
        records=[dict(token=secrets.token_urlsafe(32),tenant='local',actor='owner',scopes=['persona:express','observations:write','feedback:write','persona:admin','training:admin'],personas=['*'],users=['*'])]
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
        docker_path=root/'docker-credentials.json'
        fd=os.open(docker_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
        os.fchmod(fd,0o444)  # Explicit mode despite restrictive process umask; parent is 0700.
        with os.fdopen(fd,'w') as f:json.dump(records,f,indent=2)
        print('Created local and Docker credentials inside private .openape/ (0700). Never commit these files.');return
    if args.cmd=='serve':
        if not os.environ.get('OPENAPE_CREDENTIALS'):
            os.environ['OPENAPE_CREDENTIALS']=Path(os.environ.get('OPENAPE_CREDENTIALS_FILE','.openape/credentials.json')).read_text()
        from engine.api.app import create_app
        import uvicorn
        uvicorn.run(create_app(args.data),host=args.host,port=args.port);return
    token=os.environ.get('OPENAPE_TOKEN')
    if not token:
        try:token=json.loads(Path('.openape/credentials.json').read_text())[0]['token']
        except (OSError,ValueError):parser.error('Run openape init or set OPENAPE_TOKEN')
    client=Client(args.url,token,timeout=10)
    try:
        if args.cmd=='bridge':
            # One canonical express request per line; failures never emit style text.
            for line in sys.stdin:
                try:
                    data=json.loads(line);out=client.express(data,data.get('mode','shadow'))
                except (ValueError,TypeError):out={'text':'','status':'invalid_request','decision':None}
                print(json.dumps(out),flush=True)
            return
        if args.cmd=='persona':
            if args.action=='create':result=client.request('POST','/v1/personas',{'persona_id':args.id})
            elif args.action=='list':result=client.request('GET','/v1/personas')
            else:result=client.request('DELETE' if args.action=='delete' else 'GET',f'/v1/personas/{args.id}'+('/history' if args.action=='history' else ''))
        else:
            data=json.load(sys.stdin) if args.file=='-' else json.loads(Path(args.file).read_text())
            route={'express':'express','feedback':'feedback','learn':'consolidations','observe':'observations','import':'personas/import'}.get(args.cmd)
            if route is None:
                if not args.persona:parser.error('--persona required')
                route=f'personas/{args.persona}/'+{'promote':'promotions','rollback':'rollbacks','export':'export'}[args.cmd]
            result=client.request('POST','/v1/'+route,data)
        print(json.dumps(result,indent=2))
    finally:client.close()
if __name__=='__main__':main()
