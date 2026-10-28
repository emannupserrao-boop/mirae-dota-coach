"""Explicit prospective directional claims; independent dimensions and provenance.

All semantic identities and assessment ticks are supplied by the caller.
This module preserves declarations without interpreting dimension names.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json


RULESET = 'option.outcome_evidence.v1'


class OutcomeChange(str, Enum):
    INCREASE = 'INCREASE'
    DECREASE = 'DECREASE'
    UNCHANGED = 'UNCHANGED'
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
    return (claim.option_id, claim.outcome_context_id, claim.dimension_id,
            claim.baseline_id, claim.horizon_id)


def _validate_claim(claim):
    for value in (*_key(claim), claim.source_id, claim.assessment_policy_id):
        _text(value)
    if type(claim.change) is not OutcomeChange:
        raise TypeError('concrete_outcome_change_required')
    _tick(claim.basis_tick)
    if type(claim.evidence_refs) is not tuple:
        raise TypeError('exact_evidence_ref_tuple_required')
    for ref in claim.evidence_refs:
        _text(ref)
    if len(set(claim.evidence_refs)) != len(claim.evidence_refs):
        raise ValueError('duplicate_evidence_ref')


@dataclass(frozen=True)
class OptionOutcomeClaim:
    option_id: str
    outcome_context_id: str
    dimension_id: str
    baseline_id: str
    horizon_id: str
    change: OutcomeChange
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


@dataclass(frozen=True)
class OptionOutcomeEvidence:
    option_id: str
    outcome_context_id: str
    dimension_id: str
    baseline_id: str
    horizon_id: str
    change: OutcomeChange
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str
    base_claim: OptionOutcomeClaim


@dataclass(frozen=True)
class OptionOutcomeSnapshot:
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    ruleset: str
    evidences: tuple[OptionOutcomeEvidence, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def build_option_outcome_evidence(
        *, timeline_id: str, selected_clock_id: str, evaluated_at_tick: int,
        claims: tuple[OptionOutcomeClaim, ...],
) -> OptionOutcomeSnapshot:
    """Retain each explicit claim once, bound to supplied timeline and clock IDs.

    Older basis ticks remain exact metadata. Empty input produces no rows.
    References are labels, not content to load or verify.
    """
    _text(timeline_id)
    _text(selected_clock_id)
    _tick(evaluated_at_tick)
    if type(claims) is not tuple:
        raise TypeError('exact_claim_tuple_required')
    seen = set()
    for claim in claims:
        if type(claim) is not OptionOutcomeClaim:
            raise TypeError('exact_option_outcome_claim_required')
        _validate_claim(claim)
        if claim.basis_tick > evaluated_at_tick:
            raise ValueError('basis_after_evaluation')
        key = _key(claim)
        if key in seen:
            raise ValueError('duplicate_semantic_key')
        seen.add(key)
    ordered = sorted(claims, key=lambda c: (*_key(c), c.source_id, c.assessment_policy_id))
    evidences = tuple(OptionOutcomeEvidence(*_key(c), c.change, c.basis_tick,
        c.source_id, c.evidence_refs, c.assessment_policy_id, c) for c in ordered)
    return OptionOutcomeSnapshot(timeline_id, selected_clock_id, evaluated_at_tick,
                                 RULESET, evidences)
