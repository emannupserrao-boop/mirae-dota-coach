"""Neutral immutable occurrence envelope; no observer, clock or tracker wiring.

Source and receipt stamps are supplied independently. Neither is authoritative
by default. Clock IDs and source/ref strings are opaque, with no unit or meaning
assigned here. The caller owns timeline, source and timing-policy lifecycles.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json


RULESET = 'observation.event_envelope.v1'


def _text(value, field):
    if type(value) is not str or not value:
        raise ValueError('nonempty_' + field + '_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _refs(refs):
    if type(refs) is not tuple:
        raise TypeError('ref_tuple_required')
    for ref in refs:
        _text(ref, 'ref')
    if len(set(refs)) != len(refs):
        raise ValueError('duplicate_ref')
    return tuple(sorted(refs))


def _identity(kind, value):
    content = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('utf-8')
    return RULESET + ':' + kind + ':' + hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ObservationSource:
    source_id: str
    source_kind: str
    schema_id: str

    def __post_init__(self):
        _text(self.source_id, 'source_id')
        _text(self.source_kind, 'source_kind')
        _text(self.schema_id, 'schema_id')


@dataclass(frozen=True)
class ClockStamp:
    clock_id: str
    tick: int

    def __post_init__(self):
        _text(self.clock_id, 'clock_id')
        _tick(self.tick)


@dataclass(frozen=True)
class ObservationEvent:
    timeline_id: str
    source: ObservationSource
    refs: tuple[str, ...]
    receipt_stamp: ClockStamp
    source_stamp: ClockStamp | None = None

    def __post_init__(self):
        _text(self.timeline_id, 'timeline_id')
        if type(self.source) is not ObservationSource:
            raise TypeError('observation_source_required')
        if type(self.receipt_stamp) is not ClockStamp:
            raise TypeError('receipt_stamp_required')
        if self.source_stamp is not None and type(self.source_stamp) is not ClockStamp:
            raise TypeError('invalid_source_stamp')
        canonical = _refs(self.refs)
        if (self.source_stamp is not None and
                self.source_stamp.clock_id == self.receipt_stamp.clock_id and
                self.source_stamp.tick > self.receipt_stamp.tick):
            raise ValueError('source_after_receipt_on_same_clock')
        object.__setattr__(self, 'refs', canonical)

    @property
    def event_id(self) -> str:
        return _identity('event', asdict(self))


class TimestampBasis(str, Enum):
    SOURCE = 'source'
    RECEIPT = 'receipt'


@dataclass(frozen=True)
class ObservationTimingPolicy:
    policy_id: str
    basis: TimestampBasis

    def __post_init__(self):
        _text(self.policy_id, 'policy_id')
        if type(self.basis) is not TimestampBasis:
            raise TypeError('explicit_timestamp_basis_required')


@dataclass(frozen=True)
class TemporalProjection:
    event_id: str
    timeline_id: str
    source_id: str
    refs: tuple[str, ...]
    selected_clock_id: str
    selected_tick: int
    timing_policy_id: str
    timestamp_basis: TimestampBasis

    def __post_init__(self):
        _text(self.event_id, 'event_id')
        _text(self.timeline_id, 'timeline_id')
        _text(self.source_id, 'source_id')
        _text(self.selected_clock_id, 'selected_clock_id')
        _tick(self.selected_tick)
        _text(self.timing_policy_id, 'timing_policy_id')
        if type(self.timestamp_basis) is not TimestampBasis:
            raise TypeError('explicit_timestamp_basis_required')
        object.__setattr__(self, 'refs', _refs(self.refs))

    @property
    def projection_id(self) -> str:
        return _identity('projection', asdict(self))


def project_event_time(event: ObservationEvent, timing_policy: ObservationTimingPolicy,
                       expected_clock_id: str | None = None) -> TemporalProjection:
    """Select exactly the supplied basis; never convert, clamp, fall back or record.

    An expected clock is a binding check, not a clock-selection request.
    Late-event reconciliation and pause semantics belong to future orchestration.
    """
    if type(event) is not ObservationEvent:
        raise TypeError('observation_event_required')
    if type(timing_policy) is not ObservationTimingPolicy:
        raise TypeError('explicit_timing_policy_required')
    if expected_clock_id is not None:
        _text(expected_clock_id, 'expected_clock_id')
    if timing_policy.basis is TimestampBasis.SOURCE:
        if event.source_stamp is None:
            raise ValueError('source_stamp_required_for_source_basis')
        stamp = event.source_stamp
    else:
        stamp = event.receipt_stamp
    if expected_clock_id is not None and stamp.clock_id != expected_clock_id:
        raise ValueError('selected_clock_mismatch')
    return TemporalProjection(event.event_id, event.timeline_id, event.source.source_id,
                              event.refs, stamp.clock_id, stamp.tick,
                              timing_policy.policy_id, timing_policy.basis)
