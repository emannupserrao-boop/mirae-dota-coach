"""Caller-registered execution observations; no action or selection authority."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .selection_hysteresis_v01 import (
    SelectionHysteresisStateV1,
    SelectionHysteresisStatus,
)


RULESET = 'execution.lifecycle.v1'


class ExecutionLifecyclePhase(str, Enum):
    NOT_STARTED = 'NOT_STARTED'
    IN_PROGRESS = 'IN_PROGRESS'
    COMPLETED = 'COMPLETED'
    ABORTED = 'ABORTED'
    EXPIRED = 'EXPIRED'


class ExecutionKnowledgeStatus(str, Enum):
    KNOWN = 'KNOWN'
    INDETERMINATE = 'INDETERMINATE'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _refs(value):
    if type(value) is not tuple:
        raise TypeError('exact_evidence_tuple_required')
    for ref in value:
        _text(ref)
    if len(set(value)) != len(value):
        raise ValueError('duplicate_evidence_reference')


def _identity(value, prefix):
    _text(value)
    suffix = value[len(prefix):]
    if not value.startswith(prefix) or len(suffix) != 64 or any(c not in '0123456789abcdef' for c in suffix):
        raise ValueError('identity_format')


def _digest(kind, payload):
    content = dict(payload, ruleset=RULESET)
    encoded = json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return RULESET + ':' + kind + ':' + hashlib.sha256(encoded).hexdigest()


def _binding(value):
    if type(value) is not ExecutionLifecycleBindingV1:
        raise TypeError('exact_execution_binding_required')
    for name in ('execution_context_id', 'execution_instance_id', 'option_id',
                 'hysteresis_state_id', 'source_id', 'binding_policy_id'):
        _text(getattr(value, name))
    _identity(value.hysteresis_state_id, 'selection.hysteresis.v1:state:')
    _tick(value.basis_tick)
    _refs(value.evidence_refs)


@dataclass(frozen=True)
class ExecutionLifecycleBindingV1:
    execution_context_id: str
    execution_instance_id: str
    option_id: str
    hysteresis_state_id: str
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    binding_policy_id: str

    def __post_init__(self):
        _binding(self)

    @property
    def binding_id(self) -> str:
        return _digest('binding', {name: getattr(self, name) for name in (
            'execution_context_id', 'execution_instance_id', 'option_id',
            'hysteresis_state_id', 'basis_tick', 'source_id', 'evidence_refs', 'binding_policy_id')})


def _observation(value):
    if type(value) is not ExecutionLifecycleObservationV1:
        raise TypeError('exact_execution_observation_required')
    for name in ('execution_context_id', 'execution_instance_id', 'option_id',
                 'timeline_id', 'selected_clock_id', 'source_id', 'assessment_policy_id'):
        _text(getattr(value, name))
    _tick(value.basis_tick)
    _refs(value.evidence_refs)
    if type(value.knowledge_status) is not ExecutionKnowledgeStatus:
        raise TypeError('exact_execution_knowledge_required')
    if value.knowledge_status is ExecutionKnowledgeStatus.KNOWN:
        if type(value.phase) is not ExecutionLifecyclePhase:
            raise TypeError('known_observation_requires_exact_phase')
    elif value.phase is not None:
        raise ValueError('indeterminate_observation_requires_none')


@dataclass(frozen=True)
class ExecutionLifecycleObservationV1:
    execution_context_id: str
    execution_instance_id: str
    option_id: str
    timeline_id: str
    selected_clock_id: str
    basis_tick: int
    knowledge_status: ExecutionKnowledgeStatus
    phase: ExecutionLifecyclePhase | None
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _observation(self)

    @property
    def observation_id(self) -> str:
        return _digest('observation', {name: getattr(self, name) for name in (
            'execution_context_id', 'execution_instance_id', 'option_id',
            'timeline_id', 'selected_clock_id', 'basis_tick', 'knowledge_status',
            'phase', 'source_id', 'evidence_refs', 'assessment_policy_id')})


def _hysteresis(value):
    """Revalidate the consumed public selection boundary, without recalculating selection."""
    if type(value) is not SelectionHysteresisStateV1:
        raise TypeError('exact_hysteresis_state_required')
    if type(value.ruleset) is not str or value.ruleset != 'selection.hysteresis.v1':
        raise ValueError('accepted_hysteresis_ruleset_required')
    for name in ('hysteresis_context_id', 'switch_policy_id', 'timeline_id',
                 'selected_clock_id', 'current_arbiter_result_id'):
        _text(getattr(value, name))
    for name in ('evaluated_at_tick', 'minimum_hold_ticks', 'challenger_confirmation_ticks'):
        _tick(getattr(value, name))
    if type(value.status) is not SelectionHysteresisStatus:
        raise TypeError('exact_hysteresis_status_required')
    current = value.current_arbiter_result
    if (value.timeline_id, value.selected_clock_id, value.evaluated_at_tick) != (
            current.timeline_id, current.selected_clock_id, current.evaluated_at_tick):
        raise ValueError('hysteresis_current_header_mismatch')
    if value.current_arbiter_result_id != current.result_id:
        raise ValueError('hysteresis_current_identity_mismatch')
    if value.status is SelectionHysteresisStatus.SELECTED:
        _text(value.effective_selected_option_id)
        if value.remembered_option_id != value.effective_selected_option_id:
            raise ValueError('hysteresis_effective_memory_mismatch')
        if value.effective_selected_option is None or value.effective_selected_option.option_id != value.effective_selected_option_id:
            raise ValueError('hysteresis_selected_option_mismatch')
        if not any(row.option_id == value.effective_selected_option_id and
                   row.base_option_context is value.effective_selected_option
                   for row in current.candidate_assessments):
            raise ValueError('hysteresis_current_option_required')
    elif value.effective_selected_option_id is not None or value.effective_selected_option is not None:
        raise ValueError('unselected_hysteresis_requires_none')
    _identity(value.state_id, 'selection.hysteresis.v1:state:')


def _terminal(phase):
    return phase in (ExecutionLifecyclePhase.COMPLETED, ExecutionLifecyclePhase.ABORTED,
                     ExecutionLifecyclePhase.EXPIRED)


def _observation_binding(value, binding, timeline, clock, tick):
    _observation(value)
    if (value.execution_context_id, value.execution_instance_id, value.option_id) != (
            binding.execution_context_id, binding.execution_instance_id, binding.option_id):
        raise ValueError('observation_instance_mismatch')
    if (value.timeline_id, value.selected_clock_id, value.basis_tick) != (timeline, clock, tick):
        raise ValueError('observation_current_header_mismatch')


def _registration(binding, current):
    if (current.status is not SelectionHysteresisStatus.SELECTED
            or binding.option_id != current.effective_selected_option_id
            or binding.hysteresis_state_id != current.state_id
            or binding.basis_tick != current.evaluated_at_tick):
        raise ValueError('explicit_current_selected_registration_required')


def _state(value):
    if type(value) is not ExecutionLifecycleStateV1:
        raise TypeError('exact_execution_state_required')
    _binding(value.base_binding)
    _hysteresis(value.current_hysteresis_state)
    if type(value.ruleset) is not str or value.ruleset != RULESET:
        raise ValueError('accepted_execution_ruleset_required')
    _text(value.timeline_id)
    _text(value.selected_clock_id)
    for name in ('evaluated_at_tick', 'last_known_phase_recorded_at_tick', 'last_known_phase_observed_at_tick'):
        _tick(getattr(value, name))
    if type(value.last_known_phase) is not ExecutionLifecyclePhase or type(value.knowledge_status) is not ExecutionKnowledgeStatus:
        raise TypeError('exact_execution_state_enums_required')
    current = value.current_hysteresis_state
    if (value.timeline_id, value.selected_clock_id, value.evaluated_at_tick) != (
            current.timeline_id, current.selected_clock_id, current.evaluated_at_tick):
        raise ValueError('execution_hysteresis_header_mismatch')
    if not (value.base_binding.basis_tick <= value.last_known_phase_recorded_at_tick
            <= value.last_known_phase_observed_at_tick <= value.evaluated_at_tick):
        raise ValueError('execution_timestamp_order')
    if value.last_known_phase is ExecutionLifecyclePhase.NOT_STARTED:
        if value.last_known_phase_recorded_at_tick != value.base_binding.basis_tick:
            raise ValueError('not_started_recorded_at_registration')
    elif value.last_known_phase_recorded_at_tick <= value.base_binding.basis_tick:
        raise ValueError('post_registration_phase_required')
    if value.previous_state_id is None:
        _registration(value.base_binding, current)
        if (value.current_observation is not None or value.last_known_phase is not ExecutionLifecyclePhase.NOT_STARTED
                or value.knowledge_status is not ExecutionKnowledgeStatus.KNOWN
                or value.last_known_phase_observed_at_tick != value.evaluated_at_tick):
            raise ValueError('registration_state_required')
    else:
        _identity(value.previous_state_id, RULESET + ':state:')
        if value.evaluated_at_tick <= value.base_binding.basis_tick:
            raise ValueError('continuation_after_registration_required')
        obs = value.current_observation
        if obs is not None:
            _observation_binding(obs, value.base_binding, value.timeline_id, value.selected_clock_id, value.evaluated_at_tick)
        if obs is not None and obs.knowledge_status is ExecutionKnowledgeStatus.KNOWN:
            if (value.knowledge_status is not ExecutionKnowledgeStatus.KNOWN or value.last_known_phase is not obs.phase
                    or value.last_known_phase_observed_at_tick != value.evaluated_at_tick):
                raise ValueError('known_state_observation_mismatch')
        elif (value.knowledge_status is not ExecutionKnowledgeStatus.INDETERMINATE
              or value.last_known_phase_observed_at_tick >= value.evaluated_at_tick):
            raise ValueError('unconfirmed_state_requires_preserved_memory')


@dataclass(frozen=True)
class ExecutionLifecycleStateV1:
    base_binding: ExecutionLifecycleBindingV1
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    last_known_phase: ExecutionLifecyclePhase
    last_known_phase_recorded_at_tick: int
    last_known_phase_observed_at_tick: int
    knowledge_status: ExecutionKnowledgeStatus
    current_hysteresis_state: SelectionHysteresisStateV1
    current_observation: ExecutionLifecycleObservationV1 | None
    previous_state_id: str | None
    ruleset: str

    def __post_init__(self):
        _state(self)

    @property
    def execution_context_id(self) -> str:
        return self.base_binding.execution_context_id

    @property
    def execution_instance_id(self) -> str:
        return self.base_binding.execution_instance_id

    @property
    def option_id(self) -> str:
        return self.base_binding.option_id

    @property
    def binding_id(self) -> str:
        return self.base_binding.binding_id

    @property
    def registered_hysteresis_state_id(self) -> str:
        return self.base_binding.hysteresis_state_id

    @property
    def current_hysteresis_state_id(self) -> str:
        return self.current_hysteresis_state.state_id

    @property
    def current_observation_id(self) -> str | None:
        return None if self.current_observation is None else self.current_observation.observation_id

    @property
    def current_selection_option_id(self) -> str | None:
        if self.current_hysteresis_state.status is SelectionHysteresisStatus.SELECTED:
            return self.current_hysteresis_state.effective_selected_option_id
        return None

    @property
    def selection_matches_execution(self) -> bool | None:
        if self.current_hysteresis_state.status is SelectionHysteresisStatus.INDETERMINATE:
            return None
        return self.current_selection_option_id == self.option_id

    @property
    def effective_phase(self) -> ExecutionLifecyclePhase | None:
        return self.last_known_phase if self.knowledge_status is ExecutionKnowledgeStatus.KNOWN else None

    @property
    def instance_is_terminal(self) -> bool:
        return _terminal(self.last_known_phase)

    @property
    def state_id(self) -> str:
        return _digest('state', {name: getattr(self, name) for name in (
            'binding_id', 'execution_context_id', 'execution_instance_id', 'option_id',
            'timeline_id', 'selected_clock_id', 'evaluated_at_tick', 'last_known_phase',
            'last_known_phase_recorded_at_tick', 'last_known_phase_observed_at_tick',
            'knowledge_status', 'current_hysteresis_state_id', 'current_observation_id', 'previous_state_id')})


def build_execution_lifecycle_state_v1(
        *, current_hysteresis_state: SelectionHysteresisStateV1,
        binding: ExecutionLifecycleBindingV1,
        observation: ExecutionLifecycleObservationV1 | None,
        previous_state: ExecutionLifecycleStateV1 | None,
) -> ExecutionLifecycleStateV1:
    """Register or advance one explicit instance, retaining evidence without authority."""
    _hysteresis(current_hysteresis_state)
    _binding(binding)
    current = current_hysteresis_state
    tick = current.evaluated_at_tick
    if observation is not None:
        _observation_binding(observation, binding, current.timeline_id, current.selected_clock_id, tick)
    if previous_state is None:
        if observation is not None:
            raise ValueError('registration_requires_no_observation')
        _registration(binding, current)
        phase = ExecutionLifecyclePhase.NOT_STARTED
        recorded = observed = tick
        knowledge = ExecutionKnowledgeStatus.KNOWN
        original = binding
    else:
        _state(previous_state)
        if binding != previous_state.base_binding:
            raise ValueError('original_binding_content_required')
        if (current.timeline_id, current.selected_clock_id) != (previous_state.timeline_id, previous_state.selected_clock_id):
            raise ValueError('same_timeline_clock_required')
        if tick <= previous_state.evaluated_at_tick:
            raise ValueError('strict_tick_progression_required')
        original = previous_state.base_binding
        phase = previous_state.last_known_phase
        recorded = previous_state.last_known_phase_recorded_at_tick
        observed = previous_state.last_known_phase_observed_at_tick
        knowledge = ExecutionKnowledgeStatus.INDETERMINATE
        if observation is not None and observation.knowledge_status is ExecutionKnowledgeStatus.KNOWN:
            new_phase = observation.phase
            if (_terminal(phase) and new_phase is not phase
                    or phase is ExecutionLifecyclePhase.IN_PROGRESS and new_phase is ExecutionLifecyclePhase.NOT_STARTED):
                raise ValueError('illegal_execution_transition')
            if new_phase is not phase:
                recorded = tick
            phase = new_phase
            observed = tick
            knowledge = ExecutionKnowledgeStatus.KNOWN
    return ExecutionLifecycleStateV1(
        original, current.timeline_id, current.selected_clock_id, tick,
        phase, recorded, observed, knowledge, current, observation,
        None if previous_state is None else previous_state.state_id, RULESET)
