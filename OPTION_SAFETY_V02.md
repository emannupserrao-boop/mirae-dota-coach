# Option Safety Gate v0.2

Option Safety v0.2 is a modeled-risk tolerance gate, not action decision.
It consumes an accepted RiskEvaluationSnapshot and explicit caller-supplied
OptionSafetyPolicyClaim values. It asks only whether modeled risk blocks an
explicit option/context under the supplied tolerance policy.

**RISK_BLOCKING does not mean UNSAFE.**

**RISK_NOT_BLOCKING does not mean SAFE.**

**RISK_NOT_BLOCKING does not mean RECOMMENDED.**

**INDETERMINATE does not mean DANGEROUS.**

**RISK_BLOCKING does not mean RETREAT.**

Supported risk is blocked/tolerated only by explicit policy.
Risk INDETERMINATE cannot be overridden by tolerance.
NOT_ESTABLISHED passes modeled-risk gate but does not establish global safety.
No option ranking. No strategic reward, commitment or reversibility.

## API and dependencies

`evaluate_option_safety_v2(risk_evaluation_snapshot, policy_claims)` returns
`OptionSafetySnapshotV2`. Both arguments are explicit; there is no default policy.
The only production imports beyond dataclasses, enum, hashlib and json are
RiskEvaluationSnapshot, OptionRiskEvaluation and RiskConclusion from
coach02.risk_evaluation. No accepted constructor or evaluator is invoked.

No direct imports from Risk Evidence, Reachability, Threat State/Relevance,
Coverage, Exposure, Event, Temporal, legacy Safety, Decision or runtime exist.
Risk Evaluation is authoritative. Its complete nested evidence is retained and
serialized for identity, but never inspected to reinterpret its conclusion.
No lower evidence, freshness, risk contribution or risk conclusion is recomputed.

Legacy option_safety.py and safety_evidence.py remain frozen. The new module is
coach02/option_safety_v02.py, independent of their production implementations.

## Exact domains

| OptionSafetyGateStatus | Meaning for the explicit option/context |
|---|---|
| RISK_BLOCKING | Modeled risk prevents passing the risk gate under the explicit policy. |
| RISK_NOT_BLOCKING | Modeled risk does not prevent passing this gate under the policy. |
| INDETERMINATE | Risk and/or policy does not establish whether modeled risk blocks the option. |

| SupportedRiskTolerance | Meaning only when risk is SUPPORTED |
|---|---|
| TOLERATED | Supported modeled risk does not block the option solely because of risk. |
| NOT_TOLERATED | Supported modeled risk blocks the option at this gate. |
| UNKNOWN | The policy does not establish whether supported risk is tolerated. |

TOLERATED is neither SAFE nor RECOMMENDED. NOT_TOLERATED is not UNSAFE.
The accepted risk domain remains SUPPORTED / NOT_ESTABLISHED / INDETERMINATE.

## Explicit policy claim

Frozen OptionSafetyPolicyClaim fields:

- risk_context_id
- option_id
- safety_context_id
- supported_risk_tolerance
- safety_policy_id

The exact (risk_context_id, option_id) pair selects one accepted Risk Evaluation
row. At most one claim is allowed per pair; duplicates reject even when tolerance,
safety context or policy differs. Subset claims are valid. Claims for foreign
pairs reject, including a different risk context for an existing option.

All four identifiers are exact concrete, nonblank strings. They are opaque and
preserved without trimming, parsing or normalization. Risk and Safety contexts
have separate meanings; no string hierarchy, naming convention, player role,
strategic objective or automatic equality relationship is inferred. The same
option can have distinct risk contexts with independently bound claims.

safety_policy_id identifies the caller's external tolerance policy/version.
The implementation owns the distinct fixed gate_policy_id: option.safety_gate.v2.
Neither a default tolerance nor a caller override of gate semantics exists.

## Deterministic gate table

| Accepted risk | Explicit policy | Gate status | Reason |
|---|---|---|---|
| SUPPORTED | NOT_TOLERATED | RISK_BLOCKING | SUPPORTED_RISK_NOT_TOLERATED |
| SUPPORTED | TOLERATED | RISK_NOT_BLOCKING | SUPPORTED_RISK_TOLERATED |
| SUPPORTED | UNKNOWN | INDETERMINATE | SUPPORTED_RISK_POLICY_UNKNOWN |
| SUPPORTED | No claim | INDETERMINATE | SUPPORTED_RISK_POLICY_ABSENT |
| NOT_ESTABLISHED | Any or none | RISK_NOT_BLOCKING | RISK_NOT_ESTABLISHED |
| INDETERMINATE | Any or none | INDETERMINATE | RISK_INDETERMINATE |

Absence and UNKNOWN are distinct: absence preserves None for claim and safety
context, while UNKNOWN preserves a concrete claim, context and caller policy.
Even when both gate statuses are INDETERMINATE, reasons and snapshot IDs differ.

Claims supplied for NOT_ESTABLISHED or INDETERMINATE are retained intact for
provenance and identity, but cannot change the gate status/reason. Tolerance only
applies to SUPPORTED. Two SUPPORTED options under different policies can have
different gate results; that does not rank or choose between them.

## Immutable outputs and preservation

Frozen OptionSafetyEvaluationV2 has risk_context_id, option_id,
safety_context_id (optional), gate_status, reason, gate_policy_id,
safety_policy_claim (optional), and base_risk_evaluation. The complete exact
accepted OptionRiskEvaluation and exact claim objects are retained, not rebuilt
or stripped. Existing threat provenance remains nested in that accepted object.

