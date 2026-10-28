# Option Outcome Evidence v0.1

**OutcomeChange describes direction, not utility.**

**INCREASE does not mean GOOD.**

**DECREASE does not mean BAD.**

**UNKNOWN is an explicit assessed state; missing evidence is absence, not UNKNOWN.**

**Option Outcome Evidence does not compare options.**

**Option Outcome Evidence does not calculate opportunity cost.**

**Option Outcome Evidence does not rank or select.**

**Dimensions are opaque and cross-role.**

**Baselines and horizons are explicit and caller-owned.**

**Older basis ticks are preserved but not classified as stale/current in v0.1.**

**Option Safety and Option Outcome Evidence remain orthogonal.**

## Responsibility and accepted scope

Record what prospective direction is explicitly claimed for an option, on an
independent dimension, relative to an explicit baseline and over an explicit
horizon. It does not forecast the consequence or establish that it is desirable,
better than an alternative, worth its risk, or an instruction to act.

The implementation is standard-library-only: dataclasses, enum, hashlib and json.
It does not import Safety, Risk, Decision, Farm Context, Strategic Evidence,
runtime, Observation Event, Temporal Evidence, GSI, service, rules, vision or voice.
There is no compatibility adapter or production orchestration. The approved v0.1
contract intentionally uses opaque dimensions and explicit ticks, not the closed
axes or Event/Temporal dependencies discussed in the earlier architectural sketch.

## API and exact contracts

`build_option_outcome_evidence(*, timeline_id, selected_clock_id, evaluated_at_tick, claims)`
returns `OptionOutcomeSnapshot`. All four arguments are required and keyword-only.

`OutcomeChange` is exactly INCREASE, DECREASE, UNCHANGED, UNKNOWN. INCREASE and
DECREASE describe prospective direction relative to the supplied baseline.
UNCHANGED means no material change under the supplied assessment policy; this
module does not set a materiality threshold. UNCHANGED is not SAFE, and UNKNOWN
is neither BAD nor ZERO.

Frozen `OptionOutcomeClaim` contains option_id, outcome_context_id, dimension_id,
baseline_id, horizon_id, change, basis_tick, source_id, evidence_refs and
assessment_policy_id. There are no defaults or implicit baseline/horizon.

All seven identifiers, timeline_id, selected_clock_id and each evidence ref must
be exact concrete nonblank str. Subclasses and nonstrings are rejected. Leading
or trailing nonblank whitespace is retained, not silently stripped. Identifiers
are opaque: no prefixes, role/hero logic, namespace inference, unit conversion or
semantic relationships are derived from string equality.

dimension_id has no gameplay enum. resource_access.v1, objective_progress.v1,
commitment.v1 and reversibility.v1 are possible caller labels only; none has a
production special case. outcome_context_id is not Strategic Objective, Execution
State, risk_context_id or safety_context_id. The caller must establish any future
cross-domain relationship explicitly.

evidence_refs must be an exact tuple of exact nonblank strings with no duplicates.
An empty tuple is valid: v0.1 accepts caller assertions without authenticating
their support. References are labels, never content to load. Their exact tuple
order is retained in the claim, evidence and identity; no ref normalization or
merging is performed. The snapshot does not certify the truth of a prediction.

The exact semantic uniqueness key is (option_id, outcome_context_id, dimension_id,
baseline_id, horizon_id). Duplicates reject even if source, policy, change or tick
differs, or the duplicate is identical. There is no multi-source reconciliation.
Different baselines, horizons, contexts, options and dimensions remain independent.

Frozen `OptionOutcomeEvidence` mirrors all ten claim fields and retains the exact
input object as base_claim. The builder validates all inputs before producing
rows; exact claim type is required and field validation is repeated at the
boundary, including for manually altered frozen objects. Output dataclasses are
immutable transport records; the builder is the supported validated construction
path. They do not add independent semantic evaluation to public constructors.

Frozen `OptionOutcomeSnapshot` contains timeline_id, selected_clock_id,
evaluated_at_tick, ruleset and evidences (an immutable tuple). Its fixed builder
ruleset is `option.outcome_evidence.v1`. Exactly one evidence row is produced per
explicit claim. Empty claims yield no rows; missing dimensions are not filled
with UNKNOWN, UNCHANGED or a Cartesian product. No option universe is discovered.

## Time boundary

basis_tick and evaluated_at_tick must be concrete nonnegative int, excluding bool
and int subclasses. Require basis_tick <= evaluated_at_tick. Equal ticks and older
ticks are both valid; both are preserved exactly. There is no FRESH/STALE or
CURRENT/HISTORICAL classification, TTL, clock selection, clock read or conversion.

timeline_id and selected_clock_id bind the whole snapshot. The caller is
responsible for supplying claims whose basis ticks refer to that timeline/clock;
claims have no independent clock stamp for this builder to authenticate. Opaque
horizon_id does not encode an elapsed duration and is not ordered or parsed.
No default baseline means neither current state, doing nothing, another option
nor a previous frame is assumed.

## Canonical order and identity

Evidence order is lexicographic by option_id, outcome_context_id, dimension_id,
baseline_id, horizon_id, source_id, assessment_policy_id. OutcomeChange never
determines order. Source/policy remain in the specified ordering key even though
the preceding five-field uniqueness rule prevents ties between accepted rows.

