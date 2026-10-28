"""Sparse caller-owned pairwise assertions with local categorical costs."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .decision_context_v02 import DecisionContextV2, OptionDecisionContextV2
from .objective_outcome_relation_v01 import (
    ObjectiveOutcomeRelationSnapshotV1, ObjectiveOutcomeRelationEvidence,
)


RULESET = 'decision.pairwise_tradeoff.v1'


class PairwiseTradeoffConclusion(str, Enum):
    LEFT_ADVANTAGE = 'LEFT_ADVANTAGE'
    RIGHT_ADVANTAGE = 'RIGHT_ADVANTAGE'
    TRADE_OFF = 'TRADE_OFF'
    EQUIVALENT = 'EQUIVALENT'
    INDETERMINATE = 'INDETERMINATE'


class OpportunityCostConclusion(str, Enum):
    ESTABLISHED = 'ESTABLISHED'
    NOT_ESTABLISHED = 'NOT_ESTABLISHED'
    INDETERMINATE = 'INDETERMINATE'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('concrete_nonblank_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('concrete_integer_tick_required')
    if value < 0:
        raise ValueError('negative_tick')


def _ids(values, nonempty=False):
    if type(values) is not tuple:
        raise TypeError('exact_identity_tuple_required')
    if nonempty and not values:
        raise ValueError('nonempty_bundle_required')
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError('duplicate_identity')


def _pair(claim):
    return tuple(sorted((claim.left_option_id, claim.right_option_id)))


def _validate_claim(claim):
    for value in (claim.decision_context_id, claim.pairwise_context_id,
                  claim.left_option_id, claim.right_option_id,
                  claim.source_id, claim.assessment_policy_id):
        _text(value)
    if claim.left_option_id == claim.right_option_id:
        raise ValueError('distinct_options_required')
    _ids(claim.left_relation_evidence_ids, True)
    _ids(claim.right_relation_evidence_ids, True)
    if type(claim.conclusion) is not PairwiseTradeoffConclusion:
        raise TypeError('exact_pairwise_conclusion_required')
    _tick(claim.basis_tick)
    _ids(claim.evidence_refs)


@dataclass(frozen=True)
class PairwiseTradeoffClaim:
    decision_context_id: str
    pairwise_context_id: str
    left_option_id: str
    right_option_id: str
    left_relation_evidence_ids: tuple[str, ...]
    right_relation_evidence_ids: tuple[str, ...]
    conclusion: PairwiseTradeoffConclusion
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


def _normalize_bundles(content):
    # Normalize the hash copy only. Original caller tuples remain untouched.
    for name in ('left_relation_evidence_ids', 'right_relation_evidence_ids'):
        content['base_claim'][name] = sorted(content['base_claim'][name])


def _identity(kind, content):
    encoded = json.dumps(content, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True).encode('utf-8')
    return RULESET + ':' + kind + ':' + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PairwiseTradeoffEvidenceV1:
    decision_context_id: str
    pairwise_context_id: str
    left_option_id: str
    right_option_id: str
    conclusion: PairwiseTradeoffConclusion
    left_opportunity_cost: OpportunityCostConclusion
    right_opportunity_cost: OpportunityCostConclusion
    basis_tick: int
    source_id: str
    evidence_refs: tuple[str, ...]
    assessment_policy_id: str
    left_relation_evidences: tuple[ObjectiveOutcomeRelationEvidence, ...]
    right_relation_evidences: tuple[ObjectiveOutcomeRelationEvidence, ...]
    base_claim: PairwiseTradeoffClaim

    @property
    def evidence_id(self) -> str:
        content = asdict(self)
        _normalize_bundles(content)
        return _identity('evidence', content)


@dataclass(frozen=True)
class PairwiseTradeoffSnapshotV1:
    decision_context_id: str
    decision_context_object_id: str
    relation_snapshot_id: str
    timeline_id: str
    selected_clock_id: str
    evaluated_at_tick: int
    objective_context_id: str
    objective_horizon_id: str
    objective_id: str | None
    ruleset: str
    comparisons: tuple[PairwiseTradeoffEvidenceV1, ...]

    @property
    def snapshot_id(self) -> str:
        content = asdict(self)
        for row in content['comparisons']:
            _normalize_bundles(row)
        return _identity('snapshot', content)


def _boundary(context, snapshot):
    if type(context) is not DecisionContextV2:
        raise TypeError('exact_decision_context_required')
    if type(snapshot) is not ObjectiveOutcomeRelationSnapshotV1:
        raise TypeError('exact_relation_snapshot_required')
    for value in (context.decision_context_id, context.timeline_id, context.selected_clock_id,
                  context.objective_context_id, context.objective_horizon_id,
                  snapshot.decision_context_id, snapshot.decision_context_object_id,
                  snapshot.timeline_id, snapshot.selected_clock_id,
                  snapshot.objective_context_id, snapshot.objective_horizon_id):
        _text(value)
    _tick(context.decision_assembly_tick)
    _tick(snapshot.evaluated_at_tick)
    if type(context.ruleset) is not str or context.ruleset != 'decision.context.v2':
        raise ValueError('accepted_context_ruleset_required')
    if type(snapshot.ruleset) is not str or snapshot.ruleset != 'objective.outcome_relation.v1':
        raise ValueError('accepted_relation_ruleset_required')
    if type(context.options) is not tuple or type(snapshot.relations) is not tuple:
        raise TypeError('exact_upstream_tuple_required')
    options = set()
    for option in context.options:
        if type(option) is not OptionDecisionContextV2:
            raise TypeError('exact_option_context_required')
        _text(option.option_id)
        if option.option_id in options:
            raise ValueError('duplicate_context_option')
        options.add(option.option_id)
    lineage = context.context_id
    _text(lineage)
    if (snapshot.decision_context_id, snapshot.decision_context_object_id,
            snapshot.timeline_id, snapshot.selected_clock_id, snapshot.evaluated_at_tick) != (
            context.decision_context_id, lineage, context.timeline_id,
            context.selected_clock_id, context.decision_assembly_tick):
        raise ValueError('exact_relation_lineage_required')
    objective_id = None if context.objective_assessment is None else context.objective_assessment.objective_id
    if objective_id is not None:
        _text(objective_id)
    if snapshot.objective_id is not None:
        _text(snapshot.objective_id)
    if (snapshot.objective_context_id, snapshot.objective_horizon_id, snapshot.objective_id) != (
            context.objective_context_id, context.objective_horizon_id, objective_id):
        raise ValueError('exact_objective_binding_required')
    if objective_id is None and snapshot.relations:
        raise ValueError('relation_rows_without_objective')
    index = {}
    for row in snapshot.relations:
        if type(row) is not ObjectiveOutcomeRelationEvidence:
            raise TypeError('exact_relation_evidence_required')
        for value in (row.option_id, row.objective_context_id, row.objective_horizon_id,
                      row.objective_id, row.outcome_context_id, row.outcome_baseline_id,
                      row.outcome_horizon_id, row.dimension_id, row.source_id, row.assessment_policy_id):
            _text(value)
        _tick(row.basis_tick)
        _ids(row.evidence_refs)
        if row.option_id not in options:
            raise ValueError('foreign_relation_option')
        if (row.objective_context_id, row.objective_horizon_id, row.objective_id) != (
                snapshot.objective_context_id, snapshot.objective_horizon_id, objective_id):
            raise ValueError('foreign_relation_objective')
        if row.basis_tick != context.decision_assembly_tick:
            raise ValueError('foreign_relation_tick')
        identity = row.evidence_id
        _text(identity)
        if identity in index:
            raise ValueError('duplicate_relation_evidence_id')
        index[identity] = row
    return options, index, lineage


def _bundle(ids, option_id, index):
    rows = []
    for identity in sorted(ids):
        if identity not in index:
            raise ValueError('missing_relation_evidence')
        row = index[identity]
        if row.option_id != option_id:
            raise ValueError('wrong_side_relation_evidence')
        rows.append(row)
    return tuple(rows)


def _costs(conclusion):
    if conclusion is PairwiseTradeoffConclusion.LEFT_ADVANTAGE:
        return OpportunityCostConclusion.NOT_ESTABLISHED, OpportunityCostConclusion.ESTABLISHED
    if conclusion is PairwiseTradeoffConclusion.RIGHT_ADVANTAGE:
        return OpportunityCostConclusion.ESTABLISHED, OpportunityCostConclusion.NOT_ESTABLISHED
    if conclusion is PairwiseTradeoffConclusion.TRADE_OFF:
        return OpportunityCostConclusion.ESTABLISHED, OpportunityCostConclusion.ESTABLISHED
    if conclusion is PairwiseTradeoffConclusion.EQUIVALENT:
        return OpportunityCostConclusion.NOT_ESTABLISHED, OpportunityCostConclusion.NOT_ESTABLISHED
    return OpportunityCostConclusion.INDETERMINATE, OpportunityCostConclusion.INDETERMINATE


def build_pairwise_tradeoff_snapshot_v1(
        *, decision_context: DecisionContextV2,
        relation_snapshot: ObjectiveOutcomeRelationSnapshotV1,
        claims: tuple[PairwiseTradeoffClaim, ...],
) -> PairwiseTradeoffSnapshotV1:
    """Preserve explicit comparisons; do not infer any missing comparisons.

    Accepted upstream objects retain responsibility for their embedded semantics.
    This boundary validates lineage, identities and selected membership only.
    """
    options, index, lineage = _boundary(decision_context, relation_snapshot)
    if type(claims) is not tuple:
        raise TypeError('exact_pairwise_claim_tuple_required')
    seen = set()
    bound = []
    for claim in claims:
        if type(claim) is not PairwiseTradeoffClaim:
            raise TypeError('exact_pairwise_claim_required')
        _validate_claim(claim)
        if claim.decision_context_id != decision_context.decision_context_id:
            raise ValueError('foreign_decision_context')
        if claim.left_option_id not in options or claim.right_option_id not in options:
            raise ValueError('foreign_option')
        if relation_snapshot.objective_id is None:
            raise ValueError('concrete_objective_required')
        if claim.basis_tick != decision_context.decision_assembly_tick:
            raise ValueError('exact_decision_tick_required')
        key = (claim.decision_context_id, claim.pairwise_context_id, _pair(claim))
        if key in seen:
            raise ValueError('duplicate_unordered_pair')
        seen.add(key)
        left = _bundle(claim.left_relation_evidence_ids, claim.left_option_id, index)
        right = _bundle(claim.right_relation_evidence_ids, claim.right_option_id, index)
        bound.append((claim, left, right))
    relation_id = relation_snapshot.snapshot_id
    _text(relation_id)
    ordered = sorted(bound, key=lambda item: (item[0].pairwise_context_id, _pair(item[0]),
                                             item[0].source_id, item[0].assessment_policy_id))
    comparisons = tuple(PairwiseTradeoffEvidenceV1(
        c.decision_context_id, c.pairwise_context_id, c.left_option_id, c.right_option_id,
        c.conclusion, *_costs(c.conclusion), c.basis_tick, c.source_id, c.evidence_refs,
        c.assessment_policy_id, left, right, c) for c, left, right in ordered)
    return PairwiseTradeoffSnapshotV1(
        decision_context.decision_context_id, lineage, relation_id, decision_context.timeline_id,
        decision_context.selected_clock_id, decision_context.decision_assembly_tick,
        relation_snapshot.objective_context_id, relation_snapshot.objective_horizon_id,
        relation_snapshot.objective_id, RULESET, comparisons)
