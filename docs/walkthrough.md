# Ten-minute local walkthrough

1. Install as in the README, then `openape init` and `openape serve`.
2. Second shell (same venv): `openape persona archetypes` lists the starting
   personas. Create two: `openape persona create terse --archetype
   pragmatic_engineer --maturation-rate fast` and `openape persona create kind
   --archetype mentor`. The response labels `initialization: archetype` (a
   declared prior, not learning) and `evolution: automatic`.
3. Copy `examples/express.json`, set `identity.persona_id` to `terse`, and run
   `openape preview --file req.json`; repeat for `kind`. Identical context, visibly
   different approved controls (a level 0-4 per trait), signature habits and
   injected text. Change `context.task_type` or `context.tags` (for example
   `debugging` with `beginner`) and the same persona adapts its levels. Repeat calls
   are deterministic. Upgrading a 0.2 data directory? Run `openape migrate --reset
   --data DIR` first.
4. `python -m scripts.offline_demo` first runs the manual path on a `manual`
   persona: it records 36 explicitly synthetic preference pairs on distinct
   sessions, trains a candidate, has the independent evaluator score held-out
   groups, promotes with compare-and-swap, exports and rolls back. It then creates
   a `mentor` persona at the `fast` rate and only uses it: 20 sessions with
   consented feedback and `session.ended`. The engine matures it on the square-root
   curve (frequent, larger steps first, settling at the horizon) and promotes the
   feedback candidate itself. `openape job JOB_ID` shows any evaluator report, and
   `openape persona inspect ID --user alice` shows growth.
   Inspect also shows the persona's development (ADR 0004): `individuality`
   (create a second mentor and its seed differs; `--individuality 0` gives the exact
   archetype), `effective_experience` (repeated identical sessions count less),
   `plasticity` and `boost`, and `character_drift` from the temperament. In
   `history`, `life_event` entries record role changes, new hosts and correction
   bursts. Each `matured` entry lists its `components`: curve, habit, cooling and
   elastic. Feedback with `consent_scope: session` returns `session_adapted: true`
   and changes later turns of that session only.
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
   `protocol/upap/v2/schema/feedback.json`). Automatic personas learn from it on
   their own once enough evidence has built up. In active mode the agent can also
   call its `persona_feedback` tool when you ask for a style change, including
   habits ("always end with next steps" → `next_step: more_often`). Watch
   `openape persona history ID`. Use `openape persona evolution ID --pause` to stop
   automatic evolution; for manual personas run `openape learn`, `openape job` and
   `openape promote --persona ID --file p.json` (candidate_id + expected_version).
   Rejected candidates stay inspectable and cannot promote.
9. Revoke a piece of evidence with an `experience.corrected` observation: only
   candidates/versions derived from it are invalidated; the persona falls back to the
   nearest clean ancestor. `openape rollback --persona ID --file r.json` restores any
   non-revoked version. Exports default to core state only.

Keep credentials out of git and transcripts. Hosts need only `persona:express`,
`observations:write` and, for the agent tool, `reflection:write`. Back up the data directory with the service stopped, together
with the exact decoder manifest.
