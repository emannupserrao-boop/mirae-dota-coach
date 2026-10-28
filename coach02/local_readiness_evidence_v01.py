"""Atomic local resource predicates and bounded transitions; no action feasibility."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math

from .farm_cadence_evidence_v01 import (SemanticInputPresence,
                                      project_semantic_runtime_input_v1)

RULESET = 'resource.local_readiness.v1'
PREDICATE = 'resource.active_ability_observable.v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _identity(kind, value):
    return RULESET + ':' + kind + ':' + hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identifier_required')


def _number(value):
    try: return type(value) in (int, float) and math.isfinite(value)
    except OverflowError: return False


class LocalReadinessStatus(str, Enum):
    READY = 'READY'
    NOT_READY = 'NOT_READY'
    INDETERMINATE = 'INDETERMINATE'


class ItemPresenceStatus(str, Enum):
    PRESENT = 'PRESENT'
    NOT_REPORTED = 'NOT_REPORTED'
    INDETERMINATE = 'INDETERMINATE'


class LocalReadinessReason(str, Enum):
    ALL_OBSERVABLE_REQUIREMENTS_SATISFIED = 'ALL_OBSERVABLE_REQUIREMENTS_SATISFIED'
    OBSERVABLE_REQUIREMENT_UNSATISFIED = 'OBSERVABLE_REQUIREMENT_UNSATISFIED'
    NO_CURRENT_SNAPSHOT = 'NO_CURRENT_SNAPSHOT'
    SCOPE_INELIGIBLE = 'SCOPE_INELIGIBLE'
    FIELD_UNAVAILABLE = 'FIELD_UNAVAILABLE'
    PAUSED = 'PAUSED'
    COLLECTION_UNAVAILABLE = 'COLLECTION_UNAVAILABLE'
    COLLECTION_INVALID = 'COLLECTION_INVALID'
    IDENTITY_NOT_REPORTED = 'IDENTITY_NOT_REPORTED'
    IDENTITY_AMBIGUOUS = 'IDENTITY_AMBIGUOUS'
    NESTED_FIELD_INVALID = 'NESTED_FIELD_INVALID'
    ACTIVE_CLASSIFICATION_UNKNOWN = 'ACTIVE_CLASSIFICATION_UNKNOWN'
    RESOURCE_NOT_ACTIVE = 'RESOURCE_NOT_ACTIVE'
    ITEM_REPORTED = 'ITEM_REPORTED'
    ITEM_NOT_REPORTED = 'ITEM_NOT_REPORTED'


@dataclass(frozen=True)
class LocalReadinessPolicyV1:
    policy_id: str
    ability_selectors: tuple[str, ...]
    item_selectors: tuple[str, ...]
    hero_selector: str | None = None
    predicate_id: str = PREDICATE
    max_receipt_gap_ns: int = 5_000_000_000

    def __post_init__(self):
        _text(self.policy_id)
        if self.hero_selector is not None: _text(self.hero_selector)
        if self.predicate_id != PREDICATE:
            raise ValueError('unsupported_local_predicate')
        if type(self.max_receipt_gap_ns) is not int or self.max_receipt_gap_ns <= 0:
            raise ValueError('positive_readiness_continuity_bound_required')
        for values in (self.ability_selectors, self.item_selectors):
            if type(values) is not tuple or len(values) > 32 or len(set(values)) != len(values):
                raise ValueError('finite_unique_exact_selector_tuple_required')
            for value in values: _text(value)


@dataclass(frozen=True)
class AbilityAvailabilityEvidenceV1:
    query_identity: str
    status: LocalReadinessStatus
    reason: LocalReadinessReason
    matching_slots: tuple[str, ...]
    observed_fields_json: str
    runtime_snapshot_id: str | None
    payload_id: str | None
    evaluated_at_tick: int
    policy_id: str
    source_id: str | None
    observation_event_id: str | None
    temporal_projection_id: str | None
    temporal_snapshot_id: str | None
    evidence_refs: tuple[str, ...]

    @property
    def evidence_id(self): return _identity('ability', asdict(self))


@dataclass(frozen=True)
class ItemPresenceEvidenceV1:
    query_identity: str
    status: ItemPresenceStatus
    reason: LocalReadinessReason
    matching_slots: tuple[str, ...]
    observed_fields_json: str
    runtime_snapshot_id: str | None
    payload_id: str | None
    evaluated_at_tick: int
    policy_id: str
    source_id: str | None
    observation_event_id: str | None
    temporal_projection_id: str | None
    temporal_snapshot_id: str | None
    evidence_refs: tuple[str, ...]

    @property
    def evidence_id(self): return _identity('item', asdict(self))


@dataclass(frozen=True)
class LocalReadinessSnapshotV1:
    run_id: str
    session_id: str | None
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    receipt_elapsed_ns: int
    receive_sequence: int
    hero: str | None
    input_presence: SemanticInputPresence
    eligible_scope: bool
    runtime_snapshot_id: str | None
    payload_id: str | None
    policy: LocalReadinessPolicyV1
    abilities: tuple[AbilityAvailabilityEvidenceV1, ...]
    items: tuple[ItemPresenceEvidenceV1, ...]
    ruleset: str = RULESET

    @property
    def snapshot_id(self): return _identity('snapshot', asdict(self))


@dataclass(frozen=True)
class ReadinessTransitionV1:
    resource_kind: str
    query_identity: str
    previous_status: LocalReadinessStatus | ItemPresenceStatus
    current_status: LocalReadinessStatus | ItemPresenceStatus
    previous_evidence_id: str
    current_evidence_id: str
    previous_tick: int
    current_tick: int
    run_id: str
    session_id: str
    timeline_id: str
    selected_clock_id: str
    hero: str
    policy_id: str

    @property
    def transition_id(self): return _identity('transition', asdict(self))


@dataclass(frozen=True)
class LocalReadinessStateV1:
    policy: LocalReadinessPolicyV1
    last_snapshot: LocalReadinessSnapshotV1 | None = None
    run_id: str | None = None
    evaluated_at_tick: int | None = None
    ruleset: str = RULESET

    def __post_init__(self):
        if type(self.policy) is not LocalReadinessPolicyV1 or self.ruleset != RULESET:
            raise ValueError('exact_readiness_policy_ruleset_required')
        self.policy.__post_init__()
        if self.run_id is not None: _text(self.run_id)
        if self.evaluated_at_tick is not None and (type(self.evaluated_at_tick) is not int or self.evaluated_at_tick < 0):
            raise ValueError('valid_readiness_tick_required')
        if self.last_snapshot is not None:
            s = self.last_snapshot
            if (type(s) is not LocalReadinessSnapshotV1 or not s.eligible_scope
                    or s.ruleset != RULESET or s.policy != self.policy or s.run_id != self.run_id
                    or self.evaluated_at_tick is None or s.evaluated_at_tick > self.evaluated_at_tick):
                raise ValueError('invalid_readiness_memory')
            if tuple(r.query_identity for r in s.abilities) != self.policy.ability_selectors or tuple(r.query_identity for r in s.items) != self.policy.item_selectors:
                raise ValueError('memory_policy_query_mismatch')

    @property
    def state_id(self): return _identity('state', asdict(self))


@dataclass(frozen=True)
class LocalReadinessUpdateV1:
    next_state: LocalReadinessStateV1
    snapshot: LocalReadinessSnapshotV1
    transitions: tuple[ReadinessTransitionV1, ...]


def _scope(view, data, policy):
    if view.input_presence is SemanticInputPresence.ABSENT:
        return False, LocalReadinessReason.NO_CURRENT_SNAPSHOT
    if (view.session_id is None or not view.hero or data['local'] is not True
            or data['phase'] != 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS'
            or policy.hero_selector is not None and view.hero != policy.hero_selector):
        return False, LocalReadinessReason.SCOPE_INELIGIBLE
    if not {'local','hero','phase','paused','alive'}.issubset(view.valid_fields):
        return False, LocalReadinessReason.FIELD_UNAVAILABLE
    if type(data['paused']) is not bool or type(data['alive']) is not bool:
        return False, LocalReadinessReason.FIELD_UNAVAILABLE
    if data['paused']:
        return False, LocalReadinessReason.PAUSED
    return True, None


def _matches(view, data, group, query):
    if group not in view.valid_fields:
        return (), {}, LocalReadinessReason.COLLECTION_UNAVAILABLE
    collection = data[group]
    if type(collection) is not dict or any(type(v) is not dict or type(v.get('name')) is not str or not v['name'].strip() for v in collection.values()):
        return (), {}, LocalReadinessReason.COLLECTION_INVALID
    matches = tuple(sorted(k for k,v in collection.items() if v['name'] == query))
    values = {k: collection[k] for k in matches}
    if len(matches) > 1:
        return matches, values, LocalReadinessReason.IDENTITY_AMBIGUOUS
    return matches, values, None


def _ability(view, data, query, eligible, reason, policy):
    slots, observed = (), {}
    status = LocalReadinessStatus.INDETERMINATE
    if eligible:
        slots, observed, reason = _matches(view, data, 'abilities', query)
        if reason is None and not slots:
            reason = LocalReadinessReason.IDENTITY_NOT_REPORTED
        elif reason is None:
            value = observed[slots[0]]
            level, cooldown, can_cast = (value.get(f) for f in ('level','cooldown','can_cast'))
            flags = tuple(value[f] for f in ('passive','is_passive') if f in value)
            if not flags or any(type(f) is not bool for f in flags) or len(set(flags)) != 1:
                reason = LocalReadinessReason.ACTIVE_CLASSIFICATION_UNKNOWN
            elif flags[0]:
                reason = LocalReadinessReason.RESOURCE_NOT_ACTIVE
            elif (not _number(level) or level < 0 or int(level) != level
                    or not _number(cooldown) or cooldown < 0 or type(can_cast) is not bool):
                reason = LocalReadinessReason.NESTED_FIELD_INVALID
            elif not {'abilities.cooldown','abilities.can_cast'}.issubset(view.valid_fields):
                reason = LocalReadinessReason.FIELD_UNAVAILABLE
            elif data['alive'] and level > 0 and cooldown == 0 and can_cast:
                status, reason = LocalReadinessStatus.READY, LocalReadinessReason.ALL_OBSERVABLE_REQUIREMENTS_SATISFIED
            else:
                status, reason = LocalReadinessStatus.NOT_READY, LocalReadinessReason.OBSERVABLE_REQUIREMENT_UNSATISFIED
    refs = tuple('abilities.' + slot + '.' + field for slot in slots for field in sorted(observed[slot]))
    return AbilityAvailabilityEvidenceV1(query, status, reason, slots, _json(observed),
        view.runtime_snapshot_id, view.payload_id, view.evaluated_at_tick, policy.policy_id,
        view.source_id, view.observation_event_id, view.temporal_projection_id,
        view.temporal_snapshot_id, refs)


def _item(view, data, query, eligible, reason, policy):
    slots, observed = (), {}
    status = ItemPresenceStatus.INDETERMINATE
    if eligible:
        slots, observed, reason = _matches(view, data, 'items', query)
        if reason is None:
            status = ItemPresenceStatus.PRESENT if slots else ItemPresenceStatus.NOT_REPORTED
            reason = LocalReadinessReason.ITEM_REPORTED if slots else LocalReadinessReason.ITEM_NOT_REPORTED
    refs = tuple('items.' + slot + '.' + field for slot in slots for field in sorted(observed[slot]))
    return ItemPresenceEvidenceV1(query, status, reason, slots, _json(observed),
        view.runtime_snapshot_id, view.payload_id, view.evaluated_at_tick, policy.policy_id,
        view.source_id, view.observation_event_id, view.temporal_projection_id,
        view.temporal_snapshot_id, refs)


def _build(view, policy):
    data = json.loads(view.normalized_state_json) if view.normalized_state_json is not None else {}
    eligible, reason = _scope(view, data, policy)
    return LocalReadinessSnapshotV1(view.run_id, view.session_id, view.timeline_id,
        view.selected_clock_id, view.evaluated_at_tick, view.receipt_elapsed_ns,
        view.receive_sequence, view.hero, view.input_presence, eligible,
        view.runtime_snapshot_id, view.payload_id, policy,
        tuple(_ability(view,data,q,eligible,reason,policy) for q in policy.ability_selectors),
        tuple(_item(view,data,q,eligible,reason,policy) for q in policy.item_selectors))


def build_local_readiness_snapshot_v1(*, runtime_result, policy):
    if type(policy) is not LocalReadinessPolicyV1: raise TypeError('exact_readiness_policy_required')
    policy.__post_init__()
    return _build(project_semantic_runtime_input_v1(runtime_result=runtime_result), policy)


def new_local_readiness_state_v1(*, policy):
    return LocalReadinessStateV1(policy)


def advance_local_readiness_v1(*, previous_state, runtime_result, policy):
    if type(previous_state) is not LocalReadinessStateV1 or type(policy) is not LocalReadinessPolicyV1:
        raise TypeError('exact_readiness_contracts_required')
    previous_state.__post_init__(); policy.__post_init__()
    view = project_semantic_runtime_input_v1(runtime_result=runtime_result)
    unchanged_rejection = (view.input_presence is SemanticInputPresence.ABSENT
        and view.continuity_broken and view.evaluated_at_tick == previous_state.evaluated_at_tick)
    if previous_state.run_id == view.run_id and previous_state.evaluated_at_tick is not None and view.evaluated_at_tick <= previous_state.evaluated_at_tick and not unchanged_rejection:
        raise ValueError('nonincreasing_readiness_tick')
    current = _build(view,policy)
    previous = previous_state.last_snapshot if previous_state.policy == policy else None
    required = {'local','hero','phase','paused','alive'}
    if policy.ability_selectors: required.update(('abilities','abilities.cooldown','abilities.can_cast'))
    if policy.item_selectors: required.add('items')
    def lineage(s): return (s.run_id,s.session_id,s.timeline_id,s.selected_clock_id,s.hero)
    broken = (view.continuity_broken or previous is not None and
        (lineage(previous) != lineage(current)
         or current.receipt_elapsed_ns - previous.receipt_elapsed_ns > policy.max_receipt_gap_ns))
    transitions = []
    if previous is not None and not broken and current.eligible_scope:
        for kind, old_rows, rows in (('ability',previous.abilities,current.abilities),('item',previous.items,current.items)):
            for old,row in zip(old_rows,rows):
                if old.query_identity != row.query_identity: raise ValueError('transition_query_mismatch')
                if old.status != row.status:
                    transitions.append(ReadinessTransitionV1(kind,row.query_identity,old.status,
                        row.status,old.evidence_id,row.evidence_id,previous.evaluated_at_tick,
                        current.evaluated_at_tick,current.run_id,current.session_id,
                        current.timeline_id,current.selected_clock_id,current.hero,policy.policy_id))
    if current.input_presence is SemanticInputPresence.PRESENT:
        remembered = current if current.eligible_scope else None
    else:
        remembered = previous if not broken and required.issubset(view.fresh_fields) else None
    state = LocalReadinessStateV1(policy,remembered,view.run_id,view.evaluated_at_tick)
    return LocalReadinessUpdateV1(state,current,tuple(transitions))
