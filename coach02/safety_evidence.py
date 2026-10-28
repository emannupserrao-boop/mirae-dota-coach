"""Risk awareness from supplied domain observations. No action or option safety."""
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json

from .decision import Claim, Freshness, ObservedFact, ObservationSource, Truth


class ThreatState(str, Enum):
    VISIBLE_NEARBY = 'VISIBLE_NEARBY'
    VISIBLE_AWAY = 'VISIBLE_AWAY'
    MISSING = 'MISSING'
    UNKNOWN = 'UNKNOWN'


class RiskReason(str, Enum):
    VISIBLE_RELEVANT_THREAT = 'safety.risk.visible_relevant_threat.v1'
    MISSING_THREAT_WITHOUT_COVERAGE = 'safety.risk.missing_without_coverage.v1'
    ALL_RELEVANT_THREATS_VISIBLE_AWAY_WITH_COVERAGE = 'safety.risk.all_away_with_coverage.v1'
    MISSING_THREAT_WITH_COVERAGE = 'safety.risk.missing_with_coverage.v1'
    THREAT_INFORMATION_UNKNOWN = 'safety.risk.threat_unknown.v1'
    THREAT_INFORMATION_STALE = 'safety.risk.threat_stale.v1'
    COVERAGE_UNKNOWN = 'safety.risk.coverage_unknown.v1'
    COVERAGE_STALE = 'safety.risk.coverage_stale.v1'
    NO_RELEVANT_THREAT_EVIDENCE = 'safety.risk.no_threat_evidence.v1'
    INSUFFICIENT_RISK_SUPPORT = 'safety.risk.insufficient_support.v1'


@dataclass(frozen=True)
class RelevantThreatObservation:
    threat_id: str
    state: ThreatState
    freshness: Freshness

    def __post_init__(self):
        # Restrict namespace tokens rather than silently normalizing/colliding IDs.
        if (type(self.threat_id) is not str or not self.threat_id or not self.threat_id.isascii()
                or not all(c.isalnum() or c in '_-' for c in self.threat_id)):
            raise ValueError('invalid_threat_id')
        if not isinstance(self.state, ThreatState) or not isinstance(self.freshness, Freshness):
            raise ValueError('invalid_threat_observation')


@dataclass(frozen=True)
class CoverageObservation:
    sufficient: Truth
    freshness: Freshness

    def __post_init__(self):
        if not isinstance(self.sufficient, Truth) or not isinstance(self.freshness, Freshness):
            raise ValueError('invalid_coverage_observation')


@dataclass(frozen=True)
class RiskAwarenessEvidence:
    evidence_id: str
    seed_id: str
    observations: tuple[ObservedFact, ...]
    increased_risk: Claim
    reasons: tuple[RiskReason, ...]
    ruleset: str


RULESET = 'safety.risk_awareness.v1'
PREDICATES = (ThreatState.VISIBLE_NEARBY, ThreatState.VISIBLE_AWAY, ThreatState.MISSING)
COVERAGE_REF = 'safety.coverage.sufficient'


def _ref(threat, state):
    return 'safety.threat.' + threat.threat_id + '.' + state.value.lower()


def build_risk_awareness(seed_id: str, threats: tuple[RelevantThreatObservation, ...],
                         coverage: CoverageObservation) -> RiskAwarenessEvidence:
    """Bind risk to the caller's exact seed ID; never inspect runtime/hero/content.

    Threat relevance, nearby/away and coverage are caller supplied, not calculated.
    NO is only absence of increased risk under this heuristic, never SAFE.
    """
    if type(seed_id) is not str or not seed_id:
        raise ValueError('seed_binding_required')
    if type(threats) is not tuple or any(not isinstance(t, RelevantThreatObservation) for t in threats):
        raise TypeError('threat_observation_tuple_required')
    if not isinstance(coverage, CoverageObservation):
        raise TypeError('coverage_observation_required')
    if len({t.threat_id for t in threats}) != len(threats):
        raise ValueError('duplicate_threat_id')
    threats = tuple(sorted(threats, key=lambda t: t.threat_id))
    facts = tuple(ObservedFact(_ref(t, state),
        Truth.UNKNOWN if t.state == ThreatState.UNKNOWN else Truth.YES if t.state == state else Truth.NO,
        t.freshness, source=ObservationSource.SAFETY_EVIDENCE)
        for t in threats for state in PREDICATES)
    facts += (ObservedFact(COVERAGE_REF, coverage.sufficient, coverage.freshness,
                          source=ObservationSource.SAFETY_EVIDENCE),)
    facts = tuple(sorted(facts, key=lambda f: f.ref))
    nearby = tuple(_ref(t, ThreatState.VISIBLE_NEARBY) for t in threats
                   if t.state == ThreatState.VISIBLE_NEARBY and t.freshness == Freshness.FRESH)
    missing = tuple(_ref(t, ThreatState.MISSING) for t in threats
                    if t.state == ThreatState.MISSING and t.freshness == Freshness.FRESH)
    if nearby:
        value, refs = Truth.YES, nearby
        reasons = (RiskReason.VISIBLE_RELEVANT_THREAT,)
    elif missing and coverage.sufficient == Truth.NO and coverage.freshness == Freshness.FRESH:
        value, refs = Truth.YES, missing + (COVERAGE_REF,)
        reasons = (RiskReason.MISSING_THREAT_WITHOUT_COVERAGE,)
    elif (threats and all(t.state == ThreatState.VISIBLE_AWAY and t.freshness == Freshness.FRESH for t in threats)
          and coverage.sufficient == Truth.YES and coverage.freshness == Freshness.FRESH):
        value = Truth.NO
        refs = tuple(_ref(t, ThreatState.VISIBLE_AWAY) for t in threats) + (COVERAGE_REF,)
        reasons = (RiskReason.ALL_RELEVANT_THREATS_VISIBLE_AWAY_WITH_COVERAGE,)
    else:
        value, refs = Truth.UNKNOWN, tuple(f.ref for f in facts)
        reasons_list = []
        if not threats: reasons_list.append(RiskReason.NO_RELEVANT_THREAT_EVIDENCE)
        if any(t.state == ThreatState.UNKNOWN for t in threats): reasons_list.append(RiskReason.THREAT_INFORMATION_UNKNOWN)
        if any(t.freshness == Freshness.STALE for t in threats): reasons_list.append(RiskReason.THREAT_INFORMATION_STALE)
        if coverage.sufficient == Truth.UNKNOWN: reasons_list.append(RiskReason.COVERAGE_UNKNOWN)
        if coverage.freshness == Freshness.STALE: reasons_list.append(RiskReason.COVERAGE_STALE)
        if missing and coverage.sufficient == Truth.YES and coverage.freshness == Freshness.FRESH:
            reasons_list.append(RiskReason.MISSING_THREAT_WITH_COVERAGE)
        reasons = tuple(reasons_list) or (RiskReason.INSUFFICIENT_RISK_SUPPORT,)
    # Positive claims depend only on their fresh trigger, so unrelated UNKNOWN or
    # STALE facts remain auditable without invalidating independent positive support.
    rule_ref = reasons[0].value if value != Truth.UNKNOWN else RiskReason.INSUFFICIENT_RISK_SUPPORT.value
    result = RiskAwarenessEvidence('', seed_id, facts, Claim(value, refs, rule_ref), reasons, RULESET)
    payload = asdict(result)
    payload.pop('evidence_id')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return replace(result, evidence_id=RULESET + ':' + hashlib.sha256(encoded).hexdigest())
