# Compatibility

0.1.0 implements the experimental OpenAPE profile of upap/1. It rejects other
major identifiers. Encoder/1, behaviour-controls/1 and the exact decoder hash
travel with decisions/artifacts. Decoder replacement cannot continue old pinned
sessions: clients fail open until a new session. Compatible state import requires
same tenant, format, dimensions, finite values, valid hash and identical decoder.

Extensions to the brief: persona list endpoint; selection/seed/exploration_consent;
engine_status and relationship_version fields. These are declared in schemas.
A complete protocol compatibility guarantee is deferred until the release gate.
