"""Conservative categorical interpretation of accepted Risk Evidence v0.2.

Positive evidence and negative evidence are intentionally asymmetric. This
policy has no safety, magnitude, option ranking, or action authority.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .risk_evidence_assembly_v02 import (
    RiskEvidenceSnapshotV2, OptionRiskEvidenceBundleV2, ThreatRiskEvidenceV2, EvidenceUseStatus,
)


RULESET = 'risk.evaluation.v1'
EVALUATION_POLICY_ID = 'risk.evaluation.conservative.v1'

# Read concrete nested field contracts from the authoritative v0.2 schema.
# No lower module is imported, no constructor is called, and no type is inferred
# from caller data. These annotations are concrete in the accepted contracts.
_BaseBundle = OptionRiskEvidenceBundleV2.__annotations__['base_bundle']
_BaseThreat = ThreatRiskEvidenceV2.__annotations__['base_threat_evidence']
_StateAssessment = _BaseThreat.__annotations__['state_assessment']
_State = _StateAssessment.__annotations__['state']
_RelevanceAssessment = _BaseThreat.__annotations__['relevance_assessment'].__args__[0]
_Relevance = _RelevanceAssessment.__annotations__['relevance']
_ReachabilityAssessment = ThreatRiskEvidenceV2.__annotations__['reachability_assessment'].__args__[0]
_Reachability = _ReachabilityAssessment.__annotations__['reachability']
_CoverageObservation = _BaseBundle.__annotations__['coverage_observation'].__args__[0]
_Coverage = _CoverageObservation.__annotations__['coverage']
_ExposureObservation = _BaseBundle.__annotations__['exposure_observation'].__args__[0]
_Exposure = _ExposureObservation.__annotations__['exposure']


class RiskConclusion(str, Enum):
    SUPPORTED = 'SUPPORTED'
    NOT_ESTABLISHED = 'NOT_ESTABLISHED'
    INDETERMINATE = 'INDETERMINATE'


class ThreatContributionStatus(str, Enum):
    CONTRIBUTING = 'CONTRIBUTING'
    NON_CONTRIBUTING = 'NON_CONTRIBUTING'
    INDETERMINATE = 'INDETERMINATE'


class ThreatContributionReason(str, Enum):
    RELEVANT_AND_CAN_AFFECT = 'RELEVANT_AND_CAN_AFFECT'
    NOT_RELEVANT = 'NOT_RELEVANT'
    CANNOT_AFFECT = 'CANNOT_AFFECT'
    STATE_NOT_CURRENT = 'STATE_NOT_CURRENT'
    RELEVANCE_ABSENT = 'RELEVANCE_ABSENT'
    RELEVANCE_HISTORICAL = 'RELEVANCE_HISTORICAL'
    RELEVANCE_UNKNOWN = 'RELEVANCE_UNKNOWN'
    REACHABILITY_ABSENT = 'REACHABILITY_ABSENT'
    REACHABILITY_HISTORICAL = 'REACHABILITY_HISTORICAL'
    REACHABILITY_UNKNOWN = 'REACHABILITY_UNKNOWN'


class RiskConclusionReason(str, Enum):
    CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT = 'CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT'
    EXPOSURE_ABSENT = 'EXPOSURE_ABSENT'
    EXPOSURE_HISTORICAL = 'EXPOSURE_HISTORICAL'
    EXPOSURE_UNKNOWN = 'EXPOSURE_UNKNOWN'
    NOT_EXPOSED_WITH_CONTRIBUTING_THREAT = 'NOT_EXPOSED_WITH_CONTRIBUTING_THREAT'
    THREAT_EVIDENCE_INDETERMINATE = 'THREAT_EVIDENCE_INDETERMINATE'
    COVERAGE_ABSENT = 'COVERAGE_ABSENT'
    COVERAGE_HISTORICAL = 'COVERAGE_HISTORICAL'
    COVERAGE_INSUFFICIENT = 'COVERAGE_INSUFFICIENT'
    COVERAGE_UNKNOWN = 'COVERAGE_UNKNOWN'
    SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT = 'SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT'


@dataclass(frozen=True)
class ThreatRiskEvaluation:
    threat_id: str
    contribution: ThreatContributionStatus
    reason: ThreatContributionReason
    base_threat_evidence: ThreatRiskEvidenceV2


@dataclass(frozen=True)
class OptionRiskEvaluation:
    risk_context_id: str
    option_id: str
    conclusion: RiskConclusion
    reason: RiskConclusionReason
    evaluation_policy_id: str
    risk_assembly_tick: int
    threat_evaluations: tuple[ThreatRiskEvaluation, ...]
    base_bundle: OptionRiskEvidenceBundleV2


@dataclass(frozen=True)
class RiskEvaluationSnapshot:
    timeline_id: str
    selected_clock_id: str
    risk_evidence_snapshot_id: str
    risk_assembly_tick: int
    evaluation_policy_id: str
    evaluations: tuple[OptionRiskEvaluation, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_risk_tick_required')


def _use(value):
    if type(value) is not EvidenceUseStatus:
        raise TypeError('concrete_evidence_use_required')


def _axis(use, evidence, contract):
    _use(use)
    if use is EvidenceUseStatus.ABSENT:
        if evidence is not None:
            raise ValueError('absent_axis_must_be_none')
    else:
        if type(evidence) is not contract:
            raise TypeError('concrete_axis_evidence_required')


def _semantic(value, contract):
    if type(value) is not contract:
        raise TypeError('concrete_semantic_enum_required')


def _validate(snapshot):
    if type(snapshot) is not RiskEvidenceSnapshotV2:
        raise TypeError('exact_risk_evidence_v2_required')
    for value in (snapshot.timeline_id, snapshot.selected_clock_id,
                  snapshot.base_risk_evidence_snapshot_id, snapshot.threat_reachability_snapshot_id):
        _text(value)
    _tick(snapshot.risk_assembly_tick)
    if type(snapshot.bundles) is not tuple:
        raise TypeError('bundle_tuple_required')
    keys = set()
    for bundle in snapshot.bundles:
        if type(bundle) is not OptionRiskEvidenceBundleV2 or type(bundle.base_bundle) is not _BaseBundle:
            raise TypeError('exact_bundle_required')
        base = bundle.base_bundle
        for value in (base.risk_context_id, base.option_id, base.relevance_context_id,
                      base.coverage_context_id, base.exposure_context_id, base.binding_policy_id,
                      bundle.reachability_context_id, bundle.horizon_id, bundle.reachability_binding_policy_id):
            _text(value)
        _tick(base.risk_assembly_tick)
        if base.risk_assembly_tick != snapshot.risk_assembly_tick:
            raise ValueError('risk_header_tick_mismatch')
        key = (base.risk_context_id, base.option_id)
        if key in keys:
            raise ValueError('duplicate_option_risk_bundle')
        keys.add(key)
        _axis(base.coverage_use, base.coverage_observation, _CoverageObservation)
        _axis(base.exposure_use, base.exposure_observation, _ExposureObservation)
        if base.coverage_observation is not None:
            _semantic(base.coverage_observation.coverage, _Coverage)
        if base.exposure_observation is not None:
            _semantic(base.exposure_observation.exposure, _Exposure)
        if type(bundle.threats) is not tuple or type(base.threats) is not tuple:
            raise TypeError('threat_tuple_required')
        if len(bundle.threats) != len(base.threats):
            raise ValueError('preserved_threat_rows_required')
        subjects = set()
        for row, original in zip(bundle.threats, base.threats):
            if type(row) is not ThreatRiskEvidenceV2 or type(row.base_threat_evidence) is not _BaseThreat:
                raise TypeError('exact_threat_row_required')
            threat = row.base_threat_evidence
            if type(original) is not _BaseThreat or original != threat:
                raise ValueError('preserved_threat_rows_required')
            _text(threat.threat_id)
            if threat.threat_id in subjects:
                raise ValueError('duplicate_threat_id')
            subjects.add(threat.threat_id)
            _use(threat.state_use)
            if type(threat.state_assessment) is not _StateAssessment:
                raise TypeError('concrete_state_required')
            if type(threat.state_assessment.state) is not _State:
                raise TypeError('concrete_state_enum_required')
            if threat.state_assessment.threat_id != threat.threat_id:
                raise ValueError('state_subject_mismatch')
            _axis(threat.relevance_use, threat.relevance_assessment, _RelevanceAssessment)
            _axis(row.reachability_use, row.reachability_assessment, _ReachabilityAssessment)
            if threat.relevance_assessment is not None:
                _semantic(threat.relevance_assessment.relevance, _Relevance)
            if row.reachability_assessment is not None:
                _semantic(row.reachability_assessment.reachability, _Reachability)
    # Currentness, freshness, context selection and upstream semantics are owned
    # by v0.2. Validation never rebuilds, rebinds or refreshes these axes.


def _contribution(row):
    base = row.base_threat_evidence
    relevant, reachable = base.relevance_assessment, row.reachability_assessment
    status = ThreatContributionStatus.INDETERMINATE
    if base.relevance_use is EvidenceUseStatus.CURRENT and relevant.relevance is _Relevance.NOT_RELEVANT:
        status, reason = ThreatContributionStatus.NON_CONTRIBUTING, ThreatContributionReason.NOT_RELEVANT
    elif row.reachability_use is EvidenceUseStatus.CURRENT and reachable.reachability is _Reachability.CANNOT_AFFECT:
        status, reason = ThreatContributionStatus.NON_CONTRIBUTING, ThreatContributionReason.CANNOT_AFFECT
    elif base.state_use is not EvidenceUseStatus.CURRENT:
        reason = ThreatContributionReason.STATE_NOT_CURRENT
    elif base.relevance_use is EvidenceUseStatus.ABSENT:
        reason = ThreatContributionReason.RELEVANCE_ABSENT
    elif base.relevance_use is EvidenceUseStatus.HISTORICAL:
        reason = ThreatContributionReason.RELEVANCE_HISTORICAL
    elif relevant.relevance is _Relevance.UNKNOWN:
        reason = ThreatContributionReason.RELEVANCE_UNKNOWN
    elif row.reachability_use is EvidenceUseStatus.ABSENT:
        reason = ThreatContributionReason.REACHABILITY_ABSENT
    elif row.reachability_use is EvidenceUseStatus.HISTORICAL:
        reason = ThreatContributionReason.REACHABILITY_HISTORICAL
    elif reachable.reachability is _Reachability.UNKNOWN:
        reason = ThreatContributionReason.REACHABILITY_UNKNOWN
    elif (base.state_use is EvidenceUseStatus.CURRENT and base.relevance_use is EvidenceUseStatus.CURRENT
          and relevant.relevance is _Relevance.RELEVANT and row.reachability_use is EvidenceUseStatus.CURRENT
          and reachable.reachability is _Reachability.CAN_AFFECT):
        status, reason = ThreatContributionStatus.CONTRIBUTING, ThreatContributionReason.RELEVANT_AND_CAN_AFFECT
    else:
        raise ValueError('unhandled_threat_policy_input')
    return ThreatRiskEvaluation(base.threat_id, status, reason, row)


def _conclusion(base, threats):
    indeterminate = RiskConclusion.INDETERMINATE
    if base.exposure_use is EvidenceUseStatus.ABSENT:
        return indeterminate, RiskConclusionReason.EXPOSURE_ABSENT
    if base.exposure_use is EvidenceUseStatus.HISTORICAL:
        return indeterminate, RiskConclusionReason.EXPOSURE_HISTORICAL
    exposure = base.exposure_observation.exposure
    if exposure is _Exposure.UNKNOWN:
        return indeterminate, RiskConclusionReason.EXPOSURE_UNKNOWN
    if any(t.contribution is ThreatContributionStatus.CONTRIBUTING for t in threats):
        if exposure is _Exposure.EXPOSED:
            return RiskConclusion.SUPPORTED, RiskConclusionReason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT
        if exposure is _Exposure.NOT_EXPOSED:
            return indeterminate, RiskConclusionReason.NOT_EXPOSED_WITH_CONTRIBUTING_THREAT
        raise ValueError('unhandled_exposure_policy_input')
    if any(t.contribution is ThreatContributionStatus.INDETERMINATE for t in threats):
        return indeterminate, RiskConclusionReason.THREAT_EVIDENCE_INDETERMINATE
    if base.coverage_use is EvidenceUseStatus.ABSENT:
        return indeterminate, RiskConclusionReason.COVERAGE_ABSENT
    if base.coverage_use is EvidenceUseStatus.HISTORICAL:
        return indeterminate, RiskConclusionReason.COVERAGE_HISTORICAL
    coverage = base.coverage_observation.coverage
    if coverage is _Coverage.INSUFFICIENT:
        return indeterminate, RiskConclusionReason.COVERAGE_INSUFFICIENT
    if coverage is _Coverage.UNKNOWN:
        return indeterminate, RiskConclusionReason.COVERAGE_UNKNOWN
    if coverage is _Coverage.SUFFICIENT:
        return RiskConclusion.NOT_ESTABLISHED, RiskConclusionReason.SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT
    raise ValueError('unhandled_coverage_policy_input')


def evaluate_risk(snapshot: RiskEvidenceSnapshotV2) -> RiskEvaluationSnapshot:
    """Interpret each explicit bundle independently using the fixed v1 policy."""
    _validate(snapshot)
    evaluations = []
    # Accepted v0.2 preserves canonical base bundle and threat ordering.
    for bundle in snapshot.bundles:
        threats = tuple(_contribution(row) for row in bundle.threats)
        base = bundle.base_bundle
        conclusion, reason = _conclusion(base, threats)
        evaluations.append(OptionRiskEvaluation(base.risk_context_id, base.option_id, conclusion, reason,
            EVALUATION_POLICY_ID, snapshot.risk_assembly_tick, threats, bundle))
    return RiskEvaluationSnapshot(snapshot.timeline_id, snapshot.selected_clock_id, snapshot.snapshot_id,
        snapshot.risk_assembly_tick, EVALUATION_POLICY_ID, tuple(evaluations))
