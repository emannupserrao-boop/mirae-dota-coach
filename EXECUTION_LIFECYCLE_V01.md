# Execution Lifecycle v0.1

Selection does not create execution.
Execution registration is explicit.
execution_instance_id distinguishes repeated executions of the same option.
Registration creates NOT_STARTED; it does not start execution.
Execution phase and execution knowledge are separate axes.
Missing observation does not establish known continuation.
COMPLETED, ABORTED and EXPIRED are terminal.
Selection changes do not automatically abort, expire or replace execution.
IN_PROGRESS does not mean COMMITTED.
Reversibility is not a lifecycle phase.
Execution Lifecycle records execution state; it does not execute actions.

## Ownership and upstream boundary

This is a generic, pure, offline state transition for one caller-registered
execution instance. It consumes only the accepted public SelectionHysteresisStateV1
and SelectionHysteresisStatus contracts, plus its own explicit binding, current
observation and previous lifecycle state. No Decision Context, Arbiter, Safety,
Feasibility, Risk, Objective or Outcome is directly imported or recalculated.

The caller owns instance allocation, ID uniqueness, persistence and chain selection.
A stateless builder cannot detect historical reuse of an ID after the caller discards
the previous state. previous_state=None means explicit new registration, never a
continuation. Replaying the original registration inputs is deterministic, not a
globally authenticated allocation. The caller must not reuse an existing instance ID.
No registry, wall clock, timers, IO, network, randomness or mutable global state exists.

All dataclass roots and enums require exact concrete types; consumed own contracts
are revalidated. The upstream public fields consumed for selection, time and identity
are checked again. These checks do not authenticate a caller's observations, source
or upstream conclusions. Identifiers are opaque concrete nonblank strings, preserved
without trimming. Integer ticks are concrete, nonnegative, and exclude bool/subclasses.
Evidence references are exact tuples of unique concrete nonblank strings; empty is
allowed. Their original order is retained and participates in identity.

## Public contracts

All three dataclasses are frozen. The fixed ruleset is execution.lifecycle.v1.

ExecutionLifecyclePhase has exactly NOT_STARTED, IN_PROGRESS, COMPLETED, ABORTED,
EXPIRED. ExecutionKnowledgeStatus has exactly KNOWN, INDETERMINATE.

ExecutionLifecycleBindingV1 fields, in order:

```text
execution_context_id: str
execution_instance_id: str
option_id: str
hysteresis_state_id: str
basis_tick: int
source_id: str
evidence_refs: tuple[str, ...]
binding_policy_id: str
```

The Hysteresis reference is an accepted selection.hysteresis.v1:state:<sha256>
identity. Registration requires SELECTED with the same option, state ID and tick.
NO_SELECTION and INDETERMINATE cannot register a new instance. observation must be
None and previous_state must be None. Registration produces KNOWN NOT_STARTED;
both phase timestamps equal the registration tick. No start is inferred.

ExecutionLifecycleObservationV1 fields, in order:

```text
execution_context_id: str
execution_instance_id: str
option_id: str
timeline_id: str
selected_clock_id: str
basis_tick: int
knowledge_status: ExecutionKnowledgeStatus
phase: ExecutionLifecyclePhase | None
source_id: str
evidence_refs: tuple[str, ...]
assessment_policy_id: str
```

KNOWN requires an exact phase. INDETERMINATE requires phase=None. The observation
is a current-state assertion, not a command or a public transition-event contract.
It must match the instance/context/option, timeline, clock and current evaluation tick.
Binding and assessment policy IDs are provenance only and do not configure transitions.

ExecutionLifecycleStateV1 fields, in order:

```text
base_binding: ExecutionLifecycleBindingV1
timeline_id: str
selected_clock_id: str
evaluated_at_tick: int
last_known_phase: ExecutionLifecyclePhase
last_known_phase_recorded_at_tick: int
last_known_phase_observed_at_tick: int
knowledge_status: ExecutionKnowledgeStatus
current_hysteresis_state: SelectionHysteresisStateV1
current_observation: ExecutionLifecycleObservationV1 | None
previous_state_id: str | None
ruleset: str
```

Derived properties: execution_context_id, execution_instance_id, option_id,
binding_id, registered_hysteresis_state_id, current_hysteresis_state_id,
current_observation_id, current_selection_option_id, selection_matches_execution,
effective_phase, instance_is_terminal, state_id. No redundant mismatch boolean is stored.

The builder has four required keyword-only arguments:

```python
build_execution_lifecycle_state_v1(
    *, current_hysteresis_state, binding, observation, previous_state,
)
```

## Stateful observation transitions

