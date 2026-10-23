"""Train the on-host context classifier (opt-in OPENAPE_CONTEXT_TEXT=local).

A small linear model over hashed word and character n-grams that maps a user's
message to a task type and tags. It runs inside the host adapter; only the labels it
produces are ever sent. Python (sdk/python/lite.py) and TypeScript
(sdk/typescript/client.ts) apply it identically: decisions use only argmax and the
sign of a tag score, never exp(), so both languages agree bit for bit.

The corpus is generated here from CC0 templates written for this purpose (no
provider outputs, no real user messages). Template families are split, so the
held-out evaluation uses phrasings the model never saw. The report compares it with
the 0.3 keyword rules.

    python -m scripts.train_context_classifier
"""
import json
import random
import re
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'protocol/upap/v2/context-classifier.json'
REPORT = ROOT / 'docs/reports/context-classifier.json'
SEED, DIM = 20261023, 2048
TASKS = ['general', 'code_review', 'coding', 'support', 'creative', 'research', 'debugging', 'planning', 'writing']
TAGS = ['urgent', 'sensitive', 'beginner', 'expert', 'error_present']
# Tags implied by the task type rather than learned (as the host rules apply them).
TASK_TAGS = {'code_review': ['technical', 'review'], 'coding': ['technical'], 'debugging': ['technical']}

