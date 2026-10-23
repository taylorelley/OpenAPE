"""Model providers for the live evaluation.

* `anthropic`: Claude through the official `anthropic` SDK (optional dependency:
  `pip install -e '.[live]'`). Credentials resolve as the SDK does (ANTHROPIC_API_KEY,
  ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile). The SDK retries 429, 5xx and
  connection errors itself.
* `openai-compatible`: a non-Claude model behind an OpenAI-compatible
  `/chat/completions` endpoint, for the cross-provider check (generation only).
* `mock`: deterministic and offline, for tests and dry runs. Its replies encode the
  requested levels so the pipeline and metrics can be checked end to end.

The judge is always a Claude model. The model under test never gets a refusal
fallback: a silent switch to another model would invalidate the measurement, and
refusals are an outcome the evaluation measures. The judge uses the server-side
`fallbacks: "default"` (pass --no-judge-fallback to turn it off) and records which
model actually judged.
"""
import json
import os
import re
from benchmarks.live import judge as J
from protocol.catalogue import TRAITS, TEMPLATES, HABITS

class Refused(Exception):
    pass

def _blocks(prompt, style, placement):
    if style and placement == 'system': return [{'type': 'text', 'text': prompt}], style
    return [{'type': 'text', 'text': prompt}] + ([{'type': 'text', 'text': style}] if style else []), None

class AnthropicProvider:
    name = 'anthropic'
    def __init__(self, max_retries=4, timeout=600.0):
        import anthropic  # optional dependency: pip install -e '.[live]'
        self.client = anthropic.Anthropic(max_retries=max_retries, timeout=timeout)
    def generate(self, model, prompt, style, placement='turn', effort='medium'):
        content, system = _blocks(prompt, style, placement)
        kwargs = dict(model=model, max_tokens=16000, messages=[{'role': 'user', 'content': content}])
        if system: kwargs['system'] = system
        if effort: kwargs['output_config'] = {'effort': effort}
        r = self.client.messages.create(**kwargs)
        return dict(text=''.join(b.text for b in r.content if b.type == 'text'), stop_reason=r.stop_reason, served_model=r.model,
            input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens)
    def judge(self, model, task, reply, effort='high', fallback=True):
        kwargs = dict(model=model, max_tokens=16000, system=J.SYSTEM, messages=[{'role': 'user', 'content': J.message(task, reply)}],
            output_config={'format': {'type': 'json_schema', 'schema': J.SCHEMA}, **({'effort': effort} if effort else {})})
        if fallback: r = self.client.beta.messages.create(betas=['server-side-fallback-2026-07-01'], fallbacks='default', **kwargs)
        else: r = self.client.messages.create(**kwargs)
        if r.stop_reason == 'refusal': raise Refused(getattr(getattr(r, 'stop_details', None), 'category', None) or 'refusal')
        if r.stop_reason == 'max_tokens': raise ValueError('judge output truncated')
        text = next(b.text for b in r.content if b.type == 'text')
        return dict(J.parse(text), served_model=r.model, input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens)

class OpenAICompatibleProvider:
    """Generation only, for a non-Claude provider family. Base URL and key come from the
    environment variables named on the command line."""
    name = 'openai-compatible'
    def __init__(self, base_url, key_env, timeout=600.0):
        import httpx
        key = os.environ.get(key_env)
        if not key: raise SystemExit(f'{key_env} is not set')
        self.http = httpx.Client(base_url=base_url.rstrip('/'), headers={'Authorization': 'Bearer ' + key}, timeout=timeout)
    def generate(self, model, prompt, style, placement='turn', effort=None):
        messages = ([{'role': 'system', 'content': style}] if style and placement == 'system' else []) + \
            [{'role': 'user', 'content': prompt + ('\n\n' + style if style and placement != 'system' else '')}]
        for attempt in range(4):
            r = self.http.post('/chat/completions', json={'model': model, 'messages': messages})
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                import time; time.sleep(2 ** attempt * 2); continue
            r.raise_for_status(); break
        data = r.json(); choice = data['choices'][0]; usage = data.get('usage') or {}
        return dict(text=choice['message'].get('content') or '', stop_reason=choice.get('finish_reason'), served_model=data.get('model', model),
            input_tokens=usage.get('prompt_tokens', 0), output_tokens=usage.get('completion_tokens', 0))

class MockProvider:
    """Offline stand-in. The reply states the levels and habits that the style text asked
    for; the judge reads them back. `confuse` maps (trait, level) to the level the mock
    judge reports, to simulate levels a model does not distinguish."""
    name = 'mock'
    def __init__(self, confuse=None, ignored_habits=(), quality_drop=None):
        self.confuse = confuse or {}; self.ignored = set(ignored_habits); self.quality_drop = quality_drop or {}
        self.sentences = {text: (t, level) for t in TRAITS for level, text in enumerate(TEMPLATES[t])}
        self.habit_text = {h['text']: h['id'] for h in HABITS}
    def generate(self, model, prompt, style, placement='turn', effort=None):
        levels = {'directness': 2, 'warmth': 2, 'verbosity': 2, 'humour': 0, 'formality': 2, 'explanation_depth': 2, 'assertiveness': 2}
        habits = []
        for sentence in re.split(r'(?<=\.)\s+', style or ''):
            if sentence in self.sentences: t, level = self.sentences[sentence]; levels[t] = level
            if sentence in self.habit_text and self.habit_text[sentence] not in self.ignored: habits.append(self.habit_text[sentence])
        reply = 'MOCK ' + json.dumps({'levels': levels, 'habits': habits, 'static': bool(style) and not any(s in self.sentences for s in re.split(r'(?<=\.)\s+', style))})
        return dict(text=reply, stop_reason='end_turn', served_model=model, input_tokens=len(prompt) // 4, output_tokens=len(reply) // 4)
    def judge(self, model, task, reply, effort=None, fallback=True):
        data = json.loads(reply[len('MOCK '):])
        traits = {t: self.confuse.get((t, v), v) for t, v in data['levels'].items()}
        quality = 4 - sum(1 for (t, v), drop in self.quality_drop.items() if data['levels'].get(t) == v for _ in range(drop))
        return J.validate(dict(traits=traits, habits={h['id']: h['id'] in data['habits'] for h in HABITS}, task_quality=max(1, quality), refused=False)) | \
            dict(served_model=model, input_tokens=0, output_tokens=0)
