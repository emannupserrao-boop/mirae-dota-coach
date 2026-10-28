"""Explicit cross-domain evidence binding; no risk or safety judgment.

Usability at one common tick never rewrites the upstream semantic values.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json

from .threat_state_assembly import (
    ThreatStateSnapshot, ThreatStateAssessment, AssembledThreatState, ThreatStateReason,
    ThreatObservation, MissingThreatResolution,
)
from .threat_relevance import ThreatRelevanceSnapshot, ThreatRelevanceAssessment, ThreatRelevance
from .strategic_coverage import (
    StrategicCoverageSnapshot, StrategicCoverageObservation, StrategicCoverageState, TemporalStatus,
)
from .option_exposure import OptionExposureSnapshot, OptionExposureObservation, OptionExposureState


RULESET = 'risk.evidence_assembly.v1'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _binding_values(binding):
    return (binding.risk_context_id, binding.option_id, binding.relevance_context_id,
            binding.coverage_context_id, binding.exposure_context_id, binding.binding_policy_id)


class EvidenceUseStatus(str, Enum):
    CURRENT = 'CURRENT'
    HISTORICAL = 'HISTORICAL'
    ABSENT = 'ABSENT'


@dataclass(frozen=True)
class RiskEvidenceBinding:
    risk_context_id: str
    option_id: str
    relevance_context_id: str
    coverage_context_id: str
    exposure_context_id: str
    binding_policy_id: str

    def __post_init__(self):
        for value in _binding_values(self):
            _text(value)


@dataclass(frozen=True)
class ThreatRiskEvidence:
    threat_id: str
    state_assessment: ThreatStateAssessment
    state_use: EvidenceUseStatus
    relevance_assessment: ThreatRelevanceAssessment | None
    relevance_use: EvidenceUseStatus


@dataclass(frozen=True)
class OptionRiskEvidenceBundle:
    risk_context_id: str
    option_id: str
    relevance_context_id: str
    coverage_context_id: str
    exposure_context_id: str
    binding_policy_id: str
    risk_assembly_tick: int
    coverage_observation: StrategicCoverageObservation | None
    coverage_use: EvidenceUseStatus
    exposure_observation: OptionExposureObservation | None
    exposure_use: EvidenceUseStatus
    threats: tuple[ThreatRiskEvidence, ...]


@dataclass(frozen=True)
class RiskEvidenceSnapshot:
    timeline_id: str
    selected_clock_id: str
    threat_state_snapshot_id: str
    threat_relevance_snapshot_id: str
    strategic_coverage_snapshot_id: str
    option_exposure_snapshot_id: str
    risk_assembly_tick: int
    bundles: tuple[OptionRiskEvidenceBundle, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _nested_evidence(row, positive_snapshot_id):
    positive, missing = row.positive_observation, row.missing_resolution
    if positive is None and missing is None:
        raise ValueError('threat_evidence_required')
    if positive is not None:
        if type(positive) is not ThreatObservation:
            raise TypeError('accepted_positive_required')
        if positive.threat_id != row.threat_id:
            raise ValueError('nested_positive_subject_mismatch')
    if missing is not None:
        if type(missing) is not MissingThreatResolution:
            raise TypeError('accepted_missing_resolution_required')
        if missing.threat_id != row.threat_id or missing.absence.threat_id != row.threat_id:
            raise ValueError('nested_resolution_subject_mismatch')
        if missing.positive_snapshot_id != positive_snapshot_id or missing.positive != positive:
            raise ValueError('nested_resolution_lineage_mismatch')


def _threat_indices(state_snapshot, relevance_snapshot):
    for snapshot in (state_snapshot, relevance_snapshot):
        _text(snapshot.positive_snapshot_id)
        _text(snapshot.missing_snapshot_id)
        if type(snapshot.assessments) is not tuple:
            raise TypeError('assessment_tuple_required')
    _tick(state_snapshot.assembly_tick)
    _tick(relevance_snapshot.evaluated_at_tick)
    if (state_snapshot.positive_snapshot_id, state_snapshot.missing_snapshot_id) != (
            relevance_snapshot.positive_snapshot_id, relevance_snapshot.missing_snapshot_id):
        raise ValueError('threat_snapshot_lineage_mismatch')
    if state_snapshot.assembly_tick != relevance_snapshot.evaluated_at_tick:
        raise ValueError('threat_evaluation_tick_mismatch')
    states = {}
    for row in state_snapshot.assessments:
        if type(row) is not ThreatStateAssessment:
            raise TypeError('accepted_state_assessment_required')
        _text(row.threat_id)
        _tick(row.assembly_tick)
        if type(row.state) is not AssembledThreatState or type(row.reason) is not ThreatStateReason:
            raise TypeError('explicit_state_and_reason_required')
        if row.assembly_tick != state_snapshot.assembly_tick:
            raise ValueError('state_assessment_tick_mismatch')
        _nested_evidence(row, state_snapshot.positive_snapshot_id)
        if row.threat_id in states:
            raise ValueError('duplicate_state_subject')
        states[row.threat_id] = row
    relevances = {}
    for row in relevance_snapshot.assessments:
        if type(row) is not ThreatRelevanceAssessment:
            raise TypeError('accepted_relevance_assessment_required')
        for value in (row.threat_id, row.relevance_context_id, row.assessment_policy_id):
            _text(value)
        if type(row.relevance) is not ThreatRelevance:
            raise TypeError('explicit_relevance_required')
        if row.threat_id not in states:
            raise ValueError('relevance_subject_outside_state_universe')
        _nested_evidence(row, relevance_snapshot.positive_snapshot_id)
        state = states[row.threat_id]
        if (row.positive_observation, row.missing_resolution) != (
                state.positive_observation, state.missing_resolution):
            raise ValueError('state_relevance_evidence_mismatch')
        if row.threat_id in relevances:
            raise ValueError('duplicate_relevance_subject')
        relevances[row.threat_id] = row
    return states, relevances


def _observation_index(snapshot, exposure):
    for value in (snapshot.event_id, snapshot.projection_id, snapshot.tracker_state_id,
                  snapshot.temporal_snapshot_id):
        _text(value)
    _tick(snapshot.selected_tick)
    _tick(snapshot.evaluated_at_tick)
    if snapshot.evaluated_at_tick < snapshot.selected_tick:
        raise ValueError('evaluation_precedes_occurrence')
    if type(snapshot.observations) is not tuple:
        raise TypeError('observation_tuple_required')
    index = {}
    for row in snapshot.observations:
        expected = OptionExposureObservation if exposure else StrategicCoverageObservation
        if type(row) is not expected:
            raise TypeError('accepted_context_observation_required')
        for value in (row.ref, row.source_id, row.temporal_policy_id, row.assessment_policy_id):
            _text(value)
        if row.temporal_status is not TemporalStatus.FRESH and row.temporal_status is not TemporalStatus.STALE:
            raise TypeError('supported_temporal_status_required')
        for value in (row.observed_tick, row.last_observed_tick, row.age_ticks, row.max_age_ticks):
            _tick(value)
        if row.age_ticks < 0 or row.max_age_ticks < 0:
            raise ValueError('nonnegative_temporal_metadata_required')
        if (row.observed_tick != snapshot.selected_tick or row.last_observed_tick != row.observed_tick or
                row.last_observed_tick + row.age_ticks != snapshot.evaluated_at_tick):
            raise ValueError('observation_evaluation_binding_mismatch')
        if exposure:
            _text(row.option_id)
            _text(row.exposure_context_id)
            if type(row.exposure) is not OptionExposureState:
                raise TypeError('explicit_exposure_required')
            key = (row.option_id, row.exposure_context_id)
        else:
            _text(row.coverage_context_id)
            if type(row.coverage) is not StrategicCoverageState:
                raise TypeError('explicit_coverage_required')
            key = row.coverage_context_id
        if key in index:
            raise ValueError('duplicate_context_evidence')
        index[key] = row
    return index


def _aligned_use(evidence, evaluated_tick, risk_tick):
    if evidence is None:
        return EvidenceUseStatus.ABSENT
    return EvidenceUseStatus.CURRENT if evaluated_tick == risk_tick else EvidenceUseStatus.HISTORICAL


def _observation_use(evidence, evaluated_tick, risk_tick):
    if evidence is None:
        return EvidenceUseStatus.ABSENT
    if evidence.temporal_status is TemporalStatus.FRESH and evaluated_tick == risk_tick:
        return EvidenceUseStatus.CURRENT
    return EvidenceUseStatus.HISTORICAL


def build_risk_evidence(
        threat_state_snapshot: ThreatStateSnapshot,
        threat_relevance_snapshot: ThreatRelevanceSnapshot,
        strategic_coverage_snapshot: StrategicCoverageSnapshot,
        option_exposure_snapshot: OptionExposureSnapshot,
        bindings: tuple[RiskEvidenceBinding, ...],
) -> RiskEvidenceSnapshot:
    """Compose only explicitly requested contexts, preserving every threat subject.

    IDs provide deterministic lineage, not source authentication. No evidence
    combination is classified as risk, safety or an action recommendation.
    """
    snapshots = (threat_state_snapshot, threat_relevance_snapshot,
                 strategic_coverage_snapshot, option_exposure_snapshot)
    expected = (ThreatStateSnapshot, ThreatRelevanceSnapshot, StrategicCoverageSnapshot, OptionExposureSnapshot)
    for snapshot, contract in zip(snapshots, expected):
        if type(snapshot) is not contract:
            raise TypeError('exact_semantic_snapshot_required')
        _text(snapshot.timeline_id)
        _text(snapshot.selected_clock_id)
    if len({s.timeline_id for s in snapshots}) != 1:
        raise ValueError('timeline_mismatch')
    if len({s.selected_clock_id for s in snapshots}) != 1:
        raise ValueError('clock_mismatch')
    states, relevances = _threat_indices(threat_state_snapshot, threat_relevance_snapshot)
    coverages = _observation_index(strategic_coverage_snapshot, False)
    exposures = _observation_index(option_exposure_snapshot, True)
    if type(bindings) is not tuple or any(type(b) is not RiskEvidenceBinding for b in bindings):
        raise TypeError('binding_tuple_required')
    for binding in bindings:
        for value in _binding_values(binding):
            _text(value)
    if len({(b.risk_context_id, b.option_id) for b in bindings}) != len(bindings):
        raise ValueError('duplicate_risk_option_binding')
    tick = max(threat_state_snapshot.assembly_tick, threat_relevance_snapshot.evaluated_at_tick,
               strategic_coverage_snapshot.evaluated_at_tick, option_exposure_snapshot.evaluated_at_tick)
    bundles = []
    for binding in sorted(bindings, key=_binding_values):
        coverage = coverages.get(binding.coverage_context_id)
        exposure = exposures.get((binding.option_id, binding.exposure_context_id))
        threats = []
        for threat_id, state in sorted(states.items()):
            relevance = relevances.get(threat_id)
            if relevance is not None and relevance.relevance_context_id != binding.relevance_context_id:
                relevance = None
            threats.append(ThreatRiskEvidence(
                threat_id, state, _aligned_use(state, threat_state_snapshot.assembly_tick, tick),
                relevance, _aligned_use(relevance, threat_relevance_snapshot.evaluated_at_tick, tick)))
        bundles.append(OptionRiskEvidenceBundle(
            *_binding_values(binding), tick,
            coverage, _observation_use(coverage, strategic_coverage_snapshot.evaluated_at_tick, tick),
            exposure, _observation_use(exposure, option_exposure_snapshot.evaluated_at_tick, tick), tuple(threats)))
    return RiskEvidenceSnapshot(
        threat_state_snapshot.timeline_id, threat_state_snapshot.selected_clock_id,
        threat_state_snapshot.snapshot_id, threat_relevance_snapshot.snapshot_id,
        strategic_coverage_snapshot.snapshot_id, option_exposure_snapshot.snapshot_id, tick, tuple(bundles))
