# Live Runtime Evidence & Shadow Foundation v0.1

Shadow Foundation is NOT Decision Shadow Mode. No coaching is emitted and no
LLM/cloud is involved. This isolated foundation admits real authenticated GSI occurrences as structured
evidence. REAL INPUT != SEMANTIC CLAIM != DECISION != PLAYER OUTPUT. It consumes
unchanged `coach.state.State` / `normalize`, and the accepted Observation Event
and Temporal Evidence contracts. It does not instantiate Service, Store, Policy,
Engine, CoachCall, Voice, vision or a game-control interface. None of the accepted
strategic producers or decision layers is connected.

## Contracts and clock

`LiveRuntimePolicyV1` contains an opaque policy ID, gap threshold in nanoseconds,
freshness policy ID/threshold, fixed `gsi.local_projection.v1` schema and
`gsi.allowlist.v1` sanitization version. Caller-owned thresholds do not configure
strategy. `RuntimeInputV1` is an immutable canonical JSON occurrence or explicit
REJECTED, TIME_ADVANCE, RESET or SHUTDOWN input. Unsafe rejected bodies are absent.

The pure entry points are `new_live_runtime_state_v1`,
`advance_live_runtime_v1` and `sanitize_gsi_payload_v1`. All clocks and identities
are supplied externally. The frozen `LiveRuntimeStateV1` stores bounded continuity
memory and a finite Temporal tracker. It contains no history or mutable payload.

`run_id` identifies this capture invocation. Session IDs are
`<run>/session/<ordinal>`: locally observed episodes, not globally certified Dota
matches. Timeline IDs are `<run>/timeline/<ordinal>` and the selected clock is
`<run>/clock/receipt-ns/v1`. The IO runner obtains elapsed monotonic nanoseconds at
its serialization point. Tick unit is nanoseconds. Logical tick is `max(receipt_elapsed_ns, previous_tick+1)`;
both physical receipt input and logical tick are journaled, including ties. The
tie-break does not represent game progress. Receipt
clock is not game time. Provider timestamps are optional finite metadata, without
epoch assumptions. No clock conversion is performed.

The runner serializes POST admission and controls under one lock. HTTPServer is
single threaded, there is no private input queue, dropping or coalescing. A receive
sequence is local admission order for every accepted/rejected POST, not a Dota
sequence. Controls do not consume it. Identical payloads can share a payload ID;
distinct occurrences always have distinct tick/sequence-bound snapshot/event IDs.

## Continuity rules

Registration of a session requires a local player, nonempty hero and explicitly
in-progress phase. Optional raw-field absence never establishes exit. Explicit
phase/scope exit ends the episode. A change between usable known match IDs, or
known hero identities, ends the current episode; a qualifying current payload
starts the next one. Empty/zero match IDs are not authoritative, and the first
usable ID binds without forcing a new episode. Menu/nonlocal/spectator snapshots
remain admissible evidence with no fabricated local player.

Pause/resume requires explicit raw booleans, advances receipt time and preserves
timeline/session continuity. Same game-time updates are all processed. Backward
finite game time starts an empty new timeline, while preserving the session unless
independent episode-change evidence exists. Explicit reset creates an empty tracker.

Silence is evaluated by TIME_ADVANCE. Gap opens when elapsed time since the last
valid admitted occurrence is strictly greater than the supplied gap threshold.
The opening control first evaluates freshness on the closing timeline, then puts
an empty replacement tracker in `next_state`. Its Temporal snapshot explicitly
belongs to that closing timeline. Further silence does not repeatedly reset it.
Returning input uses the already opened timeline. The runner inserts the same
control immediately before a returning POST if the periodic control has not yet
opened the gap. The pure reducer does not secretly synthesize control occurrences.

TIME_ADVANCE has no normalized snapshot, observation event or receive increment.
It records empty refs and cannot refresh evidence. Rejected inputs have no admitted
snapshot/event/projection and never refresh Temporal marks. Out-of-order physical
time or receive sequence is rejected without changing the previous state. Shutdown
is terminal for this invocation. Reducer exceptions are fail-stop in the runner.

