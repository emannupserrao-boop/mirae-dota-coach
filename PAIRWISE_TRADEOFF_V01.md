# Pairwise Trade-off / Opportunity-Cost Evidence v0.1

Pairwise Trade-off v0.1 compares explicit evidence bundles; it does not rank the candidate set.

LEFT_ADVANTAGE does not mean SELECT_LEFT.

RIGHT_ADVANTAGE does not mean SELECT_RIGHT.

TRADE_OFF is not a tie.

EQUIVALENT is local to the explicit comparison and does not mean globally equivalent options.

NOT_ESTABLISHED opportunity cost does not mean zero opportunity cost.

Missing pairwise evidence is distinct from explicit INDETERMINATE.

No pair is automatically generated.

No transitivity or graph closure occurs.

Safety and Feasibility remain independent.

## Exact boundary and ownership

The caller supplies comparison semantics. Production imports only DecisionContextV2
and OptionDecisionContextV2 from decision_context_v02, and
ObjectiveOutcomeRelationSnapshotV1 / ObjectiveOutcomeRelationEvidence from
objective_outcome_relation_v01. OptionDecisionContextV2 is needed to reject forged
option container subclasses at the candidate boundary. No builders, lower domains,
legacy Decision/Farm, Safety, Feasibility, Risk, runtime, service or GSI are imported.

The accepted upstream objects own their embedded semantic validation. This layer
checks exact root/option/evidence types, selectors, metadata, ticks, lineage, row ID
uniqueness and selected bundle membership. It does not rebuild nested upstream
claims or authenticate their truth. Arbitrary forged nested upstream graphs are
outside the accepted boundary. Frozen caller PairwiseTradeoffClaim instances are
fully revalidated before output, including frozen-object mutation bypasses.
Frozen dataclasses are not a hostile-memory or authentication security boundary.

No ObjectiveOutcomeRelation enum is imported, ordered or examined. One SUPPORTS
may be explicitly favored over three SUPPORTS. A SUPPORTS+OPPOSES bundle versus
SUPPORTS may be declared TRADE_OFF. OPPOSES versus SUPPORTS may be declared
EQUIVALENT. The caller owns the named policy; the builder validates structure,
not strategic correctness. No counting, voting, weights, utility, expected value,
probability, magnitude or confidence is introduced.

## Domains and exact categorical mapping

PairwiseTradeoffConclusion has exactly LEFT_ADVANTAGE, RIGHT_ADVANTAGE, TRADE_OFF,
EQUIVALENT and INDETERMINATE. OpportunityCostConclusion has exactly ESTABLISHED,
NOT_ESTABLISHED and INDETERMINATE.

| Explicit conclusion | Cost of choosing LEFT | Cost of choosing RIGHT |
| --- | --- | --- |
| LEFT_ADVANTAGE | NOT_ESTABLISHED | ESTABLISHED |
| RIGHT_ADVANTAGE | ESTABLISHED | NOT_ESTABLISHED |
| TRADE_OFF | ESTABLISHED | ESTABLISHED |
| EQUIVALENT | NOT_ESTABLISHED | NOT_ESTABLISHED |
| INDETERMINATE | INDETERMINATE | INDETERMINATE |

ESTABLISHED means this exact claim attributes a forgone strategic advantage to the
alternative. NOT_ESTABLISHED does not mean no opportunity cost exists in reality.
These are directional categorical conclusions, with no numeric cost or units.
TRADE_OFF says each side preserves an advantage the other would forgo; it does not
mean equal, 50/50, equally important or indifferent. EQUIVALENT is local to this
bundle/policy and does not account for unmodeled evidence. INDETERMINATE is explicit
uncertainty, not a tie, danger, safety, avoidance or unusability.

## Claim, bundles and uniqueness

Frozen PairwiseTradeoffClaim has eleven required fields: decision_context_id,
pairwise_context_id, left_option_id, right_option_id, left_relation_evidence_ids,
right_relation_evidence_ids, conclusion, basis_tick, source_id, evidence_refs,
assessment_policy_id. String IDs are exact concrete nonblank opaque strings with
no trimming/coercion; left and right must differ. Tick is exact nonnegative int,
excluding bool/subclasses. evidence_refs is an exact tuple of unique nonblank
concrete strings, empty allowed, original order retained; references are not loaded.

Each side's bundle is an exact nonempty tuple of unique concrete nonblank evidence
IDs. Every ID must exist in the supplied relation snapshot and belong to that side's
option. A single row is sufficient. The caller explicitly chooses membership;
unreferenced relations remain valid and are not automatically attached.

Uniqueness is (decision_context_id, pairwise_context_id, sorted(left_option_id,
right_option_id)). Reverse A/B and B/A declarations in one context are duplicates,
regardless of conclusion/source/policy. Orientation is retained, not reconciled.
The same pair in distinct pairwise_context_id values is valid; conflicting contexts
are never merged or resolved. Policy IDs are opaque provenance.

