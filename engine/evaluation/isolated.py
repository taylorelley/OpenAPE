"""The independent evaluator in a process of its own.

Candidate fitting and promotion run in the engine process; evaluation of a candidate
runs in a separate, spawned interpreter that loads the decoder itself from its file,
checks it against the expected hash, and returns only a report. Training code can
therefore not reach the evaluator's thresholds, decoder or code at run time: a
candidate is judged by exactly the code and weights on disk.

OPENAPE_EVALUATOR=inline evaluates in-process instead (for tools and debugging); the
report records which mode judged it.
"""
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

_DECODERS = {}

def _decoder(path, expected):
    from engine.neural.policy import Decoder
    if (path, expected) not in _DECODERS:
        d = Decoder(path)
        if d.hash != expected: raise RuntimeError('evaluator decoder does not match the engine decoder')
        _DECODERS[(path, expected)] = d
    return _DECODERS[(path, expected)]

def _evaluate(kind, path, expected, args):
    # Imported here so the worker loads the evaluator from disk, not from the parent.
    from engine.evaluation import policy
    report = getattr(policy, kind)(_decoder(path, expected), *args)
    return {**report, 'evaluator': {'isolation': 'process', 'pid': os.getpid()}}

class Evaluator:
    def __init__(self, decoder, decoder_path, mode=None):
        self.decoder, self.path = decoder, str(decoder_path)
        self.mode = mode or os.environ.get('OPENAPE_EVALUATOR', 'process')
        if self.mode not in ('process', 'inline'): raise ValueError('OPENAPE_EVALUATOR must be process or inline')
        self.pool = None
    def _run(self, kind, *args):
        if self.mode == 'inline':
            from engine.evaluation import policy
            return {**getattr(policy, kind)(self.decoder, *args), 'evaluator': {'isolation': 'inline', 'pid': os.getpid()}}
        if self.pool is None:
            self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
        return self.pool.submit(_evaluate, kind, self.path, self.decoder.hash, args).result(timeout=600)
    def candidate(self, core, rel, candidate, scope, train, valid, auto=False):
        return self._run('evaluate_candidate', core, rel, candidate, scope, train, valid, auto)
    def maturation(self, core, rel, candidate, scope, step_budget, feedback):
        return self._run('evaluate_maturation', core, rel, candidate, scope, step_budget, feedback)
    def close(self):
        if self.pool is not None: self.pool.shutdown(wait=True, cancel_futures=True)
