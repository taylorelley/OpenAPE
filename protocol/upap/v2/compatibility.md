# Compatibility

0.3.0 implements the experimental OpenAPE profile of upap/2 and rejects other major
identifiers, including upap/1. Encoder/3, behaviour-controls/2, the catalogue hash and
the exact decoder hash travel with decisions and artifacts. Clients built for upap/1
fail open (they validate nothing they recognise and inject nothing). Decoder
replacement cannot continue old pinned sessions: clients fail open until a new
session. Compatible state import requires same tenant, format, dimensions, finite
values, valid hash and identical decoder.

upap/2 is a clean break from upap/1: controls are five-level integers plus habits
instead of one of 24 rows, feedback options are `{controls, habits}` choices instead of
row indices, and the context vocabulary grows. Persona latents are tied to their
decoder, so a 0.2 data directory must be reset with `openape migrate --reset`, which
re-creates personas from their recorded archetypes and individuality and keeps old
decisions and feedback as untrainable history. The engine refuses to start on an
unreset 0.2 store.

Extensions to the brief: persona list endpoint; selection/seed/exploration_consent;
engine_status, relationship_version and catalogue_hash fields; habits. These are
declared in schemas. A complete protocol compatibility guarantee is deferred until
the release gate.
