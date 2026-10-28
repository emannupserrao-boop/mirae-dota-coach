"""Fixed candidate admission and explicit direct-advantage selection only."""
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .decision_context_v02 import DecisionContextV2, OptionDecisionContextV2, DecisionEvidencePresence
from .option_safety_v02 import OptionSafetyEvaluationV2, OptionSafetyGateStatus
from .feasibility_gate_v01 import FeasibilitySnapshotV1, OptionFeasibilityAssessmentV1, FeasibilityGateStatus
from .pairwise_tradeoff_v01 import PairwiseTradeoffSnapshotV1, PairwiseTradeoffEvidenceV1, PairwiseTradeoffConclusion


RULESET = 'decision.arbiter.v1'


class ArbiterCandidateAdmissionStatus(str, Enum):
    ADMITTED = 'ADMITTED'
    EXCLUDED = 'EXCLUDED'
    INDETERMINATE = 'INDETERMINATE'


class DecisionArbiterStatus(str, Enum):
    SELECTED = 'SELECTED'
    NO_SELECTION = 'NO_SELECTION'
    INDETERMINATE = 'INDETERMINATE'


class DecisionArbiterReason(str, Enum):
    SINGLE_ADMITTED_OPTION = 'SINGLE_ADMITTED_OPTION'
    UNIQUE_DIRECT_ADVANTAGE = 'UNIQUE_DIRECT_ADVANTAGE'
    NO_ADMITTED_OPTIONS = 'NO_ADMITTED_OPTIONS'
    NO_UNIQUE_DIRECT_ADVANTAGE = 'NO_UNIQUE_DIRECT_ADVANTAGE'
    CANDIDATE_ADMISSION_INDETERMINATE = 'CANDIDATE_ADMISSION_INDETERMINATE'
    PAIRWISE_EVIDENCE_INCOMPLETE = 'PAIRWISE_EVIDENCE_INCOMPLETE'
    PAIRWISE_EVIDENCE_INDETERMINATE = 'PAIRWISE_EVIDENCE_INDETERMINATE'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _request(request):
    for value in (request.decision_context_id, request.arbiter_context_id, request.pairwise_context_id):
        _text(value)


@dataclass(frozen=True)
class DecisionArbiterRequestV1:
    decision_context_id: str
    arbiter_context_id: str
    pairwise_context_id: str

    def __post_init__(self):
        _request(self)


@dataclass(frozen=True)
class ArbiterCandidateAssessmentV1:
    option_id: str
    admission_status: ArbiterCandidateAdmissionStatus
    safety_presence: DecisionEvidencePresence
    safety_gate_status: OptionSafetyGateStatus | None
    feasibility_status: FeasibilityGateStatus
    base_option_context: OptionDecisionContextV2
    base_feasibility_assessment: OptionFeasibilityAssessmentV1


