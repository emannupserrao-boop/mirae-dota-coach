"""Conservative state arbitration at one explicit tick; no temporal refresh.

MISSING and CONFLICTED are accepted resolver conclusions, not derived here.
State conveys neither relevance, risk nor safety.
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


RULESET = 'threat.state_assembly.v1'


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


class AssembledThreatState(str, Enum):
    VISIBLE_NEARBY = 'VISIBLE_NEARBY'
    VISIBLE_AWAY = 'VISIBLE_AWAY'
    MISSING = 'MISSING'
    UNKNOWN = 'UNKNOWN'
    CONFLICTED = 'CONFLICTED'


class ThreatStateReason(str, Enum):
    CURRENT_POSITIVE = 'CURRENT_POSITIVE'
    JUSTIFIED_MISSING = 'JUSTIFIED_MISSING'
    VALIDATED_CONFLICT = 'VALIDATED_CONFLICT'
    NO_CURRENT_POSITIVE = 'NO_CURRENT_POSITIVE'
    UNRESOLVED_NEGATIVE_EVIDENCE = 'UNRESOLVED_NEGATIVE_EVIDENCE'
    TEMPORAL_MISALIGNMENT = 'TEMPORAL_MISALIGNMENT'


@dataclass(frozen=True)
class ThreatStateAssessment:
    threat_id: str
    state: AssembledThreatState
    reason: ThreatStateReason
    assembly_tick: int
    positive_observation: ThreatObservation | None
    missing_resolution: MissingThreatResolution | None

    def __post_init__(self):
        _text(self.threat_id)
        _tick(self.assembly_tick)
        if type(self.state) is not AssembledThreatState or type(self.reason) is not ThreatStateReason:
            raise TypeError('explicit_state_and_reason_required')
        if self.state in (AssembledThreatState.VISIBLE_NEARBY, AssembledThreatState.VISIBLE_AWAY):
            valid = self.reason is ThreatStateReason.CURRENT_POSITIVE
        elif self.state is AssembledThreatState.MISSING:
            valid = self.reason is ThreatStateReason.JUSTIFIED_MISSING
        elif self.state is AssembledThreatState.CONFLICTED:
            valid = self.reason is ThreatStateReason.VALIDATED_CONFLICT
        else:
            valid = self.reason in (ThreatStateReason.NO_CURRENT_POSITIVE,
                                    ThreatStateReason.UNRESOLVED_NEGATIVE_EVIDENCE,
                                    ThreatStateReason.TEMPORAL_MISALIGNMENT)
        if not valid:
            raise ValueError('invalid_state_reason_pair')


@dataclass(frozen=True)
class ThreatStateSnapshot:
    timeline_id: str
    selected_clock_id: str
    positive_snapshot_id: str
    missing_snapshot_id: str
    assembly_tick: int
    assessments: tuple[ThreatStateAssessment, ...]

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
    if observation.last_observed_tick != observation.observed_tick:
        raise ValueError('observation_occurrence_mismatch')
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
    if snapshot.evaluated_at_tick < snapshot.selected_tick:
        raise ValueError('evaluation_precedes_occurrence')
    if type(snapshot.observations) is not tuple:
        raise TypeError('positive_observation_tuple_required')
    index = {}
    for observation in snapshot.observations:
        _observation(observation, True)
        if (observation.observed_tick != snapshot.selected_tick or
                observation.last_observed_tick + observation.age_ticks != snapshot.evaluated_at_tick):
            raise ValueError('positive_evaluation_binding_mismatch')
        if observation.threat_id in index:
            raise ValueError('duplicate_positive_subject')
        index[observation.threat_id] = observation
    return index


def _nested_completeness(assessment, threat_id, absence):
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
    if (assessment.absence_ref, assessment.source_id, assessment.observed_tick,
            assessment.absence_temporal_status, assessment.absence_last_observed_tick,
            assessment.absence_age_ticks, assessment.absence_temporal_policy_id,
            assessment.absence_max_age_ticks) != (
            absence.ref, absence.source_id, absence.observed_tick, absence.temporal_status,
            absence.last_observed_tick, absence.age_ticks, absence.temporal_policy_id,
            absence.max_age_ticks):
        raise ValueError('nested_assessment_absence_binding_mismatch')


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
            _nested_completeness(resolution.assessment, resolution.threat_id, resolution.absence)
        for value in (resolution.last_seen_tick, resolution.missing_since_tick):
            if value is not None:
                _tick(value)
        if resolution.absence.last_observed_tick + resolution.absence.age_ticks > snapshot.resolved_at_tick:
            raise ValueError('negative_evaluation_after_resolution')
        if resolution.threat_id in index:
            raise ValueError('duplicate_resolution_subject')
        index[resolution.threat_id] = resolution
    return index


def _aligned(observation, assembly_tick):
    # Identity of the upstream evaluation instant, never a freshness calculation.
    return observation.last_observed_tick + observation.age_ticks == assembly_tick


def _current(observation, assembly_tick):
    return observation.temporal_status is TemporalStatus.FRESH and _aligned(observation, assembly_tick)


def _positive_state(positive):
    state = (AssembledThreatState.VISIBLE_NEARBY if positive.proximity is ThreatProximity.NEARBY
             else AssembledThreatState.VISIBLE_AWAY)
    return state, ThreatStateReason.CURRENT_POSITIVE


def _arbitrate(positive, resolution, assembly_tick):
    if resolution is None:
        if _current(positive, assembly_tick):
            return _positive_state(positive)
        reason = (ThreatStateReason.NO_CURRENT_POSITIVE if _aligned(positive, assembly_tick)
                  else ThreatStateReason.TEMPORAL_MISALIGNMENT)
        return AssembledThreatState.UNKNOWN, reason
    if resolution.status in (MissingResolutionStatus.MISSING, MissingResolutionStatus.CONFLICTED):
        if _current(resolution.absence, assembly_tick):
            if resolution.status is MissingResolutionStatus.MISSING:
                return AssembledThreatState.MISSING, ThreatStateReason.JUSTIFIED_MISSING
            return AssembledThreatState.CONFLICTED, ThreatStateReason.VALIDATED_CONFLICT
        reason = (ThreatStateReason.UNRESOLVED_NEGATIVE_EVIDENCE
                  if _aligned(resolution.absence, assembly_tick)
                  else ThreatStateReason.TEMPORAL_MISALIGNMENT)
        return AssembledThreatState.UNKNOWN, reason
    # NOT_JUSTIFIED is neither MISSING nor NOT_MISSING. Only a strictly later
    # current positive can settle visibility; same/older ticks remain unresolved.
    if positive is not None and positive.observed_tick > resolution.absence.observed_tick:
        if _current(positive, assembly_tick):
            return _positive_state(positive)
        reason = (ThreatStateReason.NO_CURRENT_POSITIVE if _aligned(positive, assembly_tick)
                  else ThreatStateReason.TEMPORAL_MISALIGNMENT)
        return AssembledThreatState.UNKNOWN, reason
    return AssembledThreatState.UNKNOWN, ThreatStateReason.UNRESOLVED_NEGATIVE_EVIDENCE


def build_threat_state(
        positive_snapshot: ThreatObservationSnapshot,
        missing_snapshot: MissingThreatResolutionSnapshot,
) -> ThreatStateSnapshot:
    """Resolve the explicit subject union; preserve all matching evidence objects.

    Each upstream status is usable only at its own evaluation instant. This
    function does not age evidence, rerun policies or derive resolver conclusions.
    """
    if type(positive_snapshot) is not ThreatObservationSnapshot:
        raise TypeError('positive_snapshot_required')
    if type(missing_snapshot) is not MissingThreatResolutionSnapshot:
        raise TypeError('missing_snapshot_required')
    if positive_snapshot.timeline_id != missing_snapshot.timeline_id:
        raise ValueError('timeline_mismatch')
    if positive_snapshot.selected_clock_id != missing_snapshot.selected_clock_id:
        raise ValueError('clock_mismatch')
    positives = _positive_index(positive_snapshot)
    resolutions = _missing_index(missing_snapshot, positives)
    if missing_snapshot.positive_snapshot_id != positive_snapshot.snapshot_id:
        raise ValueError('positive_snapshot_binding_mismatch')
    assembly_tick = max(positive_snapshot.evaluated_at_tick, missing_snapshot.resolved_at_tick)
    assessments = []
    for threat_id in sorted(positives.keys() | resolutions.keys()):
        positive = positives.get(threat_id)
        resolution = resolutions.get(threat_id)
        state, reason = _arbitrate(positive, resolution, assembly_tick)
        assessments.append(ThreatStateAssessment(
            threat_id, state, reason, assembly_tick, positive, resolution))
    return ThreatStateSnapshot(
        positive_snapshot.timeline_id, positive_snapshot.selected_clock_id,
        positive_snapshot.snapshot_id, missing_snapshot.snapshot_id,
        assembly_tick, tuple(assessments))
