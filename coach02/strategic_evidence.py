"""Pure envelope assembly. No new gameplay interpretation or live invocation."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json

from .context_builder import DecisionContextSeed
from .decision import Action, Claim, Execution, ObservedFact, OptionAssessment, PRODUCTIVE_ACTIONS
from .farm_context import FarmStrategicEvidence
from .option_availability import OptionAvailabilityEvidence
from .option_safety import OptionSafetyEvidence
from .safety_evidence import RiskAwarenessEvidence


@dataclass(frozen=True)
class FarmOptionEvidencePair:
    option_id: str
    action: Action
    availability: OptionAvailabilityEvidence
    safety: OptionSafetyEvidence


@dataclass(frozen=True)
class FarmEvidenceAssembly:
    assembly_id: str
    seed_id: str
    risk: RiskAwarenessEvidence
    option_pairs: tuple[FarmOptionEvidencePair, ...]
    strategic_evidence: FarmStrategicEvidence
    execution: Execution
    ruleset: str


RULESET = 'strategic.farm_evidence_assembly.v1'


def _facts(observations):
    if type(observations) is not tuple:
        raise TypeError('observed_fact_tuple_required')
    result = {}
    for fact in observations:
        if not isinstance(fact, ObservedFact) or type(fact.ref) is not str or not fact.ref:
            raise ValueError('invalid_assembly_fact')
        if fact.ref in result and result[fact.ref] != fact:
            raise ValueError('conflicting_observation_ref:' + fact.ref)
        result[fact.ref] = fact
    return result


def _merge(destination, source):
    for ref, fact in source.items():
        if ref in destination and destination[ref] != fact:
            raise ValueError('conflicting_observation_ref:' + ref)
        destination[ref] = fact


def _support(claim, facts):
    if not isinstance(claim, Claim) or type(claim.rule_ref) is not str or not claim.rule_ref:
        raise ValueError('invalid_assembly_claim')
    for ref in claim.evidence_refs:
        if type(ref) is not str or ref not in facts:
            raise ValueError('missing_claim_support')


def _envelope(envelope):
    if (type(envelope.evidence_id) is not str or not envelope.evidence_id
            or type(envelope.ruleset) is not str or not envelope.ruleset
            or type(envelope.reasons) is not tuple
            or any(not isinstance(reason, str) for reason in envelope.reasons)):
        raise ValueError('invalid_evidence_metadata')
    return _facts(envelope.observations)


def _index(envelopes, kind, label):
    if type(envelopes) is not tuple or any(not isinstance(e, kind) for e in envelopes):
        raise TypeError(label + '_evidence_tuple_required')
    result = {}
    for envelope in envelopes:
        identity = envelope.option_id
        if (type(identity) is not str or not identity or identity.startswith('@')
                or not isinstance(envelope.action, Action) or envelope.action not in PRODUCTIVE_ACTIONS):
            raise ValueError('invalid_farm_option_identity')
        if identity in result:
            raise ValueError('duplicate_' + label + '_option_id')
        result[identity] = envelope
    return result


def assemble_farm_evidence(seed: DecisionContextSeed, risk: RiskAwarenessEvidence,
        safety: tuple[OptionSafetyEvidence, ...], availability: tuple[OptionAvailabilityEvidence, ...],
        execution: Execution) -> FarmEvidenceAssembly:
    """Validate bindings/support and preserve Claims; stop before context/planner.

    Eligibility stays with compose_farm_context. Evidence validity here means
    structural consistency, not verified gameplay truth or authenticated authorship.
    """
    if not isinstance(seed, DecisionContextSeed) or type(seed.seed_id) is not str or not seed.seed_id:
        raise TypeError('decision_context_seed_required')
    if not isinstance(risk, RiskAwarenessEvidence):
        raise TypeError('risk_awareness_evidence_required')
    if risk.seed_id != seed.seed_id:
        raise ValueError('risk_seed_mismatch')
    if not isinstance(execution, Execution):
        raise TypeError('execution_required')
    if execution.plan_id is not None and type(execution.plan_id) is not str:
        raise ValueError('execution_plan_reference_must_be_string')
    risk_facts = _envelope(risk)
    _support(risk.increased_risk, risk_facts)
    safety_by_id = _index(safety, OptionSafetyEvidence, 'safety')
    availability_by_id = _index(availability, OptionAvailabilityEvidence, 'availability')
    if safety_by_id.keys() - availability_by_id.keys():
        raise ValueError('unpaired_option_safety')
    if availability_by_id.keys() - safety_by_id.keys():
        raise ValueError('unpaired_option_availability')

    # option_id is a lookup index only. Acceptance requires all three identities
    # and the exact upstream risk binding before any Claim is extracted.
    pairs = []
    actions = set()
    for identity in sorted(safety_by_id):
        safe = safety_by_id[identity]
        available = availability_by_id[identity]
        safe.validate_binding(seed.seed_id, risk)
        available.validate_binding(seed.seed_id, safe.option_id, safe.action)
        if safe.action in actions:
            raise ValueError('multiple_options_per_action_not_supported')
        actions.add(safe.action)
        pairs.append(FarmOptionEvidencePair(identity, safe.action, available, safe))

    merged = dict(risk_facts)
    assessments = []
    for pair in pairs:
        safe_facts = _envelope(pair.safety)
        available_facts = _envelope(pair.availability)
        # Safety may cite its accepted upstream Risk facts. Availability is local
        # to its own envelope; sibling options cannot backfill missing support.
        safe_support = dict(risk_facts)
        _merge(safe_support, safe_facts)
        _support(pair.safety.safety, safe_support)
        _support(pair.availability.availability, available_facts)
        _merge(merged, safe_facts)
        _merge(merged, available_facts)
        assessments.append(OptionAssessment(pair.option_id, pair.action,
                           pair.availability.availability, pair.safety.safety))
    strategic = FarmStrategicEvidence(seed.seed_id, tuple(merged[ref] for ref in sorted(merged)),
                                     tuple(assessments), risk.increased_risk)
    result = FarmEvidenceAssembly('', seed.seed_id, risk, tuple(pairs), strategic, execution, RULESET)
    payload = asdict(result)
    payload.pop('assembly_id')
    # Include complete envelope content as well as upstream IDs. Observation order
    # is not semantic; normalize only the hash copy, never the retained envelopes.
    def canonical(value):
        if isinstance(value, dict):
            return {k: (sorted((canonical(f) for f in v), key=lambda f: f['ref'])
                        if k == 'observations' else canonical(v)) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [canonical(v) for v in value]
        return value
    encoded = json.dumps(canonical(payload), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return replace(result, assembly_id=RULESET + ':' + hashlib.sha256(encoded).hexdigest())