## Projection, capabilities and provenance

`LiveRuntimeSnapshotV1` contains ruleset, run/session/timeline/clock identities,
evaluated tick, receive sequence, sanitized payload ID, source game time, optional
provider timestamp, immutable `normalized_state_json` and a capability tuple.
The JSON projection has exactly the unchanged State dataclass fields. It is newly
normalized per occurrence: no previous field value is filled forward. Continuity
memory never supplies source facts to the current snapshot.

Capability axes are independent: SUPPORTED/UNSUPPORTED, PRESENT/ABSENT and
VALID/INVALID/NOT_ASSESSED. Zero is PRESENT + VALID. Missing fields are ABSENT,
invalid supplied values are PRESENT + INVALID, explicit empty collections are
PRESENT. Normalizer defaults do not establish raw presence. Source paths identify
raw provenance; local classification also documents its scope inputs/default policy.
The finite catalog covers State fields, provider timestamp, collection cooldown and
can_cast presence, and unsupported health/max_health/mana/max_mana/enemy_positions.
Unsupported capabilities are NOT_ASSESSED and produce no observation ref.
Nested cooldown absence never becomes zero. Valid local scalar/collection evidence
requires the unchanged normalizer's local scope, avoiding spectator local claims.

Each admitted snapshot creates one canonical ObservationEvent with receipt stamp,
no source stamp, explicit RECEIPT projection, and only supported/present/valid refs.
The canonical tracker records that occurrence and evaluates explicit freshness
queries. Freshness describes receipt occurrence age, not semantic truth, current
field presence or strategic relevance. A historical mark may remain FRESH even
when the current snapshot's field is ABSENT. No legacy domain-change events,
farm cadence, readiness, target priority or semantic assessment are derived.

## Sanitization and HTTP boundary

The allowlist keeps only normalization inputs, optional finite provider timestamp
and declared unsupported raw health/mana fields. Credentials, provider/player
Steam IDs, personal names, headers, paths and unrelated groups are removed.
Spectator team/player nesting is retained only as empty structural markers; never
select a spectator player. Slot fields follow the unchanged normalize contract.
No nonfinite JSON can enter payload IDs, snapshots or journals, including nonfinite
values in subsequently dropped fields. Capture compares all original normalized
State fields against normalization of the sanitized subset while the original is
transient in memory; parity failure stops capture rather than silently changing scope.

The only existing production edit is the keyword-only opt-in `on_request_result`
hook on `coach.gsi.start_receiver`. Without it, legacy callbacks and HTTP behavior
remain unchanged. Accepted outcomes transiently expose authenticated payload and
normalized State. Rejections expose only classification/status/timing; no raw body.
HTTP 200 does not imply runtime ACCEPTED: modern sanitization/shape admission may
reject an HTTP-accepted legacy input. Parser/auth/size/transport/path classifications
remain distinguishable. The oversized-request transport exception is permitted only
for exactly 262145 bytes, HTTP 413 and a following valid HTTP 200; WinError 10054
always blocks. Real capture exposes no browser API or remote network listener.

## Journal and deterministic replay

`ShadowJournalRecordV1` has a finite record type (HEADER, INPUT, CONTROL, RESULT,
DIAGNOSTIC, FOOTER), strictly increasing record sequence, immutable canonical JSON
content, separate diagnostic JSON and fixed ruleset `runtime.shadow_foundation.v1`.
`ShadowJournalWriterV1` creates a new exclusive file, synchronously writes, flushes
and fsyncs. INPUT/CONTROL plus RESULT are one persistence transaction. All diagnostic
records for a transition are persisted before its state is published. Write/fsync
failure poisons the writer and fails capture permanently; no unaudited continuation,
automatic repair, overwrite or fallback.

Deterministic IDs use sorted keys, compact separators, ensure_ascii=True,
allow_nan=False, UTF-8 and SHA-256. Processing timings are excluded from record IDs.
Snapshot, event, projection, tracker/freshness IDs and full deterministic projections
are recorded for exact lineage comparisons.

