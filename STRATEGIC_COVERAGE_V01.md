# Strategic Coverage Observation v0.1

“SUFFICIENT coverage does not mean SAFE.”

“INSUFFICIENT coverage does not mean DANGEROUS.”

“UNKNOWN is first-class.”

“Strategic Coverage is context-bound.”

“Strategic Coverage is not Visibility Completeness.”

“STALE preserves historical coverage classification but does not establish current coverage.”

## Role

An upstream caller explicitly reports information coverage for one strategic
context at an exact occurrence. This component binds that classification to
Observation Event and Temporal Evidence; it does not calculate it. It observes
no game state, wards, vision, geometry, threats, or minimap. It has no real source,
coverage policy, risk rule, Safety adapter, or live orchestration.

Visibility Completeness assesses one explicit NOT_VISIBLE occurrence for potential
absence/MISSING inference. Strategic Coverage assesses the information available
for a strategic context. The three similarly named states belong to different
enums and domains. There is no aliasing, reuse, dependency or reconciliation.

Strategic Coverage is a sibling of the threat observation/relevance chain and
can exist without any identified threat. Combining them belongs downstream.

## Input contracts

`StrategicCoverageState` contains exactly `SUFFICIENT`, `INSUFFICIENT`, `UNKNOWN`.
UNKNOWN is neither INSUFFICIENT nor the absence of an assessment. None of the
states imply truthfulness, safety, danger, threat visibility or relevance.

Frozen `StrategicCoverageClaim` requires:

- `coverage_context_id`: opaque strategic context identity;
- `ref`: exact opaque evidence ref emitted by the event;
- `coverage`: concrete `StrategicCoverageState`;
- `temporal_policy_id`: selects the exact temporal entry;
- `assessment_policy_id`: opaque identity/version of the external assessment policy.

All four identifiers are exact strings, nonempty and not whitespace-only.
They are never trimmed or interpreted. Leading/trailing spaces in nonblank
identifiers are significant. No default state, temporal policy or assessment
policy is supplied. A string or another enum is not a coverage state.

Context is not a global map property. Different contexts may simultaneously be
SUFFICIENT and UNKNOWN. At most one claim per context is allowed in a snapshot;
duplicates are rejected even with different refs, policies or states. No state is
selected, averaged or merged. Different contexts can explicitly reference the
same occurrence; the builder does not infer an exclusive context/ref namespace.

## Builder, lineage and occurrence binding

```python
build_strategic_coverage(
    event: ObservationEvent,
    projection: TemporalProjection,
    temporal_snapshot: TemporalSnapshot,
    claims: tuple[StrategicCoverageClaim, ...],
) -> StrategicCoverageSnapshot
```

All envelopes must have the exact accepted types. The caller constructs them.
Production never calls project_event_time, new_temporal_state,
record_observations or evaluate_freshness.

Required global bindings:

- projection event ID equals event.event_id;
- projection timeline/source/refs equal the event timeline/source/refs;
- temporal timeline equals event timeline;
- temporal clock equals projection selected clock;
- temporal evaluated tick is at least the projection selected tick;
- projection selected clock/tick exactly match the actual event source or receipt
  stamp selected by the explicit TimestampBasis.

A forged projection, missing selected source stamp, cross-clock bundle or lineage
mismatch is rejected. No conversion, fallback, repair or clock read occurs.
Source and receipt bases both work. Negative and equal ticks are valid on the
caller-owned logical clock; bool is not accepted as an integer tick.

For each claim, its ref must appear in event.refs. The temporal index key is exactly
`(claim.ref, claim.temporal_policy_id)`. Missing or duplicate entries are rejected,
as is NEVER_SEEN for a selected occurrence. Conflicting thresholds under one policy
identity are rejected. Supported temporal status, identifiers, tuple/entry types,
integer metadata and nonnegative thresholds are validated defensively.

The selected entry must satisfy:

```python
entry.last_observed_tick == projection.selected_tick
entry.age_ticks == temporal_snapshot.evaluated_at_tick - entry.last_observed_tick
```

An event at tick 100 cannot borrow freshness from a later occurrence of the same
ref at tick 110. Matching is exact; namespace words such as ward, safe, route or
vision carry no semantic authority. The context is explicitly supplied and is
never derived from the ref.

The builder copies FRESH/STALE; it does not recompute the threshold comparison.
Accepted Temporal Evidence owns that classification. FRESH does not authenticate
coverage truth, source quality, or actual map coverage. Content identities do not
authenticate manually fabricated envelopes. Inherited limitation: refs/ticks
alone do not distinguish different events sharing those same values; the event
and projection IDs are preserved for provenance, not magically authenticated.