## Exact bindings and time

Candidates come only from DecisionContextV2.options. No pair claim introduces options.
The relation snapshot must match decision_context_id, exact context_id, timeline,
clock and decision_assembly_tick, even when claims are empty. Objective context,
horizon and concrete ID must agree with the accepted context. Relation rows must
belong to that candidate/objective universe and aligned tick; duplicate evidence IDs
reject. Each pairwise basis_tick must equal decision_assembly_tick exactly.
No <=, max/latest tick, freshness, re-aging or clock conversion occurs.

If objective_id is None, claims must be empty. Zero/one candidate, zero relation rows
or concrete objective with zero pair claims can yield valid empty snapshots. Empty
does not mean equivalence, absence of real trade-offs or zero opportunity cost.
All malformed/orphan/foreign claims reject rather than being silently dropped.

## Output and identity

Frozen PairwiseTradeoffEvidenceV1 retains context/pairwise context, caller orientation,
conclusion, two derived costs, tick, source, refs, policy, selected left/right relation
objects and the identical base_claim. Bundles retain the exact selected upstream
objects, sorted by evidence_id. Original claim tuples remain untouched.

Frozen PairwiseTradeoffSnapshotV1 retains decision_context_id, exact context_id,
relation_snapshot_id, timeline, clock, tick, objective context/horizon/ID, ruleset and
comparisons. `build_pairwise_tradeoff_snapshot_v1(*, decision_context,
relation_snapshot, claims)` requires all keyword-only arguments and exact tuples.
It is pure and deterministic, without IO, network, environment, wall clock or randomness.

Ruleset: `decision.pairwise_tradeoff.v1`.
IDs: `decision.pairwise_tradeoff.v1:evidence:<sha256>` and
`decision.pairwise_tradeoff.v1:snapshot:<sha256>`.
Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True and UTF-8.
Evidence hashes bind all claim fields, exact selected relation content and derived
costs. Only hash copies of base_claim bundle ID tuples are sorted; reference order
remains content. Snapshots hash every root field and normalized comparison content.
Changing context/relation lineage changes snapshot identity, even for unreferenced
upstream evidence. Claim permutations and bundle tuple permutations do not change IDs.
Caller orientation remains identity-bearing. Comparisons sort by pairwise_context_id,
unordered option pair, source_id and assessment_policy_id; never by semantic value.

## Sparse evidence and independent axes

A/B and B/C do not create A/C. Cycles are allowed without closure, topological sorting
or a tournament winner. No global ranking, Condorcet, Elo, points, best/worst option,
aggregate/total/average opportunity cost or selection occurs. An INFEASIBLE or
RISK_BLOCKING option may have pairwise advantage; future Arbiter policy combines
those axes. No action, recommendation, execution lifecycle or output authority exists.
All option/dimension IDs remain opaque across Carry, Mid, Offlane, Support 4 and 5;
no farm/gold/hero/vision/ability semantics are parsed.

## Legacy/current review and guard maintenance

Read-only review: coach02/decision.py, farm_context.py, strategic_evidence.py,
decision_context_v02.py, feasibility_gate_v01.py, objective_outcome_relation_v01.py.
Legacy Decision already selects plans and carries execution/output authority, so it
is not reused. Decision Context does not compare; Feasibility is executability only;
Objective–Outcome Relation is per-dimension and non-comparative. This is the first
explicit cross-option semantic layer, still without global ranking or selection.
No adapter/reuse of the legacy decision path.

Only exact dependency/hash maintenance is permitted: the Feasibility reverse guard
adds this exact consumer for the four named contracts, leaving existing consumers'
contract sets unchanged. No arbitrary consumers, constructors, aliases, module,
wildcard, dynamic or builder imports are authorized. The old guard hash is replaced
once in test_objective_outcome_relation_v01.py. The finite chain and old/new SHA-256
values are recorded externally; no other existing tests or production change.
The previously accepted recovered 2276-test baseline is reused without rerunning.
Historical 60-second timeout and recovery evidence remain unchanged.

## BLOCKER_BEFORE_DECISION_ARBITER

Sparse pairwise evidence; no global order/completeness requirement; no cross-context
conflict policy; no Safety/Feasibility integration policy; no selection or switching/hysteresis.

## BLOCKER_BEFORE_EXECUTION

No chosen option, lifecycle, commitment, reversibility or abort policy.

## BLOCKER_BEFORE_ATTENTION_GATE

No output authority, urgency, repetition suppression or cognitive-load policy.

## BLOCKER_BEFORE_LIVE

Caller-supplied/unverified claims; no production policy engine or live orchestration.

## ACCEPTED_V01_LIMITATION

Sparse explicit claims, caller-owned comparison semantics, categorical cost only,
no magnitude, transitivity, global ranking, selection or action.
