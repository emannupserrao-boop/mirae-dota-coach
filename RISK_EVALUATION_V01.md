# Risk Evaluation v0.1

Risk Evaluation is the first deterministic policy that interprets the accepted
Risk Evidence v0.2 composition. It evaluates each explicit option/risk context
independently. Its only production input is `RiskEvidenceSnapshotV2`.

**SUPPORTED does not mean UNSAFE.**

**NOT_ESTABLISHED does not mean SAFE.**

**INDETERMINATE is not a danger level.**

**Positive evidence and negative evidence are intentionally asymmetric.**

**Coverage incompleteness does not erase known positive risk.**

**Negative risk conclusions require CURRENT SUFFICIENT coverage.**

**Risk Evaluation v0.1 does not rank options.**

**Risk Evaluation v0.1 does not issue actions.**

**Threat State semantic category does not define severity.**

**Risk Evaluation consumes accepted Risk Evidence v0.2 without recomputing it.**

## API and fixed policy

`evaluate_risk(snapshot: RiskEvidenceSnapshotV2) -> RiskEvaluationSnapshot`

Policy identity: `risk.evaluation.conservative.v1`. This identity is owned by the
implementation, is not a caller parameter, and appears in the snapshot and every
option evaluation. A semantic policy change requires a new version.

Ruleset: `risk.evaluation.v1`.

| RiskConclusion | Meaning for this exact option/risk context |
|---|---|
| SUPPORTED | Accepted current evidence positively supports modeled risk. |
| NOT_ESTABLISHED | Evidence is sufficiently resolved under this policy and does not establish modeled risk. |
| INDETERMINATE | Evidence authorizes neither of the other conclusions. |

There is no numeric or ordinal magnitude, probability, confidence number, damage
estimate, severity, threat-count score, reward, expected value, opportunity cost,
or action authority. One contributor and five contributors both produce SUPPORTED
when exposure is current and EXPOSED.

## Threat contribution and precedence

`ThreatContributionStatus` has exactly CONTRIBUTING, NON_CONTRIBUTING, and
INDETERMINATE. These are categorical contributions, not threat magnitudes.

The first matching rule supplies the single auditable reason:

| Precedence | Accepted evidence | Contribution / reason |
|---|---|---|
| 1 | CURRENT relevance NOT_RELEVANT | NON_CONTRIBUTING / NOT_RELEVANT |
| 2 | CURRENT reachability CANNOT_AFFECT | NON_CONTRIBUTING / CANNOT_AFFECT |
| 3 | state_use not CURRENT | INDETERMINATE / STATE_NOT_CURRENT |
| 4 | relevance ABSENT | INDETERMINATE / RELEVANCE_ABSENT |
| 5 | relevance HISTORICAL | INDETERMINATE / RELEVANCE_HISTORICAL |
| 6 | CURRENT relevance UNKNOWN | INDETERMINATE / RELEVANCE_UNKNOWN |
| 7 | reachability ABSENT | INDETERMINATE / REACHABILITY_ABSENT |
| 8 | reachability HISTORICAL | INDETERMINATE / REACHABILITY_HISTORICAL |
| 9 | CURRENT reachability UNKNOWN | INDETERMINATE / REACHABILITY_UNKNOWN |
| 10 | CURRENT state, CURRENT RELEVANT, CURRENT CAN_AFFECT | CONTRIBUTING / RELEVANT_AND_CAN_AFFECT |

Any unhandled combination is rejected. Concrete enums are required; matching
strings or unrelated enum classes do not qualify. All structural validation
happens before policy evaluation, so a negative short-circuit cannot conceal an
invalid axis elsewhere in the snapshot.

Current NOT_RELEVANT wins even with absent/unknown reachability or old state.
Current CANNOT_AFFECT wins even with absent/unknown relevance or old state.
Neither means the threat is globally harmless. Historical negative evidence does
not activate these short-circuits. If both current negatives occur, NOT_RELEVANT
is the reason by precedence.

