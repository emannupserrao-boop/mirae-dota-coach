# Strategic Objective Context v0.1

Strategic Objective Context identifies intent; it does not choose action.

Objective IDs are opaque.
KNOWN does not mean recommended action.
UNKNOWN is explicit and distinct from absent evidence.
No objective priority or weighting exists in v0.1.
No option is evaluated against the objective in v0.1.
Strategic Objective, Option Safety and Option Outcome Evidence remain independent.
Decision Context v0.2 must bind them explicitly.

## Scope and contracts

This independent, standard-library-only domain answers one question: what
strategic objective is explicitly established for this context and horizon?
It does not judge the objective, compare objectives, evaluate option alignment,
calculate utility, rank, select, issue action, or choose communication authority.

`StrategicObjectiveKnownness` contains exactly `KNOWN` and `UNKNOWN`.
`KNOWN` requires a concrete nonblank `objective_id` string. `UNKNOWN` requires
`objective_id is None`; the string `"UNKNOWN"` is not an uncertainty encoding.
Under `KNOWN`, any nonblank string, even `"UNKNOWN"`, is merely an opaque ID.
There is no taxonomy, default objective, role, hero, phase or action inference.

The frozen `StrategicObjectiveClaim` requires all eight fields:

| Field | Contract |
| --- | --- |
| objective_context_id | Opaque caller-owned context identity |
| knownness | Exact StrategicObjectiveKnownness enum |
| objective_id | Concrete nonblank str for KNOWN; None for UNKNOWN |
| horizon_id | Opaque, explicit caller-owned horizon identity |
| basis_tick | Concrete nonnegative int, excluding bool and subclasses |
| source_id | Opaque source/provenance label |
| evidence_refs | Exact tuple of concrete nonblank strings; no duplicates |
| assessment_policy_id | Opaque external assessment policy identity/version |

All identifiers require exact concrete strings and reject empty/whitespace-only
values. Surrounding whitespace and Unicode are preserved; validation never trims.
References may be empty and preserve order. They are provenance labels only:
contents are never loaded or authenticated. A valid claim certifies structural
consistency, not that the external objective is appropriate or true.

## Explicit binding, uniqueness and absence

The semantic key is exactly `(objective_context_id, horizon_id)`. At most one
claim exists per pair. All duplicate pairs reject, including identical claims
or conflicting sources/policies. No reconciliation, winner, or preference exists.
The same context with different horizons is valid; different contexts with the
same horizon or objective ID remain independent. v0.1 does not model portfolios.

No claim means absent objective-context evidence and produces no row. An explicit
UNKNOWN claim produces an assessment containing UNKNOWN and None. There are no
synthetic rows, context discovery, cartesian completion or inferred uncertainty.

No horizon is parsed as seconds, minutes, near-term, next-wave or next-fight.
No semantic ordering or default horizon exists. Context names are not related to
risk_context_id, safety_context_id or outcome_context_id by spelling or equality.
String equality does not create binding across domains.

## Builder, time and retained evidence

```python
build_strategic_objective_context(
    *, timeline_id: str, selected_clock_id: str, evaluated_at_tick: int,
    claims: tuple[StrategicObjectiveClaim, ...],
) -> StrategicObjectiveSnapshot
```

All four keyword-only arguments are required. The builder is pure and deterministic:
no IO, network, environment, wall clock, random, UUID or mutable global state.
The caller supplies timeline and selected clock; no selection or conversion occurs.
`evaluated_at_tick` is a concrete nonnegative int, excluding bool/subclasses.
Every `basis_tick <= evaluated_at_tick`; future claims reject the whole input.
Older ticks are preserved exactly, without FRESH/STALE/CURRENT/HISTORICAL labels.

Claims must be an exact tuple of exact StrategicObjectiveClaim objects. The builder
revalidates each claim before creating any assessment, including objects whose
frozen fields were deliberately bypassed. Frozen records are ordinary Python
dataclasses, not an authentication or hostile-memory security boundary. Builder
outputs are the validated contract; manual construction of output records does
not certify input validity.

The frozen `StrategicObjectiveAssessment` retains all eight claim fields plus
`base_claim`, the identical original claim object. No reinterpretation occurs.
The frozen `StrategicObjectiveSnapshot` retains timeline_id, selected_clock_id,
evaluated_at_tick, fixed ruleset and an immutable assessments tuple.

## Ordering and identity

