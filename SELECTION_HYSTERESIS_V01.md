# Selection Hysteresis / Switching v0.1

Selection Hysteresis stabilizes selection; it does not execute decisions.

Remembered selection is historical memory and may differ from effective current selection.

Arbiter INDETERMINATE never exposes the remembered option as currently selected.

NO_SELECTION may retain a previously stabilized option when that option remains ADMITTED.

EXCLUDED or absent remembered options are released immediately and bypass switching thresholds.

Normal switches require both minimum hold and challenger confirmation.

Challenger confirmation measures persistence across supplied state transitions, not proof of continuity during omitted ticks.

Ticks are opaque units in the selected clock domain, not seconds.

No Safety, Feasibility or Pairwise semantics are recomputed.

No action, lifecycle, commitment, Attention or communication authority occurs.

## Contracts and ownership

All new records are frozen dataclasses. SelectionHysteresisPolicyV1 has exactly
hysteresis_context_id, switch_policy_id, minimum_hold_ticks and
challenger_confirmation_ticks. IDs are exact concrete nonblank str, preserved
without trimming or parsing. Thresholds and ticks are exact nonnegative int;
bool, subclasses and coercion are rejected. Policy thresholds are caller-owned
distances in the current result's selected clock domain, with no defaults.

SelectionHysteresisStatus has SELECTED, NO_SELECTION, INDETERMINATE.
SelectionHysteresisReason has INITIAL_SELECTION, UNCHANGED_SELECTION,
HELD_PREVIOUS_NO_SELECTION, SWITCH_PENDING_MINIMUM_HOLD,
SWITCH_PENDING_CONFIRMATION, SWITCH_CONFIRMED, PREVIOUS_OPTION_EXCLUDED,
PREVIOUS_OPTION_ABSENT, CURRENT_ARBITER_INDETERMINATE, NO_CURRENT_SELECTION.
Status describes effective selection; reason describes the transition.

SelectionHysteresisStateV1 has exactly hysteresis_context_id, switch_policy_id,
minimum_hold_ticks, challenger_confirmation_ticks, timeline_id,
selected_clock_id, evaluated_at_tick, remembered_option_id,
remembered_since_tick, effective_selected_option_id, effective_selected_option,
pending_challenger_option_id, pending_challenger_since_tick, status, reason,
current_arbiter_result_id, current_arbiter_result, previous_state_id and ruleset.
It computes state_id. Policy values are preserved for continuity validation.
The exact current DecisionArbiterResultV1 object is retained. Previous state is
ID-only and never embedded recursively. Durable option memory uses ID/tick only.

Optional memory and challenger ID/tick pairs must be complete, nonblank and
nonnegative, with timestamps no later than evaluated_at_tick. Pending must differ
from remembered and represent the current selected challenger against admitted
memory. SELECTED requires effective ID equal to remembered ID and the exact
current admitted option object. Other statuses require both effective fields
None. NO_SELECTION has no memory; INDETERMINATE may retain non-excluded memory.

## API and consumed validation boundary

build_selection_hysteresis_state_v1(*, current_arbiter_result, policy,
previous_state) requires all three keyword-only arguments, with no defaults.
previous_state=None starts a chain. Inputs and consumed rows have exact types,
excluding subclasses. The accepted Arbiter ruleset is decision.arbiter.v1.
Header IDs, concrete nonnegative tick, exact status/admission enums, exact tuple
containers, unique candidate IDs and exact OptionDecisionContextV2 members are
validated. Selected IDs/objects must match an admitted current member; unselected
Arbiter results require both fields None. Unresolved admission cannot accompany
a determinate Arbiter result.

Only accepted admission conclusions are consumed. Safety presence/gates,
Feasibility requirements, Pairwise bundles/conclusions and Arbiter reasons remain
upstream-owned; no lower semantic policy or direct-advantage selection is rerun.
The retained result_id binds accepted upstream content. Frozen construction and
hashing do not authenticate arbitrary forged semantic evidence. Malformed
consumed boundaries raise errors before any policy branch, including first-state
and immediate-release cases; they are never silently repaired or mapped to
INDETERMINATE.

Previous state is revalidated, including its exact retained Arbiter result,
matching result ID/header, optional pairs, effective current-object membership,
status/enums, thresholds and ruleset. previous_state_id, when present, must be
selection.hysteresis.v1:state: followed by 64 lowercase hexadecimal characters.
Its external ancestry is not recursively resolved or authenticated.

## Fixed transition precedence

1. Validate inputs, previous state, policy continuity and strict temporal progress.
2. Excluded or absent remembered option releases immediately. Adopt an Arbiter
   selected replacement at the current tick, otherwise clear memory and follow
   current Arbiter status. The exclusion/absence reason takes precedence even
   when current status is INDETERMINATE.
3. Without remembered selection, SELECTED acquires current selection with
   INITIAL_SELECTION; NO_SELECTION and INDETERMINATE retain no memory.
