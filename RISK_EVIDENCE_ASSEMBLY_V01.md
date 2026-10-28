# Risk Evidence Assembly v0.1

Risk Evidence is not a risk verdict.

Risk Evidence is not Safety.

CURRENT / HISTORICAL / ABSENT describe evidence usability, not risk magnitude.

ABSENT is not UNKNOWN.

Semantic UNKNOWN is preserved as evidence.

Historical evidence preserves its semantic classification.

Context domains are opaque and are joined only through explicit RiskEvidenceBinding.

No combination automatically means SAFE or UNSAFE.

Risk Evidence Assembly does not refresh upstream temporal evidence.

## Scope and API

`coach02.risk_evidence_assembly.build_risk_evidence` consumes, in order, the
accepted `ThreatStateSnapshot`, `ThreatRelevanceSnapshot`,
`StrategicCoverageSnapshot`, `OptionExposureSnapshot`, and a concrete tuple of
`RiskEvidenceBinding` values. It returns a frozen `RiskEvidenceSnapshot`.
All four domains remain separate. There is no world state, hero model, Player
Model, Data Foundation lookup, live orchestration or downstream policy invocation.

The new module imports contracts only through those four accepted semantic
modules, plus `dataclasses`, `enum`, `hashlib` and `json`. It neither imports lower
observation/temporal/resolver foundations directly nor invokes upstream builders.
The observation and resolver types re-exported by Threat State are used only for
structural type checks on retained evidence. The temporal status enum re-exported
by Strategic Coverage is used only to consume the accepted status.

## Explicit binding

Frozen `RiskEvidenceBinding` has exactly six fields:

- `risk_context_id`: requested risk-analysis context identity.
- `option_id`: requested option identity.
- `relevance_context_id`: exact relevance context to select for each threat.
- `coverage_context_id`: exact strategic coverage context to select.
- `exposure_context_id`: exact exposure context to select for this option.
- `binding_policy_id`: identity/version of the external mapping rule.

Every identifier is a concrete nonblank string. Whitespace around an otherwise
nonblank identifier is retained. IDs are opaque: no parsing, trimming, aliases,
prefix/suffix matching or Dota interpretation. One binding per
`(risk_context_id, option_id)` is permitted. Duplicate pairs are rejected even
when other fields differ. One option can belong to multiple risk contexts; one
risk context can contain multiple options. The external mapping policy is not
implemented here.

`R / option-A / REL-7 / COV-22 / EXP-A / binding-v1` is a valid binding. The
different domain IDs need not be equal. Identical context strings without a
binding create no bundle. Only explicit bindings choose options/contexts; the
assembler does not discover all exposure options or generate extra combinations.

## Input validation and lineage

All snapshots must have the exact accepted concrete type, one shared nonblank
`timeline_id`, and one shared nonblank `selected_clock_id`. Validation occurs
before any cross-snapshot numerical tick comparison. There is no clock conversion
or fallback. Ticks must be concrete integers, excluding booleans; negative ticks
are supported. Ages and TTL metadata must be nonnegative.

Threat State and Threat Relevance must have identical `positive_snapshot_id`,
identical `missing_snapshot_id`, and identical state `assembly_tick` and relevance
`evaluated_at_tick`. Every relevance subject must exist in the unique authoritative
Threat State universe. A relevance subset is valid. Complete preserved positive
and missing objects for the same subject must correspond exactly, including the
resolver's positive lineage and subject. This checks structure without rerunning
state arbitration, relevance, absence, completeness or missing derivation.

Assessment/observation containers must be concrete tuples of the accepted types.
Coverage context IDs and exposure `(option_id, exposure_context_id)` pairs must
be unique. Required IDs, concrete semantic enums, FRESH/STALE statuses and integer
temporal metadata are validated. Each context observation must agree with its
snapshot's occurrence/evaluation ticks. No coverage, exposure or freshness
algorithm is recalculated; the supplied accepted temporal status is retained.

