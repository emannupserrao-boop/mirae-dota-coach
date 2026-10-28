"""Pure stabilization of accepted selection, without action or execution."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .decision_arbiter_v01 import (
    DecisionArbiterResultV1, DecisionArbiterStatus,
    ArbiterCandidateAdmissionStatus, ArbiterCandidateAssessmentV1,
)
from .decision_context_v02 import OptionDecisionContextV2


RULESET = 'selection.hysteresis.v1'


class SelectionHysteresisStatus(str, Enum):
    SELECTED = 'SELECTED'
    NO_SELECTION = 'NO_SELECTION'
    INDETERMINATE = 'INDETERMINATE'


class SelectionHysteresisReason(str, Enum):
    INITIAL_SELECTION = 'INITIAL_SELECTION'
    UNCHANGED_SELECTION = 'UNCHANGED_SELECTION'
    HELD_PREVIOUS_NO_SELECTION = 'HELD_PREVIOUS_NO_SELECTION'
    SWITCH_PENDING_MINIMUM_HOLD = 'SWITCH_PENDING_MINIMUM_HOLD'
    SWITCH_PENDING_CONFIRMATION = 'SWITCH_PENDING_CONFIRMATION'
    SWITCH_CONFIRMED = 'SWITCH_CONFIRMED'
    PREVIOUS_OPTION_EXCLUDED = 'PREVIOUS_OPTION_EXCLUDED'
    PREVIOUS_OPTION_ABSENT = 'PREVIOUS_OPTION_ABSENT'
    CURRENT_ARBITER_INDETERMINATE = 'CURRENT_ARBITER_INDETERMINATE'
    NO_CURRENT_SELECTION = 'NO_CURRENT_SELECTION'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _policy_values(value):
    _text(value.hysteresis_context_id)
    _text(value.switch_policy_id)
    _tick(value.minimum_hold_ticks)
    _tick(value.challenger_confirmation_ticks)
    return (value.hysteresis_context_id, value.switch_policy_id,
            value.minimum_hold_ticks, value.challenger_confirmation_ticks)


@dataclass(frozen=True)
class SelectionHysteresisPolicyV1:
    hysteresis_context_id: str
    switch_policy_id: str
    minimum_hold_ticks: int
    challenger_confirmation_ticks: int

    def __post_init__(self):
        _policy_values(self)


def _arbiter(result):
    if type(result) is not DecisionArbiterResultV1:
        raise TypeError('exact_arbiter_result_required')
    if type(result.ruleset) is not str or result.ruleset != 'decision.arbiter.v1':
        raise ValueError('accepted_arbiter_ruleset_required')
    for value in (result.decision_context_id, result.decision_context_object_id,
                  result.feasibility_snapshot_id, result.pairwise_snapshot_id,
                  result.timeline_id, result.selected_clock_id):
        _text(value)
    _tick(result.evaluated_at_tick)
    if type(result.status) is not DecisionArbiterStatus:
        raise TypeError('exact_arbiter_status_required')
    if type(result.candidate_assessments) is not tuple or type(result.considered_pairwise_evidence) is not tuple:
        raise TypeError('exact_arbiter_tuples_required')
    rows = {}
    for row in result.candidate_assessments:
        if type(row) is not ArbiterCandidateAssessmentV1:
            raise TypeError('exact_candidate_assessment_required')
        _text(row.option_id)
        if row.option_id in rows:
            raise ValueError('duplicate_candidate_option')
        if type(row.admission_status) is not ArbiterCandidateAdmissionStatus:
            raise TypeError('exact_admission_status_required')
        if type(row.base_option_context) is not OptionDecisionContextV2:
            raise TypeError('exact_current_option_required')
        if row.base_option_context.option_id != row.option_id or type(row.base_option_context.option_id) is not str:
            raise ValueError('candidate_option_identity_mismatch')
        rows[row.option_id] = row
    if result.status is not DecisionArbiterStatus.INDETERMINATE and any(
            row.admission_status is ArbiterCandidateAdmissionStatus.INDETERMINATE for row in rows.values()):
        raise ValueError('unresolved_admission_requires_indeterminate')
    if result.status is DecisionArbiterStatus.SELECTED:
        _text(result.selected_option_id)
        selected = rows.get(result.selected_option_id)
        if (selected is None or selected.admission_status is not ArbiterCandidateAdmissionStatus.ADMITTED
                or result.selected_option is not selected.base_option_context):
            raise ValueError('selected_current_admitted_member_required')
    elif result.selected_option_id is not None or result.selected_option is not None:
        raise ValueError('unselected_arbiter_requires_none')
    return rows


def _state(value):
    if type(value) is not SelectionHysteresisStateV1:
        raise TypeError('exact_hysteresis_state_required')
    _policy_values(value)
    if type(value.ruleset) is not str or value.ruleset != RULESET:
        raise ValueError('accepted_hysteresis_ruleset_required')
    for identity in (value.timeline_id, value.selected_clock_id, value.current_arbiter_result_id):
        _text(identity)
    _tick(value.evaluated_at_tick)
    if type(value.status) is not SelectionHysteresisStatus or type(value.reason) is not SelectionHysteresisReason:
        raise TypeError('exact_hysteresis_enums_required')
    rows = _arbiter(value.current_arbiter_result)
    current = value.current_arbiter_result
    if (value.timeline_id, value.selected_clock_id, value.evaluated_at_tick) != (
            current.timeline_id, current.selected_clock_id, current.evaluated_at_tick):
        raise ValueError('state_arbiter_header_mismatch')
    if value.current_arbiter_result_id != current.result_id:
        raise ValueError('state_arbiter_identity_mismatch')
    if value.previous_state_id is not None:
        _text(value.previous_state_id)
        prefix = RULESET + ':state:'
        suffix = value.previous_state_id[len(prefix):]
        if not value.previous_state_id.startswith(prefix) or len(suffix) != 64 or any(c not in '0123456789abcdef' for c in suffix):
            raise ValueError('previous_state_identity_format')
    for identity, tick in ((value.remembered_option_id, value.remembered_since_tick),
                           (value.pending_challenger_option_id, value.pending_challenger_since_tick)):
        if (identity is None) != (tick is None):
            raise ValueError('complete_optional_pair_required')
        if identity is not None:
            _text(identity)
            _tick(tick)
            if tick > value.evaluated_at_tick:
                raise ValueError('state_timestamp_in_future')
    remembered = rows.get(value.remembered_option_id)
    if value.remembered_option_id is not None and (
            remembered is None or remembered.admission_status is ArbiterCandidateAdmissionStatus.EXCLUDED):
        raise ValueError('invalidated_memory_cannot_survive')
    if value.status is SelectionHysteresisStatus.SELECTED:
        _text(value.effective_selected_option_id)
        selected = rows.get(value.effective_selected_option_id)
        if (current.status is DecisionArbiterStatus.INDETERMINATE or selected is None
                or selected.admission_status is not ArbiterCandidateAdmissionStatus.ADMITTED
                or value.effective_selected_option is not selected.base_option_context
                or value.remembered_option_id != value.effective_selected_option_id):
            raise ValueError('effective_current_admitted_memory_required')
    elif value.effective_selected_option_id is not None or value.effective_selected_option is not None:
        raise ValueError('unselected_state_requires_none')
    if (current.status is DecisionArbiterStatus.INDETERMINATE) != (value.status is SelectionHysteresisStatus.INDETERMINATE):
        raise ValueError('current_indeterminacy_must_be_exposed')
    if value.status is SelectionHysteresisStatus.NO_SELECTION and value.remembered_option_id is not None:
        raise ValueError('no_selection_requires_no_memory')
    if value.pending_challenger_option_id is not None:
        if (value.status is not SelectionHysteresisStatus.SELECTED or remembered is None
                or remembered.admission_status is not ArbiterCandidateAdmissionStatus.ADMITTED
                or value.pending_challenger_option_id == value.remembered_option_id
                or current.status is not DecisionArbiterStatus.SELECTED
                or current.selected_option_id != value.pending_challenger_option_id):
            raise ValueError('current_distinct_selected_challenger_required')


@dataclass(frozen=True)
class SelectionHysteresisStateV1:
    hysteresis_context_id: str
    switch_policy_id: str
    minimum_hold_ticks: int
    challenger_confirmation_ticks: int
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    remembered_option_id: str | None
    remembered_since_tick: int | None
    effective_selected_option_id: str | None
    effective_selected_option: OptionDecisionContextV2 | None
    pending_challenger_option_id: str | None
    pending_challenger_since_tick: int | None
    status: SelectionHysteresisStatus
    reason: SelectionHysteresisReason
    current_arbiter_result_id: str
    current_arbiter_result: DecisionArbiterResultV1
    previous_state_id: str | None
    ruleset: str

    def __post_init__(self):
        _state(self)

    @property
    def state_id(self) -> str:
        content = {name: getattr(self, name) for name in (
            'hysteresis_context_id', 'switch_policy_id', 'minimum_hold_ticks',
            'challenger_confirmation_ticks', 'timeline_id', 'selected_clock_id',
            'evaluated_at_tick', 'remembered_option_id', 'remembered_since_tick',
            'effective_selected_option_id', 'pending_challenger_option_id',
            'pending_challenger_since_tick', 'status', 'reason', 'previous_state_id', 'ruleset')}
        content['current_arbiter_result_id'] = self.current_arbiter_result.result_id
        encoded = json.dumps(content, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':state:' + hashlib.sha256(encoded).hexdigest()


def build_selection_hysteresis_state_v1(
        *, current_arbiter_result: DecisionArbiterResultV1,
        policy: SelectionHysteresisPolicyV1,
        previous_state: SelectionHysteresisStateV1 | None,
) -> SelectionHysteresisStateV1:
    """Validate consumed boundaries, then apply the fixed stabilization transition."""
    rows = _arbiter(current_arbiter_result)
    if type(policy) is not SelectionHysteresisPolicyV1:
        raise TypeError('exact_hysteresis_policy_required')
    policy_values = _policy_values(policy)
    current = current_arbiter_result
    tick = current.evaluated_at_tick
    if previous_state is not None:
        _state(previous_state)
        if _policy_values(previous_state) != policy_values:
            raise ValueError('same_policy_chain_required')
        if (previous_state.timeline_id, previous_state.selected_clock_id) != (current.timeline_id, current.selected_clock_id):
            raise ValueError('same_clock_domain_required')
        if tick <= previous_state.evaluated_at_tick:
            raise ValueError('strict_tick_progression_required')
    remembered = None if previous_state is None else previous_state.remembered_option_id
    since = None if previous_state is None else previous_state.remembered_since_tick
    pending = None
    pending_since = None
    effective = None
    status = SelectionHysteresisStatus(current.status.value)
    invalidation = None
    if remembered is not None:
        if remembered not in rows:
            invalidation = SelectionHysteresisReason.PREVIOUS_OPTION_ABSENT
        elif rows[remembered].admission_status is ArbiterCandidateAdmissionStatus.EXCLUDED:
            invalidation = SelectionHysteresisReason.PREVIOUS_OPTION_EXCLUDED
    if invalidation is not None or remembered is None:
        remembered = current.selected_option_id
        since = None if remembered is None else tick
        effective = remembered
        reason = invalidation or (
            SelectionHysteresisReason.INITIAL_SELECTION if effective is not None else
            SelectionHysteresisReason.CURRENT_ARBITER_INDETERMINATE if current.status is DecisionArbiterStatus.INDETERMINATE else
            SelectionHysteresisReason.NO_CURRENT_SELECTION)
    elif current.status is DecisionArbiterStatus.INDETERMINATE:
        reason = SelectionHysteresisReason.CURRENT_ARBITER_INDETERMINATE
    elif current.status is DecisionArbiterStatus.NO_SELECTION:
        effective = remembered
        status = SelectionHysteresisStatus.SELECTED
        reason = SelectionHysteresisReason.HELD_PREVIOUS_NO_SELECTION
    elif current.selected_option_id == remembered:
        effective = remembered
        reason = SelectionHysteresisReason.UNCHANGED_SELECTION
    else:
        pending = current.selected_option_id
        pending_since = (previous_state.pending_challenger_since_tick
                         if previous_state.pending_challenger_option_id == pending else tick)
        effective = remembered
        if tick - since < policy.minimum_hold_ticks:
            reason = SelectionHysteresisReason.SWITCH_PENDING_MINIMUM_HOLD
        elif tick - pending_since < policy.challenger_confirmation_ticks:
            reason = SelectionHysteresisReason.SWITCH_PENDING_CONFIRMATION
        else:
            effective = remembered = pending
            since = tick
            pending = pending_since = None
            reason = SelectionHysteresisReason.SWITCH_CONFIRMED
    return SelectionHysteresisStateV1(
        *policy_values, current.timeline_id, current.selected_clock_id, tick,
        remembered, since, effective, None if effective is None else rows[effective].base_option_context,
        pending, pending_since, status, reason, current.result_id, current,
        None if previous_state is None else previous_state.state_id, RULESET)
