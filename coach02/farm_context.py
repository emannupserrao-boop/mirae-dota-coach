"""Explicit offline composition. Supplied assessments, never scalar-derived safety."""
from dataclasses import dataclass

from .context_builder import DecisionContextSeed, Eligibility, build_context_seed
from .decision import (Claim, DecisionContext, Execution, ObservedFact,
                       OptionAssessment, RuntimeObservation, Source, build_context)


@dataclass(frozen=True)
class FarmStrategicEvidence:
    """Bind supplied observational support and heuristic claims to one exact seed.

    ObservedFact retains its accepted observational meaning. A Claim is a separate
    supplied interpretation, not an observation. Neither is derived here. Fixtures
    may supply both synthetically; this does not certify a real Safety/Map source.
    """
    seed_id: str
    observations: tuple[ObservedFact, ...]
    assessments: tuple[OptionAssessment, ...]
    increased_risk: Claim
    assessment_source: Source = Source.EXPERT_HEURISTIC

    def __post_init__(self):
        if type(self.seed_id) is not str or not self.seed_id:
            raise ValueError('evidence_seed_identity_required')
        # build_context currently supports only expert-authored assessments.
        # Reject other declarations instead of relabeling them on resolution.
        if self.assessment_source is not Source.EXPERT_HEURISTIC:
            raise ValueError('unsupported_assessment_source')
        if type(self.observations) is not tuple or any(not isinstance(f, ObservedFact) for f in self.observations):
            raise TypeError('observed_fact_tuple_required')
        if type(self.assessments) is not tuple or any(not isinstance(o, OptionAssessment) for o in self.assessments):
            raise TypeError('option_assessment_tuple_required')
        for fact in self.observations:
            _support_ref(fact.ref)
        if len({f.ref for f in self.observations}) != len(self.observations):
            raise ValueError('duplicate_evidence_ref')
        claims = [self.increased_risk]
        for option in self.assessments:
            if type(option.plan_id) is not str or not option.plan_id:
                raise ValueError('invalid_plan_identity')
            claims.extend((option.available, option.safe))
        for claim in claims:
            if not isinstance(claim, Claim):
                raise TypeError('claim_required')
            if type(claim.rule_ref) is not str or not claim.rule_ref:
                raise ValueError('assessment_rule_reference_required')
            for ref in claim.evidence_refs:
                _support_ref(ref)


def _support_ref(ref):
    if type(ref) is not str or not ref:
        raise ValueError('observation_reference_required')
    if ref.startswith('State.'):
        raise ValueError('runtime_scalar_is_not_strategic_support')


def compose_farm_context(seed: DecisionContextSeed,
                         strategic_evidence: FarmStrategicEvidence,
                         execution: Execution) -> DecisionContext:
    """Refuse unsupported eligibility, then delegate all resolution to build_context.

    No planner/output invocation. Execution is supplied, never tracked or inferred.
    The caller retains seed/evidence for audit; DecisionContext stays unchanged.
    """
    if not isinstance(seed, DecisionContextSeed):
        raise TypeError('decision_context_seed_required')
    if seed.eligibility is not Eligibility.ELIGIBLE:
        raise ValueError('seed_not_eligible')
    if not isinstance(strategic_evidence, FarmStrategicEvidence):
        raise TypeError('farm_strategic_evidence_required')
    if not isinstance(execution, Execution):
        raise TypeError('execution_required')
    if execution.plan_id is not None and type(execution.plan_id) is not str:
        raise ValueError('execution_plan_reference_must_be_string')
    # Frozen dataclasses can still be manually constructed/replaced. Reuse the
    # accepted builder to reject forged eligibility/identity without new semantics.
    observation = RuntimeObservation(seed.observation_id, (), seed.dimensions)
    if build_context_seed(observation, seed.knowledge, seed.player) != seed:
        raise ValueError('inconsistent_seed')
    if strategic_evidence.seed_id != seed.seed_id:
        raise ValueError('strategic_evidence_seed_mismatch')
    # Scalars cannot satisfy boolean strategic dependencies; no coercion or merge.
    support = RuntimeObservation(seed.observation_id, strategic_evidence.observations)
    return build_context(support, seed.knowledge, seed.player,
                         strategic_evidence.assessments, strategic_evidence.increased_risk,
                         execution)
