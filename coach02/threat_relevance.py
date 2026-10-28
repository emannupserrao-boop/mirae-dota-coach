"""Bind caller-supplied, context-specific relevance to accepted threat evidence.

RELEVANT does not mean DANGEROUS. NOT_RELEVANT does not mean SAFE.
Evidence state and freshness are preserved, never selected or recalculated here.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .threat_observation import (
    ThreatObservation, ThreatObservationSnapshot, ThreatProximity, TemporalStatus,
)
from .missing_threat_resolver import (
    MissingThreatResolution, MissingThreatResolutionSnapshot,
    MissingResolutionStatus, MissingResolutionReason,
    ThreatAbsenceObservation, ThreatVisibilityAbsence,
    VisibilityCompletenessAssessment, VisibilityCompleteness,
)


RULESET = 'threat.relevance_assessment.v1'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _temporal(status, observed, last, age, maximum):
    if status is not TemporalStatus.FRESH and status is not TemporalStatus.STALE:
        raise TypeError('supported_temporal_status_required')
    for value in (observed, last, age, maximum):
        _tick(value)
    if age < 0 or maximum < 0:
        raise ValueError('nonnegative_age_and_threshold_required')


class ThreatRelevance(str, Enum):
    RELEVANT = 'RELEVANT'
    NOT_RELEVANT = 'NOT_RELEVANT'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class ThreatRelevanceClaim:
    threat_id: str
    relevance: ThreatRelevance
    relevance_context_id: str
    assessment_policy_id: str

    def __post_init__(self):
        for value in (self.threat_id, self.relevance_context_id, self.assessment_policy_id):
            _text(value)
        if type(self.relevance) is not ThreatRelevance:
            raise TypeError('explicit_threat_relevance_required')


@dataclass(frozen=True)
class ThreatRelevanceAssessment:
    threat_id: str
    relevance: ThreatRelevance
    relevance_context_id: str
    assessment_policy_id: str
    positive_observation: ThreatObservation | None
    missing_resolution: MissingThreatResolution | None


@dataclass(frozen=True)
class ThreatRelevanceSnapshot:
    timeline_id: str
    selected_clock_id: str
    positive_snapshot_id: str
    missing_snapshot_id: str
    evaluated_at_tick: int
    assessments: tuple[ThreatRelevanceAssessment, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _observation(observation, positive):
    expected = ThreatObservation if positive else ThreatAbsenceObservation
    if type(observation) is not expected:
        raise TypeError('accepted_observation_required')
    for value in (observation.threat_id, observation.ref, observation.source_id,
                  observation.temporal_policy_id):
        _text(value)
    _temporal(observation.temporal_status, observation.observed_tick,
              observation.last_observed_tick, observation.age_ticks, observation.max_age_ticks)
    if positive:
        if type(observation.proximity) is not ThreatProximity:
            raise TypeError('explicit_proximity_required')
    elif observation.visibility is not ThreatVisibilityAbsence.NOT_VISIBLE:
        raise TypeError('explicit_absence_required')


def _positive_index(snapshot):
    for value in (snapshot.timeline_id, snapshot.selected_clock_id, snapshot.event_id,
                  snapshot.projection_id, snapshot.tracker_state_id, snapshot.temporal_snapshot_id):
        _text(value)
    _tick(snapshot.selected_tick)
    _tick(snapshot.evaluated_at_tick)
    if type(snapshot.observations) is not tuple:
        raise TypeError('positive_observation_tuple_required')
    index = {}
    for observation in snapshot.observations:
        _observation(observation, True)
        if observation.threat_id in index:
            raise ValueError('duplicate_positive_subject')
        index[observation.threat_id] = observation
    return index


def _nested_completeness(assessment, threat_id):
    if type(assessment) is not VisibilityCompletenessAssessment:
        raise TypeError('accepted_completeness_assessment_required')
    for value in (assessment.threat_id, assessment.absence_ref, assessment.source_id,
                  assessment.scope_id, assessment.assessment_policy_id, assessment.absence_temporal_policy_id):
        _text(value)
    if assessment.threat_id != threat_id:
        raise ValueError('nested_completeness_subject_mismatch')
    if type(assessment.completeness) is not VisibilityCompleteness:
        raise TypeError('explicit_completeness_required')
    _temporal(assessment.absence_temporal_status, assessment.observed_tick,
              assessment.absence_last_observed_tick, assessment.absence_age_ticks,
              assessment.absence_max_age_ticks)


def _missing_index(snapshot, positives):
    for value in (snapshot.timeline_id, snapshot.selected_clock_id, snapshot.positive_snapshot_id,
                  snapshot.absence_snapshot_id, snapshot.completeness_snapshot_id):
        _text(value)
    _tick(snapshot.resolved_at_tick)
    if type(snapshot.resolutions) is not tuple:
        raise TypeError('missing_resolution_tuple_required')
    index = {}
    for resolution in snapshot.resolutions:
        if type(resolution) is not MissingThreatResolution:
            raise TypeError('accepted_missing_resolution_required')
        for value in (resolution.threat_id, resolution.positive_snapshot_id,
                      resolution.absence_snapshot_id, resolution.completeness_snapshot_id):
            _text(value)
        if type(resolution.status) is not MissingResolutionStatus or type(resolution.reason) is not MissingResolutionReason:
            raise TypeError('explicit_missing_status_and_reason_required')
        if (resolution.positive_snapshot_id, resolution.absence_snapshot_id, resolution.completeness_snapshot_id) != (
                snapshot.positive_snapshot_id, snapshot.absence_snapshot_id, snapshot.completeness_snapshot_id):
            raise ValueError('resolution_snapshot_lineage_mismatch')
        if resolution.positive is not None:
            _observation(resolution.positive, True)
        if resolution.positive != positives.get(resolution.threat_id):
            raise ValueError('resolution_positive_binding_mismatch')
        _observation(resolution.absence, False)
        if resolution.absence.threat_id != resolution.threat_id:
            raise ValueError('nested_absence_subject_mismatch')
        if resolution.assessment is not None:
            _nested_completeness(resolution.assessment, resolution.threat_id)
        for value in (resolution.last_seen_tick, resolution.missing_since_tick):
            if value is not None:
                _tick(value)
        if resolution.threat_id in index:
            raise ValueError('duplicate_resolution_subject')
        index[resolution.threat_id] = resolution
    return index


def build_threat_relevance(
        positive_snapshot: ThreatObservationSnapshot,
        missing_snapshot: MissingThreatResolutionSnapshot,
        claims: tuple[ThreatRelevanceClaim, ...],
) -> ThreatRelevanceSnapshot:
    """Preserve two evidence axes; only explicit claims generate assessment rows.

    Validation covers structure, subject and lineage binding. Accepted upstream
    builders own occurrence semantics, freshness and missing status/reason logic.
    The maximum same-clock evaluation tick is metadata, not an evidence refresh.
    """
    if type(positive_snapshot) is not ThreatObservationSnapshot:
        raise TypeError('positive_snapshot_required')
    if type(missing_snapshot) is not MissingThreatResolutionSnapshot:
        raise TypeError('missing_snapshot_required')
    positives = _positive_index(positive_snapshot)
    missing = _missing_index(missing_snapshot, positives)
    if positive_snapshot.timeline_id != missing_snapshot.timeline_id:
        raise ValueError('timeline_mismatch')
    if positive_snapshot.selected_clock_id != missing_snapshot.selected_clock_id:
        raise ValueError('clock_mismatch')
    positive_id = positive_snapshot.snapshot_id
    if missing_snapshot.positive_snapshot_id != positive_id:
        raise ValueError('positive_snapshot_binding_mismatch')
    if type(claims) is not tuple or any(type(c) is not ThreatRelevanceClaim for c in claims):
        raise TypeError('relevance_claim_tuple_required')
    if len({c.threat_id for c in claims}) != len(claims):
        raise ValueError('duplicate_relevance_subject')
    assessments = []
    for claim in sorted(claims, key=lambda c: c.threat_id):
        # Revalidate explicit values even if an object bypassed frozen construction.
        for value in (claim.threat_id, claim.relevance_context_id, claim.assessment_policy_id):
            _text(value)
        if type(claim.relevance) is not ThreatRelevance:
            raise TypeError('explicit_threat_relevance_required')
        if claim.threat_id not in positives and claim.threat_id not in missing:
            raise ValueError('foreign_relevance_subject')
        assessments.append(ThreatRelevanceAssessment(
            claim.threat_id, claim.relevance, claim.relevance_context_id, claim.assessment_policy_id,
            positives.get(claim.threat_id), missing.get(claim.threat_id)))
    return ThreatRelevanceSnapshot(
        positive_snapshot.timeline_id, positive_snapshot.selected_clock_id,
        positive_id, missing_snapshot.snapshot_id,
        max(positive_snapshot.evaluated_at_tick, missing_snapshot.resolved_at_tick), tuple(assessments))
