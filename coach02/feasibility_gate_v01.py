"""Explicit modeled execution requirements, independent of embedded semantics."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .decision_context_v02 import DecisionContextV2, OptionDecisionContextV2


RULESET = 'option.feasibility_gate.v1'


class FeasibilityRequirementState(str, Enum):
    SATISFIED = 'SATISFIED'
    UNSATISFIED = 'UNSATISFIED'
    UNKNOWN = 'UNKNOWN'


class FeasibilityGateStatus(str, Enum):
    FEASIBLE = 'FEASIBLE'
    INFEASIBLE = 'INFEASIBLE'
    INDETERMINATE = 'INDETERMINATE'


class FeasibilityGateReason(str, Enum):
    ALL_REQUIRED_REQUIREMENTS_SATISFIED = 'ALL_REQUIRED_REQUIREMENTS_SATISFIED'
    REQUIRED_REQUIREMENT_UNSATISFIED = 'REQUIRED_REQUIREMENT_UNSATISFIED'
    REQUIRED_REQUIREMENT_UNKNOWN = 'REQUIRED_REQUIREMENT_UNKNOWN'
    REQUIRED_REQUIREMENT_ABSENT = 'REQUIRED_REQUIREMENT_ABSENT'
    FEASIBILITY_POLICY_ABSENT = 'FEASIBILITY_POLICY_ABSENT'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _identities(values):
    if type(values) is not tuple:
        raise TypeError('exact_identity_tuple_required')
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError('duplicate_identity')


def _claim_key(claim):
    return (claim.decision_context_id, claim.option_id,
            claim.feasibility_context_id, claim.requirement_id)


def _validate_claim(claim):
    for value in (*_claim_key(claim), claim.source_id, claim.assessment_policy_id):
        _text(value)
    if type(claim.state) is not FeasibilityRequirementState:
        raise TypeError('exact_requirement_state_required')
    _tick(claim.basis_tick)
    _identities(claim.evidence_refs)


@dataclass(frozen=True)
class FeasibilityRequirementClaim:
    decision_context_id: str
    option_id: str
    feasibility_context_id: str
    requirement_id: str
    state: FeasibilityRequirementState
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


def _validate_policy(policy):
    for value in (policy.decision_context_id, policy.option_id,
                  policy.feasibility_context_id, policy.feasibility_policy_id):
        _text(value)
    _identities(policy.required_requirement_ids)
    if not policy.required_requirement_ids:
        raise ValueError('nonempty_required_universe_required')


@dataclass(frozen=True)
class OptionFeasibilityPolicyClaim:
    decision_context_id: str
    option_id: str
    feasibility_context_id: str
    required_requirement_ids: tuple[str, ...]
    feasibility_policy_id: str

    def __post_init__(self):
        _validate_policy(self)


@dataclass(frozen=True)
class OptionFeasibilityAssessmentV1:
    option_id: str
    feasibility_context_id: str | None
    status: FeasibilityGateStatus
    reason: FeasibilityGateReason
    policy: OptionFeasibilityPolicyClaim | None
    requirement_claims: tuple[FeasibilityRequirementClaim, ...]
    missing_requirement_ids: tuple[str, ...]
    base_option_context: OptionDecisionContextV2


@dataclass(frozen=True)
class FeasibilitySnapshotV1:
    decision_context_id: str
    decision_context_object_id: str
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    ruleset: str
    assessments: tuple[OptionFeasibilityAssessmentV1, ...]

    @property
    def snapshot_id(self) -> str:
        content = asdict(self)
        # Only normalize the hash copy; the original policy tuple is retained.
        for row in content['assessments']:
            if row['policy'] is not None:
                row['policy']['required_requirement_ids'] = sorted(
                    row['policy']['required_requirement_ids'])
        encoded = json.dumps(content, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(encoded).hexdigest()


def _context_options(context):
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
    options = {}
    for option in context.options:
        if type(option) is not OptionDecisionContextV2:
            raise TypeError('exact_option_context_required')
        _text(option.option_id)
        if option.option_id in options:
            raise ValueError('duplicate_context_option')
        options[option.option_id] = option
    return options


def _conclusion(policy, claims, missing):
    if policy is None:
        return FeasibilityGateStatus.INDETERMINATE, FeasibilityGateReason.FEASIBILITY_POLICY_ABSENT
    if any(c.state is FeasibilityRequirementState.UNSATISFIED for c in claims):
        return FeasibilityGateStatus.INFEASIBLE, FeasibilityGateReason.REQUIRED_REQUIREMENT_UNSATISFIED
    if any(c.state is FeasibilityRequirementState.UNKNOWN for c in claims):
        return FeasibilityGateStatus.INDETERMINATE, FeasibilityGateReason.REQUIRED_REQUIREMENT_UNKNOWN
    if missing:
        return FeasibilityGateStatus.INDETERMINATE, FeasibilityGateReason.REQUIRED_REQUIREMENT_ABSENT
    return FeasibilityGateStatus.FEASIBLE, FeasibilityGateReason.ALL_REQUIRED_REQUIREMENTS_SATISFIED


def build_feasibility_snapshot_v1(
        *, decision_context: DecisionContextV2,
        policies: tuple[OptionFeasibilityPolicyClaim, ...],
        requirement_claims: tuple[FeasibilityRequirementClaim, ...],
) -> FeasibilitySnapshotV1:
    """Evaluate only explicitly required claims for every supplied candidate."""
    options = _context_options(decision_context)
    if type(policies) is not tuple or type(requirement_claims) is not tuple:
        raise TypeError('exact_policy_and_claim_tuples_required')
    selected = {}
    for policy in policies:
        if type(policy) is not OptionFeasibilityPolicyClaim:
            raise TypeError('exact_feasibility_policy_required')
        _validate_policy(policy)
        if policy.decision_context_id != decision_context.decision_context_id:
            raise ValueError('foreign_policy_decision_context')
        if policy.option_id not in options:
            raise ValueError('foreign_policy_option')
        if policy.option_id in selected:
            raise ValueError('duplicate_option_policy')
        selected[policy.option_id] = policy
    indexed = {}
    for claim in requirement_claims:
        if type(claim) is not FeasibilityRequirementClaim:
            raise TypeError('exact_feasibility_requirement_claim_required')
        _validate_claim(claim)
        if claim.decision_context_id != decision_context.decision_context_id:
            raise ValueError('foreign_claim_decision_context')
        if claim.option_id not in options:
            raise ValueError('foreign_claim_option')
        policy = selected.get(claim.option_id)
        if policy is None:
            raise ValueError('claim_without_policy')
        if claim.feasibility_context_id != policy.feasibility_context_id:
            raise ValueError('foreign_feasibility_context')
        if claim.requirement_id not in policy.required_requirement_ids:
            raise ValueError('unrequired_claim')
        if claim.basis_tick != decision_context.decision_assembly_tick:
            raise ValueError('exact_decision_tick_required')
        key = _claim_key(claim)
        if key in indexed:
            raise ValueError('duplicate_requirement_claim')
        indexed[key] = claim
    # Resolve lineage before creating output; upstream semantics remain opaque.
    lineage = decision_context.context_id
    _text(lineage)
    assessments = []
    for option_id in sorted(options):
        policy = selected.get(option_id)
        claims = tuple(sorted((c for c in indexed.values() if c.option_id == option_id),
                              key=lambda c: (c.requirement_id, c.source_id, c.assessment_policy_id)))
        present = {c.requirement_id for c in claims}
        missing = () if policy is None else tuple(sorted(set(policy.required_requirement_ids) - present))
        status, reason = _conclusion(policy, claims, missing)
        assessments.append(OptionFeasibilityAssessmentV1(
            option_id, None if policy is None else policy.feasibility_context_id,
            status, reason, policy, claims, missing, options[option_id]))
    return FeasibilitySnapshotV1(
        decision_context.decision_context_id, lineage, decision_context.timeline_id,
        decision_context.selected_clock_id, decision_context.decision_assembly_tick,
        RULESET, tuple(assessments))
