"""Explicit scope sufficiency for an already validated NOT_VISIBLE occurrence.

No observation, completeness calculation, temporal classification or resolution.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .threat_absence_observation import (
    ThreatAbsenceObservation, ThreatAbsenceObservationSnapshot,
    ThreatVisibilityAbsence, TemporalStatus,
)


RULESET = 'threat.visibility_completeness.v1'


def _text(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_' + field + '_required')


def _integer(value, field):
    if type(value) is not int:
        raise TypeError('integer_' + field + '_required')


class VisibilityCompleteness(str, Enum):
    SUFFICIENT = 'SUFFICIENT'
    INSUFFICIENT = 'INSUFFICIENT'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class VisibilityCompletenessClaim:
    threat_id: str
    absence_ref: str
    scope_id: str
    completeness: VisibilityCompleteness
    assessment_policy_id: str

    def __post_init__(self):
        for value, field in ((self.threat_id, 'threat_id'), (self.absence_ref, 'absence_ref'),
                             (self.scope_id, 'scope_id'), (self.assessment_policy_id, 'assessment_policy_id')):
            _text(value, field)
        if type(self.completeness) is not VisibilityCompleteness:
            raise TypeError('explicit_visibility_completeness_required')


@dataclass(frozen=True)
class VisibilityCompletenessAssessment:
    threat_id: str
    absence_ref: str
    source_id: str
    observed_tick: int
    absence_temporal_status: TemporalStatus
    absence_last_observed_tick: int
    absence_age_ticks: int
    absence_temporal_policy_id: str
    absence_max_age_ticks: int
    scope_id: str
    completeness: VisibilityCompleteness
    assessment_policy_id: str


@dataclass(frozen=True)
class VisibilityCompletenessSnapshot:
    timeline_id: str
    absence_snapshot_id: str
    event_id: str
    projection_id: str
    tracker_state_id: str
    temporal_snapshot_id: str
    selected_clock_id: str
    selected_tick: int
    evaluated_at_tick: int
    assessments: tuple[VisibilityCompletenessAssessment, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _absence_index(snapshot):
    """Validate the consumed contract's structure, not its upstream provenance.

    The caller supplies an accepted absence snapshot. Event/projection validation,
    occurrence binding and TTL classification belong to the upstream builder.
    """
    if type(snapshot) is not ThreatAbsenceObservationSnapshot:
        raise TypeError('threat_absence_snapshot_required')
    for value, field in ((snapshot.timeline_id, 'timeline_id'), (snapshot.event_id, 'event_id'),
                         (snapshot.projection_id, 'projection_id'), (snapshot.tracker_state_id, 'tracker_state_id'),
                         (snapshot.temporal_snapshot_id, 'temporal_snapshot_id'),
                         (snapshot.selected_clock_id, 'selected_clock_id')):
        _text(value, field)
    _integer(snapshot.selected_tick, 'selected_tick')
    _integer(snapshot.evaluated_at_tick, 'evaluated_at_tick')
    if type(snapshot.observations) is not tuple:
        raise TypeError('absence_observation_tuple_required')
    index = {}
    for observation in snapshot.observations:
        if type(observation) is not ThreatAbsenceObservation:
            raise TypeError('threat_absence_observation_required')
        for value, field in ((observation.threat_id, 'threat_id'), (observation.ref, 'ref'),
                             (observation.source_id, 'source_id'),
                             (observation.temporal_policy_id, 'temporal_policy_id')):
            _text(value, field)
        if observation.visibility is not ThreatVisibilityAbsence.NOT_VISIBLE:
            raise ValueError('explicit_negative_visibility_required')
        if (observation.temporal_status is not TemporalStatus.FRESH and
                observation.temporal_status is not TemporalStatus.STALE):
            raise ValueError('supported_absence_temporal_status_required')
        for value, field in ((observation.observed_tick, 'observed_tick'),
                             (observation.last_observed_tick, 'last_observed_tick'),
                             (observation.age_ticks, 'age_ticks'), (observation.max_age_ticks, 'max_age_ticks')):
            _integer(value, field)
        if observation.age_ticks < 0 or observation.max_age_ticks < 0:
            raise ValueError('nonnegative_temporal_metadata_required')
        key = (observation.threat_id, observation.ref)
        if key in index:
            raise ValueError('ambiguous_absence_observation')
        index[key] = observation
    return index


def build_visibility_completeness(
        absence_snapshot: ThreatAbsenceObservationSnapshot,
        claims: tuple[VisibilityCompletenessClaim, ...],
) -> VisibilityCompletenessSnapshot:
    """Bind explicit assessments by exact subject/ref without policy inference."""
    index = _absence_index(absence_snapshot)
    if type(claims) is not tuple or any(type(c) is not VisibilityCompletenessClaim for c in claims):
        raise TypeError('visibility_completeness_claim_tuple_required')
    if len({c.threat_id for c in claims}) != len(claims):
        raise ValueError('duplicate_threat_id')
    assessments = []
    for claim in sorted(claims, key=lambda c: (c.threat_id, c.absence_ref)):
        key = (claim.threat_id, claim.absence_ref)
        if key not in index:
            raise ValueError('exact_absence_observation_required')
        observation = index[key]
        assessments.append(VisibilityCompletenessAssessment(
            observation.threat_id, observation.ref, observation.source_id,
            observation.observed_tick, observation.temporal_status,
            observation.last_observed_tick, observation.age_ticks,
            observation.temporal_policy_id, observation.max_age_ticks,
            claim.scope_id, claim.completeness, claim.assessment_policy_id))
    return VisibilityCompletenessSnapshot(
        absence_snapshot.timeline_id, absence_snapshot.snapshot_id,
        absence_snapshot.event_id, absence_snapshot.projection_id,
        absence_snapshot.tracker_state_id, absence_snapshot.temporal_snapshot_id,
        absence_snapshot.selected_clock_id, absence_snapshot.selected_tick,
        absence_snapshot.evaluated_at_tick, tuple(assessments))
