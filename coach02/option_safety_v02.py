"""Explicit policy-bound modeled-risk gate, without action authority.

Risk Evaluation is authoritative. Tolerance applies only to SUPPORTED risk;
it cannot erase epistemic uncertainty or imply global safety.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .risk_evaluation import RiskEvaluationSnapshot, OptionRiskEvaluation, RiskConclusion


RULESET = 'option.safety_gate.v2'
GATE_POLICY_ID = 'option.safety_gate.v2'


class OptionSafetyGateStatus(str, Enum):
    RISK_BLOCKING = 'RISK_BLOCKING'
    RISK_NOT_BLOCKING = 'RISK_NOT_BLOCKING'
    INDETERMINATE = 'INDETERMINATE'


class SupportedRiskTolerance(str, Enum):
    TOLERATED = 'TOLERATED'
    NOT_TOLERATED = 'NOT_TOLERATED'
    UNKNOWN = 'UNKNOWN'


class OptionSafetyGateReason(str, Enum):
    SUPPORTED_RISK_NOT_TOLERATED = 'SUPPORTED_RISK_NOT_TOLERATED'
    SUPPORTED_RISK_TOLERATED = 'SUPPORTED_RISK_TOLERATED'
    SUPPORTED_RISK_POLICY_UNKNOWN = 'SUPPORTED_RISK_POLICY_UNKNOWN'
    SUPPORTED_RISK_POLICY_ABSENT = 'SUPPORTED_RISK_POLICY_ABSENT'
    RISK_NOT_ESTABLISHED = 'RISK_NOT_ESTABLISHED'
    RISK_INDETERMINATE = 'RISK_INDETERMINATE'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_risk_tick_required')


def _claim_key(claim):
    return (claim.risk_context_id, claim.option_id, claim.safety_context_id, claim.safety_policy_id)


def _validate_claim(claim):
    for value in _claim_key(claim):
        _text(value)
    if type(claim.supported_risk_tolerance) is not SupportedRiskTolerance:
        raise TypeError('concrete_supported_risk_tolerance_required')


@dataclass(frozen=True)
class OptionSafetyPolicyClaim:
    risk_context_id: str
    option_id: str
    safety_context_id: str
    supported_risk_tolerance: SupportedRiskTolerance
    safety_policy_id: str

    def __post_init__(self):
        _validate_claim(self)


@dataclass(frozen=True)
class OptionSafetyEvaluationV2:
    risk_context_id: str
    option_id: str
    safety_context_id: str | None
    gate_status: OptionSafetyGateStatus
    reason: OptionSafetyGateReason
    gate_policy_id: str
    safety_policy_claim: OptionSafetyPolicyClaim | None
    base_risk_evaluation: OptionRiskEvaluation


@dataclass(frozen=True)
class OptionSafetySnapshotV2:
    timeline_id: str
    selected_clock_id: str
    risk_evaluation_snapshot_id: str
    risk_assembly_tick: int
    gate_policy_id: str
    evaluations: tuple[OptionSafetyEvaluationV2, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _evaluation_index(snapshot):
    if type(snapshot) is not RiskEvaluationSnapshot:
        raise TypeError('exact_risk_evaluation_snapshot_required')
    for value in (snapshot.timeline_id, snapshot.selected_clock_id,
                  snapshot.risk_evidence_snapshot_id, snapshot.evaluation_policy_id):
        _text(value)
    _tick(snapshot.risk_assembly_tick)
    if type(snapshot.evaluations) is not tuple:
        raise TypeError('evaluation_tuple_required')
    index = {}
    for row in snapshot.evaluations:
        if type(row) is not OptionRiskEvaluation:
            raise TypeError('exact_option_risk_evaluation_required')
        for value in (row.risk_context_id, row.option_id, row.evaluation_policy_id):
            _text(value)
        _tick(row.risk_assembly_tick)
        if (row.risk_assembly_tick, row.evaluation_policy_id) != (
                snapshot.risk_assembly_tick, snapshot.evaluation_policy_id):
            raise ValueError('risk_evaluation_header_mismatch')
        if type(row.conclusion) is not RiskConclusion:
            raise TypeError('concrete_risk_conclusion_required')
        key = (row.risk_context_id, row.option_id)
        if key in index:
            raise ValueError('duplicate_risk_evaluation')
        index[key] = row
    return index


def _gate(conclusion, claim):
    if conclusion is RiskConclusion.NOT_ESTABLISHED:
        return OptionSafetyGateStatus.RISK_NOT_BLOCKING, OptionSafetyGateReason.RISK_NOT_ESTABLISHED
    if conclusion is RiskConclusion.INDETERMINATE:
        return OptionSafetyGateStatus.INDETERMINATE, OptionSafetyGateReason.RISK_INDETERMINATE
    if conclusion is RiskConclusion.SUPPORTED:
        if claim is None:
            return OptionSafetyGateStatus.INDETERMINATE, OptionSafetyGateReason.SUPPORTED_RISK_POLICY_ABSENT
        if claim.supported_risk_tolerance is SupportedRiskTolerance.NOT_TOLERATED:
            return OptionSafetyGateStatus.RISK_BLOCKING, OptionSafetyGateReason.SUPPORTED_RISK_NOT_TOLERATED
        if claim.supported_risk_tolerance is SupportedRiskTolerance.TOLERATED:
            return OptionSafetyGateStatus.RISK_NOT_BLOCKING, OptionSafetyGateReason.SUPPORTED_RISK_TOLERATED
        if claim.supported_risk_tolerance is SupportedRiskTolerance.UNKNOWN:
            return OptionSafetyGateStatus.INDETERMINATE, OptionSafetyGateReason.SUPPORTED_RISK_POLICY_UNKNOWN
    raise ValueError('unhandled_gate_input')


def evaluate_option_safety_v2(
        risk_evaluation_snapshot: RiskEvaluationSnapshot,
        policy_claims: tuple[OptionSafetyPolicyClaim, ...],
) -> OptionSafetySnapshotV2:
    """Gate each accepted row under its explicit claim, with no default tolerance."""
    snapshot = risk_evaluation_snapshot
    index = _evaluation_index(snapshot)
    if type(policy_claims) is not tuple:
        raise TypeError('policy_claim_tuple_required')
    for claim in policy_claims:
        if type(claim) is not OptionSafetyPolicyClaim:
            raise TypeError('exact_policy_claim_required')
        _validate_claim(claim)
    claims = {}
    for claim in sorted(policy_claims, key=_claim_key):
        key = (claim.risk_context_id, claim.option_id)
        if key in claims:
            raise ValueError('duplicate_policy_claim')
        if key not in index:
            raise ValueError('foreign_policy_claim')
        claims[key] = claim
    evaluations = []
    # Preserve authoritative canonical row order; never order by gate outcome.
    for row in snapshot.evaluations:
        claim = claims.get((row.risk_context_id, row.option_id))
        status, reason = _gate(row.conclusion, claim)
        evaluations.append(OptionSafetyEvaluationV2(row.risk_context_id, row.option_id,
            None if claim is None else claim.safety_context_id, status, reason,
            GATE_POLICY_ID, claim, row))
    return OptionSafetySnapshotV2(snapshot.timeline_id, snapshot.selected_clock_id,
        snapshot.snapshot_id, snapshot.risk_assembly_tick, GATE_POLICY_ID, tuple(evaluations))
