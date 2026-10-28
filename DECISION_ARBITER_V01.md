# Decision Arbiter v0.1

Decision Arbiter v0.1 selects a decision candidate; it does not execute an action.

RISK_BLOCKING is an Arbiter exclusion signal under this fixed policy, not a global UNSAFE verdict.

INFEASIBLE is an Arbiter exclusion signal, not a strategically BAD verdict.

Any admission-indeterminate candidate blocks global selection.

A single admitted candidate can be selected without pairwise evidence.

With multiple admitted candidates, complete explicit pairwise coverage is required.

Pairwise evidence is never inferred.

A direct winner must have explicit direct advantage over every other admitted candidate.

No transitivity, scoring, win counting or ranking is used.

Cycles, TRADE_OFF and EQUIVALENT may produce NO_SELECTION.

SELECTED does not authorize action, execution or communication.

SELECTION != ACTION. SELECTION != COMMUNICATION. SELECTION != EXECUTION.

## Inputs and ownership

This is the first versioned generic Mirae selection component. Candidate admission
and direct comparison are consecutive internal policy stages in one module; no
separate Candidate Admissibility milestone or runtime adapter is introduced.

Production imports exactly eleven accepted contracts:

- DecisionContextV2, OptionDecisionContextV2, DecisionEvidencePresence
- OptionSafetyEvaluationV2, OptionSafetyGateStatus
- FeasibilitySnapshotV1, OptionFeasibilityAssessmentV1, FeasibilityGateStatus
- PairwiseTradeoffSnapshotV1, PairwiseTradeoffEvidenceV1, PairwiseTradeoffConclusion

Safety arrives only as the exact evaluation embedded in Decision Context. Direct
Safety imports validate its concrete type and enum; no separate Safety snapshot
is consumed. There are no upstream builder calls or upstream constructions.
No direct Objective, Outcome, Relation, Risk, Threat, legacy Decision/Farm, runtime,
service, GSI, voice or vision imports. OpportunityCostConclusion is not imported.
Opportunity costs and relation bundles never determine selection.

Accepted upstream objects retain ownership of their embedded semantic validity.
Structural validation does not recompute Risk, tolerance, requirements, objective
relations or comparative claims. Claims remain caller-supplied, not authenticated
truth. Frozen dataclass construction or content hashing alone does not certify
arbitrary forged nested evidence. Only the consumed boundary described below is
revalidated; retained nested semantics remain the upstream responsibility.

## Request and API

Frozen DecisionArbiterRequestV1 has exactly decision_context_id, arbiter_context_id
and pairwise_context_id. All are required exact concrete nonblank str, preserved
without trimming, parsing, coercion or inferred context relationships. The request
is revalidated at the builder boundary. pairwise_context_id remains required when
zero or one option is admitted, without requiring any matching row in those cases.
There are no configurable weights, scores, mappings or tie-break policies.

```python
build_decision_arbiter_result_v1(
    *, decision_context: DecisionContextV2,
    feasibility_snapshot: FeasibilitySnapshotV1,
    pairwise_snapshot: PairwiseTradeoffSnapshotV1,
    request: DecisionArbiterRequestV1,
) -> DecisionArbiterResultV1
```

All inputs are mandatory and keyword-only. Exact tuple containers are required;
no list conversion or defaults. The function is pure, deterministic and has no
IO, network, environment, wall clock, randomness or mutable global state.

## Validation before policy

All roots, option rows, Feasibility rows, Safety evaluations and Pairwise rows
have exact concrete types, excluding subclasses. Root rulesets must match their
accepted versions. IDs are concrete nonblank strings and ticks concrete
nonnegative ints, excluding bool/subclasses.

Request, Decision Context, Feasibility and Pairwise decision_context_id must agree.
Both decision_context_object_id values must equal DecisionContextV2.context_id.
The latter is a content identity, not Python id(context) or the caller's context
label. Timeline, selected clock and assembly/evaluation tick must match exactly.
No max tick, clock conversion, re-aging or temporal inference occurs.

Pairwise objective_context_id and objective_horizon_id must match Decision
Context. objective_id must equal the embedded objective ID, including None.
Comparisons without a concrete objective are rejected. relation_snapshot_id is
retained through the Pairwise identity; no direct Relation snapshot is required.

Decision Context option IDs are unique. Feasibility must have exactly the same
ID set, one assessment per option, no duplicates/extras/missing rows, exact
FeasibilityGateStatus, and base_option_context is the corresponding exact option
object. No requirement evidence is reinterpreted.

