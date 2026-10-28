# Threat Relevance Assessment v0.1

“RELEVANT does not mean DANGEROUS.”

“NOT_RELEVANT does not mean SAFE.”

“UNKNOWN is first-class.”

“Threat state does not determine relevance.”

“Relevance is context-bound and explicitly supplied in v0.1.”

## Purpose and contracts

`coach02.threat_relevance` binds the caller's explicit classification to accepted
threat evidence. It does not calculate relevance, observe Dota, determine current
threat state, or calculate risk or safety.

`ThreatRelevance` has exactly `RELEVANT`, `NOT_RELEVANT`, and `UNKNOWN`.
`RELEVANT` states that a subject matters under the supplied context and policy.
`NOT_RELEVANT` states that it does not currently matter under that context/policy;
it says nothing about safety, strength, visibility, missing state, or ability to
arrive. `UNKNOWN` means the caller cannot establish relevance. It never defaults
to `NOT_RELEVANT`.

The frozen `ThreatRelevanceClaim` contains `threat_id`, `relevance`,
`relevance_context_id`, and `assessment_policy_id`. Identifiers must be concrete
nonempty, non-whitespace strings. Strings are opaque and never trimmed or parsed.
Leading/trailing spaces in a nonblank identifier remain significant.
The enum must be a concrete `ThreatRelevance`, not a string or another enum.

The caller owns the strategic context and versioned relevance policy. A context
may concern carry farm safety or a separate decision; the component does not
inspect it. Context is attached to each assessment, never to the hero globally.
Different subjects may carry different explicit context identities. One subject
cannot receive multiple contexts/policies in one snapshot; duplicates are rejected,
without choosing, merging, or ranking them.

## Builder and evidence binding

```python
build_threat_relevance(
    positive_snapshot: ThreatObservationSnapshot,
    missing_snapshot: MissingThreatResolutionSnapshot,
    claims: tuple[ThreatRelevanceClaim, ...],
) -> ThreatRelevanceSnapshot
```

Inputs must have the exact accepted snapshot types, the same `timeline_id` and
`selected_clock_id`, and:

```python
missing_snapshot.positive_snapshot_id == positive_snapshot.snapshot_id
```

The entire input bundle is structurally checked even with empty/subset claims:
tuple collections; unique subject IDs per input; concrete row types; nonblank
lineage IDs; exact integers excluding bool; supported proximity, temporal,
resolution, reason, visibility and completeness enums; nonnegative ages and
thresholds. Negative clock ticks are not prohibited: the accepted clock domain
owns its origin. No wall clock or conversion is introduced.

Each missing row must carry its enclosing positive/absence/completeness snapshot
IDs, and its nested positive must equal the matching supplied positive observation
(or both be absent). Nested absence and completeness subjects must match the row.
Foreign subjects and borrowed positive evidence are rejected; evidence is never
repaired.

This is structural and lineage validation, not repetition of upstream semantic
algorithms. Accepted builders own occurrence/age consistency, temporal freshness,
completeness-to-absence occurrence binding, missing status/reason combinations and
last-seen/missing-since semantics. This layer does not rederive MISSING, validate
real-world truth, or authenticate fabricated snapshots. A structurally valid
fabrication is not proof of an accepted real observation.

The valid subject universe is the union of positive observation subjects and
missing resolution subjects. A claim must belong to that union. Matching uses
the exact `threat_id`, never parsed refs or hero metadata.

## Output and preservation

Frozen `ThreatRelevanceAssessment`:

- `threat_id`
- `relevance`
- `relevance_context_id`
- `assessment_policy_id`
- `positive_observation`, optional exact immutable upstream object
- `missing_resolution`, optional exact immutable upstream object

Frozen `ThreatRelevanceSnapshot`:

- `timeline_id`, `selected_clock_id`
- `positive_snapshot_id`, `missing_snapshot_id`
- `evaluated_at_tick`
- `assessments`, immutable tuple sorted by `threat_id`
- computed `snapshot_id`

Both evidence axes are retained when available. Historical positive evidence can
coexist with a derived MISSING row. Positive and missing evidence never take
precedence over each other here. NOT_JUSTIFIED remains NOT_JUSTIFIED; CONFLICTED
remains CONFLICTED. Every such status can coexist with any explicit relevance.
NEARBY/AWAY and FRESH/STALE likewise do not select relevance.

