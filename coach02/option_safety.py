"""Pure option exposure assessment. Heuristic acceptability, never guaranteed safety."""
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json

from .decision import (Action, Claim, Freshness, ObservedFact, ObservationSource,
                       PRODUCTIVE_ACTIONS, Truth)
from .safety_evidence import RiskAwarenessEvidence


class Exposure(str, Enum):
    LOW = 'LOW'
    HIGH = 'HIGH'
    UNKNOWN = 'UNKNOWN'


class OptionSafetyReason(str, Enum):
    HIGH_EXPOSURE_WITH_INCREASED_RISK_AND_NO_COVERAGE = 'safety.option.high_risk_exposed_uncovered.v1'
    LOW_EXPOSURE_WITH_LOW_RISK_AND_COVERAGE = 'safety.option.low_risk_low_exposure_covered.v1'
    GLOBAL_RISK_UNKNOWN = 'safety.option.global_risk_unknown.v1'
    GLOBAL_RISK_INCREASED_BUT_OPTION_MITIGATED = 'safety.option.increased_risk_mitigated.v1'
    GLOBAL_RISK_LOW_BUT_OPTION_EXPOSURE_HIGH = 'safety.option.low_risk_high_exposure.v1'
    OPTION_EXPOSURE_UNKNOWN = 'safety.option.exposure_unknown.v1'
    OPTION_EXPOSURE_STALE = 'safety.option.exposure_stale.v1'
    OPTION_COVERAGE_UNKNOWN = 'safety.option.coverage_unknown.v1'
    OPTION_COVERAGE_STALE = 'safety.option.coverage_stale.v1'
    INSUFFICIENT_OPTION_SAFETY_SUPPORT = 'safety.option.insufficient_support.v1'


def _seed_id(value):
    if type(value) is not str or not value:
        raise ValueError('seed_binding_required')


@dataclass(frozen=True)
class FarmOptionSafetyObservation:
    seed_id: str
    option_id: str
    action: Action
    exposure: Exposure
    exposure_freshness: Freshness
    coverage: Truth
    coverage_freshness: Freshness

    def __post_init__(self):
        _seed_id(self.seed_id)
        if (type(self.option_id) is not str or not self.option_id or not self.option_id.isascii()
                or not all(c.isalnum() or c in '_-' for c in self.option_id)):
            raise ValueError('invalid_option_id')
        if not isinstance(self.action, Action) or self.action not in PRODUCTIVE_ACTIONS:
            raise ValueError('invalid_farm_action')
        if (not isinstance(self.exposure, Exposure) or not isinstance(self.coverage, Truth)
                or not isinstance(self.exposure_freshness, Freshness)
                or not isinstance(self.coverage_freshness, Freshness)):
            raise ValueError('invalid_option_observation')


@dataclass(frozen=True)
class OptionSafetyEvidence:
    evidence_id: str
    seed_id: str
    option_id: str
    action: Action
    observations: tuple[ObservedFact, ...]
    safety: Claim
    reasons: tuple[OptionSafetyReason, ...]
    ruleset: str
    upstream_risk_evidence_id: str

    def validate_binding(self, seed_id: str, risk: RiskAwarenessEvidence) -> None:
        """Required before unpacking into legacy composition, which has no risk ID.

        Check exact seed and upstream identity; no availability or action selection.
        Retain the evidence envelope and upstream risk for audit after composition.
        """
        _check_risk(seed_id, risk)
        if self.seed_id != seed_id:
            raise ValueError('option_safety_seed_mismatch')
        if self.upstream_risk_evidence_id != risk.evidence_id:
            raise ValueError('option_safety_risk_mismatch')


RULESET = 'safety.option_assessment.v1'


def _check_risk(seed_id, risk):
    _seed_id(seed_id)
    if not isinstance(risk, RiskAwarenessEvidence):
        raise TypeError('risk_awareness_evidence_required')
    if risk.seed_id != seed_id:
        raise ValueError('risk_seed_mismatch')
    if type(risk.evidence_id) is not str or not risk.evidence_id:
        raise ValueError('risk_evidence_identity_required')
    if (type(risk.observations) is not tuple
            or any(not isinstance(f, ObservedFact) or f.source is not ObservationSource.SAFETY_EVIDENCE
                   or type(f.ref) is not str or not f.ref.startswith('safety.') for f in risk.observations)):
        raise ValueError('invalid_risk_observations')
    facts = {f.ref: f for f in risk.observations}
    if len(facts) != len(risk.observations):
        raise ValueError('duplicate_risk_observation')
    claim = risk.increased_risk
    if (not isinstance(claim, Claim) or any(type(ref) is not str or ref not in facts
                                          for ref in claim.evidence_refs)):
        raise ValueError('missing_risk_support')
    # Validate only the accepted support contract; never recalculate threat rules.
    if claim.value != Truth.UNKNOWN and (not claim.evidence_refs or any(
            facts[ref].value == Truth.UNKNOWN or facts[ref].freshness != Freshness.FRESH
            for ref in claim.evidence_refs)):
        raise ValueError('unsupported_risk_claim')


