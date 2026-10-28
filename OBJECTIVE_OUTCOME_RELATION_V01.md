# Objective–Outcome Relation Evidence v0.1

Objective–Outcome Relation Evidence v0.1 is a semantic bridge, not an optimizer.

SUPPORTS does not mean GOOD, PREFERRED or RECOMMENDED.

OPPOSES does not mean BAD or REJECT.

Missing relation evidence is distinct from explicit UNKNOWN.

OutcomeChange does not mechanically determine objective relation.

Relation evidence is per exact outcome dimension; there is no option-level alignment verdict.

No counting, weighting, scoring, ranking, selection or opportunity cost occurs here.

Safety and Feasibility remain independent axes.

## Boundary and ownership

Production imports only `DecisionContextV2` and `OptionDecisionContextV2`
from `coach02.decision_context_v02`, plus standard-library dataclasses, enum,
hashlib and json. It imports no upstream builders or lower domain modules.
The accepted Decision Context owns embedded Objective/Outcome object types and
upstream semantic validation. This consumer rechecks the context root, options,
metadata, exact selectors and embedded duplicate outcome keys. It does not
rebuild or reinterpret accepted Objective/Outcome evidence and needs no direct
Option Outcome import. Frozen caller-owned relation claims are fully revalidated.
Accepted context objects are required; arbitrary forged embedded graphs are
outside this contract. Frozen dataclasses do not authenticate evidence or provide
a hostile-memory security boundary.

The caller declares SUPPORTS, OPPOSES, NEUTRAL or UNKNOWN under an opaque policy
identity. The module validates binding, not factual truth. NEUTRAL does not mean
an irrelevant option. An OutcomeChange.UNKNOWN row may have any explicit relation,
including SUPPORTS; the caller owns that assertion. There is no mechanical mapping
from INCREASE, DECREASE, UNCHANGED or UNKNOWN. An exposure DECREASE can SUPPORT;
a gold INCREASE can OPPOSE. Names remain opaque for all five roles.

## Contracts

`ObjectiveOutcomeRelationClaim` is frozen and has fourteen required fields:
decision_context_id, option_id, objective_context_id, objective_horizon_id,
objective_id, outcome_context_id, outcome_baseline_id, outcome_horizon_id,
dimension_id, relation, basis_tick, source_id, evidence_refs, assessment_policy_id.
All eleven string IDs are exact concrete nonblank strings; no trimming or coercion.
Objective ID is never None in a claim. Tick is exact nonnegative int, excluding bool
and subclasses. References are an exact tuple of unique concrete nonblank strings;
empty is valid and original order is preserved. References are labels, never loaded.

The nine-field semantic key is the decision context, option, objective selector/ID,
outcome context/baseline/horizon and dimension. Duplicates reject even when relation,
source or assessment policy differs. No competing declarations for that same key.

Each claim must match the root decision_context_id, objective_context_id,
objective_horizon_id and concrete objective_assessment.objective_id. Each option
comes only from `decision_context.options`. The exact embedded outcome match is
(option_id, outcome_context_id, baseline_id, horizon_id, dimension_id).
Foreign, orphan, duplicate and unbound claims reject rather than being ignored.
Embedded duplicate exact outcome keys also reject, including when unclaimed.

`basis_tick == decision_context.decision_assembly_tick` is mandatory. No <=,
max/latest tick, freshness, re-aging or clock conversion. Older accepted base
evidence ticks remain unchanged metadata. The snapshot inherits timeline_id,
selected_clock_id and evaluated_at_tick directly from Decision Context.

`build_objective_outcome_relation_snapshot_v1(*, decision_context, claims)` has
required keyword-only arguments and requires an exact claim tuple. It is pure,
deterministic and does not mutate inputs. All validation precedes output creation.

`ObjectiveOutcomeRelationEvidence` retains all thirteen non-context claim fields
and the identical base_claim, base_objective_assessment and base_outcome_evidence.
The decision_context_id is retained inside base_claim. No reconstructed provenance.

`ObjectiveOutcomeRelationSnapshotV1` retains decision_context_id,
decision_context_object_id (the exact accepted context_id), timeline_id,
selected_clock_id, evaluated_at_tick, objective_context_id, objective_horizon_id,
objective_id, ruleset and relations. Both output contracts are frozen.

