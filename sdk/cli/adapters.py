"""`openape adapter ...`: install guidance, doctor checks and Hermes SOUL.md migration.

Nothing here edits host settings, CLAUDE.md, AGENTS.md or SOUL.md silently. Hermes
plugin installation copies a plugin directory; SOUL migration is a dry run unless
`--apply`, and then always writes a timestamped backup first.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HOSTS=('claude-code','hermes','pi','openclaw','opencogni')
HOST_BINARIES={'claude-code':'claude','hermes':'hermes','pi':'pi','openclaw':'openclaw'}
ENV_HELP=('OPENAPE_TOKEN (restricted host token: persona:express + observations:write)','OPENAPE_PERSONA','OPENAPE_URL (default http://127.0.0.1:8765)','OPENAPE_MODE (shadow default; active to inject)','OPENAPE_LINKED_USER (optional, explicit)','OPENAPE_TENANT (default local)')

def hermes_home(path=None):
    return Path(path or os.environ.get('HERMES_HOME') or Path.home()/'.hermes')

def install(host,hermes_path=None,force=False):
    adapter=ROOT/'adapters'/host
    if host=='hermes':
        target=hermes_home(hermes_path)/'plugins'/'openape'
        if target.exists() and not force:raise SystemExit(f'{target} exists; re-run with --force to replace it (a backup is kept)')
        if target.exists():shutil.move(str(target),str(target)+'.bak-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'))
        shutil.copytree(adapter,target,ignore=shutil.ignore_patterns('__pycache__','manifest.json'))
        return dict(installed=str(target),next=['hermes plugins enable openape','Store OPENAPE_* settings with Hermes secrets/.env for the profile','SOUL.md is untouched (coexistence). Optional: openape adapter migrate-soul'],env=ENV_HELP)
    steps={
        'claude-code':['claude plugin marketplace add '+str(ROOT),'claude plugin install openape@openape','or per session: claude --plugin-dir '+str(adapter),'Set OPENAPE_* in the environment or settings.json "env"; hooks need python3 only'],
        'pi':[f'pi -e {adapter}/index.ts   (or add the path to Pi "extensions" settings)','Keep the repository layout: the extension imports ../common.ts and the TS SDK'],
        'openclaw':[f'openclaw plugins install {adapter}','Grant hooks.allowPromptInjection and allowConversationAccess for this plugin in OpenClaw config (see adapters/openclaw/config.example.json)'],
        'opencogni':['Companion Cordis service only: load personalityPlugin(client) for experimentation. No planner integration (see docs/adapters/compatibility.md).']}
    return dict(installed=None,next=steps[host],env=ENV_HELP,note='No host settings were modified.')

def uninstall(host,hermes_path=None):
    if host!='hermes':return dict(removed=None,next=['Remove the plugin/extension path from the host configuration you added it to'])
    target=hermes_home(hermes_path)/'plugins'/'openape'
    if target.exists():shutil.rmtree(target)
    return dict(removed=str(target),next=['hermes plugins disable openape'])

def doctor(host,client,persona=None,hermes_path=None):
    checks={}
    try:checks['engine_ready']=client.request('GET','/health/ready').get('engine_status')
    except Exception as exc:checks['engine_ready']=f'FAIL: {exc}'
    try:caps=client.request('GET','/v1/capabilities');checks['token_valid']=True;checks['decoder']=caps.get('decoder_hash');checks['engine_status']=caps.get('engine_status')
    except Exception as exc:checks['token_valid']=f'FAIL: {exc}'
    if persona:
        try:client.request('GET',f'/v1/personas/{persona}');checks['persona_visible']=True
        except Exception as exc:checks['persona_visible']=f'FAIL: {exc}'
    binary=HOST_BINARIES.get(host)
    if binary:
        path=(os.environ.get('HERMES_BIN') if host=='hermes' else None) or shutil.which(binary);checks['host_binary']=path or 'not found on PATH'
        if path:
            try:checks['host_version']=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=20).stdout.strip()[:80]
            except Exception:checks['host_version']='unknown'
    if host=='hermes':
        plugin=hermes_home(hermes_path)/'plugins'/'openape';checks['plugin_installed']=(plugin/'plugin.yaml').exists()
        checks['soul_md_present']=(hermes_home(hermes_path)/'SOUL.md').exists()
    if host=='claude-code':checks['plugin_files']=(ROOT/'adapters/claude-code/.claude-plugin/plugin.json').exists()
    checks['mode']=os.environ.get('OPENAPE_MODE','shadow')
    manifest=json.loads((ROOT/'adapters'/host/'manifest.json').read_text())
    checks['adapter_release_status']=manifest.get('release_status')
    ok=all(v is True or (isinstance(v,str) and not v.startswith('FAIL') and v!='not found on PATH') for k,v in checks.items() if k not in ('mode','soul_md_present','decoder','adapter_release_status','host_version'))
    return dict(host=host,ok=ok,checks=checks)

# Style-only cues → seed vocabulary. Lines that mention operations (tools, files,
# tests, commands, safety) are always retained, even if they also mention style.
STYLE_CUES={'concise':r'\b(concise|brief|terse|short answers?)\b','detailed':r'\b(detailed|thorough|in[- ]depth|comprehensive)\b','warm':r'\b(warm|friendly|empathetic|kind|supportive)\b',
    'reserved':r'\b(reserved|neutral tone|matter[- ]of[- ]fact)\b','formal':r'\b(formal|professional)\b','casual':r'\b(casual|informal|relaxed)\b','direct':r'\b(direct|blunt|straightforward)\b',
    'gentle':r'\b(gentle|tactful|diplomatic)\b','playful':r'\b(playful|humou?r|witty|jokes?|funny)\b','serious':r'\b(serious|no jokes|no humou?r)\b'}
OPERATIONAL=r'\b(run|test|tests|commit|tool|tools|file|files|command|permission|password|secret|delete|deploy|api|code|safety|security|refuse)\b'
CONFLICTS=[{'concise','detailed'},{'warm','reserved'},{'formal','casual'},{'direct','gentle'},{'playful','serious'}]

def analyse_soul(text):
    seeds=set();style_lines=[];retained=[]
    for line in text.splitlines():
        hits={s for s,pattern in STYLE_CUES.items() if re.search(pattern,line,re.I)}
        if hits and not re.search(OPERATIONAL,line,re.I) and len(line)<=200:style_lines.append(line);seeds|=hits
        else:retained.append(line)
    if 'serious' in seeds and 'playful' in seeds and re.search(r'no (jokes|humou?r)',text,re.I):seeds.discard('playful')
    dropped=sorted(s for pair in CONFLICTS if pair<=seeds for s in pair)
    return dict(seeds=sorted(seeds-set(dropped)),conflicting_dropped=dropped,style_lines=style_lines,retained_lines=retained)

def migrate_soul(client,hermes_path=None,persona=None,apply=False):
    home=hermes_home(hermes_path);soul=home/'SOUL.md'
    if not soul.exists():return dict(soul_md=str(soul),found=False,action='none; Hermes uses its default identity')
    original=soul.read_text();analysis=analyse_soul(original)
    report=dict(soul_md=str(soul),found=True,**analysis,limitation='Hermes 0.19 has no supported setting to omit SOUL.md while keeping project context files; coexistence is the default.',applied=False)
    if not apply:
        report['action']='dry run: nothing written. Re-run with --apply --persona ID to back up SOUL.md, create a seeded persona and remove style-only lines.';return report
    if not persona:raise SystemExit('--apply requires --persona')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S');backup=home/f'SOUL.md.openape-backup-{stamp}'
    with open(backup,'x') as f:f.write(original)  # exclusive: never overwrite an existing backup
    created=client.request('POST','/v1/personas',{'persona_id':persona,'seed_preferences':analysis['seeds']})
    header=f'<!-- Style-only lines moved to OpenAPE persona "{persona}" ({",".join(analysis["seeds"]) or "neutral"}); backup: {backup.name} -->'
    tmp=soul.with_suffix('.openape.tmp');tmp.write_text('\n'.join([header,*analysis['retained_lines']])+'\n');os.replace(tmp,soul)
    report.update(applied=True,backup=str(backup),persona=created,action='SOUL.md backed up; operational lines retained; style-only lines removed')
    return report