FILL = {
    'lang': ['Python', 'TypeScript', 'Go', 'Rust', 'Java', 'C#', 'Ruby', 'Kotlin', 'JavaScript', 'SQL', 'Bash', 'C++', 'PHP', 'Swift'],
    'thing': ['function', 'class', 'module', 'script', 'endpoint', 'query', 'component', 'migration', 'handler', 'test', 'parser', 'service', 'hook', 'CLI'],
    'tool': ['Docker', 'Kubernetes', 'Git', 'Postgres', 'Redis', 'Kafka', 'React', 'Django', 'Terraform', 'nginx', 'GraphQL', 'Spark', 'webpack', 'pytest'],
    'feature': ['login', 'search', 'checkout', 'notifications', 'billing', 'file upload', 'dark mode', 'export to CSV', 'pagination', 'rate limiting', 'caching', 'audit logging'],
    'topic': ['event sourcing', 'CRDTs', 'consensus algorithms', 'vector databases', 'garbage collection', 'type inference', 'B-trees', 'OAuth', 'WebAssembly', 'service meshes', 'feature flags', 'zero-downtime deploys'],
    'err': ['TypeError: cannot read property of undefined', 'NullPointerException', 'segmentation fault', 'KeyError', 'panic: runtime error: index out of range',
        'ModuleNotFoundError', 'connection refused', 'OOMKilled', '500 Internal Server Error', 'deadlock detected', 'stack overflow', 'Traceback (most recent call last)'],
    'doc': ['email', 'README', 'blog post', 'changelog entry', 'design doc', 'release note', 'cover letter', 'status update', 'announcement', 'postmortem summary', 'proposal'],
    'audience': ['my manager', 'the team', 'a customer', 'new contributors', 'our users', 'the board', 'a recruiter', 'stakeholders'],
}
# Template families per task type. {x} slots come from FILL.
TEMPLATES = {
    'code_review': [
        ['can you review this {lang} {thing}', 'please review my {thing}', 'review this diff for me', 'take a look at my pull request', 'any feedback on this {lang} {thing}?'],
        ['lgtm? here is the {thing}', 'is this {thing} ok to merge', 'what would you change in this {lang} code', 'spot any problems in this {thing}', 'code review please'],
        ['critique my implementation of the {thing}', 'is there anything wrong with this pr', 'check this {lang} {thing} for bugs before I merge', 'give me review comments on this change', 'does this {thing} follow best practices'],
    ],
    'coding': [
        ['write a {lang} {thing} that handles {feature}', 'implement {feature} in {lang}', 'add {feature} to our {tool} app', 'how do I implement a {thing} for {feature}', 'generate a {lang} {thing} for {feature}'],
        ['refactor this {thing} to be cleaner', 'convert this {lang} {thing} to {lang}', 'write unit tests for the {thing}', 'make this {thing} async', 'add type hints to this {lang} {thing}'],
        ['how do I parse json in {lang}', 'write a regex to match emails', 'create a {tool} config for {feature}', 'scaffold a {lang} {thing} with tests', 'build a small {thing} that talks to {tool}'],
    ],
    'debugging': [
        ['I get {err} when I run my {thing}', 'why does my {lang} {thing} throw {err}', 'getting {err} after upgrading {tool}', 'help me fix {err}', 'my build fails with {err}'],
        ['the {thing} crashes on startup', 'tests are failing after my change to the {thing}', 'this {lang} {thing} returns the wrong result', 'my {tool} container keeps restarting', 'the {feature} page hangs forever'],
        ['debug this: {err}', 'it works locally but fails in CI with {err}', 'intermittent {err} in production, where do I start', 'why is my {thing} so slow all of a sudden', 'memory keeps growing in our {lang} service'],
    ],
    'research': [
        ['what is {topic}', 'how does {topic} work', 'explain the trade-offs of {topic}', 'compare {tool} and {tool} for {feature}', 'what are the pros and cons of {topic}'],
        ['is {tool} a good fit for {feature}', 'which is better for {feature}: {tool} or {tool}', 'summarize the current approaches to {topic}', 'why does {lang} use {topic}', 'what should I know about {topic} before adopting it'],
        ['give me an overview of {topic}', 'how do companies usually handle {feature} at scale', 'what are alternatives to {tool}', 'investigate whether {topic} would help us', 'what does the research say about {topic}'],
    ],
    'planning': [
        ['help me plan the migration to {tool}', 'outline a roadmap for {feature}', 'how should we structure the rollout of {feature}', 'break down {feature} into milestones', 'draft a project plan for moving to {tool}'],
        ['what are the steps to adopt {topic}', 'plan the architecture for {feature}', 'how would you sequence the work to add {feature}', 'create a timeline for replacing {tool}', 'propose phases for migrating our {lang} services'],
        ['we need {feature} next quarter, how do we plan it', 'design the system for {feature}', 'what should the first sprint for {feature} contain', 'lay out a plan to reduce our tech debt', 'how do we organize the work across two teams'],
    ],
    'writing': [
        ['draft an {doc} to {audience}', 'write a {doc} about {feature}', 'help me word an {doc} for {audience}', 'rewrite this {doc} to be clearer', 'proofread my {doc}'],
        ['make this {doc} more concise', 'polish the wording of this {doc} for {audience}', 'turn these notes into a {doc}', 'edit this paragraph for tone', 'write a short {doc} announcing {feature}'],
        ['how do I phrase this {doc} politely', 'improve the grammar in this {doc}', 'write the intro section of our {doc}', 'summarize this thread as a {doc} for {audience}', 'translate this {doc} into plain English'],
    ],
    'creative': [
        ['brainstorm names for a {thing} that does {feature}', 'write a short poem about {tool}', 'come up with a slogan for our {feature} launch', 'suggest fun names for our team', 'write a story about a {thing} that came alive'],
        ['give me playful ideas for a hackathon about {topic}', 'invent a mascot for our {tool} meetup', 'write a limerick about {err}', 'creative ways to celebrate shipping {feature}', 'pitch three quirky themes for an offsite'],
        ['write a haiku about {topic}', 'imagine a sci-fi plot involving {topic}', 'make up a funny error message for {feature}', 'brainstorm a tagline for {tool}', 'dream up names for our new {lang} library'],
    ],
    'support': [
        ['I am stuck and frustrated with {tool}', 'I feel overwhelmed by our {lang} codebase', 'I keep failing at {topic}, any advice', 'nothing I try works with {tool} and I am exhausted', 'how do I stay motivated learning {lang}'],
        ['my teammate keeps rejecting my pull requests and I feel bad', 'I broke production yesterday and feel terrible', 'how do I ask for help without looking incompetent', 'I am anxious about my first on-call shift', 'I do not understand {topic} no matter what I read'],
        ['help me, I am confused by {tool}', 'I am lost, where do I even begin with {topic}', 'I am burned out from fixing {err} all week', 'any tips for imposter syndrome', 'I am struggling to keep up with the team'],
    ],
    'general': [
        ['thanks', 'hello there', 'what can you do', 'good morning', 'ok sounds good'],
        ['quick question', 'what time zone is UTC plus 2', 'how many days until the end of the month', 'tell me something interesting', 'can you remind me what we discussed'],
        ['hi, how are you', 'what do you think', 'never mind', 'got it, thanks', 'let us continue'],
    ],
}
MODIFIERS = {
    'urgent': ['urgent:', 'asap', 'this is blocking a release, please hurry', 'prod is down', 'I need this in ten minutes', 'emergency:', 'customers are affected right now', 'hotfix needed'],
    'sensitive': ['this touches customer passwords', 'it involves personal medical data', 'legal asked about this', 'we store credit card numbers here', 'this is security critical', 'there might be a vulnerability',
        'the production database is involved', 'it concerns employee salaries'],
    'beginner': ["I'm new to {lang}", 'explain like I am five', 'I have never used {tool} before', 'I am a beginner', 'this is my first time doing this', 'please keep it simple, I am just learning'],
    'expert': ['skip the basics', 'tl;dr please', 'just the code', 'no explanation needed', 'I know {tool} well, just the diff', 'give me the short version'],
    'error_present': ['here is the output: {err}', 'it prints {err}', 'the log shows {err}', 'error: {err}'],
}

