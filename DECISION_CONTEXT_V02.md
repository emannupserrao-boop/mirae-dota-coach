# Decision Context v0.2

Decision Context v0.2 assembles evidence; it does not decide.
PRESENT/ABSENT are evidence-presence states, not semantic verdicts.
Safety ABSENT is not Safety INDETERMINATE.
Outcome ABSENT is not Outcome UNKNOWN.
Objective ABSENT is not Objective UNKNOWN.
RISK_BLOCKING does not remove a candidate from Decision Context.
Outcome direction does not become utility.
Decision Context does not evaluate objective alignment.
Decision Context does not rank or select options.
Decision Context does not evaluate feasibility.
Decision Context does not calculate opportunity cost.
Decision Context has no action or communication authority.

## Domain boundary

One call answers which accepted shared objective, Safety evaluation and Outcome
evidence are explicitly bound to each requested option at one coherent instant.
This new versioned assembler imports only six exact public contracts:

- StrategicObjectiveSnapshot, StrategicObjectiveAssessment
- OptionSafetySnapshotV2, OptionSafetyEvaluationV2
- OptionOutcomeSnapshot, OptionOutcomeEvidence

It does not import upstream builders or semantic enums, reinterpret their meanings,
instantiate upstream contracts, or consume Risk/lower domains directly. It trusts
accepted upstream semantics. Structural type/key/container validation is defensive;
it is not re-evaluation, truth certification, provenance authentication or security
against hostile Python memory manipulation. Frozen output records are builder outputs;
manual dataclass construction alone does not certify a valid assembly.

## Request and option bindings

Frozen DecisionContextRequestV2 requires decision_context_id, objective_context_id,
objective_horizon_id, context_binding_policy_id and option_bindings.
Exactly one decision context is represented per call. All four IDs are concrete
nonblank str; all five fields are required. No implicit policy or default context.

Frozen DecisionOptionBindingV2 requires option_id, risk_context_id,
safety_context_id, outcome_context_id, outcome_baseline_id and outcome_horizon_id.
All IDs are exact concrete nonblank str, except safety_context_id may be None.
Nonblank whitespace-padded and Unicode strings are preserved, never silently trimmed.
No names, roles, heroes, phases, priorities or action taxonomies are parsed.

option_bindings must be an exact tuple of exact bindings. option_id is unique
within the request; duplicates reject even with different contexts. Another
interpretation of an option requires another explicit decision context. There is
no reconciliation, merging or discovery of candidates from upstream snapshots.

## Exact selection and evidence presence

DecisionEvidencePresence contains exactly PRESENT and ABSENT. ABSENT is not
UNKNOWN, INDETERMINATE, UNSAFE, BAD or INELIGIBLE.

The root objective selector is (objective_context_id, objective_horizon_id), matching
upstream (objective_context_id, horizon_id). One exact assessment gives PRESENT
and the identical object. No match gives ABSENT and None. An explicit UNKNOWN
assessment remains PRESENT. The shared objective is retained at the root only.

For each binding, (risk_context_id, option_id) selects Safety. When a row exists,
its safety_context_id must exactly match the binding, including None; mismatch
rejects the entire assembly, never silently becomes absence. A None binding can
select an accepted policy-absent evaluation. No matching row gives ABSENT and None.
gate_status, reason, tolerance and RiskConclusion are never inspected for selection.

Outcome selects the set matching option_id, outcome_context_id,
baseline_id == outcome_baseline_id and horizon_id == outcome_horizon_id.
Independent dimension_id rows remain separate exact objects. Zero matches gives
ABSENT and (); any matches give PRESENT and a canonical tuple. No synthetic
dimensions or combined verdict. Explicit OutcomeChange.UNKNOWN remains PRESENT.

Exact upstream snapshot/row types and tuple containers are required. Duplicate
structural keys reject defensively across each snapshot: objective context/horizon;
Safety risk context/option; Outcome option/context/dimension/baseline/horizon.
Well-formed extra rows are allowed and not selected, embedded or used to discover
options. Their snapshot IDs still contribute to lineage and context identity.

All four combinations of Safety/Outcome PRESENT/ABSENT are valid. An explicitly
bound candidate with neither is retained. Empty option_bindings is valid and
produces options == (); shared objective may remain PRESENT or ABSENT. Empty
candidates means only that none were explicitly bound, not a feasibility or action
verdict. Safety status never filters a candidate.

## Exact alignment and horizons

DECISION_CONTEXT_V02_EXACT_ALIGNMENT_RULE: all three snapshots must have exactly
the same timeline_id, selected_clock_id and evaluated_at_tick / risk_assembly_tick.
The common tick becomes decision_assembly_tick. Headers are concrete nonblank
strings and ticks concrete nonnegative ints (not bool or subclasses).
No max tick, clock conversion, temporal advancement, freshness refresh,
CURRENT/HISTORICAL classification or stale inference occurs. A one-tick mismatch
rejects. Preserved older upstream basis ticks are not reinterpreted.