## Output and temporal semantics

Frozen `StrategicCoverageObservation` contains:

```text
coverage_context_id, ref, coverage, source_id, observed_tick,
temporal_status, last_observed_tick, age_ticks,
temporal_policy_id, max_age_ticks, assessment_policy_id
```

Frozen `StrategicCoverageSnapshot` contains:

```text
timeline_id, event_id, projection_id, tracker_state_id, temporal_snapshot_id,
selected_clock_id, selected_tick, evaluated_at_tick, observations
```

It exposes a deterministic `snapshot_id`. Observations form an immutable tuple.
Complete meaningful provenance is retained through the envelope IDs and row fields.
There are no threat_id, relevance, missing, exposure, risk, safety, route,
recommendation, action, score or probability outputs.

All six coverage/freshness combinations are supported. SUFFICIENT/STALE says
coverage was sufficient at the historical occurrence, and that observation is
stale under the supplied temporal policy. It does not establish current sufficient
coverage and is not silently changed to UNKNOWN. Semantic and temporal states
remain separate axes.

`claims=()` returns a valid empty snapshot after validating the envelopes. It means
no assessments were selected from that event. It does not imply UNKNOWN,
insufficient coverage, no vision, no threats, safety or danger. No automatic rows
are generated. A subset of event refs may be explicitly selected.

## Determinism

Ruleset: `strategic.coverage_observation.v1`.

The ID is `ruleset:snapshot:SHA-256` of `dataclasses.asdict(snapshot)`, serialized
as JSON with sorted keys, compact separators, ensure_ascii=True and UTF-8.
It binds event/projection/tracker/temporal snapshot identities, timeline/clock/ticks,
contexts, coverage, freshness, thresholds and both policy identities.

Claims sort by coverage_context_id, ref, temporal_policy_id, assessment_policy_id.
Their input order does not affect output or ID. Full upstream identities remain
preserved; changing their own ordered content may change those IDs. There is no
wall clock, generated UUID, hidden memory, environment, random value or cache.

## Test-only Safety compatibility

The accepted `CoverageObservation` has only `sufficient: Truth` and
`freshness: Freshness`. A test-only helper demonstrates:

| Strategic Coverage | Downstream representation |
|---|---|
| SUFFICIENT | Truth.YES |
| INSUFFICIENT | Truth.NO |
| UNKNOWN | Truth.UNKNOWN |
| TemporalStatus.FRESH | Freshness.FRESH |
| TemporalStatus.STALE | Freshness.STALE |

Truth.YES here still does not mean SAFE. The helper performs no risk inference and
does not call build_risk_awareness. It is intentionally a lossy representation
demo: CoverageObservation has no context or provenance fields. Context selection,
provenance retention and integration are future downstream work, not a production
adapter hidden in these tests.

## Dependency guards and preservation

Production imports only dataclasses, enum, hashlib, json and the required contracts:
ObservationEvent, TemporalProjection, TimestampBasis, TemporalEvidenceStatus,
TemporalSnapshot and TemporalStatus.

Event and Temporal guards add exactly `coach02/strategic_coverage.py` to the existing
two-consumer allowlist, without widening allowed symbols. The corresponding
allowlist assertion in Threat Absence adds the same path. Arbitrary consumers,
upstream/live modules, wildcard/module-wide/dynamic imports, contract constructors
and orchestration aliases remain rejected.

Dependent hash maintenance is limited to literals: Temporal test hash in Event
and Threat tests; Event test hash in Threat tests. No other semantic test changes
are needed. No existing production or documentation file changes. No existing
production imports Strategic Coverage.

## Validation and limitations

104 focused tests cover the requested 91 requirements and additional structural,
provenance, purity and coexistence cases. Fixtures use accepted upstream builders.
Adversarial A–K include all three fresh states, stale sufficient, empty claims,
mixed contexts, duplicate contexts, wrong refs, cross-event refresh, separate
Visibility Completeness and relevant missing threat coexistence. None infer risk.

Every required gate runs once, without retry-until-green. LF formatting and all
hash literal maintenance are finalized before gates. The committed files must
match the tested manifest exactly. External reports record the actual results.

BLOCKER_BEFORE_REAL_COVERAGE:

- no validated real strategic coverage source/policy;
- no ward/map/minimap/vision implementation.

BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:

- no production composition of Threat Relevance + Threat State + Strategic Coverage;
- no Option Exposure real source;
- no production Safety integration;
- no live orchestration.

ACCEPTED_V01_LIMITATION:

- one explicit coverage claim per context per snapshot;
- categorical only;
- policy implementation external;
- no multi-source reconciliation;
- no geometry or Dota-specific coverage calculation.
