"""Deterministic occurrence/time contracts; synthetic ticks, no live observers."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import temporal_evidence as temporal
from coach02.decision import Freshness
from coach02.temporal_evidence import (
    FreshnessPolicy, ObservationMark, TemporalEvidenceStatus, TemporalQuery,
    TemporalSnapshot, TemporalStatus, TemporalTrackerState,
    evaluate_freshness, new_temporal_state, record_observations,
)


F = TemporalStatus.FRESH
S = TemporalStatus.STALE
N = TemporalStatus.NEVER_SEEN


def observed(tick=100, refs=('x',)):
    return record_observations(new_temporal_state('timeline-A', 'logical-domain'), refs, tick)


def snapshot(state, tick, ttl=10, ref='x', policy_id='test-policy'):
    # Explicit synthetic fixture policy. Production has no threshold default.
    return evaluate_freshness(state, tick, (TemporalQuery(ref, FreshnessPolicy(policy_id, ttl)),))


def core_freshness(status):
    """Test-only explicit adapter: no implicit NEVER_SEEN conversion."""
    if status is F:
        return Freshness.FRESH
    if status is S:
        return Freshness.STALE
    raise ValueError('unobserved_has_no_core_freshness')


class TemporalEvidenceTests(unittest.TestCase):
    def test_01_new_state_empty(self):
        state = new_temporal_state('a', 'c')
        self.assertEqual(state.marks, ())
        self.assertIsNone(state.last_tick)

    def test_02_first_observation(self):
        state = observed()
        self.assertEqual(state.marks, (ObservationMark('x', 100),))
        self.assertEqual(state.last_tick, 100)

    def test_03_equal_tick_allowed_returns_new_state(self):
        state = observed()
        next_state = record_observations(state, ('x',), 100)
        self.assertEqual(next_state, state)
        self.assertIsNot(next_state, state)
        self.assertEqual(snapshot(next_state, 100).entries[0].age_ticks, 0)

    def test_04_forward_tick_updates_only_recorded_refs(self):
        state = record_observations(observed(refs=('x', 'y')), ('x',), 108)
        self.assertEqual(state.marks, (ObservationMark('x', 108), ObservationMark('y', 100)))
        self.assertEqual(state.last_tick, 108)

    def test_05_backward_record_rejected(self):
        state = observed()
        with self.assertRaisesRegex(ValueError, 'decreasing_tick'):
            record_observations(state, ('y',), 99)
        self.assertEqual(state, observed())

    def test_06_backward_evaluation_rejected(self):
        with self.assertRaisesRegex(ValueError, 'decreasing_tick'):
            snapshot(observed(), 99)

    def test_07_fresh_immediately(self):
        entry = snapshot(observed(), 100).entries[0]
        self.assertIs(entry.status, F)
        self.assertEqual((entry.last_observed_tick, entry.age_ticks), (100, 0))

    def test_08_fresh_at_exact_boundary(self):
        entry = snapshot(observed(), 110).entries[0]
        self.assertIs(entry.status, F)
        self.assertEqual(entry.age_ticks, 10)

    def test_09_stale_just_after_boundary(self):
        entry = snapshot(observed(), 111).entries[0]
        self.assertIs(entry.status, S)
        self.assertEqual(entry.age_ticks, 11)

    def test_10_zero_ttl(self):
        self.assertIs(snapshot(observed(), 100, ttl=0).entries[0].status, F)
        self.assertIs(snapshot(observed(), 101, ttl=0).entries[0].status, S)

    def test_11_never_seen_distinct_with_no_invented_times(self):
        entry = snapshot(observed(), 120, ref='unseen').entries[0]
        self.assertIs(entry.status, N)
        self.assertIsNone(entry.last_observed_tick)
        self.assertIsNone(entry.age_ticks)
        self.assertEqual((entry.ref, entry.policy_id, entry.max_age_ticks), ('unseen', 'test-policy', 10))
        self.assertIs(snapshot(observed(), 120).entries[0].status, S)

    def test_12_no_default_policy(self):
        with self.assertRaises(TypeError):
            FreshnessPolicy('p')
        with self.assertRaises(TypeError):
            TemporalQuery('x')
        with self.assertRaises(TypeError):
            evaluate_freshness(observed(), 100)
        with self.assertRaises(TypeError):
            TemporalQuery('x', None)
        self.assertIs(inspect.signature(FreshnessPolicy).parameters['max_age_ticks'].default,
                      inspect.Parameter.empty)

    def test_13_policy_result_and_identity(self):
        state = observed()
        tight = snapshot(state, 111, ttl=10)
        loose = snapshot(state, 111, ttl=11)
        renamed = snapshot(state, 111, ttl=11, policy_id='another-policy')
        self.assertIs(tight.entries[0].status, S)
        self.assertIs(loose.entries[0].status, F)
        self.assertNotEqual(tight.snapshot_id, loose.snapshot_id)
        self.assertNotEqual(loose.snapshot_id, renamed.snapshot_id)
        self.assertEqual(tight.tracker_state_id, loose.tracker_state_id)
        self.assertEqual(tight.entries[0].last_observed_tick, loose.entries[0].last_observed_tick)

    def test_14_atomic_batch(self):
        state = observed(refs=('observer.enemy_mid.visible', 'observer.coverage.bot'))
        self.assertEqual(len(state.marks), 2)
        self.assertEqual({m.last_observed_tick for m in state.marks}, {100})

    def test_15_bad_ref_atomic_failure(self):
        state = observed()
        before = asdict(state)
        for bad in ('', '  ', None, 1, True, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    record_observations(state, ('new-valid-ref', bad), 110)
                self.assertEqual(asdict(state), before)

    def test_16_duplicate_refs_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_ref'):
            record_observations(observed(), ('x', 'x'), 100)

    def test_17_batch_order_independent(self):
        a, b = observed(refs=('z', 'a')), observed(refs=('a', 'z'))
        self.assertEqual(a, b)
        self.assertEqual(a.state_id, b.state_id)
        self.assertEqual(tuple(m.ref for m in a.marks), ('a', 'z'))

    def test_18_query_order_independent(self):
        state = observed(refs=('z', 'a'))
        queries = (TemporalQuery('z', FreshnessPolicy('p', 1)),
                   TemporalQuery('a', FreshnessPolicy('p', 1)))
        a = evaluate_freshness(state, 101, queries)
        b = evaluate_freshness(state, 101, tuple(reversed(queries)))
        self.assertEqual(a, b)
        self.assertEqual(a.snapshot_id, b.snapshot_id)
        self.assertEqual(tuple(e.ref for e in a.entries), ('a', 'z'))

    def test_19_multiple_policies_per_ref(self):
        queries = (TemporalQuery('x', FreshnessPolicy('loose', 20)),
                   TemporalQuery('x', FreshnessPolicy('tight', 1)))
        result = evaluate_freshness(observed(), 110, queries)
        self.assertEqual(tuple(e.status for e in result.entries), (F, S))
        self.assertEqual(tuple(e.policy_id for e in result.entries), ('loose', 'tight'))
        self.assertEqual(result, evaluate_freshness(observed(), 110, tuple(reversed(queries))))

    def test_20_new_timeline_empty(self):
        self.assertEqual(new_temporal_state('B', 'logical-domain').marks, ())
        self.assertIsNone(new_temporal_state('B', 'logical-domain').last_tick)

    def test_21_timeline_no_leak(self):
        a = observed()
        b = new_temporal_state('B', a.clock_id)
        self.assertIs(snapshot(b, 100).entries[0].status, N)
        self.assertNotEqual(a.state_id, b.state_id)
        self.assertEqual(a.marks, (ObservationMark('x', 100),))

    def test_22_clock_and_timeline_binding(self):
        state = record_observations(new_temporal_state('opaque-session', 'opaque-unit'), ('x',), -5)
        result = snapshot(state, -4)
        self.assertEqual((result.timeline_id, result.clock_id), ('opaque-session', 'opaque-unit'))
        self.assertEqual(result.tracker_state_id, state.state_id)
        self.assertEqual(result.evaluated_at_tick, -4)
        self.assertNotEqual(new_temporal_state('a', 'c1').state_id, new_temporal_state('a', 'c2').state_id)
        self.assertNotEqual(new_temporal_state('a', 'c1').state_id, new_temporal_state('b', 'c1').state_id)

    def test_23_state_determinism_and_observation_identity(self):
        self.assertEqual(observed().state_id, observed().state_id)
        self.assertNotEqual(observed().state_id, observed(101).state_id)
        self.assertNotEqual(observed().state_id, observed(refs=('y',)).state_id)
        self.assertNotEqual(observed().state_id, record_observations(observed(), (), 101).state_id)
        value = asdict(observed())
        canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        self.assertEqual(observed().state_id,
                         temporal.RULESET + ':state:' + hashlib.sha256(canonical).hexdigest())

    def test_24_snapshot_determinism_and_input_binding(self):
        a = snapshot(observed(), 110)
        self.assertEqual(a.snapshot_id, snapshot(observed(), 110).snapshot_id)
        self.assertNotEqual(a.snapshot_id, snapshot(observed(), 109).snapshot_id)
        # Even an unqueried occurrence changes the snapshot's state binding.
        self.assertNotEqual(a.snapshot_id, snapshot(observed(refs=('x', 'y')), 110).snapshot_id)
        self.assertNotEqual(snapshot(observed(), 100, ref='never').snapshot_id,
                            snapshot(observed(), 100, ttl=11, ref='never').snapshot_id)

    def test_25_immutable_contracts(self):
        values = (observed(), ObservationMark('x', 1), FreshnessPolicy('p', 1),
                  TemporalQuery('x', FreshnessPolicy('p', 1)),
                  snapshot(observed(), 100), snapshot(observed(), 100).entries[0])
        for value in values:
            with self.subTest(contract=type(value).__name__):
                name = fields(value)[0].name
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, name, getattr(value, name))
        self.assertIsInstance(observed().marks, tuple)
        self.assertIsInstance(snapshot(observed(), 100).entries, tuple)

    def test_26_input_immutability(self):
        state = observed()
        refs = ('z', 'a')
        queries = (TemporalQuery('z', FreshnessPolicy('p', 10)),)
        before = (asdict(state), refs, tuple(asdict(q) for q in queries))
        next_state = record_observations(state, refs, 101)
        evaluate_freshness(next_state, 103, queries)
        self.assertEqual(before, (asdict(state), refs, tuple(asdict(q) for q in queries)))

    def test_27_state_schema_occurrences_only(self):
        self.assertEqual({f.name for f in fields(ObservationMark)}, {'ref', 'last_observed_tick'})
        self.assertEqual({f.name for f in fields(TemporalTrackerState)},
                         {'timeline_id', 'clock_id', 'last_tick', 'marks'})
        with self.assertRaises(TypeError):
            ObservationMark('x', 100, value=True)

    def test_28_silence_does_not_record(self):
        state = observed()
        later = record_observations(state, (), 120)
        self.assertEqual(later.marks, state.marks)
        self.assertEqual(later.last_tick, 120)
        self.assertIs(snapshot(later, 120, ref='new').entries[0].status, N)

    def test_29_silence_ages_without_refresh_fixed_policy(self):
        state = observed()
        self.assertEqual(tuple(snapshot(state, t).entries[0].status for t in (100, 110, 111, 120)),
                         (F, F, S, S))
        self.assertEqual(state.last_tick, 100)

    def test_30_stale_preserves_last_observed(self):
        entry = snapshot(observed(), 1000).entries[0]
        self.assertIs(entry.status, S)
        self.assertEqual((entry.last_observed_tick, entry.age_ticks), (100, 900))

    def test_31_reobservation_refreshes(self):
        state = record_observations(observed(), ('x',), 121)
        entry = snapshot(state, 121).entries[0]
        self.assertIs(entry.status, F)
        self.assertEqual((entry.last_observed_tick, entry.age_ticks), (121, 0))

    def test_32_no_semantic_fields(self):
        forbidden = {'truth', 'value', 'threat', 'threat_state', 'risk', 'safety', 'availability',
                     'hero', 'items', 'route', 'action', 'recommendation'}
        for cls in (ObservationMark, TemporalTrackerState, FreshnessPolicy, TemporalQuery,
                    TemporalEvidenceStatus, TemporalSnapshot):
            self.assertFalse({f.name for f in fields(cls)} & forbidden)

    def test_33_no_gameplay_interpretation(self):
        tree = ast.parse(inspect.getsource(temporal))
        forbidden = {'hero', 'items', 'level', 'gold', 'gpm', 'inventory', 'missing',
                     'safe', 'danger', 'available', 'route', 'action', 'match_id'}
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)))
        self.assertEqual(set(TemporalStatus), {N, F, S})
        state = observed(refs=('enemy.visible_away', 'irrelevant', 'resource.absent'))
        result = evaluate_freshness(state, 111, tuple(TemporalQuery(m.ref, FreshnessPolicy('same', 10))
                                                   for m in state.marks))
        self.assertEqual(tuple(e.status for e in result.entries), (S, S, S))
        self.assertEqual(tuple(e.ref for e in result.entries), tuple(m.ref for m in state.marks))

    def test_34_no_namespace_ttl(self):
        refs = ('safety.threat', 'coverage', 'hero.anything', 'arbitrary')
        state = observed(refs=refs)
        result = evaluate_freshness(state, 101, tuple(TemporalQuery(ref, FreshnessPolicy('zero', 0)) for ref in refs))
        self.assertTrue(all(e.status is S and e.max_age_ticks == 0 for e in result.entries))
        tree = ast.parse(inspect.getsource(temporal))
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr in ('startswith', 'endswith', 'split') for n in ast.walk(tree)))

    def test_35_no_clock_imports_or_reads(self):
        tree = ast.parse(inspect.getsource(temporal))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imports.add(node.module)
        self.assertEqual(imports, {'dataclasses', 'enum', 'hashlib', 'json'})
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & {'eval', 'exec', '__import__', 'open', 'getattr'})

    def test_36_pure_operations_no_sinks_or_mutable_globals(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        before_globals = dict(vars(temporal))
        before = observed()
        expected = snapshot(record_observations(before, ('x', 'y'), 105), 116)
        sinks = [(builtins, 'open'), (io, 'open'), (os, 'open'), (os, 'getenv'), (os, 'system'),
                 (socket, 'socket'), (socket, 'getaddrinfo'), (socket, 'create_connection'),
                 (sqlite3, 'connect'), (subprocess, 'Popen'), (time, 'time'),
                 (time, 'monotonic'), (time, 'perf_counter'), (random, 'random'), (uuid, 'uuid4')]
        forbidden = AssertionError('temporal purity violation')
        class NoEnvironment(dict):
            def __getitem__(self, key): raise forbidden
            def get(self, *args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner, name in sinks:
                stack.enter_context(patch.object(owner, name, side_effect=forbidden))
            stack.enter_context(patch.object(os, 'environ', NoEnvironment()))
            actual = snapshot(record_observations(new_temporal_state('timeline-A', 'logical-domain'),
                                                  ('x', 'y'), 105), 116)
            identity = actual.snapshot_id
        self.assertEqual(actual, expected)
        self.assertEqual(identity, expected.snapshot_id)
        self.assertEqual(before, observed())
        self.assertEqual(before_globals, vars(temporal))
        for name, value in vars(temporal).items():
            if not name.startswith('__'):
                self.assertNotIsInstance(value, (dict, list, set, bytearray, TemporalTrackerState))
        tree = ast.parse(inspect.getsource(temporal))
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))

    def test_37_core_compatibility_test_only(self):
        self.assertIs(core_freshness(F), Freshness.FRESH)
        self.assertIs(core_freshness(S), Freshness.STALE)
        with self.assertRaises(ValueError):
            core_freshness(N)
        self.assertEqual(set(Freshness), {Freshness.FRESH, Freshness.STALE})

    def test_38_frozen_core_hashes_and_no_backward_import(self):
        root = Path(temporal.__file__).resolve().parent.parent
        accepted = FROZEN_HASHES
        for rel, sha in accepted:
            with self.subTest(file=rel):
                self.assertEqual(hashlib.sha256((root / rel).read_bytes()).hexdigest().upper(), sha)
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/threat_observation.py',
                                           'coach02/threat_absence_observation.py',
                                           'coach02/strategic_coverage.py', 'coach02/option_exposure.py'})
        allowed_contracts = frozenset(('TemporalEvidenceStatus', 'TemporalSnapshot', 'TemporalStatus'))
        operations = frozenset({'project_event_time', 'new_temporal_state',
                                'record_observations', 'evaluate_freshness'})

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            live = relative_path == 'coach02/live_runtime_v01.py'
            live_contracts = frozenset(('TemporalTrackerState', 'TemporalSnapshot', 'FreshnessPolicy', 'TemporalQuery', 'new_temporal_state', 'record_observations', 'evaluate_freshness'))
            errors = []
            blocked_calls = set() if live else set(operations)
            if live:
                blocked_calls.update({'getattr', 'eval', 'exec', '__import__'})
            if consumer:
                blocked_calls.update(allowed_contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'temporal_evidence' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('temporal_evidence' in (node.module or '').split('.') or
                               any(a.name == 'temporal_evidence' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'temporal_evidence') or
                                        (node.level == 0 and node.module == 'coach02.temporal_evidence'))
                        if not (consumer or live) or not exact_module:
                            errors.append('unauthorized production consumer or import path')
                        for alias in node.names:
                            if alias.name not in (live_contracts if live else allowed_contracts):
                                errors.append('non-contract symbol import')
                            elif not live:
                                blocked_calls.add(alias.asname or alias.name)
            # Follow simple local aliases too; importing a contract does not grant
            # permission to instantiate it through a renamed factory reference.
            changed = True
            while changed:
                changed = False
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        value = node.value
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        if isinstance(value, ast.Name) and value.id in blocked_calls:
                            for target in targets:
                                if isinstance(target, ast.Name) and target.id not in blocked_calls:
                                    blocked_calls.add(target.id)
                                    changed = True
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = ast.unparse(node.func)
                if (name in blocked_calls or
                        (not live and isinstance(node.func, ast.Attribute) and node.func.attr in operations)):
                    errors.append('constructor or orchestration call')
                if name in importers:
                    if consumer or live or any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                       and 'temporal_evidence' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .temporal_evidence import TemporalEvidenceStatus',
            'from coach02.temporal_evidence import TemporalEvidenceStatus as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.temporal_evidence as foundation',
            'from coach02 import temporal_evidence as foundation',
            'from .temporal_evidence import *',
            'from ..temporal_evidence import TemporalEvidenceStatus',
            'from .temporal_evidence import TemporalEvidenceStatus as Contract\nContract()',
            'from .temporal_evidence import TemporalEvidenceStatus as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.temporal_evidence')",
            "from importlib import import_module as load\nload('coach02.temporal_evidence')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .temporal_evidence import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.temporal_evidence')"
        self.assertTrue(violations(dynamic, 'coach02/arbitrary_future_consumer.py'))
        live_path = 'coach02/live_runtime_v01.py'
        live_source = 'from .temporal_evidence import TemporalTrackerState as Public\nPublic()'
        self.assertEqual(violations(live_source, live_path), [])
        self.assertTrue(violations(live_source, 'coach02/arbitrary_future_consumer.py'))
        for bad in ('from .temporal_evidence import *',
                    'import coach02.temporal_evidence as foundation',
                    'from ..temporal_evidence import TemporalTrackerState',
                    'from .temporal_evidence import PrivateSymbol',
                    "import importlib as loader\nloader.import_module('coach02.temporal_evidence')"):
            self.assertTrue(violations(bad, live_path))
        paths = [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py'))
        for path in paths:
            if path.relative_to(root).as_posix() == 'coach02/temporal_evidence.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))

    def test_39_adversarial_A_ages_out(self):
        state = observed(100)
        self.assertIs(snapshot(state, 110).entries[0].status, F)
        self.assertIs(snapshot(state, 111).entries[0].status, S)
        self.assertEqual(state, observed(100))

    def test_40_adversarial_B_refresh_before_expiry(self):
        state = record_observations(observed(100), ('x',), 108)
        entry = snapshot(state, 115).entries[0]
        self.assertIs(entry.status, F)
        self.assertEqual(entry.age_ticks, 7)

    def test_41_adversarial_C_stale_then_reobserved(self):
        state = record_observations(observed(100), (), 120)
        self.assertIs(snapshot(state, 120).entries[0].status, S)
        next_state = record_observations(state, ('x',), 121)
        self.assertIs(snapshot(next_state, 121).entries[0].status, F)
        self.assertEqual(state.marks[0].last_observed_tick, 100)

    def test_42_adversarial_D_unrelated_never_seen(self):
        state = observed(refs=('known',))
        self.assertIs(snapshot(state, 100, ref='unrelated').entries[0].status, N)

    def test_43_adversarial_E_new_session(self):
        state_a = observed()
        state_b = new_temporal_state('timeline-B', state_a.clock_id)
        state_b = record_observations(state_b, (), -100)
        self.assertIs(snapshot(state_b, -100).entries[0].status, N)
        self.assertEqual(state_a.marks, observed().marks)

    def test_44_adversarial_F_equal_tick_no_artificial_age(self):
        state = observed()
        first = snapshot(state, 100, ttl=0)
        for refs in ((), ('x',), ()):
            state = record_observations(state, refs, 100)
            result = snapshot(state, 100, ttl=0)
            self.assertEqual(result, first)
            self.assertEqual(result.snapshot_id, first.snapshot_id)

    def test_45_tick_validation_and_negative_time(self):
        for invalid in (True, False, 1.0, '100', None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError): record_observations(observed(), (), invalid)
                with self.assertRaises(TypeError): snapshot(observed(), invalid)
                with self.assertRaises(TypeError): ObservationMark('x', invalid)
        state = observed(-100)
        self.assertIs(snapshot(state, -90).entries[0].status, F)
        self.assertIs(snapshot(state, -89).entries[0].status, S)
        self.assertEqual(snapshot(observed(0), 0).entries[0].last_observed_tick, 0)
        self.assertIs(snapshot(observed(0), 0).entries[0].status, F)

    def test_46_policy_and_identifier_validation(self):
        for value in (True, False, 1.0, '1', None):
            with self.assertRaises(TypeError): FreshnessPolicy('p', value)
        with self.assertRaises(ValueError): FreshnessPolicy('p', -1)
        for value in ('', '  ', None, 1):
            with self.assertRaises(ValueError): new_temporal_state(value, 'c')
            with self.assertRaises(ValueError): new_temporal_state('a', value)
            with self.assertRaises(ValueError): FreshnessPolicy(value, 1)
            with self.assertRaises(ValueError): TemporalQuery(value, FreshnessPolicy('p', 1))
        # Opaque text is not trimmed or reinterpreted.
        state = record_observations(new_temporal_state(' a ', ' c '), (' x ',), 0)
        self.assertEqual((state.timeline_id, state.clock_id, state.marks[0].ref), (' a ', ' c ', ' x '))

    def test_47_invalid_or_noncanonical_state(self):
        with self.assertRaises(TypeError): TemporalTrackerState('a', 'c', True)
        with self.assertRaises(TypeError): TemporalTrackerState('a', 'c', 1, [])
        with self.assertRaises(TypeError): TemporalTrackerState('a', 'c', 1, ('x',))
        with self.assertRaises(ValueError): TemporalTrackerState('a', 'c', None, (ObservationMark('x', 0),))
        with self.assertRaises(ValueError): TemporalTrackerState('a', 'c', 0, (ObservationMark('x', 1),))
        with self.assertRaises(ValueError): TemporalTrackerState('a', 'c', 1, (ObservationMark('x', 1),)*2)
        a = TemporalTrackerState('a', 'c', 1, (ObservationMark('z', 1), ObservationMark('a', 0)))
        b = TemporalTrackerState('a', 'c', 1, tuple(reversed(a.marks)))
        self.assertEqual(a, b)
        self.assertEqual(a.state_id, b.state_id)
        with self.assertRaises(TypeError): record_observations(None, (), 1)
        with self.assertRaises(TypeError): evaluate_freshness(None, 1, ())
        with self.assertRaises(TypeError): record_observations(observed(), ['x'], 100)

    def test_48_queries_unambiguous_and_subset(self):
        state = observed(refs=('x', 'y'))
        q = TemporalQuery('x', FreshnessPolicy('p', 1))
        with self.assertRaisesRegex(ValueError, 'duplicate_query'):
            evaluate_freshness(state, 100, (q, q))
        with self.assertRaisesRegex(ValueError, 'conflicting_policy_id'):
            evaluate_freshness(state, 100, (q, TemporalQuery('y', FreshnessPolicy('p', 2))))
        with self.assertRaises(TypeError): evaluate_freshness(state, 100, [q])
        with self.assertRaises(TypeError): evaluate_freshness(state, 100, ('x',))
        self.assertEqual(evaluate_freshness(state, 100, ()).entries, ())
        self.assertEqual(len(evaluate_freshness(state, 100, (q,)).entries), 1)
        self.assertEqual(len(state.marks), 2)

    def test_49_evaluation_is_read_commit_high_water_explicitly(self):
        state = observed()
        snapshot(state, 120)
        self.assertEqual(state.last_tick, 100)
        # No hidden evaluation history. Same immutable input remains repeatable.
        self.assertIs(snapshot(state, 110).entries[0].status, F)
        advanced = record_observations(state, (), 120)
        self.assertEqual(advanced.marks, state.marks)
        with self.assertRaises(ValueError): snapshot(advanced, 110)
        with self.assertRaises(ValueError): record_observations(advanced, ('x',), 110)

    def test_50_policy_reassessment_is_not_reobservation(self):
        state = record_observations(observed(), (), 120)
        stale = snapshot(state, 120, ttl=10, policy_id='narrow')
        fresh = snapshot(state, 120, ttl=20, policy_id='wide')
        self.assertIs(stale.entries[0].status, S)
        self.assertIs(fresh.entries[0].status, F)
        self.assertEqual(stale.tracker_state_id, fresh.tracker_state_id)
        self.assertEqual(stale.entries[0].last_observed_tick, 100)
        self.assertEqual(fresh.entries[0].last_observed_tick, 100)
        self.assertNotEqual(stale.snapshot_id, fresh.snapshot_id)


# Accepted OFFLINE_CORE_V01 freeze; immutable regression anchors, no runtime IO.
FROZEN_HASHES = (
    ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'),
    ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'),
    ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'),
    ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'),
    ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'),
    ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'),
    ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'),
    ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'),
    ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'),
    ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'),
    ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'),
    ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'),
)


if __name__ == '__main__':
    unittest.main()
