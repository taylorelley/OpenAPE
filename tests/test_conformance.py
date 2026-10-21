import json
from pathlib import Path
import pytest
from sdk.python.client import render
fixtures=json.loads(Path('protocol/upap/v1/conformance.json').read_text())
@pytest.mark.parametrize('case',fixtures['decisions'],ids=lambda f:f['name'])
def test_common_wire_fixtures(case):
    if case['valid']:assert isinstance(render(case['value']),str)
    else:
        with pytest.raises(ValueError):render(case['value'])