Malformed inputs are rejected even when bindings are empty or the malformed
evidence would not be selected. Incomplete but valid evidence is accepted.

## Common assembly tick and evidence use

After validating the shared timeline and clock:

```text
risk_assembly_tick = max(
    threat_state_snapshot.assembly_tick,
    threat_relevance_snapshot.evaluated_at_tick,
    strategic_coverage_snapshot.evaluated_at_tick,
    option_exposure_snapshot.evaluated_at_tick,
)
```

`EvidenceUseStatus` contains exactly `CURRENT`, `HISTORICAL`, `ABSENT`.

| Axis | Selection | CURRENT | Otherwise |
| --- | --- | --- | --- |
| Threat State | Every state subject | State assembly tick equals risk tick | HISTORICAL |
| Threat Relevance | Same threat and exact bound relevance context | Relevance evaluation tick equals risk tick | HISTORICAL if selected; ABSENT if not |
| Strategic Coverage | Exact bound coverage context | FRESH and coverage evaluation tick equals risk tick | HISTORICAL if selected; ABSENT if not |
| Option Exposure | Exact option and bound exposure context | FRESH and exposure evaluation tick equals risk tick | HISTORICAL if selected; ABSENT if not |

An absent selected axis is represented by `None` and `ABSENT`. Explicit semantic
UNKNOWN is an actual object and may be CURRENT or HISTORICAL. No UNKNOWN object
is synthesized. An UNKNOWN threat state remains a subject in the universe.

A FRESH observation evaluated at an older tick is HISTORICAL at the common tick;
it is not refreshed or rewritten as STALE. A STALE observation at the common tick
is also HISTORICAL. Threat relevance gets no invented TTL policy. Historical
MISSING, CONFLICTED, RELEVANT, SUFFICIENT, INSUFFICIENT, EXPOSED and NOT_EXPOSED
remain those semantic values, without asserting they hold currently.

## Output contracts and ordering

Frozen `ThreatRiskEvidence` contains `threat_id`, complete `state_assessment`,
`state_use`, optional complete `relevance_assessment`, and `relevance_use`.

Frozen `OptionRiskEvidenceBundle` preserves all six binding fields, the common
`risk_assembly_tick`, optional complete `coverage_observation` with `coverage_use`,
optional complete `exposure_observation` with `exposure_use`, and a tuple of all
threat rows. NOT_RELEVANT, UNKNOWN, CONFLICTED, historical and relevance-absent
threats are never filtered. All state subjects appear in every requested bundle.

Frozen `RiskEvidenceSnapshot` preserves timeline, clock, all four upstream
snapshot IDs, the common tick and the tuple of bundles. An empty binding tuple
returns an empty bundle tuple while retaining upstream provenance. It means no
composition was requested; it is not a claim about safety, threats or exposure.

Bundles are sorted by the six binding fields in their declaration order. Threat
rows are sorted by `threat_id`. Binding input order does not change the result or
identity. Selected objects are retained intact, with no mutation or reduction to
labels. Missing axes and historical axes can coexist in a valid bundle.

## Deterministic identity

`snapshot_id` is `risk.evidence_assembly.v1:snapshot:` plus SHA-256 of the full
dataclass serialization: JSON, `sort_keys=True`, compact separators,
`ensure_ascii=True`, UTF-8. Identity includes timeline, clock, assembly tick, four
upstream IDs, every binding and policy ID, selected evidence objects, all threat
rows and every use status. The derived `snapshot_id` property is not included in
its own payload. No time, I/O, network, environment, random value or mutable global
state influences assembly.

Deterministic IDs and structural lineage do not authenticate an external source
or prove that an observation is true. Synthetic evidence remains synthetic.

## No risk or Safety policy

