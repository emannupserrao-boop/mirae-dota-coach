# Missing Threat Resolver v0.1

**MISSING is derived, not observed.**

**NOT_JUSTIFIED does not mean NOT_MISSING.**

**MISSING does not mean dangerous or relevant.**

**A stale positive sighting may remain valid historical last-seen evidence.**

**A stale negative observation cannot justify current MISSING in v0.1.**

**Same-tick positive/negative evidence is CONFLICTED when all prerequisite negative
evidence is otherwise authoritative.**

## Contract

resolve_missing_threats(positive_snapshot, absence_snapshot, completeness_snapshot)
is a pure transformation of three explicitly supplied immutable semantic snapshots:

- ThreatObservationSnapshot: NEARBY/AWAY positive sightings;
- ThreatAbsenceObservationSnapshot: explicit NOT_VISIBLE evidence;
- VisibilityCompletenessSnapshot: SUFFICIENT/INSUFFICIENT/UNKNOWN assessment of the
  exact supplied absence snapshot.

The caller supplies one intended positive snapshot, conceptually the latest known
positive evidence for this resolution attempt. The resolver does not discover history,
choose a source, merge snapshots, store previous evidence, or observe Dota.

Each explicit absence subject receives one resolution. Positive-only subjects receive
no row. Empty absence returns an empty resolution snapshot and makes no statement
about visibility, safety, NOT_MISSING or other subjects.

## Status and reason taxonomy

MissingResolutionStatus contains exactly:
- MISSING;
- NOT_JUSTIFIED;
- CONFLICTED.

MissingResolutionReason contains:
- JUSTIFIED_MISSING;
- NO_PRIOR_POSITIVE_SIGHTING;
- NO_COMPLETENESS_ASSESSMENT;
- COMPLETENESS_INSUFFICIENT;
- COMPLETENESS_UNKNOWN;
- ABSENCE_STALE;
- SAME_TICK_POSITIVE_NEGATIVE_CONFLICT;
- NEWER_POSITIVE_SIGHTING.

MISSING requires JUSTIFIED_MISSING. CONFLICTED requires
SAME_TICK_POSITIVE_NEGATIVE_CONFLICT. NOT_JUSTIFIED uses one of the other six
reasons. Invalid enum types or status/reason pairs are rejected.

NOT_JUSTIFIED is a failure to justify MISSING from this supplied bundle. It never
means NOT_MISSING, visible, safe, or irrelevant. CONFLICTED represents the exact
same-tick contradiction only after the negative evidence prerequisites pass.

## Structural validation and exact binding

All three input types must be the concrete accepted snapshot contracts. The resolver
checks the consumed structure: identity strings, exact integer ticks (not bool),
immutable entry tuples, supported enum values, one subject per input snapshot, and
coherent observation tick/age metadata. No TTL is recalculated or classification
repaired. Unsupported or ambiguous input is rejected before semantic reasoning.

All inputs require identical timeline_id and selected_clock_id. No comparison of
ticks across clock domains or clock conversion occurs.

Completeness must bind absence_snapshot.snapshot_id and exactly preserve its
timeline, clock, event_id, projection_id, tracker_state_id, temporal_snapshot_id,
selected_tick and evaluated_at_tick.

Each assessment must match the exact absence subject/ref, source, observed tick,
temporal status, age, last-observed tick, temporal policy and threshold. Extra
assessment subjects, wrong refs, duplicate subjects and metadata mismatches reject.
An absent assessment instead yields NO_COMPLETENESS_ASSESSMENT, not a fabricated
UNKNOWN assessment.

Positive entries are matched only by exact threat_id. No ref parsing, fallback to
another subject, borrowing completeness, or source-specific behavior exists.

Content IDs provide deterministic binding, not external authentication or proof that
the source supplied truthful observations. Inputs still originate from trusted,
accepted semantic builders; arbitrary fabricated evidence is not certified.

## Frozen semantic precedence

After validating the entire bundle, resolve each absence in this exact order:

1. No matching completeness assessment:
   NOT_JUSTIFIED / NO_COMPLETENESS_ASSESSMENT.
2. Completeness INSUFFICIENT or UNKNOWN:
   NOT_JUSTIFIED / COMPLETENESS_INSUFFICIENT or COMPLETENESS_UNKNOWN.
3. Absence STALE:
   NOT_JUSTIFIED / ABSENCE_STALE.
4. No matching positive sighting:
   NOT_JUSTIFIED / NO_PRIOR_POSITIVE_SIGHTING.
5. Compare positive observed_tick to absence observed_tick:
   - earlier: MISSING / JUSTIFIED_MISSING;
   - equal: CONFLICTED / SAME_TICK_POSITIVE_NEGATIVE_CONFLICT;
   - later: NOT_JUSTIFIED / NEWER_POSITIVE_SIGHTING.

Thus UNKNOWN + STALE absence + same-tick positive is COMPLETENESS_UNKNOWN, not a
conflict. Missing completeness, inadequate scope, and stale negative evidence never
gain conflict authority. A newer positive blocks the current derivation; no earlier
temporary missing interval is reconstructed.

Both NEARBY and AWAY prior sightings are historical positive evidence. Either FRESH
or STALE positive status is accepted and preserved. Only the negative observation
must be FRESH, with SUFFICIENT completeness, before temporal ordering can justify
MISSING or a conflict.

