"""Versioned reachability extension of accepted Risk Evidence v0.1.

Base bundles and threat rows are retained intact. No original axis is rebuilt,
reclassified or refreshed. Reachability remains evidence, never a risk verdict.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from .risk_evidence_assembly import (
    RiskEvidenceSnapshot, OptionRiskEvidenceBundle, ThreatRiskEvidence, EvidenceUseStatus,
)
from .threat_reachability import (
    ThreatReachabilitySnapshot, ThreatReachabilityAssessment, ThreatReachability,
)


RULESET = 'risk.evidence_assembly.v2'


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty_identity_required')


def _tick(value):
    if type(value) is not int:
        raise TypeError('integer_tick_required')


def _binding_values(binding):
    return (binding.risk_context_id, binding.option_id, binding.reachability_context_id,
            binding.horizon_id, binding.reachability_binding_policy_id)


@dataclass(frozen=True)
class RiskEvidenceReachabilityBinding:
    risk_context_id: str
    option_id: str
    reachability_context_id: str
    horizon_id: str
    reachability_binding_policy_id: str

    def __post_init__(self):
        for value in _binding_values(self):
            _text(value)


@dataclass(frozen=True)
class ThreatRiskEvidenceV2:
    base_threat_evidence: ThreatRiskEvidence
    reachability_assessment: ThreatReachabilityAssessment | None
    reachability_use: EvidenceUseStatus


@dataclass(frozen=True)
class OptionRiskEvidenceBundleV2:
    base_bundle: OptionRiskEvidenceBundle
    reachability_context_id: str
    horizon_id: str
    reachability_binding_policy_id: str
    threats: tuple[ThreatRiskEvidenceV2, ...]


@dataclass(frozen=True)
class RiskEvidenceSnapshotV2:
    timeline_id: str
    selected_clock_id: str
    base_risk_evidence_snapshot_id: str
    threat_reachability_snapshot_id: str
    risk_assembly_tick: int
    bundles: tuple[OptionRiskEvidenceBundleV2, ...]

    @property
    def snapshot_id(self) -> str:
        content = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode('utf-8')
        return RULESET + ':snapshot:' + hashlib.sha256(content).hexdigest()


def _state_binding(state, threat_id, evaluated_tick):
    # The accepted parent contracts own state semantics and nested provenance.
    # Only the subject and evaluation binding are checked here.
    if state is None:
        raise ValueError('preserved_state_required')
    _text(state.threat_id)
    _tick(state.assembly_tick)
    if state.threat_id != threat_id or state.assembly_tick != evaluated_tick:
        raise ValueError('preserved_state_lineage_mismatch')


def _base_index(base, reachability_tick):
    if type(base.bundles) is not tuple:
        raise TypeError('base_bundle_tuple_required')
    bundles, states = {}, {}
    for bundle in base.bundles:
        if type(bundle) is not OptionRiskEvidenceBundle:
            raise TypeError('exact_base_bundle_required')
        for value in (bundle.risk_context_id, bundle.option_id, bundle.relevance_context_id,
                      bundle.coverage_context_id, bundle.exposure_context_id, bundle.binding_policy_id):
            _text(value)
        _tick(bundle.risk_assembly_tick)
        if bundle.risk_assembly_tick != base.risk_assembly_tick:
            raise ValueError('base_bundle_tick_mismatch')
        key = (bundle.risk_context_id, bundle.option_id)
        if key in bundles:
            raise ValueError('duplicate_base_bundle')
        bundles[key] = bundle
        if type(bundle.threats) is not tuple:
            raise TypeError('base_threat_tuple_required')
        subjects = set()
        for row in bundle.threats:
            if type(row) is not ThreatRiskEvidence:
                raise TypeError('exact_base_threat_required')
            _text(row.threat_id)
            if row.threat_id in subjects:
                raise ValueError('duplicate_base_threat')
            subjects.add(row.threat_id)
            _state_binding(row.state_assessment, row.threat_id, reachability_tick)
            if row.threat_id in states and row.state_assessment != states[row.threat_id]:
                raise ValueError('inconsistent_preserved_state')
            states[row.threat_id] = row.state_assessment
            for use in (row.state_use, row.relevance_use):
                if type(use) is not EvidenceUseStatus:
                    raise TypeError('accepted_base_use_required')
        for use in (bundle.coverage_use, bundle.exposure_use):
            if type(use) is not EvidenceUseStatus:
                raise TypeError('accepted_base_use_required')
    return bundles, states


def _reachability_index(snapshot, states, has_base_bundles):
    if type(snapshot.assessments) is not tuple:
        raise TypeError('reachability_assessment_tuple_required')
    index = {}
    for row in snapshot.assessments:
        if type(row) is not ThreatReachabilityAssessment:
            raise TypeError('exact_reachability_assessment_required')
        key = (row.threat_id, row.option_id, row.reachability_context_id, row.horizon_id)
        for value in (*key, row.assessment_policy_id):
            _text(value)
        if type(row.reachability) is not ThreatReachability:
            raise TypeError('explicit_reachability_required')
        _state_binding(row.threat_state_assessment, row.threat_id, snapshot.evaluated_at_tick)
        if has_base_bundles and row.threat_id not in states:
            raise ValueError('reachability_subject_outside_base_state')
        if row.threat_id in states and (type(row.threat_state_assessment) is not type(states[row.threat_id]) or
                                       row.threat_state_assessment != states[row.threat_id]):
            raise ValueError('reachability_preserved_state_mismatch')
        if key in index:
            raise ValueError('duplicate_reachability_assessment')
        index[key] = row
    return index


def build_risk_evidence_v2(
        risk_evidence_v1: RiskEvidenceSnapshot,
        threat_reachability_snapshot: ThreatReachabilitySnapshot,
        bindings: tuple[RiskEvidenceReachabilityBinding, ...],
) -> RiskEvidenceSnapshotV2:
    """Extend every base bundle without changing its data or accepted use statuses.

    V02_TEMPORAL_EXTENSION_ALIGNMENT_RULE: reachability cannot advance the base
    risk tick, since v0.2 cannot rewrite the meaning of its CURRENT statuses.
    """
    base, reachability = risk_evidence_v1, threat_reachability_snapshot
    if type(base) is not RiskEvidenceSnapshot or type(reachability) is not ThreatReachabilitySnapshot:
        raise TypeError('exact_accepted_snapshots_required')
    for snapshot in (base, reachability):
        _text(snapshot.timeline_id)
        _text(snapshot.selected_clock_id)
        _text(snapshot.threat_state_snapshot_id)
    for value in (base.threat_relevance_snapshot_id, base.strategic_coverage_snapshot_id,
                  base.option_exposure_snapshot_id):
        _text(value)
    if (base.timeline_id, base.selected_clock_id) != (reachability.timeline_id, reachability.selected_clock_id):
        raise ValueError('timeline_or_clock_mismatch')
    if base.threat_state_snapshot_id != reachability.threat_state_snapshot_id:
        raise ValueError('threat_state_snapshot_lineage_mismatch')
    _tick(base.risk_assembly_tick)
    _tick(reachability.evaluated_at_tick)
    tick = max(base.risk_assembly_tick, reachability.evaluated_at_tick)
    if tick != base.risk_assembly_tick:
        raise ValueError('V02_TEMPORAL_EXTENSION_ALIGNMENT_RULE')
    base_bundles, states = _base_index(base, reachability.evaluated_at_tick)
    assessments = _reachability_index(reachability, states, bool(base_bundles))
    if type(bindings) is not tuple or any(type(b) is not RiskEvidenceReachabilityBinding for b in bindings):
        raise TypeError('exact_extension_binding_tuple_required')
    extensions = {}
    for binding in bindings:
        for value in _binding_values(binding):
            _text(value)
    for binding in sorted(bindings, key=_binding_values):
        key = (binding.risk_context_id, binding.option_id)
        if key in extensions:
            raise ValueError('duplicate_extension_binding')
        extensions[key] = binding
    if set(extensions) != set(base_bundles):
        raise ValueError('exactly_one_extension_per_base_bundle_required')
    selected_use = (EvidenceUseStatus.CURRENT if reachability.evaluated_at_tick == tick
                    else EvidenceUseStatus.HISTORICAL)
    bundles = []
    # Accepted v0.1 ordering is authoritative; binding input order is irrelevant.
    for base_bundle in base.bundles:
        binding = extensions[(base_bundle.risk_context_id, base_bundle.option_id)]
        threats = []
        for base_row in base_bundle.threats:
            assessment = assessments.get((base_row.threat_id, base_bundle.option_id,
                                           binding.reachability_context_id, binding.horizon_id))
            threats.append(ThreatRiskEvidenceV2(base_row, assessment,
                EvidenceUseStatus.ABSENT if assessment is None else selected_use))
        bundles.append(OptionRiskEvidenceBundleV2(base_bundle, binding.reachability_context_id,
            binding.horizon_id, binding.reachability_binding_policy_id, tuple(threats)))
    return RiskEvidenceSnapshotV2(base.timeline_id, base.selected_clock_id, base.snapshot_id,
                                  reachability.snapshot_id, tick, tuple(bundles))