snapshot_id is `option.outcome_evidence.v1:snapshot:<sha256>`, computed from
asdict(snapshot), JSON sort_keys=True, compact separators, ensure_ascii=True,
UTF-8. The computed property itself is excluded. Identity includes all headers,
evidence fields and complete base_claim content. Permuting the claims tuple
preserves identity; changing a meaningful field or header changes identity.
Whitespace, Unicode and opaque refs are preserved without silent normalization.
No clock, IO, network, environment, random/UUID or mutable global state is used.

## Independence and adversarial interpretation

- INCREASE for resource-like and commitment-like dimensions has the same
  descriptive meaning. Neither is intrinsically favorable.
- One option may have INCREASE on one dimension and DECREASE on another; there is
  no aggregate conclusion. Multiple options with opposing changes are not ranked.
- Explicit UNKNOWN keeps a row; absent evidence does not create one.
- Short/long horizon labels and different baselines do not define ordering,
  comparability, opportunity cost or pairwise subtraction.
- Identical source/policy strings across dimensions do not merge claims.
- Gold, farm, commitment or role names inside IDs have no special behavior.
- Older basis ticks remain numbers, never currentness assertions.

No scalar value, reward/utility/expected-value score, magnitude, probability,
confidence percentage, weighted sum, combined LOW/MEDIUM/HIGH rating, preference,
dominance, recommendation, ranking, selection, action or communication authority.
Commitment, reversibility and future resource access may be opaque dimensions;
no execution, abort window/cost, urgency, ownership or strategic policy is built.
All five roles (Carry, Mid, Offlane, Support 4 and Support 5) use the same contract,
without farm/gold priority, lane ownership, core status or solo resource ownership.

## Legacy review: reference only, frozen

`coach02/decision.py` DecisionContext carries old availability/safe Conditions,
global increased_risk, farm Actions, knowledge/player refs and Execution. It
cannot represent these independent baseline/horizon/dimension-bound claims
without loss and is not a direct target. No old Truth or Action conversion exists.

`coach02/farm_context.py` composes seed-bound FarmStrategicEvidence into that
legacy context, restricted to productive farm actions. It stays frozen and
reference-only for this domain. `coach02/strategic_evidence.py` preserves old
risk/safety/availability envelopes; its exact-binding pattern is a useful design
reference, not a dependency or adapter.

`CandidatePlan.expected_future_state` is an unstructured string selected from
`coach02/farm_cycle.py` FUTURE constants. It lacks independent dimension,
baseline, horizon, assessment tick and per-claim source/policy provenance. It is
too lossy to serve as prospective Outcome Evidence.

`coach02/option_availability.py` describes supplied current resource presence and
access, under seed/option/action binding and supplied freshness. Availability is
not a prospective change relative to an explicit baseline over an explicit
horizon. It stays unchanged. No legacy/current module is modified or adapted.

## Future handoff and blockers

Future composition only, not an implemented dependency:

```text
OptionSafetySnapshotV2 + OptionOutcomeSnapshot
  + future Strategic Objective Context
  + future execution/commitment-related evidence
  -> future DecisionContextV2
```

Safety cannot establish an outcome and outcome direction cannot establish a risk
gate. RISK_NOT_BLOCKING does not mean a better outcome; RISK_BLOCKING does not
mean a worse one; INDETERMINATE does not manufacture an UNKNOWN outcome row.

BLOCKER_BEFORE_DECISION_CONTEXT_V02: explicit cross-domain option/context/clock
bindings, shared objective and separately accepted execution/commitment evidence
remain future work. Context must preserve full objects and uncertainty; it must
not score, rank, select, issue actions or choose communication authority.

BLOCKER_BEFORE_DECISION_ARBITER: cross-option comparisons, trade-off policy,
opportunity cost, sacrifices, tie-breaking and selection have not been accepted.

BLOCKER_BEFORE_ATTENTION_GATE: communication urgency, suppression, repetitions,
cognitive load and speech/output authority are not modeled here.

BLOCKER_BEFORE_LIVE: supplied source/policy/ref labels are not authenticated real
observations or forecasts. Clock ownership, validated real sources and live
orchestration remain unresolved. No GSI/vision or real-match readiness claim.

ACCEPTED_V01_LIMITATION: directional categorical outcome only; opaque dimensions,
baselines and horizons; no magnitude, probability, utility, comparison or
selection. Exact ticks are metadata; freshness and policy/source truth are not
established. No Strategic Objective, Execution Lifecycle or urgency implementation.

## Scope and validation discipline

Only this document, coach02/option_outcome_evidence.py and
tests/test_option_outcome_evidence.py are new. Existing production and existing
tests/guards remain byte-identical. Standard-library-only dependencies require no
new protected-domain consumer allowance. No protected imports are introduced.

The focused matrix has 104 tests covering contracts, strict identity/ticks,
absence, uniqueness, provenance, deterministic identity, adversarial dimensions,
forbidden semantics, purity and preservation. Each required gate runs once;
actual results, transport, manifests and final bytes are recorded externally.
WinError 10054 blocks; 10053 is accepted only for the known 262145-byte oversized
request with server 413 followed by valid 200. No retry or post-gate project edit.
No promotion or later architecture is authorized by this milestone.