Safety ABSENT requires safety_evaluation is None and derives safety_gate_status
None. PRESENT requires exact OptionSafetyEvaluationV2 and OptionSafetyGateStatus,
with option_id, risk_context_id and safety_context_id matching the option.
safety_context_id=None is legitimate for a PRESENT evaluation, not absence.
The Arbiter does not inspect base_risk_evaluation or supported_risk_tolerance.

Every Pairwise comparison, including irrelevant rows, must have exact type and
conclusion enum, matching decision/tick, concrete context/source/policy IDs, and
two known distinct options. Duplicate unordered pairs in the same pairwise
context reject even if orientation, conclusion or source differs. Distinct
contexts may contain different valid comparisons of the same pair.

All structural checks precede every selection-policy return, including empty,
single and admission-indeterminate cases. Malformed inputs raise validation
errors; they are not converted into an indeterminate decision or silently fixed.

## Fixed admission

ArbiterCandidateAdmissionStatus: ADMITTED, EXCLUDED, INDETERMINATE.

| Safety | FEASIBLE | INFEASIBLE | INDETERMINATE |
| --- | --- | --- | --- |
| PRESENT / RISK_BLOCKING | EXCLUDED | EXCLUDED | EXCLUDED |
| PRESENT / RISK_NOT_BLOCKING | ADMITTED | EXCLUDED | INDETERMINATE |
| PRESENT / INDETERMINATE | INDETERMINATE | EXCLUDED | INDETERMINATE |
| ABSENT / None | INDETERMINATE | EXCLUDED | INDETERMINATE |

Decisive exclusion dominates uncertainty on the other axis. This is an explicit
new Arbiter policy; Decision Context itself still retains every bound candidate.
Neither exclusion nor admission changes upstream meanings. Nonblocking risk is
not global safety or recommendation; feasibility is not strategic desirability.

Frozen ArbiterCandidateAssessmentV1 fields: option_id, admission_status,
safety_presence, safety_gate_status, feasibility_status, base_option_context,
base_feasibility_assessment. Both base objects are preserved exactly. The two
axes remain auditable, including simultaneous exclusion; no scalar candidate
reason, selected flag, score, weight or action is added. Excluded candidates stay
in the complete candidate_assessments tuple.

## Selection stages and reasons

DecisionArbiterStatus contains exactly SELECTED, NO_SELECTION, INDETERMINATE.
DecisionArbiterReason contains exactly the seven reasons below, in policy order:

1. Any admission INDETERMINATE: INDETERMINATE / CANDIDATE_ADMISSION_INDETERMINATE.
2. Zero admitted: NO_SELECTION / NO_ADMITTED_OPTIONS.
3. One admitted: SELECTED / SINGLE_ADMITTED_OPTION.
4. Multiple admitted, missing required pair: INDETERMINATE / PAIRWISE_EVIDENCE_INCOMPLETE.
5. Complete pairs, any required INDETERMINATE: INDETERMINATE / PAIRWISE_EVIDENCE_INDETERMINATE.
6. Explicit direct advantage over all others: SELECTED / UNIQUE_DIRECT_ADVANTAGE.
7. Otherwise: NO_SELECTION / NO_UNIQUE_DIRECT_ADVANTAGE.

Empty Decision Context with empty Feasibility is valid and returns no admitted
options. One admitted candidate can be selected even without a concrete objective
or comparison rows. It is selection within the explicit candidate universe, not
absolute optimality or superiority over an unmodeled alternative of doing nothing.

For multiple admitted options only the request's exact pairwise_context_id and
pairs wholly inside the admitted set participate. Valid other-context/excluded
rows remain allowed but unused. Required unordered pairs are enumerated only to
check completeness, never to create evidence. Incompleteness precedes explicit
pair uncertainty. Even uncertainty between other alternatives blocks selection
before searching for a universal direct advantage.

LEFT_ADVANTAGE favors the preserved left side; RIGHT_ADVANTAGE favors the right.
TRADE_OFF and EQUIVALENT give neither side direct advantage in that pair. A/B and
B/C never imply A/C. The universal direct predicate uses no counting, weighted
sum, score, majority, Elo, graph closure, topological sorting or global ordering.
Valid pair uniqueness makes two simultaneous universal direct winners impossible.
Lexical iteration cannot break ties because there are no selectable tied winners.

