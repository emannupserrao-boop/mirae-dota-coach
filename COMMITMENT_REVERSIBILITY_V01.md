# Commitment / Reversibility Evidence v0.1

Commitment and reversibility are independent evidence axes.
This component is exact-tick and stateless.
Prior evidence does not carry forward automatically.
Evidence absence differs from explicit INDETERMINATE.

## Scope

One snapshot describes one caller-owned, nonterminal execution instance at the
exact evaluated tick of its accepted Execution Lifecycle state. It preserves the
supplied lifecycle and claims by object identity. Independent instances can be
assessed separately; no global instance registry or uniqueness proof is provided.

The component consumes only the public Execution Lifecycle state, phase and
knowledge contracts. It does not separately consume Hysteresis, Arbiter, Safety,
Feasibility, Pairwise, Outcome, Objective or Risk. Caller classifications are
accepted evidence, not gameplay-derived conclusions or source authentication.

## Domains

`ExecutionCommitmentLevel` contains exactly `NOT_ESTABLISHED`, `LIMITED`,
`SUBSTANTIAL`, `INDETERMINATE`.

NOT_ESTABLISHED does not mean zero commitment.
It is an explicit current assessment that meaningful commitment is not established.
LIMITED and SUBSTANTIAL are external categorical assessments, not scores or
comparisons with other executions. INDETERMINATE means the explicit assessment
cannot establish a category.

SUBSTANTIAL does not imply irreversibility or obligation to continue.

`ExecutionReversibilityLevel` contains exactly `REVERSIBLE`, `CONSTRAINED`,
`NOT_REVERSIBLE`, `INDETERMINATE`.

REVERSIBLE establishes availability of reversal/abandonment under the caller's
assessment. CONSTRAINED establishes availability with material constraints.
REVERSIBLE does not imply cheap reversal.
NOT_REVERSIBLE is scoped to external policy/evidence.
It does not assert universal impossibility, prohibit abort or require continuation.
INDETERMINATE does not establish reversibility.

`ExecutionAssessmentPresence` contains exactly `PRESENT`, `ABSENT`.

## Input claims and independent provenance

Frozen `ExecutionCommitmentClaimV1` fields:

```text
commitment_context_id: str
execution_context_id: str
execution_instance_id: str
option_id: str
lifecycle_state_id: str
assessed_at_tick: int
commitment_level: ExecutionCommitmentLevel
source_id: str
evidence_refs: tuple[str, ...]
assessment_policy_id: str
```

Frozen `ExecutionReversibilityClaimV1` fields:

```text
reversibility_context_id: str
execution_context_id: str
execution_instance_id: str
option_id: str
lifecycle_state_id: str
assessed_at_tick: int
reversibility_level: ExecutionReversibilityLevel
source_id: str
evidence_refs: tuple[str, ...]
assessment_policy_id: str
```

Each claim has its own `claim_id`. Context, source, references and policy may
differ between axes. Policy IDs are provenance only and never configure engine
behavior. Identifiers are opaque exact concrete nonblank strings, without trim,
parsing, hierarchy inference or inferred relationships. Lifecycle IDs must have
the accepted `execution.lifecycle.v1:state:<sha256>` form.

Ticks are exact nonnegative integers; bool and subclasses are rejected. Levels
are exact enum members. References are exact tuples of concrete nonblank strings,
without duplicates; an empty tuple is allowed. Original order and tuple object
are preserved. No source authentication, ref interpretation or network lookup.

## Assessments and absence

Frozen `ExecutionCommitmentAssessmentV1` and
`ExecutionReversibilityAssessmentV1` each contain exactly:

```text
lifecycle_state_id: str
assessed_at_tick: int
presence: ExecutionAssessmentPresence
conclusion: corresponding axis enum
base_claim: corresponding claim | None
```

PRESENT requires the exact claim, matching lifecycle ID/tick, and its unchanged
level as conclusion. ABSENT requires `base_claim=None` and INDETERMINATE conclusion.
That derived conclusion does not fabricate an explicit unknown claim or provenance.
An explicit INDETERMINATE claim remains PRESENT. Presence and claim ID distinguish
its identity from absence. Assessments have no separate assessment ID.

Empty evidence and one-axis-only evidence are valid for eligible instances.

## Snapshot and builder

Frozen `ExecutionCommitmentReversibilitySnapshotV1` contains exactly:

```text
base_lifecycle_state: ExecutionLifecycleStateV1
commitment_assessment: ExecutionCommitmentAssessmentV1
reversibility_assessment: ExecutionReversibilityAssessmentV1
ruleset: str
```

Derived properties: `lifecycle_state_id`, `execution_context_id`,
`execution_instance_id`, `option_id`, `timeline_id`, `selected_clock_id`,
`assessed_at_tick`, `snapshot_id`.

```python
build_execution_commitment_reversibility_snapshot_v1(
    *,
    lifecycle_state: ExecutionLifecycleStateV1,
    commitment_claim: ExecutionCommitmentClaimV1 | None,
    reversibility_claim: ExecutionReversibilityClaimV1 | None,
) -> ExecutionCommitmentReversibilitySnapshotV1
```