## Absence and independent dimensions

Absent objective assessment or explicit objective_id=None requires claims=().
Both produce a valid empty relation snapshot with objective_id=None, preserving
Decision Context lineage. They never synthesize UNKNOWN. A known objective with
zero claims is valid; options without outcome evidence or without relation claims
are valid. Empty candidates require empty claims. Unclaimed outcome rows remain
accepted; there is no completeness requirement for relations.

An option may have SUPPORTS, OPPOSES and UNKNOWN across different dimensions.
All supplied rows remain separate. Three SUPPORTS and one OPPOSES do not create
a majority, net relation or option verdict. No weight, priority, strength, magnitude,
confidence, probability, utility or expected value is computed. The opaque policy
ID does not execute a weighting policy. No candidate is selected, ranked or filtered.

RISK_BLOCKING and Safety ABSENT do not suppress SUPPORTS. Feasibility is neither
imported nor consumed; INFEASIBLE elsewhere does not change relation evidence.
No pairwise comparison, dominance, Pareto verdict, regret, opportunity cost,
recommendation, action, execution lifecycle or output authority is present.

## Deterministic identity

Fixed ruleset: `objective.outcome_relation.v1`.

- Evidence: `objective.outcome_relation.v1:evidence:<sha256>`.
- Snapshot: `objective.outcome_relation.v1:snapshot:<sha256>`.

Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True and UTF-8.
Evidence identity hashes the complete dataclass content, including all base objects
and every claim field. Snapshot identity hashes every root field and relation row,
including the accepted Decision Context lineage ID. Reference order is content.
Claims sort lexically by option_id, objective_context_id, objective_horizon_id,
objective_id, outcome_context_id, outcome_baseline_id, outcome_horizon_id,
dimension_id, source_id and assessment_policy_id. Relation values do not determine
ordering. Input claim permutations preserve snapshot identity.

## Legacy/current review and guard maintenance

Read-only review covered coach02/decision.py, farm_context.py,
strategic_evidence.py, decision_context_v02.py, feasibility_gate_v01.py,
option_outcome_evidence.py and strategic_objective_context.py.
Legacy Decision.objective belongs to action-bearing context containing selected_plan,
execution and output_authority. Farm context and strategic evidence compose legacy
farm-specific assessments and actions. No adapter or legacy logic is reused.
Current Strategic Objective is shared intent without per-option relations. Outcome
is directional, not utility. Decision Context explicitly does not evaluate objective
alignment. Feasibility is executability only. This separate semantic bridge supplies
explicit relation rows without turning any of these layers into an optimizer.

Only tests/test_feasibility_gate_v01.py needs an existing-file edit: its exact
Decision Context consumer allowlist adds coach02/objective_outcome_relation_v01.py,
with exactly DecisionContextV2 and OptionDecisionContextV2. The same constructor,
alias, wildcard, dynamic import and unrelated-consumer rejection remains active.
The old SHA-256 and repository hash dependents were recorded externally before
editing. No stored hash dependent exists; no literal-only maintenance is necessary.
New tests exercise both positive and negative guard cases. Existing production,
documentation and all other tests remain unchanged.

## BLOCKER_BEFORE_TRADEOFF_EVIDENCE

No cross-option comparison, importance/priority policy across dimensions,
aggregation of mixed relation rows or opportunity cost.

## BLOCKER_BEFORE_DECISION_ARBITER

No pairwise preference, trade-off resolution, best alternative, selection,
switching or hysteresis.

## BLOCKER_BEFORE_EXECUTION

No selected option, lifecycle, commitment or reversibility.

## BLOCKER_BEFORE_ATTENTION_GATE

No output authority, urgency, suppression or repetition policy.

## BLOCKER_BEFORE_LIVE

Relation claims remain caller-supplied and unverified. No live semantic policy
source or orchestration exists.

## ACCEPTED_V01_LIMITATION

One concrete objective identity only; exact-tick claims; explicit relation rows
only; opaque policy identity; no aggregation, comparison, selection or action.
Empty relations mean no accepted relation rows were supplied, not objective
irrelevance, absence of good options or absence of strategic relations in reality.
