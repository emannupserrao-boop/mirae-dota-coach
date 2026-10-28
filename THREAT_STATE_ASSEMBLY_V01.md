# Threat State Assembly v0.1

**Threat state is not threat relevance.**

**Threat state is not risk.**

**Threat state is not safety.**

**FRESH is valid only at the tick where upstream freshness was evaluated.**

**Threat State Assembly does not refresh temporal evidence.**

**A FRESH classification from an earlier evaluation tick is not silently treated as current.**

**MISSING is consumed from Missing Threat Resolver; it is not re-derived.**

**CONFLICTED is first-class and is not silently downgraded.** Current support is still
required; an older conflict is retained in provenance while current state is UNKNOWN.

**NOT_JUSTIFIED is not NOT_MISSING.**

## Input and output contracts

`build_threat_state(positive_snapshot, missing_snapshot)` accepts exactly one concrete
`ThreatObservationSnapshot` and one concrete `MissingThreatResolutionSnapshot`. It
accepts no claims or caller classification. It deterministically arbitrates state.

The new `AssembledThreatState` domain contains exactly VISIBLE_NEARBY, VISIBLE_AWAY,
MISSING, UNKNOWN and CONFLICTED. It is independent of legacy Safety. Nearby is not
dangerous, away is not safe, missing is not dangerous, unknown is not safe, and conflict
is not dangerous. There are no relevance, coverage, exposure, risk, safety, action,
authority, recommendation, score, probability or weight outputs.

Frozen `ThreatStateAssessment` preserves threat_id, state, reason, assembly_tick,
the complete optional positive_observation and complete optional missing_resolution.
The builder retains the exact matching objects, including historical observations and
the nested absence/completeness, without rewriting upstream conclusions.

Frozen `ThreatStateSnapshot` preserves timeline_id, selected_clock_id,
positive_snapshot_id, missing_snapshot_id, assembly_tick and an immutable assessments
tuple. Its snapshot_id is computed from the complete envelope.

| State | Permitted reason |
| --- | --- |
| VISIBLE_NEARBY / VISIBLE_AWAY | CURRENT_POSITIVE |
| MISSING | JUSTIFIED_MISSING |
| CONFLICTED | VALIDATED_CONFLICT |
| UNKNOWN | NO_CURRENT_POSITIVE / UNRESOLVED_NEGATIVE_EVIDENCE / TEMPORAL_MISALIGNMENT |

The assessment constructor enforces these enum pairs. NO_CURRENT_POSITIVE means a
potentially decisive positive was aligned but stale. UNRESOLVED_NEGATIVE_EVIDENCE
means no strictly later current positive settles NOT_JUSTIFIED, or aligned negative
support is stale. TEMPORAL_MISALIGNMENT means the potentially decisive classification
was evaluated at a different tick. The preserved evidence supplies the full reason
and chronology; no arbitrary confidence or priority is assigned.

## Binding, structural validation and subject universe

Timeline and selected clock must match exactly. The resolver's positive_snapshot_id
must equal the supplied positive snapshot ID. Per-resolution snapshot IDs must match
the resolver envelope. Identifiers are concrete nonblank strings and remain opaque;
no subject is parsed from a ref. Tuples, accepted nested types, enum types, unique
subjects and concrete integer ticks are checked. Booleans/floats are not integers.
Negative ticks remain valid in their explicit clock domain.

Positive occurrences bind to the positive header's selected/evaluation ticks. A nested
positive must equal the supplied positive for that subject (including consistent
absence of positive). Absence and completeness subjects must match the resolution;
completeness's preserved absence metadata must match its nested absence. Negative
evaluation cannot occur after the resolver's resolved_at_tick. These are structural
and provenance checks, not a repetition of resolver policy. Supported temporal status
is FRESH or STALE; NEVER_SEEN is not a supported accepted observation here.

The universe is exactly the union of positive-observation and resolution threat IDs.
There is one sorted row per subject. Positive-only and resolution-only subjects may
coexist; an empty union yields an empty snapshot. There is no implicit subject registry,
history lookup or automatic UNKNOWN row for an unrepresented subject.

## Assembly tick and decision table

After same-clock validation:

`assembly_tick = max(positive_snapshot.evaluated_at_tick, missing_snapshot.resolved_at_tick)`

For each positive/absence observation:

`evidence_evaluated_at_tick = last_observed_tick + age_ticks`

This sum checks evaluation identity only. It neither adds elapsed age nor recalculates
FRESH/STALE from max_age_ticks. Current support requires upstream FRESH **and** exact
equality of that evaluation tick with assembly_tick. Even a large TTL cannot justify
extrapolating FRESH from100 to110. Historical proximity and statuses stay intact.

