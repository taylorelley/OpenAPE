"""Blind judge: rates what a reply does, without seeing the requested style.

The judge sees only the user's task and the reply. It rates each trait on the
catalogue's five-level scale (the level sentences are the anchors), says which
habits the reply clearly shows, rates task quality ignoring style, and flags a
refusal. Output is constrained to a JSON schema.
"""
import json
from protocol.catalogue import TRAITS, TEMPLATES, HABITS

LABELS = {'directness': 'Directness', 'warmth': 'Warmth', 'verbosity': 'Verbosity', 'humour': 'Humour', 'formality': 'Formality',
    'explanation_depth': 'Explanation depth', 'assertiveness': 'Assertiveness'}

def rubric():
    lines = ['Rate each trait by the level whose description best matches what the reply actually does.']
    for t in TRAITS:
        lines.append(f'\n{LABELS[t]} ({t}):')
        lines += [f'  {level}: {text}' for level, text in enumerate(TEMPLATES[t])]
    lines.append('\nHabits. Mark a habit true only if the reply clearly and deliberately shows it:')
    lines += [f'  {h["id"]}: {h["text"]}' for h in HABITS]
    lines.append('\nTask quality (1-5), ignoring style entirely: how correct, complete and useful the reply is for the task. '
        '1 = wrong or useless, 3 = adequate with gaps, 5 = excellent.')
    lines.append('Refused: true only if the reply declines or fails to attempt the task.')
    return '\n'.join(lines)

SYSTEM = ('You evaluate the communication style of an AI assistant\'s reply. You are not told what style the assistant was asked to use; '
    'judge only what the reply does. Rate traits independently of each other and of task quality. Use the full scale where it fits.\n\n' + rubric())

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['traits', 'habits', 'task_quality', 'refused'],
    'properties': {
        'traits': {'type': 'object', 'additionalProperties': False, 'required': list(TRAITS),
            'properties': {t: {'type': 'integer', 'enum': [0, 1, 2, 3, 4]} for t in TRAITS}},
        'habits': {'type': 'object', 'additionalProperties': False, 'required': [h['id'] for h in HABITS],
            'properties': {h['id']: {'type': 'boolean'} for h in HABITS}},
        'task_quality': {'type': 'integer', 'enum': [1, 2, 3, 4, 5]},
        'refused': {'type': 'boolean'},
    },
}

def message(task, reply):
    return f'<task>\n{task}\n</task>\n\n<reply>\n{reply}\n</reply>\n\nRate the reply.'

def validate(data):
    """Raise ValueError unless data matches SCHEMA (defence in depth for any provider)."""
    if not isinstance(data, dict) or set(data) != set(SCHEMA['required']): raise ValueError('judge output keys')
    if set(data['traits']) != set(TRAITS) or any(type(v) is not int or not 0 <= v <= 4 for v in data['traits'].values()): raise ValueError('judge traits')
    if set(data['habits']) != {h['id'] for h in HABITS} or any(type(v) is not bool for v in data['habits'].values()): raise ValueError('judge habits')
    if type(data['task_quality']) is not int or not 1 <= data['task_quality'] <= 5 or type(data['refused']) is not bool: raise ValueError('judge quality')
    return data

def parse(text):
    return validate(json.loads(text))
