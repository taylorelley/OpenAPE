#!/usr/bin/env python3
"""OpenAPE persona_feedback tool for Claude Code: a stdio MCP server. Python stdlib only.

Lists one tool in active mode (none otherwise, or with OPENAPE_AGENT_FEEDBACK=0). A call
attaches to the latest decision the UserPromptSubmit hook recorded for this persona,
so the model supplies trait moves only and never an ID, text or score.
"""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import upap_lite  # noqa: E402  (vendored, byte-identical to sdk/python/lite.py)
from hook import VERSION, config, latest_path  # noqa: E402

MAX_AGE = 3600  # seconds; an older decision belongs to a finished conversation

def enabled(cfg): return bool(cfg) and cfg['mode'] == 'active' and os.environ.get('OPENAPE_AGENT_FEEDBACK', '1') != '0'

def latest_decision(cfg):
    try: state = json.loads(latest_path(cfg['persona']).read_text())
    except (OSError, ValueError): return None
    return state.get('decision_id') if time.time() - state.get('at', 0) <= MAX_AGE else None

def handle(message):
    method, cfg = message.get('method'), config()
    if method == 'initialize':
        return {'protocolVersion': message.get('params', {}).get('protocolVersion', '2025-06-18'), 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'openape', 'version': VERSION}}
    if method == 'ping': return {}
    if method == 'tools/list':
        return {'tools': [{'name': upap_lite.TOOL_NAME, 'description': upap_lite.TOOL_DESCRIPTION, 'inputSchema': upap_lite.TOOL_PARAMETERS}] if enabled(cfg) else []}
    if method == 'tools/call':
        params = message.get('params') or {}
        if params.get('name') != upap_lite.TOOL_NAME: raise LookupError('Unknown tool')
        text = upap_lite.reflect(cfg['url'], cfg['token'], latest_decision(cfg), params.get('arguments') or {}) if enabled(cfg) else 'Not recorded: persona feedback is not enabled.'
        return {'content': [{'type': 'text', 'text': text}], 'isError': text.startswith('Not recorded')}
    raise LookupError('Method not found')

def main():
    for line in sys.stdin:
        try: message = json.loads(line)
        except ValueError: continue
        if 'id' not in message: continue  # notifications need no reply
        try: reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': handle(message)}
        except Exception as exc: reply = {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601 if isinstance(exc, LookupError) else -32603, 'message': str(exc)[:200]}}
        print(json.dumps(reply), flush=True)

if __name__ == '__main__': main()