A>B, B>C, C>A gives NO_SELECTION, not INDETERMINATE, when evidence is complete.
No cycle detector is needed. D>A, D>B, D>C can select D despite that cycle.
TRADE_OFF is not a tie; EQUIVALENT is not global equivalence. Neither is resolved
by an arbitrary option-ID tie-break. No runner-up or full ordering is produced.

## Result and identity

Frozen DecisionArbiterResultV1 has decision_context_id, decision_context_object_id,
feasibility_snapshot_id, pairwise_snapshot_id, timeline_id, selected_clock_id,
evaluated_at_tick, base_request, candidate_assessments, considered_pairwise_evidence,
status, reason, selected_option_id, selected_option and ruleset.

SELECTED carries the exact selected OptionDecisionContextV2 member and matching
concrete ID. All other results carry None for both. Output records are builder
results; manually constructing/replacing an output does not certify its invariants.

The exact request and exact considered PairwiseTradeoffEvidenceV1 objects are
preserved. considered_pairwise_evidence is empty for admission indeterminacy,
zero admitted and one admitted. With multiple admitted it retains all available
required rows, including on incomplete/indeterminate results.

Candidate assessments sort by option_id. Considered rows sort by pairwise_context_id,
unordered option pair, source_id and assessment_policy_id. This is representation,
never preference. Caller pair orientation is preserved.

Fixed ruleset: decision.arbiter.v1. result_id is decision.arbiter.v1:result:<sha256>.
Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True and UTF-8.
Identity binds the complete request, exact public Context/Feasibility/Pairwise IDs,
root time/context fields, candidate IDs and derived statuses/presence, considered
evidence_id values, result status/reason, selected ID and ruleset. Upstream objects
are not blindly asdict-serialized again. Their IDs already bind accepted content
and normalized set-like tuples. Feasibility requirement order and Pairwise bundle
ID order remain equivalent when their upstream public IDs are equivalent.
Changes to unused upstream content may change source IDs and thus result identity
without changing selection. No random UUID or wall-clock identity exists.

## Legacy review and guard maintenance

coach02/decision.py defines action-bearing CandidatePlan, Decision.selected_plan,
Decision.output_authority and Decision.next_action. Legacy Execution has execution
state; Action contains farm-specific actions. context_builder.py produces runtime
eligibility seeds; farm_context.py and strategic_evidence.py compose farm evidence,
legacy action enums and supplied Execution. No legacy reuse/adapter is introduced.

Only two existing guard functions change: consumer_violations in
tests/test_decision_context_v02.py and import_violations in
tests/test_feasibility_gate_v01.py. Exact path-specific authorization grants only
coach02/decision_arbiter_v01.py the eleven contracts above, without expanding any
existing consumer. Constructor/alias/module/wildcard/dynamic imports remain blocked.
The finite hash chain updates one literal in Feasibility tests, two in Relation
tests and three in Pairwise tests. No other existing test semantics or production
bytes change. External evidence records old/new hashes and exact edits.

The 104 focused tests cover the full matrix, rejection boundaries, complete and
sparse comparisons, precedence, orientation, cycles, identity normalization,
provenance, purity, import guards and preservation. All project bytes are frozen
before post-implementation gates; every gate runs once. Full suites use an external
180-second timeout. No retry-until-green or edits after validation failure.

## BLOCKER_BEFORE_HYSTERESIS

No previous selection state, switch cost, minimum hold or stickiness. A future
layer may consume successive immutable results using IDs/context/time, owning
its own state. This module has no switching policy.

## BLOCKER_BEFORE_EXECUTION

Selection does not start lifecycle. No commitment, reversibility, abort/completion
or execution state. No planner/Microplan call or action path.

## BLOCKER_BEFORE_ATTENTION_GATE

No urgency, communication authority, suppression/repetition or cognitive-load policy.

## BLOCKER_BEFORE_LIVE

Upstream policies remain caller-supplied. No production orchestration, Shadow Mode,
real-match testing or real-match action path.

## ACCEPTED_V01_LIMITATION

Fixed admission policy; complete pairwise requirement for more than one admitted;
direct universal advantage only; at most one selection; no ranking; no action.
Carry, Mid, Offlane, Support 4 and Support 5 share the same opaque option contract.
No farm/gold/kills/damage/lane/vision/tower/Roshan/hero/item/spell logic is inferred.