When state_use is CURRENT, every accepted state category can contribute:
VISIBLE_NEARBY, VISIBLE_AWAY, MISSING, UNKNOWN, and CONFLICTED. Reachability already
assessed the accepted state. This policy neither reinterprets state semantics nor
adds a proximity rule. The complete state provenance remains in the output.

## Bundle conclusion and precedence

1. ABSENT exposure yields INDETERMINATE / EXPOSURE_ABSENT. HISTORICAL exposure
   yields EXPOSURE_HISTORICAL. CURRENT UNKNOWN yields EXPOSURE_UNKNOWN. These
   conditions prevent both positive and negative conclusions.
2. CURRENT EXPOSED with any CONTRIBUTING threat yields SUPPORTED /
   CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT. It wins despite other indeterminate
   threats and despite coverage ABSENT, HISTORICAL, INSUFFICIENT, or UNKNOWN.
3. CURRENT NOT_EXPOSED with a CONTRIBUTING threat yields INDETERMINATE /
   NOT_EXPOSED_WITH_CONTRIBUTING_THREAT. Mixed evidence is retained, without
   declaring an upstream contradiction.
4. Otherwise any INDETERMINATE threat yields INDETERMINATE /
   THREAT_EVIDENCE_INDETERMINATE, before examining coverage.
5. With no contributors and no indeterminate threats, coverage ABSENT,
   HISTORICAL, CURRENT INSUFFICIENT, or CURRENT UNKNOWN respectively yields
   INDETERMINATE with COVERAGE_ABSENT, COVERAGE_HISTORICAL,
   COVERAGE_INSUFFICIENT, or COVERAGE_UNKNOWN.
6. Only CURRENT SUFFICIENT coverage with CURRENT EXPOSED or NOT_EXPOSED and all
   threats NON_CONTRIBUTING yields NOT_ESTABLISHED /
   SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT.

Zero threat rows make the resolved threat condition vacuously true, but the
exposure and coverage preconditions still apply. Zero rows alone never mean no
risk. Empty input bundles produce an empty evaluation tuple: no option/risk
contexts were evaluated; no implicit negative conclusion is created.

## Preserved contracts and defensive boundary

Frozen `ThreatRiskEvaluation` contains threat_id, contribution, reason, and the
exact complete `ThreatRiskEvidenceV2` object as base_threat_evidence.

Frozen `OptionRiskEvaluation` contains risk_context_id, option_id, conclusion,
reason, evaluation_policy_id, risk_assembly_tick, threat_evaluations, and the
exact complete `OptionRiskEvidenceBundleV2` object as base_bundle.

Frozen `RiskEvaluationSnapshot` contains timeline_id, selected_clock_id,
risk_evidence_snapshot_id, risk_assembly_tick, evaluation_policy_id, evaluations,
and a computed snapshot_id. No new clock or tick is introduced.

Every explicit bundle and every threat row is retained one-to-one, including
negative and indeterminate rows. Accepted v0.2 canonical bundle and threat order
is preserved, independent of conclusions. Nothing is compared, filtered, ranked,
or invented. Input objects are not mutated or reconstructed.

Production imports exactly four public contracts from risk_evidence_assembly_v02:
RiskEvidenceSnapshotV2, OptionRiskEvidenceBundleV2, ThreatRiskEvidenceV2, and
EvidenceUseStatus. Concrete nested types and enums are read from those accepted
dataclass field annotations. These are fixed schema references, never types
inferred from caller values, dynamic module imports, enum-string coercions, or
calls to lower constructors. This permits exact enum checks without editing v0.2
or directly importing any lower semantic domain.

Validation checks exact snapshot/bundle/row types, tuple containers, unique
option/risk keys and threat IDs, concrete integer risk ticks excluding bool,
nonblank header and binding IDs, matching bundle/header risk tick, preserved base
row correspondence, concrete evidence use and semantic enums, and None pairing
for ABSENT optional axes. Required state evidence and its subject are checked.
Malformed input fails atomically with TypeError or ValueError.

