"""Explicit context-bound coverage at an exact supplied observation occurrence.

Coverage is not safety, risk or visibility completeness. Temporal Evidence owns
freshness; stale observations retain their historical coverage classification.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .observation_event import ObservationEvent, TemporalProjection, TimestampBasis
from .temporal_evidence import TemporalEvidenceStatus, TemporalSnapshot, TemporalStatus


RULESET = 'strategic.coverage_observation.v1'


def _text(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_' + field + '_required')


def _integer(value, field):
    if type(value) is not int:
        raise TypeError('integer_' + field + '_required')


class StrategicCoverageState(str, Enum):
    SUFFICIENT = 'SUFFICIENT'
    INSUFFICIENT = 'INSUFFICIENT'
    UNKNOWN = 'UNKNOWN'


@dataclass(frozen=True)
class StrategicCoverageClaim:
    coverage_context_id: str
    ref: str
    coverage: StrategicCoverageState
    temporal_policy_id: str
    assessment_policy_id: str

    def __post_init__(self):
        for value, field in ((self.coverage_context_id, 'coverage_context_id'), (self.ref, 'ref'),
                             (self.temporal_policy_id, 'temporal_policy_id'),
                             (self.assessment_policy_id, 'assessment_policy_id')):
            _text(value, field)
        if type(self.coverage) is not StrategicCoverageState:
            raise TypeError('explicit_strategic_coverage_required')


@dataclass(frozen=True)
class StrategicCoverageObservation:
    coverage_context_id: str
    ref: str
    coverage: StrategicCoverageState
    source_id: str
    observed_tick: int
    temporal_status: TemporalStatus
    last_observed_tick: int
    age_ticks: int
    temporal_policy_id: str
    max_age_ticks: int
    assessment_policy_id: str


@dataclass(frozen=True)
class StrategicCoverageSnapshot:
    timeline_id: str
    event_id: str
    projection_id: str
    tracker_state_id: str
    temporal_snapshot_id: str
    selected_clock_id: str
    selected_tick: int
    evaluated_at_tick: int
    observations: tuple[StrategicCoverageObservation, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _lineage(event, projection, temporal_snapshot):
    if type(event) is not ObservationEvent:
        raise TypeError('observation_event_required')
    if type(projection) is not TemporalProjection:
        raise TypeError('temporal_projection_required')
    if type(temporal_snapshot) is not TemporalSnapshot:
        raise TypeError('temporal_snapshot_required')
    for value, field in ((event.timeline_id, 'timeline_id'), (event.source.source_id, 'source_id'),
                         (projection.selected_clock_id, 'clock_id'),
                         (projection.timing_policy_id, 'timing_policy_id'),
                         (temporal_snapshot.tracker_state_id, 'tracker_state_id')):
        _text(value, field)
    if projection.event_id != event.event_id:
        raise ValueError('projection_event_mismatch')
    if projection.timeline_id != event.timeline_id:
        raise ValueError('projection_timeline_mismatch')
    if projection.source_id != event.source.source_id:
        raise ValueError('projection_source_mismatch')
    if projection.refs != event.refs:
        raise ValueError('projection_refs_mismatch')
    if type(projection.timestamp_basis) is not TimestampBasis:
        raise TypeError('explicit_timestamp_basis_required')
    _integer(projection.selected_tick, 'selected_tick')
    stamp = event.source_stamp if projection.timestamp_basis is TimestampBasis.SOURCE else event.receipt_stamp
    if stamp is None or (stamp.clock_id, stamp.tick) != (projection.selected_clock_id, projection.selected_tick):
        raise ValueError('projection_stamp_mismatch')
    if temporal_snapshot.timeline_id != event.timeline_id:
        raise ValueError('temporal_timeline_mismatch')
    if temporal_snapshot.clock_id != projection.selected_clock_id:
        raise ValueError('temporal_clock_mismatch')
    _integer(temporal_snapshot.evaluated_at_tick, 'evaluated_tick')
    if temporal_snapshot.evaluated_at_tick < projection.selected_tick:
        raise ValueError('evaluation_precedes_occurrence')


def _entry_index(temporal_snapshot):
    if type(temporal_snapshot.entries) is not tuple:
        raise TypeError('temporal_entry_tuple_required')
    index = {}
    policies = {}
    for entry in temporal_snapshot.entries:
        if type(entry) is not TemporalEvidenceStatus:
            raise TypeError('temporal_evidence_status_required')
        _text(entry.ref, 'ref')
        _text(entry.policy_id, 'temporal_policy_id')
        if type(entry.status) is not TemporalStatus:
            raise TypeError('temporal_status_required')
        _integer(entry.max_age_ticks, 'max_age_ticks')
        if entry.max_age_ticks < 0:
            raise ValueError('negative_max_age_ticks')
        key = (entry.ref, entry.policy_id)
        if key in index:
            raise ValueError('ambiguous_temporal_entry')
        if entry.policy_id in policies and policies[entry.policy_id] != entry.max_age_ticks:
            raise ValueError('conflicting_temporal_policy')
        index[key] = entry
        policies[entry.policy_id] = entry.max_age_ticks
    return index


def build_strategic_coverage(
        event: ObservationEvent,
        projection: TemporalProjection,
        temporal_snapshot: TemporalSnapshot,
        claims: tuple[StrategicCoverageClaim, ...],
) -> StrategicCoverageSnapshot:
    """Bind each explicit coverage claim to its exact event and temporal entry.

    One claim per context. Empty claims make no semantic assertion. No source,
    timing or coverage policy is selected or implemented by this builder.
    """
    _lineage(event, projection, temporal_snapshot)
    if type(claims) is not tuple or any(type(c) is not StrategicCoverageClaim for c in claims):
        raise TypeError('strategic_coverage_claim_tuple_required')
    if len({c.coverage_context_id for c in claims}) != len(claims):
        raise ValueError('duplicate_coverage_context_id')
    index = _entry_index(temporal_snapshot)
    observations = []
    for claim in sorted(claims, key=lambda c: (c.coverage_context_id, c.ref, c.temporal_policy_id, c.assessment_policy_id)):
        for value, field in ((claim.coverage_context_id, 'coverage_context_id'), (claim.ref, 'ref'),
                             (claim.temporal_policy_id, 'temporal_policy_id'),
                             (claim.assessment_policy_id, 'assessment_policy_id')):
            _text(value, field)
        if type(claim.coverage) is not StrategicCoverageState:
            raise TypeError('explicit_strategic_coverage_required')
        if claim.ref not in event.refs:
            raise ValueError('claim_ref_not_in_event')
        key = (claim.ref, claim.temporal_policy_id)
        if key not in index:
            raise ValueError('temporal_entry_required')
        entry = index[key]
        if entry.status is TemporalStatus.NEVER_SEEN:
            raise ValueError('claim_occurrence_never_seen')
        _integer(entry.last_observed_tick, 'last_observed_tick')
        _integer(entry.age_ticks, 'age_ticks')
        if entry.last_observed_tick != projection.selected_tick:
            raise ValueError('exact_occurrence_tick_required')
        if entry.age_ticks != temporal_snapshot.evaluated_at_tick - entry.last_observed_tick:
            raise ValueError('inconsistent_temporal_age')
        observations.append(StrategicCoverageObservation(
            claim.coverage_context_id, claim.ref, claim.coverage, event.source.source_id,
            projection.selected_tick, entry.status, entry.last_observed_tick, entry.age_ticks,
            entry.policy_id, entry.max_age_ticks, claim.assessment_policy_id))
    return StrategicCoverageSnapshot(
        event.timeline_id, event.event_id, projection.projection_id, temporal_snapshot.tracker_state_id,
        temporal_snapshot.snapshot_id, projection.selected_clock_id, projection.selected_tick,
        temporal_snapshot.evaluated_at_tick, tuple(observations))
