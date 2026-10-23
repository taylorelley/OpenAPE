"""Model providers for the live evaluation.

* `anthropic`: Claude through the official `anthropic` SDK (optional dependency:
  `pip install -e '.[live]'`). Credentials resolve as the SDK does (ANTHROPIC_API_KEY,
  ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile). The SDK retries 429, 5xx and
  connection errors itself.
* `openai-compatible`: any OpenAI-compatible Chat Completions endpoint through the
  official `openai` SDK, as the model under test (another provider family, or a
  gateway) and optionally as the judge.
* `mock`: deterministic and offline, for tests and dry runs. Its replies encode the
  requested levels so the pipeline and metrics can be checked end to end.

The judge defaults to Claude. The model under test never gets a refusal
fallback: a silent switch to another model would invalidate the measurement, and
refusals are an outcome the evaluation measures. The judge uses the server-side
`fallbacks: "default"` when it is Claude (pass --no-judge-fallback to turn it off),
and every judgement records which model actually judged.
"""
import json
import os
import re
from benchmarks.live import judge as J
from protocol.catalogue import TRAITS, TEMPLATES, HABITS

class Refused(Exception):
    pass

def _blocks(prompt, style, placement):
    """Where the style text goes: `turn` after the task in the user turn (as Claude Code and
    Hermes inject it), `prefix` before the task, `system` in the system prompt."""
    if style and placement == 'system': return [{'type': 'text', 'text': prompt}], style
    if style and placement == 'prefix': return [{'type': 'text', 'text': style}, {'type': 'text', 'text': prompt}], None
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
    """Any OpenAI-compatible Chat Completions endpoint, through the official `openai` SDK
    (optional dependency: `pip install -e '.[live]'`). Serves as the model under test
    (another provider family, or a gateway) and, with --judge-provider, as the judge.

    The base URL and key default to the SDK's own environment variables (OPENAI_BASE_URL,
    OPENAI_API_KEY). The SDK retries 408/409/429/5xx and connection errors. The judge asks
    for `json_schema` output; for endpoints without it, use `json_object` (JSON mode,
    with the schema in the prompt) or `none` (instructions only). Every judgement is
    validated against the schema either way."""
    name = 'openai-compatible'
    def __init__(self, base_url=None, key_env='OPENAI_API_KEY', response_format='json_schema', max_retries=4, timeout=600.0):
        import openai  # optional dependency: pip install -e '.[live]'
        key = os.environ.get(key_env or 'OPENAI_API_KEY')
        if not key: raise SystemExit(f'{key_env or "OPENAI_API_KEY"} is not set')
        self.client = openai.OpenAI(api_key=key, base_url=base_url or os.environ.get('OPENAI_BASE_URL') or None, max_retries=max_retries, timeout=timeout)
        self.response_format = response_format
    def _create(self, model, messages, effort, **extra):
        kwargs = dict(model=model, messages=messages, **extra)
        if effort: kwargs['reasoning_effort'] = effort
        r = self.client.chat.completions.create(**kwargs)
        choice = r.choices[0]; usage = r.usage
        return r, choice, dict(served_model=r.model or model, input_tokens=getattr(usage, 'prompt_tokens', 0) or 0, output_tokens=getattr(usage, 'completion_tokens', 0) or 0)
    def generate(self, model, prompt, style, placement='turn', effort=None):
        messages = ([{'role': 'system', 'content': style}] if style and placement == 'system' else []) + \
            [{'role': 'user', 'content': (style + '\n\n' + prompt) if style and placement == 'prefix' else prompt + ('\n\n' + style if style and placement != 'system' else '')}]
        _, choice, meta = self._create(model, messages, effort)
        # A Chat Completions refusal arrives as message.refusal (or finish_reason content_filter).
        refused = bool(getattr(choice.message, 'refusal', None)) or choice.finish_reason == 'content_filter'
        return dict(text=choice.message.content or '', stop_reason='refusal' if refused else choice.finish_reason, **meta)
    def judge(self, model, task, reply, effort=None, fallback=True):
        system = J.SYSTEM
        if self.response_format == 'json_schema':
            extra = {'response_format': {'type': 'json_schema', 'json_schema': {'name': 'style_judgement', 'strict': True, 'schema': J.SCHEMA}}}
        else:
            system += '\n\nReply with only a JSON object matching this schema:\n' + json.dumps(J.SCHEMA)
            extra = {'response_format': {'type': 'json_object'}} if self.response_format == 'json_object' else {}
        _, choice, meta = self._create(model, [{'role': 'system', 'content': system}, {'role': 'user', 'content': J.message(task, reply)}], effort, **extra)
        if getattr(choice.message, 'refusal', None) or choice.finish_reason == 'content_filter': raise Refused(choice.message.refusal or 'content_filter')
        if choice.finish_reason == 'length': raise ValueError('judge output truncated')
        return dict(J.parse(_json_text(choice.message.content or '')), **meta)

def _json_text(text):
    """The JSON object in a reply, tolerating a Markdown code fence around it."""
    text = text.strip()
    if text.startswith('```'): text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    return text

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