def build_option_safety(seed_id: str, risk: RiskAwarenessEvidence,
                        options: tuple[FarmOptionSafetyObservation, ...]) -> tuple[OptionSafetyEvidence, ...]:
    """Assess only requested options, identically across productive action types.

    YES: acceptable under this narrow heuristic, not guaranteed safe.
    NO: not supported as acceptable under these conditions, not death certainty.
    UNKNOWN: insufficient evidence for YES or NO. Availability is never inferred.
    """
    _check_risk(seed_id, risk)
    if type(options) is not tuple or any(not isinstance(o, FarmOptionSafetyObservation) for o in options):
        raise TypeError('option_observation_tuple_required')
    if any(o.seed_id != seed_id for o in options):
        raise ValueError('option_observation_seed_mismatch')
    if len({o.option_id for o in options}) != len(options):
        raise ValueError('duplicate_option_id')
    return tuple(_assess(risk, o) for o in sorted(options, key=lambda o: o.option_id))


def _assess(risk, option):
    prefix = 'safety.option.' + option.option_id + '.'
    low_ref, high_ref, coverage_ref = (prefix + name for name in
                                     ('exposure_low', 'exposure_high', 'coverage_sufficient'))
    facts = tuple(ObservedFact(ref,
        Truth.UNKNOWN if option.exposure == Exposure.UNKNOWN else Truth.YES if option.exposure == state else Truth.NO,
        option.exposure_freshness, source=ObservationSource.SAFETY_EVIDENCE)
        for ref, state in ((low_ref, Exposure.LOW), (high_ref, Exposure.HIGH)))
    facts += (ObservedFact(coverage_ref, option.coverage, option.coverage_freshness,
                           source=ObservationSource.SAFETY_EVIDENCE),)
    observations = tuple(sorted(risk.observations + facts, key=lambda f: f.ref))
    if len({f.ref for f in observations}) != len(observations):
        raise ValueError('risk_option_reference_collision')
    current = option.exposure_freshness == option.coverage_freshness == Freshness.FRESH
    value = Truth.UNKNOWN
    refs = (low_ref, high_ref, coverage_ref)
    if (current and risk.increased_risk.value == Truth.YES and option.exposure == Exposure.HIGH
            and option.coverage == Truth.NO):
        value, refs = Truth.NO, (high_ref, coverage_ref)
        reasons = (OptionSafetyReason.HIGH_EXPOSURE_WITH_INCREASED_RISK_AND_NO_COVERAGE,)
    elif (current and risk.increased_risk.value == Truth.NO and option.exposure == Exposure.LOW
          and option.coverage == Truth.YES):
        value, refs = Truth.YES, (low_ref, coverage_ref)
        reasons = (OptionSafetyReason.LOW_EXPOSURE_WITH_LOW_RISK_AND_COVERAGE,)
    else:
        reasons_list = []
        if risk.increased_risk.value == Truth.UNKNOWN: reasons_list.append(OptionSafetyReason.GLOBAL_RISK_UNKNOWN)
        if option.exposure == Exposure.UNKNOWN: reasons_list.append(OptionSafetyReason.OPTION_EXPOSURE_UNKNOWN)
        if option.exposure_freshness == Freshness.STALE: reasons_list.append(OptionSafetyReason.OPTION_EXPOSURE_STALE)
        if option.coverage == Truth.UNKNOWN: reasons_list.append(OptionSafetyReason.OPTION_COVERAGE_UNKNOWN)
        if option.coverage_freshness == Freshness.STALE: reasons_list.append(OptionSafetyReason.OPTION_COVERAGE_STALE)
        if current and risk.increased_risk.value == Truth.YES and (option.exposure == Exposure.LOW or option.coverage == Truth.YES):
            reasons_list.append(OptionSafetyReason.GLOBAL_RISK_INCREASED_BUT_OPTION_MITIGATED)
        if current and risk.increased_risk.value == Truth.NO and option.exposure == Exposure.HIGH:
            reasons_list.append(OptionSafetyReason.GLOBAL_RISK_LOW_BUT_OPTION_EXPOSURE_HIGH)
        reasons = tuple(reasons_list) or (OptionSafetyReason.INSUFFICIENT_OPTION_SAFETY_SUPPORT,)
    refs = tuple(sorted(set(risk.increased_risk.evidence_refs + refs)))
    rule = reasons[0].value if value != Truth.UNKNOWN else OptionSafetyReason.INSUFFICIENT_OPTION_SAFETY_SUPPORT.value
    result = OptionSafetyEvidence('', option.seed_id, option.option_id, option.action, observations,
                                  Claim(value, refs, rule), reasons, RULESET, risk.evidence_id)
    payload = asdict(result)
    payload.pop('evidence_id')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return replace(result, evidence_id=RULESET + ':' + hashlib.sha256(encoded).hexdigest())
