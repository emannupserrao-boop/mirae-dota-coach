"""Pure runtime eligibility seed. Explicit opt-in; no planner or live output."""
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json

from .decision import (Freshness, Knownness, KnowledgeSnapshotRef,
                       PlayerModelSnapshotRef, RuntimeObservation, ScalarObservation)
from .runtime_adapter import BOOLEAN_FIELDS, NUMBER_FIELDS, TEXT_FIELDS


class Eligibility(str, Enum):
    ELIGIBLE = 'ELIGIBLE'
    INELIGIBLE = 'INELIGIBLE'
    INSUFFICIENT_DATA = 'INSUFFICIENT_DATA'


class SeedReason(str, Enum):
    MATCH_NOT_ACTIVE = 'runtime_seed.match_not_active.v1'
    NON_LOCAL_PLAYER = 'runtime_seed.non_local_player.v1'
    PLAYER_DEAD = 'runtime_seed.player_dead.v1'
    ACTIVE_UNKNOWN = 'runtime_seed.active_unknown.v1'
    LOCAL_UNKNOWN = 'runtime_seed.local_unknown.v1'
    ALIVE_UNKNOWN = 'runtime_seed.alive_unknown.v1'
    HERO_UNKNOWN = 'runtime_seed.hero_unknown.v1'
    MATCH_TIME_UNKNOWN = 'runtime_seed.match_time_unknown.v1'
    REQUIRED_STALE = 'runtime_seed.required_stale.v1'


@dataclass(frozen=True)
class RuntimeReason:
    code: SeedReason
    # Resolve within this seed's observation_id/dimensions; absent is not observed.
    ref: str


@dataclass(frozen=True)
class DecisionContextSeed:
    seed_id: str
    observation_id: str
    knowledge: KnowledgeSnapshotRef
    player: PlayerModelSnapshotRef
    eligibility: Eligibility
    eligibility_refs: tuple[str, ...]
    reasons: tuple[RuntimeReason, ...]
    dimensions: tuple[ScalarObservation, ...]
    unknown_required: tuple[str, ...]
    stale_required: tuple[str, ...]


# Fixed order is also the order of reasons and evidence dependencies.
REQUIRED = (
    ('State.active', SeedReason.ACTIVE_UNKNOWN, SeedReason.MATCH_NOT_ACTIVE),
    ('State.local', SeedReason.LOCAL_UNKNOWN, SeedReason.NON_LOCAL_PLAYER),
    ('State.alive', SeedReason.ALIVE_UNKNOWN, SeedReason.PLAYER_DEAD),
    ('State.hero', SeedReason.HERO_UNKNOWN, None),
    ('State.time', SeedReason.MATCH_TIME_UNKNOWN, None),
)


def build_context_seed(runtime_observation: RuntimeObservation,
                       knowledge_ref: KnowledgeSnapshotRef,
                       player_ref: PlayerModelSnapshotRef) -> DecisionContextSeed:
    """Derive only eligibility; preserve supplied scalars and versioned lineage.

    A fresh explicit blocker wins over missing support, but uncertainties remain
    recorded. Stale supplied facts are retained, never used as current support.
    No time is measured; active/buyback are not recomputed or explained.
    """
    if not isinstance(runtime_observation, RuntimeObservation):
        raise TypeError('runtime_observation_required')
    if type(runtime_observation.observation_id) is not str or not runtime_observation.observation_id:
        raise ValueError('observation_identity_required')
    for ref, kind in ((knowledge_ref, KnowledgeSnapshotRef), (player_ref, PlayerModelSnapshotRef)):
        if not isinstance(ref, kind):
            raise TypeError('snapshot_reference_type')
        if any(type(value) is not str or not value for value in (ref.snapshot_id, ref.version)):
            raise ValueError('versioned_snapshot_required')

    dimensions = tuple(sorted(runtime_observation.scalars, key=lambda s: s.provenance.ref))
    # ScalarObservation validates knownness, freshness, provenance and finiteness.
    # Here enforce only the accepted adapter's field-specific types.
    for scalar in dimensions:
        name = scalar.provenance.ref.removeprefix('State.')
        if scalar.provenance.ref != 'State.' + name or name not in NUMBER_FIELDS + BOOLEAN_FIELDS + TEXT_FIELDS:
            raise ValueError('unsupported_runtime_scalar')
        if scalar.knownness == Knownness.KNOWN:
            value = scalar.value
            valid = (type(value) in (int, float) if name in NUMBER_FIELDS else
                     type(value) is bool if name in BOOLEAN_FIELDS else
                     type(value) is str and bool(value))
            if not valid:
                raise ValueError('invalid_runtime_scalar_type')

    by_ref = {scalar.provenance.ref: scalar for scalar in dimensions}
    reasons, unknown, stale = [], [], []
    blocked = False
    for ref, unknown_reason, blocker in REQUIRED:
        scalar = by_ref.get(ref)
        if scalar is None or scalar.knownness == Knownness.UNKNOWN:
            unknown.append(ref)
            reasons.append(RuntimeReason(unknown_reason, ref))
        if scalar is not None and scalar.freshness == Freshness.STALE:
            stale.append(ref)
            reasons.append(RuntimeReason(SeedReason.REQUIRED_STALE, ref))
        if (scalar is not None and scalar.knownness == Knownness.KNOWN
                and scalar.freshness == Freshness.FRESH and blocker is not None
                and scalar.value is False):
            blocked = True
            reasons.append(RuntimeReason(blocker, ref))
    eligibility = (Eligibility.INELIGIBLE if blocked else
                   Eligibility.INSUFFICIENT_DATA if unknown or stale else
                   Eligibility.ELIGIBLE)
    seed = DecisionContextSeed('', runtime_observation.observation_id, knowledge_ref, player_ref,
        eligibility, tuple(ref for ref, _, _ in REQUIRED), tuple(reasons), dimensions,
        tuple(unknown), tuple(stale))
    payload = asdict(seed)
    payload.pop('seed_id')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return replace(seed, seed_id='runtime-context-seed-v1:' + hashlib.sha256(encoded).hexdigest())