Validation does not reproduce v0.2's evidence derivation, currentness, freshness,
context selection, or temporal/lineage policy. The supplied accepted statuses are
authoritative. Exact nested evidence is preserved even when it cannot support a
conclusion. Historical positive evidence is never treated as current.

## Deterministic identity

`risk.evaluation.v1:snapshot:` plus SHA-256 of `asdict(snapshot)` serialized with
JSON sort_keys=True, compact separators, ensure_ascii=True, and UTF-8.
The computed ID itself is excluded because it is a property rather than a field.

Identity binds the exact upstream v0.2 snapshot ID, timeline, clock, risk tick,
fixed policy identity, every complete base bundle, all threat contributions and
reasons, and every option conclusion and reason. Meaningful input, provenance,
policy, or output changes therefore change identity. Opaque IDs are preserved
without trimming or normalization.

## Legacy Safety review

**NO_DIRECT_PRODUCTION_COMPATIBILITY_V01**

Inspection of safety_evidence.py found RelevantThreatObservation with only
threat_id/state/freshness; its ThreatState lacks CONFLICTED. Its RiskAwarenessEvidence
is seed-bound and carries ObservedFact/Claim truth values generated by a different
nearby/missing/coverage heuristic. It lacks the complete option/context/horizon
composition and accepted CURRENT/HISTORICAL/ABSENT dimensions.

Inspection of option_safety.py found LOW/HIGH/UNKNOWN Exposure and action-bearing
FarmOptionSafetyObservation and OptionSafetyEvidence. Its safety Claim expresses
heuristic acceptability. Mapping NOT_ESTABLISHED to its positive safety value
would be invalid, and mapping INDETERMINATE to legacy UNKNOWN would lose the
precise reasons and provenance. Legacy risk Truth.NO also belongs to a different
policy, so even a superficial three-way enum mapping is not equivalence.

No production compatibility adapter exists. Both legacy modules remain
unchanged and are not imported by Risk Evaluation.

## Future Safety v0.2 handoff

Future Safety v0.2 would consume RiskEvaluationSnapshot together with an explicit
Safety policy, possibly option reward/value, commitment/reversibility, execution
state, strategic objective, future-state cost, and accepted risk tolerance.
It must preserve risk provenance and distinguish risk support from acceptability.
This task implements none of those inputs or policy decisions.

### BLOCKER_BEFORE_RISK_SEVERITY

- No severity model or capability magnitude.
- No player vulnerability or damage/disable model.
- No option commitment/cost model.
- No reward/opportunity-cost integration.

### BLOCKER_BEFORE_SAFETY_V02

- No Safety policy translating risk into safe/unsafe/action tolerance.
- No strategic objective integration.
- No execution/reversibility integration.

### BLOCKER_BEFORE_LIVE

- Synthetic upstream sources.
- Real reachability policy absent.
- Live orchestration absent.

### ACCEPTED_V01_LIMITATION

- Categorical risk support only; no magnitude.
- Conservative policy with explicit positive/negative asymmetry.
- No cross-option comparison.
- No multi-source reliability weighting.

## Dependency and validation scope

The v0.2 reverse-dependency guard admits only coach02/risk_evaluation.py and only
the four named contracts. Builders, constructors, import aliases, module imports,
wildcards, dynamic imports, arbitrary consumers, and live/runtime consumers remain
rejected. Lower-domain guards remain unchanged. Existing production is unchanged.
Any dependent hash maintenance is limited to required literal replacements.

The 104 focused tests cover policy precedence, asymmetric conclusions, all five
state categories, empty contexts and threats, object identity and provenance,
deterministic IDs, malformed boundaries, architecture, purity, and guard denial
cases. Upstream orchestration is confined to synthetic test fixtures. Each
specified validation gate runs once; a failing gate stops acceptance without
repair or retry. Passing project bytes are frozen and committed unchanged.