Continuation requires the exact previous lifecycle type, unchanged binding content,
same timeline/clock, and strictly increasing ticks. Binding content includes its
original provenance and reference order. The output retains the exact original
previous base_binding object even when the caller supplies an equivalent binding.
Current Hysteresis and observation objects are preserved exactly as supplied.
The binding permanently references registration Hysteresis, not current Hysteresis.
Hysteresis evaluations may be skipped; no adjacent upstream-state requirement exists.

| Last known phase | Allowed known observed phase |
|---|---|
| NOT_STARTED | NOT_STARTED, IN_PROGRESS, COMPLETED, ABORTED, EXPIRED |
| IN_PROGRESS | IN_PROGRESS, COMPLETED, ABORTED, EXPIRED |
| COMPLETED | COMPLETED only |
| ABORTED | ABORTED only |
| EXPIRED | EXPIRED only |

NOT_STARTED -> COMPLETED is allowed because execution may start and finish between
observations. No intermediate IN_PROGRESS state or start timestamp is synthesized.
ABORTED includes cancellation before starting. EXPIRED is explicit caller evidence
that the instance is no longer valid/relevant for execution, without asserting normal
completion or intentional abort. Time, selection changes and option disappearance
do not infer expiry. COMPLETED says nothing about strategic success or objective value.

A new known phase sets both phase timestamps to the current tick. A repeated known
phase preserves its first recorded tick and advances its observed tick. Timestamps
describe accepted evidence, not guaranteed real-world physical transition times.

Absent or explicitly indeterminate observation preserves the last known phase and
both timestamps, exposes INDETERMINATE knowledge and effective_phase=None. Absence
has no observation object/ID; explicit uncertainty retains its own object/ID. Known
evidence after a gap is checked against the remembered phase. Gaps never reopen
COMPLETED, ABORTED or EXPIRED. instance_is_terminal depends on remembered phase,
even when current knowledge is indeterminate. A new execution of the same option
requires a new caller-owned instance ID and a new registration chain.

## Selection audit

Every evaluation consumes current Hysteresis as audit and time anchor. For SELECTED,
current_selection_option_id is the effective selected ID and selection_matches_execution
compares it with the tracked option. NO_SELECTION exposes None and False. Hysteresis
INDETERMINATE exposes None and None. Selection knowledge and execution knowledge
are independent: either unselected status can coexist with KNOWN IN_PROGRESS evidence.
Mismatch never aborts, completes, expires or switches the tracked instance.

## Identity and preservation

IDs use execution.lifecycle.v1:binding:<sha256>, :observation:<sha256> and :state:<sha256>.
Canonical JSON uses sort_keys=True, compact separators, ensure_ascii=True and UTF-8.
Binding and observation IDs bind all their fields plus ruleset. Reference order is
content, with no normalization. State identity binds binding ID, derived instance/context/
option IDs, timeline, clock, tick, memory, both phase timestamps, knowledge, current
Hysteresis ID, current observation ID or None, previous state ID and ruleset.
It does not recursively serialize previous state or the upstream tree.

The new reverse dependency guard allows only this production consumer to import
the two named Hysteresis contracts. It rejects aliases, modules, wildcard/dynamic
imports, upstream constructors/builders and other domains. All 139 pre-feature
canonical files are covered by SHA-256 preservation in the new focused tests.
No existing implementation, test, guard or hash changes are required.

## Legacy separation

coach02/decision.py has two legacy phases and plan_id, without instance identity,
terminal evidence or temporal chain. farm_cycle.py combines farm planning, route
continuation/abort actions and output authority. farm_context.py and strategic_evidence.py
merely carry caller-supplied legacy Execution through farm assemblies. None is reused;
no adapter or legacy edit exists. Option IDs do not encode role or game mechanics.

## Deferred boundaries

BLOCKER_BEFORE_COMMITMENT_REVERSIBILITY

- No commitment evidence, reversibility, abort cost or sunk cost.

BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING

- Selection/execution mismatch is only audited.
- No switch/abort decision based on execution progress.

BLOCKER_BEFORE_MICROPLAN

- No action sequence, route or mechanics execution.

BLOCKER_BEFORE_ATTENTION_GATE

- No communication authority, urgency or speech/repetition policy.

BLOCKER_BEFORE_LIVE

- Observations are caller-supplied.
- No executor integration, real game execution verification or live orchestration.

ACCEPTED_V01_LIMITATION

- Explicit registration and caller-owned instance IDs.
- Caller-supplied observations; no source authentication.
- Exact timeline/clock; strict ticks; no migration or re-aging.
- Terminal lifecycle only; no commitment/reversibility/action authority.
- No global registry or automatic detection of caller-discarded instance history.
- No lifecycle object means no registered instance in supplied scope, not proof
  that nothing is happening in the real game.
