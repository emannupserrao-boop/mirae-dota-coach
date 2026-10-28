# Visibility Completeness Assessment v0.1

**SUFFICIENT does not mean MISSING.**

**INSUFFICIENT does not mean NOT_MISSING.**

**UNKNOWN is first-class.**

**Completeness assesses the observational scope of one exact NOT_VISIBLE occurrence.**

**This is not strategic map coverage.**

## Semantic boundary

SILENCE is no explicit negative observation. NOT_VISIBLE is an explicitly supplied
negative visibility observation. VISIBILITY COMPLETENESS is an explicitly supplied
assessment of whether the scope associated with that exact negative occurrence was
sufficient for a future absence/missing resolver to consider it. MISSING remains a
future derived state.

Neither NOT_VISIBLE alone, SUFFICIENT alone, nor FRESH NOT_VISIBLE + SUFFICIENT
produces MISSING here. INSUFFICIENT is not proof of NOT_MISSING. UNKNOWN does not
fall back to INSUFFICIENT, None, false, or an omitted field.

This component does not calculate scope completeness, certify the source, decide
truth, assess relevance, calculate risk/safety, inspect the map, or observe Dota.

## API and immutable contracts

VisibilityCompleteness contains exactly SUFFICIENT, INSUFFICIENT, UNKNOWN.

VisibilityCompletenessClaim contains:
- threat_id;
- absence_ref;
- scope_id;
- completeness;
- assessment_policy_id.

Identity strings are exact nonempty/non-whitespace strings, preserved without
trimming or parsing. scope_id and assessment_policy_id are opaque. The caller must
supply the enum member and external assessment policy identity. There is no default
policy, policy registry, source-specific rule or numeric score.

build_visibility_completeness(absence_snapshot, claims) receives only an accepted
ThreatAbsenceObservationSnapshot and a tuple of claims. At most one claim per threat
is allowed; duplicates are rejected. Each claim requires exactly one observation
matching (threat_id, absence_ref), without fallback to another ref or subject.

Empty claims return a valid empty assessment snapshot. They do not assert UNKNOWN,
INSUFFICIENT, safety, no missing threat, or lack of all information.

VisibilityCompletenessAssessment preserves:
threat_id, absence_ref, source_id, observed_tick, absence_temporal_status,
absence_last_observed_tick, absence_age_ticks, absence_temporal_policy_id,
absence_max_age_ticks, scope_id, completeness, assessment_policy_id.

The extra temporal metadata fields preserve the full selected observation's
accepted lineage rather than discarding policy or last-observed metadata.

VisibilityCompletenessSnapshot preserves:
timeline_id, absence_snapshot_id, event_id, projection_id, tracker_state_id,
temporal_snapshot_id, selected_clock_id, selected_tick, evaluated_at_tick,
and an immutable tuple of assessments.

Claims and outputs are frozen dataclasses. Assessments are canonically ordered by
(threat_id, absence_ref). Caller-owned inputs are not mutated.

## Validation responsibility

This component requires concrete accepted snapshot/observation types. It checks the
consumed structural fields: strings, exact integer ticks (bool rejected), tuple
shape, explicit NOT_VISIBLE, nonnegative age/threshold, and supported FRESH/STALE
status. Unsupported states, including NEVER_SEEN or plain status strings, reject.
Ambiguous observation keys reject rather than choosing a preferred entry.

The caller must supply a snapshot produced by the accepted Threat Absence builder.
This layer does not duplicate the upstream event/projection validation, occurrence
tick binding, age arithmetic, or freshness classification. It does not authenticate
manually fabricated snapshots. All upstream lineage is preserved and content-bound,
not repaired or silently replaced.

Completeness and absence temporal status are independent axes. SUFFICIENT + STALE
is valid historical evidence: the scope was assessed as sufficient for that occurrence,
while the absence observation is not current. Staleness never automatically changes
SUFFICIENT to INSUFFICIENT or UNKNOWN. No new clock, timeline, observation, policy
selection, or temporal tracking is introduced.

## Deterministic identity

Ruleset: threat.visibility_completeness.v1

snapshot_id = ruleset + ":snapshot:" + SHA-256(canonical serialized snapshot).

Canonical JSON: sort_keys=True, separators=(',', ':'), ensure_ascii=True, UTF-8.
Identity binds the entire upstream absence snapshot identity, all lineage, selected
assessment fields, scope, policy and completeness. Claim order cannot change output
or ID. No time, process metadata, random value or UUID is used.

## Dependency direction and purity

Observation Event -> Temporal Evidence -> Threat Absence -> Visibility Completeness.

A future Missing Threat Resolver may consume positive Threat Observation, negative
Threat Absence, and this separate completeness assessment. This component does not
inspect positive sightings and does not reconcile contradictions.

Production imports only dataclasses, enum, hashlib, json and contracts exposed by
threat_absence_observation:
ThreatAbsenceObservation, ThreatAbsenceObservationSnapshot, ThreatVisibilityAbsence
and the existing TemporalStatus enum already exposed by that module. The latter is
reused for concrete status validation and annotations; no second temporal taxonomy
or direct Temporal Evidence import is introduced.

No direct Observation Event, Temporal Evidence, Threat Observation, Safety, Decision,
runtime, GSI or vision dependency is added. No existing production path imports this
component. No observation/tracker builder is called. No I/O, clock, network,
environment, database, subprocess, random, UUID, scheduler or hidden mutable state
exists.

The previously global Threat Absence dependency guard required narrow maintenance.
Its sole downstream exception is coach02/visibility_completeness.py, limited to the
four contracts above. Arbitrary/upstream/live/sibling consumers, wildcard and dynamic
imports, constructor calls and orchestration remain prohibited. The existing
Absence module's own orchestration assertions remain intact.

Only tests/test_threat_absence_observation.py is modified among preexisting files.
No dependent frozen hash reference to this test was found, so no other hash
maintenance is required. Accepted production, other tests and documentation remain
byte-for-byte unchanged.

## Limitations

**BLOCKER_BEFORE_REAL_OBSERVATION:**
- no validated real source/policy for completeness.

**BLOCKER_BEFORE_MISSING_RESOLUTION:**
- Missing Threat Resolver not implemented;
- positive/negative conflict resolution not implemented.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:**
- Missing Resolver absent;
- Threat Relevance absent;
- Strategic Coverage absent;
- live orchestration absent.

**ACCEPTED_V01_LIMITATION:**
- one completeness assessment per threat_id per snapshot;
- categorical only;
- no multi-source reconciliation;
- policy implementation external;
- tied to already validated Threat Absence occurrence.

Upstream limits remain: ref/tick metadata alone cannot distinguish separate events
sharing the same ref and tick; subject/ref association and authentic source evidence
remain external responsibilities. Scope and policy IDs provide provenance, not proof
of sufficiency.

## Validation design

The accepted baseline is 632/632/632 and is reused on resume. The new focused suite
contains 84 tests covering the required matrix, malformed contract structure,
negative ticks, temporal classification preservation, empty snapshots, exact subject
binding, independent completeness/freshness axes, conflicting positive fixtures and
dependency restrictions.

Run each post-change gate once: dependency guards (4), completeness (84), Threat
Absence (88), Threat Observation (84), Observation Event (68), Temporal (50), Offline
Core (31), full feature suite (expected 716). Actual acceptance results, manifests,
test logs, conditional guard hash changes and final commit identity are recorded in
the external evidence package.

No Missing Resolver, next observer, live integration, merge, tag or push is part of
this task.
