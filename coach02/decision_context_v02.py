"""Explicit cross-domain assembly of accepted objects at one aligned instant."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .strategic_objective_context import StrategicObjectiveSnapshot, StrategicObjectiveAssessment
from .option_safety_v02 import OptionSafetySnapshotV2, OptionSafetyEvaluationV2
from .option_outcome_evidence import OptionOutcomeSnapshot, OptionOutcomeEvidence


RULESET = 'decision.context.v2'


class DecisionEvidencePresence(str, Enum):
    PRESENT = 'PRESENT'
    ABSENT = 'ABSENT'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _nullable_text(value):
    if value is not None:
        _text(value)


def _validate_binding(binding):
    for value in (binding.option_id, binding.risk_context_id, binding.outcome_context_id,
                  binding.outcome_baseline_id, binding.outcome_horizon_id):
        _text(value)
    _nullable_text(binding.safety_context_id)


@dataclass(frozen=True)
class DecisionOptionBindingV2:
    option_id: str
    risk_context_id: str
    safety_context_id: str | None
    outcome_context_id: str
    outcome_baseline_id: str
    outcome_horizon_id: str

    def __post_init__(self):
        _validate_binding(self)


def _validate_request(request):
    for value in (request.decision_context_id, request.objective_context_id,
                  request.objective_horizon_id, request.context_binding_policy_id):
        _text(value)
    if type(request.option_bindings) is not tuple:
        raise TypeError('exact_binding_tuple_required')
    seen = set()
    for binding in request.option_bindings:
        if type(binding) is not DecisionOptionBindingV2:
            raise TypeError('exact_option_binding_required')
        _validate_binding(binding)
        if binding.option_id in seen:
            raise ValueError('duplicate_option_binding')
        seen.add(binding.option_id)


@dataclass(frozen=True)
class DecisionContextRequestV2:
    decision_context_id: str
    objective_context_id: str
    objective_horizon_id: str
    context_binding_policy_id: str
    option_bindings: tuple[DecisionOptionBindingV2, ...]

    def __post_init__(self):
        _validate_request(self)


@dataclass(frozen=True)
class OptionDecisionContextV2:
    option_id: str
    risk_context_id: str
    safety_context_id: str | None
    outcome_context_id: str
    outcome_baseline_id: str
    outcome_horizon_id: str
    safety_presence: DecisionEvidencePresence
    safety_evaluation: OptionSafetyEvaluationV2 | None
    outcome_presence: DecisionEvidencePresence
    outcome_evidences: tuple[OptionOutcomeEvidence, ...]
    base_binding: DecisionOptionBindingV2


@dataclass(frozen=True)
class DecisionContextV2:
    decision_context_id: str
    timeline_id: str
    selected_clock_id: str
    decision_assembly_tick: int
    context_binding_policy_id: str
    objective_context_id: str
    objective_horizon_id: str
    objective_presence: DecisionEvidencePresence
    objective_assessment: StrategicObjectiveAssessment | None
    strategic_objective_snapshot_id: str
    option_safety_snapshot_id: str
    option_outcome_snapshot_id: str
    options: tuple[OptionDecisionContextV2, ...]
    base_request: DecisionContextRequestV2
    ruleset: str

    @property
    def context_id(self) -> str:
        content = asdict(self)
        # Normalize only the hash copy; retain the original request and bindings.
        content['base_request']['option_bindings'] = sorted(
            content['base_request']['option_bindings'], key=lambda b: b['option_id'])
        encoded = json.dumps(content, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':context:' + hashlib.sha256(encoded).hexdigest()


def _header(snapshot, tick):
    _text(snapshot.timeline_id)
    _text(snapshot.selected_clock_id)
    if type(tick) is not int:
        raise TypeError('concrete_integer_tick_required')
    if tick < 0:
        raise ValueError('negative_assembly_tick')
    return (snapshot.timeline_id, snapshot.selected_clock_id, tick)


def _index(rows, kind, key_fields):
    if type(rows) is not tuple:
        raise TypeError('exact_upstream_row_tuple_required')
    index = {}
    for row in rows:
        if type(row) is not kind:
            raise TypeError('exact_upstream_row_required')
        key = tuple(getattr(row, name) for name in key_fields)
        for value in key:
            _text(value)
        if key in index:
            raise ValueError('duplicate_upstream_key')
        index[key] = row
    return index


def _presence(exists):
    return DecisionEvidencePresence.PRESENT if exists else DecisionEvidencePresence.ABSENT


def build_decision_context_v2(
        *, strategic_objective_snapshot: StrategicObjectiveSnapshot,
        option_safety_snapshot: OptionSafetySnapshotV2,
        option_outcome_snapshot: OptionOutcomeSnapshot,
        request: DecisionContextRequestV2,
) -> DecisionContextV2:
    """Bind exact selectors and preserve objects; presence never judges candidates."""
    if type(strategic_objective_snapshot) is not StrategicObjectiveSnapshot:
        raise TypeError('exact_strategic_objective_snapshot_required')
    if type(option_safety_snapshot) is not OptionSafetySnapshotV2:
        raise TypeError('exact_option_safety_snapshot_required')
    if type(option_outcome_snapshot) is not OptionOutcomeSnapshot:
        raise TypeError('exact_option_outcome_snapshot_required')
    if type(request) is not DecisionContextRequestV2:
        raise TypeError('exact_decision_context_request_required')
    _validate_request(request)
    objective = strategic_objective_snapshot
    safety = option_safety_snapshot
    outcome = option_outcome_snapshot
    header = _header(objective, objective.evaluated_at_tick)
    if (header != _header(safety, safety.risk_assembly_tick)
            or header != _header(outcome, outcome.evaluated_at_tick)):
        raise ValueError('DECISION_CONTEXT_V02_EXACT_ALIGNMENT_RULE')
    objectives = _index(objective.assessments, StrategicObjectiveAssessment,
                        ('objective_context_id', 'horizon_id'))
    evaluations = _index(safety.evaluations, OptionSafetyEvaluationV2,
                         ('risk_context_id', 'option_id'))
    outcomes = _index(outcome.evidences, OptionOutcomeEvidence,
                     ('option_id', 'outcome_context_id', 'dimension_id', 'baseline_id', 'horizon_id'))
    for row in evaluations.values():
        _nullable_text(row.safety_context_id)
    for row in outcomes.values():
        _text(row.source_id)
        _text(row.assessment_policy_id)
    assessment = objectives.get((request.objective_context_id, request.objective_horizon_id))
    options = []
    for binding in sorted(request.option_bindings, key=lambda b: b.option_id):
        evaluation = evaluations.get((binding.risk_context_id, binding.option_id))
        if evaluation is not None and evaluation.safety_context_id != binding.safety_context_id:
            raise ValueError('safety_context_binding_mismatch')
        evidences = tuple(sorted((row for row in outcomes.values() if
            (row.option_id, row.outcome_context_id, row.baseline_id, row.horizon_id) ==
            (binding.option_id, binding.outcome_context_id,
             binding.outcome_baseline_id, binding.outcome_horizon_id)),
            key=lambda r: (r.dimension_id, r.outcome_context_id, r.baseline_id,
                           r.horizon_id, r.source_id, r.assessment_policy_id)))
        options.append(OptionDecisionContextV2(
            binding.option_id, binding.risk_context_id, binding.safety_context_id,
            binding.outcome_context_id, binding.outcome_baseline_id, binding.outcome_horizon_id,
            _presence(evaluation is not None), evaluation, _presence(bool(evidences)),
            evidences, binding))
    return DecisionContextV2(
        request.decision_context_id, *header, request.context_binding_policy_id,
        request.objective_context_id, request.objective_horizon_id,
        _presence(assessment is not None), assessment, objective.snapshot_id,
        safety.snapshot_id, outcome.snapshot_id, tuple(options), request, RULESET)
