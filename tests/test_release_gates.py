"""Explicit failing release gates retained as strict xfails, linked to local issues.
Host lifecycle smoke tests (scripts/*_host_smoke.py) use real hosts with a synthetic
model endpoint; live-provider and independent behavioural evidence remain open."""
import pytest
@pytest.mark.xfail(strict=True,reason='ISSUE-001: no live-provider model run across >=3 model families; host smokes use synthetic model endpoints')
def test_live_model_release_gate():
    pytest.fail('No live provider credentials were used')
@pytest.mark.xfail(strict=True,reason='ISSUE-001: OpenCogni planner integration needs the upstream boundary patch to be reviewed and merged')
def test_opencogni_upstream_release_gate():
    pytest.fail('adapters/opencogni/upstream patch not merged in OpenCogni main')
@pytest.mark.xfail(strict=True,reason='ISSUE-002: independent 200+ interaction A/B/C/D evidence is not available')
def test_independent_behavioral_benefit_release_gate():
    pytest.fail('No independent user/evaluator outcomes across 3 providers and 3 harnesses')
