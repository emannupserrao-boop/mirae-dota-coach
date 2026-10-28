"""Pure derived missing-state resolution over explicitly supplied semantic evidence."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .threat_observation import ThreatObservation, ThreatObservationSnapshot, ThreatProximity, TemporalStatus
from .threat_absence_observation import (
    ThreatAbsenceObservation, ThreatAbsenceObservationSnapshot, ThreatVisibilityAbsence,
)
from .visibility_completeness import (
    VisibilityCompleteness, VisibilityCompletenessAssessment, VisibilityCompletenessSnapshot,
)


RULESET = 'threat.missing_resolver.v1'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _status(value):
    if value is not TemporalStatus.FRESH and value is not TemporalStatus.STALE:
        raise ValueError('supported_temporal_status_required')


class MissingResolutionStatus(str, Enum):
    MISSING = 'MISSING'
    NOT_JUSTIFIED = 'NOT_JUSTIFIED'
    CONFLICTED = 'CONFLICTED'


class MissingResolutionReason(str, Enum):
    JUSTIFIED_MISSING = 'JUSTIFIED_MISSING'
    NO_PRIOR_POSITIVE_SIGHTING = 'NO_PRIOR_POSITIVE_SIGHTING'
    NO_COMPLETENESS_ASSESSMENT = 'NO_COMPLETENESS_ASSESSMENT'
    COMPLETENESS_INSUFFICIENT = 'COMPLETENESS_INSUFFICIENT'
    COMPLETENESS_UNKNOWN = 'COMPLETENESS_UNKNOWN'
    ABSENCE_STALE = 'ABSENCE_STALE'
    SAME_TICK_POSITIVE_NEGATIVE_CONFLICT = 'SAME_TICK_POSITIVE_NEGATIVE_CONFLICT'
    NEWER_POSITIVE_SIGHTING = 'NEWER_POSITIVE_SIGHTING'


@dataclass(frozen=True)
class MissingThreatResolution:
    threat_id: str
    status: MissingResolutionStatus
    reason: MissingResolutionReason
    positive: ThreatObservation | None
    absence: ThreatAbsenceObservation
    assessment: VisibilityCompletenessAssessment | None
    positive_snapshot_id: str
    absence_snapshot_id: str
    completeness_snapshot_id: str
    last_seen_tick: int | None
    missing_since_tick: int | None

    def __post_init__(self):
        if type(self.status) is not MissingResolutionStatus or type(self.reason) is not MissingResolutionReason:
            raise TypeError('explicit_resolution_status_and_reason_required')
        if self.status is MissingResolutionStatus.MISSING:
            valid = self.reason is MissingResolutionReason.JUSTIFIED_MISSING
        elif self.status is MissingResolutionStatus.CONFLICTED:
            valid = self.reason is MissingResolutionReason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT
        else:
            valid = self.reason not in (MissingResolutionReason.JUSTIFIED_MISSING,
                                        MissingResolutionReason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT)
        if not valid:
            raise ValueError('invalid_status_reason_combination')
        expected_last = None if self.positive is None else self.positive.observed_tick
        expected_since = self.absence.observed_tick if self.status is MissingResolutionStatus.MISSING else None
        if self.last_seen_tick != expected_last or self.missing_since_tick != expected_since:
            raise ValueError('invalid_resolution_time_metadata')
        if self.last_seen_tick is not None:
            _tick(self.last_seen_tick)
        if self.missing_since_tick is not None:
            _tick(self.missing_since_tick)


@dataclass(frozen=True)
class MissingThreatResolutionSnapshot:
    timeline_id: str
    selected_clock_id: str
    positive_snapshot_id: str
    absence_snapshot_id: str
    completeness_snapshot_id: str
    resolved_at_tick: int
    resolutions: tuple[MissingThreatResolution, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _header(snapshot):
    for value in (snapshot.timeline_id, snapshot.selected_clock_id, snapshot.event_id,
                  snapshot.projection_id, snapshot.tracker_state_id, snapshot.temporal_snapshot_id):
        _text(value)
    _tick(snapshot.selected_tick)
    _tick(snapshot.evaluated_at_tick)
    if snapshot.evaluated_at_tick < snapshot.selected_tick:
        raise ValueError('evaluation_precedes_occurrence')


def _observations(snapshot, positive):
    if type(snapshot.observations) is not tuple:
        raise TypeError('observation_tuple_required')
    expected_type = ThreatObservation if positive else ThreatAbsenceObservation
    index = {}
    for observation in snapshot.observations:
        if type(observation) is not expected_type:
            raise TypeError('semantic_observation_required')
        for value in (observation.threat_id, observation.ref, observation.source_id, observation.temporal_policy_id):
            _text(value)
        _status(observation.temporal_status)
        for value in (observation.observed_tick, observation.last_observed_tick,
                      observation.age_ticks, observation.max_age_ticks):
            _tick(value)
        if observation.age_ticks < 0 or observation.max_age_ticks < 0:
            raise ValueError('nonnegative_temporal_metadata_required')
        if (observation.observed_tick != snapshot.selected_tick or
                observation.last_observed_tick != observation.observed_tick or
                observation.age_ticks != snapshot.evaluated_at_tick - observation.observed_tick):
            raise ValueError('observation_occurrence_mismatch')
        if positive:
            if observation.proximity is not ThreatProximity.NEARBY and observation.proximity is not ThreatProximity.AWAY:
                raise ValueError('explicit_positive_sighting_required')
        elif observation.visibility is not ThreatVisibilityAbsence.NOT_VISIBLE:
            raise ValueError('explicit_negative_sighting_required')
        if observation.threat_id in index:
            raise ValueError('duplicate_observation_subject')
        index[observation.threat_id] = observation
    return index


def _assessments(snapshot, absences):
    if type(snapshot.assessments) is not tuple:
        raise TypeError('assessment_tuple_required')
    index = {}
    for assessment in snapshot.assessments:
        if type(assessment) is not VisibilityCompletenessAssessment:
            raise TypeError('completeness_assessment_required')
        for value in (assessment.threat_id, assessment.absence_ref, assessment.source_id,
                      assessment.scope_id, assessment.assessment_policy_id, assessment.absence_temporal_policy_id):
            _text(value)
        if type(assessment.completeness) is not VisibilityCompleteness:
            raise TypeError('explicit_completeness_required')
        _status(assessment.absence_temporal_status)
        for value in (assessment.observed_tick, assessment.absence_age_ticks,
                      assessment.absence_last_observed_tick, assessment.absence_max_age_ticks):
            _tick(value)
        if assessment.threat_id in index:
            raise ValueError('duplicate_assessment_subject')
        if assessment.threat_id not in absences:
            raise ValueError('extra_completeness_subject')
        absence = absences[assessment.threat_id]
        if (assessment.absence_ref, assessment.source_id, assessment.observed_tick,
                assessment.absence_temporal_status, assessment.absence_age_ticks,
                assessment.absence_last_observed_tick, assessment.absence_temporal_policy_id,
                assessment.absence_max_age_ticks) != (
                absence.ref, absence.source_id, absence.observed_tick, absence.temporal_status,
                absence.age_ticks, absence.last_observed_tick, absence.temporal_policy_id, absence.max_age_ticks):
            raise ValueError('assessment_absence_binding_mismatch')
        index[assessment.threat_id] = assessment
    return index


def _reason(positive, absence, assessment):
    # Precedence: completeness exists -> sufficient -> fresh absence -> positive -> order.
    if assessment is None:
        return MissingResolutionReason.NO_COMPLETENESS_ASSESSMENT
    if assessment.completeness is VisibilityCompleteness.INSUFFICIENT:
        return MissingResolutionReason.COMPLETENESS_INSUFFICIENT
    if assessment.completeness is VisibilityCompleteness.UNKNOWN:
        return MissingResolutionReason.COMPLETENESS_UNKNOWN
    if absence.temporal_status is TemporalStatus.STALE:
        return MissingResolutionReason.ABSENCE_STALE
    if positive is None:
        return MissingResolutionReason.NO_PRIOR_POSITIVE_SIGHTING
    if positive.observed_tick == absence.observed_tick:
        return MissingResolutionReason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT
    if positive.observed_tick > absence.observed_tick:
        return MissingResolutionReason.NEWER_POSITIVE_SIGHTING
    return MissingResolutionReason.JUSTIFIED_MISSING


def resolve_missing_threats(
        positive_snapshot: ThreatObservationSnapshot,
        absence_snapshot: ThreatAbsenceObservationSnapshot,
        completeness_snapshot: VisibilityCompletenessSnapshot,
) -> MissingThreatResolutionSnapshot:
    """Resolve each explicit absence; no hidden history, freshness update or risk."""
    if type(positive_snapshot) is not ThreatObservationSnapshot:
        raise TypeError('positive_snapshot_required')
    if type(absence_snapshot) is not ThreatAbsenceObservationSnapshot:
        raise TypeError('absence_snapshot_required')
    if type(completeness_snapshot) is not VisibilityCompletenessSnapshot:
        raise TypeError('completeness_snapshot_required')
    for snapshot in (positive_snapshot, absence_snapshot, completeness_snapshot):
        _header(snapshot)
    if not positive_snapshot.timeline_id == absence_snapshot.timeline_id == completeness_snapshot.timeline_id:
        raise ValueError('timeline_mismatch')
    if not positive_snapshot.selected_clock_id == absence_snapshot.selected_clock_id == completeness_snapshot.selected_clock_id:
        raise ValueError('clock_mismatch')
    positives = _observations(positive_snapshot, True)
    absences = _observations(absence_snapshot, False)
    if (completeness_snapshot.absence_snapshot_id != absence_snapshot.snapshot_id or
            (completeness_snapshot.event_id, completeness_snapshot.projection_id,
             completeness_snapshot.tracker_state_id, completeness_snapshot.temporal_snapshot_id,
             completeness_snapshot.selected_tick, completeness_snapshot.evaluated_at_tick) !=
            (absence_snapshot.event_id, absence_snapshot.projection_id,
             absence_snapshot.tracker_state_id, absence_snapshot.temporal_snapshot_id,
             absence_snapshot.selected_tick, absence_snapshot.evaluated_at_tick)):
        raise ValueError('completeness_snapshot_binding_mismatch')
    assessments = _assessments(completeness_snapshot, absences)
    positive_id = positive_snapshot.snapshot_id
    absence_id = absence_snapshot.snapshot_id
    completeness_id = completeness_snapshot.snapshot_id
    resolutions = []
    for threat_id, absence in sorted(absences.items()):
        positive = positives.get(threat_id)
        assessment = assessments.get(threat_id)
        reason = _reason(positive, absence, assessment)
        if reason is MissingResolutionReason.JUSTIFIED_MISSING:
            status = MissingResolutionStatus.MISSING
        elif reason is MissingResolutionReason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT:
            status = MissingResolutionStatus.CONFLICTED
        else:
            status = MissingResolutionStatus.NOT_JUSTIFIED
        resolutions.append(MissingThreatResolution(
            threat_id, status, reason, positive, absence, assessment,
            positive_id, absence_id, completeness_id,
            None if positive is None else positive.observed_tick,
            absence.observed_tick if status is MissingResolutionStatus.MISSING else None))
    return MissingThreatResolutionSnapshot(
        absence_snapshot.timeline_id, absence_snapshot.selected_clock_id,
        positive_id, absence_id, completeness_id,
        max(positive_snapshot.evaluated_at_tick, absence_snapshot.evaluated_at_tick,
            completeness_snapshot.evaluated_at_tick), tuple(resolutions))
