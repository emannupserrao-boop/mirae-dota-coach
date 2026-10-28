"""Explicit shared strategic intent, with opaque identities and provenance.

The caller supplies every context, horizon and tick. No objective is inferred.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json


RULESET = 'strategic.objective_context.v1'


class StrategicObjectiveKnownness(str, Enum):
    KNOWN = 'KNOWN'
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
    return (claim.objective_context_id, claim.horizon_id)


def _validate_claim(claim):
    for value in (*_key(claim), claim.source_id, claim.assessment_policy_id):
        _text(value)
    if type(claim.knownness) is not StrategicObjectiveKnownness:
        raise TypeError('concrete_objective_knownness_required')
    if claim.knownness is StrategicObjectiveKnownness.KNOWN:
        _text(claim.objective_id)
    elif claim.objective_id is not None:
        raise ValueError('unknown_objective_requires_none')
    _tick(claim.basis_tick)
    if type(claim.evidence_refs) is not tuple:
        raise TypeError('exact_evidence_ref_tuple_required')
    for ref in claim.evidence_refs:
        _text(ref)
    if len(set(claim.evidence_refs)) != len(claim.evidence_refs):
        raise ValueError('duplicate_evidence_ref')


@dataclass(frozen=True)
class StrategicObjectiveClaim:
    objective_context_id: str
    knownness: StrategicObjectiveKnownness
    objective_id: str | None
    horizon_id: str
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


@dataclass(frozen=True)
class StrategicObjectiveAssessment:
    objective_context_id: str
    knownness: StrategicObjectiveKnownness
    objective_id: str | None
    horizon_id: str
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str
    base_claim: StrategicObjectiveClaim


@dataclass(frozen=True)
class StrategicObjectiveSnapshot:
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    ruleset: str
    assessments: tuple[StrategicObjectiveAssessment, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def build_strategic_objective_context(
        *, timeline_id: str, selected_clock_id: str, evaluated_at_tick: int,
        claims: tuple[StrategicObjectiveClaim, ...],
) -> StrategicObjectiveSnapshot:
    """Preserve each supplied context/horizon assessment without reinterpretation.

    Empty input stays empty. References are labels, never loaded or authenticated.
    Older basis ticks remain metadata without a temporal classification.
    """
    _text(timeline_id)
    _text(selected_clock_id)
    _tick(evaluated_at_tick)
    if type(claims) is not tuple:
        raise TypeError('exact_claim_tuple_required')
    seen = set()
    for claim in claims:
        if type(claim) is not StrategicObjectiveClaim:
            raise TypeError('exact_strategic_objective_claim_required')
        _validate_claim(claim)
        if claim.basis_tick > evaluated_at_tick:
            raise ValueError('basis_after_evaluation')
        key = _key(claim)
        if key in seen:
            raise ValueError('duplicate_context_horizon')
        seen.add(key)
    ordered = sorted(claims, key=lambda c: (*_key(c), c.source_id, c.assessment_policy_id))
    assessments = tuple(StrategicObjectiveAssessment(
        c.objective_context_id, c.knownness, c.objective_id, c.horizon_id,
        c.basis_tick, c.source_id, c.evidence_refs, c.assessment_policy_id, c)
        for c in ordered)
    return StrategicObjectiveSnapshot(timeline_id, selected_clock_id,
                                      evaluated_at_tick, RULESET, assessments)
