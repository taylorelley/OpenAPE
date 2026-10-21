"""Explicit failing release gates retained as strict xfails, linked to local issues."""
import pytest
@pytest.mark.parametrize('host',['hermes','claude-code','openclaw','opencogni'])
@pytest.mark.xfail(strict=True,reason='ISSUE-001: no verified full native host/model smoke; see docs/reports/open-issues.md')
def test_remaining_native_host_release_gates(host):
    pytest.fail(f'{host}: actual pinned host lifecycle + live-model integration not verified')
@pytest.mark.xfail(strict=True,reason='ISSUE-002: independent 200+ interaction A/B/C/D evidence is not available')
def test_independent_behavioral_benefit_release_gate():
    pytest.fail('No independent user/evaluator outcomes across 3 providers and 3 harnesses')
