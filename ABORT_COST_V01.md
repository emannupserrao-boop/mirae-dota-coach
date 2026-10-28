# Abort Cost Evidence v0.1

Abort Cost models prospective additional consequence of ending the current execution now.

Abort Cost is independent from commitment.
Abort Cost is independent from reversibility.
Abort Cost is distinct from sunk cost.
Abort Cost is distinct from strategic opportunity cost.
Abort Cost is not Switch Cost.
Switch Cost is target-specific and deferred.
NOT_ESTABLISHED does not mean zero cost.
SUBSTANTIAL does not mean continue.
This component is exact-tick and stateless.
Old cost evidence does not carry forward.
Terminal executions are not eligible.
No decision/action authority exists.

## Scope and input authority

The sole upstream production contract is accepted `ExecutionLifecycleStateV1` from
Execution Lifecycle v0.1. Abort Cost is a sibling of Commitment/Reversibility; neither
component supplies or determines the other's conclusions. The engine preserves one
explicit, caller-classified prospective exit consequence for one execution instance.
It does not interpret gameplay, sources, evidence references or policy identifiers.

Already-spent irrecoverable investment is not prospective additional exit consequence.
Cost of transitioning to a particular destination is outside this component. Forgone
future benefit, alternative advantage and strategic opportunity cost are not automatically
included in abort cost. No Outcome or Pairwise conversion exists. No cost dimensions,
numeric magnitude, weights, scores, thresholds, utility or expected value are modeled.

## Public contracts

`ExecutionAbortCostLevel` has exactly four string members:

| Member | Explicit current assessment |
| --- | --- |
| NOT_ESTABLISHED | Meaningful prospective additional exit cost is not established; this does not assert zero cost. |
| LIMITED | Caller classifies prospective exit consequence as limited. |
| SUBSTANTIAL | Caller establishes material prospective exit consequence. |
| INDETERMINATE | Caller cannot establish the abort-cost category. |

`ExecutionAbortCostPresence` has exactly `PRESENT` and `ABSENT`. It is local to this
module and is not imported from Commitment/Reversibility.

Frozen `ExecutionAbortCostClaimV1` has exactly these ten fields:

```python
cost_context_id: str
execution_context_id: str
execution_instance_id: str
option_id: str
lifecycle_state_id: str
assessed_at_tick: int
abort_cost_level: ExecutionAbortCostLevel
source_id: str
evidence_refs: tuple[str, ...]
assessment_policy_id: str
```

IDs require concrete nonblank strings, remain opaque and are never trimmed. Lifecycle
state IDs use the accepted canonical `execution.lifecycle.v1:state:<sha256>` format.
Ticks are concrete nonnegative integers; booleans and integer subclasses are rejected.
Enums require exact types. References require a concrete tuple of unique concrete
nonblank strings; empty tuples are valid. Original order and tuple identity are preserved.
Source, references and policy identify provenance, not configuration or authentication.
The cost context does not need to share a name with the execution context.

Frozen `ExecutionAbortCostAssessmentV1` has exactly:

```python
lifecycle_state_id: str
assessed_at_tick: int
presence: ExecutionAbortCostPresence
conclusion: ExecutionAbortCostLevel
base_claim: ExecutionAbortCostClaimV1 | None
```

`PRESENT` requires an exact claim and matching lifecycle ID, tick and conclusion.
`ABSENT` requires `base_claim=None` and `conclusion=INDETERMINATE`. There is no
assessment ID. No claim produces `ABSENT/INDETERMINATE/None`; an explicit unknown
claim produces `PRESENT/INDETERMINATE/exact claim`. These structures, provenance
and snapshot identities differ. Missing evidence never fabricates an explicit claim.

Frozen `ExecutionAbortCostSnapshotV1` has exactly:

```python
base_lifecycle_state: ExecutionLifecycleStateV1
abort_cost_assessment: ExecutionAbortCostAssessmentV1
ruleset: str
```

Its derived properties are `lifecycle_state_id`, `execution_context_id`,
`execution_instance_id`, `option_id`, `timeline_id`, `selected_clock_id`,
`assessed_at_tick` and `snapshot_id`. Ruleset is exactly `execution.abort_cost.v1`.
The exact input lifecycle state and supplied claim objects are retained.

## Builder and binding

```python
build_execution_abort_cost_snapshot_v1(
    *,
    lifecycle_state: ExecutionLifecycleStateV1,
    abort_cost_claim: ExecutionAbortCostClaimV1 | None,
) -> ExecutionAbortCostSnapshotV1
```