Objective and Outcome horizons are opaque independent IDs and may differ.
The explicit request and binding authorize joint inclusion under
context_binding_policy_id; this is not inferred temporal equivalence. No naming
join, horizon parsing or semantic ordering is permitted.

## Outputs, API and identity

Frozen OptionDecisionContextV2 retains all six binding fields, safety_presence,
safety_evaluation, outcome_presence, outcome_evidences and exact base_binding.
Frozen DecisionContextV2 retains decision_context_id, timeline_id,
selected_clock_id, decision_assembly_tick, context_binding_policy_id,
objective_context_id, objective_horizon_id, objective_presence,
objective_assessment, strategic_objective_snapshot_id, option_safety_snapshot_id,
option_outcome_snapshot_id, options, exact base_request and fixed ruleset.
No separate Decision or selected option is produced.

```python
build_decision_context_v2(
    *, strategic_objective_snapshot: StrategicObjectiveSnapshot,
    option_safety_snapshot: OptionSafetySnapshotV2,
    option_outcome_snapshot: OptionOutcomeSnapshot,
    request: DecisionContextRequestV2,
) -> DecisionContextV2
```

No argument defaults, runtime state, player model, legacy context, planner or
policy selection. Request/bindings are revalidated before assembly.
All selected upstream objects, the request and bindings preserve object identity.
The pure deterministic builder has no IO, network, environment, wall clock,
random, UUID or mutable global state.

Ruleset is decision.context.v2. context_id is
decision.context.v2:context:<sha256> of complete output content using JSON
sort_keys=True, compact separators, ensure_ascii=True and UTF-8. It binds all
headers/selectors, policy identity, presence, selected objects, three snapshot
IDs, every binding and complete base request. The property is not itself hashed.
Options sort by option_id. Outcomes sort by dimension_id, outcome_context_id,
baseline_id, horizon_id, source_id, assessment_policy_id, never semantic status.
Only the hash copy of base_request.option_bindings is normalized by option_id,
so input binding order does not affect identity while the exact request is retained.
Extra upstream rows can change lineage IDs and thus context_id without adding rows.

## Noninterpretation and genericity

RISK_NOT_BLOCKING != RECOMMENDED.
RISK_BLOCKING != AUTOMATIC_REJECTION_BY_ARBITER.
OutcomeChange.INCREASE != GOOD; OutcomeChange.DECREASE != BAD.
Strategic Objective KNOWN != ACTION; Strategic Objective UNKNOWN != NO_OBJECTIVE.
Missing upstream row != semantic UNKNOWN.

No score, rank, utility, preference, alignment, opportunity cost, feasibility,
availability, action, execution state, urgency or speech policy exists. Carry,
Mid, Offlane, Support 4 and Support 5 are equally supported as opaque caller
contexts, with no farm/lane/gold/core/support-duty/hero assumptions.

## Legacy comparison and dependency review

coach02/decision.py defines legacy DecisionContext with Option.safe/available,
increased risk and Execution; legacy Decision contains selected_plan, objective,
next_action and output_authority. These action-bearing contracts are not reused.
coach02/context_builder.py builds an eligibility seed from runtime/player/knowledge
inputs, not this explicit cross-domain envelope. coach02/farm_context.py and
coach02/strategic_evidence.py compose farm-specific assessments and remain
frozen/reference-only. DecisionContextV2 is a new versioned clean assembly.
No adapter is created; legacy production is unchanged.

The accepted Objective/Outcome tests check their own module independence and old
file hashes, not a reverse-consumer ban. Safety's guard checks its consumption of
Risk Evaluation, not consumption of Safety. Existing lower-domain guards remain
intact. No existing test/guard/hash changes are required. New tests restrict this
consumer to the six exact contracts; no builders, aliases, wildcard/module/dynamic
imports, lower-domain access or arbitrary consumers are authorized.

## Handoff and blockers (documentation only)

The next milestone remains Feasibility Gate v0.1. Later assembly/Arbiter policies
must explicitly consume accepted contracts; none are implemented here.

BLOCKER_BEFORE_FEASIBILITY_GATE: no generic executability/availability semantics;
legacy Option Availability remains farm/resource-specific. Safety is not feasibility.

BLOCKER_BEFORE_DECISION_ARBITER: no option comparison, outcome/objective utility
mapping, opportunity cost, trade-off policy, selection or switching/hysteresis.

BLOCKER_BEFORE_EXECUTION: no lifecycle, commitment transition or abort state.

BLOCKER_BEFORE_ATTENTION_GATE: no communication urgency, authority, suppression,
repetition or cognitive-load policy.

BLOCKER_BEFORE_LIVE: objective/outcome/Safety policy sources remain synthetic or
caller-supplied; no live orchestration, Shadow Mode or real-match testing.

ACCEPTED_V02_LIMITATION: exact-tick assembly only; explicit candidate universe and
bindings; evidence presence only; no feasibility, utility, comparison or action.
