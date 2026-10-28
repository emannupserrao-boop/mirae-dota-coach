"""Explicit per-dimension semantic assertions at the accepted context boundary."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .decision_context_v02 import DecisionContextV2, OptionDecisionContextV2


RULESET = 'objective.outcome_relation.v1'


class ObjectiveOutcomeRelation(str, Enum):
    SUPPORTS = 'SUPPORTS'
    OPPOSES = 'OPPOSES'
    NEUTRAL = 'NEUTRAL'
    UNKNOWN = 'UNKNOWN'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _key(claim):
    return (claim.decision_context_id, claim.option_id, claim.objective_context_id,
            claim.objective_horizon_id, claim.objective_id, claim.outcome_context_id,
            claim.outcome_baseline_id, claim.outcome_horizon_id, claim.dimension_id)


def _validate_claim(claim):
    for value in (*_key(claim), claim.source_id, claim.assessment_policy_id):
        _text(value)
    if type(claim.relation) is not ObjectiveOutcomeRelation:
        raise TypeError('exact_relation_required')
    _tick(claim.basis_tick)
    if type(claim.evidence_refs) is not tuple:
        raise TypeError('exact_evidence_ref_tuple_required')
    for ref in claim.evidence_refs:
        _text(ref)
    if len(set(claim.evidence_refs)) != len(claim.evidence_refs):
        raise ValueError('duplicate_evidence_ref')


@dataclass(frozen=True)
class ObjectiveOutcomeRelationClaim:
    decision_context_id: str
    option_id: str
    objective_context_id: str
    objective_horizon_id: str
    objective_id: str
    outcome_context_id: str
    outcome_baseline_id: str
    outcome_horizon_id: str
    dimension_id: str
    relation: ObjectiveOutcomeRelation
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


def _identity(kind, value):
    content = json.dumps(asdict(value), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('utf-8')
    return RULESET + ':' + kind + ':' + hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ObjectiveOutcomeRelationEvidence:
    option_id: str
    objective_context_id: str
    objective_horizon_id: str
    objective_id: str
    outcome_context_id: str
    outcome_baseline_id: str
    outcome_horizon_id: str
    dimension_id: str
    relation: ObjectiveOutcomeRelation
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str
    base_claim: ObjectiveOutcomeRelationClaim
    base_objective_assessment: object
    base_outcome_evidence: object

    @property
    def evidence_id(self) -> str:
        return _identity('evidence', self)


@dataclass(frozen=True)
class ObjectiveOutcomeRelationSnapshotV1:
    decision_context_id: str
    decision_context_object_id: str
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    objective_context_id: str
    objective_horizon_id: str
    objective_id: str | None
    ruleset: str
    relations: tuple[ObjectiveOutcomeRelationEvidence, ...]

    @property
    def snapshot_id(self) -> str:
        return _identity('snapshot', self)


def _context_rows(context):
    if type(context) is not DecisionContextV2:
        raise TypeError('exact_decision_context_required')
    for value in (context.decision_context_id, context.timeline_id,
                  context.selected_clock_id, context.context_binding_policy_id,
                  context.objective_context_id, context.objective_horizon_id,
                  context.strategic_objective_snapshot_id, context.option_safety_snapshot_id,
                  context.option_outcome_snapshot_id):
        _text(value)
    _tick(context.decision_assembly_tick)
    if type(context.ruleset) is not str or context.ruleset != 'decision.context.v2':
        raise ValueError('accepted_decision_context_ruleset_required')
    if type(context.options) is not tuple:
        raise TypeError('exact_option_context_tuple_required')
    options = set()
    outcomes = {}
    for option in context.options:
        if type(option) is not OptionDecisionContextV2:
            raise TypeError('exact_option_context_required')
        selector = (option.option_id, option.outcome_context_id,
                    option.outcome_baseline_id, option.outcome_horizon_id)
        for value in selector:
            _text(value)
        if option.option_id in options:
            raise ValueError('duplicate_context_option')
        options.add(option.option_id)
        if type(option.outcome_evidences) is not tuple:
            raise TypeError('exact_embedded_outcome_tuple_required')
        # Embedded evidence types/semantics were accepted by Decision Context.
        # Recheck selectors and uniqueness, without rebuilding upstream evidence.
        for row in option.outcome_evidences:
            key = (row.option_id, row.outcome_context_id, row.baseline_id,
                   row.horizon_id, row.dimension_id)
            for value in key:
                _text(value)
            if key[:4] != selector:
                raise ValueError('foreign_embedded_outcome')
            if key in outcomes:
                raise ValueError('duplicate_embedded_outcome')
            outcomes[key] = row
    objective = context.objective_assessment
    objective_id = None
    if objective is not None:
        _text(objective.objective_context_id)
        _text(objective.horizon_id)
        if (objective.objective_context_id, objective.horizon_id) != (
                context.objective_context_id, context.objective_horizon_id):
            raise ValueError('foreign_embedded_objective')
        objective_id = objective.objective_id
        if objective_id is not None:
            _text(objective_id)
    return options, outcomes, objective_id


def build_objective_outcome_relation_snapshot_v1(
        *, decision_context: DecisionContextV2,
        claims: tuple[ObjectiveOutcomeRelationClaim, ...],
) -> ObjectiveOutcomeRelationSnapshotV1:
    """Bind caller declarations; missing declarations remain absent rows.

    Accepted embedded objects retain their upstream validation responsibility.
    Relation claims are fully revalidated here, including frozen-object bypasses.
    """
    options, outcomes, objective_id = _context_rows(decision_context)
    if type(claims) is not tuple:
        raise TypeError('exact_relation_claim_tuple_required')
    seen = set()
    bound = []
    for claim in claims:
        if type(claim) is not ObjectiveOutcomeRelationClaim:
            raise TypeError('exact_relation_claim_required')
        _validate_claim(claim)
        if claim.decision_context_id != decision_context.decision_context_id:
            raise ValueError('foreign_decision_context')
        if claim.option_id not in options:
            raise ValueError('foreign_option')
        if objective_id is None:
            raise ValueError('concrete_objective_required')
        if (claim.objective_context_id, claim.objective_horizon_id, claim.objective_id) != (
                decision_context.objective_context_id,
                decision_context.objective_horizon_id, objective_id):
            raise ValueError('foreign_objective')
        outcome_key = (claim.option_id, claim.outcome_context_id,
                       claim.outcome_baseline_id, claim.outcome_horizon_id, claim.dimension_id)
        if outcome_key not in outcomes:
            raise ValueError('missing_exact_outcome')
        if claim.basis_tick != decision_context.decision_assembly_tick:
            raise ValueError('exact_decision_tick_required')
        key = _key(claim)
        if key in seen:
            raise ValueError('duplicate_relation_semantic_key')
        seen.add(key)
        bound.append((claim, outcomes[outcome_key]))
    lineage = decision_context.context_id
    _text(lineage)
    ordered = sorted(bound, key=lambda pair: (
        *_key(pair[0])[1:], pair[0].source_id, pair[0].assessment_policy_id))
    relations = tuple(ObjectiveOutcomeRelationEvidence(
        *_key(c)[1:], c.relation, c.basis_tick, c.source_id, c.evidence_refs,
        c.assessment_policy_id, c, decision_context.objective_assessment, row)
        for c, row in ordered)
    return ObjectiveOutcomeRelationSnapshotV1(
        decision_context.decision_context_id, lineage, decision_context.timeline_id,
        decision_context.selected_clock_id, decision_context.decision_assembly_tick,
        decision_context.objective_context_id, decision_context.objective_horizon_id,
        objective_id, RULESET, relations)
