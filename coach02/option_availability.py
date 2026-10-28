"""Presence/access evidence only. No safety, risk, timing or action selection."""
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json

from .decision import (Action, Claim, Freshness, ObservedFact, ObservationSource,
                       PRODUCTIVE_ACTIONS, Truth)


class AvailabilityReason(str, Enum):
    RESOURCE_PRESENT_AND_ACCESSIBLE = 'availability.option.present_and_accessible.v1'
    RESOURCE_NOT_PRESENT = 'availability.option.not_present.v1'
    RESOURCE_NOT_ACCESSIBLE = 'availability.option.not_accessible.v1'
    RESOURCE_PRESENCE_UNKNOWN = 'availability.option.presence_unknown.v1'
    RESOURCE_PRESENCE_STALE = 'availability.option.presence_stale.v1'
    RESOURCE_ACCESS_UNKNOWN = 'availability.option.access_unknown.v1'
    RESOURCE_ACCESS_STALE = 'availability.option.access_stale.v1'
    INSUFFICIENT_AVAILABILITY_SUPPORT = 'availability.option.insufficient_support.v1'


def _identity(seed_id, option_id, action):
    if type(seed_id) is not str or not seed_id:
        raise ValueError('seed_binding_required')
    if (type(option_id) is not str or not option_id or not option_id.isascii()
            or not all(c.isalnum() or c in '_-' for c in option_id)):
        raise ValueError('invalid_option_id')
    if not isinstance(action, Action) or action not in PRODUCTIVE_ACTIONS:
        raise ValueError('invalid_farm_action')


@dataclass(frozen=True)
class FarmOptionAvailabilityObservation:
    seed_id: str
    option_id: str
    action: Action
    resource_presence: Truth
    presence_freshness: Freshness
    access_state: Truth
    access_freshness: Freshness

    def __post_init__(self):
        _identity(self.seed_id, self.option_id, self.action)
        if (not isinstance(self.resource_presence, Truth) or not isinstance(self.access_state, Truth)
                or not isinstance(self.presence_freshness, Freshness)
                or not isinstance(self.access_freshness, Freshness)):
            raise ValueError('invalid_availability_observation')


@dataclass(frozen=True)
class OptionAvailabilityEvidence:
    evidence_id: str
    seed_id: str
    option_id: str
    action: Action
    observations: tuple[ObservedFact, ...]
    availability: Claim
    reasons: tuple[AvailabilityReason, ...]
    ruleset: str

    def validate_binding(self, seed_id: str, option_id: str, action: Action) -> None:
        """Validate identity before unpacking into a legacy assessment.

        Consumers combining envelopes must provide the other envelope's identity.
        No dependency on, or interpretation of, any other evidence builder.
        """
        _identity(seed_id, option_id, action)
        if self.seed_id != seed_id:
            raise ValueError('availability_seed_mismatch')
        if self.option_id != option_id:
            raise ValueError('availability_option_mismatch')
        if self.action != action:
            raise ValueError('availability_action_mismatch')


RULESET = 'availability.option_presence.v1'


def build_option_availability(seed_id: str,
        options: tuple[FarmOptionAvailabilityObservation, ...]) -> tuple[OptionAvailabilityEvidence, ...]:
    """YES means supplied presence/access support, not safe or recommended.

    NO is explicit current unavailability, not danger or permanent absence.
    UNKNOWN is insufficient/stale evidence. Missing options stay omitted.
    """
    if type(seed_id) is not str or not seed_id:
        raise ValueError('seed_binding_required')
    if type(options) is not tuple or any(not isinstance(o, FarmOptionAvailabilityObservation) for o in options):
        raise TypeError('availability_observation_tuple_required')
    if any(o.seed_id != seed_id for o in options):
        raise ValueError('availability_observation_seed_mismatch')
    if len({o.option_id for o in options}) != len(options):
        raise ValueError('duplicate_option_id')
    return tuple(_assess(o) for o in sorted(options, key=lambda o: o.option_id))


def _assess(option):
    prefix = 'availability.option.' + option.option_id + '.'
    present = ObservedFact(prefix + 'resource_present', option.resource_presence,
                          option.presence_freshness, source=ObservationSource.SAFETY_EVIDENCE)
    access = ObservedFact(prefix + 'accessible', option.access_state,
                         option.access_freshness, source=ObservationSource.SAFETY_EVIDENCE)
    facts = tuple(sorted((present, access), key=lambda f: f.ref))
    negative = tuple(f for f in facts if f.value == Truth.NO and f.freshness == Freshness.FRESH)
    if negative:
        value = Truth.NO
        refs = tuple(f.ref for f in negative)
        reasons = tuple(reason for fact, reason in (
            (present, AvailabilityReason.RESOURCE_NOT_PRESENT),
            (access, AvailabilityReason.RESOURCE_NOT_ACCESSIBLE)) if fact in negative)
    elif all(f.value == Truth.YES and f.freshness == Freshness.FRESH for f in facts):
        value, refs = Truth.YES, tuple(f.ref for f in facts)
        reasons = (AvailabilityReason.RESOURCE_PRESENT_AND_ACCESSIBLE,)
    else:
        value, refs = Truth.UNKNOWN, tuple(f.ref for f in facts)
        reasons_list = []
        for fact, unknown, stale in (
            (present, AvailabilityReason.RESOURCE_PRESENCE_UNKNOWN, AvailabilityReason.RESOURCE_PRESENCE_STALE),
            (access, AvailabilityReason.RESOURCE_ACCESS_UNKNOWN, AvailabilityReason.RESOURCE_ACCESS_STALE)):
            if fact.value == Truth.UNKNOWN: reasons_list.append(unknown)
            if fact.freshness == Freshness.STALE: reasons_list.append(stale)
        reasons = tuple(reasons_list) or (AvailabilityReason.INSUFFICIENT_AVAILABILITY_SUPPORT,)
    rule = reasons[0].value if value != Truth.UNKNOWN else AvailabilityReason.INSUFFICIENT_AVAILABILITY_SUPPORT.value
    result = OptionAvailabilityEvidence('', option.seed_id, option.option_id, option.action,
        facts, Claim(value, refs, rule), reasons, RULESET)
    payload = asdict(result)
    payload.pop('evidence_id')
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    return replace(result, evidence_id=RULESET + ':' + hashlib.sha256(encoded).hexdigest())
