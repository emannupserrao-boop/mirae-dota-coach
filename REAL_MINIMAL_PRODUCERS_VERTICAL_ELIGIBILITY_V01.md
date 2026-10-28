# Real Minimal Producers + Vertical Eligibility Proof v0.1

This is a generic semantic-evidence milestone, not Juggernaut validation.
The accepted immutable REAL_GSI Foundation artifact contains Phantom Assassin
(`npc_dota_hero_phantom_assassin`), 835 accepted updates over about 10 min 50 s.
No new capture, player-facing output or strategic decision is introduced.

## Farm evidence

`farm_cadence_evidence_v01` implements frozen `FarmCadencePolicyV1`,
`FarmCadenceSampleV1`, `FarmCadenceStateV1`, `FarmCadenceEvidenceV1` and
`FarmCadenceUpdateV1`. `new_farm_cadence_state_v1` creates bounded memory;
`advance_farm_cadence_v1` consumes a canonical `RuntimeUpdateResultV1`.
The shared `SemanticInputPresence` domain is exactly PRESENT / ABSENT.

`FarmCadenceStatus` is exactly OBSERVED_INTERVAL / INDETERMINATE.
Cadence is retrospective observed LH evidence, with no farm quality,
benchmark, trend rating or prediction. An eligible non-overlapping interval
preserves its start/end samples, delta LH and gameplay duration.
The derived presentation rate is `60 * delta_lh / gameplay_duration`.
A valid zero-LH interval is OBSERVED_INTERVAL with rate zero.
Unrepresentable nonfinite rates produce INDETERMINATE, with an explicit reason.

`source_match_time` measures gameplay duration. Receipt logical tick and receive
sequence order occurrences; physical receipt elapsed time bounds continuity;
the embedded Foundation receipt Temporal result establishes freshness.
Provider timestamps never supply farm duration. Numeric LH additionally must
be a nonnegative integer counter; booleans and fractional counters are invalid.
Current accepted snapshot, local/session scope, hero/phase, explicit pause and
alive status, capability validity and freshness must all be established.

The policy supplies observational minimum interval, maximum receipt gap and
maximum source step. These are continuity constraints, not quality benchmarks.
Only the anchor and last eligible sample are retained. Closing an interval
reuses its endpoint as the next anchor. Session/timeline/hero/policy changes,
rewind, gaps, stale controls, pause, death, unavailable fields or LH regression
clear or re-anchor memory. Equal game times never create a duration. Equal time
with changed LH re-anchors. TIME_ADVANCE has ABSENT current input and creates
no sample; a fresh control can retain comparison memory without retaining a
current conclusion. An out-of-order rejection clears continuity even when
Foundation returns its unchanged previous tick.

## Atomic readiness

`local_readiness_evidence_v01` implements frozen `LocalReadinessPolicyV1`,
`AbilityAvailabilityEvidenceV1`, `ItemPresenceEvidenceV1`,
`ReadinessTransitionV1`, `LocalReadinessSnapshotV1`, `LocalReadinessStateV1`
and `LocalReadinessUpdateV1`. Public builders are
`build_local_readiness_snapshot_v1`, `new_local_readiness_state_v1` and
`advance_local_readiness_v1`.

The caller supplies exact opaque ability/item identities (unique tuples,
at most 32 per resource kind), an optional exact hero selector, policy ID
and continuity bound. The only predicate is
`resource.active_ability_observable.v1`; there is no global combat readiness.
Policies/identifiers are not silently trimmed or strategically interpreted.

`LocalReadinessStatus` is exactly READY / NOT_READY / INDETERMINATE.
READY requires a current eligible local/session/hero/phase scope, explicit
unpaused and alive state, a unique identity match, integer level > 0, finite
nonnegative cooldown equal to zero, concrete can_cast true and explicit active
classification. Contradictory passive flags, missing/invalid/ambiguous required
evidence cause INDETERMINATE. Once all required evidence is valid, an observable
unsatisfied requirement permits NOT_READY. Missing evidence is conservative
even when another observable requirement is false.

Hard invariant: cooldown zero != can_cast. Both are independently required.
This is not a statement to cast, fight, engage or that an action is safe.
The boundary is mana unsupported: no mana sufficiency or affordability is
inferred from can_cast. Complete action feasibility can require more evidence.

`ItemPresenceStatus` is exactly PRESENT / NOT_REPORTED / INDETERMINATE.
PRESENT means a unique queried identity in the evaluated normalized reported
scope. NOT_REPORTED means no match in that scope; it does not prove global
nonownership. Scope completeness is not promised by Foundation normalization:
malformed raw entries can have been omitted upstream. Missing/invalid current
collection, malformed retained identities or duplicate matches abstain.
Identity, slot and observed scalar fields are preserved as provenance.
No activation readiness, build order, item quality or strategy is inferred;
item presence != power spike. Nested evidence refs describe retained snapshot
fields and do not claim independent per-resource Temporal observations.

