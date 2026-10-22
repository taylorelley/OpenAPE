import json
from pathlib import Path
import pytest
from sdk.python.client import render
fixtures=json.loads(Path('protocol/upap/v1/conformance.json').read_text())
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
    from sdk.python.lite import CATALOGUE
    from protocol.catalogue import CATALOGUE as SOURCE
    assert CATALOGUE==SOURCE
