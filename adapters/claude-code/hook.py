#!/usr/bin/env python3
"""OpenAPE Claude Code plugin hook (all lifecycle events). Python stdlib only.

Fail-open: always exits 0; on any failure it prints nothing. Never reads the
transcript, CLAUDE.md or AGENTS.md. Only UserPromptSubmit emits
`hookSpecificOutput.additionalContext`; every other event is a best-effort
observation carrying IDs and status only. UserPromptSubmit also records the latest
active decision ID for the persona_feedback MCP tool (mcp_server.py).

Turn context comes from metadata: the tool names, failure count and edited files'
extensions (never paths or contents) of the previous turn, recorded by
PostToolUse/PostToolUseFailure; repository-marker file names in the working directory;
plan mode; and the user's declared context (`.openape.json` in the project, overridden
by OPENAPE_CONTEXT). Prompt text is read only with OPENAPE_CONTEXT_TEXT=local and
classified in memory by the on-host context classifier; it is never sent, logged or
stored; only the derived enum labels leave this process.
"""
import hashlib
import json
import os
import re
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import upap_lite  # noqa: E402  (vendored, byte-identical to sdk/python/lite.py)

ADAPTER = 'upap.claude-code'
VERSION = '0.3.0'

def stable(value): return hashlib.sha256(value.encode()).hexdigest()[:48]
def safe_id(value, default): return (re.sub(r'[^A-Za-z0-9_.:-]', '-', value or '')[:100]) or default

def config():
    token, persona = os.environ.get('OPENAPE_TOKEN'), os.environ.get('OPENAPE_PERSONA')
    if not token or not persona: return None
    return dict(token=token, persona=persona, url=os.environ.get('OPENAPE_URL', 'http://127.0.0.1:8765'), tenant=os.environ.get('OPENAPE_TENANT', 'local'),
        user=os.environ.get('OPENAPE_LINKED_USER'), mode=os.environ.get('OPENAPE_MODE', 'shadow'), host_version=safe_id(os.environ.get('OPENAPE_HOST_VERSION'), 'unverified'),
        context_text=os.environ.get('OPENAPE_CONTEXT_TEXT') == 'local', example=os.environ.get('OPENAPE_STYLE_EXAMPLE') == '1')

PROJECT_FILE_MAX = 65536

def project_context(cwd):
    """The repository's `.openape.json`, which anyone who controls the repository can
    write: a regular file only (no symlink, FIFO or device), at most 64 KB, read without
    blocking. derive_context keeps only enum values it may set (never lower stakes,
    never channel or turn origin)."""
    if not cwd: return {}
    try:
        fd = os.open(Path(cwd) / '.openape.json', os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except (OSError, TypeError, ValueError): return {}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): return {}
        raw = os.read(fd, PROJECT_FILE_MAX + 1)
        return {} if len(raw) > PROJECT_FILE_MAX else upap_lite.parse_declared(raw.decode('utf-8', 'replace'))
    except OSError: return {}
    finally: os.close(fd)

def declared_context():
    """The user's own declaration (OPENAPE_CONTEXT): trusted, ranks above everything."""
    return upap_lite.parse_declared(os.environ.get('OPENAPE_CONTEXT') or '{}')

def state_root():
    root = Path(os.environ.get('CLAUDE_PLUGIN_DATA') or Path.home() / '.openape' / 'claude-code-state')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root

def state_path(session_key): return state_root() / f'{session_key}.json'

def latest_path(persona):
    """Latest active decision for this persona, read by the persona_feedback MCP tool."""
    return state_root() / f'latest-{stable(persona)}.json'

def load(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}

def save(path, state):
    tmp = path.with_suffix(f'.{os.getpid()}.tmp'); tmp.write_text(json.dumps(state)); os.replace(tmp, path)

def event(cfg, session_key, kind, status='ok', decision_id=None):
    e = dict(event_id=str(uuid.uuid4()), occurred_at=datetime.now(timezone.utc).isoformat(), persona_id=cfg['persona'], session_id=session_key, type=kind, status=status)
    if cfg['user']: e['user_id'] = cfg['user']
    if decision_id: e['decision_id'] = decision_id
    return e