| Accepted evidence | Current assembled state |
| --- | --- |
| Positive-only, aligned FRESH NEARBY / AWAY | VISIBLE_NEARBY / VISIBLE_AWAY |
| Positive-only stale or misaligned | UNKNOWN |
| Resolver MISSING with current absence | MISSING |
| Resolver CONFLICTED with current absence | CONFLICTED |
| Resolver MISSING / CONFLICTED without current absence | UNKNOWN, original resolution retained |
| NOT_JUSTIFIED with strictly newer, aligned FRESH positive | Corresponding visible state |
| NOT_JUSTIFIED with same-tick or older positive | UNKNOWN; no synthesized conflict |
| NOT_JUSTIFIED with newer stale/misaligned positive | UNKNOWN |
| Resolution-only NOT_JUSTIFIED | UNKNOWN |

For MISSING and CONFLICTED, the accepted resolver status owns the semantic conclusion:
this assembler does not recheck completeness sufficiency, prior-positive prerequisites,
resolver precedence or missing-interval derivation. Defensive structural checks do not
certify semantic truth of a manually constructed upstream envelope. Tests explicitly
demonstrate this trust boundary without claiming such envelopes were emitted by the
resolver. For NOT_JUSTIFIED, later positive chronology applies regardless of the
resolver's blocking reason, since resolver precedence may stop before comparing ticks.

## Deterministic identity

Ruleset: `threat.state_assembly.v1`.

snapshot_id is the ruleset plus `:snapshot:` and SHA-256 of the complete dataclass
snapshot serialized as JSON with sorted keys, compact separators, ensure_ascii=True,
and UTF-8. Identity binds input IDs, timeline/clock, assembly tick, sorted threat IDs,
state/reason and all nested provenance. Rows sort by threat_id. Equivalent canonical
upstream ordering yields the same output/ID; rearranging a manually constructed
upstream tuple can change its own upstream ID, which this layer must preserve.

## Dependency and downstream review

Production imports dataclasses, enum, hashlib and json, plus contract symbols only from
threat_observation and missing_threat_resolver. TemporalStatus is available through
Threat Observation; nested absence/completeness contracts are available through the
resolver. No direct lower Event, Temporal, Absence or Completeness import is needed.
No sibling Threat Relevance, Strategic Coverage or Option Exposure import is present.
External NOT_RELEVANT, coverage UNKNOWN and option EXPOSED fixtures cannot change state.

**NO_DIRECT_PRODUCTION_COMPATIBILITY_V01:** actual legacy safety_evidence.ThreatState
has VISIBLE_NEARBY, VISIBLE_AWAY, MISSING and UNKNOWN, but no CONFLICTED.
RelevantThreatObservation retains only threat_id, state and Freshness, restricts IDs to
ASCII tokens and presupposes relevance. It loses assembly tick, reason, both snapshot
IDs and complete provenance. Its Freshness label alone cannot represent exact evaluation
alignment or the several UNKNOWN causes. There is no production adapter or test mapping;
tests demonstrate incompatibility without silently collapsing CONFLICTED to UNKNOWN.

Threat Observation and Missing Resolver guards add only the exact consumer
`coach02/threat_state_assembly.py`. Required symbols are already in their contract
allowlists. Operations, contract constructors, wildcard/module-wide/dynamic imports and
arbitrary consumers remain forbidden. The pre-edit SHA dependency review finds no
stored-hash consumers of these two tests; therefore zero hash literals require updating.
No existing production file changes and no reverse dependency is introduced.

## Validation and limitations

104 focused tests cover the requested matrix and adversarial cases A-O. Foundation
orchestration occurs only in synthetic test fixtures. Purity checks cover clock reads,
IO, network, environment, random/UUID, mutable globals and upstream/downstream builder
calls. All bytes, LF line endings and guard maintenance are finalized before one-shot
gates. Actual gate results and manifests are recorded in the external execution report.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:** no production composition with Threat Relevance,
Strategic Coverage or Option Exposure; legacy Safety/Option Safety contracts may be
incompatible or lossy; no live orchestration.

**BLOCKER_BEFORE_REAL_OBSERVATION:** positive sightings and NOT_VISIBLE/completeness
remain synthetic/non-real upstream; real clock/alignment policy is unresolved.

**ACCEPTED_V01_LIMITATION:** exactly one positive and one resolver snapshot; no history
search, multi-source reconciliation or reliability weighting; categorical states;
conservative temporal alignment can yield UNKNOWN until upstream snapshots align.
No detection, GSI, memory reading, map geometry, distance or mobility model is added.