4. Current INDETERMINATE clears pending and effective selection, retaining only
   still-present, non-excluded historical memory and its original since tick.
5. NO_SELECTION with admitted remembered candidate holds that candidate using
   HELD_PREVIOUS_NO_SELECTION and clears pending. The exact Arbiter result is
   unchanged; Hysteresis does not claim a new direct winner.
6. Same selected ID preserves remembered_since_tick, uses the current object,
   returns UNCHANGED_SELECTION and clears pending.
7. Different selected candidate against admitted memory is a normal challenger.
   New/changed challenger starts at current tick; repeated challenger preserves
   its original since tick. Minimum hold takes reason precedence over confirmation.
8. When both thresholds are satisfied, SWITCH_CONFIRMED adopts the challenger,
   resets remembered_since_tick to current tick and clears pending.

hold_elapsed = current_tick - remembered_since_tick.
challenger_elapsed = current_tick - pending_challenger_since_tick.
Both conditions use >= threshold. Confirmation accumulates while hold is active.
Zero satisfies immediately; both zero allow the first normal challenger to switch.
Current NO_SELECTION, INDETERMINATE or return to the remembered option breaks
challenger persistence. A changed challenger never inherits another's timestamp.

After a transient uncertain tick, NO_SELECTION with admitted memory restores the
old selection immediately. A different SELECTED result starts normal challenger
confirmation against the original remembered_since_tick. Hold time includes the
logical tick distance through the uncertain interval, without asserting effective
selection during it. A caller omitting intermediate ticks supplies no proof of
uninterrupted challenger selection. No adjacent-tick or maximum-gap rule is added.

## Continuity and identity

Current tick must be strictly greater than previous evaluated_at_tick. Timeline,
selected_clock_id and all four policy values must match. New policy requires
previous_state=None; caller should assign a fresh hysteresis_context_id. No auto
reset. Decision context IDs, content IDs, arbiter context, Feasibility and Pairwise
snapshot IDs may change each tick. Caller owns semantic option-ID continuity,
clock scale/cadence, state retention and avoidance of stale-state forks. The
module neither interprets IDs nor authenticates their conceptual equivalence.

Fixed ruleset selection.hysteresis.v1; state_id is
selection.hysteresis.v1:state:<sha256>. Canonical JSON uses sort_keys=True,
separators=(',', ':'), ensure_ascii=True and UTF-8. Identity binds complete policy,
current Arbiter result_id, previous_state_id, timeline, clock, tick, memory/tick,
effective selected ID, pending/tick, status, reason and ruleset. It does not
asdict-serialize the current upstream tree or embed previous objects. A changed
upstream ID may change state identity without changing the stabilized choice.

## Imports, preservation and legacy review

Production imports only DecisionArbiterResultV1, DecisionArbiterStatus,
ArbiterCandidateAdmissionStatus, ArbiterCandidateAssessmentV1 and
OptionDecisionContextV2; stdlib dataclass, Enum, hashlib and json. No upstream
builders or constructors. Exact path-specific guards reject aliases, module,
wildcard, dynamic and extra-domain imports. The new tests own the reverse Arbiter
consumer guard. Existing import_violations in Feasibility tests grants only
OptionDecisionContextV2 to this exact new path. Six dependent hash literals update:
Relation one, Pairwise two, Arbiter three. Decision Context tests are unchanged.
All existing production bytes remain frozen.

Legacy decision.py has action-bearing plans, Execution/ExecutionState and output
authority. farm_cycle.py continues or aborts farm routes using that execution and
legacy risk. farm_context.py composes supplied farm evidence and Execution. None
is a generic selection-memory contract or reusable hysteresis policy. No adapter
or legacy production change occurs. Carry, Mid, Offlane, Support 4 and Support 5
use the same opaque option-ID contract with no gameplay interpretation.

## BLOCKER_BEFORE_EXECUTION_LIFECYCLE

Stabilized selection does not mean execution began. No commitment, reversibility,
abort or completion; no Microplan invocation.

## BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING

No sunk cost, execution progress, abort penalty or irreversibility.

## BLOCKER_BEFORE_ATTENTION_GATE

No urgency, output authority, speech or repeat suppression.

## BLOCKER_BEFORE_LIVE

Caller must persist/pass previous state, owns option identity continuity and
clock/tick cadence. No live orchestrator, network, Shadow Mode or real-match path.

## ACCEPTED_V01_LIMITATION

Two explicit tick thresholds; same policy/context across state chain; memory can
survive transient indeterminacy; exclusion/absence are the only decisive
invalidators; no execution awareness or action. The transition is pure: no IO,
wall clock, waiting, mutable global state, scheduler, randomness or UUID.

Project bytes freeze before all post-implementation gates. Every gate runs once,
without retries or subsequent edits. Baseline/full suites use external timeout
180 seconds. The focused target is 104 tests; +104 to 2484 yields 2588.
