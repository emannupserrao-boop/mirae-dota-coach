# Risk Evidence Assembly v0.2

v0.2 extends accepted Risk Evidence v0.1; it does not rebuild it.

Risk Evidence v0.1 remains frozen.

Threat Reachability is the fifth evidence axis.

Reachability UNKNOWN is not ABSENT reachability.

CAN_AFFECT does not mean DANGEROUS.

CANNOT_AFFECT does not mean SAFE.

CURRENT/HISTORICAL/ABSENT are evidence usability states, not risk levels.

v0.2 preserves every v0.1 bundle and threat row exactly.

v0.2 does not calculate risk or safety.

## Versioned architecture

`coach02.risk_evidence_assembly_v02` consumes only accepted contracts from
Risk Evidence Assembly v0.1 and Threat Reachability v0.1, plus explicit extension
bindings. It adds reachability to the accepted composition, without accepting
the original four upstream snapshots or rerunning their builders.

```python
build_risk_evidence_v2(
    risk_evidence_v1: RiskEvidenceSnapshot,
    threat_reachability_snapshot: ThreatReachabilitySnapshot,
    bindings: tuple[RiskEvidenceReachabilityBinding, ...],
) -> RiskEvidenceSnapshotV2
```

Production imports only dataclasses, hashlib, json and these contracts:

- RiskEvidenceSnapshot, OptionRiskEvidenceBundle, ThreatRiskEvidence and
  EvidenceUseStatus from risk_evidence_assembly.
- ThreatReachabilitySnapshot, ThreatReachabilityAssessment and ThreatReachability
  from threat_reachability.

There are no direct imports of Threat State, Threat Relevance, Strategic Coverage,
Option Exposure, lower observation/temporal/resolver foundations, legacy Safety,
Option Safety, Decision, runtime, GSI or vision. The existing production modules
remain byte-identical and independently usable. No existing production consumer
is integrated with v0.2.

## Complete extension binding

Frozen `RiskEvidenceReachabilityBinding` has five fields:

- `risk_context_id`
- `option_id`
- `reachability_context_id`
- `horizon_id`
- `reachability_binding_policy_id`

The first two identify an exact existing v0.1 option bundle. The next two choose
an explicit reachability context and strategic horizon. The policy identifies
the external reachability-extension mapping; it does not replace, reinterpret
or implement the original v0.1 `binding_policy_id`.

All IDs are exact concrete nonblank strings, opaque and untrimmed. Equal-looking
context IDs do not cause joins; no prefixes, suffixes, option meaning or horizon
duration is interpreted. Exactly one extension binding is required per v0.1
`(risk_context_id, option_id)` pair. Missing, duplicate or foreign extension keys
reject. Even a bundle with no matching reachability needs an explicit context
and horizon so absence has a defined scope.

An empty v0.1 bundle tuple requires empty bindings and returns empty v0.2 bundles.
Reachability may be empty or may contain accepted unselected assessments. Empty
means no composed risk-option bundles, not a safety or threat conclusion.

## Structural lineage and defensive validation

Inputs and bindings require the exact accepted concrete classes; containers
must be concrete tuples. Required IDs are concrete and nonblank. v0.1 bundle keys
and each bundle's threat IDs must be unique. Exact base bundle/threat row types,
base use-enum types and enclosing bundle tick binding are checked. v0.1 remains
authoritative over its four axes: their selection, semantics and currentness are
not recomputed.

Both snapshots must have identical timeline and selected clock, before comparing
ticks. Reachability's `threat_state_snapshot_id` must equal v0.1's exact
`threat_state_snapshot_id`. Each preserved base state assessment must agree with
the reachability evaluated tick and threat subject. Repeated state evidence for
a subject across base bundles must agree. Each reachability row retains a state
assessment with the same subject and evaluated tick, and must equal the complete
corresponding state object in the base universe, including type and nested
provenance. Claimed matching IDs cannot mask differing retained evidence.

Reachability rows require exact accepted assessment types, unique
`(threat_id, option_id, reachability_context_id, horizon_id)` keys, nonblank
identities and the concrete reachability enum. Duplicate or malformed extra rows
also reject, even if unselected. Valid extra options, contexts and horizons are
allowed and ignored by selection. When base bundles exist, a foreign threat
outside their authoritative state universe rejects. With no base bundles, there
is no retained state universe to compare: global state-snapshot identity and each
reachability row's subject/tick binding still apply.

This verifies structural lineage only. It does not reconstruct a Threat State
snapshot, rerun arbitration, re-evaluate temporal evidence or calculate
reachability. Accepted parent contracts own their nested semantic validity.
Deterministic IDs identify supplied data; they do not authenticate external truth.

## V02_TEMPORAL_EXTENSION_ALIGNMENT_RULE

After same-clock validation, concrete integer ticks excluding bool are required:

```text
risk_assembly_tick_v2 = max(
    risk_evidence_v1.risk_assembly_tick,
    threat_reachability_snapshot.evaluated_at_tick,
)
```

The result must equal the accepted v0.1 risk tick. If reachability would advance
the common tick, composition rejects. This applies even to empty compositions.
Negative ticks are supported.

Advancing the tick would invalidate the meaning of v0.1 CURRENT statuses while
v0.2 is forbidden to mutate them. Therefore v0.2 never recomputes or rewrites
state_use, relevance_use, coverage_use or exposure_use. It preserves CURRENT,
HISTORICAL and ABSENT exactly through the original objects. No wall clock,
clock conversion, temporal advancement, age calculation or refresh occurs.

