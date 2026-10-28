"""Observation and offline decision contracts. No IO or live integration."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math


class Truth(str, Enum):
    YES = 'YES'
    NO = 'NO'
    UNKNOWN = 'UNKNOWN'


class Knownness(str, Enum):
    KNOWN = 'KNOWN'
    UNKNOWN = 'UNKNOWN'


class Freshness(str, Enum):
    FRESH = 'FRESH'
    STALE = 'STALE'


class Source(str, Enum):
    RUNTIME_OBSERVATION = 'RUNTIME_OBSERVATION'
    KNOWLEDGE_SNAPSHOT = 'KNOWLEDGE_SNAPSHOT'
    PLAYER_MODEL = 'PLAYER_MODEL'
    EXPERT_HEURISTIC = 'EXPERT_HEURISTIC'


class ObservationSource(str, Enum):
    """Additional observational origin; keep the established Source enum stable."""
    SAFETY_EVIDENCE = 'SAFETY_EVIDENCE'


class Action(str, Enum):
    TAKE_ONE_MORE_WAVE = 'TAKE_ONE_MORE_WAVE'
    LEAVE_TO_SAFE_FARM = 'LEAVE_TO_SAFE_FARM'
    SAFE_RESOURCE_THEN_REEVALUATE = 'SAFE_RESOURCE_THEN_REEVALUATE'
    HOLD_AND_REEVALUATE = 'HOLD_AND_REEVALUATE'
    ABORT_CURRENT_ROUTE = 'ABORT_CURRENT_ROUTE'
    NO_DIRECTIVE = 'NO_DIRECTIVE'


PRODUCTIVE_ACTIONS = (Action.TAKE_ONE_MORE_WAVE, Action.LEAVE_TO_SAFE_FARM,
                      Action.SAFE_RESOURCE_THEN_REEVALUATE)


class ExecutionState(str, Enum):
    NOT_STARTED = 'NOT_STARTED'
    IN_PROGRESS = 'IN_PROGRESS'


class Authority(str, Enum):
    DIRECTIVE = 'DIRECTIVE'
    ADVISORY = 'ADVISORY'
    AWARENESS = 'AWARENESS'
    SUPPRESS = 'SUPPRESS'


class Validity(str, Enum):
    VALID = 'VALID'
    EXPIRED = 'EXPIRED'
    INVALID = 'INVALID'


class Risk(str, Enum):
    ACCEPTABLE = 'ACCEPTABLE'
    UNSAFE = 'UNSAFE'
    UNKNOWN = 'UNKNOWN'


class Confidence(str, Enum):
    SUPPORTED = 'SUPPORTED'
    LIMITED = 'LIMITED'


class Reason(str, Enum):
    SAFE_WAVE = 'farm_cycle.safe_wave.v1'
    SAFER_FARM = 'farm_cycle.safer_farm.v1'
    PRODUCTIVE_WAIT = 'farm_cycle.productive_wait.v1'
    RISK_WITHOUT_ROUTE = 'farm_cycle.risk_without_route.v1'
    INSUFFICIENT_EVIDENCE = 'farm_cycle.insufficient_evidence.v1'
    CONTINUE_ROUTE = 'farm_cycle.continue_route.v1'
    ROUTE_UNSAFE = 'farm_cycle.route_unsafe.v1'
    ROUTE_UNCONFIRMED = 'farm_cycle.route_unconfirmed.v1'
    EVIDENCE_STALE = 'decision.evidence_stale.v1'
    EVIDENCE_CHANGED = 'decision.evidence_changed.v1'
    EVIDENCE_UNKNOWN = 'decision.evidence_unknown.v1'
    SNAPSHOT_CHANGED = 'decision.snapshot_changed.v1'
    EXECUTION_CHANGED = 'decision.execution_changed.v1'
    OUTPUT_DISABLED = 'decision.output_disabled.v1'
    NOT_VALID = 'decision.not_valid.v1'


@dataclass(frozen=True)
class Provenance:
    source: Source | ObservationSource
    ref: str


@dataclass(frozen=True)
class KnowledgeSnapshotRef:
    snapshot_id: str
    version: str


@dataclass(frozen=True)
class PlayerModelSnapshotRef:
    snapshot_id: str
    version: str


@dataclass(frozen=True)
class ObservedFact:
    """Boolean observation only, e.g. entity visible; never 'route is safe'."""
    ref: str
    value: Truth
    freshness: Freshness
    source: Source | ObservationSource = Source.RUNTIME_OBSERVATION

    def __post_init__(self):
        if not self.ref or not isinstance(self.value, Truth) or not isinstance(self.freshness, Freshness):
            raise ValueError('invalid_observed_fact')
        if self.source is not Source.RUNTIME_OBSERVATION and self.source is not ObservationSource.SAFETY_EVIDENCE:
            raise ValueError('invalid_observational_source')


@dataclass(frozen=True)
class ScalarObservation:
    """A scalar from normalized State, with explicit knownness and source.

    FRESH refers to the supplied snapshot, not to a measured receipt age. This
    representation is separate from the Truth-valued facts used by fixtures.
    """
    provenance: Provenance
    knownness: Knownness
    value: bool | int | float | str | None = None
    freshness: Freshness = Freshness.FRESH

    def __post_init__(self):
        if (not isinstance(self.provenance, Provenance)
                or self.provenance.source is not Source.RUNTIME_OBSERVATION
                or type(self.provenance.ref) is not str or not self.provenance.ref
                or not isinstance(self.knownness, Knownness)
                or not isinstance(self.freshness, Freshness)):
            raise ValueError('invalid_scalar_observation')
        if self.knownness == Knownness.UNKNOWN:
            if self.value is not None:
                raise ValueError('unknown_scalar_has_value')
        elif (type(self.value) not in (bool, int, float, str)
              or (type(self.value) is float and not math.isfinite(self.value))):
            raise ValueError('invalid_known_scalar')


@dataclass(frozen=True)
class RuntimeObservation:
    observation_id: str
    facts: tuple[ObservedFact, ...]
    scalars: tuple[ScalarObservation, ...] = ()

    def __post_init__(self):
        if not self.observation_id or type(self.facts) is not tuple:
            raise ValueError('invalid_observation')
        if len({f.ref for f in self.facts}) != len(self.facts):
            raise ValueError('duplicate_evidence_ref')
        if type(self.scalars) is not tuple or any(not isinstance(s, ScalarObservation) for s in self.scalars):
            raise ValueError('invalid_scalar_collection')
        refs = [f.ref for f in self.facts] + [s.provenance.ref for s in self.scalars]
        if len(set(refs)) != len(refs):
            raise ValueError('duplicate_evidence_ref')


@dataclass(frozen=True)
class Claim:
    """Supplied semantic assessment, explicitly an unvalidated expert heuristic.

    This prototype does not calculate route safety from positions or vision.
    Fixture authors must supply scoped assessments and their observation refs.
    """
    value: Truth
    evidence_refs: tuple[str, ...]
    rule_ref: str

    def __post_init__(self):
        if not isinstance(self.value, Truth) or type(self.evidence_refs) is not tuple or not self.rule_ref:
            raise ValueError('invalid_claim')


@dataclass(frozen=True)
class OptionAssessment:
    plan_id: str
    action: Action
    available: Claim
    safe: Claim


@dataclass(frozen=True)
class Execution:
    state: ExecutionState = ExecutionState.NOT_STARTED
    plan_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.state, ExecutionState):
            raise ValueError('invalid_execution_state')
        if (self.state == ExecutionState.IN_PROGRESS) != bool(self.plan_id):
            raise ValueError('execution_requires_exactly_one_active_plan')


@dataclass(frozen=True)
class Condition:
    key: str
    value: Truth
    freshness: Freshness
    evidence: tuple[ObservedFact, ...]
    provenance: tuple[Provenance, ...]


@dataclass(frozen=True)
class Option:
    plan_id: str
    action: Action
    available: Condition
    safe: Condition


@dataclass(frozen=True)
class DecisionContext:
    observation_id: str
    knowledge: KnowledgeSnapshotRef
    player: PlayerModelSnapshotRef
    options: tuple[Option, ...]
    increased_risk: Condition
    execution: Execution

    @property
    def conditions(self):
        return (self.increased_risk,) + tuple(c for o in self.options for c in (o.available, o.safe))


def build_context(observation, knowledge, player, assessments, increased_risk,
                  execution=Execution()):
    """Resolve explicit fixture assessments against supplied facts, fail closed.

    Freshness is supplied, not calculated from invented time thresholds. Unknown
    or missing support never becomes a confirmed semantic proposition. References
    to knowledge/player snapshots provide lineage only; no contents are accessed.
    """
    for snapshot in (knowledge, player):
        if not snapshot.snapshot_id or not snapshot.version:
            raise ValueError('versioned_snapshot_required')
    if any(not isinstance(o.action, Action) or o.action not in PRODUCTIVE_ACTIONS or not o.plan_id or o.plan_id.startswith('@') for o in assessments):
        raise ValueError('invalid_farm_option')
    if len({o.plan_id for o in assessments}) != len(assessments) or len({o.action for o in assessments}) != len(assessments):
        raise ValueError('duplicate_farm_option')
    facts = {f.ref: f for f in observation.facts}

    def resolve(key, claim):
        evidence = tuple(facts.get(ref, ObservedFact(ref, Truth.UNKNOWN, Freshness.STALE))
                         for ref in claim.evidence_refs)
        fresh = Freshness.STALE if any(f.freshness == Freshness.STALE for f in evidence) else Freshness.FRESH
        supported = bool(evidence) and all(f.value != Truth.UNKNOWN for f in evidence)
        value = claim.value if supported and fresh == Freshness.FRESH else Truth.UNKNOWN
        provenance = tuple(Provenance(f.source, f.ref) for f in evidence)
        return Condition(key, value, fresh, evidence,
                         provenance + (Provenance(Source.EXPERT_HEURISTIC, claim.rule_ref),))

    options = tuple(Option(o.plan_id, o.action, resolve(o.plan_id + ':available', o.available),
                           resolve(o.plan_id + ':safe', o.safe))
                    for o in sorted(assessments, key=lambda o: o.action.value))
    return DecisionContext(observation.observation_id, knowledge, player, options,
                           resolve('@risk', increased_risk), execution)


@dataclass(frozen=True)
class CandidatePlan:
    plan_id: str
    action: Action
    feasibility: Truth
    risk: Risk
    dependencies: tuple[Condition, ...]
    expected_future_state: str


@dataclass(frozen=True)
class Decision:
    decision_id: str
    context_id: str
    domain: str
    objective: str
    candidate_plans: tuple[CandidatePlan, ...]
    selected_plan: CandidatePlan
    execution: Execution
    confidence: Confidence
    output_authority: Authority
    reason_codes: tuple[Reason, ...]
    provenance: tuple[Provenance, ...]
    knowledge: KnowledgeSnapshotRef
    player: PlayerModelSnapshotRef
    validity: Validity = Validity.VALID
    invalidation_conditions: tuple[str, ...] = (
        'support_stale_or_unknown', 'support_or_snapshot_changed', 'execution_changed')
    preemption_conditions: tuple[str, ...] = ('active_route_materially_unsafe',)

    @property
    def next_action(self): return self.selected_plan.action

    @property
    def evidence_dependencies(self): return self.selected_plan.dependencies


@dataclass(frozen=True)
class Validation:
    state: Validity
    reasons: tuple[Reason, ...] = ()


def context_id(context):
    payload = json.dumps(asdict(context), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_decision(decision, context):
    """Recheck a previous decision; no clock, scheduler or transport required."""
    if decision.validity != Validity.VALID:
        return Validation(decision.validity, (Reason.NOT_VALID,))
    if decision.knowledge != context.knowledge or decision.player != context.player:
        return Validation(Validity.INVALID, (Reason.SNAPSHOT_CHANGED,))
    if decision.execution != context.execution:
        return Validation(Validity.INVALID, (Reason.EXECUTION_CHANGED,))
    current = {c.key: c for c in context.conditions}
    for dependency in decision.evidence_dependencies:
        now = current.get(dependency.key)
        if now is None:
            return Validation(Validity.INVALID, (Reason.EVIDENCE_UNKNOWN,))
        if now.freshness == Freshness.STALE:
            return Validation(Validity.EXPIRED, (Reason.EVIDENCE_STALE,))
        if now != dependency:
            return Validation(Validity.INVALID, (Reason.EVIDENCE_CHANGED,))
    # Even an advisory based on insufficient information must be reconsidered
    # when its supplied context changes, rather than persisting indefinitely.
    if decision.context_id != context_id(context):
        return Validation(Validity.INVALID, (Reason.EVIDENCE_CHANGED,))
    return Validation(Validity.VALID)


@dataclass(frozen=True)
class Output:
    """Machine-readable attention result, not UI or user-facing presentation."""
    decision_id: str
    authority: Authority
    next_action: Action
    validity: Validation
    reason_codes: tuple[Reason, ...]


def authorize_output(decision, context, *, enabled=True):
    validity = validate_decision(decision, context)
    authority = decision.output_authority
    reasons = decision.reason_codes + validity.reasons
    if not enabled or validity.state != Validity.VALID:
        authority = Authority.SUPPRESS
        if not enabled: reasons += (Reason.OUTPUT_DISABLED,)
    action = decision.next_action if authority in (Authority.DIRECTIVE, Authority.ADVISORY) else Action.NO_DIRECTIVE
    return Output(decision.decision_id, authority, action, validity, reasons)
