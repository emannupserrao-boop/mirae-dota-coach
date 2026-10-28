# Threat Absence Observation v0.1

**Silence is not NOT_VISIBLE.**

**NOT_VISIBLE is not MISSING.**

**STALE NOT_VISIBLE is only a historical negative observation.**

## Scope and semantics

This offline component binds an explicitly supplied negative visibility claim to one
exact event occurrence. It does not observe Dota, certify the claim, choose a clock,
select a TTL, or interpret silence.

1. **SILENCE:** no relevant explicit negative observation was supplied. No semantic
   conclusion follows. An absent event is rejected; an empty claim tuple produces an empty
   snapshot. An unrelated event ref cannot support a claim.
2. **NOT_VISIBLE:** a source explicitly supplied a negative visibility observation
   for an identified threat at one exact occurrence under its own observation contract.
3. **MISSING:** a future derived strategic state. This component never produces it,
   and no direct conversion to Safety Evidence MISSING is provided, even in tests.

The only value in ThreatVisibilityAbsence is NOT_VISIBLE. It is a separate enum;
ThreatProximity remains unchanged with NEARBY/AWAY.

NOT_VISIBLE does not establish map-wide absence, source completeness, source health,
reliability, danger, or strategic relevance. STALE preserves the historical negative
claim and does not assert current visibility.

## Immutable contracts and pure builder

ThreatAbsenceClaim contains threat_id, ref, visibility, temporal_policy_id.
Identifiers must be exact nonempty non-whitespace strings. Valid strings remain
unchanged, including surrounding whitespace. Strings are not parsed into identities
or namespaces. visibility must be the enum member, not a plain string.

build_threat_absence_observations(event, projection, temporal_snapshot, claims)
requires a tuple of claims. Duplicate threat_id values are explicitly rejected.
Multiple distinct threats are supported. Empty claims are valid and assert nothing
about enemies, coverage, safety, or completeness.

ThreatAbsenceObservation carries:
threat_id, ref, visibility, source_id, observed_tick, temporal_status,
last_observed_tick, age_ticks, temporal_policy_id, max_age_ticks.

ThreatAbsenceObservationSnapshot carries:
timeline_id, event_id, projection_id, tracker_state_id, temporal_snapshot_id,
selected_clock_id, selected_tick, evaluated_at_tick, observations.

Observations are ordered by (threat_id, ref, temporal_policy_id) and stored as a tuple.
Caller inputs are not mutated. There is no hidden state, cache, clock read, I/O,
network, environment read, database, random ID, thread, or scheduler.

## Exact lineage and occurrence binding

The builder validates:

- projection event ID, timeline, source ID and canonical refs against the event;
- the selected stamp against the actual SOURCE or RECEIPT stamp indicated by the
  projection's already selected TimestampBasis;
- temporal snapshot timeline and clock against the event/projection;
- evaluated_at_tick >= selected_tick;
- each claim ref was emitted by that event;
- exactly one temporal entry for (ref, temporal_policy_id);
- no ambiguous entries or conflicting thresholds under one policy identity;
- NEVER_SEEN cannot substantiate an explicit claim;
- last_observed_tick == selected_tick;
- age_ticks == evaluated_at_tick - last_observed_tick.

Invalid lineage is rejected; it is never repaired, clamped or converted. A later
re-observation of the same ref cannot lend freshness to an older occurrence.
Negative and equal logical ticks work under the existing external clock contracts.

FRESH and STALE are copied from Temporal Evidence, with supplied policy identity and
threshold. The builder does not recalculate TTL classification or choose a policy.
Snapshots must come from the accepted Temporal Evidence pipeline; this component is
not a cryptographic authenticity check for manually fabricated upstream objects.

The caller supplies the threat/ref association. An opaque ref does not prove which
threat it describes. Temporal Evidence tracks ref/tick, not event identity: two
different occurrences with identical ref and tick cannot be distinguished by that
tracker alone. Output still binds all supplied envelope identities.

## Deterministic identity

Ruleset: threat.explicit_absence.v1

snapshot_id = ruleset + ":snapshot:" + SHA-256(canonical snapshot content).

Canonical JSON uses sort_keys=True, separators=(',', ':'), ensure_ascii=True, UTF-8.
All output fields and upstream event/projection/tracker/temporal snapshot identities
are bound. Claim input order cannot change the result or identity. No wall clock,
process metadata, UUID, or randomness participates.

## Sibling dependency architecture

    Observation Event -----+
                           +--> Threat Observation
    Temporal Evidence -----+

    Observation Event -----+
                           +--> Threat Absence Observation
    Temporal Evidence -----+

Threat Observation and Threat Absence Observation are SIBLINGS. Neither imports the
other. Future Missing Threat Resolver may consume both.

Production imports only standard library and accepted contracts:
ObservationEvent, TemporalProjection, TimestampBasis,
TemporalEvidenceStatus, TemporalSnapshot, TemporalStatus.

No production call to project_event_time, new_temporal_state, record_observations or
evaluate_freshness is allowed. No existing live/core path imports the new component.

The two legacy foundation guards now explicitly allow exactly these two sibling
paths, with the existing symbol restrictions. Both are exercised with valid contract
imports and rejected constructor/orchestration/dynamic/wildcard cases. Arbitrary
third consumers remain forbidden.

tests/test_threat_observation.py receives only the two necessarily dependent hash
literal updates, classified AUTHORIZED_DEPENDENT_HASH_MAINTENANCE_ONLY.
No previous production file or documentation is modified.

## Contradictory observations

A positive NEARBY/AWAY sighting and explicit NOT_VISIBLE at the same tick may coexist
as contradictory upstream evidence. This component neither inspects, reconciles nor
overwrites the positive sibling. Tests demonstrate compatible fields for a future
resolver without implementing that resolver or mapping negative evidence to Safety.

## Limits

**BLOCKER_BEFORE_REAL_OBSERVATION:**
- real source that explicitly asserts NOT_VISIBLE is not implemented.

**BLOCKER_BEFORE_MISSING_RESOLUTION:**
- positive/negative evidence reconciliation is not implemented.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:**
- Missing Threat Resolver not implemented;
- coverage semantics not implemented;
- threat relevance not implemented;
- live orchestration not implemented.

**ACCEPTED_V01_LIMITATION:**
- one absence claim per threat_id per snapshot;
- no source reliability/completeness model;
- no multi-source reconciliation;
- exact occurrence-tick binding required.

## Validation and acceptance record

The accepted pre-feature baseline is 544/544/544; it is not rerun on resume.
The new suite has 88 tests covering explicit absence, exact binding, silence,
NEVER_SEEN, cross-event refresh, mixed freshness, forged stamps, immutable output,
identity, purity, conflicting sibling evidence, guard restrictions and production
hash preservation. The expected full feature suite has 632 tests.

Post-change gates are run once each: focused guards (6), absence (88), positive
Threat (84), Observation Event (68), Temporal (50), Offline Core (31), full suite
(632). Actual results, old/new hashes and final feature commit identity are recorded
in the external evidence package, not assumed by this document.

No merge, tag, remote, push, PR, detector, resolver, orchestration, Shadow Mode or
real-match integration is part of this task.