def fill(text, rng):
    return re.sub(r'\{(\w+)\}', lambda m: rng.choice(FILL[m.group(1)]), text)

def corpus():
    rng = random.Random(SEED); rows = []
    for task, families in TEMPLATES.items():
        for family, templates in enumerate(families):
            for template in templates:
                for _ in range(60):
                    text = fill(template, rng); tags = set()
                    tags.update(TASK_TAGS.get(task, []))
                    if task == 'debugging' and '{err}' in template: tags.add('error_present')
                    for tag, mods in MODIFIERS.items():
                        if rng.random() < 0.18:
                            mod = fill(rng.choice(mods), rng); text = f'{mod} {text}' if rng.random() < 0.5 else f'{text}, {mod}'; tags.add(tag)
                    if rng.random() < 0.3: text = text.capitalize() + rng.choice(['', '.', '?', '!'])
                    rows.append(dict(text=text, task=task, tags=sorted(tags), family=f'{task}/{family}'))
    return rows

# --- the classifier (mirrors sdk/python/lite.py classify_text) ---
def fnv1a(s):
    h = 0x811c9dc5
    for b in s.encode('utf-8'):
        h = ((h ^ b) * 0x01000193) & 0xffffffff
    return h

def features(text, dim=DIM):
    words = re.findall(r'[a-z0-9]+', text.lower(), re.A)[:300]
    feats = {'w:' + w for w in words} | {'b:' + a + '_' + b for a, b in zip(words, words[1:])}
    for w in words:
        padded = '<' + w + '>'
        feats |= {'c:' + padded[i:i + 3] for i in range(len(padded) - 2)}
    return sorted({fnv1a(f) % dim for f in feats})

def matrix(rows):
    X = np.zeros((len(rows), DIM))
    for i, r in enumerate(rows):
        idx = features(r['text'])
        if idx: X[i, idx] = 1 / np.sqrt(len(idx))
    return X

def train(rows, steps=1500, lr=4.0, l2=2e-5):
    X = matrix(rows); n = len(rows)
    yt = np.zeros((n, len(TASKS))); yt[np.arange(n), [TASKS.index(r['task']) for r in rows]] = 1
    yg = np.array([[t in r['tags'] for t in TAGS] for r in rows], dtype=float)
    Wt = np.zeros((DIM, len(TASKS))); bt = np.zeros(len(TASKS)); Wg = np.zeros((DIM, len(TAGS))); bg = np.zeros(len(TAGS))
    for _ in range(steps):
        zt = X @ Wt + bt; zt -= zt.max(1, keepdims=True); pt = np.exp(zt); pt /= pt.sum(1, keepdims=True)
        pg = 1 / (1 + np.exp(-(X @ Wg + bg)))
        gt = (pt - yt) / n; gg = (pg - yg) / n
        Wt -= lr * (X.T @ gt + l2 * Wt); bt -= lr * gt.sum(0); Wg -= lr * (X.T @ gg + l2 * Wg); bg -= lr * gg.sum(0)
    return np.hstack([Wt, Wg]), np.concatenate([bt, bg])

