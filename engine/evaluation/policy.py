"""Independent fixed promotion rules. Trainer may return metrics, never thresholds."""
from dataclasses import dataclass, asdict
import hashlib
import json

@dataclass(frozen=True)
class EvaluationPolicy:
    minimum_train_groups: int = 4
    minimum_validation_groups: int = 2
    maximum_drift: float = 2.0
    maximum_kl: float = 0.15
    minimum_gain: float = 0.001
    def evaluate(self,metrics):
        checks={
            'train_groups':metrics['train_groups']>=self.minimum_train_groups,
            'validation_groups':metrics['validation_groups']>=self.minimum_validation_groups,
            'drift':metrics['drift']<=self.maximum_drift+1e-6,
            'kl':metrics['kl']<=self.maximum_kl,
            'heldout_gain':metrics['heldout_gain']>=self.minimum_gain,
            'constraints':metrics['constraints_ok'],
        }
        return {'eligible':all(checks.values()),'checks':checks,'metrics':metrics,'policy_hash':hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest(), 'evidence':'synthetic_or_explicit_feedback; not a live-model behavioral evaluation'}
