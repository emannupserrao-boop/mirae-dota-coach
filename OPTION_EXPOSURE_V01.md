# Option Exposure Observation v0.1

Option Exposure records an explicit upstream assessment for one option and one
exposure context at one exact observation occurrence. It does not calculate exposure.

**EXPOSED does not mean UNSAFE.**

**NOT_EXPOSED does not mean SAFE.**

**UNKNOWN is first-class.**

**Option Exposure is bound to option_id and exposure_context_id.**

**Semantic exposure and temporal freshness are independent axes.**

**STALE preserves historical exposure classification but does not establish current
exposure.** This applies equally to EXPOSED, NOT_EXPOSED and UNKNOWN. FRESH establishes
temporal status under the supplied policy, not truth, safety or danger.

**Option Exposure does not consume Strategic Coverage.**

**Option Exposure does not consume threat semantics.**

## API and identities

`coach02.option_exposure.build_option_exposure(event, projection, temporal_snapshot,
claims)` consumes already-built accepted envelopes. It does not call event projection,
temporal tracking, recording or freshness evaluation. The caller supplies all claims
explicitly as a concrete tuple of frozen `OptionExposureClaim` values:

| Field | Meaning |
| --- | --- |
| `option_id` | Opaque identity of the decision option |
| `exposure_context_id` | Separate opaque external assessment context |
| `ref` | Exact evidence key in this event |
| `exposure` | Concrete `OptionExposureState`: EXPOSED / NOT_EXPOSED / UNKNOWN |
| `temporal_policy_id` | Exact policy selecting the temporal entry |
| `assessment_policy_id` | Explicit external assessment policy/version |

There are no defaults. Every identifier is an exact concrete nonempty,
non-whitespace string; whitespace and Unicode are preserved, never silently trimmed.
Strings and other enums cannot substitute for `OptionExposureState`. Option names,
contexts and refs are not parsed for game meaning or derived from one another.

Uniqueness is the pair `(option_id, exposure_context_id)` per snapshot. The same option
can be EXPOSED in context A and NOT_EXPOSED in context B. Different options can have
different states in the same context. Duplicate pairs fail even when their refs or
policies differ. Nothing selects a strongest/newest claim or reconciles sources.
Shared refs across different pairs are permitted: the caller explicitly supplies
the binding; this layer verifies occurrence membership, not a real-world attribution.

Empty claims produce an empty valid snapshot, not synthetic UNKNOWN rows, safety,
non-exposure, absence of danger or absence of relevant threats. Global envelope
validation still applies to empty snapshots.

## Exact occurrence and temporal authority

The projection must bind the event ID, timeline, source and refs exactly. Its selected
clock/tick must equal the actual event source or receipt stamp selected by its concrete
`TimestampBasis`. Missing stamps and forged projections fail without fallback or
clock conversion. The temporal timeline and clock must match, and evaluation cannot
precede the selected tick. Ticks are concrete integers, including negative ticks;
booleans are rejected.

Each claim requires exactly one temporal entry keyed by `(ref, temporal_policy_id)`.
The ref must be present in the event. Missing, ambiguous and NEVER_SEEN bindings fail.
The entry's `last_observed_tick` must equal the projection's `selected_tick`, and
`age_ticks` must equal `evaluated_at_tick - last_observed_tick`. Event A at tick 100
cannot borrow a later same-ref observation at tick 110. Conflicting thresholds under
the same temporal policy ID fail. Temporal Evidence remains authoritative for
FRESH/STALE: this builder validates structural binding and age, but does not recalculate
classification or certify that a fabricated upstream envelope is truthful.

All six exposure/freshness combinations are preserved. No stale state becomes
UNKNOWN, SAFE, UNSAFE or a claim about current exposure.

## Immutable output and deterministic identity

Frozen `OptionExposureObservation` preserves `option_id`, `exposure_context_id`, `ref`,
`exposure`, `source_id`, `observed_tick`, `temporal_status`, `last_observed_tick`,
`age_ticks`, `temporal_policy_id`, `max_age_ticks` and `assessment_policy_id`.

