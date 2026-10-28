"""Explicit occurrence metadata on a caller-owned logical timeline.

No values, source interpretation, clocks, IO or automatic core integration.
Evaluation is a read: commit timeline progress with record_observations(state, (),
tick) when retaining a newer high-water mark is required. Never reuse an older
state to represent a current timeline. Policies and refs are opaque inputs.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json


RULESET = 'temporal.explicit_freshness.v1'


def _text(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_' + field + '_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _identity(kind, value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('utf-8')
    return RULESET + ':' + kind + ':' + hashlib.sha256(encoded).hexdigest()


class TemporalStatus(str, Enum):
    NEVER_SEEN = 'never_seen'
    FRESH = 'fresh'
    STALE = 'stale'


@dataclass(frozen=True)
class ObservationMark:
    ref: str
    last_observed_tick: int

    def __post_init__(self):
        _text(self.ref, 'ref')
        _tick(self.last_observed_tick)


@dataclass(frozen=True)
class TemporalTrackerState:
    timeline_id: str
    clock_id: str
    last_tick: int | None = None
    marks: tuple[ObservationMark, ...] = ()

    def __post_init__(self):
        _text(self.timeline_id, 'timeline_id')
        _text(self.clock_id, 'clock_id')
        if self.last_tick is not None:
            _tick(self.last_tick)
        if type(self.marks) is not tuple or any(type(m) is not ObservationMark for m in self.marks):
            raise TypeError('observation_mark_tuple_required')
        if len({m.ref for m in self.marks}) != len(self.marks):
            raise ValueError('duplicate_ref')
        if self.marks and (self.last_tick is None or
                           any(m.last_observed_tick > self.last_tick for m in self.marks)):
            raise ValueError('mark_outside_recorded_timeline')
        object.__setattr__(self, 'marks', tuple(sorted(self.marks, key=lambda m: m.ref)))

    @property
    def state_id(self) -> str:
        return _identity('state', asdict(self))


@dataclass(frozen=True)
class FreshnessPolicy:
    policy_id: str
    max_age_ticks: int

    def __post_init__(self):
        _text(self.policy_id, 'policy_id')
        _tick(self.max_age_ticks)
        if self.max_age_ticks < 0:
            raise ValueError('negative_max_age_ticks')


@dataclass(frozen=True)
class TemporalQuery:
    ref: str
    policy: FreshnessPolicy

    def __post_init__(self):
        _text(self.ref, 'ref')
        if type(self.policy) is not FreshnessPolicy:
            raise TypeError('explicit_freshness_policy_required')


@dataclass(frozen=True)
class TemporalEvidenceStatus:
    ref: str
    status: TemporalStatus
    last_observed_tick: int | None
    age_ticks: int | None
    policy_id: str
    max_age_ticks: int


@dataclass(frozen=True)
class TemporalSnapshot:
    timeline_id: str
    clock_id: str
    evaluated_at_tick: int
    tracker_state_id: str
    entries: tuple[TemporalEvidenceStatus, ...]

    @property
    def snapshot_id(self) -> str:
        return _identity('snapshot', asdict(self))


def new_temporal_state(timeline_id: str, clock_id: str) -> TemporalTrackerState:
    """New explicit lifetime, always empty; never discovers or reuses a session."""
    return TemporalTrackerState(timeline_id, clock_id)


def _check_time(state, tick):
    if type(state) is not TemporalTrackerState:
        raise TypeError('temporal_tracker_state_required')
    _tick(tick)
    if state.last_tick is not None and tick < state.last_tick:
        raise ValueError('decreasing_tick')


def record_observations(state: TemporalTrackerState, refs: tuple[str, ...],
                        tick: int) -> TemporalTrackerState:
    """Atomic pure transition; duplicates fail. Empty refs advance time only.

    Equal ticks are valid. A mark certifies an occurrence, never a semantic value.
    The caller must retain the returned state for subsequent timeline operations.
    """
    _check_time(state, tick)
    if type(refs) is not tuple:
        raise TypeError('ref_tuple_required')
    for ref in refs:
        _text(ref, 'ref')
    if len(set(refs)) != len(refs):
        raise ValueError('duplicate_ref')
    marks = {m.ref: m for m in state.marks}
    for ref in refs:
        marks[ref] = ObservationMark(ref, tick)
    return TemporalTrackerState(state.timeline_id, state.clock_id, tick,
                                tuple(marks.values()))


def evaluate_freshness(state: TemporalTrackerState, tick: int,
                       queries: tuple[TemporalQuery, ...]) -> TemporalSnapshot:
    """Read at an explicit tick, without advancing the supplied immutable state.

    Query keys are (ref, policy_id); duplicates fail. Multiple policies per ref
    are supported, but a policy_id must have one threshold within this snapshot.
    Under a fixed policy and nondecreasing ticks, silence cannot refresh a mark.
    An explicitly changed policy is a new assessment, not a new observation.
    """
    _check_time(state, tick)
    if type(queries) is not tuple or any(type(q) is not TemporalQuery for q in queries):
        raise TypeError('temporal_query_tuple_required')
    if len({(q.ref, q.policy.policy_id) for q in queries}) != len(queries):
        raise ValueError('duplicate_query')
    policies = {}
    for query in queries:
        policy = query.policy
        if policy.policy_id in policies and policies[policy.policy_id] != policy.max_age_ticks:
            raise ValueError('conflicting_policy_id')
        policies[policy.policy_id] = policy.max_age_ticks
    marks = {m.ref: m.last_observed_tick for m in state.marks}
    entries = []
    for query in sorted(queries, key=lambda q: (q.ref, q.policy.policy_id)):
        last = marks.get(query.ref)
        age = None if last is None else tick - last
        status = (TemporalStatus.NEVER_SEEN if age is None else
                  TemporalStatus.FRESH if age <= query.policy.max_age_ticks else
                  TemporalStatus.STALE)
        entries.append(TemporalEvidenceStatus(query.ref, status, last, age,
                                              query.policy.policy_id, query.policy.max_age_ticks))
    return TemporalSnapshot(state.timeline_id, state.clock_id, tick,
                            state.state_id, tuple(entries))
