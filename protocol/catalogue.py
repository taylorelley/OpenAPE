"""Audited behaviour-controls/2 catalogue; no runtime ML dependency.

Seven style traits, each on a five-level scale (0-4) with one fixed, reviewed
sentence per level. Reviewed coherence rules forbid level pairs that contradict each
other; every combination of the 5^7 that passes them is an approved configuration
(APPROVED, enumerated once). Signature habits are a fixed list of reviewed sentences
with static eligibility on the trait levels; at most MAX_HABITS apply per turn.

Nothing here grants permissions or changes what the agent does: every sentence is a
style preference, and assertiveness never changes factual certainty. Changing any
text, rule or habit requires a new control schema and decoder; CATALOGUE_HASH binds
decisions to this exact catalogue.
"""
import hashlib
import itertools
import json

SCHEMA = 'behaviour-controls/2'
TRAITS = ('directness', 'warmth', 'verbosity', 'humour', 'formality', 'explanation_depth', 'assertiveness')
LEVELS = 5
PREFIX = 'Style preferences only. Host, system, developer, safety and user task requirements take precedence.'
TEMPLATES = {
    'directness': ('Use gentle, indirect phrasing.', 'Use gentle phrasing.', 'Be clear.', 'Lead with the answer.', 'Lead with the answer and skip preamble.'),
    'warmth': ('Use a strictly neutral tone.', 'Use a neutral tone.', 'Be considerate.', 'Use a warm, supportive tone.', 'Use a very warm, encouraging tone.'),
    'verbosity': ('Keep responses as short as possible.', 'Keep responses concise.', 'Use moderate detail.', 'Include useful detail.', 'Be thorough and comprehensive.'),
    'humour': ('Avoid humour.', 'Avoid humour unless the user jokes first.', 'Use light humour when appropriate.', 'Use humour when appropriate.', 'Be playful and use humour freely when appropriate.'),
    'formality': ('Use relaxed, conversational language.', 'Use casual language.', 'Use plain professional language.', 'Use formal language.', 'Use formal, precise language.'),
    'explanation_depth': ('Skip explanation unless asked.', 'Give essential explanation.', 'Explain key reasoning.', 'Explain reasoning with examples.', 'Explain reasoning step by step with examples.'),
    'assertiveness': ('Offer options rather than recommendations.', 'Offer suggestions gently.', 'State recommendations clearly without changing factual certainty.',
        'Be decisive without changing factual certainty.', 'Give firm recommendations without changing factual certainty.'),
}
# The approved neutral fallback: moderate everything, no humour (never masked by context).
NEUTRAL = {'directness': 2, 'warmth': 2, 'verbosity': 2, 'humour': 0, 'formality': 2, 'explanation_depth': 2, 'assertiveness': 2}
# Coherence: (trait, levels, other trait, other levels) that may not co-occur.
RULES = (
    ('verbosity', (0,), 'explanation_depth', (3, 4)),
    ('verbosity', (4,), 'explanation_depth', (0,)),
    ('formality', (4,), 'humour', (3, 4)),
    ('warmth', (0,), 'humour', (3, 4)),
    ('directness', (0,), 'assertiveness', (3, 4)),
    ('directness', (4,), 'assertiveness', (0,)),
)
MAX_HABITS = 3
# `requires`: inclusive [min, max] trait levels; `excludes`: habits it cannot join.
HABITS = (
    {'id': 'summary_first', 'text': 'Open with a one-line summary.', 'requires': {'verbosity': (2, 4)}, 'excludes': ()},
    {'id': 'risks_first', 'text': 'Flag important risks or caveats early.', 'requires': {}, 'excludes': ()},
    {'id': 'next_step', 'text': 'End with a suggested next step when one is useful.', 'requires': {}, 'excludes': ()},
    {'id': 'confirm_goal', 'text': 'Restate the goal in one sentence before a long answer.', 'requires': {'verbosity': (3, 4)}, 'excludes': ()},
    {'id': 'clarify_once', 'text': 'Ask one clarifying question when a request is genuinely ambiguous.', 'requires': {}, 'excludes': ()},
    {'id': 'acknowledge_constraints', 'text': "Acknowledge the user's stated constraints before advising.", 'requires': {}, 'excludes': ()},
    {'id': 'concrete_examples', 'text': 'Prefer concrete examples over abstractions.', 'requires': {'explanation_depth': (2, 4)}, 'excludes': ()},
    {'id': 'analogies', 'text': 'Use a brief analogy when it aids understanding.', 'requires': {'explanation_depth': (2, 4), 'formality': (0, 3)}, 'excludes': ()},
    {'id': 'structured', 'text': 'Use short lists or headings for multi-part answers.', 'requires': {}, 'excludes': ()},
    {'id': 'plain_words', 'text': 'Prefer plain words over jargon.', 'requires': {}, 'excludes': ('precise_terms',)},
    {'id': 'precise_terms', 'text': 'Use precise technical terms.', 'requires': {}, 'excludes': ('plain_words',)},
    {'id': 'tradeoffs', 'text': 'Name the main trade-off behind a recommendation.', 'requires': {'explanation_depth': (1, 4)}, 'excludes': ()},
    {'id': 'acknowledge_progress', 'text': 'Briefly acknowledge progress and good decisions.', 'requires': {'warmth': (3, 4)}, 'excludes': ()},
    {'id': 'light_aside', 'text': 'Allow an occasional light aside.', 'requires': {'humour': (2, 4)}, 'excludes': ()},
    {'id': 'recap_end', 'text': 'Close long answers with a short recap.', 'requires': {'verbosity': (3, 4)}, 'excludes': ()},
    {'id': 'flag_uncertainty', 'text': 'Say plainly when you are unsure.', 'requires': {}, 'excludes': ()},
)
HABIT_IDS = tuple(h['id'] for h in HABITS)
MAX_STYLE_CHARS = 900  # ~150 tokens; the worst case rendering is well below it.