def export(W, b):
    weights = {str(i): [round(float(v), 3) for v in W[i]] for i in range(DIM) if np.abs(W[i]).max() >= 0.001}
    return dict(format='openape-context-classifier/1', dim=DIM, tasks=TASKS, tags=TAGS, bias=[round(float(v), 3) for v in b], weights=weights,
        features='lowercase ASCII words [a-z0-9]+ (first 300): word unigrams, word bigrams and character trigrams of <word>; FNV-1a 32-bit mod dim; binary, scaled by 1/sqrt(n) in ascending index order',
        decision='task = argmax of task scores; tag present when its score > 0', task_tags=TASK_TAGS, provenance='CC0 synthetic templates in scripts/train_context_classifier.py; no real messages or model outputs')

def classify(model, text):
    idx = features(text, model['dim'])
    if not idx: return None
    scale = 1 / len(idx) ** 0.5; k = len(model['tasks']); scores = list(model['bias'])
    for i in idx:
        row = model['weights'].get(str(i))
        if row:
            for c in range(len(scores)): scores[c] += row[c] * scale
    task = model['tasks'][max(range(k), key=lambda c: (scores[c], -c))]
    return task, sorted(set(TASK_TAGS.get(task, [])) | {t for c, t in enumerate(model['tags']) if scores[k + c] > 0})

KEYWORDS = [  # the 0.3 keyword rules, kept here only for the comparison
    (r'\b(review|pr|pull request|code review|lgtm)\b', 'code_review', ['review']), (r'\b(debug|bug|traceback|exception|stack trace|segfault|error|failing|crash(es|ed)?)\b', 'debugging', ['technical', 'error_present']),
    (r'\b(story|poem|brainstorm|slogan|lyrics|creative)\b', 'creative', []), (r'\b(plan|roadmap|architecture|design doc|milestones?)\b', 'planning', []),
    (r'\b(draft|rewrite|proofread|email|blog post|essay|documentation)\b', 'writing', []), (r'\b(implement|refactor|compile|function|unit test)\b', 'coding', ['technical']),
    (r'\b(research|compare|investigate|survey|what is|how does|why does)\b', 'research', []), (r'\b(stuck|confused|not working|frustrat\w*|help me)\b', 'support', []),
    (r'\b(urgent|asap|immediately|outage|hotfix|prod(uction)? is down)\b', None, ['urgent']), (r'\b(security|vulnerabilit\w*|credentials?|password|legal|medical|production database)\b', None, ['sensitive']),
    (r'\b(beginner|eli5|explain like|new to|first time|never used)\b', None, ['beginner']), (r'\b(tl;?dr|just the (code|diff|answer)|skip the explanation|no explanation)\b', None, ['expert'])]

def keywords(text):
    task, tags = None, set()
    for pattern, t, tg in KEYWORDS:
        if re.search(pattern, text, re.I | re.A): task = task or t; tags.update(tg)
    return task or 'general', sorted(tags)

def score(rows, predict):
    task_acc = np.mean([predict(r['text'])[0] == r['task'] for r in rows]); f1 = {}
    for t in ['technical', 'review'] + TAGS:
        tp = sum(t in predict(r['text'])[1] and t in r['tags'] for r in rows); fp = sum(t in predict(r['text'])[1] and t not in r['tags'] for r in rows)
        fn = sum(t not in predict(r['text'])[1] and t in r['tags'] for r in rows)
        f1[t] = round(2 * tp / (2 * tp + fp + fn), 4) if tp + fp + fn else None
    return dict(task_accuracy=round(float(task_acc), 4), tag_f1=f1)

def main():
    rows = corpus()
    heldout = [r for r in rows if r['family'].endswith('/2')]; train_rows = [r for r in rows if not r['family'].endswith('/2')]
    W, b = train(train_rows); model = export(W, b)
    evaluation = dict(heldout_families=len({r['family'] for r in heldout}), heldout_rows=len(heldout), train_rows=len(train_rows),
        classifier=score(heldout, lambda t: classify(model, t) or ('general', [])), keyword_rules=score(heldout, keywords))
    W, b = train(rows); final = export(W, b)  # the shipped model trains on every family
    final['evaluation'] = dict(evaluation, note='held-out template families; synthetic, not real user messages')
    OUT.write_text(json.dumps(final, separators=(',', ':')) + '\n')
    REPORT.write_text(json.dumps(dict(kind='on-host context classifier evaluation; synthetic templates, not real messages', **evaluation), indent=2) + '\n')
    print(json.dumps(evaluation, indent=2))
if __name__ == '__main__': main()