def main():
    data = json.load(sys.stdin)
    cfg = config(); name = data.get('hook_event_name'); session = data.get('session_id')
    if not cfg or not session or cfg['mode'] == 'disabled': return
    # Subagents opt out by default: no injection into child contexts and no learning
    # signal attributed to the parent. Bind a separately scoped child persona instead.
    if data.get('agent_id'): return
    key = stable(f'claude-code:{session}:{cfg["persona"]}'); path = state_path(key); state = load(path)
    observe = lambda *events: upap_lite.observe(cfg['url'], cfg['token'], ADAPTER, list(events))
    if name == 'SessionStart':
        if data.get('model'): state['model'] = safe_id(data['model'], 'host-selected')
        save(path, state)
        observe(event(cfg, key, 'session.compacted' if data.get('source') == 'compact' else 'session.started'))
    elif name in ('PostToolUse', 'PostToolUseFailure'):
        # Previous-turn signals for the next prompt's context: tool names and a count only.
        tools = state.setdefault('tools', [])
        tool = safe_id(data.get('tool_name'), 'unknown')[:64]
        if tool not in tools and len(tools) < 32: tools.append(tool)
        inputs = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
        ext = upap_lite.extension_of(inputs.get('file_path') or inputs.get('notebook_path') or inputs.get('path'))
        if ext and len(state.setdefault('extensions', [])) < 64: state['extensions'].append(ext)
        if name == 'PostToolUseFailure': state['failures'] = state.get('failures', 0) + 1
        save(path, state)
    elif name == 'UserPromptSubmit':
        prompt_id = data.get('prompt_id') or str(uuid.uuid4())
        if state.get('prompt_id') == prompt_id: return  # never inject twice for one prompt
        signals = dict(tools=state.pop('tools', []), failures=state.pop('failures', 0), plan_mode=data.get('permission_mode') == 'plan',
            extensions=state.pop('extensions', []), repo_files=upap_lite.repo_files(data.get('cwd')) if data.get('cwd') else [])
        text = data.get('prompt') if cfg['context_text'] else None
        context = upap_lite.derive_context(signals, declared_context(), text, project=project_context(data.get('cwd')))
        request = dict(request_id=stable(f'{key}:{prompt_id}'), identity=dict(tenant_id=cfg['tenant'], persona_id=cfg['persona']),
            session=dict(id=key, turn_id=stable(prompt_id)),
            host=dict(adapter_id=ADAPTER, adapter_version=VERSION, host_version=cfg['host_version'], provider_family='anthropic', model_id=state.get('model', 'host-selected')),
            context=context)
        if cfg['user']: request['identity']['user_id'] = cfg['user']
        result = upap_lite.express(cfg['url'], cfg['token'], request, cfg['mode'], example=cfg['example'])
        state.update(prompt_id=prompt_id, decision_id=(result['decision'] or {}).get('decision_id'), applied=bool(result['text'])); save(path, state)
        if result['text'] and state['decision_id']: save(latest_path(cfg['persona']), {'decision_id': state['decision_id'], 'at': time.time()})
        if result['text']:
            # Context tier wording: a factual statement of user-configured preferences.
            text = 'OpenAPE persona style preferences configured by the user for this session. ' + result['text']
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': text}}))
    elif name in ('Stop', 'StopFailure'):
        if data.get('stop_hook_active') or not state.get('decision_id'): return
        observe(event(cfg, key, 'turn.completed' if name == 'Stop' else 'turn.failed', 'ok' if name == 'Stop' else 'failed', state['decision_id']))
    elif name == 'PostCompact':
        observe(event(cfg, key, 'session.compacted'))
    elif name == 'PostModelSwitch':
        state['model'] = safe_id(data.get('to_model'), 'host-selected'); save(path, state)
        observe(event(cfg, key, 'model.changed'))  # persona identity is unchanged by provider switches
    elif name == 'SessionEnd':
        observe(event(cfg, key, 'session.ended'))
        path.unlink(missing_ok=True)

if __name__ == '__main__':
    try: main()
    except Exception: pass
    sys.exit(0)
