"""Synthetic context coverage; foundation orchestration and Safety mapping are test-only."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import strategic_coverage as coverage
from coach02.strategic_coverage import (
    StrategicCoverageState as State, StrategicCoverageClaim as Claim,
    StrategicCoverageObservation, StrategicCoverageSnapshot, build_strategic_coverage,
)
from coach02.observation_event import (
    ObservationEvent, ObservationSource, ClockStamp, TimestampBasis,
    ObservationTimingPolicy, project_event_time,
)
from coach02.temporal_evidence import (
    TemporalStatus, TemporalSnapshot, TemporalEvidenceStatus, FreshnessPolicy,
    TemporalQuery, new_temporal_state, record_observations, evaluate_freshness,
)
from coach02.safety_evidence import CoverageObservation
from coach02.decision import Truth, Freshness
from test_threat_observation import prepare


def claim(context='context-A', ref='ref.a', state=State.SUFFICIENT, policy='p', assessment='assessment-v1'):
    return Claim(context, ref, state, policy, assessment)


def build(bundle=None, claims=None):
    b = prepare() if bundle is None else bundle
    return build_strategic_coverage(b['event'], b['projection'], b['temporal'],
                                    (claim(),) if claims is None else claims)


def row(state=State.SUFFICIENT, **kwargs):
    return build(prepare(**kwargs), (claim(state=state),)).observations[0]


def safety_for_test(observation):
    """Lossy representational demonstration only; context selection belongs downstream."""
    if type(observation) is not StrategicCoverageObservation:
        raise TypeError('coverage_observation_required')
    if type(observation.coverage) is not State:
        raise ValueError('unsupported_coverage')
    truth = {State.SUFFICIENT: Truth.YES, State.INSUFFICIENT: Truth.NO, State.UNKNOWN: Truth.UNKNOWN}[observation.coverage]
    if observation.temporal_status is TemporalStatus.FRESH:
        freshness = Freshness.FRESH
    elif observation.temporal_status is TemporalStatus.STALE:
        freshness = Freshness.STALE
    else:
        raise ValueError('unsupported_temporal_status')
    return CoverageObservation(truth, freshness)


class StrategicCoverageTests(unittest.TestCase):
    def test_01_exact_enum(self):
        self.assertEqual({s.value for s in State}, {'SUFFICIENT', 'INSUFFICIENT', 'UNKNOWN'})

    def test_02_no_safety_states(self):
        self.assertTrue({'SAFE','UNSAFE','DANGEROUS','COMPLETE','VISIBLE','MISSING','YES','NO'}.isdisjoint(State.__members__))

    def test_03_valid_claim(self):
        self.assertEqual(asdict(claim()), dict(coverage_context_id='context-A', ref='ref.a',
                         coverage=State.SUFFICIENT, temporal_policy_id='p', assessment_policy_id='assessment-v1'))

    def test_04_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().coverage = State.UNKNOWN

    def test_05_blank_context(self):
        for bad in ('',' ',None,True,1):
            with self.assertRaises(ValueError): claim(context=bad)

    def test_06_blank_ref(self):
        for bad in ('','\t',None,True,1):
            with self.assertRaises(ValueError): claim(ref=bad)

    def test_07_blank_temporal_policy(self):
        for bad in ('','\n',None,True,1):
            with self.assertRaises(ValueError): claim(policy=bad)

    def test_08_blank_assessment_policy(self):
        for bad in ('',' ',None,True,1):
            with self.assertRaises(ValueError): claim(assessment=bad)

    def test_09_explicit_enum(self):
        for bad in ('SUFFICIENT','UNKNOWN',None,True,Truth.YES):
            with self.assertRaises(TypeError): claim(state=bad)

    def test_10_claim_tuple(self):
        b = prepare()
        for bad in ([claim()],None,('bad',),{claim()}):
            with self.assertRaises(TypeError):
                build_strategic_coverage(b['event'],b['projection'],b['temporal'],bad)

    def test_11_duplicate_context_adversarial_G(self):
        b = prepare(refs=('ref.a','ref.b'))
        for other in (claim(),claim(ref='ref.b'),claim(state=State.UNKNOWN),claim(assessment='v2')):
            with self.assertRaisesRegex(ValueError,'duplicate_coverage_context_id'): build(b,(claim(),other))

    def test_12_claim_order(self):
        b = prepare(refs=('ref.b','ref.a'))
        claims = (claim('B','ref.b',State.UNKNOWN),claim())
        self.assertEqual(build(b,claims),build(b,claims[::-1]))

    def test_13_empty_claims_adversarial_E(self):
        result = build(claims=())
        self.assertEqual(result.observations,())
        self.assertTrue(result.event_id)

    def test_14_event_required(self):
        b = prepare(); b['event'] = None
        with self.assertRaises(TypeError): build(b)

    def test_15_projection_required(self):
        b = prepare(); b['projection'] = {}
        with self.assertRaises(TypeError): build(b)

    def test_16_temporal_snapshot_required(self):
        b = prepare(); b['temporal'] = b['state']
        with self.assertRaises(TypeError): build(b)

    def test_17_event_id_binding(self):
        b = prepare(); b['projection'] = replace(b['projection'],event_id='other')
        with self.assertRaisesRegex(ValueError,'projection_event_mismatch'): build(b)

    def test_18_projection_timeline(self):
        b = prepare(); b['projection'] = replace(b['projection'],timeline_id='other')
        with self.assertRaisesRegex(ValueError,'projection_timeline_mismatch'): build(b)

    def test_19_projection_source(self):
        b = prepare(); b['projection'] = replace(b['projection'],source_id='other')
        with self.assertRaisesRegex(ValueError,'projection_source_mismatch'): build(b)

    def test_20_projection_refs(self):
        b = prepare(); b['projection'] = replace(b['projection'],refs=('other',))
        with self.assertRaisesRegex(ValueError,'projection_refs_mismatch'): build(b)

    def test_21_temporal_timeline(self):
        b = prepare(); b['temporal'] = replace(b['temporal'],timeline_id='other')
        with self.assertRaisesRegex(ValueError,'temporal_timeline_mismatch'): build(b)

    def test_22_temporal_clock(self):
        b = prepare(); b['temporal'] = replace(b['temporal'],clock_id='other')
        with self.assertRaisesRegex(ValueError,'temporal_clock_mismatch'): build(b)

    def test_23_evaluation_not_before_event(self):
        b = prepare(); b['temporal'] = replace(b['temporal'],evaluated_at_tick=99)
        with self.assertRaisesRegex(ValueError,'evaluation_precedes_occurrence'): build(b)

    def test_24_forged_projection(self):
        for changes in ({'selected_tick':99},{'selected_clock_id':'other'},{'timestamp_basis':TimestampBasis.RECEIPT}):
            b = prepare(); b['projection'] = replace(b['projection'],**changes)
            with self.assertRaisesRegex(ValueError,'projection_stamp_mismatch'): build(b)

    def test_25_ref_in_event_adversarial_H(self):
        b = prepare(policies=(('ref.a','p',10),('foreign','p',10)))
        with self.assertRaisesRegex(ValueError,'claim_ref_not_in_event'): build(b,(claim(ref='foreign'),))

    def test_26_temporal_entry_required(self):
        b = prepare(policies=())
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(b)

    def test_27_wrong_policy(self):
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(claims=(claim(policy='other'),))

    def test_28_ambiguous_entry(self):
        b = prepare(); b['temporal'] = replace(b['temporal'],entries=b['temporal'].entries*2)
        with self.assertRaisesRegex(ValueError,'ambiguous_temporal_entry'): build(b)

    def test_29_never_seen(self):
        with self.assertRaisesRegex(ValueError,'claim_occurrence_never_seen'): build(prepare(recorded=False))

    def test_30_exact_occurrence(self):
        b = prepare(); entry = replace(b['temporal'].entries[0],last_observed_tick=99,age_ticks=1)
        b['temporal'] = replace(b['temporal'],entries=(entry,))
        with self.assertRaisesRegex(ValueError,'exact_occurrence_tick_required'): build(b)

    def test_31_age_consistency(self):
        b = prepare(now=105); entry = replace(b['temporal'].entries[0],age_ticks=4)
        b['temporal'] = replace(b['temporal'],entries=(entry,))
        with self.assertRaisesRegex(ValueError,'inconsistent_temporal_age'): build(b)

    def check_axes(self,state,now,status):
        observation = row(state,now=now)
        self.assertIs(observation.coverage,state)
        self.assertIs(observation.temporal_status,status)
        self.assertEqual(observation.age_ticks,now-100)
        return observation

    def test_32_fresh_sufficient_adversarial_A(self):
        self.check_axes(State.SUFFICIENT,105,TemporalStatus.FRESH)

    def test_33_fresh_insufficient_adversarial_B(self):
        self.check_axes(State.INSUFFICIENT,105,TemporalStatus.FRESH)

    def test_34_fresh_unknown_adversarial_C(self):
        self.check_axes(State.UNKNOWN,105,TemporalStatus.FRESH)

    def test_35_stale_sufficient_adversarial_D(self):
        self.check_axes(State.SUFFICIENT,111,TemporalStatus.STALE)

    def test_36_stale_insufficient(self):
        self.check_axes(State.INSUFFICIENT,111,TemporalStatus.STALE)

    def test_37_stale_unknown(self):
        self.check_axes(State.UNKNOWN,111,TemporalStatus.STALE)

    def test_38_stale_preserves_historical_state(self):
        for state in State:
            fresh,stale = row(state,now=100),row(state,now=1000)
            self.assertIs(fresh.coverage,stale.coverage)
            self.assertEqual(stale.observed_tick,fresh.observed_tick)

    def test_39_no_default(self):
        with self.assertRaises(TypeError): Claim('context-A','ref.a',temporal_policy_id='p',assessment_policy_id='p2')
        with self.assertRaises(TypeError): Claim('context-A','ref.a',State.SUFFICIENT,'p')
        self.assertTrue(all(p.default is inspect.Parameter.empty for p in inspect.signature(Claim).parameters.values()))

    def test_40_unknown_distinct(self):
        unknown,insufficient = row(State.UNKNOWN),row(State.INSUFFICIENT)
        self.assertNotEqual(unknown,insufficient)
        self.assertIsNot(unknown.coverage,insufficient.coverage)

    def test_41_empty_not_unknown(self):
        self.assertNotEqual(build(claims=()).snapshot_id,build(claims=(claim(state=State.UNKNOWN),)).snapshot_id)
        self.assertEqual(build(claims=()).observations,())

    def test_42_contexts_independent_adversarial_F(self):
        b = prepare(refs=('ref.a','ref.b'))
        output = build(b,(claim(),claim('context-B','ref.b',State.UNKNOWN)))
        self.assertEqual([(o.coverage_context_id,o.coverage) for o in output.observations],
                         [('context-A',State.SUFFICIENT),('context-B',State.UNKNOWN)])

    def test_43_no_ref_borrowing(self):
        b = prepare(refs=('ref.a','ref.b'),policies=(('ref.a','p',10),))
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(b,(claim('B','ref.b'),))

    def test_44_no_policy_borrowing(self):
        b = prepare(refs=('ref.a','ref.b'),policies=(('ref.a','a-policy',10),('ref.b','b-policy',10)))
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(b,(claim('B','ref.b',policy='a-policy'),))

    def test_45_cross_event_refresh_adversarial_I(self):
        with self.assertRaisesRegex(ValueError,'exact_occurrence_tick_required'):
            build(prepare(source_tick=100,reobserve=110,now=110))

    def test_46_source_basis(self):
        b = prepare(basis=TimestampBasis.SOURCE)
        self.assertEqual(build(b).observations[0].observed_tick,b['event'].source_stamp.tick)

    def test_47_receipt_basis(self):
        b = prepare(basis=TimestampBasis.RECEIPT)
        self.assertEqual(build(b).observations[0].observed_tick,b['event'].receipt_stamp.tick)
        self.assertEqual(build(b).selected_tick,103)

    def test_48_negative_ticks(self):
        o = row(source_tick=-100,now=-95)
        self.assertEqual((o.observed_tick,o.last_observed_tick,o.age_ticks),(-100,-100,5))

    def test_49_equal_ticks(self):
        o = row(source_tick=100,now=100,reobserve=100)
        self.assertEqual(o.age_ticks,0)
        self.assertIs(o.temporal_status,TemporalStatus.FRESH)

    def test_50_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().selected_tick = 0

    def test_51_observation_frozen(self):
        with self.assertRaises(FrozenInstanceError): row().coverage = State.UNKNOWN

    def test_52_canonical_identity(self):
        result = build()
        encoded = json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'strategic.coverage_observation.v1:snapshot:'+hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result.snapshot_id,build().snapshot_id)

    def test_53_order_identity(self):
        b = prepare(refs=('ref.b','ref.a')); claims = (claim(),claim('B','ref.b',State.UNKNOWN))
        self.assertEqual(build(b,claims).snapshot_id,build(b,claims[::-1]).snapshot_id)

    def test_54_state_identity(self):
        self.assertEqual(len({build(claims=(claim(state=s),)).snapshot_id for s in State}),3)

    def test_55_context_identity(self):
        self.assertNotEqual(build(claims=(claim('A'),)).snapshot_id,build(claims=(claim('B'),)).snapshot_id)

    def test_56_temporal_policy_identity(self):
        b = prepare(policies=(('ref.a','p',10),('ref.a','other',10)))
        self.assertNotEqual(build(b).snapshot_id,build(b,(claim(policy='other'),)).snapshot_id)

    def test_57_assessment_policy_identity(self):
        self.assertNotEqual(build().snapshot_id,build(claims=(claim(assessment='v2'),)).snapshot_id)

    def test_58_event_identity(self):
        b = prepare(); first = build(b)
        b['event'] = replace(b['event'],source=replace(b['event'].source,schema_id='schema-v2'))
        b['projection'] = replace(b['projection'],event_id=b['event'].event_id)
        self.assertNotEqual(first.snapshot_id,build(b).snapshot_id)

    def test_59_projection_identity(self):
        b = prepare(); first = build(b)
        b['projection'] = replace(b['projection'],timing_policy_id='other-timing')
        self.assertNotEqual(first.snapshot_id,build(b).snapshot_id)

    def test_60_tracker_identity(self):
        self.assertNotEqual(build().snapshot_id,build(prepare(extra_marks=('unqueried',))).snapshot_id)

    def test_61_temporal_identity(self):
        results = [build(prepare(now=t)) for t in (100,101,111)]
        self.assertEqual(len({r.snapshot_id for r in results}),3)
        self.assertEqual([r.observations[0].temporal_status for r in results],
                         [TemporalStatus.FRESH,TemporalStatus.FRESH,TemporalStatus.STALE])

    def imports(self):
        tree = ast.parse(inspect.getsource(coverage))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def test_62_no_completeness_import(self):
        self.assertNotIn('.visibility_completeness',self.imports())

    def test_63_no_threat_imports(self):
        self.assertTrue({'.threat_observation','.threat_absence_observation','.missing_threat_resolver',
                         '.threat_relevance'}.isdisjoint(self.imports()))

    def test_64_no_safety_production_import(self):
        self.assertNotIn('.safety_evidence',self.imports())

    def test_65_no_decision_import(self):
        self.assertNotIn('.decision',self.imports())

    def test_66_no_coverage_calculation(self):
        self.assertEqual(tuple(inspect.signature(build_strategic_coverage).parameters),
                         ('event','projection','temporal_snapshot','claims'))
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.observation_event','.temporal_evidence'})
        for state in State: self.assertIs(row(state).coverage,state)

    def forbidden_attributes(self,names):
        tree = ast.parse(inspect.getsource(coverage))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in names for n in ast.walk(tree)))

    def test_67_no_ward_logic(self):
        self.forbidden_attributes({'wards','ward','sentry','observer','vision_radius'})

    def test_68_no_fog_logic(self):
        self.forbidden_attributes({'fog','fog_of_war','minimap','scan'})

    def test_69_no_map_geometry(self):
        self.forbidden_attributes({'polygon','polygons','geometry','camera','line_of_sight'})

    def test_70_no_hero_vision(self):
        self.forbidden_attributes({'hero','allies','tower','vision','abilities'})

    def test_71_no_coordinates(self):
        self.forbidden_attributes({'coordinates','x','y','distance','path','pathfinding','speed'})

    def output_fields(self):
        return {f.name for cls in (StrategicCoverageObservation,StrategicCoverageSnapshot) for f in fields(cls)}

    def test_72_no_score(self):
        self.assertTrue({'score','confidence','probability'}.isdisjoint(self.output_fields()))

    def test_73_no_risk(self):
        self.assertTrue({'risk','danger','increased_risk','action','route_recommendation'}.isdisjoint(self.output_fields()))

    def test_74_no_safety(self):
        self.assertTrue({'safe','unsafe','safety'}.isdisjoint(self.output_fields()))

    def test_75_no_relevance(self):
        self.assertTrue({'relevance','relevant','exposure'}.isdisjoint(self.output_fields()))

    def test_76_no_threat_id(self):
        self.assertTrue({'threat_id','missing'}.isdisjoint(self.output_fields()))
        self.assertEqual(row().coverage_context_id,'context-A')

    def pure(self,sinks):
        b = prepare(now=111); expected = build(b); before = {k:asdict(v) for k,v in b.items()}
        with ExitStack() as stack:
            for owner,name in sinks:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure coverage builder')))
            result = build(b); identity = result.snapshot_id
        self.assertEqual(result,expected); self.assertEqual(identity,expected.snapshot_id)
        self.assertEqual(before,{k:asdict(v) for k,v in b.items()})

    def test_77_no_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_78_no_io(self):
        import builtins,io,os,sqlite3,subprocess
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(sqlite3,'connect'),(subprocess,'Popen')])

    def test_79_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_80_no_environment(self):
        import os
        class ForbiddenEnvironment(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',ForbiddenEnvironment()): self.pure([(os,'getenv')])

    def test_81_no_random(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid4'),(uuid,'uuid1')])

    def test_82_no_mutable_globals(self):
        before = dict(vars(coverage)); expected = build()
        build(prepare(now=1000000),())
        self.assertEqual(expected,build()); self.assertEqual(before,vars(coverage))
        for name,value in vars(coverage).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray,StrategicCoverageSnapshot))
        tree = ast.parse(inspect.getsource(coverage))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))

    def test_83_safety_mapping_sufficient(self):
        mapped = safety_for_test(row(State.SUFFICIENT))
        self.assertEqual(mapped,CoverageObservation(Truth.YES,Freshness.FRESH))
        self.assertEqual({f.name for f in fields(mapped)},{'sufficient','freshness'})

    def test_84_safety_mapping_insufficient(self):
        self.assertEqual(safety_for_test(row(State.INSUFFICIENT)),CoverageObservation(Truth.NO,Freshness.FRESH))

    def test_85_safety_mapping_unknown(self):
        self.assertEqual(safety_for_test(row(State.UNKNOWN)),CoverageObservation(Truth.UNKNOWN,Freshness.FRESH))

    def test_86_safety_freshness(self):
        for state,truth in ((State.SUFFICIENT,Truth.YES),(State.INSUFFICIENT,Truth.NO),(State.UNKNOWN,Truth.UNKNOWN)):
            self.assertEqual(safety_for_test(row(state,now=111)),CoverageObservation(truth,Freshness.STALE))
            self.assertEqual(safety_for_test(row(state,now=100)),CoverageObservation(truth,Freshness.FRESH))

    def test_87_mapping_no_risk_builder(self):
        from coach02 import safety_evidence
        with patch.object(safety_evidence,'build_risk_awareness',side_effect=AssertionError('risk forbidden')) as risk:
            for state in State: safety_for_test(row(state))
            risk.assert_not_called()
        calls = {ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(safety_for_test))) if isinstance(n,ast.Call)}
        self.assertNotIn('build_risk_awareness',calls)
        self.assertFalse(hasattr(safety_for_test(row()),'safe'))

    def guards(self):
        root = Path(coverage.__file__).resolve().parent.parent
        for filename,method,module in (
            ('test_observation_event.py','test_56_frozen_core_and_dependency_direction_unchanged','observation_event'),
            ('test_temporal_evidence.py','test_38_frozen_core_hashes_and_no_backward_import','temporal_evidence')):
            tree = ast.parse((root/'tests'/filename).read_text(encoding='utf-8'))
            fn = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==method)
            selected = [n for n in fn.body if
                isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
                {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or
                isinstance(n,ast.FunctionDef) and n.name=='violations']
            self.assertEqual(len(selected),4)
            namespace = {'ast':ast}
            exec(compile(ast.Module(body=selected,type_ignores=[]),filename,'exec'),namespace)
            yield module,namespace

    def test_88_dependency_direction(self):
        for module,g in self.guards():
            self.assertEqual(g['violations'](inspect.getsource(coverage),'coach02/strategic_coverage.py'),[])
        root = Path(coverage.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evidence_assembly.py'})
        allowed_contracts = frozenset(('StrategicCoverageSnapshot', 'StrategicCoverageObservation', 'StrategicCoverageState', 'TemporalStatus'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure'))

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            errors = []
            blocked_calls = set(operations) if consumer else set()
            if consumer:
                blocked_calls.update(allowed_contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'strategic_coverage' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('strategic_coverage' in (node.module or '').split('.') or
                               any(a.name == 'strategic_coverage' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'strategic_coverage') or
                                        (node.level == 0 and node.module == 'coach02.strategic_coverage'))
                        if not consumer or not exact_module:
                            errors.append('unauthorized production consumer or import path')
                        for alias in node.names:
                            if alias.name not in allowed_contracts:
                                errors.append('non-contract symbol import')
                            else:
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
                        consumer and isinstance(node.func, ast.Attribute) and node.func.attr in operations):
                    errors.append('constructor or orchestration call')
                if name in importers:
                    if consumer or any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                       and 'strategic_coverage' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .strategic_coverage import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evidence_assembly.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .strategic_coverage import *', 'import coach02.strategic_coverage',
                    'from coach02 import strategic_coverage',
                    "__import__('coach02.strategic_coverage')"]
        for symbol in allowed_contracts:
            rejected.append('from .strategic_coverage import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .strategic_coverage import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evidence_assembly.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/strategic_coverage.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_89_arbitrary_consumer_rejected(self):
        for module,g in self.guards():
            self.assertEqual(g['authorized_consumers'],frozenset({'coach02/threat_observation.py',
                             'coach02/threat_absence_observation.py','coach02/strategic_coverage.py', 'coach02/option_exposure.py'}))
            for symbol in g['allowed_contracts']:
                source = 'from .'+module+' import '+symbol
                self.assertEqual(g['violations'](source,'coach02/strategic_coverage.py'),[])
                for path in ('coach02/arbitrary_future.py','coach02/service.py','coach02/safety_evidence.py','run.py'):
                    self.assertTrue(g['violations'](source,path))

    def test_90_orchestration_rejected(self):
        for module,g in self.guards():
            sources = ['from .'+module+' import *','import coach02.'+module+' as foundation',
                       'from coach02 import '+module,
                       "import importlib as loader; loader.import_module('coach02."+module+"')"]
            for symbol in g['allowed_contracts']:
                sources.append('from .'+module+' import '+symbol+' as Contract; factory=Contract; factory()')
            for operation in g['operations']:
                sources.append('from .'+module+' import '+operation+' as run; alias=run; alias()')
                sources.append('runtime.'+operation+'()')
            for source in sources:
                with self.subTest(module=module,source=source):
                    self.assertTrue(g['violations'](source,'coach02/strategic_coverage.py'))
        calls = {ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(coverage))) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'project_event_time','new_temporal_state','record_observations','evaluate_freshness'})

    def test_91_existing_production_hashes(self):
        root = Path(coverage.__file__).resolve().parent.parent
        for name,sha in PRODUCTION_HASHES:
            with self.subTest(path=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),sha)

    def test_92_provenance_complete(self):
        b = prepare(now=105); result = build(b); o = result.observations[0]
        self.assertEqual((result.timeline_id,result.event_id,result.projection_id,result.tracker_state_id,result.temporal_snapshot_id),
                         (b['event'].timeline_id,b['event'].event_id,b['projection'].projection_id,b['state'].state_id,b['temporal'].snapshot_id))
        self.assertEqual((o.ref,o.source_id,o.observed_tick,o.last_observed_tick,o.age_ticks,o.temporal_policy_id,o.max_age_ticks,o.assessment_policy_id),
                         ('ref.a','producer',100,100,5,'p',10,'assessment-v1'))
        self.assertEqual({f.name for f in fields(o)},{'coverage_context_id','ref','coverage','source_id','observed_tick',
                         'temporal_status','last_observed_tick','age_ticks','temporal_policy_id','max_age_ticks','assessment_policy_id'})

    def test_93_no_namespace_parsing(self):
        tree = ast.parse(inspect.getsource(coverage))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in {'startswith','endswith','split','partition'} for n in ast.walk(tree)))
        for ref in ('ward.safe.lane','vision.route',' opaque ref '):
            o = build(prepare(refs=(ref,)),(claim(ref=ref,state=State.UNKNOWN),)).observations[0]
            self.assertEqual(o.ref,ref); self.assertIs(o.coverage,State.UNKNOWN)

    def test_94_conflicting_policy_threshold(self):
        b = prepare(refs=('ref.a','ref.b')); a,c = b['temporal'].entries
        b['temporal'] = replace(b['temporal'],entries=(a,replace(c,max_age_ticks=20)))
        with self.assertRaisesRegex(ValueError,'conflicting_temporal_policy'): build(b)

    def test_95_missing_source_stamp(self):
        b = prepare(); b['event'] = replace(b['event'],source_stamp=None)
        b['projection'] = replace(b['projection'],event_id=b['event'].event_id)
        with self.assertRaisesRegex(ValueError,'projection_stamp_mismatch'): build(b)

    def test_96_input_immutability(self):
        b = prepare(); claims = (claim(),); before = {k:asdict(v) for k,v in b.items()}
        original_claims = tuple(asdict(c) for c in claims)
        build(b,claims)
        self.assertEqual(before,{k:asdict(v) for k,v in b.items()})
        self.assertEqual(original_claims,tuple(asdict(c) for c in claims))

    def test_97_bad_temporal_structure(self):
        for entries in ([],({},),('bad',)):
            b = prepare(); b['temporal'] = replace(b['temporal'],entries=entries)
            with self.assertRaises(TypeError): build(b)
        for changes in ({'status':'fresh'},{'max_age_ticks':True},{'max_age_ticks':-1},
                        {'last_observed_tick':True},{'age_ticks':True},{'age_ticks':-1},{'ref':' '},{'policy_id':' '}):
            b = prepare(); entry = replace(b['temporal'].entries[0],**changes)
            b['temporal'] = replace(b['temporal'],entries=(entry,))
            with self.assertRaises((TypeError,ValueError)): build(b)

    def test_98_bad_header_even_empty_claims(self):
        for changes in ({'evaluated_at_tick':True},{'tracker_state_id':' '}):
            b = prepare(); b['temporal'] = replace(b['temporal'],**changes)
            with self.assertRaises((TypeError,ValueError)): build(b,())
        b = prepare(); b['projection'] = replace(b['projection'],selected_tick=99)
        with self.assertRaises(ValueError): build(b,())

    def test_99_multiple_temporal_policies(self):
        b = prepare(now=105,policies=(('ref.a','short',1),('ref.a','long',10)))
        short = build(b,(claim(policy='short'),)).observations[0]
        long = build(b,(claim(policy='long'),)).observations[0]
        self.assertIs(short.temporal_status,TemporalStatus.STALE)
        self.assertIs(long.temporal_status,TemporalStatus.FRESH)
        self.assertIs(short.coverage,long.coverage)
        self.assertEqual((short.max_age_ticks,long.max_age_ticks),(1,10))

    def test_100_completeness_coexists_adversarial_J(self):
        from coach02.visibility_completeness import VisibilityCompleteness
        from test_missing_threat_resolver import prepare as threat_bundle
        separate = threat_bundle()['complete'].assessments[0]
        o = row(State.UNKNOWN)
        self.assertIs(separate.completeness,VisibilityCompleteness.SUFFICIENT)
        self.assertIs(o.coverage,State.UNKNOWN)
        self.assertIsNot(State,VisibilityCompleteness)
        with self.assertRaises(TypeError): claim(state=VisibilityCompleteness.SUFFICIENT)

    def test_101_relevant_missing_coexists_adversarial_K(self):
        from test_threat_relevance import build as relevance_fixture,claim as relevance_claim
        from coach02.threat_relevance import ThreatRelevance
        from coach02.missing_threat_resolver import MissingResolutionStatus
        relevant = relevance_fixture((relevance_claim(context='context-A'),)).assessments[0]
        o = row(State.SUFFICIENT)
        self.assertIs(relevant.relevance,ThreatRelevance.RELEVANT)
        self.assertIs(relevant.missing_resolution.status,MissingResolutionStatus.MISSING)
        self.assertEqual(relevant.relevance_context_id,o.coverage_context_id)
        self.assertIs(o.coverage,State.SUFFICIENT)
        self.assertFalse(hasattr(o,'risk'))

    def test_102_exact_types_and_identifiers(self):
        class String(str): pass
        for kwargs in ({'context':String('A')},{'ref':String('ref.a')},{'policy':String('p')},{'assessment':String('v1')}):
            with self.assertRaises(ValueError): claim(**kwargs)
        b = prepare()
        class SubEvent(ObservationEvent): pass
        b['event'] = SubEvent(**b['event'].__dict__)
        with self.assertRaises(TypeError): build(b)

    def test_103_no_temporal_reclassification(self):
        b = prepare(); entry = replace(b['temporal'].entries[0],status=TemporalStatus.STALE)
        b['temporal'] = replace(b['temporal'],entries=(entry,))
        o = build(b).observations[0]
        self.assertIs(o.temporal_status,TemporalStatus.STALE)
        self.assertEqual(o.age_ticks,0)
        # This structural fabrication demonstrates trust in accepted upstream status,
        # not certification that the supplied classification is truthful.

    def test_104_opaque_unicode_no_trim_and_shared_ref(self):
        b = prepare(refs=(' ref.Ω ',)); claims = (claim(' context-A ',' ref.Ω ',assessment=' policy '),
                                                claim('context-B',' ref.Ω ',State.UNKNOWN))
        result = build(b,claims)
        self.assertEqual(result.observations[0].coverage_context_id,' context-A ')
        self.assertEqual(result.observations[0].assessment_policy_id,' policy ')
        self.assertEqual(result.observations[1].ref,' ref.Ω ')
        with self.assertRaises(ValueError): build(b,(claim(ref='ref.Ω'),))
        for changes in ({'coverage':'UNKNOWN'},{'temporal_status':TemporalStatus.NEVER_SEEN}):
            with self.assertRaises(ValueError): safety_for_test(replace(row(),**changes))


# Filled from the canonical manifest before any feature gate.
PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