First eligible readiness evaluation has no transition. Later transitions compare
only the same resource query under the same run/session/timeline/clock/hero and
full policy, within the caller's receipt continuity bound. State retains only
the last eligible queried snapshot. Status changes may include explicit
INDETERMINATE; initial absence is never invented as a prior transition.
Fresh TIME_ADVANCE may retain bounded comparison memory but emits no new facts.
Session/timeline/hero/policy/gap/rewind/shutdown/stale or ineligible scope resets
comparison. Death can establish NOT_READY; respawn re-evaluates current fields.

## Foundation boundary and Shadow replay

Producers use the accepted public Live Runtime result and its existing embedded
Observation/Temporal provenance. They never import or call those lower layers
directly. The narrow shared projection/presence contract lives in the farm
module, avoiding an extra file. It validates current snapshot/result lineage,
receipt projection and current capability/freshness coherence; absent results
never fill forward a current field from cached historical evidence.

`real_minimal_producers_shadow_v01` consumes ordered immutable canonical
Foundation journal records. It recomputes each Foundation input/control with
the accepted reducer and compares the complete Foundation RESULT before using
that result as producer input. Stored semantic outputs are comparison targets,
never replay inputs. The integration does not parse raw GSI or start a listener.

A separate semantic journal uses `runtime.real_minimal_producers_shadow.v1`.
The finite record types are HEADER / PRODUCER_RESULT / DIAGNOSTIC / FOOTER.
HEADER binds actual canonical Foundation journal SHA-256, REAL_GSI or SYNTHETIC
origin, semantic and producer rulesets, full policies and selectors.
PRODUCER_RESULT binds Foundation input/result IDs, runtime state/snapshot/payload,
current lineage/tick/sequence, producer states, evidence, queries and transitions.
FOOTER binds final Foundation and producer state IDs and structural proof counts.
The Foundation journal schema and original artifact bytes remain unchanged.

All deterministic identities use compact sorted-key ensure_ascii JSON, UTF-8
and SHA-256. No absolute path, wall clock, random or profiling diagnostic enters
identity. The builder is deterministic; an optional caller-injected timer only
measures separate diagnostics and has no default clock. Resource and anchor
memory are bounded; caller-owned batch replay records are separate from reducer
state. Journal IO is explicit outside the pure reducers, uses exclusive creation,
and propagates write/fsync errors without fallback. Partial journal prefixes are
INCOMPLETE; malformed records, hashes or deterministic mismatches are CORRUPT.
Complete semantic replay compares deterministic evidence/lineage and requires
zero divergences. No Dota, clocks, scheduler, filesystem or network is needed
by pure replay over already loaded records.

## Evidence and acceptance

The SYNTHETIC fixture and tests cover death/respawn, pause/resume, gap/rewind,
session/timeline changes, regressions, equal-time inconsistencies, missing or
duplicate resource identities and invalid nested fields. Those events are not
claimed as real events in the accepted PA capture. The immutable real artifact
is read-only; its producer execution and semantic replay run once as external
acceptance gates. Real selectors are explicit resource identities, not hero
strategy. Artifact/hash inspection tests do not execute that real pipeline.
Reports and semantic journals remain outside Git and contain no auth secrets.

Acceptance records exact discovered test counts, the once-only focused gates,
156/156 pre-feature file preservation, real interval/resource/transition proof,
zero-divergence semantic replay, canonical regressions and one full suite with
an external 360-second timeout. Profiling separates farm, readiness, semantic
identity/serialization and journal IO where practical. Projection validation is
included in each reducer cost. Combined producer target p95 <= 5 ms; the overall
Foundation plus semantic budget remains <250 ms. A nonmaterial target miss is
reported as follow-up without byte edits after freeze.

## Explicit exclusions

UNKNOWN != FALSE; ABSENT != NEGATIVE; STALE != MISSING.
There is no Option Outcome translation, no complete Feasibility,
no Risk/Safety, no Arbiter, selection or execution reconciliation.
No Microplan, Attention, CoachCall, Voice/TTS, service integration, output
authority, player-facing coaching, action execution or cloud/LLM live inference.
There are no existing production/test/guard/hash edits. Core producers remain
generic across heroes and all five roles; Carry is external caller context.

Future Juggernaut validation needs a targeted real bot capture demonstrating
its queried resources. Future semantic-to-option translation and Decision
Shadow require separate architectural closure and milestones. This milestone
ends at REAL_GSI -> Foundation -> deterministic semantic evidence.