All arguments are required keyword-only. The caller explicitly supplies None
for each absent axis. No previous snapshot, persistence or carry-forward exists.
The underlying lifecycle may retain its own previous-state lineage; this layer
does not use it to inherit commitment/reversibility.

## Exact binding and eligibility

Claims must match execution context, execution instance, option and lifecycle
state ID exactly. Their tick must equal `evaluated_at_tick`. Old, future or
foreign claims are rejected without rebinding, tolerance or repair. Timeline,
clock and binding identity are inherited from lifecycle lineage, not duplicated
as claim fields.

NOT_STARTED and IN_PROGRESS are eligible, even with lifecycle knowledge
INDETERMINATE and effective phase None. Explicit current axis evidence can be
established independently of phase knowledge.

Terminal lifecycle instances are not eligible.
COMPLETED, ABORTED and EXPIRED are rejected, including indeterminate current
knowledge and both claims absent. Terminal last-known memory remains authoritative.
Previously produced snapshots can be archived externally but are not current
evidence at a later tick.

Selection mismatch, Hysteresis NO_SELECTION and Hysteresis INDETERMINATE do not
invalidate evidence for a nonterminal instance. No selection equality is required.

## Validation boundary

The builder revalidates exact supplied contracts, rulesets, identifiers, ticks,
phase/knowledge types, binding identity, memory timestamps, effective phase,
terminal consistency and current lineage headers/IDs. The accepted State's public
field annotations identify its nested binding/lineage types without additional
domain imports. Flat public lifecycle identity is checked using its accepted
canonical payload. No Lifecycle builder/private validator is invoked, no previous
state is reconstructed, no Hysteresis decision is recalculated and no transitions
are replayed. Upstream history correctness and source authenticity are not proved.

Claims and assessment/snapshot constructors are defensively revalidated, including
malformed frozen objects. Invalid exact types, enums, tuples, identities, chronology,
foreign bindings and mismatched assessments are rejected.

## Identity

Fixed ruleset: `execution.commitment_reversibility.v1`.

```text
execution.commitment_reversibility.v1:commitment:<sha256>
execution.commitment_reversibility.v1:reversibility:<sha256>
execution.commitment_reversibility.v1:snapshot:<sha256>
```

Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True, UTF-8
and SHA-256. Claim IDs bind all fields and ruleset. Evidence-ref order participates
in identity; references are not sorted or normalized.

Snapshot identity binds lifecycle state ID, execution context/instance/option,
timeline, clock, exact tick, both presences, both conclusions, both claim IDs or
None and ruleset. It does not recursively serialize the lifecycle object.

## Non-inference and authority boundaries

No phase-to-commitment inference.
No phase-to-reversibility inference.
No cross-axis inference.
All 16 category combinations are structurally valid, including SUBSTANTIAL with
REVERSIBLE and NOT_ESTABLISHED with NOT_REVERSIBLE.

No abort/switch cost exists in v0.1.
No switching decision exists in v0.1.
No cost, utility, ranking, option selection, aggregation into switchability,
execution score, priority, continuation or abort recommendation exists.

The component never changes lifecycle phase, knowledge, timestamps or instance.
It never starts, continues, completes, aborts, expires, reopens or switches execution.
It has no action/output authority, Microplan, routes, waypoints, action sequences,
Attention, speech, urgency or repetition policy.

The builder is pure: no wall clock, sleep, timers, scheduler, async, threads,
filesystem persistence, network, random, UUID or mutable global state.

## Genericity and legacy

All five roles are supported without gameplay interpretation. Option IDs remain
opaque; no farm, gold, lane, hero, item, spell, movement or channeling inference.
Legacy execution/farm continuation/abort semantics and the textual
`commitment_paused_pending_information` label are not compatible contracts.
No legacy reuse, adapter or edit is introduced.

## Dependency and preservation

Production domain imports are exactly ExecutionLifecycleStateV1,
ExecutionLifecyclePhase and ExecutionKnowledgeStatus from execution_lifecycle_v01.
Stdlib imports are exactly dataclass, Enum, hashlib and json.
The new tests protect these imports against unauthorized consumers, aliases,
wildcards, module/dynamic imports, builders, private helpers and earlier domains.
They freeze all 142 existing canonical files. Existing guards and hashes remain
unchanged. Only this document, the new module and its new test file are added.

## Future blockers

- BLOCKER_BEFORE_ABORT_SWITCH_COST: define independent scoped cost evidence;
  do not use commitment/reversibility as proxy cost.
- BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING: explicitly design authority and inputs;
  this snapshot cannot decide whether to hold, release or switch.
- BLOCKER_BEFORE_MICROPLAN: define planning/execution boundaries separately.
- BLOCKER_BEFORE_ATTENTION_GATE: define presentation/output authority separately.
- BLOCKER_BEFORE_LIVE: require separately authorized integration and validation;
  synthetic tests do not validate live Dota behavior.

## Validation plan

104 focused tests cover exact contracts, provenance, absence/indeterminacy,
eligibility, epistemic and selection independence, terminal rejection, exact
binding/ticks, all category combinations, identity, purity, dependency guards
and byte preservation. Canonical baseline is 2692 tests; expected full count with
104 additions is 2796. Baseline/full gates use a 180-second external timeout.
Every gate runs once after final implementation bytes are frozen; any required
post-gate project-byte edit blocks acceptance without retry.
