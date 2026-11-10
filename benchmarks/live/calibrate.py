"""Measure one model and write its Model Style Profile (ADR 0007).

    openape calibrate --model MODEL                       # plan and cost estimate, no calls
    openape calibrate --model MODEL --execute             # Claude, your ANTHROPIC_API_KEY
    openape calibrate --provider openai-compatible --model MODEL --base-url URL \\
        --judge-provider openai-compatible --judge-model JUDGE --execute --install
    openape calibrate --provider simulated --model sim-compressed --execute   # offline, known distortion

It runs the trait probes of the live evaluation (benchmarks/live: the neutral
configuration and each trait at every other level, on the fixed CC0 prompts) with your
own key, has the blind judge rate every reply, and fits the model's response curve per
trait. `--habits` also measures habit adherence. The profile is printed and written to
the run directory; `--install` also copies it into the engine's data directory, where
the engine applies it from its next start. The engine itself never calls a model.

A profile is one judge's measurement on a few prompts. Read the gamut report before
installing: a dead trait is left alone, and thin data moves a trait by one level at most.
"""
import argparse
import sys
from pathlib import Path
from benchmarks.live import run, profile
from engine.neural.calibration import model_key

ROOT = Path(__file__).resolve().parents[2]

def main(argv=None):
    ap = argparse.ArgumentParser(prog='openape calibrate', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', required=True, help='model under test, as the host names it')
    ap.add_argument('--as', dest='alias', help='model id the host sends, if different from --model (profiles are matched on host.model_id)')
    ap.add_argument('--habits', action='store_true', help='also measure habit adherence (about 60%% more calls)')
    ap.add_argument('--per-task', type=int, default=2, help='prompts per task type (2 = 18 prompts; 4 = all 36)')
    ap.add_argument('--reference', help='reference.json to measure against (default: the catalogue anchors)')
    ap.add_argument('--run-dir', help='where records are kept (default benchmarks/live/runs/calibrate-MODEL)')
    ap.add_argument('--install', action='store_true', help='copy the profile into the data directory')
    ap.add_argument('--data', default='.openape', help='engine data directory for --install')
    ap.add_argument('--execute', action='store_true', help='call models (otherwise a dry run)')
    a, passthrough = ap.parse_known_args(argv)  # provider, judge, placement, effort, workers...: as benchmarks.live.run
    run_dir = Path(a.run_dir or ROOT / 'benchmarks/live/runs' / ('calibrate-' + model_key(a.model).replace(':', '_')))
    args = ['--model', a.model, '--kinds', 'trait,habit' if a.habits else 'trait', '--per-task', str(a.per_task), '--run-dir', str(run_dir), '--no-report'] + passthrough
    code = run.main(args + (['--execute'] if a.execute else []))
    if code or not a.execute: return code
    import json
    placement = passthrough[passthrough.index('--placement') + 1] if '--placement' in passthrough else 'turn'
    ref = json.loads(Path(a.reference).read_text()) if a.reference else None
    p = profile.from_records(run.load(run_dir / 'records.jsonl'), a.model, placement, None, ref['traits'] if ref else None, ref.get('kind', 'consensus') if ref else 'anchors', run=run_dir.name)
    if a.alias:
        from engine.neural import calibration
        p = calibration.seal({**{k: v for k, v in p.items() if k != 'hash'}, 'model_id': model_key(a.alias), 'source': {**p['source'], 'measured_model': a.model}})
    print(profile.describe(p)); print(f'\nwrote {profile.write(p, run_dir)}')
    if a.install: print(f"installed {profile.write(p, Path(a.data) / 'style-profiles')}; restart `openape serve` to apply it")
    return 0

if __name__ == '__main__': sys.exit(main())