Frozen OptionSafetySnapshotV2 has timeline_id, selected_clock_id,
risk_evaluation_snapshot_id, risk_assembly_tick, gate_policy_id, evaluations,
and a computed snapshot_id property. The tick and clock are copied exactly;
there is no new time source, refresh or execution state.

Exactly one output is produced per input Risk Evaluation row, preserving
canonical input order independently of gate status. No rows are filtered and no
options invented. Empty Risk Evaluation requires empty claims and produces an
empty Safety snapshot, meaning no options were gated, without an implicit safety
conclusion. Inputs are never mutated.

## Defensive boundary

Require exact RiskEvaluationSnapshot, tuple evaluations, exact OptionRiskEvaluation
rows, unique option/risk pairs and concrete RiskConclusion. Header and row IDs must
be exact nonblank strings; snapshot and row risk ticks must be concrete int,
excluding bool, and match. Row evaluation_policy_id must match the snapshot.
The policy_claims container must be a tuple of exact OptionSafetyPolicyClaim
objects. Claim fields and concrete tolerance are rechecked at the API boundary.
All inputs are validated atomically before output is produced; dangling claims
are rejected even when a risk conclusion would otherwise ignore policy.

These are structural/identity checks, not a reconstruction of upstream semantic
validation. In particular, nested reasons, contribution rules and evidence are
not used to second-guess the authoritative risk conclusion.

## Canonical identity

Ruleset and fixed gate policy: option.safety_gate.v2.

snapshot_id is `option.safety_gate.v2:snapshot:` plus SHA-256 of asdict(snapshot),
serialized with JSON sort_keys=True, compact separators, ensure_ascii=True and
UTF-8. The computed ID itself is excluded because it is a property.

Claims are normalized by (risk_context_id, option_id, safety_context_id,
safety_policy_id), then bound to the exact input pair. Caller claim order does
not alter output ordering or identity. Each accepted claim is preserved once in
its output row; no claim is silently discarded.

Identity binds the exact Risk Evaluation snapshot ID, timeline, clock, risk tick,
fixed gate policy, complete base evaluations, all attached claims, contexts,
tolerance, external policy IDs, statuses and reasons. Changes to a claim still
change identity when that claim does not affect the gate outcome. Full nested
provenance is serialized without assigning it new semantic weight.

## Legacy compatibility inspection

**NO_DIRECT_PRODUCTION_COMPATIBILITY_V02**

option_safety.py exposes action-bearing FarmOptionSafetyObservation and
OptionSafetyEvidence with a safety Claim. Its legacy exposure domain is
LOW/HIGH/UNKNOWN and its heuristic uses exposure/freshness/coverage plus global
RiskAwarenessEvidence. It has no explicit supported-risk tolerance or separate
Safety context/policy binding and cannot represent a risk gate without changing
meaning. Mapping RISK_NOT_BLOCKING to a positive safety Claim would incorrectly
turn non-blocking modeled risk into heuristic acceptability.

safety_evidence.py uses seed-bound RiskAwarenessEvidence and simplified
RelevantThreatObservation (threat_id/state/freshness). It lacks the complete
option/context-bound Risk Evaluation envelope, explicit tolerance claim and gate
reasons. A superficial three-way truth mapping loses these semantics/provenance.

Both files were inspected for documentation only, remain unchanged, and are not
production dependencies. No compatibility adapter was created.

## Future Decision Context handoff

Future Decision Context should consume OptionSafetySnapshotV2 together with
separate strategic objective, option value/reward, opportunity cost, future resource access, commitment, reversibility, abort window, execution state and
urgency. RISK_NOT_BLOCKING must never be interpreted as choose option.

The gate has no reward, expected value, severity, damage/death, resource,
commitment, reversibility, execution, option ranking, action or speech authority.
It does not produce GO/STOP/LEAVE/STAY/RETREAT/FIGHT/FARM/ROTATE or
DIRECTIVE/ADVISORY/AWARENESS/SUPPRESS. Those later layers are not implemented here.

### BLOCKER_BEFORE_DECISION_CONTEXT

- Strategic objective, option value/reward and opportunity cost remain separate.
- Future resource access, commitment, reversibility, abort window, execution
  state and urgency need accepted explicit contracts.
- No context composition translating gate output into action preference exists.

### BLOCKER_BEFORE_ACTION_AUTHORITY

- No Decision Arbiter, option selection or action-authority policy.
- No Microplan integration, Attention Gate or output/speech authority.
- A passing modeled-risk gate does not establish global safety or recommendation.

### BLOCKER_BEFORE_LIVE

- Upstream fixtures and external tolerance policies are synthetic.
- No live orchestration, real-match validation or Shadow Mode integration.
- Real reachability and caller tolerance policies need independent validation.

### ACCEPTED_V02_LIMITATION

- Modeled-risk gating only, under explicit tolerance claims.
- No default tolerance or override of epistemic uncertainty.
- No severity, value or action selection.
- No multi-source policy reconciliation; conflicting duplicate pairs reject.

## Guards and acceptance discipline

The reverse-dependency guard in tests/test_risk_evaluation.py admits only
coach02/option_safety_v02.py and only RiskEvaluationSnapshot, OptionRiskEvaluation
and RiskConclusion. evaluate_risk, constructors, aliases, dynamic/module/wildcard
imports, arbitrary consumers and live/runtime consumers remain rejected.
Lower-domain guards remain unchanged. Existing production is byte-preserved.

The focused suite contains 104 tests, including all 12 risk/policy combinations,
opaque binding, missing versus UNKNOWN claims, exact contracts, immutable
provenance, deterministic identity, purity, forbidden authority, legacy review
and dependency denials. The baseline, guards, focused and specified regressions
and full suite each run once. Any failing gate stops acceptance; no retry or
post-gate edit is permitted. Passing bytes are committed exactly.
