# Ten-minute local walkthrough

1. Install as in the README, then `openape init` and `openape serve`.
2. Second shell (same venv): create two personas from declared seed preferences:
   `openape persona create terse --seed concise --seed direct` and
   `openape persona create kind --seed warm --seed detailed`. The response labels
   `initialization: seed_preferences`; that is a declared prior, not learning.
3. Copy `examples/express.json`, set `identity.persona_id` to `terse`, and run
   `openape preview --file req.json`; repeat for `kind`. Identical context, visibly
   different approved controls and injected text. Repeat calls are deterministic.
4. `python -m scripts.offline_demo` creates its own persona, records 36 explicitly
   synthetic preference pairs on distinct sessions, trains a candidate, has the
   independent evaluator score held-out groups, promotes with compare-and-swap,
   exports and rolls back. `openape job JOB_ID` shows the evaluator report.
5. `openape persona history DEMO_ID` lists versions (with producing candidate and
   revoked flag) and the audit trail. Restart `openape serve` and inspect again to
   confirm SQLite persistence.
6. Mint a restricted host token: `openape token add --actor claude --personas terse`
   (restart serve). Install a host adapter (README table), set `OPENAPE_TOKEN`,
   `OPENAPE_PERSONA=terse`, `OPENAPE_MODE=active`, then `openape adapter doctor
   claude-code --persona terse`.
7. Stop the engine during a host session: the next prompt continues with no style
   injection (all five host smokes verify this).
8. Collect genuine opted-in feedback (`openape feedback --file f.json`, see
   `protocol/upap/v1/schema/feedback.json`), then `openape learn`, `openape job`,
   `openape promote --persona ID --file p.json` (candidate_id + expected_version).
   Rejected candidates stay inspectable and cannot promote.
9. Revoke a piece of evidence with an `experience.corrected` observation: only
   candidates/versions derived from it are invalidated; the persona falls back to the
   nearest clean ancestor. `openape rollback --persona ID --file r.json` restores any
   non-revoked version. Exports default to core state only.

Keep credentials out of git and transcripts. Hosts need only `persona:express` and
`observations:write`. Back up the data directory with the service stopped, together
with the exact decoder manifest.
