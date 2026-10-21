# Ten-minute local walkthrough

1. Follow README installation, run `openape init`, then `openape serve`.
2. In a second shell with the venv active, `openape persona create ape`.
3. `openape express --file examples/express.json` returns a shadow decision.
   To preview active style use the Python client with mode='active'; the SDK
   renderer returns a short approved instruction, never arbitrary prompt text.
4. Run `python -m scripts.offline_demo`. This creates its own persona, records
   36 explicitly synthetic preference pairs on distinct sessions, trains a latent
   candidate, checks held-out gain/drift, promotes manually, exports and rolls back.
   The default owner credential is required for this admin demonstration.
5. Inspect its returned persona ID: `openape persona history DEMO_ID`.
6. Stop/restart `openape serve`; inspect again to verify SQLite persistence.
7. For Pi, install the pinned smoke dependency as shown in README, then run
   `python -m scripts.real_host_smoke`. This uses a real native SDK session with
   synthetic model I/O; it makes no provider API calls. For normal Pi usage,
   review `docs/adapters/compatibility.md` and configure a restricted host token.
8. Stop the engine during a host session. Client deadline/fallback tests verify
   empty injection or exact-scoped short-lived cache; host tasks continue.
9. Use explicit feedback requests from protocol schemas to collect genuine opted-in
   preference pairs. `openape learn --file job.json` returns job_id. Poll the HTTP
   consolidation endpoint; inspect metrics. `openape promote --persona ID --file
   promotion.json` needs candidate_id and expected_version. Rejected candidates
   remain inspectable and cannot promote.
10. `openape rollback --persona ID --file rollback.json` takes version and reason.
    Exports default to core only. `openape persona delete ID` permanently deletes
    the scoped persona and its derived state; export first if you want a backup.

No credentials belong in git or transcripts. Create separate host and admin
credentials; hosts do not need persona:admin or training:admin. Back up the data
directory with the service stopped; keep the exact decoder manifest with it.
