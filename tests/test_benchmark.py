import pytest
from benchmarks.evaluate import evaluate

def test_paired_cluster_interval_and_synthetic_disclosure():
    rows=[dict(scenario_id=str(i),group_id=str(i//2),provider='fixture',harness='fixture',evidence_source='synthetic',**{k:dict(preference_satisfied=int(k=='D'),task_correct=1,safe=1) for k in 'ABCD'}) for i in range(12)]
    report=evaluate(rows)
    assert report['learning_minus_fixed_cluster_bootstrap_95_ci']==[1,1]
    assert report['measured_behavioral_benefit'] is False
    with pytest.raises(ValueError):evaluate(rows+rows)
