"""Exact-tick prospective exit-cost evidence, without switching or action authority."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .execution_lifecycle_v01 import (
    ExecutionLifecycleStateV1,
    ExecutionLifecyclePhase,
    ExecutionKnowledgeStatus,
)


RULESET = 'execution.abort_cost.v1'


class ExecutionAbortCostLevel(str, Enum):
    NOT_ESTABLISHED = 'NOT_ESTABLISHED'
    LIMITED = 'LIMITED'
    SUBSTANTIAL = 'SUBSTANTIAL'
    INDETERMINATE = 'INDETERMINATE'


class ExecutionAbortCostPresence(str, Enum):
    PRESENT = 'PRESENT'
    ABSENT = 'ABSENT'


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


def _digest(kind, payload, ruleset=RULESET):
    encoded = json.dumps(dict(payload, ruleset=ruleset), sort_keys=True,
                         separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return ruleset + ':' + kind + ':' + hashlib.sha256(encoded).hexdigest()


def _claim(value):
    if type(value) is not ExecutionAbortCostClaimV1:
        raise TypeError('exact_abort_cost_claim_required')
    for name in ('cost_context_id', 'execution_context_id', 'execution_instance_id',
                 'option_id', 'source_id', 'assessment_policy_id'):
        _text(getattr(value, name))
    _identity(value.lifecycle_state_id, 'execution.lifecycle.v1:state:')
    _tick(value.assessed_at_tick)
    if type(value.abort_cost_level) is not ExecutionAbortCostLevel:
        raise TypeError('exact_abort_cost_level_required')
    _refs(value.evidence_refs)


@dataclass(frozen=True)
class ExecutionAbortCostClaimV1:
    cost_context_id: str
    execution_context_id: str
    execution_instance_id: str
    option_id: str
    lifecycle_state_id: str
    assessed_at_tick: int
    abort_cost_level: ExecutionAbortCostLevel
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _claim(self)

    @property
    def claim_id(self) -> str:
        return _digest('claim', {name: getattr(self, name) for name in (
            'cost_context_id', 'execution_context_id', 'execution_instance_id',
            'option_id', 'lifecycle_state_id', 'assessed_at_tick', 'abort_cost_level',
            'source_id', 'evidence_refs', 'assessment_policy_id')})


def _assessment(value):
    if type(value) is not ExecutionAbortCostAssessmentV1:
        raise TypeError('exact_abort_cost_assessment_required')
    _identity(value.lifecycle_state_id, 'execution.lifecycle.v1:state:')
    _tick(value.assessed_at_tick)
    if (type(value.presence) is not ExecutionAbortCostPresence
            or type(value.conclusion) is not ExecutionAbortCostLevel):
        raise TypeError('exact_abort_cost_assessment_enums_required')
    if value.presence is ExecutionAbortCostPresence.ABSENT:
        if value.base_claim is not None or value.conclusion is not ExecutionAbortCostLevel.INDETERMINATE:
            raise ValueError('absent_cost_requires_indeterminate_without_claim')
    else:
        _claim(value.base_claim)
        if (value.conclusion is not value.base_claim.abort_cost_level
                or value.lifecycle_state_id != value.base_claim.lifecycle_state_id
                or value.assessed_at_tick != value.base_claim.assessed_at_tick):
            raise ValueError('assessment_claim_mismatch')


@dataclass(frozen=True)
class ExecutionAbortCostAssessmentV1:
    lifecycle_state_id: str
    assessed_at_tick: int
    presence: ExecutionAbortCostPresence
    conclusion: ExecutionAbortCostLevel
    base_claim: ExecutionAbortCostClaimV1 | None

    def __post_init__(self):
        _assessment(self)


def _lifecycle(value):
    """Validate the consumed public boundary; do not replay lifecycle transitions."""
    if type(value) is not ExecutionLifecycleStateV1:
        raise TypeError('exact_lifecycle_state_required')
    if type(value.ruleset) is not str or value.ruleset != 'execution.lifecycle.v1':
        raise ValueError('accepted_lifecycle_ruleset_required')
    if type(value.base_binding) is not ExecutionLifecycleStateV1.__annotations__['base_binding']:
        raise TypeError('exact_lifecycle_base_binding_required')
    if type(value.current_hysteresis_state) is not ExecutionLifecycleStateV1.__annotations__['current_hysteresis_state']:
        raise TypeError('exact_lifecycle_current_lineage_required')
    if (value.current_observation is not None and type(value.current_observation)
            is not ExecutionLifecycleStateV1.__annotations__['current_observation'].__args__[0]):
        raise TypeError('exact_lifecycle_observation_required')
    for name in ('execution_context_id', 'execution_instance_id', 'option_id',
                 'timeline_id', 'selected_clock_id'):
        _text(getattr(value, name))
    for name in ('evaluated_at_tick', 'last_known_phase_recorded_at_tick',
                 'last_known_phase_observed_at_tick'):
        _tick(getattr(value, name))
    if (type(value.last_known_phase) is not ExecutionLifecyclePhase
            or type(value.knowledge_status) is not ExecutionKnowledgeStatus):
        raise TypeError('exact_lifecycle_enums_required')
    binding = value.base_binding
    # The accepted State annotation supplies its concrete binding type; no extra domain import.
    if type(binding) is not ExecutionLifecycleStateV1.__annotations__['base_binding']:
        raise TypeError('exact_lifecycle_base_binding_required')
    binding_fields = ('execution_context_id', 'execution_instance_id', 'option_id',
                      'hysteresis_state_id', 'basis_tick', 'source_id', 'evidence_refs', 'binding_policy_id')
    for name in ('execution_context_id', 'execution_instance_id', 'option_id', 'source_id', 'binding_policy_id'):
        _text(getattr(binding, name))
    _tick(binding.basis_tick)
    _refs(binding.evidence_refs)
    _identity(binding.hysteresis_state_id, 'selection.hysteresis.v1:state:')
    expected_binding = _digest('binding', {name: getattr(binding, name) for name in binding_fields},
                               'execution.lifecycle.v1')
    if (value.binding_id != expected_binding or value.binding_id != binding.binding_id
            or value.registered_hysteresis_state_id != binding.hysteresis_state_id
            or (value.execution_context_id, value.execution_instance_id, value.option_id) != (
                binding.execution_context_id, binding.execution_instance_id, binding.option_id)):
        raise ValueError('lifecycle_binding_identity_mismatch')
    if not (binding.basis_tick <= value.last_known_phase_recorded_at_tick
            <= value.last_known_phase_observed_at_tick <= value.evaluated_at_tick):
        raise ValueError('lifecycle_timestamp_order')
    if value.last_known_phase is ExecutionLifecyclePhase.NOT_STARTED:
        if value.last_known_phase_recorded_at_tick != binding.basis_tick:
            raise ValueError('lifecycle_not_started_memory')
    elif value.last_known_phase_recorded_at_tick <= binding.basis_tick:
        raise ValueError('lifecycle_post_registration_memory')
    expected_phase = value.last_known_phase if value.knowledge_status is ExecutionKnowledgeStatus.KNOWN else None
    if value.effective_phase is not expected_phase:
        raise ValueError('lifecycle_effective_phase_mismatch')
    terminal = value.last_known_phase in (ExecutionLifecyclePhase.COMPLETED,
                                        ExecutionLifecyclePhase.ABORTED, ExecutionLifecyclePhase.EXPIRED)
    if type(value.instance_is_terminal) is not bool or value.instance_is_terminal is not terminal:
        raise ValueError('lifecycle_terminal_flag_mismatch')
    if value.knowledge_status is ExecutionKnowledgeStatus.KNOWN:
        if value.last_known_phase_observed_at_tick != value.evaluated_at_tick:
            raise ValueError('lifecycle_known_tick_mismatch')
    elif value.last_known_phase_observed_at_tick >= value.evaluated_at_tick:
        raise ValueError('lifecycle_indeterminate_memory_mismatch')
    _identity(value.current_hysteresis_state_id, 'selection.hysteresis.v1:state:')
    if value.current_observation_id is not None:
        _identity(value.current_observation_id, 'execution.lifecycle.v1:observation:')
    if value.previous_state_id is not None:
        _identity(value.previous_state_id, 'execution.lifecycle.v1:state:')
    current = value.current_hysteresis_state
    if (value.timeline_id, value.selected_clock_id, value.evaluated_at_tick) != (
            current.timeline_id, current.selected_clock_id, current.evaluated_at_tick):
        raise ValueError('lifecycle_current_header_mismatch')
    obs = value.current_observation
    if value.previous_state_id is None:
        if (obs is not None or value.last_known_phase is not ExecutionLifecyclePhase.NOT_STARTED
                or value.knowledge_status is not ExecutionKnowledgeStatus.KNOWN
                or value.evaluated_at_tick != binding.basis_tick):
            raise ValueError('lifecycle_registration_header_mismatch')
    else:
        if value.evaluated_at_tick <= binding.basis_tick:
            raise ValueError('lifecycle_continuation_tick_mismatch')
        if obs is not None:
            if type(obs) is not ExecutionLifecycleStateV1.__annotations__['current_observation'].__args__[0]:
                raise TypeError('exact_lifecycle_observation_required')
            if (obs.execution_context_id, obs.execution_instance_id, obs.option_id,
                    obs.timeline_id, obs.selected_clock_id, obs.basis_tick) != (
                    value.execution_context_id, value.execution_instance_id, value.option_id,
                    value.timeline_id, value.selected_clock_id, value.evaluated_at_tick):
                raise ValueError('lifecycle_observation_header_mismatch')
            if type(obs.knowledge_status) is not ExecutionKnowledgeStatus:
                raise TypeError('exact_lifecycle_observation_knowledge_required')
            for name in ('execution_context_id', 'execution_instance_id', 'option_id',
                         'timeline_id', 'selected_clock_id', 'source_id', 'assessment_policy_id'):
                _text(getattr(obs, name))
            _tick(obs.basis_tick)
            _refs(obs.evidence_refs)
            if obs.knowledge_status is ExecutionKnowledgeStatus.KNOWN:
                if (type(obs.phase) is not ExecutionLifecyclePhase
                        or value.knowledge_status is not ExecutionKnowledgeStatus.KNOWN
                        or value.last_known_phase is not obs.phase):
                    raise ValueError('lifecycle_observation_phase_mismatch')
            elif obs.phase is not None or value.knowledge_status is not ExecutionKnowledgeStatus.INDETERMINATE:
                raise ValueError('lifecycle_indeterminate_observation_mismatch')
        elif value.knowledge_status is not ExecutionKnowledgeStatus.INDETERMINATE:
            raise ValueError('lifecycle_missing_observation_not_known')
    identity_fields = ('binding_id', 'execution_context_id', 'execution_instance_id', 'option_id',
                       'timeline_id', 'selected_clock_id', 'evaluated_at_tick', 'last_known_phase',
                       'last_known_phase_recorded_at_tick', 'last_known_phase_observed_at_tick',
                       'knowledge_status', 'current_hysteresis_state_id', 'current_observation_id', 'previous_state_id')
    _identity(value.state_id, 'execution.lifecycle.v1:state:')
    if value.state_id != _digest('state', {name: getattr(value, name) for name in identity_fields},
                                 'execution.lifecycle.v1'):
        raise ValueError('lifecycle_state_identity_mismatch')
    if terminal:
        raise ValueError('terminal_lifecycle_not_eligible')


def _bind(claim, state):
    if (claim.execution_context_id, claim.execution_instance_id, claim.option_id,
            claim.lifecycle_state_id) != (state.execution_context_id, state.execution_instance_id,
                                         state.option_id, state.state_id):
        raise ValueError('claim_execution_binding_mismatch')
    if claim.assessed_at_tick != state.evaluated_at_tick:
        raise ValueError('claim_exact_tick_required')


def _snapshot(value):
    if type(value) is not ExecutionAbortCostSnapshotV1:
        raise TypeError('exact_abort_cost_snapshot_required')
    if type(value.ruleset) is not str or value.ruleset != RULESET:
        raise ValueError('accepted_abort_cost_ruleset_required')
    _lifecycle(value.base_lifecycle_state)
    row = value.abort_cost_assessment
    _assessment(row)
    if (row.lifecycle_state_id, row.assessed_at_tick) != (
            value.base_lifecycle_state.state_id, value.base_lifecycle_state.evaluated_at_tick):
        raise ValueError('snapshot_assessment_binding_mismatch')
    if row.base_claim is not None:
        _bind(row.base_claim, value.base_lifecycle_state)


@dataclass(frozen=True)
class ExecutionAbortCostSnapshotV1:
    base_lifecycle_state: ExecutionLifecycleStateV1
    abort_cost_assessment: ExecutionAbortCostAssessmentV1
    ruleset: str

    def __post_init__(self):
        _snapshot(self)

    @property
    def lifecycle_state_id(self) -> str:
        return self.base_lifecycle_state.state_id

    @property
    def execution_context_id(self) -> str:
        return self.base_lifecycle_state.execution_context_id

    @property
    def execution_instance_id(self) -> str:
        return self.base_lifecycle_state.execution_instance_id

    @property
    def option_id(self) -> str:
        return self.base_lifecycle_state.option_id

    @property
    def timeline_id(self) -> str:
        return self.base_lifecycle_state.timeline_id

    @property
    def selected_clock_id(self) -> str:
        return self.base_lifecycle_state.selected_clock_id

    @property
    def assessed_at_tick(self) -> int:
        return self.base_lifecycle_state.evaluated_at_tick

    @property
    def snapshot_id(self) -> str:
        payload = {name: getattr(self, name) for name in (
            'lifecycle_state_id', 'execution_context_id', 'execution_instance_id',
            'option_id', 'timeline_id', 'selected_clock_id', 'assessed_at_tick')}
        row = self.abort_cost_assessment
        payload['presence'] = row.presence
        payload['conclusion'] = row.conclusion
        payload['claim_id'] = None if row.base_claim is None else row.base_claim.claim_id
        return _digest('snapshot', payload)


def build_execution_abort_cost_snapshot_v1(
        *, lifecycle_state: ExecutionLifecycleStateV1,
        abort_cost_claim: ExecutionAbortCostClaimV1 | None,
) -> ExecutionAbortCostSnapshotV1:
    """Preserve explicit current prospective cost; never infer a cost or decision."""
    _lifecycle(lifecycle_state)
    if abort_cost_claim is not None:
        _claim(abort_cost_claim)
        _bind(abort_cost_claim, lifecycle_state)
    row = ExecutionAbortCostAssessmentV1(
        lifecycle_state.state_id, lifecycle_state.evaluated_at_tick,
        ExecutionAbortCostPresence.ABSENT if abort_cost_claim is None else ExecutionAbortCostPresence.PRESENT,
        ExecutionAbortCostLevel.INDETERMINATE if abort_cost_claim is None else abort_cost_claim.abort_cost_level,
        abort_cost_claim)
    return ExecutionAbortCostSnapshotV1(lifecycle_state, row, RULESET)