Ruleset: `strategic.objective_context.v1`.
Canonical assessment order: objective_context_id, horizon_id, source_id,
assessment_policy_id. This is deterministic storage ordering, with no priority.
Input permutation does not change identity. Reference ordering remains explicit
provenance content and therefore contributes to identity.

`snapshot_id` is `strategic.objective_context.v1:snapshot:<sha256>` of the complete
snapshot dataclass content, including every header, assessment and base claim.
Serialization uses JSON `sort_keys=True`, compact separators `(',', ':')`,
`ensure_ascii=True`, UTF-8 bytes. The snapshot ID itself is excluded as a property.
This is content identity, not proof of authorship or gameplay truth.

## Independence and adversarial examples

`carry.sustainable_progression.v1`, `FARM`, `FIGHT`, `PUSH`, `RETREAT`, Unicode and
space-padded strings may be objective IDs; each is retained verbatim without
action semantics. There is no priority, weight, score, urgency, utility, option_id,
support/opposition, alignment, contribution or fit. There are no role-specific
branches for Carry, Mid, Offlane, Support 4 or Support 5, or hero-specific branches.

Production imports only dataclasses, enum, hashlib and json. It does not import or
consume OptionOutcomeSnapshot, OptionSafetySnapshotV2, Risk Evaluation, legacy
Decision/Farm modules, Observation Event, Temporal Evidence, runtime/service/GSI,
vision or voice. INCREASE is not interpreted as advancing an objective; DECREASE
is not interpreted as harming it. Safety does not define an objective, and an
objective does not change the modeled-risk gate.

## Legacy comparison, reference only

`coach02/decision.py`: legacy `Decision.objective` is an unstructured string on an
action-bearing decision record alongside selected_plan and authority. It is NOT
reusable as the shared objective contract. `coach02/farm_cycle.py` creates the
`CARRY_FARM_CYCLE` decision with `farm_without_unsupported_exposure`, chooses among
farm actions and emits authority; Farm Cycle is carry/farm specific and action-bearing.

`coach02/farm_context.py` remains frozen/reference-only. Its FarmStrategicEvidence
and compose_farm_context bind legacy option assessments to a seed; they do not
define this generic objective context. `coach02/strategic_evidence.py` assembles
FarmOptionEvidencePair/FarmEvidenceAssembly using legacy Action, Safety and
Availability contracts; it is not a bridge to this domain. No adapter is created.

## Future handoff and documented roadmap only

`StrategicObjectiveSnapshot + OptionSafetySnapshotV2 + OptionOutcomeSnapshot`
will be explicitly assembled into future `DecisionContextV2`. Objective, safety,
risk and outcome contexts, horizons/timelines and option IDs require explicit
caller bindings and validation. No joining by string naming. No domain discovers
another domain's rows from equal-looking labels.

NEXT 1 — Decision Context v0.2: explicit assembly only, shared Strategic Objective,
Option Safety rows and Option Outcome rows; no scoring, ranking, selection,
action issuance or communication authority.

NEXT 2 — Feasibility Gate v0.1: generic option executability/availability, distinct
from Safety and desirability. Legacy `coach02/option_availability.py` is farm/resource
specific and not reusable as-is. No feasibility implementation is included here.

NEXT 3 — Decision Arbiter foundation: cross-option comparison, opportunity-cost
reasoning and trade-off policy remain deferred.

## Limitations and blockers

ACCEPTED_V01_LIMITATION: caller declarations only, one objective per exact pair,
no temporal policy, truth verification, priority, option evaluation or authority.

BLOCKER_BEFORE_DECISION_CONTEXT_V02: define and accept explicit cross-domain
bindings, snapshot compatibility, absence/uncertainty handling and rejection rules.
This milestone does not implement that assembly.

BLOCKER_BEFORE_FEASIBILITY_GATE: define a generic executability contract and its
evidence/policy boundaries independently of risk tolerance and desirability.

BLOCKER_BEFORE_DECISION_ARBITER: establish accepted context assembly, feasibility,
cross-option comparison and explicit trade-off/opportunity-cost policies without
turning objective identity or outcome direction into an implicit score.

BLOCKER_BEFORE_ATTENTION_GATE: establish separate communication relevance and
authority contracts; objective knownness grants no permission to speak.

BLOCKER_BEFORE_LIVE: accepted runtime binding, provenance/clock policy, isolation
and offline integration validation are still required. No live integration,
orchestration, Shadow Mode or real-match testing occurs in this milestone.
