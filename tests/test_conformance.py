import json
from pathlib import Path
import pytest
from sdk.python.client import render
fixtures=json.loads(Path('protocol/upap/v2/conformance.json').read_text())
@pytest.mark.parametrize('case',fixtures['decisions'],ids=lambda f:f['name'])
def test_common_wire_fixtures(case):
    # Identical fixture and golden text are asserted by sdk/typescript/test.ts.
    if case['valid']:assert render(case['value'])==case['rendered']
    else:
        with pytest.raises(ValueError):render(case['value'])

def test_sdk_does_not_import_engine():
    import subprocess,sys
    code='import sys,sdk.python.client;assert not [m for m in sys.modules if m.startswith(("engine","torch","fastapi","pydantic"))]'
    assert subprocess.run([sys.executable,'-c',code]).returncode==0

def test_vendored_lite_clients_identical():
    canonical=Path('sdk/python/lite.py').read_bytes()
    for vendored in Path('adapters').glob('*/upap_lite.py'):assert vendored.read_bytes()==canonical,vendored
    from sdk.python.lite import CONTROLS,CONTROLS_HASH
    from protocol.catalogue import SPEC,CATALOGUE_HASH
    assert CONTROLS==json.loads(json.dumps(SPEC)) and CONTROLS_HASH==CATALOGUE_HASH
    assert json.loads(Path('renderers/controls-v2.json').read_text())==CONTROLS

def test_sdk_approval_matches_catalogue():
    import itertools
    from sdk.python import lite
    from protocol.catalogue import APPROVED,TRAITS,HABITS,habits_valid
    approved={tuple(c[t] for t in TRAITS) for c in APPROVED}
    for row in itertools.product(range(5),repeat=7):assert lite.coherent(dict(zip(TRAITS,row)))==(row in approved)
    for c in APPROVED[::997]:
        for h in HABITS:assert lite.habits_valid([h['id']],c)==habits_valid([h['id']],c)

def test_worst_case_rendering_within_bound():
    from protocol.catalogue import PREFIX,TEMPLATES,HABITS,MAX_HABITS,MAX_STYLE_CHARS
    worst=len(PREFIX)+sum(1+max(map(len,v)) for v in TEMPLATES.values())+sum(sorted(1+len(h['text']) for h in HABITS)[-MAX_HABITS:])
    assert worst<=MAX_STYLE_CHARS

@pytest.mark.parametrize('case',fixtures['contexts'],ids=lambda f:f['name'])
def test_context_derivation_fixtures(case):
    # The same fixtures are asserted against deriveContext in sdk/typescript/test.ts.
    from sdk.python.lite import derive_context
    assert derive_context(case['signals'],case['declared'],case['text'])==case['context']

def test_context_rules_match_engine_vocabulary():
    from sdk.python.lite import CONTEXT_RULES
    from engine.neural.policy import VOCAB
    from engine.api.contracts import Context
    vocab=CONTEXT_RULES['vocab']
    from engine.neural.policy import ENGINE_TAGS
    assert {k:tuple(vocab[k]) for k in VOCAB}==VOCAB and tuple(CONTEXT_RULES['engine_tags'])==ENGINE_TAGS
    Context(**CONTEXT_RULES['defaults'])
    for rule in CONTEXT_RULES['tools']+CONTEXT_RULES['text']+CONTEXT_RULES['failures']:
        Context(**{k:rule[k] for k in ('task_type','stakes') if k in rule},tags=rule.get('tags',[]))
    assert json.loads(Path('protocol/upap/v2/context-rules.json').read_text())==CONTEXT_RULES

def test_derived_context_never_contains_text():
    from sdk.python.lite import derive_context
    secret='zz-private-marker review this asap'
    assert 'zz-private-marker' not in json.dumps(derive_context({'tools':['Edit']},None,secret))
