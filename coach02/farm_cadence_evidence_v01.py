"""Retrospective observed LH intervals; no quality, prediction or action authority."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math

from .live_runtime_v01 import (RuntimeUpdateResultV1, RuntimeUpdateStatus,
                              RuntimeCapabilitySupport, RuntimeFieldPresence,
                              RuntimeFieldValidity)

RULESET = 'farm.observed_lh_cadence.v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def _identity(kind, value):
    return RULESET + ':' + kind + ':' + hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identifier_required')


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _counter(value):
    return _number(value) and value >= 0 and int(value) == value


class SemanticInputPresence(str, Enum):
    PRESENT = 'PRESENT'
    ABSENT = 'ABSENT'


class FarmCadenceStatus(str, Enum):
    OBSERVED_INTERVAL = 'OBSERVED_INTERVAL'
    INDETERMINATE = 'INDETERMINATE'


class FarmCadenceReason(str, Enum):
    INITIAL_ANCHOR = 'INITIAL_ANCHOR'
    WINDOW_INCOMPLETE = 'WINDOW_INCOMPLETE'
    OBSERVED_INTERVAL = 'OBSERVED_INTERVAL'
    NO_CURRENT_SNAPSHOT = 'NO_CURRENT_SNAPSHOT'
    SCOPE_INELIGIBLE = 'SCOPE_INELIGIBLE'
    FIELD_UNAVAILABLE = 'FIELD_UNAVAILABLE'
    INVALID_SOURCE_TIME = 'INVALID_SOURCE_TIME'
    INVALID_LH = 'INVALID_LH'
    PAUSED = 'PAUSED'
    NOT_ALIVE = 'NOT_ALIVE'
    CONTINUITY_RESET = 'CONTINUITY_RESET'
    CONTINUITY_GAP = 'CONTINUITY_GAP'
    SOURCE_TIME_REWIND = 'SOURCE_TIME_REWIND'
    LH_REGRESSION = 'LH_REGRESSION'
    SAME_SOURCE_TIME = 'SAME_SOURCE_TIME'
    SAME_TIME_LH_CHANGE = 'SAME_TIME_LH_CHANGE'
    RATE_NOT_REPRESENTABLE = 'RATE_NOT_REPRESENTABLE'


@dataclass(frozen=True)
class SemanticRuntimeInputV1:
    """Current snapshot and existing embedded freshness; never creates observations."""
    input_presence: SemanticInputPresence
    run_id: str
    session_id: str | None
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    receipt_elapsed_ns: int
    receive_sequence: int
    hero: str | None
    runtime_snapshot_id: str | None
    payload_id: str | None
    normalized_state_json: str | None
    source_id: str | None
    observation_event_id: str | None
    temporal_projection_id: str | None
    temporal_snapshot_id: str | None
    valid_fields: tuple[str, ...]
    fresh_fields: tuple[str, ...]
    continuity_broken: bool
    shutdown: bool


def project_semantic_runtime_input_v1(*, runtime_result):
    """Validate accepted envelope lineage. No raw GSI, clocks or Temporal calls."""
    if type(runtime_result) is not RuntimeUpdateResultV1:
        raise TypeError('exact_runtime_result_required')
    runtime_result.__post_init__()
    state = runtime_result.next_state
    state.__post_init__()
    if state.evaluated_at_tick is None or state.last_receipt_elapsed_ns is None:
        raise ValueError('evaluated_runtime_result_required')
    snapshot, event, projection, temporal = (runtime_result.snapshot,
        runtime_result.observation_event, runtime_result.temporal_projection,
        runtime_result.temporal_snapshot)
    reasons = tuple(r.value for r in runtime_result.reason_codes)
    broken = (runtime_result.status in (RuntimeUpdateStatus.REJECTED, RuntimeUpdateStatus.ERROR)
              or any(r in reasons for r in ('SESSION_END', 'SESSION_START', 'REWIND',
                    'GAP', 'TIMELINE_RESET', 'SHUTDOWN')))
    fresh = ()
    temporal_id = None
    if temporal is not None:
        temporal_id = temporal.snapshot_id
        if temporal.evaluated_at_tick != state.evaluated_at_tick:
            raise ValueError('freshness_tick_mismatch')
        if (temporal.timeline_id, temporal.clock_id) == (state.timeline_id, state.selected_clock_id):
            if len({e.ref for e in temporal.entries}) != len(temporal.entries):
                raise ValueError('ambiguous_embedded_freshness')
            fresh = tuple(e.ref for e in temporal.entries
                if e.status.value == 'fresh' and e.last_observed_tick is not None
                and e.last_observed_tick <= state.evaluated_at_tick
                and e.age_ticks == state.evaluated_at_tick - e.last_observed_tick
                and 0 <= e.age_ticks <= e.max_age_ticks
                and e.policy_id == state.policy.freshness_policy_id
                and e.max_age_ticks == state.policy.max_age_ns)
        elif not broken:
            raise ValueError('freshness_timeline_mismatch')
    if snapshot is None:
        return SemanticRuntimeInputV1(SemanticInputPresence.ABSENT, state.run_id,
            state.session_id, state.timeline_id, state.selected_clock_id,
            state.evaluated_at_tick, state.last_receipt_elapsed_ns,
            state.receive_sequence, state.known_hero, None, None, None, None,
            None, None, temporal_id, (), fresh, broken, state.shutdown)
    snapshot.__post_init__()
    if (snapshot.run_id, snapshot.session_id, snapshot.timeline_id,
            snapshot.selected_clock_id, snapshot.evaluated_at_tick, snapshot.receive_sequence) != (
            state.run_id, state.session_id, state.timeline_id, state.selected_clock_id,
            state.evaluated_at_tick, state.receive_sequence):
        raise ValueError('runtime_snapshot_state_lineage_mismatch')
    if (event.timeline_id != snapshot.timeline_id or projection.event_id != event.event_id
            or projection.timeline_id != snapshot.timeline_id
            or projection.selected_clock_id != snapshot.selected_clock_id
            or projection.selected_tick != snapshot.evaluated_at_tick
            or projection.timestamp_basis.value != 'receipt'
            or event.receipt_stamp.clock_id != snapshot.selected_clock_id
            or event.receipt_stamp.tick != snapshot.evaluated_at_tick
            or projection.refs != event.refs or projection.source_id != event.source.source_id
            or temporal.timeline_id != snapshot.timeline_id
            or temporal.clock_id != snapshot.selected_clock_id):
        raise ValueError('embedded_occurrence_lineage_mismatch')
    data = json.loads(snapshot.normalized_state_json)
    if data['time'] != snapshot.source_match_time:
        raise ValueError('source_time_projection_mismatch')
    entries = {e.ref: e for e in temporal.entries}
    valid = tuple(c.field_id for c in snapshot.capabilities
        if c.support is RuntimeCapabilitySupport.SUPPORTED
        and c.presence is RuntimeFieldPresence.PRESENT
        and c.validity is RuntimeFieldValidity.VALID
        and c.field_id in fresh and c.field_id in event.refs
        and entries[c.field_id].last_observed_tick == snapshot.evaluated_at_tick)
    return SemanticRuntimeInputV1(SemanticInputPresence.PRESENT, state.run_id,
        snapshot.session_id, snapshot.timeline_id, snapshot.selected_clock_id,
        snapshot.evaluated_at_tick, state.last_receipt_elapsed_ns, snapshot.receive_sequence,
        data['hero'] if type(data['hero']) is str and data['hero'].strip() else None,
        snapshot.snapshot_id, snapshot.payload_id, snapshot.normalized_state_json,
        event.source.source_id, event.event_id, projection.projection_id,
        temporal_id, valid, fresh, broken, state.shutdown)


@dataclass(frozen=True)
class FarmCadencePolicyV1:
    policy_id: str
    minimum_gameplay_interval_seconds: int | float
    max_receipt_gap_ns: int
    max_source_step_seconds: int | float

    def __post_init__(self):
        _text(self.policy_id)
        if not _number(self.minimum_gameplay_interval_seconds) or self.minimum_gameplay_interval_seconds <= 0:
            raise ValueError('positive_gameplay_interval_required')
        if type(self.max_receipt_gap_ns) is not int or self.max_receipt_gap_ns <= 0:
            raise ValueError('positive_concrete_receipt_gap_required')
        if not _number(self.max_source_step_seconds) or self.max_source_step_seconds <= 0:
            raise ValueError('positive_source_step_required')


@dataclass(frozen=True)
class FarmCadenceSampleV1:
    runtime_snapshot_id: str
    payload_id: str
    run_id: str
    session_id: str
    timeline_id: str
    selected_clock_id: str
    hero: str
    evaluated_at_tick: int
    receipt_elapsed_ns: int
    receive_sequence: int
    source_match_time: int | float
    lh: int
    source_id: str
    observation_event_id: str
    temporal_projection_id: str
    temporal_snapshot_id: str
    evidence_refs: tuple[str, ...] = ('lh', 'time', 'local', 'hero', 'phase', 'paused', 'alive')

    def __post_init__(self):
        for value in (self.runtime_snapshot_id, self.payload_id, self.run_id, self.session_id,
                self.timeline_id, self.selected_clock_id, self.hero, self.source_id,
                self.observation_event_id, self.temporal_projection_id, self.temporal_snapshot_id):
            _text(value)
        for value in (self.evaluated_at_tick, self.receipt_elapsed_ns, self.receive_sequence, self.lh):
            if type(value) is not int or value < 0:
                raise ValueError('nonnegative_sample_integer_required')
        if self.receive_sequence == 0 or not _number(self.source_match_time) or self.source_match_time < 0:
            raise ValueError('invalid_sample_source_time_or_sequence')
        if type(self.evidence_refs) is not tuple or len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError('exact_unique_provenance_tuple_required')
        for ref in self.evidence_refs: _text(ref)

    @property
    def sample_id(self):
        return _identity('sample', asdict(self))


@dataclass(frozen=True)
class FarmCadenceStateV1:
    policy: FarmCadencePolicyV1
    run_id: str | None = None
    session_id: str | None = None
    timeline_id: str | None = None
    selected_clock_id: str | None = None
    hero: str | None = None
    evaluated_at_tick: int | None = None
    anchor: FarmCadenceSampleV1 | None = None
    last_sample: FarmCadenceSampleV1 | None = None
    ruleset: str = RULESET

    def __post_init__(self):
        if type(self.policy) is not FarmCadencePolicyV1 or self.ruleset != RULESET:
            raise ValueError('exact_farm_policy_ruleset_required')
        self.policy.__post_init__()
        for value in (self.run_id, self.session_id, self.timeline_id, self.selected_clock_id, self.hero):
            if value is not None: _text(value)
        if self.evaluated_at_tick is not None and (type(self.evaluated_at_tick) is not int or self.evaluated_at_tick < 0):
            raise ValueError('valid_farm_tick_required')
        if (self.anchor is None) != (self.last_sample is None):
            raise ValueError('paired_anchor_and_sample_required')
        for s in (self.anchor, self.last_sample):
            if s is not None:
                if type(s) is not FarmCadenceSampleV1: raise TypeError('exact_farm_sample_required')
                s.__post_init__()
                if _lineage(s) != _lineage(self) or self.evaluated_at_tick is None or s.evaluated_at_tick > self.evaluated_at_tick:
                    raise ValueError('farm_sample_lineage_mismatch')
        if self.anchor is not None and (self.anchor.evaluated_at_tick > self.last_sample.evaluated_at_tick
                or self.anchor.source_match_time > self.last_sample.source_match_time or self.anchor.lh > self.last_sample.lh):
            raise ValueError('invalid_farm_interval_memory')

    @property
    def state_id(self): return _identity('state', asdict(self))


@dataclass(frozen=True)
class FarmCadenceEvidenceV1:
    status: FarmCadenceStatus
    reason: FarmCadenceReason
    input_presence: SemanticInputPresence
    run_id: str
    session_id: str | None
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    receive_sequence: int
    runtime_snapshot_id: str | None
    payload_id: str | None
    policy_id: str
    start_sample: FarmCadenceSampleV1 | None
    end_sample: FarmCadenceSampleV1 | None
    delta_lh: int | None
    gameplay_duration: int | float | None
    ruleset: str = RULESET

    @property
    def lh_per_game_minute(self):
        return None if self.delta_lh is None else 60 * self.delta_lh / self.gameplay_duration

    @property
    def evidence_id(self): return _identity('evidence', asdict(self))


@dataclass(frozen=True)
class FarmCadenceUpdateV1:
    next_state: FarmCadenceStateV1
    evidence: FarmCadenceEvidenceV1


def _lineage(value):
    return (value.run_id, value.session_id, value.timeline_id, value.selected_clock_id, value.hero)


def new_farm_cadence_state_v1(*, policy):
    return FarmCadenceStateV1(policy)


def advance_farm_cadence_v1(*, previous_state, runtime_result, policy):
    if type(previous_state) is not FarmCadenceStateV1 or type(policy) is not FarmCadencePolicyV1:
        raise TypeError('exact_farm_contracts_required')
    previous_state.__post_init__(); policy.__post_init__()
    view = project_semantic_runtime_input_v1(runtime_result=runtime_result)
    old = previous_state
    same = _lineage(old) == _lineage(view) and policy == old.policy
    unchanged_rejection = (view.input_presence is SemanticInputPresence.ABSENT
        and view.continuity_broken and view.evaluated_at_tick == old.evaluated_at_tick)
    if old.run_id == view.run_id and old.evaluated_at_tick is not None and view.evaluated_at_tick <= old.evaluated_at_tick and not unchanged_rejection:
        raise ValueError('nonincreasing_farm_tick')
    anchor, last = (old.anchor, old.last_sample) if same and not view.continuity_broken else (None, None)
    reason = FarmCadenceReason.INITIAL_ANCHOR
    current = None
    start = None
    delta = duration = None
    status = FarmCadenceStatus.INDETERMINATE
    if view.input_presence is SemanticInputPresence.ABSENT:
        reason = FarmCadenceReason.NO_CURRENT_SNAPSHOT
        essential = {'lh', 'time', 'local', 'hero', 'phase', 'paused', 'alive'}
        if (view.continuity_broken or view.shutdown or not essential.issubset(view.fresh_fields)
                or last is not None and view.receipt_elapsed_ns - last.receipt_elapsed_ns > policy.max_receipt_gap_ns):
            anchor = last = None
            reason = FarmCadenceReason.CONTINUITY_RESET
    else:
        data = json.loads(view.normalized_state_json)
        if view.session_id is None or data['local'] is not True or not view.hero or data['phase'] != 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS':
            reason = FarmCadenceReason.SCOPE_INELIGIBLE
        elif not {'lh','time','local','hero','phase','paused','alive'}.issubset(view.valid_fields):
            reason = FarmCadenceReason.FIELD_UNAVAILABLE
        elif not _number(data['time']) or data['time'] < 0:
            reason = FarmCadenceReason.INVALID_SOURCE_TIME
        elif not _counter(data['lh']):
            reason = FarmCadenceReason.INVALID_LH
        elif type(data['paused']) is not bool or type(data['alive']) is not bool:
            reason = FarmCadenceReason.FIELD_UNAVAILABLE
        elif data['paused']:
            reason = FarmCadenceReason.PAUSED
        elif not data['alive']:
            reason = FarmCadenceReason.NOT_ALIVE
        else:
            current = FarmCadenceSampleV1(view.runtime_snapshot_id, view.payload_id, view.run_id,
                view.session_id, view.timeline_id, view.selected_clock_id, view.hero,
                view.evaluated_at_tick, view.receipt_elapsed_ns, view.receive_sequence,
                data['time'], int(data['lh']), view.source_id, view.observation_event_id,
                view.temporal_projection_id, view.temporal_snapshot_id)
        if current is None:
            anchor = last = None
        elif last is None:
            anchor = last = current
        else:
            step = current.source_match_time - last.source_match_time
            if current.receive_sequence <= last.receive_sequence:
                raise ValueError('nonincreasing_farm_sequence')
            if current.receipt_elapsed_ns - last.receipt_elapsed_ns > policy.max_receipt_gap_ns or step > policy.max_source_step_seconds:
                reason = FarmCadenceReason.CONTINUITY_GAP
                anchor = last = current
            elif step < 0:
                reason = FarmCadenceReason.SOURCE_TIME_REWIND
                anchor = last = current
            elif current.lh < last.lh:
                reason = FarmCadenceReason.LH_REGRESSION
                anchor = last = current
            elif step == 0:
                reason = FarmCadenceReason.SAME_SOURCE_TIME if current.lh == last.lh else FarmCadenceReason.SAME_TIME_LH_CHANGE
                if current.lh != last.lh: anchor = current
                last = current
            else:
                duration = current.source_match_time - anchor.source_match_time
                if duration >= policy.minimum_gameplay_interval_seconds:
                    start = anchor
                    delta = current.lh - anchor.lh
                    try:
                        representable = math.isfinite(60 * delta / duration)
                    except OverflowError:
                        representable = False
                    if representable:
                        status, reason = FarmCadenceStatus.OBSERVED_INTERVAL, FarmCadenceReason.OBSERVED_INTERVAL
                    else:
                        start = None
                        delta = duration = None
                        reason = FarmCadenceReason.RATE_NOT_REPRESENTABLE
                    anchor = current
                else:
                    duration = None
                    reason = FarmCadenceReason.WINDOW_INCOMPLETE
                last = current
    state = FarmCadenceStateV1(policy, view.run_id, view.session_id, view.timeline_id,
        view.selected_clock_id, view.hero, view.evaluated_at_tick, anchor, last)
    evidence = FarmCadenceEvidenceV1(status, reason, view.input_presence, view.run_id,
        view.session_id, view.timeline_id, view.selected_clock_id, view.evaluated_at_tick,
        view.receive_sequence, view.runtime_snapshot_id, view.payload_id, policy.policy_id,
        start, current, delta, duration)
    return FarmCadenceUpdateV1(state, evidence)