Both keyword-only arguments are required; pass `None` explicitly for absence. A claim
must match execution context, instance, option and exact current lifecycle state ID.
Its assessed tick must equal the lifecycle evaluated tick. Old and future claims,
foreign bindings and semantic repair are rejected. Timeline and clock are inherited
from the lifecycle state; no redundant claim binding/timeline/clock fields exist.

At tick 100 an explicit SUBSTANTIAL claim establishes a present assessment. At tick
101, passing no claim gives ABSENT/INDETERMINATE/None. Previous cost is not reused;
there is no previous snapshot, aging, grace period, hysteresis or temporal memory.

## Lifecycle eligibility and validation

Remembered NOT_STARTED and IN_PROGRESS instances are eligible. Every cost category
is possible with either phase, solely through an explicit claim. Registration does
not imply zero cost; progression does not imply LIMITED or SUBSTANTIAL cost.

Remembered COMPLETED, ABORTED and EXPIRED instances reject the entire snapshot,
including empty evidence. This applies even with current knowledge INDETERMINATE
and effective phase None. Remembered terminality is authoritative.

Nonterminal lifecycle knowledge INDETERMINATE and effective phase None may coexist
with explicitly known abort cost. A current selection of another option, NO_SELECTION
or INDETERMINATE does not invalidate evidence about the tracked execution. Multiple
caller-owned instances and policy assessments remain independent; no ranking or global
uniqueness is inferred. Phase constrains eligibility only, never the cost conclusion.

The module defensively validates exact lifecycle type and ruleset, concrete IDs/ticks,
exact phase/knowledge types, concrete nested accepted contract types from public State
annotations, binding and state identities, current lineage/observation coherence,
effective phase, remembered terminality and chronology
`binding.basis_tick <= recorded <= observed <= evaluated_at_tick`.
It does not rebuild states, replay transitions, reconstruct Hysteresis, call Lifecycle
builders or invoke upstream private validators. Frozen claims and assessments are
revalidated at consumption boundaries to reject malformed bypassed constructors.
This structural validation cannot authenticate evidence or prove historical truth.

## Deterministic identity and purity

Claim IDs are `execution.abort_cost.v1:claim:<sha256>` and bind all ten claim fields
plus ruleset. Snapshot IDs are `execution.abort_cost.v1:snapshot:<sha256>` and bind
flat lifecycle ID, execution context/instance/option, timeline/clock, assessed tick,
presence, conclusion, claim ID or None, and ruleset. They do not recursively serialize
the lifecycle object. Evidence-reference order participates in identity.

Both use `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True)`, UTF-8
and SHA-256. There is no wall clock, timer, sleep, scheduler, async, thread, network,
filesystem persistence, random source, UUID or mutable global state in production.

## Dependency and preservation boundaries

Production imports exactly dataclass, Enum, hashlib, json and the public Lifecycle
State, Phase and Knowledge contracts. No Commitment/Reversibility, Hysteresis, Arbiter,
Context, Outcome, Pairwise, Safety, Feasibility, Risk, Objective, farm, runtime, GSI,
vision or voice imports exist. Option IDs remain opaque across all five roles.

The sole existing-file change is the consumer predicate in
`tests/test_commitment_reversibility_v01.py`, extending authorization to
`coach02/abort_cost_v01.py` with the same three public Lifecycle symbols. No other
guard restrictions, assertions, fixtures, schemas, hashes or counts change. New tests
verify 144 original files byte-identical and reverse the exact guard delta to verify
the original 145th file's hash. Existing hash-literal maintenance and cascade are zero.

Legacy `farm_cycle` ABORT_CURRENT_ROUTE issues decision/action authority and is not
abort-cost evidence. No adapter or legacy production edit is made. The component does
not start, continue, complete, abort, expire, reopen or switch an execution; mutate
lifecycle phase, knowledge, instance or timestamps; compare options; recommend actions;
or implement Attention, output, Microplan or live orchestration.

## Deferred boundaries

### BLOCKER_BEFORE_SWITCH_COST

No target-specific transition cost or target validation policy exists. Switch Cost is
a separate future milestone; no automatic sum of abort and transition costs is assumed.

### BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING

Abort Cost does not decide switching or continuation. A future switching layer needs
its own architecture and explicit authority policy.

### BLOCKER_BEFORE_COST_DIMENSIONS

No explicit time, position, resource or exposure dimensions exist. The engine does not
aggregate dimensions; use an explicit INDETERMINATE claim or absence if classification
cannot be established by the caller.

### BLOCKER_BEFORE_LIVE

Evidence is caller-supplied. No source authentication or automatic cost producer exists.

### ACCEPTED_V01_LIMITATION

One categorical prospective abort-cost axis, exact tick, caller policy/provenance,
nonterminal execution only, no cost carry-forward, no switching or action authority.
Implementation baseline and full-suite gates use a 240-second external timeout.
