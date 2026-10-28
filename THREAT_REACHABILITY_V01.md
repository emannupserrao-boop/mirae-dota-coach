# Threat Reachability Assessment v0.1

CAN_AFFECT does not mean DANGEROUS.

CANNOT_AFFECT does not mean SAFE.

UNKNOWN is first-class.

Reachability is threat-to-option and horizon-bound.

Reachability is not literal physical path reachability.

Threat State does not determine Reachability.

Threat Relevance does not determine Reachability.

Option Exposure does not determine Reachability.

Missing assessment is not UNKNOWN.

v0.1 explicitly receives the classification; it does not calculate it.

## Semantic scope

This layer records that external caller policy P assessed whether threat T can
materially affect option O under reachability context C and strategic horizon H,
against an exact accepted Threat State snapshot. It implements the semantic
contract for a future real policy's output, not that policy.

`ThreatReachability` contains exactly CAN_AFFECT, CANNOT_AFFECT and UNKNOWN,
without aliases. CAN_AFFECT means explicit assessed ability to materially affect
the option inside that context/horizon. CANNOT_AFFECT is explicit assessed
inability in that context/horizon, not permanent harmlessness. UNKNOWN records an
explicit inability to establish affectability. There are no risk, safety or
physical REACHABLE/NOT_REACHABLE enum values.

Strategic affectability may eventually involve physical arrival, mobility,
teleport, global or long-range influence, initiation, contesting or punishing an
option. None of these mechanisms is calculated here. Opaque policy/context names
suggesting global influence do not invoke spell logic.

## Contracts and API

```python
build_threat_reachability(
    threat_state_snapshot: ThreatStateSnapshot,
    claims: tuple[ThreatReachabilityClaim, ...],
) -> ThreatReachabilitySnapshot
```

Frozen `ThreatReachabilityClaim` fields:

- `threat_id`: exact subject in the supplied Threat State snapshot.
- `option_id`: opaque option identity.
- `reachability_context_id`: opaque strategic affectability context.
- `horizon_id`: opaque strategic time/action horizon identity.
- `reachability`: exact concrete ThreatReachability enum.
- `assessment_policy_id`: opaque identity/version of the external policy.

All identifiers must be exact concrete nonempty, non-whitespace strings. No
silent trimming, case conversion, namespace interpretation, prefix matching or
ref parsing occurs. Otherwise nonblank strings retain surrounding whitespace.
Examples such as stay-lane, farm-wave-top, take-camp-A, rotate-gate and push-tier1
carry no executable semantics. Neither immediate-window nor next-wave-window nor
an ID containing digits/units implies a duration in seconds or ticks.

Each `(threat_id, option_id, reachability_context_id, horizon_id)` tuple may have
at most one claim. Duplicates reject even if classification or policy differs.
No strongest/newest selection or reconciliation. Different threats, options,
contexts or horizons remain independent and can have different classifications.
One threat/option can be CANNOT_AFFECT under H-short and CAN_AFFECT under H-long.
Reachability is never an unqualified permanent property of a threat.

Frozen `ThreatReachabilityAssessment` preserves the six claim fields plus the
complete matching `threat_state_assessment`. Frozen `ThreatReachabilitySnapshot`
holds `timeline_id`, `selected_clock_id`, `threat_state_snapshot_id`,
`evaluated_at_tick` and an assessments tuple; `snapshot_id` is derived.

## State authority, validation and preservation

The exact accepted `ThreatStateSnapshot` defines the subject universe. Every
claim must identify exactly one assessment. Foreign subjects reject; no subjects
are invented or inferred from option names, contexts or observation refs.

The builder defensively checks concrete snapshot/row/claim types, tuple containers,
nonblank timeline/clock and positive/missing snapshot identities, concrete integer
ticks excluding bool, unique state subject IDs, supported AssembledThreatState
and ThreatStateReason enums, and each row's tick binding to its enclosing snapshot.
Negative ticks are valid. Malformed supplied state rejects even with empty claims.

This is structural validation only. Threat State owns arbitration and its nested
evidence validity. Reachability does not reconstruct evidence, re-evaluate
temporal alignment, resolve conflict, derive MISSING or rerun an upstream builder.
The matching accepted assessment object is retained by identity, including state,
reason and all nested provenance. Inputs and claims are never mutated.

`evaluated_at_tick` is exactly `threat_state_snapshot.assembly_tick`. Timeline and
selected clock are copied exactly. No wall clock, clock conversion, advancement,
age calculation or temporal refresh. There is no reachability FRESH/STALE enum.
Future downstream composition may classify the whole snapshot relative to a
later common tick.

## Independence and absent claims

All 15 combinations of the five accepted states and three reachability values
are valid. VISIBLE_NEARBY does not force CAN_AFFECT; VISIBLE_AWAY does not force
CANNOT_AFFECT. MISSING, UNKNOWN and CONFLICTED each permit all three explicit
classifications without modifying the underlying state or resolving uncertainty.

Empty claims return an empty snapshot with upstream provenance: no assessments
were supplied. This means neither all threats UNKNOWN nor all CANNOT_AFFECT nor
safe options. Subsets of threats/options/contexts/horizons are valid. Only claims
create rows, with no automatic Cartesian product. An explicit UNKNOWN row differs
from no assessment in both data and deterministic identity.

Threat Relevance asks whether a threat matters to a relevance context; Reachability
asks whether it can affect a particular option in a horizon. NOT_RELEVANT plus
CAN_AFFECT and RELEVANT plus CANNOT_AFFECT can coexist in future composition.
Option Exposure classifies the option itself, not this threat-option relation.
NOT_EXPOSED plus CAN_AFFECT and EXPOSED plus CANNOT_AFFECT can coexist. No coverage,
relevance or exposure reconciliation occurs here.