def coherent(levels):
    """True if a {trait: level} mapping is a complete, in-range, coherent configuration."""
    if set(levels) != set(TRAITS) or any(type(levels[t]) is not int or not 0 <= levels[t] < LEVELS for t in TRAITS): return False
    return not any(levels[a] in la and levels[b] in lb for a, la, b, lb in RULES)

def habit_allowed(habit, levels):
    return all(lo <= levels[t] <= hi for t, (lo, hi) in habit['requires'].items())

def habits_valid(ids, levels):
    """Known, unique, at most MAX_HABITS, in catalogue order, eligible and not mutually exclusive."""
    if not isinstance(ids, (list, tuple)) or len(ids) > MAX_HABITS or any(i not in HABIT_IDS for i in ids): return False
    if list(ids) != sorted(set(ids), key=HABIT_IDS.index): return False
    by_id = {h['id']: h for h in HABITS}
    return all(habit_allowed(by_id[i], levels) and not set(by_id[i]['excludes']) & set(ids) for i in ids)

APPROVED = [dict(zip(TRAITS, row)) for row in itertools.product(range(LEVELS), repeat=len(TRAITS)) if coherent(dict(zip(TRAITS, row)))]
SPEC = {'schema': SCHEMA, 'traits': list(TRAITS), 'levels': LEVELS, 'prefix': PREFIX, 'templates': {t: list(v) for t, v in TEMPLATES.items()}, 'neutral': NEUTRAL,
    'rules': [[a, list(la), b, list(lb)] for a, la, b, lb in RULES], 'max_habits': MAX_HABITS, 'max_style_chars': MAX_STYLE_CHARS,
    'habits': [{'id': h['id'], 'text': h['text'], 'requires': {t: list(r) for t, r in h['requires'].items()}, 'excludes': list(h['excludes'])} for h in HABITS]}
CATALOGUE_HASH = 'sha256:' + hashlib.sha256(json.dumps(SPEC, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
assert coherent(NEUTRAL) and len(set(HABIT_IDS)) == len(HABIT_IDS)
