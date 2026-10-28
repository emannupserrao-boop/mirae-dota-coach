"""Explicit threat-to-option affectability under an opaque context and horizon.

Caller policy supplies the classification. State, proximity and missing evidence
never determine affectability here. CAN_AFFECT is not danger; CANNOT_AFFECT is not
safety. No physical reachability, risk or freshness algorithm is implemented.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .threat_state_assembly import (
    ThreatStateSnapshot, ThreatStateAssessment, AssembledThreatState, ThreatStateReason,
)


RULESET = 'threat.reachability_assessment.v1'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


class ThreatReachability(str, Enum):
    CAN_AFFECT = 'CAN_AFFECT'
    CANNOT_AFFECT = 'CANNOT_AFFECT'
    UNKNOWN = 'UNKNOWN'


def _key(claim):
    return (claim.threat_id, claim.option_id, claim.reachability_context_id, claim.horizon_id)


def _claim(claim):
    for value in (*_key(claim), claim.assessment_policy_id):
        _text(value)
    if type(claim.reachability) is not ThreatReachability:
        raise TypeError('explicit_reachability_required')


@dataclass(frozen=True)
class ThreatReachabilityClaim:
    threat_id: str
    option_id: str
    reachability_context_id: str
    horizon_id: str
    reachability: ThreatReachability
    assessment_policy_id: str

    def __post_init__(self):
        _claim(self)


@dataclass(frozen=True)
class ThreatReachabilityAssessment:
    threat_id: str
    option_id: str
    reachability_context_id: str
    horizon_id: str
    reachability: ThreatReachability
    assessment_policy_id: str
    threat_state_assessment: ThreatStateAssessment


@dataclass(frozen=True)
class ThreatReachabilitySnapshot:
    timeline_id: str
    selected_clock_id: str
    threat_state_snapshot_id: str
    evaluated_at_tick: int
    assessments: tuple[ThreatReachabilityAssessment, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _state_index(snapshot):
    if type(snapshot) is not ThreatStateSnapshot:
        raise TypeError('exact_threat_state_snapshot_required')
    for value in (snapshot.timeline_id, snapshot.selected_clock_id,
                  snapshot.positive_snapshot_id, snapshot.missing_snapshot_id):
        _text(value)
    _tick(snapshot.assembly_tick)
    if type(snapshot.assessments) is not tuple:
        raise TypeError('state_assessment_tuple_required')
    index = {}
    for assessment in snapshot.assessments:
        if type(assessment) is not ThreatStateAssessment:
            raise TypeError('exact_threat_state_assessment_required')
        _text(assessment.threat_id)
        _tick(assessment.assembly_tick)
        if type(assessment.state) is not AssembledThreatState or type(assessment.reason) is not ThreatStateReason:
            raise TypeError('explicit_state_and_reason_required')
        if assessment.assembly_tick != snapshot.assembly_tick:
            raise ValueError('state_assessment_tick_mismatch')
        if assessment.threat_id in index:
            raise ValueError('duplicate_state_subject')
        index[assessment.threat_id] = assessment
    return index


def build_threat_reachability(
        threat_state_snapshot: ThreatStateSnapshot,
        claims: tuple[ThreatReachabilityClaim, ...],
) -> ThreatReachabilitySnapshot:
    """Bind each explicit assessment to its exact accepted state object.

    Empty/subset claims create no unrequested rows. IDs and retained provenance
    identify supplied evidence; they do not authenticate the external policy.
    """
    states = _state_index(threat_state_snapshot)
    if type(claims) is not tuple or any(type(c) is not ThreatReachabilityClaim for c in claims):
        raise TypeError('reachability_claim_tuple_required')
    seen = set()
    for claim in claims:
        _claim(claim)
        key = _key(claim)
        if key in seen:
            raise ValueError('duplicate_reachability_claim')
        seen.add(key)
        if claim.threat_id not in states:
            raise ValueError('unknown_threat_subject')
    assessments = tuple(ThreatReachabilityAssessment(
        *_key(claim), claim.reachability, claim.assessment_policy_id, states[claim.threat_id])
        for claim in sorted(claims, key=lambda c: (*_key(c), c.assessment_policy_id)))
    return ThreatReachabilitySnapshot(
        threat_state_snapshot.timeline_id, threat_state_snapshot.selected_clock_id,
        threat_state_snapshot.snapshot_id, threat_state_snapshot.assembly_tick, assessments)