CAN_AFFECT never implies high risk or danger. CANNOT_AFFECT never establishes
safety. UNKNOWN is not danger. MISSING/NEARBY/RELEVANT plus CAN_AFFECT produces
no unsafe conclusion. No risk, safety, scoring, confidence, probability,
recommendation, action, route, distance, ETA, speed, spell range or cooldown output.

## Ordering and deterministic identity

Rows sort by threat_id, option_id, reachability_context_id, horizon_id and
assessment_policy_id. Equivalent claim order does not change output or identity.

`snapshot_id` is `threat.reachability_assessment.v1:snapshot:` followed by SHA-256
of the complete dataclass serialization, using JSON, sorted keys, compact
separators, ensure_ascii=True and UTF-8. It binds upstream snapshot ID, timeline,
clock, evaluated tick, all claim identifiers, policy, classification and complete
preserved state assessment. Meaningful changes affect identity. The property is
not included recursively in its own serialization. Determinism and structural
provenance do not authenticate the caller policy or prove external truth.

## Dependency and purity boundaries

Production imports only dataclasses, enum, hashlib, json and four contracts from
threat_state_assembly: ThreatStateSnapshot, ThreatStateAssessment,
AssembledThreatState, ThreatStateReason. No contract construction or upstream
builder invocation. No imports of lower Observation/Temporal/Resolver foundations,
Threat Relevance, Strategic Coverage, Option Exposure, Risk Evidence, Safety,
Option Safety, Decision, runtime, GSI or vision.

There is no I/O, network, environment access, randomness, UUID, database,
subprocess, threads, async, scheduler, cache, singleton or mutable global state.
No existing production module consumes the new layer.

Only Threat State's exact consumer/symbol allowlist and Risk Evidence's assertion
of that same allowlist are maintained. The new consumer is exactly
coach02/threat_reachability.py with the four contracts above. Risk Evidence retains
its existing six-symbol permission. Reachability cannot import the two lower
evidence contracts re-exported for Risk Evidence. Builders, construction through
aliases, wildcard/whole-module/dynamic imports and arbitrary future/live consumers
remain rejected. Pre-edit hash-chain review found no stored SHA dependents for
the two affected test files, so no hash literal updates are needed. All unrelated
assertions and existing production bytes are preserved.

## RISK_EVIDENCE_V02_COMPATIBILITY_REVIEW

Actual Risk Evidence v0.1 has six-field RiskEvidenceBinding with relevance,
coverage and exposure contexts but no reachability_context_id or horizon_id.
ThreatRiskEvidence retains state/relevance only. RiskEvidenceSnapshot identifies
four upstream snapshots and has no reachability snapshot identity. Therefore
Risk Evidence v0.1 does not consume this new axis.

A future separate v0.2 design would need:

- Explicit caller mapping of reachability_context_id and horizon_id alongside
  risk context and option, without inferring joins from equal strings.
- Selection by the complete threat_id/option_id/context/horizon tuple, preserving
  independent assessments and avoiding evidence borrowing.
- Reachability snapshot identity and complete selected assessment provenance,
  including exact Threat State snapshot lineage.
- Timeline/clock and evaluated_at_tick compatibility rules before comparing time.
- A policy for CURRENT/HISTORICAL/ABSENT at its common composition tick; this
  feature adds no freshness or downstream-use enum.
- Optional selected evidence to distinguish absent reachability from explicit
  UNKNOWN, retaining historical classifications rather than rewriting them.
- Extended canonical serialization, identity and dependency guards, reviewed as
  separate work. No unvalidated inference from affectability to risk.

No v0.1 production change, v0.2 adapter, integration or legacy Safety mapper is
created. Legacy Safety/Option Safety has no faithful direct destination for this
threat/option/context/horizon axis; any lossy mapping is outside this feature.

## Real-policy boundary

A future real policy may require Threat State plus Threat Capability, mobility
resources, cooldowns, position/uncertainty, option location/action and travel/action
horizon. None of their algorithms belongs here. There is no hero/item database,
coordinate/geometry model, movement speed, pathfinding, Blink, teleport, global
spell, cast/attack range, mana/HP, disable/immunity or terrain logic in v0.1.

## BLOCKER_BEFORE_REAL_REACHABILITY

- No validated real reachability policy or threat capability model.
- No mobility/resource/cooldown model.
- No real position/uncertainty model.
- No option geometry/location model.
- No action/travel timing model.
- No pathfinding or hero-specific reachability logic.

## BLOCKER_BEFORE_RISK_EVALUATION

- Risk Evidence v0.1 does not yet consume Reachability.
- No Risk Evidence v0.2 or risk policy.
- No severity weighting or capability/reachability-derived risk rules.

## BLOCKER_BEFORE_LIVE_INTEGRATION

- Real observation sources remain unresolved.
- Real clock/alignment policy unresolved.
- No live orchestration.

## ACCEPTED_V01_LIMITATION

- Explicit caller classification.
- One claim per threat/option/context/horizon tuple.
- No multi-source reconciliation or reliability weighting.
- Horizon is opaque identity, not duration.
- Categorical assessment only.

## Validation workflow

The 104-test matrix covers contracts, structural validation, every state/value
combination, horizon/option/context isolation, UNKNOWN versus absence, canonical
identity, purity, external domain independence, future compatibility and exact
dependency scope. Existing production hashes are pinned. Each required gate runs
once, with no retry. LF, formatting and guard edits are finalized before gates;
the exact passing bytes must be staged and committed. Results are recorded in an
external report. Promotion and all later architectural work remain separate.