RELEVANT plus MISSING or VISIBLE_NEARBY is not an automatic danger/UNSAFE verdict.
NOT_RELEVANT is not harmlessness. SUFFICIENT coverage is not SAFE; INSUFFICIENT
coverage is not UNSAFE. EXPOSED is not UNSAFE; NOT_EXPOSED is not SAFE. CONFLICTED
and UNKNOWN do not imply high risk. No combination creates SAFE, UNSAFE, LOW,
HIGH, risk levels, scores, weights, confidence, probability, recommendations,
actions or ranking. This layer supplies evidence for a future validated policy.

## Legacy downstream compatibility review

Actual inspection of `coach02/safety_evidence.py` and `coach02/option_safety.py`
yields **NO_DIRECT_PRODUCTION_COMPATIBILITY_V01**.

- Legacy `ThreatState` lacks CONFLICTED. `RelevantThreatObservation` has only
  `threat_id`, `state`, `freshness`; it assumes relevance and cannot retain separate
  relevance/context/use axes, state reasons or complete provenance. It also
  restricts threat IDs to ASCII namespace tokens.
- Legacy `CoverageObservation` has only `sufficient: Truth` and `freshness`.
  It loses the strategic context, optional absence distinction and source lineage.
- Legacy `Exposure` has LOW/HIGH/UNKNOWN, with no faithful EXPOSED/NOT_EXPOSED
  mapping specified. `FarmOptionSafetyObservation` has seed, option, action,
  exposure/freshness and coverage/freshness. It lacks risk/context binding and
  complete provenance, requires a productive action and restricts option IDs.
- Legacy freshness alone does not represent the independent CURRENT/HISTORICAL/
  ABSENT axis. Collapsing missing or historical evidence into UNKNOWN would lose
  required distinctions. Multiple risk bindings for one option would also lose
  identity under a legacy option-only key.

No production adapter, test mapper, policy bridge or downstream builder invocation
is introduced, including subset mappings. A faithful downstream contract is
future work.

## Dependency guards and validation

Only the existing reverse-dependency guards in the Threat State, Threat Relevance,
Strategic Coverage and Option Exposure test files are maintained. Their exact new
consumer is `coach02/risk_evidence_assembly.py`, with only the contract symbols
actually required by that module. Upstream builders, contract construction,
wildcards, whole-module imports, dynamic imports and arbitrary future consumers
remain prohibited. No existing production file imports this new module.

The pre-edit finite SHA-256 dependency review found no stored hash references to
those four modified tests; zero dependent literal updates are required. Existing
production hashes are pinned in the new suite. Unrelated guards and assertions
remain intact. All project formatting and LF bytes are finalized before gates.

The focused suite defines 104 tests following the requested matrix, including
complete current composition, current nearby threats, historical state and axes,
missing axes, unknown semantics, exact context isolation, duplicate rejection,
opaque mappings, lineage disagreement, determinism, purity and legacy review.
Gates run once each: baseline, focused guards, focused feature, eleven named domain
regressions and full feature suite. Results are recorded externally; no outcome is
assumed by this document. The tested bytes must equal staged and committed bytes.

## BLOCKER_BEFORE_RISK_EVALUATION

- No validated risk policy.
- No weighting/severity model.
- No threat capability/reachability model.
- No resource/opportunity-cost integration.
- No current policy for converting evidence combinations into risk levels.

## BLOCKER_BEFORE_LIVE_RISK_INTEGRATION

- Upstream threat/coverage/exposure sources remain synthetic/non-real.
- Real clock/alignment policy is unresolved.
- No live orchestration.
- No production Safety v0.2.

## ACCEPTED_V01_LIMITATION

- Explicit caller binding between opaque context domains.
- One binding per risk-context/option pair.
- No multi-source reconciliation or source reliability weighting.
- No risk classification or safety decision.
- Conservative currentness may leave historical/absent axes.

Promotion, Risk Evaluation, production Safety, Decision integration, resource
observations, geometry/reachability, live GSI/vision, Shadow Mode and real-match
testing are outside this feature.
