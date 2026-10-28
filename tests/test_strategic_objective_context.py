"""Explicit shared-objective contracts, adversarial inputs and frozen dependencies."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
from enum import Enum
import hashlib
import inspect
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import strategic_objective_context as objective
from coach02.strategic_objective_context import (
    StrategicObjectiveKnownness, StrategicObjectiveClaim,
    StrategicObjectiveAssessment, StrategicObjectiveSnapshot,
    build_strategic_objective_context,
)


def claim(**changes):
    values = dict(objective_context_id='context', knownness=StrategicObjectiveKnownness.KNOWN,
                  objective_id='objective', horizon_id='horizon', basis_tick=4,
                  source_id='source', evidence_refs=('ref-b', 'ref-a'),
                  assessment_policy_id='assessment.v1')
    values.update(changes)
    return StrategicObjectiveClaim(**values)


def build(claims=None, **changes):
    values = dict(timeline_id='timeline', selected_clock_id='clock', evaluated_at_tick=5,
                  claims=(claim(),) if claims is None else claims)
    values.update(changes)
    return build_strategic_objective_context(**values)


class StrategicObjectiveContextTests(unittest.TestCase):
    def identifier(self, name):
        class Text(str): pass
        for value in ('', ' \t\n', None, 0, False, Text('text')):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                claim(**{name: value})
        value = '  opaque:/β ' + name + '  '
        self.assertEqual(getattr(build((claim(**{name: value}),)).assessments[0], name), value)

    def preserved(self, name, value):
        source = claim(**{name: value})
        row = build((source,)).assessments[0]
        self.assertEqual(getattr(row, name), value)
        self.assertEqual(getattr(row.base_claim, name), value)

    def changed(self, name, value, header=False):
        other = build(**{name: value}) if header else build((claim(**{name: value}),))
        self.assertNotEqual(build().snapshot_id, other.snapshot_id)

    def tokens(self):
        tree = ast.parse(inspect.getsource(objective))
        return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
            n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is str}

    def absent_terms(self, *terms):
        self.assertTrue(set(terms).isdisjoint(self.tokens()))
        names = {f.name for c in (StrategicObjectiveClaim, StrategicObjectiveAssessment,
                                 StrategicObjectiveSnapshot) for f in fields(c)}
        self.assertTrue(set(terms).isdisjoint(names))

    def imports(self):
        tree = ast.parse(inspect.getsource(objective))
        return {'.' * n.level + (n.module or '') for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}

    def forbidden_imports(self, *names):
        self.assertEqual(self.imports(), {'dataclasses', 'enum', 'hashlib', 'json'})
        self.assertFalse(any(any(name in imported for name in names) for imported in self.imports()))

    def pure(self, targets):
        source = (claim(), claim(objective_context_id='other', objective_id='FARM'))
        expected = build(source)
        def denied(*args, **kwargs): raise AssertionError('forbidden side effect')
        with ExitStack() as stack:
            for module, name in targets:
                stack.enter_context(patch.object(module, name, denied))
            result = build(source)
            identity = result.snapshot_id
        self.assertEqual(result, expected)
        self.assertEqual(identity, expected.snapshot_id)

    def test_001_exact_knownness_enum(self):
        self.assertEqual(StrategicObjectiveKnownness.__members__,
                         {x: StrategicObjectiveKnownness(x) for x in ('KNOWN', 'UNKNOWN')})
        self.assertEqual([x.value for x in StrategicObjectiveKnownness], ['KNOWN', 'UNKNOWN'])

    def test_002_no_priority_or_action_enum(self):
        self.assertEqual({n for n, v in vars(objective).items() if isinstance(v, type)
                          and issubclass(v, Enum) and v.__module__ == objective.__name__},
                         {'StrategicObjectiveKnownness'})
        self.absent_terms('GOOD', 'BAD', 'HIGH_PRIORITY', 'LOW_PRIORITY', 'PRIMARY', 'SECONDARY')

    def test_003_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().objective_id = 'changed'

    def test_004_assessment_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assessments[0].source_id = 'changed'

    def test_005_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assessments = ()

    def test_006_context_identifier(self): self.identifier('objective_context_id')
    def test_007_horizon_identifier(self): self.identifier('horizon_id')
    def test_008_source_identifier(self): self.identifier('source_id')
    def test_009_policy_identifier(self): self.identifier('assessment_policy_id')

    def test_010_exact_knownness_and_revalidation(self):
        class Other(str, Enum): KNOWN = 'KNOWN'
        for value in ('KNOWN', Other.KNOWN, None, 1):
            with self.subTest(value=value), self.assertRaises(TypeError): claim(knownness=value)
        source = claim()
        object.__setattr__(source, 'knownness', 'KNOWN')
        with self.assertRaises(TypeError): build((source,))

    def test_011_known_requires_concrete_objective(self):
        class Text(str): pass
        for value in (None, False, 7, Text('objective')):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                claim(objective_id=value)
        with self.assertRaises(TypeError):
            StrategicObjectiveClaim(**{k: v for k, v in asdict(claim()).items() if k != 'objective_id'})

    def test_012_known_blank_objective_rejected(self):
        for value in ('', ' \t\n', '\u2003'):
            with self.subTest(value=value), self.assertRaises(ValueError): claim(objective_id=value)
        self.preserved('objective_id', '  β/目標  ')

    def test_013_unknown_requires_none(self):
        for value in ('objective', '', False, 0, (), object()):
            with self.subTest(value=value), self.assertRaises(ValueError):
                claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=value)

    def test_014_unknown_magic_string_is_not_uncertainty(self):
        with self.assertRaises(ValueError):
            claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id='UNKNOWN')
        row = build((claim(objective_id='UNKNOWN'),)).assessments[0]
        self.assertIs(row.knownness, StrategicObjectiveKnownness.KNOWN)
        self.assertEqual(row.objective_id, 'UNKNOWN')

    def test_015_exact_claim_tuple_and_exact_elements(self):
        class Tuple(tuple): pass
        class Child(StrategicObjectiveClaim): pass
        for value in ([claim()], iter((claim(),)), Tuple((claim(),)), None):
            with self.subTest(value=type(value)), self.assertRaises(TypeError):
                build_strategic_objective_context(timeline_id='t', selected_clock_id='c',
                                                 evaluated_at_tick=5, claims=value)
        for value in (object(), Child(**asdict(claim()))):
            with self.assertRaises(TypeError): build((value,))

    def test_016_exact_reference_tuple(self):
        class Tuple(tuple): pass
        for value in (['r'], iter(('r',)), Tuple(('r',)), 'r', None):
            with self.subTest(value=type(value)), self.assertRaises(TypeError): claim(evidence_refs=value)

    def test_017_duplicate_refs_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_evidence_ref'): claim(evidence_refs=('r', 'r'))

    def test_018_blank_or_nonconcrete_refs_rejected(self):
        class Text(str): pass
        for value in ('', ' \n', None, 3, Text('r')):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                claim(evidence_refs=(value,))

    def test_019_empty_refs_allowed_without_resolution(self):
        self.assertEqual(build((claim(evidence_refs=()),)).assessments[0].evidence_refs, ())
        self.preserved('evidence_refs', ('nonexistent://opaque', 'C:/not-loaded'))

    def test_020_concrete_basis_tick(self):
        class Number(int): pass
        for value in (4.0, '4', None, Number(4)):
            with self.subTest(value=value), self.assertRaises(TypeError): claim(basis_tick=value)

    def test_021_bool_basis_rejected(self):
        for value in (True, False):
            with self.assertRaises(TypeError): claim(basis_tick=value)

    def test_022_negative_basis_rejected_zero_valid(self):
        with self.assertRaises(ValueError): claim(basis_tick=-1)
        self.assertEqual(build((claim(basis_tick=0),), evaluated_at_tick=0).assessments[0].basis_tick, 0)

    def test_023_concrete_evaluation_tick(self):
        class Number(int): pass
        for value in (5.0, '5', None, Number(5)):
            with self.subTest(value=value), self.assertRaises(TypeError): build(evaluated_at_tick=value)

    def test_024_bool_evaluation_rejected(self):
        for value in (True, False):
            with self.assertRaises(TypeError): build((), evaluated_at_tick=value)

    def test_025_negative_evaluation_rejected(self):
        with self.assertRaises(ValueError): build((), evaluated_at_tick=-1)

    def test_026_timeline_concrete_nonblank(self):
        class Text(str): pass
        for value in ('', ' \t', None, False, Text('t')):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                build(timeline_id=value)

    def test_027_clock_concrete_nonblank(self):
        class Text(str): pass
        for value in ('', ' \t', None, False, Text('c')):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                build(selected_clock_id=value)

    def test_028_future_basis_rejected_before_any_output(self):
        with patch.object(objective, 'StrategicObjectiveAssessment') as constructor:
            with self.assertRaisesRegex(ValueError, 'basis_after_evaluation'):
                build((claim(), claim(objective_context_id='second', basis_tick=6)))
            constructor.assert_not_called()

    def test_029_equal_tick_valid(self):
        result = build((claim(basis_tick=5),))
        self.assertEqual(result.assessments[0].basis_tick, result.evaluated_at_tick)

    def test_030_older_tick_preserved(self):
        source = claim(basis_tick=0)
        result = build((source,), evaluated_at_tick=1000000)
        self.assertEqual(result.assessments[0].basis_tick, 0)
        self.assertIs(result.assessments[0].base_claim, source)

    def test_031_no_temporal_classification(self):
        self.absent_terms('freshness', 'temporal_status', 'FRESH', 'STALE', 'CURRENT', 'HISTORICAL')
        first = build((claim(basis_tick=0),), evaluated_at_tick=5)
        later = build((claim(basis_tick=0),), evaluated_at_tick=999999)
        self.assertEqual(first.assessments, later.assessments)

    def test_032_duplicate_pair_rejected_not_reconciled(self):
        first = claim()
        for other in (first, claim(objective_id='other'), claim(source_id='other'),
                      claim(assessment_policy_id='other'), claim(basis_tick=3),
                      claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None)):
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, 'duplicate_context_horizon'):
                build((first, other))

    def test_033_same_context_different_horizons(self):
        result = build((claim(horizon_id='short'), claim(horizon_id='long', objective_id='other')))
        self.assertEqual([(r.horizon_id, r.objective_id) for r in result.assessments],
                         [('long', 'other'), ('short', 'objective')])

    def test_034_different_contexts_same_horizon_and_objective(self):
        result = build((claim(objective_context_id='a'), claim(objective_context_id='b')))
        self.assertEqual([(r.objective_context_id, r.objective_id) for r in result.assessments],
                         [('a', 'objective'), ('b', 'objective')])

    def test_035_empty_claims_valid(self):
        result = build((), timeline_id='empty', selected_clock_id='explicit', evaluated_at_tick=0)
        self.assertEqual(result.assessments, ())
        self.assertEqual((result.timeline_id, result.selected_clock_id, result.evaluated_at_tick),
                         ('empty', 'explicit', 0))

    def test_036_absent_distinct_from_unknown(self):
        absent = build(())
        unknown = build((claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),))
        self.assertEqual(len(absent.assessments), 0)
        self.assertEqual(len(unknown.assessments), 1)
        self.assertNotEqual(absent.snapshot_id, unknown.snapshot_id)

    def test_037_explicit_unknown_row(self):
        source = claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None)
        row = build((source,)).assessments[0]
        self.assertIs(row.knownness, StrategicObjectiveKnownness.UNKNOWN)
        self.assertIsNone(row.objective_id)
        self.assertIs(row.base_claim, source)

    def test_038_no_synthetic_unknown_or_cartesian_rows(self):
        result = build((claim(objective_context_id='a', horizon_id='x'),
                        claim(objective_context_id='b', horizon_id='y')))
        self.assertEqual([(r.objective_context_id, r.horizon_id) for r in result.assessments],
                         [('a', 'x'), ('b', 'y')])
        self.assertTrue(all(r.knownness is StrategicObjectiveKnownness.KNOWN for r in result.assessments))

    def test_039_one_assessment_per_claim(self):
        sources = tuple(claim(objective_context_id=str(i)) for i in range(4))
        self.assertEqual(len(build(sources).assessments), 4)
        self.assertEqual({id(r.base_claim) for r in build(sources).assessments}, {id(c) for c in sources})

    def test_040_no_context_discovery_or_defaults(self):
        parameters = inspect.signature(build_strategic_objective_context).parameters
        self.assertEqual(tuple(parameters), ('timeline_id', 'selected_clock_id', 'evaluated_at_tick', 'claims'))
        self.assertTrue(all(p.kind == p.KEYWORD_ONLY and p.default == p.empty for p in parameters.values()))
        result = build((claim(objective_context_id='risk:safety:outcome'),))
        self.assertEqual([r.objective_context_id for r in result.assessments], ['risk:safety:outcome'])

    def test_041_base_claim_identity_survives_sort(self):
        first, second = claim(objective_context_id='z'), claim(objective_context_id='a')
        rows = build((first, second)).assessments
        self.assertIs(rows[0].base_claim, second)
        self.assertIs(rows[1].base_claim, first)

    def test_042_no_input_mutation(self):
        sources = (claim(objective_context_id='z'), claim(objective_context_id='a'))
        before = tuple(asdict(c) for c in sources)
        build(sources)
        build(sources)
        self.assertEqual(tuple(asdict(c) for c in sources), before)
        self.assertEqual(tuple(c.objective_context_id for c in sources), ('z', 'a'))

    def test_043_context_preserved(self): self.preserved('objective_context_id', '  risk-like:/β  ')
    def test_044_knownness_preserved(self): self.preserved('knownness', StrategicObjectiveKnownness.KNOWN)
    def test_045_objective_preserved(self): self.preserved('objective_id', 'carry.sustainable_progression.v1')
    def test_046_horizon_preserved(self): self.preserved('horizon_id', '99seconds/next-wave/not-parsed')
    def test_047_basis_preserved(self): self.preserved('basis_tick', 2)
    def test_048_source_preserved(self): self.preserved('source_id', 'fixture/not-authenticated')
    def test_049_refs_order_preserved(self): self.preserved('evidence_refs', (' z ', 'é', 'a'))
    def test_050_policy_preserved(self): self.preserved('assessment_policy_id', 'external.policy.v9')
    def test_051_timeline_preserved(self): self.assertEqual(build(timeline_id='  timeline/β ').timeline_id, '  timeline/β ')
    def test_052_clock_preserved(self): self.assertEqual(build(selected_clock_id=' supplied clock ').selected_clock_id, ' supplied clock ')
    def test_053_evaluation_preserved(self): self.assertEqual(build(evaluated_at_tick=10**40).evaluated_at_tick, 10**40)

    def test_054_fixed_ruleset_and_complete_schema(self):
        self.assertEqual(build().ruleset, 'strategic.objective_context.v1')
        claim_fields = ('objective_context_id', 'knownness', 'objective_id', 'horizon_id',
                        'basis_tick', 'source_id', 'evidence_refs', 'assessment_policy_id')
        self.assertEqual(tuple(f.name for f in fields(StrategicObjectiveClaim)), claim_fields)
        self.assertEqual(tuple(f.name for f in fields(StrategicObjectiveAssessment)), claim_fields + ('base_claim',))
        self.assertEqual(tuple(f.name for f in fields(StrategicObjectiveSnapshot)),
                         ('timeline_id', 'selected_clock_id', 'evaluated_at_tick', 'ruleset', 'assessments'))

    def test_055_canonical_json_identity(self):
        snapshot = build((claim(objective_id='目標/é'),))
        payload = json.dumps(asdict(snapshot), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(snapshot.snapshot_id, 'strategic.objective_context.v1:snapshot:' + hashlib.sha256(payload).hexdigest())
        self.assertEqual(snapshot.snapshot_id, build((claim(objective_id='目標/é'),)).snapshot_id)
        self.assertNotEqual(snapshot.snapshot_id, replace(snapshot, ruleset='changed').snapshot_id)

    def test_056_permutation_invariant(self):
        sources = (claim(objective_context_id='z'), claim(objective_context_id='a'),
                   claim(objective_context_id='a', horizon_id='other'))
        expected = build(sources)
        for order in itertools.permutations(sources):
            self.assertEqual(build(order), expected)
            self.assertEqual(build(order).snapshot_id, expected.snapshot_id)

    def test_057_canonical_order_is_not_objective_order(self):
        sources = (claim(objective_context_id='z', objective_id='a'),
                   claim(objective_context_id='a', horizon_id='z', objective_id='b'),
                   claim(objective_context_id='a', horizon_id='a', objective_id='z'))
        rows = build(sources).assessments
        self.assertEqual([(r.objective_context_id, r.horizon_id, r.source_id, r.assessment_policy_id)
                          for r in rows], sorted((c.objective_context_id, c.horizon_id, c.source_id,
                                                  c.assessment_policy_id) for c in sources))
        self.assertEqual([r.objective_id for r in rows], ['z', 'b', 'a'])

    def test_058_context_binds_identity(self): self.changed('objective_context_id', 'other')
    def test_059_knownness_binds_identity(self):
        other = build((claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),))
        self.assertNotEqual(build().snapshot_id, other.snapshot_id)
    def test_060_objective_binds_identity(self): self.changed('objective_id', 'other')
    def test_061_horizon_binds_identity(self): self.changed('horizon_id', 'other')
    def test_062_basis_binds_identity(self): self.changed('basis_tick', 3)
    def test_063_source_binds_identity(self): self.changed('source_id', 'other')
    def test_064_refs_bind_identity(self): self.changed('evidence_refs', ('ref-a', 'ref-b'))
    def test_065_policy_binds_identity(self): self.changed('assessment_policy_id', 'other')
    def test_066_timeline_binds_identity(self): self.changed('timeline_id', 'other', True)
    def test_067_clock_binds_identity(self): self.changed('selected_clock_id', 'other', True)
    def test_068_evaluation_binds_identity(self): self.changed('evaluated_at_tick', 6, True)

    def test_069_complete_base_claim_binds_identity(self):
        snapshot = build()
        row = snapshot.assessments[0]
        changed = replace(snapshot, assessments=(replace(row, base_claim=claim(source_id='other')),))
        self.assertNotEqual(snapshot.snapshot_id, changed.snapshot_id)
        unknown = claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None)
        object.__setattr__(unknown, 'objective_id', 'forged')
        with self.assertRaises(ValueError): build((unknown,))

    def test_070_no_priority(self): self.absent_terms('priority', 'primary', 'secondary', 'importance')
    def test_071_no_weights(self): self.absent_terms('weight', 'weights', 'weighting')
    def test_072_no_objective_score(self): self.absent_terms('score', 'objective_score', 'criticality')
    def test_073_no_utility(self): self.absent_terms('utility', 'reward', 'expected_value', 'opportunity_cost')
    def test_074_no_option_id(self): self.absent_terms('option_id', 'option_ids', 'options')
    def test_075_no_alignment(self): self.absent_terms('alignment', 'contribution', 'fit')
    def test_076_no_support_opposition(self): self.absent_terms('supports_objective', 'opposes_objective', 'support', 'opposition')
    def test_077_no_ranking(self): self.absent_terms('rank', 'ranking', 'ranked', 'compare_options')
    def test_078_no_selection(self): self.absent_terms('selected_option', 'selected_plan', 'winner', 'recommendation')
    def test_079_no_action_authority(self): self.absent_terms('action', 'Action', 'Authority', 'authority', 'directive', 'TAKE_WAVE', 'ABORT', 'ROTATE', 'STAY', 'LEAVE')
    def test_080_no_communication_authority(self): self.absent_terms('speak', 'speech', 'output', 'communication', 'message', 'voice')
    def test_081_no_urgency(self): self.absent_terms('urgency', 'urgent', 'deadline')

    def test_082_farm_is_opaque(self):
        self.absent_terms('FARM')
        self.preserved('objective_id', 'FARM')

    def test_083_fight_is_opaque(self):
        self.absent_terms('FIGHT')
        self.preserved('objective_id', 'FIGHT')

    def test_084_push_is_opaque(self):
        self.absent_terms('PUSH')
        self.preserved('objective_id', 'PUSH')

    def test_085_retreat_is_opaque(self):
        self.absent_terms('RETREAT')
        self.preserved('objective_id', 'RETREAT')

    def test_086_generic_across_five_roles(self):
        self.absent_terms('role', 'carry', 'mid', 'offlane', 'support', 'gold', 'lane', 'damage', 'vision')
        for role in ('Carry', 'Mid', 'Offlane', 'Support 4', 'Support 5'):
            self.preserved('objective_id', role + '/opaque')

    def test_087_no_hero_inference(self):
        self.absent_terms('hero', 'hero_id', 'phase', 'power_spike')
        self.preserved('objective_id', 'hero:Invoker/FARM/midgame')

    def test_088_no_outcome_dependency(self): self.forbidden_imports('option_outcome_evidence')
    def test_089_no_safety_dependency(self): self.forbidden_imports('option_safety', 'safety_evidence')
    def test_090_no_risk_dependency(self): self.forbidden_imports('risk_evaluation', 'risk_evidence_assembly')
    def test_091_no_decision_dependency(self): self.forbidden_imports('decision')
    def test_092_no_farm_context_dependency(self): self.forbidden_imports('farm_context')
    def test_093_no_farm_cycle_or_legacy_assembly(self): self.forbidden_imports('farm_cycle', 'strategic_evidence')
    def test_094_no_observation_event_dependency(self): self.forbidden_imports('observation_event')
    def test_095_no_temporal_dependency(self): self.forbidden_imports('temporal_evidence')
    def test_096_no_runtime_service_gsi(self): self.forbidden_imports('runtime_adapter', 'service', 'gsi', 'rules', 'vision', 'voice')

    def test_097_no_wall_clock(self):
        import time
        self.forbidden_imports('time', 'datetime')
        self.pure(((time, 'time'), (time, 'monotonic'), (time, 'perf_counter')))

    def test_098_no_io(self):
        import builtins
        self.absent_terms('open', 'read_text', 'read_bytes', 'write_text', 'write_bytes')
        self.pure(((builtins, 'open'), (Path, 'read_text'), (Path, 'read_bytes')))

    def test_099_no_network(self):
        import socket
        self.forbidden_imports('socket', 'urllib', 'requests', 'http')
        self.pure(((socket, 'socket'), (socket, 'create_connection'), (socket, 'getaddrinfo')))

    def test_100_no_environment(self):
        import os
        self.forbidden_imports('os', 'sys')
        self.pure(((os, 'getenv'), (os, 'getcwd')))

    def test_101_no_random_or_uuid(self):
        import random
        import uuid
        self.forbidden_imports('random', 'uuid', 'secrets')
        self.pure(((random, 'random'), (random, 'choice'), (uuid, 'uuid4')))

    def test_102_no_mutable_global_state(self):
        before = {k: id(v) for k, v in vars(objective).items() if not k.startswith('__')}
        self.assertFalse(any(isinstance(v, (dict, list, set, bytearray))
                             for k, v in vars(objective).items() if not k.startswith('__')))
        tree = ast.parse(inspect.getsource(objective))
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))
        build().snapshot_id
        build(())
        self.assertEqual(before, {k: id(v) for k, v in vars(objective).items() if not k.startswith('__')})

    def test_103_legacy_handoff_and_limits_documented(self):
        document = (Path(objective.__file__).resolve().parent.parent /
                    'STRATEGIC_OBJECTIVE_CONTEXT_V01.md').read_text(encoding='utf-8')
        for text in (
                'Strategic Objective Context identifies intent; it does not choose action.',
                'Objective IDs are opaque.', 'KNOWN does not mean recommended action.',
                'UNKNOWN is explicit and distinct from absent evidence.',
                'No objective priority or weighting exists in v0.1.',
                'No option is evaluated against the objective in v0.1.',
                'Strategic Objective, Option Safety and Option Outcome Evidence remain independent.',
                'Decision Context v0.2 must bind them explicitly.',
                'Decision.objective', 'coach02/farm_cycle.py', 'coach02/farm_context.py',
                'coach02/strategic_evidence.py', 'No adapter', 'OptionSafetySnapshotV2',
                'OptionOutcomeSnapshot', 'DecisionContextV2', 'StrategicObjectiveSnapshot',
                'NEXT 1', 'NEXT 2', 'NEXT 3', 'coach02/option_availability.py',
                'BLOCKER_BEFORE_DECISION_CONTEXT_V02', 'BLOCKER_BEFORE_FEASIBILITY_GATE',
                'BLOCKER_BEFORE_DECISION_ARBITER', 'BLOCKER_BEFORE_ATTENTION_GATE',
                'BLOCKER_BEFORE_LIVE', 'ACCEPTED_V01_LIMITATION'):
            with self.subTest(text=text): self.assertIn(text, document)

    def test_104_existing_project_hashes_preserved(self):
        root = Path(objective.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES), 118)
        for name, expected in BASELINE_HASHES:
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(), expected)


BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'),
 ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'),
 ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'),
 ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md',
  '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'),
 ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'),
 ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'),
 ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'),
 ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'),
 ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'),
 ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'),
 ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'),
 ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'),
 ('OPTION_OUTCOME_EVIDENCE_V01.md', '61D6DAD163B724E2EB9BD6859BBD476E828AC3574D32A3FDDEC7B58F3E7BC53A'),
 ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'),
 ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'),
 ('README.md', '72A60A5815269D2B2EAED3119841A4D57D26E6564F56BE104C6766F2FAAEF674'),
 ('RISK_EVALUATION_V01.md', '7A13246FD6D31A4A58C22AA9C1D209FF40727D79C8E90339620EDFDF2A878C32'),
 ('RISK_EVIDENCE_ASSEMBLY_V01.md', 'D44F8700089A390AC5CF6C670A78481A7340CF84A98A4766D194BF1D821B28B6'),
 ('RISK_EVIDENCE_ASSEMBLY_V02.md', '60A9C3B76C42C19B42EE94DA50A3A6C7E85400398502117200B3BF4F388D4D76'),
 ('RUNTIME_ADAPTER_V01.md', '723B87C9FA564CCB0527D6647F66D9752DA127082910C415D10838449E0051AE'),
 ('Run-Tests.cmd', 'C7D36F01B393C13362D8C6FB35D6C5FFDB9A81DC7AE086B61DE723974240136A'),
 ('SAFETY_EVIDENCE_V01.md', '160811B5829650324AD3353DD89C85ABAB878D3465B9261D0AFE840F284A8978'),
 ('STRATEGIC_COVERAGE_V01.md', '70AB604B5F34613F0BB306CC7E48FFB95CE1CA5419DB38427B91E8D4A8FB9181'),
 ('STRATEGIC_EVIDENCE_ASSEMBLY_V01.md', 'E2918BA287987AE36DF60BAD083CC45726998CFA97F082A626EB103D2F76FADD'),
 ('Start-Bot-Test.cmd', 'A967FFFC010A28FB3957C86B8B2AAF5DA7E98B40BA645B4DE63464FDBF3A11A4'),
 ('Start-Coach.cmd', '400EF821414BC0036D0BD29ED6382CDCC3477147604DAFCFAE488C7E329A8123'),
 ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'),
 ('THREAT_ABSENCE_OBSERVATION_V01.md', '6A37416C544E27A08DB0B8B1BC4D2D07136C833DE0A8674DD17EC79D9F9F0952'),
 ('THREAT_OBSERVATION_V01.md', '4633E7C0E920F790605DA27635A8D84ACA38DE59A52485CF16DEF1C7EDB8327B'),
 ('THREAT_REACHABILITY_V01.md', '180A3F7995AD367FD62DFCAA2175C03C6E1940C6C4BCFE80BF05C575DF0F2D42'),
 ('THREAT_RELEVANCE_V01.md', '51F9BEB03B612559A8EA350AB4C9FF5438C05A40EEAE5798CD40B5D1AD069666'),
 ('THREAT_STATE_ASSEMBLY_V01.md', 'CD7DDFAAFDBBA7A295616A1820FC267F46651C8B3AEB9ED445532B5C48E9766A'),
 ('VISIBILITY_COMPLETENESS_V01.md', 'E79A0B25695A39529E324F18792CA9C4CD31BDEB8EF8548C3FD351BB3DAFA7B3'),
 ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'),
 ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'),
 ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'),
 ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'),
 ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'),
 ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'),
 ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'),
 ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'),
 ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'),
 ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'),
 ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'),
 ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'),
 ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'),
 ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'),
 ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'),
 ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'),
 ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'),
 ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'),
 ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'),
 ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'),
 ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'),
 ('coach02/option_outcome_evidence.py', '04D5F650484CD7B067A410E6C7A37892CE054BCC1319835D2C948A0594CA0325'),
 ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'),
 ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'),
 ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'),
 ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'),
 ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'),
 ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'),
 ('coach02/risk_evidence_assembly_v02.py',
  '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'),
 ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'),
 ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'),
 ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'),
 ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'),
 ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'),
 ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'),
 ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'),
 ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'),
 ('coach02/threat_absence_observation.py',
  '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'),
 ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'),
 ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'),
 ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'),
 ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'),
 ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'),
 ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'),
 ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'),
 ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'),
 ('docs/CHANGES.md', 'A2DBFDAE75A11C1CFD601269E677D6F73F72A6017006D235AAD527A22F26BD9A'),
 ('docs/DECISIONS.md', '35C72BB38D35D8EE6A804BE9F3631047FB68E4A8E9538908F2259CD3917FB14A'),
 ('docs/TESTE_REAL.md', '335EC57D975ADB1FD046A358975DDF8831B67BC1F183C1AB4E576DAD675C06A8'),
 ('docs/VALIDATION.md', '7D5D0E515DE4D46E158DD955B2422F4B997A99000FCB531F61272FB06079A9C5'),
 ('docs/alpha01-reference/DECISIONS.md', '83D8C8EDD6386C958CB5A770746A1B7016C355596985DB44646EFF0B9ADA7571'),
 ('docs/alpha01-reference/VALIDATION.md', 'F29B09DD7427543EDA767B0FDBE68033C4A7980E6A9A9ADC3255189F274F619E'),
 ('docs/baseline-sha256.json', '3561C10064F6BAC12F032FCC51382EBD7D7FBEF70786C31E6C857DC386ECD40D'),
 ('docs/baseline-verification.json', '7326E1A33FB35E281A6A3211E85DFFD2A081BB22317C33DB7B7FAEE67E2E394B'),
 ('docs/test-results.txt', 'EE9BBD62124FCF6CB377DF2D79129BF0C927ACEAB2128AB247CABE92F0A7F2B7'),
 ('requirements-vision.txt', 'ECBC0244A6BC4646A912CF032F999724D47E22CB12CDBFAA231B600465F06711'),
 ('requirements.txt', 'CE972E5602F1BADF47B56CE597EBF4A3CBC516CA6C8979C95EE75C067D275840'),
 ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'),
 ('tests/test_alpha.py', '17BD7EBFF1558F062577A4677A472B0B3F65B85DC921253D6A9F5C2B705862D5'),
 ('tests/test_alpha02.py', '9F0839D676974435FA4AB3EE4887F9BE8DF876D07C271CADA4D0AFAA43A43C02'),
 ('tests/test_context_builder.py', '26A50D99710BAF117FA45AA570BA8BCDC38343835FED5EEF9C2618493E9AE701'),
 ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'),
 ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'),
 ('tests/test_missing_threat_resolver.py',
  '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'),
 ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'),
 ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'),
 ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'),
 ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'),
 ('tests/test_option_outcome_evidence.py',
  '650A4F6FD90A1163A8D7DBEED12EAF121F4AB265C07620A9224E2D099E3FE8E8'),
 ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'),
 ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'),
 ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'),
 ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'),
 ('tests/test_risk_evidence_assembly_v02.py',
  'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'),
 ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'),
 ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'),
 ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'),
 ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'),
 ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'),
 ('tests/test_threat_absence_observation.py',
  'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'),
 ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'),
 ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'),
 ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'),
 ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'),
 ('tests/test_visibility_completeness.py',
  '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