@dataclass(frozen=True)
class DecisionArbiterResultV1:
    decision_context_id: str
    decision_context_object_id: str
    feasibility_snapshot_id: str
    pairwise_snapshot_id: str
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    base_request: DecisionArbiterRequestV1
    candidate_assessments: tuple[ArbiterCandidateAssessmentV1, ...]
    considered_pairwise_evidence: tuple[PairwiseTradeoffEvidenceV1, ...]
    status: DecisionArbiterStatus
    reason: DecisionArbiterReason
    selected_option_id: str | None
    selected_option: OptionDecisionContextV2 | None
    ruleset: str

    @property
    def result_id(self) -> str:
        content = {name: getattr(self, name) for name in (
            'decision_context_id', 'decision_context_object_id', 'feasibility_snapshot_id',
            'pairwise_snapshot_id', 'timeline_id', 'selected_clock_id', 'evaluated_at_tick',
            'status', 'reason', 'selected_option_id', 'ruleset')}
        content['base_request'] = {name: getattr(self.base_request, name) for name in (
            'decision_context_id', 'arbiter_context_id', 'pairwise_context_id')}
        content['candidate_assessments'] = [{name: getattr(row, name) for name in (
            'option_id', 'admission_status', 'safety_presence', 'safety_gate_status',
            'feasibility_status')} for row in self.candidate_assessments]
        content['considered_pairwise_evidence'] = [row.evidence_id for row in self.considered_pairwise_evidence]
        encoded = json.dumps(content, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':result:' + hashlib.sha256(encoded).hexdigest()


def _safety(option):
    if type(option.safety_presence) is not DecisionEvidencePresence:
        raise TypeError('exact_safety_presence_required')
    for value in (option.option_id, option.risk_context_id):
        _text(value)
    if option.safety_context_id is not None:
        _text(option.safety_context_id)
    evaluation = option.safety_evaluation
    if option.safety_presence is DecisionEvidencePresence.ABSENT:
        if evaluation is not None:
            raise ValueError('absent_safety_requires_none')
        return None
    if type(evaluation) is not OptionSafetyEvaluationV2:
        raise TypeError('exact_safety_evaluation_required')
    for value in (evaluation.option_id, evaluation.risk_context_id, evaluation.gate_policy_id):
        _text(value)
    if evaluation.safety_context_id is not None:
        _text(evaluation.safety_context_id)
    if (evaluation.option_id, evaluation.risk_context_id, evaluation.safety_context_id) != (
            option.option_id, option.risk_context_id, option.safety_context_id):
        raise ValueError('foreign_safety_binding')
    if type(evaluation.gate_status) is not OptionSafetyGateStatus:
        raise TypeError('exact_safety_gate_status_required')
    return evaluation.gate_status


def _pair(row):
    return tuple(sorted((row.left_option_id, row.right_option_id)))


def _boundary(context, feasibility, pairwise, request):
    for value, kind in ((context, DecisionContextV2), (feasibility, FeasibilitySnapshotV1),
                        (pairwise, PairwiseTradeoffSnapshotV1), (request, DecisionArbiterRequestV1)):
        if type(value) is not kind:
            raise TypeError('exact_input_contract_required')
    _request(request)
    for value in (context.context_binding_policy_id, context.objective_context_id,
                  context.objective_horizon_id, context.strategic_objective_snapshot_id,
                  context.option_safety_snapshot_id, context.option_outcome_snapshot_id,
                  pairwise.relation_snapshot_id, pairwise.objective_context_id,
                  pairwise.objective_horizon_id):
        _text(value)
    header = (context.decision_context_id, context.timeline_id,
              context.selected_clock_id, context.decision_assembly_tick)
    for obj, tick, ruleset in ((context, context.decision_assembly_tick, 'decision.context.v2'),
                               (feasibility, feasibility.evaluated_at_tick, 'option.feasibility_gate.v1'),
                               (pairwise, pairwise.evaluated_at_tick, 'decision.pairwise_tradeoff.v1')):
        for value in (obj.decision_context_id, obj.timeline_id, obj.selected_clock_id):
            _text(value)
        _tick(tick)
        if type(obj.ruleset) is not str or obj.ruleset != ruleset:
            raise ValueError('accepted_ruleset_required')
        if (obj.decision_context_id, obj.timeline_id, obj.selected_clock_id, tick) != header:
            raise ValueError('exact_header_alignment_required')
    if request.decision_context_id != context.decision_context_id:
        raise ValueError('foreign_request_context')
    if type(context.options) is not tuple:
        raise TypeError('exact_options_tuple_required')
    options = {}
    safety = {}
    for option in context.options:
        if type(option) is not OptionDecisionContextV2:
            raise TypeError('exact_option_context_required')
        _text(option.option_id)
        if option.option_id in options:
            raise ValueError('duplicate_context_option')
        options[option.option_id] = option
        safety[option.option_id] = _safety(option)
    lineage = context.context_id
    _text(lineage)
    for snapshot in (feasibility, pairwise):
        _text(snapshot.decision_context_object_id)
        if snapshot.decision_context_object_id != lineage:
            raise ValueError('exact_context_lineage_required')
    objective_id = None if context.objective_assessment is None else context.objective_assessment.objective_id
    for value in (objective_id, pairwise.objective_id):
        if value is not None:
            _text(value)
    if (pairwise.objective_context_id, pairwise.objective_horizon_id, pairwise.objective_id) != (
            context.objective_context_id, context.objective_horizon_id, objective_id):
        raise ValueError('exact_objective_lineage_required')
    if type(feasibility.assessments) is not tuple:
        raise TypeError('exact_assessments_tuple_required')
    assessments = {}
    for row in feasibility.assessments:
        if type(row) is not OptionFeasibilityAssessmentV1:
            raise TypeError('exact_feasibility_assessment_required')
        _text(row.option_id)
        if row.option_id in assessments:
            raise ValueError('duplicate_feasibility_assessment')
        if row.option_id not in options or row.base_option_context is not options[row.option_id]:
            raise ValueError('foreign_feasibility_option')
        if type(row.status) is not FeasibilityGateStatus:
            raise TypeError('exact_feasibility_status_required')
        assessments[row.option_id] = row
    if assessments.keys() != options.keys():
        raise ValueError('complete_feasibility_mapping_required')
    if type(pairwise.comparisons) is not tuple:
        raise TypeError('exact_comparisons_tuple_required')
    if objective_id is None and pairwise.comparisons:
        raise ValueError('comparisons_without_objective')
    seen = set()
    for row in pairwise.comparisons:
        if type(row) is not PairwiseTradeoffEvidenceV1:
            raise TypeError('exact_pairwise_evidence_required')
        for value in (row.decision_context_id, row.pairwise_context_id, row.left_option_id,
                      row.right_option_id, row.source_id, row.assessment_policy_id):
            _text(value)
        _tick(row.basis_tick)
        if row.decision_context_id != context.decision_context_id or row.basis_tick != context.decision_assembly_tick:
            raise ValueError('foreign_pairwise_header')
        if row.left_option_id not in options or row.right_option_id not in options or row.left_option_id == row.right_option_id:
            raise ValueError('known_distinct_pair_options_required')
        if type(row.conclusion) is not PairwiseTradeoffConclusion:
            raise TypeError('exact_pairwise_conclusion_required')
        key = (row.pairwise_context_id, _pair(row))
        if key in seen:
            raise ValueError('duplicate_unordered_pair')
        seen.add(key)
    return options, safety, assessments, lineage


def _admission(safety, feasibility):
    if safety is OptionSafetyGateStatus.RISK_BLOCKING or feasibility is FeasibilityGateStatus.INFEASIBLE:
        return ArbiterCandidateAdmissionStatus.EXCLUDED
    if safety is OptionSafetyGateStatus.RISK_NOT_BLOCKING and feasibility is FeasibilityGateStatus.FEASIBLE:
        return ArbiterCandidateAdmissionStatus.ADMITTED
    return ArbiterCandidateAdmissionStatus.INDETERMINATE


def _advantage(row, option_id):
    return (row.conclusion is PairwiseTradeoffConclusion.LEFT_ADVANTAGE and row.left_option_id == option_id
            or row.conclusion is PairwiseTradeoffConclusion.RIGHT_ADVANTAGE and row.right_option_id == option_id)


def _selection(candidates, pairwise, request):
    if any(row.admission_status is ArbiterCandidateAdmissionStatus.INDETERMINATE for row in candidates):
        return DecisionArbiterStatus.INDETERMINATE, DecisionArbiterReason.CANDIDATE_ADMISSION_INDETERMINATE, None, ()
    admitted = tuple(row.option_id for row in candidates if row.admission_status is ArbiterCandidateAdmissionStatus.ADMITTED)
    if not admitted:
        return DecisionArbiterStatus.NO_SELECTION, DecisionArbiterReason.NO_ADMITTED_OPTIONS, None, ()
    if len(admitted) == 1:
        return DecisionArbiterStatus.SELECTED, DecisionArbiterReason.SINGLE_ADMITTED_OPTION, admitted[0], ()
    considered = tuple(sorted((row for row in pairwise.comparisons if
        row.pairwise_context_id == request.pairwise_context_id and
        row.left_option_id in admitted and row.right_option_id in admitted),
        key=lambda row: (row.pairwise_context_id, _pair(row), row.source_id, row.assessment_policy_id)))
    indexed = {_pair(row): row for row in considered}
    required = tuple((left, right) for i, left in enumerate(admitted) for right in admitted[i+1:])
    if any(pair not in indexed for pair in required):
        return DecisionArbiterStatus.INDETERMINATE, DecisionArbiterReason.PAIRWISE_EVIDENCE_INCOMPLETE, None, considered
    if any(row.conclusion is PairwiseTradeoffConclusion.INDETERMINATE for row in considered):
        return DecisionArbiterStatus.INDETERMINATE, DecisionArbiterReason.PAIRWISE_EVIDENCE_INDETERMINATE, None, considered
    for option_id in admitted:
        if all(_advantage(indexed[tuple(sorted((option_id, other)))], option_id) for other in admitted if other != option_id):
            return DecisionArbiterStatus.SELECTED, DecisionArbiterReason.UNIQUE_DIRECT_ADVANTAGE, option_id, considered
    return DecisionArbiterStatus.NO_SELECTION, DecisionArbiterReason.NO_UNIQUE_DIRECT_ADVANTAGE, None, considered


def build_decision_arbiter_result_v1(
        *, decision_context: DecisionContextV2,
        feasibility_snapshot: FeasibilitySnapshotV1,
        pairwise_snapshot: PairwiseTradeoffSnapshotV1,
        request: DecisionArbiterRequestV1,
) -> DecisionArbiterResultV1:
    """Validate all supplied boundaries before applying the fixed selection policy."""
    options, safety, feasibility, lineage = _boundary(
        decision_context, feasibility_snapshot, pairwise_snapshot, request)
    candidates = tuple(ArbiterCandidateAssessmentV1(
        identity, _admission(safety[identity], feasibility[identity].status),
        options[identity].safety_presence, safety[identity], feasibility[identity].status,
        options[identity], feasibility[identity]) for identity in sorted(options))
    status, reason, selected_id, considered = _selection(candidates, pairwise_snapshot, request)
    feasibility_id = feasibility_snapshot.snapshot_id
    pairwise_id = pairwise_snapshot.snapshot_id
    _text(feasibility_id)
    _text(pairwise_id)
    return DecisionArbiterResultV1(
        decision_context.decision_context_id, lineage, feasibility_id, pairwise_id,
        decision_context.timeline_id, decision_context.selected_clock_id,
        decision_context.decision_assembly_tick, request, candidates, considered,
        status, reason, selected_id, None if selected_id is None else options[selected_id], RULESET)