`replay_shadow_records_v1(*, records: tuple[ShadowJournalRecordV1, ...])` reconstructs
state from HEADER and INPUT/CONTROL by executing the same reducer. RESULT is only a
comparison target. It compares statuses, reasons, identities, ticks, sequences,
normalization, capabilities, observations, Temporal projections/freshness, reset,
pause and gap behavior. It does not open HTTP, read clocks, instantiate Performance,
start subprocesses or produce coaching. Unsafe bodies were not stored: rejection
replay reproduces classification ONLY, and does not re-authenticate/re-parse them.

A complete replay requires the exact final-state-bound footer. Missing footer or
truncated final suffix yields INCOMPLETE; corrupt complete prefix records raise or
produce CORRUPT with explicit divergence details. Complete-prefix corruption is
never skipped. Extra data after a complete footer is invalid. A pending input with
no complete result does not commit reconstructed state. No journal bytes are repaired.

## Isolated runner and operation

Use `python -B -m coach02.shadow_runtime_v01 capture` with the existing settings file,
an external new journal path, explicit run/policy IDs, gap/freshness nanoseconds,
control interval and duration. `--scope-label` is optional diagnostics only. The
runner reads only port/token from existing settings; it never saves settings or
installs/rewrites GSI. Port collision fails; no other port is selected and no process
is killed. Existing receiver requested groups remain unchanged. Caller opens and
operates Dota manually. Replay CLI reads journal only and does not open the receiver.

Diagnostics record parsing/normalization, sanitization, reducer, append/fsync and
post-body durations. External acceptance monitoring records app CPU/RAM and local
backlog observations. This is no claim about Dota FPS. Capture has no configurable
coaching/voice/strategy switch and no output authority. No SQLite journal, legacy
recommendation storage, Window adapter, real screenshot, TTS or game action exists.

## Validation and milestone limits

Synthetic fixtures in `tests/fixtures/live_runtime_v01/SYNTHETIC.json` are explicitly
hand-authored contract vectors; they are never labeled real capture. Focused tests
cover independent field axes, raw parity, continuity, clocks, controls, rejection,
immutability, prefix replay, durability failure, isolation and hook legacy behavior.
Six functional guards participate: Observation Event, Temporal Evidence, Threat
Observation, Threat Absence, Visibility Completeness and Missing Threat Resolver.
Observation/Temporal authorization is generic infrastructure. The four semantic
guards grant only strict exact-path infrastructure exceptions; Live Runtime is
not a semantic consumer of Threat, Absence, Completeness or Missing, and receives
no semantic builder authority. The preplanned finite 26-test hash chain is
maintained. Abort Cost's exact inverse guard proof retains its original
hash and reverses the explicitly enumerated authorized hash literals before checking.

All project bytes freeze before one-shot focused/regression/full gates. Full baseline
and final suite have external timeout 240 seconds. No edits or retry-until-green after
gates begin. Acceptance also requires real GSI capture >=10 minutes and >=100 valid
updates, normalization/sanitization parity, zero replay divergence, no outputs, no
queue loss and measured p95 compose <50ms, journal <100ms, post-body total <250ms,
replay throughput >=10 times captured input rate. Evidence is external to Git.

The feature is not canonical until a separately authorized promotion. No semantic
producer, strategic decision, execution-aware switching, Microplan, Attention, output
authority, orchestration, Shadow coaching or real-match decision evaluation starts
with this foundation milestone.

BLOCKER_BEFORE_REAL_SEMANTIC_PRODUCERS

BLOCKER_BEFORE_DECISION_SHADOW_MODE

BLOCKER_BEFORE_EXECUTION_RECONCILIATION

BLOCKER_BEFORE_MICROPLAN

BLOCKER_BEFORE_COACH_CALL

BLOCKER_BEFORE_ATTENTION

BLOCKER_BEFORE_ACTIVE_COACHING
