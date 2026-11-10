"""Blind line-up: which candidate reply was written in the same voice as the references?

The judge reads a few replies by one persona on one model, then several replies to a
different task on another model, one of them by the same persona. It is told nothing
about styles, personas or models. Chance is 1 / number of candidates.
"""
SYSTEM = ("You compare the communication style of AI assistant replies. You will see reference replies, all written in one assistant's voice, "
    'then several numbered candidate replies to a different task, written by different assistants. Exactly one candidate was written in the same '
    'voice as the references. Judge voice only: tone, directness, warmth, length, humour, formality, how much is explained, how firmly it '
    'recommends, and recurring habits such as how replies open and close. Ignore the topic and whether the answers are correct. '
    'Answer with the number of the candidate in the same voice.')

def schema(k):
    return {'type': 'object', 'additionalProperties': False, 'required': ['choice'], 'properties': {'choice': {'type': 'integer', 'enum': list(range(1, k + 1))}}}

def message(references, candidates):
    """`references` and `candidates`: lists of (task, reply)."""
    parts = [f'<reference n="{i}">\n<task>\n{task}\n</task>\n<reply>\n{reply}\n</reply>\n</reference>' for i, (task, reply) in enumerate(references, 1)]
    parts.append(f'<candidate_task>\n{candidates[0][0]}\n</candidate_task>')
    parts += [f'<candidate n="{i}">\n{reply}\n</candidate>' for i, (_, reply) in enumerate(candidates, 1)]
    return '\n\n'.join(parts) + '\n\nWhich candidate is in the same voice as the references?'

def ask(provider, model, references, candidates, effort=None):
    """Index (0-based) of the chosen candidate, with usage. Simulated providers answer themselves."""
    if hasattr(provider, 'lineup'): return provider.lineup(model, references, candidates, effort)
    r = provider.structured(model, SYSTEM, message(references, candidates), schema(len(candidates)), 'lineup', effort)
    choice = r['data'].get('choice') if isinstance(r['data'], dict) else None
    if type(choice) is not int or not 1 <= choice <= len(candidates): raise ValueError('line-up answer out of range')
    return dict(choice=choice - 1, served_model=r['served_model'], input_tokens=r['input_tokens'], output_tokens=r['output_tokens'])
