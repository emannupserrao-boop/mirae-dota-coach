"""Pure receipt-clock evidence reducer. No decisions, IO, output or game control."""
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json
import math

from coach.state import State, normalize
from .observation_event import (ObservationSource, ClockStamp, ObservationEvent,
                                ObservationTimingPolicy, TimestampBasis,
                                TemporalProjection, project_event_time)
from .temporal_evidence import (TemporalTrackerState, TemporalSnapshot,
                               FreshnessPolicy, TemporalQuery, new_temporal_state,
                               record_observations, evaluate_freshness)

RULESET = 'runtime.live_evidence.v1'
SCHEMA = 'gsi.local_projection.v1'
SANITIZATION = 'gsi.allowlist.v1'
IN_PROGRESS = 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS'


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def identity(kind, value):
    return RULESET + ':' + kind + ':' + hashlib.sha256(
        canonical_json(value).encode('utf-8')).hexdigest()


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('opaque_nonblank_string_required')


def _tick(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative_concrete_integer_required')


class RuntimeInputKind(str, Enum):
    RECEIVED = 'RECEIVED'
    REJECTED = 'REJECTED'
    TIME_ADVANCE = 'TIME_ADVANCE'
    RESET = 'RESET'
    SHUTDOWN = 'SHUTDOWN'


class RuntimeUpdateStatus(str, Enum):
    ACCEPTED = 'ACCEPTED'
    REJECTED = 'REJECTED'
    CONTROL = 'CONTROL'
    ERROR = 'ERROR'


class RuntimeUpdateReason(str, Enum):
    RECEIVED = 'RECEIVED'
    INVALID_JSON = 'INVALID_JSON'
    INVALID_SHAPE = 'INVALID_SHAPE'
    INVALID_AUTH = 'INVALID_AUTH'
    INVALID_SIZE = 'INVALID_SIZE'
    INVALID_TRANSPORT = 'INVALID_TRANSPORT'
    INVALID_PATH = 'INVALID_PATH'
    OUT_OF_ORDER = 'OUT_OF_ORDER'
    OPTIONAL_ABSENT = 'OPTIONAL_ABSENT'
    OPTIONAL_INVALID = 'OPTIONAL_INVALID'
    UNSUPPORTED_FIELD = 'UNSUPPORTED_FIELD'
    SESSION_START = 'SESSION_START'
    SESSION_END = 'SESSION_END'
    PAUSE = 'PAUSE'
    RESUME = 'RESUME'
    REWIND = 'REWIND'
    GAP = 'GAP'
    TIMELINE_RESET = 'TIMELINE_RESET'
    TIME_ADVANCE = 'TIME_ADVANCE'
    SHUTDOWN = 'SHUTDOWN'
    INTERNAL_ERROR = 'INTERNAL_ERROR'


class RuntimeCapabilitySupport(str, Enum):
    SUPPORTED = 'SUPPORTED'
    UNSUPPORTED = 'UNSUPPORTED'


class RuntimeFieldPresence(str, Enum):
    PRESENT = 'PRESENT'
    ABSENT = 'ABSENT'


class RuntimeFieldValidity(str, Enum):
    VALID = 'VALID'
    INVALID = 'INVALID'
    NOT_ASSESSED = 'NOT_ASSESSED'


@dataclass(frozen=True)
class LiveRuntimePolicyV1:
    policy_id: str
    gap_after_ns: int
    freshness_policy_id: str
    max_age_ns: int
    schema_id: str = SCHEMA
    sanitization_version: str = SANITIZATION

    def __post_init__(self):
        _text(self.policy_id)
        _text(self.freshness_policy_id)
        _tick(self.gap_after_ns)
        _tick(self.max_age_ns)
        if self.schema_id != SCHEMA or self.sanitization_version != SANITIZATION:
            raise ValueError('unsupported_runtime_schema')


@dataclass(frozen=True)
class RuntimeInputV1:
    kind: RuntimeInputKind
    receipt_elapsed_ns: int
    receive_sequence: int | None = None
    sanitized_payload_json: str | None = None
    rejection_reason: RuntimeUpdateReason | None = None

    def __post_init__(self):
        if type(self.kind) is not RuntimeInputKind:
            raise TypeError('explicit_input_kind_required')
        _tick(self.receipt_elapsed_ns)
        post = self.kind in (RuntimeInputKind.RECEIVED, RuntimeInputKind.REJECTED)
        if post:
            _tick(self.receive_sequence)
            if self.receive_sequence == 0:
                raise ValueError('positive_receive_sequence_required')
        elif self.receive_sequence is not None:
            raise ValueError('control_cannot_consume_receive_sequence')
        if self.kind is RuntimeInputKind.RECEIVED:
            if type(self.sanitized_payload_json) is not str:
                raise TypeError('immutable_payload_json_required')
            value = json.loads(self.sanitized_payload_json)
            if type(value) is not dict or canonical_json(value) != self.sanitized_payload_json:
                raise ValueError('canonical_payload_required')
            if canonical_json(sanitize_gsi_payload_v1(payload=value)) != self.sanitized_payload_json:
                raise ValueError('unsanitized_payload')
            if self.rejection_reason is not None:
                raise ValueError('received_cannot_have_rejection_reason')
        elif self.sanitized_payload_json is not None:
            raise ValueError('unsafe_or_control_payload_prohibited')
        if self.kind is RuntimeInputKind.REJECTED:
            if self.rejection_reason not in REJECTION_REASONS:
                raise ValueError('explicit_rejection_classification_required')
        elif self.rejection_reason is not None:
            raise ValueError('unexpected_rejection_classification')


REJECTION_REASONS = frozenset((RuntimeUpdateReason.INVALID_JSON,
                              RuntimeUpdateReason.INVALID_SHAPE,
                              RuntimeUpdateReason.INVALID_AUTH,
                              RuntimeUpdateReason.INVALID_SIZE,
                              RuntimeUpdateReason.INVALID_TRANSPORT,
                              RuntimeUpdateReason.INVALID_PATH))


@dataclass(frozen=True)
class RuntimeCapabilityV1:
    field_id: str
    support: RuntimeCapabilitySupport
    presence: RuntimeFieldPresence
    validity: RuntimeFieldValidity
    source_paths: tuple[str, ...]

    def __post_init__(self):
        _text(self.field_id)
        for value, cls in ((self.support, RuntimeCapabilitySupport),
                           (self.presence, RuntimeFieldPresence),
                           (self.validity, RuntimeFieldValidity)):
            if type(value) is not cls:
                raise TypeError('explicit_capability_axis_required')
        if type(self.source_paths) is not tuple:
            raise TypeError('source_path_tuple_required')
        for path in self.source_paths:
            _text(path)
        if len(set(self.source_paths)) != len(self.source_paths):
            raise ValueError('duplicate_source_path')
        if (self.presence is RuntimeFieldPresence.ABSENT or
                self.support is RuntimeCapabilitySupport.UNSUPPORTED):
            if self.validity is not RuntimeFieldValidity.NOT_ASSESSED:
                raise ValueError('unassessed_capability_required')


@dataclass(frozen=True)
class LiveRuntimeStateV1:
    run_id: str
    policy: LiveRuntimePolicyV1
    session_ordinal: int
    session_id: str | None
    timeline_ordinal: int
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int | None
    last_receipt_elapsed_ns: int | None
    receive_sequence: int
    last_valid_receipt_elapsed_ns: int | None
    last_source_match_time: int | float | None
    known_match_id: str | None
    known_hero: str | None
    paused: bool | None
    temporal_state: TemporalTrackerState
    gap_open: bool
    shutdown: bool
    ruleset: str = RULESET

    def __post_init__(self):
        _text(self.run_id)
        if type(self.policy) is not LiveRuntimePolicyV1 or self.ruleset != RULESET:
            raise ValueError('runtime_policy_ruleset_mismatch')
        for value in (self.session_ordinal, self.timeline_ordinal, self.receive_sequence):
            _tick(value)
        for value in (self.evaluated_at_tick, self.last_receipt_elapsed_ns,
                      self.last_valid_receipt_elapsed_ns):
            if value is not None:
                _tick(value)
        if self.timeline_id != self.run_id + '/timeline/' + str(self.timeline_ordinal):
            raise ValueError('timeline_lineage_mismatch')
        if self.selected_clock_id != self.run_id + '/clock/receipt-ns/v1':
            raise ValueError('receipt_clock_lineage_mismatch')
        if self.session_id is not None and self.session_id != self.run_id + '/session/' + str(self.session_ordinal):
            raise ValueError('session_lineage_mismatch')
        if type(self.temporal_state) is not TemporalTrackerState:
            raise TypeError('temporal_tracker_required')
        if (self.temporal_state.timeline_id, self.temporal_state.clock_id) != (self.timeline_id, self.selected_clock_id):
            raise ValueError('tracker_lineage_mismatch')
        if type(self.gap_open) is not bool or type(self.shutdown) is not bool:
            raise TypeError('concrete_state_flags_required')
        if self.paused is not None and type(self.paused) is not bool:
            raise TypeError('concrete_pause_memory_required')
        for value in (self.known_match_id, self.known_hero):
            if value is not None:
                _text(value)
        if self.last_source_match_time is not None and not _finite(self.last_source_match_time):
            raise ValueError('finite_source_time_required')
        if any(mark.ref not in FIELD_IDS for mark in self.temporal_state.marks):
            raise ValueError('unbounded_or_foreign_temporal_ref')
        if (self.temporal_state.last_tick is not None and
                (self.evaluated_at_tick is None or self.temporal_state.last_tick > self.evaluated_at_tick)):
            raise ValueError('future_tracker_tick')

    @property
    def state_id(self):
        return identity('state', asdict(self))


@dataclass(frozen=True)
class LiveRuntimeSnapshotV1:
    ruleset: str
    run_id: str
    session_id: str | None
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    receive_sequence: int
    payload_id: str
    source_match_time: int | float | None
    provider_timestamp: int | float | None
    normalized_state_json: str
    capabilities: tuple[RuntimeCapabilityV1, ...]

    def __post_init__(self):
        if self.ruleset != RULESET:
            raise ValueError('snapshot_ruleset_mismatch')
        for value in (self.run_id, self.timeline_id, self.selected_clock_id, self.payload_id):
            _text(value)
        if self.session_id is not None:
            _text(self.session_id)
        _tick(self.evaluated_at_tick)
        _tick(self.receive_sequence)
        for value in (self.source_match_time, self.provider_timestamp):
            if value is not None and not _finite(value):
                raise ValueError('finite_snapshot_metadata_required')
        if type(self.normalized_state_json) is not str:
            raise TypeError('immutable_normalized_json_required')
        value = json.loads(self.normalized_state_json)
        if type(value) is not dict or set(value) != set(State.__dataclass_fields__) or canonical_json(value) != self.normalized_state_json:
            raise ValueError('exact_state_projection_required')
        if type(self.capabilities) is not tuple or any(type(c) is not RuntimeCapabilityV1 for c in self.capabilities):
            raise TypeError('immutable_capability_tuple_required')
        if tuple(c.field_id for c in self.capabilities) != FIELD_IDS:
            raise ValueError('finite_catalog_required')

    @property
    def snapshot_id(self):
        return identity('snapshot', asdict(self))


@dataclass(frozen=True)
class RuntimeUpdateResultV1:
    status: RuntimeUpdateStatus
    reason_codes: tuple[RuntimeUpdateReason, ...]
    next_state: LiveRuntimeStateV1
    snapshot: LiveRuntimeSnapshotV1 | None = None
    observation_event: ObservationEvent | None = None
    temporal_projection: TemporalProjection | None = None
    temporal_snapshot: TemporalSnapshot | None = None

    def __post_init__(self):
        if type(self.status) is not RuntimeUpdateStatus or type(self.next_state) is not LiveRuntimeStateV1:
            raise TypeError('exact_update_contract_required')
        if type(self.reason_codes) is not tuple or any(type(r) is not RuntimeUpdateReason for r in self.reason_codes):
            raise TypeError('typed_reason_tuple_required')
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError('duplicate_update_reason')
        for value, contract in ((self.snapshot, LiveRuntimeSnapshotV1),
                                (self.observation_event, ObservationEvent),
                                (self.temporal_projection, TemporalProjection),
                                (self.temporal_snapshot, TemporalSnapshot)):
            if value is not None and type(value) is not contract:
                raise TypeError('exact_optional_update_contract_required')
        if self.status is RuntimeUpdateStatus.ACCEPTED:
            if any(v is None for v in (self.snapshot, self.observation_event, self.temporal_projection, self.temporal_snapshot)):
                raise ValueError('accepted_evidence_required')
        elif any(v is not None for v in (self.snapshot, self.observation_event, self.temporal_projection)):
            raise ValueError('nonaccepted_cannot_refresh_evidence')


# Tuple catalog: field ID, raw group/key, validation kind. Fixed cardinality.
FIELD_CATALOG = (
    ('match_id', 'map', 'matchid', 'id'), ('time', 'map', 'clock_time', 'number'),
    ('phase', 'map', 'game_state', 'text'), ('paused', 'map', 'paused', 'bool'),
    ('local', 'player', 'team_name', 'scope'), ('hero', 'hero', 'name', 'text'),
    ('level', 'hero', 'level', 'number'), ('kills', 'player', 'kills', 'number'),
    ('deaths', 'player', 'deaths', 'number'), ('assists', 'player', 'assists', 'number'),
    ('lh', 'player', 'last_hits', 'number'), ('denies', 'player', 'denies', 'number'),
    ('gold', 'player', 'gold', 'number'), ('gpm', 'player', 'gpm', 'number'),
    ('xpm', 'player', 'xpm', 'number'), ('buyback_cost', 'hero', 'buyback_cost', 'number'),
    ('buyback_cooldown', 'hero', 'buyback_cooldown', 'number'),
    ('alive', 'hero', 'alive', 'bool'), ('items', '', 'items', 'collection'),
    ('abilities', '', 'abilities', 'collection'),
    ('provider_timestamp', 'provider', 'timestamp', 'number'),
)
SLOT_FIELDS = ('name', 'level', 'cooldown', 'can_cast', 'is_passive',
               'ability_active', 'ultimate', 'charges', 'passive', 'purchaser')
UNSUPPORTED_FIELDS = ('health', 'max_health', 'mana', 'max_mana', 'enemy_positions')
FIELD_IDS = tuple(row[0] for row in FIELD_CATALOG) + (
    'items.cooldown', 'items.can_cast', 'abilities.cooldown', 'abilities.can_cast',
) + UNSUPPORTED_FIELDS


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def sanitize_gsi_payload_v1(*, payload):
    """Copy a finite allowlist; preserve scope nesting, never credentials/PII.

    This is a raw subset, not normalization. The IO owner must prove full State
    parity with the original while the original is transiently in memory.
    """
    if type(payload) is not dict:
        raise ValueError('gsi_object_required')
    canonical_json(payload)  # reject nonfinite anywhere, including dropped fields
    result = {}
    groups = (
        ('provider', ('appid', 'timestamp')),
        ('map', ('matchid', 'clock_time', 'game_state', 'paused')),
        ('player', ('team_name', 'activity', 'kills', 'deaths', 'assists', 'last_hits', 'denies', 'gold', 'gpm', 'xpm')),
        ('hero', ('name', 'level', 'alive', 'buyback_cost', 'buyback_cooldown', 'health', 'max_health', 'mana', 'max_mana')),
    )
    for group, keys in groups:
        if group not in payload:
            continue
        raw = payload[group]
        if type(raw) is not dict:
            result[group] = json.loads(canonical_json(raw))
            continue
        result[group] = {key: json.loads(canonical_json(raw[key])) for key in keys if key in raw}
        if group == 'player':
            for key, value in raw.items():
                if str(key).startswith(('team', 'player')) and isinstance(value, dict):
                    # Do not retain names/Steam IDs inside spectator structures.
                    result[group][key] = {}
    for group, prefixes in (('items', ('slot', 'stash', 'teleport', 'neutral')),
                            ('abilities', ('ability',))):
        if group not in payload:
            continue
        raw = payload[group]
        if type(raw) is not dict:
            result[group] = json.loads(canonical_json(raw))
            continue
        result[group] = {
            key: {field: json.loads(canonical_json(value[field])) for field in SLOT_FIELDS if field in value}
            for key, value in raw.items() if str(key).startswith(prefixes) and type(value) is dict
        }
    return result


def _valid(value, kind):
    if kind == 'number':
        return _finite(value)
    if kind == 'bool':
        return type(value) is bool
    if kind == 'text':
        return type(value) is str and bool(value.strip())
    if kind == 'id':
        return (type(value) is str and bool(value.strip())) or (type(value) is int and value > 0)
    if kind == 'scope':
        return value in ('radiant', 'dire')
    return type(value) is dict


def _capabilities(payload, normalized):
    values = []
    for field, group, key, kind in FIELD_CATALOG:
        owner = payload.get(group, {}) if group else payload
        owner = owner if type(owner) is dict else {}
        present = key in owner
        valid = present and _valid(owner[key], kind)
        if field == 'local':
            present = present and type(payload.get('hero')) is dict and 'name' in payload['hero']
            valid = present and normalized.local
        elif field in ('hero', 'level', 'kills', 'deaths', 'assists', 'lh', 'denies',
                       'gold', 'gpm', 'xpm', 'buyback_cost', 'buyback_cooldown', 'alive', 'items', 'abilities'):
            valid = valid and normalized.local
        paths = ((group + '.' if group else '') + key,)
        if field == 'local':
            paths = ('player.team_name', 'player.activity', 'hero.name', 'player.team*/player*')
        values.append(RuntimeCapabilityV1(field, RuntimeCapabilitySupport.SUPPORTED,
                      RuntimeFieldPresence.PRESENT if present else RuntimeFieldPresence.ABSENT,
                      RuntimeFieldValidity.VALID if valid else RuntimeFieldValidity.INVALID if present else RuntimeFieldValidity.NOT_ASSESSED,
                      paths))
    for group in ('items', 'abilities'):
        slots = payload.get(group, {})
        for field in ('cooldown', 'can_cast'):
            paths = tuple(group + '.' + key + '.' + field for key, value in sorted(slots.items())
                          if type(value) is dict and field in value) if type(slots) is dict else ()
            present = bool(paths)
            valid = present and normalized.local and all(
                _valid(value[field], 'number' if field == 'cooldown' else 'bool')
                for value in slots.values() if type(value) is dict and field in value)
            values.append(RuntimeCapabilityV1(group + '.' + field, RuntimeCapabilitySupport.SUPPORTED,
                          RuntimeFieldPresence.PRESENT if present else RuntimeFieldPresence.ABSENT,
                          RuntimeFieldValidity.VALID if valid else RuntimeFieldValidity.INVALID if present else RuntimeFieldValidity.NOT_ASSESSED,
                          paths))
    hero = payload.get('hero', {})
    for field in UNSUPPORTED_FIELDS:
        present = type(hero) is dict and field in hero
        values.append(RuntimeCapabilityV1(field, RuntimeCapabilitySupport.UNSUPPORTED,
                      RuntimeFieldPresence.PRESENT if present else RuntimeFieldPresence.ABSENT,
                      RuntimeFieldValidity.NOT_ASSESSED, ('hero.' + field,)))
    return tuple(values)


def new_live_runtime_state_v1(*, run_id, policy):
    _text(run_id)
    if type(policy) is not LiveRuntimePolicyV1:
        raise TypeError('explicit_runtime_policy_required')
    timeline = run_id + '/timeline/0'
    clock = run_id + '/clock/receipt-ns/v1'
    return LiveRuntimeStateV1(run_id, policy, 0, None, 0, timeline, clock,
                              None, None, 0, None, None, None, None, None,
                              new_temporal_state(timeline, clock), False, False)


def _reset(state):
    ordinal = state.timeline_ordinal + 1
    timeline = state.run_id + '/timeline/' + str(ordinal)
    return replace(state, timeline_ordinal=ordinal, timeline_id=timeline,
                   temporal_state=new_temporal_state(timeline, state.selected_clock_id))


def _freshness(state, tick, policy):
    return evaluate_freshness(state.temporal_state, tick,
                             tuple(TemporalQuery(field, FreshnessPolicy(policy.freshness_policy_id,
                                   policy.max_age_ns)) for field in FIELD_IDS))


def advance_live_runtime_v1(*, previous_state, runtime_input, policy):
    if type(previous_state) is not LiveRuntimeStateV1 or type(runtime_input) is not RuntimeInputV1:
        raise TypeError('exact_runtime_contracts_required')
    if type(policy) is not LiveRuntimePolicyV1 or policy != previous_state.policy:
        raise ValueError('runtime_policy_mismatch')
    previous_state.__post_init__()
    runtime_input.__post_init__()
    old, inp = previous_state, runtime_input
    if old.shutdown:
        raise ValueError('runtime_already_shutdown')
    post = inp.kind in (RuntimeInputKind.RECEIVED, RuntimeInputKind.REJECTED)
    if ((old.last_receipt_elapsed_ns is not None and inp.receipt_elapsed_ns < old.last_receipt_elapsed_ns)
            or post and inp.receive_sequence != old.receive_sequence + 1):
        return RuntimeUpdateResultV1(RuntimeUpdateStatus.REJECTED,
                                     (RuntimeUpdateReason.OUT_OF_ORDER,), old)
    tick = max(inp.receipt_elapsed_ns, 0 if old.evaluated_at_tick is None else old.evaluated_at_tick + 1)
    state = replace(old, evaluated_at_tick=tick, last_receipt_elapsed_ns=inp.receipt_elapsed_ns,
                    receive_sequence=inp.receive_sequence if post else old.receive_sequence)
    if inp.kind is RuntimeInputKind.REJECTED:
        return RuntimeUpdateResultV1(RuntimeUpdateStatus.REJECTED, (inp.rejection_reason,), state)
    if not post:
        state = replace(state, temporal_state=record_observations(state.temporal_state, (), tick))
        temporal = _freshness(state, tick, policy)
        reasons = [RuntimeUpdateReason.TIME_ADVANCE]
        if inp.kind is RuntimeInputKind.RESET:
            state = _reset(state)
            state = replace(state, last_source_match_time=None, gap_open=False,
                            last_valid_receipt_elapsed_ns=None)
            reasons = [RuntimeUpdateReason.TIMELINE_RESET]
        elif inp.kind is RuntimeInputKind.SHUTDOWN:
            state = replace(state, shutdown=True)
            reasons = [RuntimeUpdateReason.SHUTDOWN]
        elif (not state.gap_open and state.last_valid_receipt_elapsed_ns is not None and
              inp.receipt_elapsed_ns - state.last_valid_receipt_elapsed_ns > policy.gap_after_ns):
            state = replace(_reset(state), gap_open=True, last_source_match_time=None)
            reasons.extend((RuntimeUpdateReason.GAP, RuntimeUpdateReason.TIMELINE_RESET))
        # At gap/reset this explicitly describes the closing timeline, before
        # its empty replacement; it never refreshes an occurrence.
        return RuntimeUpdateResultV1(RuntimeUpdateStatus.CONTROL, tuple(reasons), state,
                                     temporal_snapshot=temporal)
    payload = json.loads(inp.sanitized_payload_json)
    try:
        normalized = normalize(payload)
        normalized_json = canonical_json(normalized.to_dict())
    except (ValueError, TypeError, RecursionError):
        return RuntimeUpdateResultV1(RuntimeUpdateStatus.REJECTED,
                                     (RuntimeUpdateReason.INVALID_SHAPE,), state)
    reasons = [RuntimeUpdateReason.RECEIVED]
    m, p, h = (payload.get(key, {}) for key in ('map', 'player', 'hero'))
    m, p, h = (value if type(value) is dict else {} for value in (m, p, h))
    match = str(m['matchid']) if 'matchid' in m and _valid(m['matchid'], 'id') and str(m['matchid']) != '0' else None
    hero = normalized.hero if normalized.local and normalized.hero.strip() else None
    qualifies = normalized.local and bool(hero) and m.get('game_state') == IN_PROGRESS
    explicit_exit = (('game_state' in m and type(m['game_state']) is str and m['game_state'] != IN_PROGRESS)
                     or ('activity' in p and type(p['activity']) is str and p['activity'] != 'playing')
                     or ('team_name' in p and type(p['team_name']) is str and p['team_name'] not in ('radiant', 'dire'))
                     or any(str(key).startswith(('team', 'player')) and type(value) is dict for key, value in p.items()))
    changed = (match is not None and old.known_match_id is not None and match != old.known_match_id
               or hero is not None and old.known_hero is not None and hero != old.known_hero)
    reset = False
    if old.session_id is not None and (explicit_exit or changed):
        state = replace(state, session_id=None, known_match_id=None, known_hero=None,
                        paused=None, last_source_match_time=None)
        reasons.append(RuntimeUpdateReason.SESSION_END)
        reset = True
    if state.session_id is None and qualifies:
        ordinal = state.session_ordinal + 1
        state = replace(state, session_ordinal=ordinal, session_id=state.run_id + '/session/' + str(ordinal))
        reasons.append(RuntimeUpdateReason.SESSION_START)
        reset = True
    if (not reset and normalized.time is not None and state.last_source_match_time is not None
            and normalized.time < state.last_source_match_time):
        reasons.append(RuntimeUpdateReason.REWIND)
        reset = True
    if reset:
        state = _reset(state)
        reasons.append(RuntimeUpdateReason.TIMELINE_RESET)
    if type(m.get('paused')) is bool:
        if state.paused is not None and state.paused != m['paused']:
            reasons.append(RuntimeUpdateReason.PAUSE if m['paused'] else RuntimeUpdateReason.RESUME)
        state = replace(state, paused=m['paused'])
    if state.session_id is not None:
        state = replace(state, known_match_id=match or state.known_match_id,
                        known_hero=hero or state.known_hero)
    state = replace(state, last_valid_receipt_elapsed_ns=inp.receipt_elapsed_ns,
                    last_source_match_time=normalized.time if normalized.time is not None else state.last_source_match_time,
                    gap_open=False)
    capabilities = _capabilities(payload, normalized)
    if any(c.presence is RuntimeFieldPresence.ABSENT and c.support is RuntimeCapabilitySupport.SUPPORTED for c in capabilities):
        reasons.append(RuntimeUpdateReason.OPTIONAL_ABSENT)
    if any(c.validity is RuntimeFieldValidity.INVALID for c in capabilities):
        reasons.append(RuntimeUpdateReason.OPTIONAL_INVALID)
    if any(c.support is RuntimeCapabilitySupport.UNSUPPORTED and c.presence is RuntimeFieldPresence.PRESENT for c in capabilities):
        reasons.append(RuntimeUpdateReason.UNSUPPORTED_FIELD)
    timestamp = payload.get('provider', {}).get('timestamp') if type(payload.get('provider')) is dict else None
    snapshot = LiveRuntimeSnapshotV1(RULESET, state.run_id, state.session_id, state.timeline_id,
               state.selected_clock_id, tick, state.receive_sequence, identity('payload', payload),
               normalized.time, timestamp if _finite(timestamp) else None, normalized_json, capabilities)
    refs = tuple(c.field_id for c in capabilities if c.support is RuntimeCapabilitySupport.SUPPORTED
                 and c.presence is RuntimeFieldPresence.PRESENT and c.validity is RuntimeFieldValidity.VALID)
    event = ObservationEvent(state.timeline_id, ObservationSource(state.run_id + '/gsi', 'gsi', SCHEMA),
                             refs, ClockStamp(state.selected_clock_id, tick))
    projection = project_event_time(event, ObservationTimingPolicy(policy.policy_id + '/receipt',
                                   TimestampBasis.RECEIPT), state.selected_clock_id)
    state = replace(state, temporal_state=record_observations(state.temporal_state, projection.refs, projection.selected_tick))
    return RuntimeUpdateResultV1(RuntimeUpdateStatus.ACCEPTED, tuple(reasons), state,
                                 snapshot, event, projection, _freshness(state, tick, policy))
