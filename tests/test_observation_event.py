"""Synthetic neutral envelopes, explicit projection, and test-only tracker bridge."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import observation_event as envelope
from coach02.observation_event import (
    ClockStamp, ObservationEvent, ObservationSource, ObservationTimingPolicy,
    TemporalProjection, TimestampBasis, project_event_time,
)
from coach02.temporal_evidence import new_temporal_state, record_observations


SOURCE = TimestampBasis.SOURCE
RECEIPT = TimestampBasis.RECEIPT


def event(**changes):
    args = dict(timeline_id='A', source=ObservationSource('producer-1', 'opaque-kind', 'schema-v1'),
                refs=('b', 'a'), source_stamp=ClockStamp('clock', 100), receipt_stamp=ClockStamp('clock', 103))
    args.update(changes)
    return ObservationEvent(**args)


def policy(basis, policy_id='fixture-policy'):
    return ObservationTimingPolicy(policy_id, basis)


def bridge_for_test(state, projection):
    """Only tests feed Temporal Evidence. Both bindings are mandatory here."""
    if state.timeline_id != projection.timeline_id:
        raise ValueError('timeline_mismatch')
    if state.clock_id != projection.selected_clock_id:
        raise ValueError('clock_mismatch')
    return record_observations(state, projection.refs, projection.selected_tick)


def pure_exercise(sinks):
    expected_event = event()
    expected = project_event_time(expected_event, policy(SOURCE), 'clock')
    expected_ids = expected_event.event_id, expected.projection_id
    with ExitStack() as stack:
        for owner, name in sinks:
            stack.enter_context(patch.object(owner, name, side_effect=AssertionError('impure envelope')))
        actual_event = event()
        actual = project_event_time(actual_event, policy(SOURCE), 'clock')
        actual_ids = actual_event.event_id, actual.projection_id
    return (actual_event, actual, actual_ids), (expected_event, expected, expected_ids)


class ObservationEventTests(unittest.TestCase):
    def test_01_valid_source(self):
        source = ObservationSource('p', 'kind', 'schema')
        self.assertEqual(asdict(source), dict(source_id='p', source_kind='kind', schema_id='schema'))

    def test_02_source_fields_opaque(self):
        source = ObservationSource(' Producer ', ' arbitrary.Category ', ' v1 / schema ')
        self.assertEqual(source.source_id, ' Producer ')
        self.assertEqual(source.source_kind, ' arbitrary.Category ')
        self.assertEqual(source.schema_id, ' v1 / schema ')
        self.assertEqual(ObservationSource(' ', ' ', ' ').source_kind, ' ')
        for kind in ('GSI', 'VISION', 'unrecognized', 'coverage'):
            value = event(source=replace(source, source_kind=kind))
            self.assertEqual(project_event_time(value, policy(SOURCE)).selected_tick, 100)

    def test_03_valid_clock_stamp(self):
        self.assertEqual(asdict(ClockStamp('domain', 42)), dict(clock_id='domain', tick=42))

    def test_04_negative_tick(self):
        value = event(source_stamp=ClockStamp('clock', -100), receipt_stamp=ClockStamp('clock', -90))
        self.assertEqual(project_event_time(value, policy(SOURCE)).selected_tick, -100)

    def test_05_bool_tick_rejected(self):
        for value in (True, False):
            with self.assertRaises(TypeError): ClockStamp('clock', value)

    def test_06_float_tick_rejected(self):
        for value in (1.0, -1.5, float('nan'), float('inf')):
            with self.assertRaises(TypeError): ClockStamp('clock', value)

    def test_07_event_requires_timeline(self):
        for value in ('', None, 1, True):
            with self.assertRaises(ValueError): event(timeline_id=value)
        with self.assertRaises(TypeError):
            ObservationEvent(source=event().source, refs=(), receipt_stamp=ClockStamp('c', 0))

    def test_08_event_requires_source(self):
        for value in (None, 'producer', {}, 1):
            with self.assertRaises(TypeError): event(source=value)
        with self.assertRaises(TypeError):
            ObservationEvent(timeline_id='A', refs=(), receipt_stamp=ClockStamp('c', 0))

    def test_09_receipt_required(self):
        for value in (None, 103, {'clock_id':'clock', 'tick':103}):
            with self.assertRaises(TypeError): event(receipt_stamp=value)
        with self.assertRaises(TypeError):
            ObservationEvent(timeline_id='A', source=event().source, refs=())

    def test_10_source_stamp_optional(self):
        value = ObservationEvent('A', event().source, ('x',), ClockStamp('clock', 0))
        self.assertIsNone(value.source_stamp)
        self.assertEqual(value.receipt_stamp, ClockStamp('clock', 0))

    def test_11_valid_refs(self):
        value = event(refs=('observer.enemy_mid.visible', 'observer.coverage.bot'))
        self.assertEqual(value.refs, ('observer.coverage.bot', 'observer.enemy_mid.visible'))

    def test_12_bad_ref_atomic_construction_failure(self):
        for bad in ('', None, True, 1, {}, []):
            refs = ('valid', bad)
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): event(refs=refs)
                self.assertEqual(refs[0], 'valid')
                self.assertIs(refs[1], bad)
        self.assertEqual(event(refs=('valid',)).refs, ('valid',))

    def test_13_duplicate_ref_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_ref'):
            event(refs=('x', 'x'))

    def test_14_tuple_required(self):
        for value in (['x'], {'x'}, 'x', None):
            with self.assertRaises(TypeError): event(refs=value)

    def test_15_canonical_ref_order(self):
        self.assertEqual(event(refs=('c', 'a', 'b')).refs, ('a', 'b', 'c'))

    def test_16_inputs_immutable(self):
        refs = ('z', 'a')
        source = ObservationSource('p', 'k', 's')
        stamp = ClockStamp('clock', 99)
        before = (refs, asdict(source), asdict(stamp))
        value = event(refs=refs, source=source, source_stamp=stamp)
        project_event_time(value, policy(SOURCE))
        self.assertEqual(before, (refs, asdict(source), asdict(stamp)))
        self.assertEqual(refs, ('z', 'a'))

    def test_17_event_frozen(self):
        with self.assertRaises(FrozenInstanceError): event().timeline_id = 'B'
        with self.assertRaises(TypeError): event().refs[0] = 'new'

    def test_18_source_frozen(self):
        with self.assertRaises(FrozenInstanceError): event().source.source_id = 'new'

    def test_19_stamp_frozen(self):
        with self.assertRaises(FrozenInstanceError): event().receipt_stamp.tick = 200

    def test_20_same_clock_source_before_receipt(self):
        value = event()
        self.assertEqual((value.source_stamp.tick, value.receipt_stamp.tick), (100, 103))

    def test_21_same_clock_equal_ticks(self):
        value = event(receipt_stamp=ClockStamp('clock', 100))
        self.assertEqual(value.source_stamp, value.receipt_stamp)

    def test_22_same_clock_future_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source_after_receipt_on_same_clock'):
            event(source_stamp=ClockStamp('clock', 105), receipt_stamp=ClockStamp('clock', 100))

    def test_23_different_clock_numbers_incomparable(self):
        value = event(source_stamp=ClockStamp('game', 10**30), receipt_stamp=ClockStamp('other', -10**30))
        self.assertEqual(project_event_time(value, policy(SOURCE)).selected_tick, 10**30)
        self.assertEqual(project_event_time(value, policy(RECEIPT)).selected_tick, -10**30)

    def test_24_no_default_basis_or_policy(self):
        with self.assertRaises(TypeError): ObservationTimingPolicy('p')
        with self.assertRaises(TypeError): project_event_time(event())
        with self.assertRaises(TypeError): project_event_time(event(), None)
        self.assertIs(inspect.signature(ObservationTimingPolicy).parameters['basis'].default, inspect.Parameter.empty)

    def test_25_source_selected(self):
        value = event(receipt_stamp=ClockStamp('receipt-domain', 5000))
        result = project_event_time(value, policy(SOURCE))
        self.assertEqual((result.selected_clock_id, result.selected_tick), ('clock', 100))
        self.assertEqual((result.event_id, result.timeline_id, result.source_id, result.refs),
                         (value.event_id, 'A', 'producer-1', ('a', 'b')))
        self.assertIs(result.timestamp_basis, SOURCE)

    def test_26_receipt_selected(self):
        result = project_event_time(event(receipt_stamp=ClockStamp('receipt-domain', 5000)), policy(RECEIPT))
        self.assertEqual((result.selected_clock_id, result.selected_tick), ('receipt-domain', 5000))
        self.assertIs(result.timestamp_basis, RECEIPT)

    def test_27_source_missing_no_fallback(self):
        with self.assertRaisesRegex(ValueError, 'source_stamp_required_for_source_basis'):
            project_event_time(event(source_stamp=None), policy(SOURCE))

    def test_28_expected_clock_matches(self):
        self.assertEqual(project_event_time(event(), policy(SOURCE), 'clock').selected_tick, 100)

    def test_29_expected_clock_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'selected_clock_mismatch'):
            project_event_time(event(), policy(SOURCE), 'other')

    def test_30_projection_and_policy_frozen(self):
        result = project_event_time(event(), policy(SOURCE))
        with self.assertRaises(FrozenInstanceError): result.selected_tick = 103
        with self.assertRaises(FrozenInstanceError): policy(SOURCE).basis = RECEIPT
        self.assertIsInstance(result.refs, tuple)

    def test_31_event_deterministic_identity(self):
        value = event()
        self.assertEqual(value.event_id, event().event_id)
        encoded = json.dumps(asdict(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(value.event_id, envelope.RULESET+':event:'+hashlib.sha256(encoded).hexdigest())

    def test_32_projection_deterministic_identity(self):
        a, b = project_event_time(event(), policy(SOURCE)), project_event_time(event(), policy(SOURCE))
        self.assertEqual(a, b)
        self.assertEqual(a.projection_id, b.projection_id)
        encoded = json.dumps(asdict(a), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(a.projection_id, envelope.RULESET+':projection:'+hashlib.sha256(encoded).hexdigest())

    def test_33_ref_order_not_identity(self):
        a, b = event(refs=('x', 'y')), event(refs=('y', 'x'))
        self.assertEqual(a.event_id, b.event_id)
        self.assertEqual(project_event_time(a, policy(SOURCE)).projection_id,
                         project_event_time(b, policy(SOURCE)).projection_id)

    def test_34_every_source_field_in_identity(self):
        value = event()
        for name in ('source_id', 'source_kind', 'schema_id'):
            with self.subTest(field=name):
                changed = event(source=replace(value.source, **{name:'different'}))
                self.assertNotEqual(value.event_id, changed.event_id)

    def test_35_timeline_in_identity(self):
        self.assertNotEqual(event().event_id, event(timeline_id='B').event_id)

    def test_36_source_stamp_in_identity(self):
        self.assertNotEqual(event().event_id, event(source_stamp=ClockStamp('clock', 99)).event_id)
        self.assertNotEqual(event().event_id, event(source_stamp=ClockStamp('other', 100)).event_id)
        self.assertNotEqual(event().event_id, event(source_stamp=None).event_id)

    def test_37_receipt_stamp_in_identity(self):
        self.assertNotEqual(event().event_id, event(receipt_stamp=ClockStamp('clock', 104)).event_id)
        self.assertNotEqual(event().event_id, event(receipt_stamp=ClockStamp('other', 103)).event_id)

    def test_38_policy_and_basis_in_projection_identity(self):
        value = event(receipt_stamp=ClockStamp('clock', 100))
        a = project_event_time(value, policy(SOURCE, 'p'))
        b = project_event_time(value, policy(SOURCE, 'q'))
        c = project_event_time(value, policy(RECEIPT, 'p'))
        self.assertEqual(a.selected_tick, c.selected_tick)
        self.assertEqual(len({a.projection_id, b.projection_id, c.projection_id}), 3)
        self.assertEqual(a.event_id, c.event_id)

    def test_39_no_wall_clock(self):
        import time
        a, b = pure_exercise([(time,'time'), (time,'monotonic'), (time,'perf_counter')])
        self.assertEqual(a, b)
        tree = ast.parse(inspect.getsource(envelope))
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import): imports.update(a.name for a in n.names)
            if isinstance(n, ast.ImportFrom):
                self.assertEqual(n.level, 0)
                imports.add(n.module)
        self.assertEqual(imports, {'dataclasses','enum','hashlib','json'})

    def test_40_no_io(self):
        import builtins, io, os, sqlite3, subprocess
        a, b = pure_exercise([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),
                              (sqlite3,'connect'),(subprocess,'Popen')])
        self.assertEqual(a, b)

    def test_41_no_network(self):
        import socket, http.client
        a, b = pure_exercise([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
                              (http.client.HTTPConnection,'request')])
        self.assertEqual(a, b)

    def test_42_no_environment(self):
        import os
        class ForbiddenEnvironment(dict):
            def __getitem__(self, key): raise AssertionError('environment read')
            def get(self, *args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os, 'environ', ForbiddenEnvironment()):
            a, b = pure_exercise([(os,'getenv')])
        self.assertEqual(a, b)

    def test_43_no_random_uuid(self):
        import random, uuid
        a, b = pure_exercise([(random,'random'), (random,'getrandbits'),(uuid,'uuid4'),(uuid,'uuid1')])
        self.assertEqual(a, b)

    def test_44_no_gameplay_fields(self):
        schemas = {
            ObservationSource:{'source_id','source_kind','schema_id'},
            ClockStamp:{'clock_id','tick'},
            ObservationEvent:{'timeline_id','source','refs','source_stamp','receipt_stamp'},
            ObservationTimingPolicy:{'policy_id','basis'},
            TemporalProjection:{'event_id','timeline_id','source_id','refs','selected_clock_id',
                                'selected_tick','timing_policy_id','timestamp_basis'},
        }
        for cls, names in schemas.items(): self.assertEqual({f.name for f in fields(cls)}, names)
        with self.assertRaises(TypeError): event(value=True)
        self.assertEqual(set(TimestampBasis), {SOURCE, RECEIPT})

    def test_45_no_namespace_interpretation(self):
        tree = ast.parse(inspect.getsource(envelope))
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(any(c.endswith(('.startswith','.endswith','.split','.strip')) for c in calls))
        refs = ('enemy.missing', 'observer.coverage.bot', ' nonsense ', 'ward.safe')
        value = event(refs=refs)
        self.assertEqual(value.refs, tuple(sorted(refs)))
        self.assertEqual(project_event_time(value, policy(SOURCE)).refs, tuple(sorted(refs)))

    def test_46_no_conversion_to_expected_clock(self):
        value = event(receipt_stamp=ClockStamp('other', 5000))
        with self.assertRaises(ValueError): project_event_time(value, policy(SOURCE), 'other')
        self.assertEqual(project_event_time(value, policy(SOURCE), 'clock').selected_tick, 100)

    def test_47_timeline_not_derived(self):
        value = event(timeline_id=' explicit timeline ')
        self.assertEqual(project_event_time(value, policy(SOURCE)).timeline_id, ' explicit timeline ')
        self.assertEqual(event(source=ObservationSource('new','new','new')).timeline_id, 'A')
        tree = ast.parse(inspect.getsource(envelope))
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr in {'match_id','hero','pid'} for n in ast.walk(tree)))

    def test_48_tracker_source_compatibility(self):
        state = new_temporal_state('A','clock')
        projection = project_event_time(event(), policy(SOURCE), state.clock_id)
        result = bridge_for_test(state, projection)
        self.assertEqual(result.last_tick, 100)
        self.assertEqual(tuple(m.ref for m in result.marks), projection.refs)
        self.assertEqual({m.last_observed_tick for m in result.marks}, {100})
        self.assertEqual(state.marks, ())

    def test_49_tracker_receipt_compatibility(self):
        state = new_temporal_state('A','clock')
        projection = project_event_time(event(source_stamp=None), policy(RECEIPT), state.clock_id)
        result = bridge_for_test(state, projection)
        self.assertEqual(result.last_tick, 103)
        self.assertEqual({m.last_observed_tick for m in result.marks}, {103})

    def test_50_tracker_timeline_guard(self):
        state = new_temporal_state('B','clock')
        with self.assertRaisesRegex(ValueError, 'timeline_mismatch'):
            bridge_for_test(state, project_event_time(event(), policy(SOURCE)))
        self.assertEqual(state.marks, ())

    def test_51_tracker_clock_guard(self):
        state = new_temporal_state('A','other')
        with self.assertRaisesRegex(ValueError, 'clock_mismatch'):
            bridge_for_test(state, project_event_time(event(), policy(SOURCE)))
        self.assertEqual(state.marks, ())

    def test_52_late_source_no_automatic_fix(self):
        state = record_observations(new_temporal_state('A','clock'), (), 120)
        value = event(source_stamp=ClockStamp('clock',110), receipt_stamp=ClockStamp('clock',125))
        source = project_event_time(value, policy(SOURCE))
        self.assertEqual(source.selected_tick, 110)
        with self.assertRaisesRegex(ValueError, 'decreasing_tick'):
            bridge_for_test(state, source)
        self.assertEqual(state.last_tick, 120)
        self.assertEqual(state.marks, ())
        receipt = project_event_time(value, policy(RECEIPT))
        self.assertEqual(bridge_for_test(state, receipt).last_tick, 125)
        self.assertEqual(source.selected_tick, 110)

    def test_53_identical_events_same_id_not_retransmission_judgment(self):
        a, b = event(), event()
        self.assertIsNot(a, b)
        self.assertEqual(a.event_id, b.event_id)
        self.assertFalse(hasattr(a, 'is_retransmission'))

    def test_54_no_hidden_stream_memory(self):
        before = dict(vars(envelope))
        first = event()
        first_projection = project_event_time(first, policy(SOURCE))
        unrelated = event(timeline_id='other', source_stamp=None, receipt_stamp=ClockStamp('new',1000000))
        project_event_time(unrelated, policy(RECEIPT))
        earlier = event(source_stamp=ClockStamp('clock',-20), receipt_stamp=ClockStamp('clock',-10))
        self.assertEqual(project_event_time(earlier, policy(SOURCE)).selected_tick, -20)
        self.assertEqual(first_projection, project_event_time(first, policy(SOURCE)))
        self.assertEqual(before, vars(envelope))
        for name, value in vars(envelope).items():
            if not name.startswith('__'):
                self.assertNotIsInstance(value, (dict,list,set,bytearray,ObservationEvent,TemporalProjection))
        tree = ast.parse(inspect.getsource(envelope))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'eval','exec','__import__','getattr','open'})

    def test_55_temporal_files_unchanged(self):
        self.check_hashes('temporal')

    def test_56_frozen_core_and_dependency_direction_unchanged(self):
        self.check_hashes('core')
        root = Path(envelope.__file__).resolve().parent.parent
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/threat_observation.py',
                                           'coach02/threat_absence_observation.py',
                                           'coach02/strategic_coverage.py', 'coach02/option_exposure.py'})
        allowed_contracts = frozenset(('ObservationEvent', 'TemporalProjection', 'TimestampBasis'))
        operations = frozenset({'project_event_time', 'new_temporal_state',
                                'record_observations', 'evaluate_freshness'})

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            live = relative_path == 'coach02/live_runtime_v01.py'
            live_contracts = frozenset(('ObservationSource', 'ClockStamp', 'ObservationEvent', 'ObservationTimingPolicy', 'TimestampBasis', 'TemporalProjection', 'project_event_time'))
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
                        if 'observation_event' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('observation_event' in (node.module or '').split('.') or
                               any(a.name == 'observation_event' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'observation_event') or
                                        (node.level == 0 and node.module == 'coach02.observation_event'))
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
                                       and 'observation_event' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .observation_event import ObservationEvent',
            'from coach02.observation_event import ObservationEvent as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.observation_event as foundation',
            'from coach02 import observation_event as foundation',
            'from .observation_event import *',
            'from ..observation_event import ObservationEvent',
            'from .observation_event import ObservationEvent as Contract\nContract()',
            'from .observation_event import ObservationEvent as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.observation_event')",
            "from importlib import import_module as load\nload('coach02.observation_event')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .observation_event import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.observation_event')"
        self.assertTrue(violations(dynamic, 'coach02/arbitrary_future_consumer.py'))
        live_path = 'coach02/live_runtime_v01.py'
        live_source = 'from .observation_event import ObservationSource as Public\nPublic()'
        self.assertEqual(violations(live_source, live_path), [])
        self.assertTrue(violations(live_source, 'coach02/arbitrary_future_consumer.py'))
        for bad in ('from .observation_event import *',
                    'import coach02.observation_event as foundation',
                    'from ..observation_event import ObservationSource',
                    'from .observation_event import PrivateSymbol',
                    "import importlib as loader\nloader.import_module('coach02.observation_event')"):
            self.assertTrue(violations(bad, live_path))
        paths = [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py'))
        for path in paths:
            if path.relative_to(root).as_posix() == 'coach02/observation_event.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))

    def check_hashes(self, group):
        root = Path(envelope.__file__).resolve().parent.parent
        for rel,sha in ACCEPTED_HASHES:
            temporal = 'temporal_evidence' in rel.lower()
            if (group=='temporal') != temporal: continue
            with self.subTest(file=rel):
                self.assertEqual(hashlib.sha256((root/rel).read_bytes()).hexdigest().upper(),sha)

    def test_57_adversarial_A_same_clock_explicit_choice(self):
        value = event()
        self.assertEqual(project_event_time(value, policy(SOURCE)).selected_tick, 100)
        self.assertEqual(project_event_time(value, policy(RECEIPT)).selected_tick, 103)
        with self.assertRaises(TypeError): project_event_time(value)

    def test_58_adversarial_B_different_domains(self):
        value = event(source_stamp=ClockStamp('game-clock',100), receipt_stamp=ClockStamp('orchestrator-clock',5000))
        source, receipt = project_event_time(value,policy(SOURCE)), project_event_time(value,policy(RECEIPT))
        self.assertEqual((source.selected_clock_id,source.selected_tick),('game-clock',100))
        self.assertEqual((receipt.selected_clock_id,receipt.selected_tick),('orchestrator-clock',5000))
        tree = ast.parse(inspect.getsource(envelope))
        self.assertFalse(any(isinstance(n,ast.BinOp) and isinstance(n.op,ast.Sub) for n in ast.walk(tree)))

    def test_59_adversarial_C_missing_source(self):
        value = event(source_stamp=None)
        self.assertEqual(project_event_time(value,policy(RECEIPT)).selected_tick,103)
        with self.assertRaises(ValueError): project_event_time(value,policy(SOURCE))

    def test_60_adversarial_D_impossible_order(self):
        with self.assertRaises(ValueError):
            event(source_stamp=ClockStamp('c',105),receipt_stamp=ClockStamp('c',100))

    def test_61_adversarial_E_late_event_other_receipt_clock(self):
        state = record_observations(new_temporal_state('A','tracker-clock'),(),120)
        value = event(source_stamp=ClockStamp('tracker-clock',110),receipt_stamp=ClockStamp('receipt-clock',125))
        projection = project_event_time(value,policy(SOURCE),state.clock_id)
        self.assertEqual(projection.selected_tick,110)
        with self.assertRaisesRegex(ValueError,'decreasing_tick'): bridge_for_test(state,projection)
        with self.assertRaisesRegex(ValueError,'clock_mismatch'):
            bridge_for_test(state,project_event_time(value,policy(RECEIPT)))
        self.assertEqual(state.last_tick,120)
        self.assertEqual(projection.selected_tick,110)

    def test_62_adversarial_F_timeline_mismatch(self):
        projection = project_event_time(event(timeline_id='A'),policy(SOURCE))
        with self.assertRaisesRegex(ValueError,'timeline_mismatch'):
            bridge_for_test(new_temporal_state('B','clock'),projection)

    def test_63_adversarial_G_clock_mismatch(self):
        projection = project_event_time(event(source_stamp=ClockStamp('X',100)),policy(SOURCE))
        with self.assertRaisesRegex(ValueError,'clock_mismatch'):
            bridge_for_test(new_temporal_state('A','Y'),projection)

    def test_64_adversarial_H_pause_like_equal_stamps(self):
        value = event(source_stamp=ClockStamp('clock',0),receipt_stamp=ClockStamp('clock',0))
        for basis in (SOURCE,RECEIPT):
            result = project_event_time(value,policy(basis))
            self.assertEqual(result.selected_tick,0)
            self.assertFalse(hasattr(result,'paused'))

    def test_65_empty_batch_no_occurrences(self):
        value = event(refs=())
        projection = project_event_time(value,policy(SOURCE))
        self.assertEqual(projection.refs,())
        self.assertNotEqual(value.event_id,event().event_id)
        # Projection alone does not call tracker, even for an empty batch.
        with patch('coach02.temporal_evidence.record_observations',side_effect=AssertionError('automatic wiring')):
            self.assertEqual(projection,project_event_time(value,policy(SOURCE)))

    def test_66_source_clock_policy_validation(self):
        for bad in ('',None,1,True,[]):
            for name in ('source_id','source_kind','schema_id'):
                args=dict(source_id='p',source_kind='k',schema_id='s'); args[name]=bad
                with self.assertRaises(ValueError): ObservationSource(**args)
            with self.assertRaises(ValueError): ClockStamp(bad,0)
            with self.assertRaises(ValueError): ObservationTimingPolicy(bad,SOURCE)
        for bad in ('source','receipt',None,1,True):
            with self.assertRaises(TypeError): ObservationTimingPolicy('p',bad)
        for bad in ('100',None,[]):
            with self.assertRaises(TypeError): ClockStamp('clock',bad)
        for bad in ('',True,123):
            with self.assertRaises(ValueError): project_event_time(event(),policy(SOURCE),bad)

    def test_67_invalid_nested_inputs_and_projection(self):
        for bad in ({'clock_id':'clock','tick':100},100,'clock'):
            with self.assertRaises(TypeError): event(source_stamp=bad)
        with self.assertRaises(TypeError): project_event_time({},policy(SOURCE))
        with self.assertRaises(TypeError): project_event_time(event(),{'policy_id':'p','basis':SOURCE})
        result = project_event_time(event(),policy(SOURCE))
        with self.assertRaises(TypeError): replace(result,selected_tick=True)
        with self.assertRaises(TypeError): replace(result,timestamp_basis='source')
        with self.assertRaises(TypeError): replace(result,refs=['x'])
        with self.assertRaises(ValueError): replace(result,event_id='')
        with self.assertRaises(ValueError): replace(result,refs=('x','x'))

    def test_68_projection_binds_unselected_stamp_and_source_metadata(self):
        a = event()
        b = event(receipt_stamp=ClockStamp('clock',104))
        c = event(source=replace(a.source,schema_id='next'))
        projections = [project_event_time(e,policy(SOURCE)) for e in (a,b,c)]
        self.assertEqual({p.selected_tick for p in projections},{100})
        self.assertEqual(len({p.projection_id for p in projections}),3)
        self.assertEqual(project_event_time(a,policy(SOURCE)).projection_id,
                         project_event_time(a,policy(SOURCE),'clock').projection_id)


# Accepted hashes are appended from the preserved pre-change freeze at preparation.

ACCEPTED_HASHES = (('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'), ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'), ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'))

if __name__ == "__main__":
    unittest.main()
