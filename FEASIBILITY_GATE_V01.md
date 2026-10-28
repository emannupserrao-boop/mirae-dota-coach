# Feasibility Gate v0.1

Feasibility Gate v0.1 evaluates modeled executability requirements; it does not choose actions.
FEASIBLE does not mean SAFE, GOOD, RECOMMENDED or SELECTED.
INFEASIBLE does not mean UNSAFE or strategically bad.
INDETERMINATE is epistemic/policy incompleteness, not danger.
Missing required claim is distinct from explicit UNKNOWN.
Safety, Outcome and Strategic Objective do not determine feasibility.
Legacy Option Availability v0.1 is farm/resource-specific and is not reused.
Feasibility Gate does not pathfind or compute Dota mechanics.

SAFETY != FEASIBILITY != DESIRABILITY != SELECTION.

## Scope and dependencies

The question is whether the explicit modeled requirements necessary to execute
each option are satisfied under its supplied policy at this exact decision instant.
The only production domain imports are the exact public DecisionContextV2 and
OptionDecisionContextV2 contracts from coach02.decision_context_v02. No builders,
aliases, module imports, wildcard/dynamic imports, lower domains or legacy modules.
Standard library dependencies are dataclasses, enum, hashlib and json.

Decision Context is the accepted candidate-envelope boundary. Feasibility never
branches on embedded Objective, Safety or Outcome presence/semantics. It retains
base option objects for provenance, not for another semantic evaluation.

## Domains and gate table

FeasibilityRequirementState contains exactly SATISFIED, UNSATISFIED and UNKNOWN.
They describe caller-supplied modeled requirement evidence at the exact instant.
UNKNOWN is an explicit assessment; missing claim is absence.

FeasibilityGateStatus contains exactly FEASIBLE, INFEASIBLE and INDETERMINATE.
FeasibilityGateReason contains exactly the five codes in this table:

| Explicit evidence | Status | Reason |
| --- | --- | --- |
| No policy (and no claims) | INDETERMINATE | FEASIBILITY_POLICY_ABSENT |
| Any required UNSATISFIED claim | INFEASIBLE | REQUIRED_REQUIREMENT_UNSATISFIED |
| No UNSATISFIED, any required UNKNOWN | INDETERMINATE | REQUIRED_REQUIREMENT_UNKNOWN |
| No UNSATISFIED/UNKNOWN, any required claim absent | INDETERMINATE | REQUIRED_REQUIREMENT_ABSENT |
| Every required claim present and SATISFIED | FEASIBLE | ALL_REQUIRED_REQUIREMENTS_SATISFIED |

Precedence is UNSATISFIED > UNKNOWN > ABSENT > POLICY_ABSENT > ALL_SATISFIED.
Policy absence cannot coexist with supplied claims: orphan claims reject.
This is deterministic evidence precedence, not severity, weight or desirability.
An explicit unsatisfied requirement remains decisive even if another is unknown
or absent. Missing IDs remain recorded even when a different reason dominates.

## Caller contracts and validation

Frozen FeasibilityRequirementClaim requires decision_context_id, option_id,
feasibility_context_id, requirement_id, state, basis_tick, source_id,
evidence_refs and assessment_policy_id.

All identifiers are exact concrete nonblank str, opaque and never trimmed.
Unicode and whitespace surrounding nonblank text are retained exactly. state must
be the exact FeasibilityRequirementState enum, not a string or foreign enum.
basis_tick must be exact nonnegative int; bool and subclasses are rejected.
evidence_refs is an exact tuple of exact concrete nonblank strings; duplicates
reject, empty tuple is valid and original order is preserved. References are
labels, never loaded or authenticated.

Unique claim key: (decision_context_id, option_id, feasibility_context_id,
requirement_id). Duplicate keys reject regardless of state/source/policy.

Frozen OptionFeasibilityPolicyClaim requires decision_context_id, option_id,
feasibility_context_id, required_requirement_ids and feasibility_policy_id.
IDs obey the same string rules. required_requirement_ids is an exact nonempty
tuple of concrete nonblank IDs, without duplicates. No empty policy can establish
FEASIBLE. One policy per decision context/option; a different feasibility context
does not permit a second policy. The exact original policy tuple is retained.
Policy is declarative configuration, with no observation tick or freshness.

## Binding and candidate universe

Candidates come ONLY from DecisionContextV2.options. Each produces one assessment,
including INFEASIBLE and INDETERMINATE. No eligible-options list, discovery or
filtering. Every supplied claim/policy must match decision_context_id and an
existing option_id. A policy defines that option's exact feasibility_context_id
and complete required requirement universe; there are no inferred/default needs.

Reject every foreign decision context, foreign option, duplicate policy, duplicate
claim, claim without policy, wrong feasibility context and unrequired claim.
Nothing is silently ignored. Policy absence and missing required claims are valid
incomplete inputs, with the table's reasons and no fabricated policy/claim objects.

Empty Decision Context options requires empty policies and requirement_claims and
returns assessments == (). It says only that no candidates were present to evaluate.

## Exact time

Every claim basis_tick MUST equal decision_context.decision_assembly_tick, not <=.
Both old and future claims reject. Root timeline_id, selected_clock_id and tick
are inherited exactly. No other clock, max/latest tick, freshness classification,
clock conversion, temporal advancement or re-aging exists.