## Reachability selection and use

Every base threat row selects at most one reachability assessment by exact:

```text
base_threat_row.threat_id
base_bundle.option_id
extension.reachability_context_id
extension.horizon_id
```

No evidence is borrowed across threats, options, contexts or horizons. A matching
assessment is retained as the complete accepted object. Its use is CURRENT iff
reachability evaluated_at_tick equals the v0.2 risk tick; otherwise HISTORICAL.
No match gives None and ABSENT. The existing v0.1 EvidenceUseStatus enum is reused;
no new use or FRESH/STALE enum is introduced.

UNKNOWN may be CURRENT or HISTORICAL and is not absence. Historical CAN_AFFECT,
CANNOT_AFFECT and UNKNOWN preserve their semantic value. No UNKNOWN row is
synthesized for absent evidence. All base threats remain, including NOT_RELEVANT,
CONFLICTED, UNKNOWN state, relevance-ABSENT and CANNOT_AFFECT. CAN_AFFECT does not
promote a row or change its order.

## Immutable output and version recovery

Frozen `ThreatRiskEvidenceV2` contains the exact `base_threat_evidence`, optional
complete `reachability_assessment`, and `reachability_use`.

Frozen `OptionRiskEvidenceBundleV2` contains the exact `base_bundle`, explicit
reachability context, horizon and extension policy IDs, and a tuple of extended
threat rows. Those rows correspond one-to-one to base_bundle.threats in its exact
accepted canonical order. No base subject is added, removed, duplicated or
filtered. The four previous axes are retained through the base objects, not
copied into independently interpreted fields.

Frozen `RiskEvidenceSnapshotV2` contains timeline, selected clock,
base_risk_evidence_snapshot_id, threat_reachability_snapshot_id, risk_assembly_tick
and the bundles tuple. Complete base bundle objects retain v0.1 provenance;
the exact base snapshot ID also covers provenance of an empty base composition.

Version recovery: `tuple(b.base_bundle for b in v2.bundles)` is exactly the v0.1
bundle tuple by equality and per-bundle object identity. Each base threat row
also retains object identity. Removing only the extension recovers the original
bundles and therefore the original snapshot identity when combined with its
unchanged header. Both inputs remain unmodified.

## Ordering and identity

Extension bindings normalize by risk context, option, reachability context,
horizon and extension policy. The output preserves v0.1 bundle order and each
base threat order. Binding input order is irrelevant.

Ruleset: `risk.evidence_assembly.v2`. The snapshot ID is ruleset:snapshot:SHA-256
of full dataclass JSON with sorted keys, compact separators, ensure_ascii=True
and UTF-8. The derived property is not recursively serialized. It binds both
accepted input snapshot IDs, timeline, clock, tick, complete base bundles and
rows, every extension field, selected full reachability objects and use statuses.
Unselected valid reachability affects its upstream snapshot ID and therefore
v0.2 identity, while leaving selected bundle data unchanged.

## No verdict or calculation

RELEVANT, NOT_RELEVANT, MISSING, VISIBLE_NEARBY, CONFLICTED, EXPOSED, NOT_EXPOSED,
SUFFICIENT or INSUFFICIENT combined with CAN_AFFECT remains evidence only.
CANNOT_AFFECT plus NOT_EXPOSED does not establish safety. No SAFE, UNSAFE, risk
level, danger, score, probability, confidence, recommendation, action, weighting
or ranking is produced.

No capability, distance, pathfinding, movement, mobility, Blink, teleport, global
ability, travel time, cooldown, hero/item lookup or map geometry is calculated.
No legacy adapter or downstream policy invocation. No I/O, network, environment,
randomness, UUID, database, subprocess, async, scheduler or mutable global state.

## Guard maintenance and validation

Only the reverse-consumer guards in test_risk_evidence_assembly.py and
test_threat_reachability.py authorize the new exact consumer
coach02/risk_evidence_assembly_v02.py. Permissions are the seven contracts actually
imported above. Builders, contract construction via aliases, arbitrary consumers,
wildcards, module-wide and dynamic imports remain rejected. Existing upstream
checks and unrelated assertions are retained.

Pre-edit finite stored-SHA dependency review found no dependents for either
changed test; zero hash literal maintenance is required. All 43 existing
production files have pinned hashes. The focused matrix contains 104 tests,
including version recovery, immutable object preservation, all use states,
complete bindings, exact lineage, temporal rejection, selection isolation,
adversarial combinations, purity and guard scope. Each gate runs once with no
retry; all LF bytes and maintenance are completed beforehand. Exact passing
bytes must be committed. Actual results are recorded externally.

## BLOCKER_BEFORE_RISK_EVALUATION

- No risk policy or severity/weight model.
- No real reachability policy or real capability model.
- No evidence combination rules.

## BLOCKER_BEFORE_LIVE_INTEGRATION

- Upstream sources remain synthetic/non-real.
- Live clock/alignment unresolved.
- No live orchestration.

## ACCEPTED_V02_LIMITATION

- Complete extension binding required for every v0.1 bundle.
- Reachability context/horizon caller supplied.
- No multi-source reconciliation or reliability weighting.
- No risk verdict or safety verdict.
- Later reachability that would advance the accepted common tick is rejected.

Promotion, Risk Evaluation/Policy, capability/mobility engines, Safety v0.2,
Decision integration, geometry/pathfinding, real observation, live orchestration,
Shadow Mode and real-match testing remain outside this feature.
