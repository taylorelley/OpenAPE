"""UPAP/1 wire contracts. Unknown fields are rejected throughout."""
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from protocol.catalogue import CATALOGUE

Id = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')]
ControlIndex = Annotated[int, Field(ge=0, le=len(CATALOGUE)-1)]
Seed = Literal['concise','detailed','warm','reserved','formal','casual','direct','gentle','playful','serious']
Archetype = Literal['balanced','mentor','pragmatic_engineer','concierge','collaborator','analyst','critic']
Trait = Literal['directness','warmth','verbosity','humour','formality','explanation_depth','assertiveness']
Horizon = Annotated[int, Field(ge=3, le=1000)]
Timestamp = Annotated[str, StringConstraints(max_length=40)]
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Envelope(Strict):
    protocol_version: Literal['upap/1']
class Identity(Strict):
    tenant_id: Id
    persona_id: Id
    user_id: Id | None = None
class Session(Strict):
    id: Id
    turn_id: Id
class Host(Strict):
    adapter_id: Id
    adapter_version: Id
    host_version: Id
    provider_family: Literal['openai','anthropic','google','qwen','other'] = 'other'
    model_id: Id = 'unspecified'
class Context(Strict):
    task_type: Literal['general','code_review','coding','support','creative','research'] = 'general'
    channel: Literal['terminal','chat','voice','background'] = 'terminal'
    stakes: Literal['low','medium','high'] = 'low'
    turn_origin: Literal['user','system','tool','subagent'] = 'user'
    tags: list[Literal['technical','review','sensitive','urgent','beginner','expert']] = Field(default_factory=list, max_length=6)
class Express(Envelope):
    request_id: Id
    identity: Identity
    session: Session
    host: Host
    context: Context = Field(default_factory=Context)
    mode: Literal['shadow','active','frozen'] = 'shadow'
    selection: Literal['argmax','sample'] = 'argmax'
    seed: int | None = None
    exploration_consent: bool = False
    pinned_version: Id | None = None
    debug: bool = False
class MaturationHorizon(Strict):
    relationship_horizon: Horizon
    core_horizon: Horizon
MaturationRate = Literal['fast','normal','slow'] | MaturationHorizon
class Create(Envelope):
    persona_id: Id
    archetype: Archetype | None = None
    seed_preferences: list[Seed] = Field(default_factory=list, max_length=5)
    parent_persona_id: Id | None = None
    evolution: Literal['automatic','manual'] = 'automatic'
    maturation_rate: MaturationRate | None = None
    agent_feedback: bool = True
class Evolution(Envelope):
    evolution: Literal['automatic','manual'] | None = None
    maturation_rate: MaturationRate | None = None
    agent_feedback: bool | None = None
class Reflection(Envelope):
    reflection_id: Id
    decision_id: Id
    adjustments: dict[Trait, Literal['more','less']] = Field(min_length=1, max_length=3)
    reason: Literal['user_requested','user_corrected','observed_preference']
    scope: Literal['core','relationship'] | None = None
class Feedback(Envelope):
    feedback_id: Id
    decision_id: Id
    source: Literal['explicit_user','owner','verified_evaluator','agent_reflection']
    kind: Literal['rating','pairwise_preference','correction']
    actor_id: Id
    consent_scope: Literal['core','relationship','session','record_only'] = 'record_only'
    learning_consent: bool = False
    value: float | None = Field(default=None, ge=-1, le=1)
    preferred_control: ControlIndex | None = None
    rejected_control: ControlIndex | None = None
    evidence_group: Id
    occurred_at: Timestamp | None = None
    evidence_refs: list[Id] = Field(default_factory=list, max_length=8)
class Event(Strict):
    event_id: Id
    occurred_at: str = Field(max_length=40)
    persona_id: Id
    user_id: Id | None = None
    session_id: Id | None = None
    decision_id: Id | None = None
    type: Literal['session.started','turn.preparing','turn.completed','turn.failed','model.changed','session.compacted','session.ended','tool.result.summary','experience.corrected']
    status: Literal['ok','failed','aborted'] = 'ok'
    feedback_id: Id | None = None
class Observations(Envelope):
    adapter_id: Id
    events: list[Event] = Field(min_length=1, max_length=100)
class Consolidate(Envelope):
    persona_id: Id
    scope: Literal['core','relationship'] = 'relationship'
    user_id: Id | None = None
    seed: int = 42
class Promote(Envelope):
    candidate_id: Id
    expected_version: Id
class Rollback(Envelope):
    version: Id
    reason: str = Field(min_length=3,max_length=300)
class Export(Envelope):
    include_relationships: bool = False
class Import(Envelope):
    persona_id: Id
    bundle: dict
class Controls(Strict):
    directness: Literal['low','moderate','high']
    warmth: Literal['low','moderate','high']
    verbosity: Literal['low','moderate','high']
    humour: Literal['low','moderate','high']
    formality: Literal['low','moderate','high']
    explanation_depth: Literal['low','moderate','high']
    assertiveness: Literal['low','moderate','high']
class Policy(Strict):
    eligible: bool
    mask_reason: str | None
class Decision(Envelope):
    protocol_version: Literal['upap/1'] = 'upap/1'
    request_id: Id
    decision_id: Id
    persona_version: Id
    relationship_version: Id | None = None
    decoder_hash: str
    control_schema: Literal['behaviour-controls/1'] = 'behaviour-controls/1'
    control_set_id: str
    controls: Controls
    mode: Literal['shadow','active','frozen']
    applies_to: Literal['next_model_request'] = 'next_model_request'
    policy: Policy
    cache_ttl_ms: int = 30000
    engine_status: Literal['experimental_synthetic','baseline_fallback']
    # Returned only to training administrators that request debug output.
    propensity: float | None = None
    diagnostics: dict[str, float] | None = None
