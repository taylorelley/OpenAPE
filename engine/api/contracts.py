"""UPAP/2 wire contracts. Unknown fields are rejected throughout."""
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from protocol.catalogue import HABIT_IDS, MAX_HABITS, PREFERENCES

Id = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')]
Level = Annotated[int, Field(ge=0, le=4)]
Habit = Literal[HABIT_IDS]
Seed = Literal['concise','detailed','warm','reserved','formal','casual','direct','gentle','playful','serious']
Archetype = Literal['balanced','mentor','pragmatic_engineer','concierge','collaborator','analyst','critic']
Trait = Literal['directness','warmth','verbosity','humour','formality','explanation_depth','assertiveness']
Horizon = Annotated[int, Field(ge=3, le=1000)]
Timestamp = Annotated[str, StringConstraints(max_length=40)]
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Envelope(Strict):
    protocol_version: Literal['upap/2']
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
    task_type: Literal['general','code_review','coding','support','creative','research','debugging','planning','writing'] = 'general'
    channel: Literal['terminal','chat','voice','background'] = 'terminal'
    stakes: Literal['low','medium','high'] = 'low'
    turn_origin: Literal['user','system','tool','subagent'] = 'user'
    # first_turn, long_session, returning and corrected are set by the engine; host values are ignored.
    tags: list[Literal['technical','review','sensitive','urgent','beginner','expert','error_present','first_turn','long_session','returning','corrected']] = Field(default_factory=list, max_length=11)
    # Labels only: the language of files the agent edited (from extensions) and the kind of repository.
    language: Literal['none','python','typescript','javascript','go','rust','java','c_cpp','csharp','ruby','php','shell','sql','markup','config','other'] = 'none'
    repo_kind: Literal['unknown','software','infrastructure','documentation','data_science'] = 'unknown'
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
    # Temperament variation around the archetype (0 = the exact archetype profile);
    # the seed defaults to one derived from tenant and persona id and is recorded.
    individuality: float = Field(default=0.3, ge=0, le=1)
    individuality_seed: int | None = Field(default=None, ge=0, le=2**31-1)
class Evolution(Envelope):
    evolution: Literal['automatic','manual'] | None = None
    maturation_rate: MaturationRate | None = None
    agent_feedback: bool | None = None
class Reflection(Envelope):
    reflection_id: Id
    decision_id: Id
    adjustments: dict[Trait, Literal['more','less']] = Field(default_factory=dict, max_length=3)
    habits: dict[Habit, Literal['more_often','less_often']] = Field(default_factory=dict, max_length=2)
    reason: Literal['user_requested','user_corrected','observed_preference']
    scope: Literal['core','relationship'] | None = None
    @model_validator(mode='after')
    def some_move(self):
        if not self.adjustments and not self.habits: raise ValueError('at least one trait or habit move required')
        return self
class Feedback(Envelope):
    feedback_id: Id
    decision_id: Id
    source: Literal['explicit_user','owner','verified_evaluator','agent_reflection']
    kind: Literal['rating','pairwise_preference','correction']
    actor_id: Id
    consent_scope: Literal['core','relationship','session','record_only'] = 'record_only'
    learning_consent: bool = False
    value: float | None = Field(default=None, ge=-1, le=1)
    preferred: 'Choice | None' = None
    rejected: 'Choice | None' = None
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
    directness: Level
    warmth: Level
    verbosity: Level
    humour: Level
    formality: Level
    explanation_depth: Level
    assertiveness: Level
class Choice(Strict):
    """One rendered style: an approved trait configuration and its habits (catalogue order)."""
    controls: Controls
    habits: list[Habit] = Field(default_factory=list, max_length=MAX_HABITS)
class Policy(Strict):
    eligible: bool
    mask_reason: str | None
def _slot(name):
    return Literal[tuple(PREFERENCES[name])] | None
class Preferences(Strict):
    """The linked user's explicit choices; each value renders one reviewed sentence."""
    address: _slot('address') = None
    spelling: _slot('spelling') = None
    units: _slot('units') = None
    format: _slot('format') = None
    dates: _slot('dates') = None
class Pin(Strict):
    min: Level = 0
    max: Level = 4
    @model_validator(mode='after')
    def ordered(self):
        if self.min > self.max: raise ValueError('pin min above max')
        return self
class Settings(Envelope):
    """User-controlled relationship settings: preferences, trait pins (allowed level
    ranges), habit vetoes, a freeze on relationship evolution, and consent to contribute
    this relationship to the persona's cohort prior."""
    preferences: Preferences = Field(default_factory=Preferences)
    pins: dict[Trait, Pin] = Field(default_factory=dict)
    vetoes: list[Habit] = Field(default_factory=list, max_length=16)
    frozen: bool = False
    cohort_contribution: bool = False
    # Occasionally serve a nearby style (low-stakes user turns only) so preferences can be compared.
    exploration: bool = False
class Comparison(Envelope):
    decision_id: Id
class Decision(Envelope):
    protocol_version: Literal['upap/2'] = 'upap/2'
    request_id: Id
    decision_id: Id
    persona_version: Id
    relationship_version: Id | None = None
    decoder_hash: str
    control_schema: Literal['behaviour-controls/2'] = 'behaviour-controls/2'
    catalogue_hash: str
    controls: Controls
    habits: list[Habit] = Field(max_length=MAX_HABITS)
    preferences: dict[str, str] = Field(default_factory=dict)
    # True when the user's opt-in exploration served a style other than the persona's first choice.
    exploration: bool = False
    mode: Literal['shadow','active','frozen']
    applies_to: Literal['next_model_request'] = 'next_model_request'
    policy: Policy
    cache_ttl_ms: int = 30000
    engine_status: Literal['experimental_synthetic','baseline_fallback']
    # Returned only to training administrators that request debug output.
    propensity: float | None = None
    diagnostics: dict[str, float] | None = None
Feedback.model_rebuild()