Frozen `OptionExposureSnapshot` preserves `timeline_id`, `event_id`, `projection_id`,
`tracker_state_id`, `temporal_snapshot_id`, `selected_clock_id`, `selected_tick`,
`evaluated_at_tick` and an immutable tuple of observations. No safety, risk, danger,
threat, coverage, relevance, confidence, probability, action or recommendation is output.

Rows sort by `(option_id, exposure_context_id, ref, temporal_policy_id,
assessment_policy_id)`. The snapshot ID is `option.exposure_observation.v1:snapshot:`
plus SHA-256 of `asdict(snapshot)` serialized as JSON with `sort_keys=True`, compact
separators, `ensure_ascii=True`, and UTF-8. All provenance and assessment fields
participate. Input claim order does not affect the output or ID.

## Accepted downstream review

**NO_DIRECT_TEST_COMPATIBILITY_TARGET_V01**

The actual accepted `option_safety.Exposure` enum is LOW / HIGH / UNKNOWN. It does not
have affirmative EXPOSED or negative NOT_EXPOSED states. A threshold-based LOW/HIGH
classification is not defined by this observation layer. No conversion is invented.

The frozen `FarmOptionSafetyObservation` requires `seed_id`, `option_id`, productive
`action`, `exposure`, `exposure_freshness`, `coverage`, and `coverage_freshness`.
It accepts only ASCII alphanumeric/underscore/hyphen option IDs; this new layer's IDs
are opaque. Its builder rejects duplicate option IDs without a context dimension.
It lacks exposure context, source/ref, policy IDs and full temporal lineage. An
UNKNOWN label or representable FRESH/STALE labels alone cannot make the whole contract
compatible. Any future conversion would require explicit semantics, additional inputs,
context selection and lossiness handling.

There is **no test mapping and no production adapter**. Tests instead verify the actual
contract mismatch, preserved contexts/provenance, and that no Safety or Risk builder
is invoked. Strategic Coverage SUFFICIENT can coexist with EXPOSED or UNKNOWN;
coverage UNKNOWN can coexist with NOT_EXPOSED. RELEVANT/MISSING threats can coexist
with EXPOSED or NOT_EXPOSED options. No risk or safety conclusion follows here.

## Purity, guard maintenance and validation

Production imports only dataclasses, enum, hashlib, json, the three required
Observation Event contracts and the three required Temporal Evidence contracts.
No existing production file changes. No reverse dependency, runtime/GSI/vision,
clock reads, IO, networking, environment, randomness, UUID, DB, subprocess, threads,
async, scheduler, cache, singleton or mutable global state is introduced.

Foundation guards add exactly `coach02/option_exposure.py` as a contract-only consumer.
Existing absence and coverage tests maintain the same explicit allowlist assertion.
No operations, wildcard/module-wide/dynamic imports or arbitrary consumers become
authorized. The finite stored-hash chain is Temporal test -> Event and Threat tests;
Event test -> Threat test. Only the three directly dependent hash literals change.
Reversing those literals and allowlist additions must reproduce the prior test bytes.

The focused suite has 104 named tests corresponding to the requested matrix, including
adversarial cases A-N. Downstream mapping points use independence/lossiness checks.
All line endings and hashes are finalized before gates. Baseline, focused guards,
new focused suite, all specified regressions and the full suite run once each. The
external execution report records actual results, transport traces and byte manifests.

## Limitations and integration blockers

**BLOCKER_BEFORE_REAL_EXPOSURE:** no validated real exposure source/policy; no
path/map/position/reachability model; no Dota-specific option exposure calculation.
There is no geometry, movement speed, hero mobility, attack/spell range, ward/fog
model, route quality, current position, destination, arrival or travel-time model.

**BLOCKER_BEFORE_LIVE_RISK_INTEGRATION:** no production composition of Threat State +
Threat Relevance + Strategic Coverage + Option Exposure; no production Safety adapter;
no live orchestration.

**ACCEPTED_V01_LIMITATION:** one explicit exposure assessment per option/context pair
per snapshot; categorical states only; external assessment policy; no multi-source
reconciliation; no geometry; no actual Dota exposure algorithm. Any future downstream
compatibility demonstration must remain test-only and disclose lossiness until a
separately authorized integration exists. None is provided in this version.
