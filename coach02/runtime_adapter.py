"""Explicit opt-in adapter: normalized State -> scalar RuntimeObservation only."""
from dataclasses import asdict
import hashlib
import json
import math

from coach.state import State
from .decision import (Knownness, Provenance, RuntimeObservation, ScalarObservation,
                       Source)

# The canonical State has no HP/mana. Collections and other scalars are deferred.
NUMBER_FIELDS = ('time', 'level', 'gold', 'lh', 'gpm', 'xpm', 'deaths',
                 'buyback_cost', 'buyback_cooldown')
BOOLEAN_FIELDS = ('local', 'alive', 'active', 'buyback')
TEXT_FIELDS = ('match_id', 'hero')


def _number(value):
    return type(value) in (int, float) and (type(value) is int or math.isfinite(value))


def _read(state, name):
    # Guard malformed manually constructed States before evaluating properties.
    # None is valid in the legacy contract; preserve the properties' own handling.
    if name == 'buyback':
        if any(v is not None and not _number(v) for v in
               (state.gold, state.buyback_cost, state.buyback_cooldown)):
            return None
    if name == 'active':
        if (type(state.local) is not bool or type(state.paused) is not bool
                or type(state.hero) is not str or type(state.phase) is not str
                or (state.time is not None and not _number(state.time))):
            return None
    return getattr(state, name)


def adapt_state(state: State) -> RuntimeObservation:
    """Report the current normalized scalar projection, without retaining State.

    active/buyback are the existing State properties, not new strategic rules.
    Empty strings are the State contract's unset identifier/name sentinel.
    Identity covers this projection, not omitted fields, receipt time or secrets.
    """
    if not isinstance(state, State):
        raise TypeError('normalized_state_required')
    values = []
    for name in NUMBER_FIELDS + BOOLEAN_FIELDS + TEXT_FIELDS:
        value = _read(state, name)
        if name in NUMBER_FIELDS:
            valid = _number(value)
        elif name in BOOLEAN_FIELDS:
            valid = type(value) is bool
        else:
            valid = type(value) is str and value != ''
        values.append(ScalarObservation(
            Provenance(Source.RUNTIME_OBSERVATION, 'State.' + name),
            Knownness.KNOWN if valid else Knownness.UNKNOWN,
            value if valid else None))
    scalars = tuple(sorted(values, key=lambda s: s.provenance.ref))
    encoded = json.dumps([asdict(s) for s in scalars], sort_keys=True,
                         separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
    identity = 'alpha-state-scalars-v1:' + hashlib.sha256(encoded).hexdigest()
    return RuntimeObservation(identity, (), scalars)