## Output and provenance

MissingThreatResolution is frozen and contains:
- threat_id, status, reason;
- positive: exact ThreatObservation or None;
- absence: exact ThreatAbsenceObservation;
- assessment: exact VisibilityCompletenessAssessment or None;
- positive_snapshot_id, absence_snapshot_id, completeness_snapshot_id;
- last_seen_tick and missing_since_tick.

Nested immutable contracts preserve every source/ref/proximity/visibility/tick/status/
age/policy/threshold and scope/completeness/assessment-policy field without flattening
away metadata. Snapshot IDs identify all upstream envelopes. A supplied empty
positive snapshot still has an identity; positive=None explicitly indicates no
matching positive observation.

last_seen_tick is the matching positive observed_tick, if present.
missing_since_tick is the explicit absence observed_tick ONLY for MISSING; otherwise
None. Invalid output time metadata is rejected. No movement time, location,
destination or arrival estimate is invented.

MissingThreatResolutionSnapshot is frozen and contains:
timeline_id, selected_clock_id, all three snapshot IDs, resolved_at_tick and a
canonical tuple of resolutions sorted by threat_id.

resolved_at_tick is max of the three evaluated_at_tick values, after same-clock
validation. This is metadata for the supplied bundle, not a new freshness evaluation.
It never refreshes evidence, changes age/status or rewrites observation ticks.
Consequently FRESH/STALE are authoritative supplied classifications at their upstream
evaluation points; future orchestration must align/evaluate snapshots appropriately
before live use. No hidden TTL or age adjustment is introduced here.

## Deterministic identity

Ruleset: threat.missing_resolver.v1

snapshot_id = ruleset + ":snapshot:" + SHA-256(canonical serialized snapshot).

Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True, UTF-8.
Identity includes input snapshot IDs and every output status/reason, nested
provenance, scope/policy, last_seen_tick and missing_since_tick.

Canonical upstream builders make equivalent input order produce identical IDs.
If a caller manually reorders an already-built upstream snapshot, its own content
identity may change. Resolver row ordering remains canonical, but those changed
upstream identities are deliberately retained rather than erased.

## Dependencies, guards and purity

Production imports only dataclasses, enum, hashlib, json and accepted contracts from:
- threat_observation (ThreatObservation, ThreatObservationSnapshot, ThreatProximity,
  and TemporalStatus already exposed there);
- threat_absence_observation (ThreatAbsenceObservation,
  ThreatAbsenceObservationSnapshot, ThreatVisibilityAbsence);
- visibility_completeness (VisibilityCompleteness,
  VisibilityCompletenessAssessment, VisibilityCompletenessSnapshot).

No direct Observation Event, Temporal Evidence, Safety, Decision, runtime, GSI or
vision imports. No builders/orchestration calls, wall clock, I/O, network, environment,
database, subprocess, random/UUID, scheduler, async, global mutable state or cache.
No existing production module imports the resolver.

The three legacy guards required narrow maintenance to admit exactly
coach02/missing_threat_resolver.py. Absence still admits its existing Visibility
Completeness consumer; the resolver receives only its required subset of symbols.
The completeness test's allowlist assertion is maintained to reflect this authorized
consumer. Arbitrary/upstream/live/sibling consumers, wildcard/module/dynamic imports
and orchestration remain prohibited.

There are no stored dependent test hashes for these three modified tests, so no hash
cascade or additional file changes are required. All existing production remains
byte-for-byte unchanged.

## Test-only Safety compatibility

Tests explicitly map only a MISSING resolution with a FRESH absence to the existing
ThreatState.MISSING / Freshness.FRESH contract. NOT_JUSTIFIED and CONFLICTED reject.
This compatibility demonstration does not select relevance, compute Safety/Risk, or
create any production adapter. Safety's own identity validation remains authoritative.

## Limitations

**BLOCKER_BEFORE_REAL_OBSERVATION:**
- positive sightings, NOT_VISIBLE and completeness are still supplied by
  non-real/synthetic upstream sources.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:**
- Threat Relevance not implemented;
- strategic coverage not implemented;
- live orchestration not implemented;
- no production mapping into Safety Evidence yet.

**ACCEPTED_V01_LIMITATION:**
- one positive snapshot supplied by caller; no historical latest-sighting search;
- no multi-source reconciliation;
- no reconstructed missing intervals;
- no source confidence/reliability weighting;
- same-clock ordering required;
- categorical statuses/reasons only.

SILENCE is not NOT_VISIBLE. NOT_VISIBLE and SUFFICIENT alone are not MISSING.
MISSING is a location-knowledge state, not a threat/danger judgment.

## Validation design

Baseline: 716/716/716, executed once before feature creation.
Post-change gates run once: focused dependency guards (7), resolver (104), Visibility
Completeness (84), Threat Absence (88), Threat Observation (84), Observation Event (68),
Temporal (50), Offline Core (31), full feature suite (expected 820).

The resolver suite covers the required 88-case matrix plus defensive, precedence,
ordering and provenance cases. Actual gate results, manifests, old/new test hashes,
diff audit and commit identity are kept in the external evidence package.

No merge, tag, push, next observer, live integration or real-match test is authorized
by this implementation task.
