"""Offline semantic gates only; no planner invocation or gameplay assessment."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import normalize
from coach02 import context_builder
from coach02.context_builder import (DecisionContextSeed, Eligibility, SeedReason,
                                      build_context_seed)
from coach02.decision import (Freshness, Knownness, KnowledgeSnapshotRef,
    ObservedFact, PlayerModelSnapshotRef, Provenance, RuntimeObservation,
    ScalarObservation, Source, Truth)
from coach02.runtime_adapter import adapt_state

KNOWLEDGE = KnowledgeSnapshotRef('not-loaded', 'v1')
PLAYER = PlayerModelSnapshotRef('not-profiled', 'v1')


def observation():
    return adapt_state(normalize(payload(t=300, lh=10, gold=100)))


def changed(obs, name, value=None, *, freshness=Freshness.FRESH):
    ref = 'State.' + name
    scalar = ScalarObservation(Provenance(Source.RUNTIME_OBSERVATION, ref),
        Knownness.UNKNOWN if value is None else Knownness.KNOWN, value, freshness)
    return replace(obs, scalars=tuple(scalar if s.provenance.ref == ref else s for s in obs.scalars))


def seed(obs=None):
    return build_context_seed(observation() if obs is None else obs, KNOWLEDGE, PLAYER)


class ContextBuilderTests(unittest.TestCase):
    def test_normal_eligible_preserves_projection_and_evidence(self):
        obs = observation()
        result = seed(obs)
        self.assertEqual(result.eligibility, Eligibility.ELIGIBLE)
        self.assertEqual(result.reasons, ())
        self.assertEqual(result.unknown_required, ())
        self.assertEqual(result.observation_id, obs.observation_id)
        self.assertEqual(result.dimensions, obs.scalars)
        self.assertEqual(result.eligibility_refs,
            ('State.active', 'State.local', 'State.alive', 'State.hero', 'State.time'))
        self.assertTrue(all(s.provenance.source == Source.RUNTIME_OBSERVATION for s in result.dimensions))

    def test_explicit_inactive_uses_supplied_property_without_cause(self):
        result = seed(changed(observation(), 'active', False))
        self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
        self.assertEqual([(r.code, r.ref) for r in result.reasons],
                         [(SeedReason.MATCH_NOT_ACTIVE, 'State.active')])

    def test_explicit_nonlocal(self):
        result = seed(changed(observation(), 'local', False))
        self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
        self.assertEqual([(r.code, r.ref) for r in result.reasons],
                         [(SeedReason.NON_LOCAL_PLAYER, 'State.local')])

    def test_dead_is_blocking_even_when_legacy_active_is_true(self):
        state = replace(normalize(payload()), alive=False)
        self.assertTrue(state.active)
        result = seed(adapt_state(state))
        self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
        self.assertEqual([(r.code, r.ref) for r in result.reasons],
                         [(SeedReason.PLAYER_DEAD, 'State.alive')])

    def test_unknown_booleans_never_become_negative_facts(self):
        for name, reason in [('active', SeedReason.ACTIVE_UNKNOWN),
                             ('local', SeedReason.LOCAL_UNKNOWN), ('alive', SeedReason.ALIVE_UNKNOWN)]:
            with self.subTest(name=name):
                result = seed(changed(observation(), name))
                self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
                self.assertEqual(result.unknown_required, ('State.' + name,))
                self.assertEqual([(r.code, r.ref) for r in result.reasons], [(reason, 'State.' + name)])

    def test_unknown_hero_is_insufficient_when_other_inputs_are_positive(self):
        result = seed(changed(observation(), 'hero'))
        self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
        self.assertEqual(result.reasons[0].code, SeedReason.HERO_UNKNOWN)

    def test_unknown_time_is_insufficient_when_other_inputs_are_positive(self):
        result = seed(changed(observation(), 'time'))
        self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
        self.assertEqual(result.reasons[0].code, SeedReason.MATCH_TIME_UNKNOWN)

    def test_actual_missing_time_preserves_legacy_inactive_and_uncertainty(self):
        state = replace(normalize(payload()), time=None)
        self.assertFalse(state.active)
        result = seed(adapt_state(state))
        self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
        self.assertEqual(result.unknown_required, ('State.time',))
        self.assertEqual([r.code for r in result.reasons],
                         [SeedReason.MATCH_NOT_ACTIVE, SeedReason.MATCH_TIME_UNKNOWN])

    def test_optional_economy_level_and_match_id_unknown_do_not_gate(self):
        obs = observation()
        for name in ('gold', 'lh', 'gpm', 'xpm', 'level', 'match_id'):
            obs = changed(obs, name)
        result = seed(obs)
        self.assertEqual(result.eligibility, Eligibility.ELIGIBLE)
        for s in result.dimensions:
            if s.provenance.ref in ('State.gold','State.lh','State.gpm','State.xpm','State.level','State.match_id'):
                self.assertEqual(s.knownness, Knownness.UNKNOWN)
                self.assertIsNone(s.value)

    def test_zero_and_false_are_preserved_not_unknown(self):
        result = seed(adapt_state(normalize(payload(t=0, lh=0, gold=0, gpm=0, xpm=0))))
        self.assertEqual(result.eligibility, Eligibility.ELIGIBLE)
        dims = {s.provenance.ref:s for s in result.dimensions}
        for ref in ('State.time', 'State.gold', 'State.lh', 'State.gpm', 'State.xpm'):
            self.assertEqual(dims[ref].value, 0)
            self.assertEqual(dims[ref].knownness, Knownness.KNOWN)
        self.assertIs(dims['State.buyback'].value, False)
        self.assertEqual(dims['State.buyback'].knownness, Knownness.KNOWN)

    def test_deterministic_identity_and_input_order_independent(self):
        obs = observation()
        first = seed(obs)
        self.assertEqual(first, seed(obs))
        self.assertEqual(first, seed(replace(obs, scalars=tuple(reversed(obs.scalars)))))
        data = asdict(first)
        data.pop('seed_id')
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
        self.assertEqual(first.seed_id, 'runtime-context-seed-v1:' + hashlib.sha256(encoded).hexdigest())

    def test_lineage_changes_identity_but_not_runtime_semantics(self):
        obs = observation()
        original = seed(obs)
        for knowledge, player in [(replace(KNOWLEDGE, version='v2'), PLAYER),
                                  (KNOWLEDGE, replace(PLAYER, version='v2')),
                                  (replace(KNOWLEDGE, snapshot_id='other'), PLAYER)]:
            changed_seed = build_context_seed(obs, knowledge, player)
            self.assertNotEqual(original.seed_id, changed_seed.seed_id)
            self.assertEqual(original.dimensions, changed_seed.dimensions)
            self.assertEqual(original.eligibility, changed_seed.eligibility)
            self.assertEqual(original.reasons, changed_seed.reasons)

    def test_identity_includes_values_even_if_observation_id_is_reused(self):
        obs = observation()
        changed_obs = changed(obs, 'gold', 101)
        self.assertEqual(obs.observation_id, changed_obs.observation_id)
        self.assertNotEqual(seed(obs).seed_id, seed(changed_obs).seed_id)

    def test_input_preservation_and_deep_output_immutability(self):
        obs = observation()
        original = (asdict(obs), asdict(KNOWLEDGE), asdict(PLAYER))
        result = seed(obs)
        self.assertEqual(original, (asdict(obs), asdict(KNOWLEDGE), asdict(PLAYER)))
        with self.assertRaises(FrozenInstanceError): result.eligibility = Eligibility.INELIGIBLE
        with self.assertRaises(FrozenInstanceError): result.dimensions[0].value = False
        with self.assertRaises(FrozenInstanceError): result.knowledge.version = 'changed'
        with self.assertRaises(FrozenInstanceError): result.dimensions[0].provenance.ref = 'raw'
        self.assertIsInstance(result.dimensions, tuple)
        self.assertIsInstance(result.reasons, tuple)

    def test_missing_required_ref_is_unknown_without_fabricating_scalar(self):
        obs = observation()
        obs = replace(obs, scalars=tuple(s for s in obs.scalars if s.provenance.ref != 'State.alive'))
        result = seed(obs)
        self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
        self.assertEqual(result.unknown_required, ('State.alive',))
        self.assertNotIn('State.alive', {s.provenance.ref for s in result.dimensions})
        self.assertEqual(result.reasons[0].ref, 'State.alive')

    def test_boolean_fixture_facts_do_not_substitute_runtime_scalars(self):
        obs = RuntimeObservation('legacy', (ObservedFact('State.alive', Truth.YES, Freshness.FRESH),))
        result = seed(obs)
        self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
        self.assertEqual(result.unknown_required, result.eligibility_refs)
        self.assertEqual(result.dimensions, ())

    def test_schema_has_no_strategic_assessments_or_action(self):
        result = seed()
        self.assertEqual(set(asdict(result)), {'seed_id','observation_id','knowledge','player',
            'eligibility','eligibility_refs','reasons','dimensions','unknown_required','stale_required'})
        self.assertFalse(hasattr(result, 'options'))
        self.assertFalse(hasattr(result, 'next_action'))
        self.assertEqual({r.name for r in SeedReason}, {'MATCH_NOT_ACTIVE','NON_LOCAL_PLAYER','PLAYER_DEAD',
            'ACTIVE_UNKNOWN','LOCAL_UNKNOWN','ALIVE_UNKNOWN','HERO_UNKNOWN','MATCH_TIME_UNKNOWN','REQUIRED_STALE'})

    def test_end_to_end_offline_chain_stops_at_seed(self):
        state = normalize(payload())
        result = build_context_seed(adapt_state(state), KNOWLEDGE, PLAYER)
        self.assertIsInstance(result, DecisionContextSeed)
        self.assertEqual(result, build_context_seed(adapt_state(state), KNOWLEDGE, PLAYER))
        self.assertEqual(result.eligibility, Eligibility.ELIGIBLE)

    def test_actual_spectator_and_nonplaying_do_not_reconstruct_player_fields(self):
        for spectator in (True, False):
            data = payload()
            if spectator: data['player'] = {'team2': {'player0':data['player']}}
            else: data['player']['activity'] = 'menu'
            obs = adapt_state(normalize(data))
            result = seed(obs)
            self.assertEqual(result.dimensions, obs.scalars)
            self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
            self.assertIn(SeedReason.NON_LOCAL_PLAYER, [r.code for r in result.reasons])
            for name in ('hero','alive','level','gold','lh','gpm','xpm','deaths','buyback'):
                scalar = next(s for s in result.dimensions if s.provenance.ref=='State.'+name)
                self.assertEqual(scalar.knownness, Knownness.UNKNOWN)
                self.assertIsNone(scalar.value)
            self.assertNotIn(SeedReason.PLAYER_DEAD, [r.code for r in result.reasons])

    def test_blocker_wins_without_erasing_other_uncertainties(self):
        obs = changed(changed(observation(), 'alive', False), 'hero')
        result = seed(obs)
        self.assertEqual(result.eligibility, Eligibility.INELIGIBLE)
        self.assertEqual(result.unknown_required, ('State.hero',))
        self.assertEqual([r.code for r in result.reasons], [SeedReason.PLAYER_DEAD, SeedReason.HERO_UNKNOWN])

    def test_supplied_stale_required_facts_are_not_current_support(self):
        for value in (True, False, None):
            result = seed(changed(observation(), 'alive', value, freshness=Freshness.STALE))
            self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)
            self.assertEqual(result.stale_required, ('State.alive',))
            self.assertNotIn(SeedReason.PLAYER_DEAD, [r.code for r in result.reasons])
            self.assertIn(SeedReason.REQUIRED_STALE, [r.code for r in result.reasons])
        result = seed(changed(observation(), 'gold', 100, freshness=Freshness.STALE))
        self.assertEqual(result.eligibility, Eligibility.ELIGIBLE)
        self.assertEqual(next(s for s in result.dimensions if s.provenance.ref=='State.gold').freshness, Freshness.STALE)

    def test_missing_snapshot_does_not_reuse_history(self):
        seed(observation())
        result = seed(RuntimeObservation('empty-now', ()))
        self.assertEqual(result.dimensions, ())
        self.assertEqual(result.eligibility, Eligibility.INSUFFICIENT_DATA)

    def test_wrong_field_types_and_unsupported_dimensions_fail_explicitly(self):
        for name, value in [('active',1), ('time',True), ('hero',''), ('level','6')]:
            with self.assertRaisesRegex(ValueError, 'invalid_runtime_scalar_type'):
                seed(changed(observation(), name, value))
        extra = ScalarObservation(Provenance(Source.RUNTIME_OBSERVATION, 'State.mana'), Knownness.KNOWN, 339)
        with self.assertRaisesRegex(ValueError, 'unsupported_runtime_scalar'):
            seed(replace(observation(), scalars=observation().scalars+(extra,)))

    def test_boundary_and_versioned_lineage_are_validated(self):
        with self.assertRaises(TypeError): build_context_seed({}, KNOWLEDGE, PLAYER)
        with self.assertRaises(ValueError): seed(replace(observation(), observation_id=123))
        with self.assertRaises(TypeError): build_context_seed(observation(), PLAYER, KNOWLEDGE)
        for value in ('', None, 1):
            with self.assertRaises(ValueError): build_context_seed(observation(), replace(KNOWLEDGE, version=value), PLAYER)
            with self.assertRaises(ValueError): build_context_seed(observation(), KNOWLEDGE, replace(PLAYER, snapshot_id=value))

    def test_builder_performs_no_io_or_downstream_invocation(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        from coach02 import decision, farm_cycle, voice, vision
        obs = observation()
        expected = seed(obs)
        sinks = [(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (decision,'build_context'),(decision,'authorize_output'),(farm_cycle,'plan'),
            (voice.WindowsBackend,'play'),(vision,'capture_roi')]
        originals = [(owner,name,getattr(owner,name)) for owner,name in sinks]
        environment = os.environ
        forbidden = AssertionError('builder crossed seed boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual = build_context_seed(obs, KNOWLEDGE, PLAYER)
        self.assertEqual(actual, expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ, environment)

    def test_import_boundary_and_absence_from_live_paths(self):
        tree = ast.parse(Path(context_builder.__file__).read_text(encoding='utf-8'))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name for a in node.names)
            if isinstance(node, ast.ImportFrom): imports.add('.'*node.level+(node.module or ''))
        self.assertEqual(imports, {'dataclasses','enum','hashlib','json','.decision','.runtime_adapter'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        root = Path(context_builder.__file__).resolve().parent.parent
        for relative in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py',
                         'coach02/policy.py','coach02/runtime_adapter.py','coach02/farm_cycle.py'):
            other = ast.parse((root/relative).read_text(encoding='utf-8'))
            for node in ast.walk(other):
                if isinstance(node,(ast.Import,ast.ImportFrom,ast.Call)):
                    self.assertNotIn('context_builder',ast.unparse(node),relative)
                    self.assertNotIn('DecisionContextSeed',ast.unparse(node),relative)


if __name__ == '__main__': unittest.main()
