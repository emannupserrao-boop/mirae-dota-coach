"""Scalar boundary regressions; fixtures do not claim raw-GSI provenance."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import State, normalize
from coach02 import decision, farm_cycle, runtime_adapter
from coach02.decision import (Freshness, Knownness, ObservedFact, Provenance,
                              RuntimeObservation, ScalarObservation, Source, Truth)
from coach02.runtime_adapter import adapt_state


def scalar_map(observation):
    return {s.provenance.ref: s for s in observation.scalars}


class RuntimeAdapterTests(unittest.TestCase):
    def test_normal_snapshot_maps_exact_supported_core(self):
        state = normalize(payload(t=603, lh=72, gold=1480))
        result = adapt_state(state)
        expected = dict(active=True, local=True, match_id='demo', time=603,
                        hero='npc_dota_hero_juggernaut', level=5, alive=True,
                        gold=1480, lh=72, gpm=400, xpm=450, deaths=0,
                        buyback=True, buyback_cost=700, buyback_cooldown=0)
        self.assertEqual(result.facts, ())
        self.assertEqual({s.provenance.ref: s.value for s in result.scalars},
                         {'State.' + key: value for key, value in expected.items()})
        self.assertTrue(all(s.knownness == Knownness.KNOWN for s in result.scalars))

    def test_missing_numeric_is_unknown_not_zero(self):
        data = payload()
        data['player'].pop('gold')
        result = scalar_map(adapt_state(normalize(data)))
        self.assertEqual(result['State.gold'].knownness, Knownness.UNKNOWN)
        self.assertIsNone(result['State.gold'].value)
        self.assertEqual(result['State.buyback'].knownness, Knownness.UNKNOWN)
        zero = scalar_map(adapt_state(normalize(payload(gold=0))))
        self.assertEqual(zero['State.gold'].knownness, Knownness.KNOWN)
        self.assertEqual(zero['State.gold'].value, 0)
        self.assertIs(zero['State.buyback'].value, False)

    def test_invalid_normalized_numbers_are_unknown(self):
        locations = {'time': ('map', 'clock_time'), 'level': ('hero', 'level'),
                     'gold': ('player', 'gold'), 'lh': ('player', 'last_hits'),
                     'gpm': ('player', 'gpm'), 'xpm': ('player', 'xpm'),
                     'deaths': ('player', 'deaths'), 'buyback_cost': ('hero', 'buyback_cost'),
                     'buyback_cooldown': ('hero', 'buyback_cooldown')}
        for value in (None, True, False, '12', float('nan'), float('inf'), float('-inf')):
            for name, (container, key) in locations.items():
                with self.subTest(field=name, value=repr(value)):
                    data = payload()
                    data[container][key] = value
                    state = normalize(data)
                    self.assertIsNone(getattr(state, name))
                    scalar = scalar_map(adapt_state(state))['State.' + name]
                    self.assertEqual(scalar.knownness, Knownness.UNKNOWN)
                    self.assertIsNone(scalar.value)

    def test_boolean_unknown_is_distinct_from_false(self):
        for value, expected in [(False, Knownness.KNOWN), (True, Knownness.KNOWN),
                                (None, Knownness.UNKNOWN), (0, Knownness.UNKNOWN),
                                ('false', Knownness.UNKNOWN)]:
            data = payload()
            data['hero']['alive'] = value
            scalar = scalar_map(adapt_state(normalize(data)))['State.alive']
            self.assertEqual(scalar.knownness, expected)
            self.assertIs(scalar.value, value if expected == Knownness.KNOWN else None)

    def test_spectator_and_nonplaying_do_not_fabricate_player_data(self):
        for spectator in (True, False):
            data = payload()
            if spectator:
                data['player'] = {'team2': {'player0': data['player']}}
            else:
                data['player']['activity'] = 'menu'
            state = normalize(data)
            self.assertFalse(state.local)
            values = scalar_map(adapt_state(state))
            for name in ('hero', 'level', 'alive', 'gold', 'lh', 'gpm', 'xpm',
                         'deaths', 'buyback', 'buyback_cost', 'buyback_cooldown'):
                self.assertEqual(values['State.' + name].knownness, Knownness.UNKNOWN)
                self.assertIsNone(values['State.' + name].value)
            for name in ('local', 'active'):
                self.assertEqual(values['State.' + name].knownness, Knownness.KNOWN)
                self.assertIs(values['State.' + name].value, False)
            self.assertEqual(values['State.time'].value, state.time)
            self.assertEqual(values['State.match_id'].value, state.match_id)

    def test_empty_identifiers_remain_unknown(self):
        values = scalar_map(adapt_state(State()))
        for name in ('match_id', 'hero'):
            self.assertEqual(values['State.' + name].knownness, Knownness.UNKNOWN)
        self.assertIs(values['State.active'].value, False)
        self.assertIsNone(values['State.buyback'].value)

    def test_identity_is_deterministic_and_matches_documented_projection(self):
        state = normalize(payload())
        first, second = adapt_state(state), adapt_state(state)
        self.assertEqual(first, second)
        encoded = json.dumps([asdict(s) for s in first.scalars], sort_keys=True,
                             separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
        self.assertEqual(first.observation_id, 'alpha-state-scalars-v1:' + hashlib.sha256(encoded).hexdigest())

    def test_observed_change_updates_value_and_identity(self):
        state = normalize(payload())
        before, after = adapt_state(state), adapt_state(replace(state, lh=73))
        self.assertNotEqual(before.observation_id, after.observation_id)
        self.assertEqual(scalar_map(after)['State.lh'].value, 73)
        for ref, value in scalar_map(before).items():
            if ref != 'State.lh': self.assertEqual(value, scalar_map(after)[ref])

    def test_no_carry_forward_between_snapshots(self):
        adapt_state(normalize(payload(gold=1480)))
        missing = scalar_map(adapt_state(replace(normalize(payload()), gold=None)))
        self.assertEqual(missing['State.gold'].knownness, Knownness.UNKNOWN)
        self.assertIsNone(missing['State.gold'].value)

    def test_immutable_result_and_no_state_mutation_or_retention(self):
        state = normalize(payload())
        before = state.to_dict()
        result = adapt_state(state)
        self.assertEqual(state.to_dict(), before)
        self.assertIsInstance(result.scalars, tuple)
        with self.assertRaises(FrozenInstanceError): result.observation_id = 'changed'
        with self.assertRaises(FrozenInstanceError): result.scalars[0].value = False
        with self.assertRaises(FrozenInstanceError): result.scalars[0].provenance.ref = 'changed'
        saved = asdict(result)
        state.items.clear()
        state.abilities.clear()
        self.assertEqual(asdict(result), saved)

    def test_collections_and_deferred_scalars_do_not_enter_identity(self):
        state = normalize(payload())
        changed = replace(state, items={'opaque': object()}, abilities={'opaque': object()},
                          kills=99, assists=88, denies=77)
        self.assertEqual(adapt_state(state), adapt_state(changed))

    def test_absent_hp_mana_not_invented_from_raw_payload(self):
        data = payload()
        original = adapt_state(normalize(data))
        data['hero'].update(health=500, max_health=700, mana=339, max_mana=339)
        self.assertEqual(adapt_state(normalize(data)), original)
        with self.assertRaisesRegex(TypeError, 'normalized_state_required'):
            adapt_state(data)

    def test_no_strategic_fields_or_boolean_fixture_facts(self):
        result = adapt_state(normalize(payload()))
        self.assertEqual(set(asdict(result)), {'observation_id', 'facts', 'scalars'})
        self.assertEqual(result.facts, ())
        allowed = {'active', 'local', 'match_id', 'time', 'hero', 'level', 'alive',
                   'gold', 'lh', 'gpm', 'xpm', 'deaths', 'buyback', 'buyback_cost', 'buyback_cooldown'}
        self.assertEqual({s.provenance.ref for s in result.scalars}, {'State.' + name for name in allowed})

    def test_provenance_and_freshness_reference_only_supplied_state(self):
        result = adapt_state(normalize(payload()))
        for scalar in result.scalars:
            self.assertEqual(scalar.provenance.source, Source.RUNTIME_OBSERVATION)
            self.assertTrue(scalar.provenance.ref.startswith('State.'))
            self.assertEqual(scalar.freshness, Freshness.FRESH)
        self.assertFalse(any(s.provenance.ref.startswith(('hero.', 'player.', 'map.')) for s in result.scalars))

    def test_existing_boolean_contract_and_mixed_observations(self):
        fact = ObservedFact('visible', Truth.YES, Freshness.FRESH)
        legacy = RuntimeObservation('legacy', (fact,))
        self.assertEqual(legacy.scalars, ())
        scalar = ScalarObservation(Provenance(Source.RUNTIME_OBSERVATION, 'State.time'), Knownness.KNOWN, 603)
        mixed = RuntimeObservation('mixed', (fact,), (scalar,))
        self.assertEqual(mixed.facts, legacy.facts)
        self.assertEqual(mixed.scalars[0].value, 603)
        with self.assertRaises(ValueError): ObservedFact('bad', 603, Freshness.FRESH)

    def test_scalar_contract_rejects_ambiguous_or_mutable_values(self):
        source = Provenance(Source.RUNTIME_OBSERVATION, 'State.time')
        for value in (None, {}, [], object(), float('nan'), float('inf'), Truth.YES):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                ScalarObservation(source, Knownness.KNOWN, value)
        for value in (0, False, ''):
            with self.assertRaises(ValueError): ScalarObservation(source, Knownness.UNKNOWN, value)
        with self.assertRaises(ValueError): ScalarObservation(source, None)
        with self.assertRaises(ValueError): ScalarObservation(Provenance(Source.EXPERT_HEURISTIC, 'x'), Knownness.UNKNOWN)
        scalar = ScalarObservation(source, Knownness.KNOWN, 1)
        with self.assertRaises(ValueError): RuntimeObservation('x', (), [scalar])
        with self.assertRaises(ValueError): RuntimeObservation('x', (), (scalar, scalar))
        fact = ObservedFact('State.time', Truth.YES, Freshness.FRESH)
        with self.assertRaises(ValueError): RuntimeObservation('x', (fact,), (scalar,))

    def test_manual_invalid_state_does_not_fabricate_property_values(self):
        state = normalize(payload())
        for value in (False, '12', float('nan'), float('inf')):
            invalid = scalar_map(adapt_state(replace(state, time=value, gold=value, gpm=value)))
            for name in ('time', 'gold', 'gpm', 'active', 'buyback'):
                self.assertEqual(invalid['State.' + name].knownness, Knownness.UNKNOWN)

    def test_existing_properties_are_preserved_without_new_heuristics(self):
        state = normalize(payload())
        for changed in (state, replace(state, paused=True), replace(state, alive=False),
                        replace(state, time=None), replace(state, time=-1),
                        replace(state, buyback_cooldown=1), replace(state, buyback_cost=None)):
            values = scalar_map(adapt_state(changed))
            self.assertEqual(values['State.active'].value, changed.active)
            self.assertEqual(values['State.buyback'].value, changed.buyback)
        # Legacy active does not require alive. Reporting it must not change that.
        self.assertTrue(scalar_map(adapt_state(replace(state, alive=False)))['State.active'].value)

    def test_adapter_calls_no_io_clock_environment_or_decision_layer(self):
        # Import test guard dependencies before entering the restricted call.
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        state = normalize(payload())
        expected = adapt_state(state)
        forbidden = AssertionError('adapter crossed scalar boundary')
        sinks = [(builtins, 'open'), (io, 'open'), (os, 'open'), (os, 'getenv'),
                 (os, 'system'), (socket, 'socket'), (socket, 'getaddrinfo'),
                 (socket, 'create_connection'), (http.client.HTTPConnection, 'request'),
                 (sqlite3, 'connect'), (subprocess, 'Popen'), (time, 'time'),
                 (time, 'monotonic'), (uuid, 'uuid4'), (random, 'random'),
                 (decision, 'build_context'), (decision, 'authorize_output'), (farm_cycle, 'plan')]
        class NoEnvironment(dict):
            def __getitem__(self, key): raise forbidden
            def get(self, *args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner, name in sinks:
                stack.enter_context(patch.object(owner, name, side_effect=forbidden))
            stack.enter_context(patch.object(os, 'environ', NoEnvironment()))
            result = adapt_state(state)
        self.assertEqual(result, expected)

    def test_adapter_dependency_boundary_is_standard_library_and_contracts(self):
        tree = ast.parse(Path(runtime_adapter.__file__).read_text(encoding='utf-8'))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(n.name for n in node.names)
            if isinstance(node, ast.ImportFrom): imports.add('.' * node.level + (node.module or ''))
        self.assertEqual(imports, {'dataclasses', 'hashlib', 'json', 'math', 'coach.state', '.decision'})
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))


if __name__ == '__main__': unittest.main()