Full nested evidence preserves refs, source IDs, positive proximity, absence
visibility, resolution status/reason, all snapshot IDs, occurrence/last-seen/
missing-since ticks, temporal classifications/ages/thresholds/policies, completeness,
scope and assessment policy. No conversion to Safety is implemented, including in
the new tests.

`evaluated_at_tick` is the maximum of positive `evaluated_at_tick` and missing
`resolved_at_tick` after same-clock validation. It is metadata only. It does not
refresh ages, reclassify freshness, advance missing intervals, or synchronize
observations. Future live composition must supply appropriately aligned evidence.

`claims=()` produces a valid empty assessment tuple. Subset claims are valid;
unclaimed subjects produce no row. No claim is distinct from an explicit UNKNOWN
row. Empty results do not mean no relevant threats, safety, or no danger.

## Determinism

Ruleset: `threat.relevance_assessment.v1`.

`snapshot_id` is `ruleset:snapshot:SHA-256` of `dataclasses.asdict(snapshot)`
serialized as JSON with `sort_keys=True`, compact separators, `ensure_ascii=True`,
and UTF-8. It binds all output fields and nested evidence, including both upstream
snapshot IDs, context and policy. No generated ID, clock, environment or randomness
is used. Claim order does not affect assessments or identity.

Upstream identities are preserved truthfully. Manually reordering an upstream
snapshot can change its upstream ID; the relevance layer does not erase that
provenance. Determinism does not authenticate the source or policy.

## Dependencies and guards

Production imports only dataclasses, enum, hashlib and json, plus contracts from
Threat Observation and Missing Threat Resolver. TemporalStatus is taken from the
existing Threat Observation exposure. Nested absence/completeness contract types
and enums are taken from the existing resolver exposure solely for defensive
validation; no direct lower-layer imports or builder calls are needed.

Dependency direction is Threat Observation + Missing Resolver → Threat Relevance.
Existing production remains byte-for-byte unchanged. No existing production
imports relevance. There is no Safety adapter or state arbitration.

The existing Threat Observation guard adds only `coach02/threat_relevance.py` to
its authorized consumers, using the same four required contracts. The Missing
Resolver guard now allows only that exact consumer and the eight imported
contract symbols. Both forbid arbitrary consumers, wildcard/module-wide/dynamic
imports, upstream builders and aliases used to construct upstream contracts.
The guard-only maintenance preserves historical test counts. Pre-flight found
no dependent frozen hashes for the two changed test files.

No hero, role, mobility, teleport, item, level, damage, cooldown, matchup, distance,
movement speed, player state, objective or route algorithm exists. There is no
I/O, network, environment access, random/UUID, database, process, thread, async,
scheduler, cache, singleton or mutable global state in production.

## Validation

The 104 focused tests cover the 78 requested requirements plus structural,
lineage, nested-type, immutability and malformed-input cases. They reuse the
accepted resolver test fixture to build synthetic upstream evidence. No real
match data, capture, voice or live orchestration is introduced.

Adversarial cases A–K cover MISSING+NOT_RELEVANT, NEARBY/FRESH+UNKNOWN,
AWAY+RELEVANT, CONFLICTED+RELEVANT, NOT_JUSTIFIED+RELEVANT, missing claims,
foreign subjects, mismatched positive snapshots/clocks, mixed subjects and
context-dependent identity. Guard tests exercise rejection using parsed synthetic
source. Existing production hashes are frozen from pre-flight.

Each required gate runs once. External evidence records baseline, guard/focused
results, historical regressions, full suite, localhost transport, hashes and
commit audit. A failed gate blocks acceptance without retry-until-green.

## Limitations

BLOCKER_BEFORE_REAL_RELEVANCE:

- no validated real relevance policy/source;
- no hero capability/mobility/item/context model feeding relevance.

BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:

- no state/relevance composition into production Safety;
- strategic coverage still absent;
- live orchestration absent.

ACCEPTED_V01_LIMITATION:

- one explicit relevance assessment per threat per snapshot;
- one positive snapshot + one missing snapshot supplied;
- no multi-source reconciliation;
- no actual relevance algorithm;
- opaque relevance_context_id and assessment_policy_id owned by caller.
