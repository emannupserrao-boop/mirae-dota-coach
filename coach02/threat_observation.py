"""Bind an explicit positive sighting to its exact event occurrence.

No detector, relevance decision, missing inference or downstream orchestration.
Temporal Evidence supplies status; stale sightings retain historical proximity.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .observation_event import ObservationEvent, TemporalProjection, TimestampBasis
from .temporal_evidence import TemporalEvidenceStatus, TemporalSnapshot, TemporalStatus


RULESET = 'threat.explicit_sighting.v1'


def _text(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_' + field + '_required')


def _integer(value, field):
    if type(value) is not int:
        raise TypeError('integer_' + field + '_required')


class ThreatProximity(str, Enum):
    NEARBY = 'NEARBY'
    AWAY = 'AWAY'


@dataclass(frozen=True)
class ThreatSightingClaim:
    threat_id: str
    ref: str
    proximity: ThreatProximity
    temporal_policy_id: str

    def __post_init__(self):
        _text(self.threat_id, 'threat_id')
        _text(self.ref, 'ref')
        _text(self.temporal_policy_id, 'temporal_policy_id')
        if type(self.proximity) is not ThreatProximity:
            raise TypeError('explicit_threat_proximity_required')


@dataclass(frozen=True)
class ThreatObservation:
    threat_id: str
    ref: str
    proximity: ThreatProximity
    source_id: str
    observed_tick: int
    temporal_status: TemporalStatus
    last_observed_tick: int
    age_ticks: int
    temporal_policy_id: str
    max_age_ticks: int


@dataclass(frozen=True)
class ThreatObservationSnapshot:
    timeline_id: str
    event_id: str
    projection_id: str
    tracker_state_id: str
    temporal_snapshot_id: str
    selected_clock_id: str
    selected_tick: int
    evaluated_at_tick: int
    observations: tuple[ThreatObservation, ...]

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
    for value, field in (
            (event.timeline_id, 'timeline_id'), (event.source.source_id, 'source_id'),
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
    # A manually constructed projection must still select the actual event stamp.
    # This is lineage validation, not a policy choice, conversion or orchestration.
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


def build_threat_observations(event: ObservationEvent, projection: TemporalProjection,
                              temporal_snapshot: TemporalSnapshot,
                              claims: tuple[ThreatSightingClaim, ...]) -> ThreatObservationSnapshot:
    """Copy supported explicit semantics and authoritative temporal metadata.

    One claim per threat per build. Empty claims make no negative assertion.
    No ref parsing and no reinterpretation of a stale historical sighting.
    """
    _lineage(event, projection, temporal_snapshot)
    if type(claims) is not tuple or any(type(c) is not ThreatSightingClaim for c in claims):
        raise TypeError('threat_sighting_claim_tuple_required')
    if len({c.threat_id for c in claims}) != len(claims):
        raise ValueError('duplicate_threat_id')
    index = _entry_index(temporal_snapshot)
    observations = []
    for claim in sorted(claims, key=lambda c: (c.threat_id, c.ref, c.temporal_policy_id)):
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
        observations.append(ThreatObservation(
            claim.threat_id, claim.ref, claim.proximity, event.source.source_id,
            projection.selected_tick, entry.status, entry.last_observed_tick,
            entry.age_ticks, entry.policy_id, entry.max_age_ticks))
    return ThreatObservationSnapshot(
        event.timeline_id, event.event_id, projection.projection_id,
        temporal_snapshot.tracker_state_id, temporal_snapshot.snapshot_id,
        projection.selected_clock_id, projection.selected_tick,
        temporal_snapshot.evaluated_at_tick, tuple(observations))