## Outputs, API and identity

Frozen OptionFeasibilityAssessmentV1 contains option_id, feasibility_context_id,
status, reason, policy, requirement_claims, missing_requirement_ids and
base_option_context. Exact input policy/claim/base option objects are retained.
Policy absence gives None feasibility context/policy and empty claims/missing IDs.
Missing required IDs are lexical; explicit UNKNOWN claims remain claims.

Frozen FeasibilitySnapshotV1 contains decision_context_id,
decision_context_object_id (the accepted Decision Context context_id), timeline_id,
selected_clock_id, evaluated_at_tick, ruleset and assessments. Root lineage does
not copy Objective/Safety/Outcome verdicts into new fields.

```python
build_feasibility_snapshot_v1(
    *, decision_context: DecisionContextV2,
    policies: tuple[OptionFeasibilityPolicyClaim, ...],
    requirement_claims: tuple[FeasibilityRequirementClaim, ...],
) -> FeasibilitySnapshotV1
```

All keyword-only arguments are required; exact tuples, no list coercion/defaults.
Caller policies/claims are fully revalidated before output, including frozen
objects deliberately mutated through Python bypasses. Decision Context validation
covers exact root/option types, root metadata/ruleset/tick, exact options tuple,
concrete option IDs and uniqueness. Its accepted embedded domain semantics remain
upstream responsibility; no lower-domain re-evaluation or authentication occurs.
Frozen dataclasses are not a hostile-memory security boundary. Manual output
construction alone does not certify a valid builder result.

Pure deterministic builder: no IO, network, environment, wall clock, random, UUID
or mutable global state. No input mutation. All validation finishes before output.

Ruleset: option.feasibility_gate.v1.
snapshot_id: option.feasibility_gate.v1:snapshot:<sha256>.
Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True and UTF-8.
Complete root headers/lineage, assessments, policies, explicit claims, missing IDs
and exact retained base options contribute to identity. The property is not hashed.
Assessments sort by option_id; claims by requirement_id, source_id,
assessment_policy_id; missing IDs by exact lexical order. Only the hash copy of
each policy's required_requirement_ids is sorted, preserving the original object
and tuple while making policy requirement order irrelevant to snapshot identity.
Policy input order and claim input order also do not affect identity. Reference
order remains content. No ordering by semantic status or preference.

## Independence and adversarial examples

FEASIBLE + RISK_BLOCKING and FEASIBLE + Safety ABSENT are valid. INFEASIBLE +
RISK_NOT_BLOCKING is valid. INDETERMINATE can coexist with any Safety state.
Positive-looking outcomes, INCREASE/DECREASE and objective KNOWN/UNKNOWN/ABSENT
cannot establish, prevent or change feasibility. Only explicit requirements count.

mana.available, cooldown.ready, target.in_range, path.exists, resource.present and
channel.not_blocked are examples of opaque caller IDs only. No mechanics, geometry,
inventory, spell, pathfinding, resource or hero logic is implemented. The same
contract applies across Carry, Mid, Offlane, Support 4 and Support 5 without defaults.

There is no score, ranking, selection, opportunity cost, trade-off resolution,
action authority or lifecycle. FEASIBLE does not assert execution started,
committed, succeeded or completed. No urgency, priority, speech or output policy.

## Legacy and guard review

coach02/option_availability.py and OPTION_AVAILABILITY_V01.md define old farm
resource presence/access evidence bound to DecisionContextSeed.seed_id and legacy
Action/PRODUCTIVE_ACTIONS, using Truth/Freshness. They explicitly do not establish
route/path, safety, arrival timing or validated pathfinding. There is no generic
explicit requirement universe and no DecisionContextV2 binding. Generic Feasibility
is broader and policy/requirement-based. No adapter/reuse is created.

coach02/decision.py, coach02/farm_context.py and coach02/strategic_evidence.py retain
legacy safe/available, selected-action and farm evidence composition semantics.
All legacy modules remain frozen/reference-only, with no modification or deletion.

tests/test_decision_context_v02.py guards only that module's consumption of its
three upstream domains, not downstream consumption of Decision Context itself.
No existing guard/hash maintenance is needed. New tests restrict the exact new
consumer coach02/feasibility_gate_v01.py to the two public Decision Context contracts
and reject builders, aliases, module/wildcard/dynamic imports and arbitrary consumers.

## Documented blockers only

BLOCKER_BEFORE_DECISION_ARBITER: Feasibility is now available; objective/outcome
preference mapping, opportunity cost, trade-off policy, selection and
switching/hysteresis remain absent.

BLOCKER_BEFORE_EXECUTION: a feasible option is not yet selected; no lifecycle,
commitment/reversibility transition, abort or completion state.

BLOCKER_BEFORE_ATTENTION_GATE: no communication authority, urgency or
suppression/repetition policy.

BLOCKER_BEFORE_LIVE: requirement sources remain caller-supplied/synthetic; no real
pathfinding/cooldown/mana/range/resource derivation or live orchestration.

ACCEPTED_V01_LIMITATION: exact-tick only, explicit per-option policies and required
requirement universe, caller-supplied states, no mechanic inference, candidate
filtering, selection or action. No promotion or later architecture is included.
