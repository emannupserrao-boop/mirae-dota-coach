"""Synthetic explicit absence; orchestration is test-only, with no Safety mapping."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import threat_absence_observation as threat
from coach02.threat_absence_observation import (
    ThreatVisibilityAbsence, ThreatAbsenceClaim, ThreatAbsenceObservation, ThreatAbsenceObservationSnapshot,
    build_threat_absence_observations,
)
from coach02.observation_event import (
    ObservationSource, ObservationEvent, ClockStamp, TimestampBasis,
    ObservationTimingPolicy, project_event_time,
)
from coach02.temporal_evidence import (
    TemporalStatus, TemporalSnapshot, TemporalEvidenceStatus, FreshnessPolicy,
    TemporalQuery, new_temporal_state, record_observations, evaluate_freshness,
)


NOT_VISIBLE = ThreatVisibilityAbsence.NOT_VISIBLE
FRESH = TemporalStatus.FRESH
STALE = TemporalStatus.STALE


def claim(threat_id='A', ref='ref.a', visibility=NOT_VISIBLE, policy_id='p'):
    return ThreatAbsenceClaim(threat_id, ref, visibility, policy_id)


def prepare(refs=('ref.a',), source_tick=100, now=None, basis=TimestampBasis.SOURCE,
            policies=None, recorded=True, reobserve=None, extra_marks=()):
    event = ObservationEvent('timeline-A', ObservationSource('producer','opaque-kind','schema-v1'),
                             refs, ClockStamp('clock',source_tick+3), ClockStamp('clock',source_tick))
    projection = project_event_time(event,ObservationTimingPolicy('timing-v1',basis),'clock')
    state = new_temporal_state(event.timeline_id,projection.selected_clock_id)
    if recorded: state = record_observations(state,projection.refs,projection.selected_tick)
    if extra_marks: state = record_observations(state,extra_marks,projection.selected_tick)
    if reobserve is not None: state = record_observations(state,projection.refs,reobserve)
    policies = policies if policies is not None else tuple((ref,'p',10) for ref in refs)
    queries = tuple(TemporalQuery(ref,FreshnessPolicy(pid,ttl)) for ref,pid,ttl in policies)
    temporal = evaluate_freshness(state,projection.selected_tick if now is None else now,queries)
    return dict(event=event,projection=projection,temporal=temporal,state=state)


def build(bundle, claims=None):
    return build_threat_absence_observations(bundle['event'],bundle['projection'],bundle['temporal'],
                                     (claim(),) if claims is None else claims)


def pure_exercise(sinks):
    bundle = prepare(now=111)
    expected = build(bundle)
    before = asdict(bundle['state'])
    with ExitStack() as stack:
        for owner,name in sinks:
            stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure threat builder')))
        actual = build_threat_absence_observations(bundle['event'],bundle['projection'],bundle['temporal'],(claim(),))
        identity = actual.snapshot_id
    return actual,expected,identity,before,asdict(bundle['state'])


class ThreatAbsenceObservationTests(unittest.TestCase):
    def test_01_visibility_exact_enum(self):
        self.assertEqual({x.value for x in ThreatVisibilityAbsence},{'NOT_VISIBLE'})

    def test_02_no_missing_enum(self):
        self.assertNotIn('MISSING',ThreatVisibilityAbsence.__members__)

    def test_03_no_unknown_enum(self):
        self.assertNotIn('UNKNOWN',ThreatVisibilityAbsence.__members__)

    def test_04_valid_claim(self):
        self.assertEqual(asdict(claim()),dict(threat_id='A',ref='ref.a',visibility=NOT_VISIBLE,temporal_policy_id='p'))
        self.assertEqual(claim(' A ',' ref ',NOT_VISIBLE,' p ').threat_id,' A ')

    def test_05_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().visibility = NOT_VISIBLE

    def test_06_blank_threat_rejected(self):
        for bad in ('',' ','\t',None,True,1):
            with self.assertRaises(ValueError): claim(threat_id=bad)

    def test_07_blank_ref_rejected(self):
        for bad in ('',' ','\n',None,1):
            with self.assertRaises(ValueError): claim(ref=bad)

    def test_08_blank_policy_rejected(self):
        for bad in ('',' ','\t',None,1):
            with self.assertRaises(ValueError): claim(policy_id=bad)

    def test_09_invalid_visibility_rejected(self):
        for bad in ('NOT_VISIBLE','NEARBY','MISSING','UNKNOWN',None,1,TimestampBasis.SOURCE):
            with self.assertRaises(TypeError): claim(visibility=bad)

    def test_10_claim_tuple_required(self):
        bundle=prepare()
        for bad in ([claim()],None,('bad',),{claim()}):
            with self.assertRaises(TypeError):
                build_threat_absence_observations(bundle['event'],bundle['projection'],bundle['temporal'],bad)

    def test_11_duplicate_threat_id_rejected(self):
        bundle = prepare(refs=('ref.a','ref.b'))
        for claims in ((claim(),claim()),(claim(),claim(ref='ref.b',visibility=NOT_VISIBLE))):
            with self.assertRaisesRegex(ValueError,'duplicate_threat_id'): build(bundle,claims)

    def test_12_claim_order_independent(self):
        bundle = prepare(refs=('ref.b','ref.a'))
        claims = (claim('B','ref.b',NOT_VISIBLE),claim())
        self.assertEqual(build(bundle,claims),build(bundle,tuple(reversed(claims))))
        self.assertEqual(tuple(o.threat_id for o in build(bundle,claims).observations),('A','B'))

    def test_13_empty_claims(self):
        result = build(prepare(),())
        self.assertEqual(result.observations,())
        self.assertEqual(result.timeline_id,'timeline-A')

    def test_14_event_type_required(self):
        bundle = prepare();bundle['event']={}
        with self.assertRaises(TypeError): build(bundle)

    def test_15_projection_type_required(self):
        bundle = prepare();bundle['projection']=None
        with self.assertRaises(TypeError): build(bundle)

    def test_16_snapshot_type_required(self):
        bundle = prepare();bundle['temporal']={}
        with self.assertRaises(TypeError): build(bundle)

    def test_17_event_id_exact(self):
        bundle = prepare();bundle['projection']=replace(bundle['projection'],event_id='foreign-event')
        with self.assertRaisesRegex(ValueError,'projection_event_mismatch'): build(bundle)

    def test_18_projection_timeline(self):
        bundle = prepare();bundle['projection']=replace(bundle['projection'],timeline_id='foreign')
        with self.assertRaisesRegex(ValueError,'projection_timeline_mismatch'): build(bundle)

    def test_19_projection_source(self):
        bundle = prepare();bundle['projection']=replace(bundle['projection'],source_id='foreign')
        with self.assertRaisesRegex(ValueError,'projection_source_mismatch'): build(bundle)

    def test_20_projection_refs(self):
        bundle = prepare();bundle['projection']=replace(bundle['projection'],refs=('ref.b',))
        with self.assertRaisesRegex(ValueError,'projection_refs_mismatch'): build(bundle)

    def test_21_temporal_timeline(self):
        bundle = prepare();bundle['temporal']=replace(bundle['temporal'],timeline_id='foreign')
        with self.assertRaisesRegex(ValueError,'temporal_timeline_mismatch'): build(bundle)

    def test_22_temporal_clock(self):
        bundle = prepare();bundle['temporal']=replace(bundle['temporal'],clock_id='foreign')
        with self.assertRaisesRegex(ValueError,'temporal_clock_mismatch'): build(bundle)

    def test_23_evaluation_cannot_precede_occurrence(self):
        bundle = prepare();bundle['temporal']=replace(bundle['temporal'],evaluated_at_tick=99)
        with self.assertRaisesRegex(ValueError,'evaluation_precedes_occurrence'): build(bundle)

    def test_24_claim_ref_emitted_by_event(self):
        bundle = prepare(policies=(('ref.a','p',10),('foreign','p',10)))
        with self.assertRaisesRegex(ValueError,'claim_ref_not_in_event'): build(bundle,(claim(ref='foreign'),))

    def test_25_temporal_entry_required(self):
        bundle = prepare(policies=())
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(bundle)

    def test_26_exact_policy_key(self):
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'):
            build(prepare(),(claim(policy_id='different'),))

    def test_27_never_seen_rejected(self):
        bundle = prepare(recorded=False)
        self.assertIs(bundle['temporal'].entries[0].status,TemporalStatus.NEVER_SEEN)
        with self.assertRaisesRegex(ValueError,'claim_occurrence_never_seen'): build(bundle)

    def test_28_exact_tick_earlier_and_later(self):
        for tick in (99,101):
            bundle=prepare(now=110)
            entry=replace(bundle['temporal'].entries[0],last_observed_tick=tick,age_ticks=110-tick)
            bundle['temporal']=replace(bundle['temporal'],entries=(entry,))
            with self.assertRaisesRegex(ValueError,'exact_occurrence_tick_required'): build(bundle)

    def test_29_stale_preserves_visibility(self):
        for visibility in (NOT_VISIBLE,):
            observation=build(prepare(now=111),(claim(visibility=visibility),)).observations[0]
            self.assertIs(observation.visibility,visibility)
            self.assertIs(observation.temporal_status,STALE)
            self.assertEqual((observation.observed_tick,observation.last_observed_tick,observation.age_ticks),(100,100,11))

    def test_30_fresh_preserves_visibility(self):
        for visibility in (NOT_VISIBLE,):
            observation=build(prepare(now=110),(claim(visibility=visibility),)).observations[0]
            self.assertIs(observation.visibility,visibility)
            self.assertIs(observation.temporal_status,FRESH)

    def test_31_stale_never_becomes_missing(self):
        for now in (111,120,1000000):
            result=build(prepare(now=now))
            self.assertEqual(len(result.observations),1)
            self.assertIs(result.observations[0].visibility,NOT_VISIBLE)
            self.assertIs(result.observations[0].temporal_status,STALE)

    def test_32_silence_never_creates_absence(self):
        self.assertEqual(build(prepare(now=1000000),()).observations,())
        self.assertEqual(build(prepare(recorded=False),()).observations,())
        self.assertEqual(build(prepare(refs=()),()).observations,())

    def test_33_multiple_threats_isolated(self):
        bundle=prepare(refs=('ref.a','ref.b'),now=111,policies=(('ref.a','tight',10),('ref.b','wide',20)))
        result=build(bundle,(claim(policy_id='tight'),claim('B','ref.b',NOT_VISIBLE,'wide')))
        a,b=result.observations
        self.assertEqual((a.threat_id,a.ref,a.visibility,a.temporal_status,a.max_age_ticks),('A','ref.a',NOT_VISIBLE,STALE,10))
        self.assertEqual((b.threat_id,b.ref,b.visibility,b.temporal_status,b.max_age_ticks),('B','ref.b',NOT_VISIBLE,FRESH,20))

    def test_34_no_borrowing_another_ref_entry(self):
        bundle=prepare(refs=('ref.a','ref.b'),policies=(('ref.b','p',10),))
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(bundle,(claim(),))
        self.assertEqual(build(bundle,(claim('B','ref.b',NOT_VISIBLE),)).observations[0].ref,'ref.b')

    def test_35_no_borrowing_another_policy_entry(self):
        bundle=prepare(now=111,policies=(('ref.a','tight',10),('ref.a','wide',20)))
        self.assertIs(build(bundle,(claim(policy_id='tight'),)).observations[0].temporal_status,STALE)
        self.assertIs(build(bundle,(claim(policy_id='wide'),)).observations[0].temporal_status,FRESH)
        with self.assertRaises(ValueError): build(bundle,(claim(policy_id='unprovided'),))

    def test_36_cross_event_refresh_rejected(self):
        bundle=prepare(now=115,reobserve=110)
        self.assertEqual(bundle['temporal'].entries[0].last_observed_tick,110)
        with self.assertRaisesRegex(ValueError,'exact_occurrence_tick_required'): build(bundle)

    def test_37_source_projection(self):
        result=build(prepare())
        self.assertEqual(result.selected_tick,100)
        self.assertEqual(result.observations[0].observed_tick,100)

    def test_38_receipt_projection(self):
        result=build(prepare(basis=TimestampBasis.RECEIPT))
        self.assertEqual(result.selected_tick,103)
        self.assertEqual(result.observations[0].last_observed_tick,103)

    def test_39_negative_ticks(self):
        result=build(prepare(source_tick=-100,now=-90))
        self.assertEqual(result.selected_tick,-100)
        self.assertEqual(result.observations[0].age_ticks,10)
        self.assertIs(result.observations[0].temporal_status,FRESH)

    def test_40_equal_tick_compatible(self):
        bundle=prepare(source_tick=0)
        self.assertEqual(build(bundle),build(bundle))
        self.assertEqual(build(bundle).observations[0].age_ticks,0)

    def test_41_snapshot_frozen(self):
        result=build(prepare())
        with self.assertRaises(FrozenInstanceError): result.selected_tick=101
        self.assertIsInstance(result.observations,tuple)

    def test_42_observation_frozen(self):
        observation=build(prepare()).observations[0]
        with self.assertRaises(FrozenInstanceError): observation.visibility=NOT_VISIBLE

    def test_43_snapshot_id_canonical(self):
        result=build(prepare())
        expected=hashlib.sha256(json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id,threat.RULESET+':snapshot:'+expected)
        self.assertEqual(result.snapshot_id,build(prepare()).snapshot_id)

    def test_44_order_independent_identity(self):
        bundle=prepare(refs=('ref.b','ref.a'))
        claims=(claim('B','ref.b',NOT_VISIBLE),claim())
        self.assertEqual(build(bundle,claims).snapshot_id,build(bundle,tuple(reversed(claims))).snapshot_id)

    def test_45_subject_changes_identity(self):
        bundle=prepare()
        self.assertNotEqual(build(bundle).snapshot_id,build(bundle,(claim('different'),)).snapshot_id)


    def test_47_event_changes_identity(self):
        bundle=prepare();before=build(bundle)
        bundle['event']=replace(bundle['event'],source=replace(bundle['event'].source,schema_id='schema-v2'))
        bundle['projection']=project_event_time(bundle['event'],ObservationTimingPolicy('timing-v1',TimestampBasis.SOURCE))
        self.assertNotEqual(before.snapshot_id,build(bundle).snapshot_id)

    def test_48_projection_changes_identity(self):
        bundle=prepare();before=build(bundle)
        bundle['projection']=project_event_time(bundle['event'],ObservationTimingPolicy('timing-v2',TimestampBasis.SOURCE))
        self.assertNotEqual(before.snapshot_id,build(bundle).snapshot_id)

    def test_49_tracker_changes_identity(self):
        self.assertNotEqual(build(prepare()).snapshot_id,build(prepare(extra_marks=('unqueried',))).snapshot_id)

    def test_50_status_and_age_change_identity(self):
        outputs=[build(prepare(now=now)) for now in (100,101,111)]
        self.assertEqual(len({o.snapshot_id for o in outputs}),3)
        self.assertEqual([o.observations[0].temporal_status for o in outputs],[FRESH,FRESH,STALE])

    def check_pure(self,sinks):
        actual,expected,identity,before,after=pure_exercise(sinks)
        self.assertEqual(actual,expected);self.assertEqual(identity,expected.snapshot_id);self.assertEqual(before,after)

    def test_51_no_wall_clock(self):
        import time
        self.check_pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])
        tree=ast.parse(inspect.getsource(threat));imports=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imports.update(a.name for a in node.names)
            if isinstance(node,ast.ImportFrom): imports.add('.'*node.level+node.module)
        self.assertEqual(imports,{'dataclasses','enum','hashlib','json','.observation_event','.temporal_evidence'})

    def test_52_no_io(self):
        import builtins,io,os,sqlite3,subprocess
        self.check_pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(sqlite3,'connect'),(subprocess,'Popen')])

    def test_53_no_network(self):
        import socket,http.client
        self.check_pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_54_no_environment(self):
        import os
        class ForbiddenEnvironment(dict):
            def __getitem__(self,key): raise AssertionError('environment access')
            def get(self,*args): raise AssertionError('environment access')
            def __iter__(self): raise AssertionError('environment access')
        with patch.object(os,'environ',ForbiddenEnvironment()): self.check_pure([(os,'getenv')])

    def test_55_no_random_uuid(self):
        import random,uuid
        self.check_pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid4'),(uuid,'uuid1')])

    def test_56_no_mutable_globals_or_hidden_state(self):
        before=dict(vars(threat));expected=build(prepare())
        build(prepare(now=1000000),())
        self.assertEqual(expected,build(prepare()))
        self.assertEqual(before,vars(threat))
        for name,value in vars(threat).items():
            if not name.startswith('__'):
                self.assertNotIsInstance(value,(dict,list,set,bytearray,ThreatAbsenceObservationSnapshot))
        tree=ast.parse(inspect.getsource(threat))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))

    def test_57_no_namespace_parsing(self):
        tree=ast.parse(inspect.getsource(threat))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in {'startswith','endswith','split','partition'} for n in ast.walk(tree)))
        bundle=prepare(refs=(' opaque enemy.foo ',))
        result=build(bundle,(claim(ref=' opaque enemy.foo '),))
        self.assertEqual(result.observations[0].ref,' opaque enemy.foo ')

    def check_forbidden_attributes(self,names):
        tree=ast.parse(inspect.getsource(threat))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in names for n in ast.walk(tree)))

    def test_58_no_hero_logic(self):
        self.check_forbidden_attributes({'hero','items','level','gpm','gold','spells','build'})

    def test_59_no_coordinate_distance_logic(self):
        self.check_forbidden_attributes({'x','y','coordinates','distance','speed','travel_time','path'})

    def test_60_no_score(self):
        self.check_forbidden_attributes({'score','confidence','priority','probability'})

    def test_61_no_risk_safety_outputs(self):
        allowed={'threat_id','ref','visibility','source_id','observed_tick','temporal_status',
                 'last_observed_tick','age_ticks','temporal_policy_id','max_age_ticks'}
        self.assertEqual({f.name for f in fields(ThreatAbsenceObservation)},allowed)
        self.assertEqual({f.name for f in fields(ThreatAbsenceObservationSnapshot)},
            {'timeline_id','event_id','projection_id','tracker_state_id','temporal_snapshot_id',
             'selected_clock_id','selected_tick','evaluated_at_tick','observations'})

    def test_62_no_relevance_selection(self):
        bundle=prepare(refs=('ref.a','ref.b'))
        result=build(bundle,(claim(),claim('B','ref.b',NOT_VISIBLE)))
        self.assertEqual(len(result.observations),2)
        self.check_forbidden_attributes({'relevance','relevant','matchup','role','objective','damage','mobility'})


    def test_70_no_backward_production_import_or_orchestration(self):
        root=Path(threat.__file__).resolve().parent.parent
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/visibility_completeness.py', 'coach02/missing_threat_resolver.py'})
        allowed_contracts = frozenset(('ThreatAbsenceObservation', 'ThreatAbsenceObservationSnapshot', 'ThreatVisibilityAbsence', 'TemporalStatus'))
        operations = frozenset({'project_event_time', 'new_temporal_state',
                                'record_observations', 'evaluate_freshness', 'build_threat_absence_observations'})

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            contracts = (allowed_contracts - {'TemporalStatus'}
                         if relative_path == 'coach02/missing_threat_resolver.py' else allowed_contracts)
            errors = []
            infrastructure = relative_path == 'coach02/live_runtime_v01.py'
            # Generic infrastructure is separate from semantic contract consumers.
            generic_operations = frozenset((
                'project_event_time', 'new_temporal_state',
                'record_observations', 'evaluate_freshness',
            )) if infrastructure else frozenset()
            generic_imports = set()
            if infrastructure:
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        if any(set(alias.name.split('.')) & {'observation_event', 'temporal_evidence'}
                               for alias in node.names):
                            errors.append('infrastructure module import escape')
                    elif isinstance(node, ast.ImportFrom):
                        if any(alias.name == '*' for alias in node.names):
                            errors.append('infrastructure wildcard import')
                        if any(alias.name in {'observation_event', 'temporal_evidence'}
                               for alias in node.names):
                            errors.append('infrastructure module import escape')
                        for alias in node.names:
                            if alias.name not in generic_operations:
                                continue
                            module = ('observation_event' if alias.name == 'project_event_time'
                                      else 'temporal_evidence')
                            exact = ((node.level == 1 and node.module == module) or
                                     (node.level == 0 and node.module == 'coach02.' + module))
                            if not exact or alias.asname is not None:
                                errors.append('infrastructure operation import escape')
                            else:
                                generic_imports.add(alias.name)
                    elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        if any(isinstance(target, ast.Name) and target.id in generic_operations
                               for target in targets):
                            errors.append('infrastructure operation rebinding')
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if node.name in generic_operations:
                            errors.append('infrastructure operation rebinding')
                    elif isinstance(node, ast.arg) and node.arg in generic_operations:
                        errors.append('infrastructure operation shadowing')
            blocked_calls = set(operations) - generic_operations
            if infrastructure:
                blocked_calls.update({'getattr', 'eval', 'exec', '__import__',
                                      'build_threat_observations', 'build_threat_absence_observations',
                                      'build_visibility_completeness', 'build_visibility_completenesss',
                                      'resolve_missing_threats'})
            if consumer:
                blocked_calls.update(contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'threat_absence_observation' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('threat_absence_observation' in (node.module or '').split('.') or
                               any(a.name == 'threat_absence_observation' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'threat_absence_observation') or
                                        (node.level == 0 and node.module == 'coach02.threat_absence_observation'))
                        if not consumer or not exact_module:
                            errors.append('unauthorized production consumer or import path')
                        for alias in node.names:
                            if alias.name not in contracts:
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
                        if isinstance(value, ast.Name) and (value.id in blocked_calls or
                                                                 value.id in generic_operations):
                            for target in targets:
                                if isinstance(target, ast.Name) and target.id not in blocked_calls:
                                    blocked_calls.add(target.id)
                                    changed = True
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = ast.unparse(node.func)
                if name in generic_operations and name not in generic_imports:
                    errors.append('unbound infrastructure operation')
                if (name in blocked_calls or
                        isinstance(node.func, ast.Attribute) and node.func.attr in (operations | blocked_calls)):
                    errors.append('constructor or orchestration call')
                if name in importers:
                    if consumer or infrastructure or any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                       and 'threat_absence_observation' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .threat_absence_observation import ThreatAbsenceObservationSnapshot',
            'from coach02.threat_absence_observation import ThreatAbsenceObservationSnapshot as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.threat_absence_observation as foundation',
            'from coach02 import threat_absence_observation as foundation',
            'from .threat_absence_observation import *',
            'from ..threat_absence_observation import ThreatAbsenceObservationSnapshot',
            'from .threat_absence_observation import ThreatAbsenceObservationSnapshot as Contract\nContract()',
            'from .threat_absence_observation import ThreatAbsenceObservationSnapshot as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.threat_absence_observation')",
            "from importlib import import_module as load\nload('coach02.threat_absence_observation')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .threat_absence_observation import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.threat_absence_observation')"
        self.assertTrue(violations(dynamic, 'coach02/arbitrary_future_consumer.py'))
        # Recovery A: exact infrastructure authority, no semantic authority.
        live_path = 'coach02/live_runtime_v01.py'
        for operation, module in (
            ('project_event_time', 'observation_event'),
            ('new_temporal_state', 'temporal_evidence'),
            ('record_observations', 'temporal_evidence'),
            ('evaluate_freshness', 'temporal_evidence'),
        ):
            for import_path in ('.' + module, 'coach02.' + module):
                source = 'from ' + import_path + ' import ' + operation + '\n' + operation + '()'
                with self.subTest(infrastructure_allowed=source):
                    self.assertEqual(violations(source, live_path), [])
                for path in ('coach02/arbitrary_future_consumer.py',
                             'coach02/shadow_runtime_v01.py', 'coach02/shadow_journal_v01.py',
                             'coach02/live_runtime_v01.py.other'):
                    with self.subTest(infrastructure_wrong_path=path, operation=operation):
                        self.assertTrue(violations(source, path))
            rejected_infrastructure = (
                'from .' + module + ' import ' + operation + ' as call\ncall()',
                'from .' + module + ' import ' + operation + '\ncall = ' + operation + '\ncall()',
                'from .unapproved import ' + operation + '\n' + operation + '()',
                'from ..' + module + ' import ' + operation + '\n' + operation + '()',
                'from .' + module + ' import *\n' + operation + '()',
                'import coach02.' + module + ' as foundation\nfoundation.' + operation + '()',
                'from coach02 import ' + module + ' as foundation\nfoundation.' + operation + '()',
                "import importlib as loader\nloader.import_module('coach02." + module + "')",
                "from importlib import import_module as load\nload('coach02." + module + "')",
                "__import__('coach02." + module + "')",
                operation + '()',
                'from .' + module + ' import ' + operation + '\n' + operation + ' = replacement',
                'runtime.' + operation + '()',
            )
            for source in rejected_infrastructure:
                with self.subTest(infrastructure_rejected=source):
                    self.assertTrue(violations(source, live_path))
        for builder in ('build_threat_observations', 'build_threat_absence_observations',
                        'build_visibility_completeness', 'build_visibility_completenesss',
                        'resolve_missing_threats'):
            for source in (builder + '()', 'factory = ' + builder + '\nfactory()',
                           'runtime.' + builder + '()'):
                with self.subTest(infrastructure_semantic_builder=source):
                    self.assertTrue(violations(source, live_path))
        for source in valid + tuple(rejected):
            with self.subTest(infrastructure_semantic_contract=source):
                self.assertTrue(violations(source, live_path))
        paths = [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py'))
        for path in paths:
            if path.relative_to(root).as_posix() == 'coach02/threat_absence_observation.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))
        tree=ast.parse(inspect.getsource(threat))
        calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'project_event_time','record_observations','evaluate_freshness',
            'build_risk_awareness','RelevantThreatAbsenceObservation','plan','eval','exec','__import__'})

    def test_71_adversarial_A_fresh_absence(self):
        result=build(prepare());obs=result.observations[0]
        self.assertEqual((obs.visibility,obs.temporal_status),(NOT_VISIBLE,FRESH))
        self.assertEqual(obs.last_observed_tick,result.selected_tick)


    def test_73_adversarial_C_stale_absence(self):
        obs=build(prepare(now=111)).observations[0]
        self.assertEqual((obs.visibility,obs.temporal_status),(NOT_VISIBLE,STALE))
        self.assertEqual(obs.observed_tick,100)

    def test_74_adversarial_D_empty_not_safe(self):
        result=build(prepare(now=111),())
        self.assertEqual(result.observations,())
        self.assertFalse(hasattr(result,'safe'))
        self.assertFalse(hasattr(result,'risk'))

    def test_75_adversarial_E_never_seen(self):
        with self.assertRaisesRegex(ValueError,'claim_occurrence_never_seen'): build(prepare(recorded=False))

    def test_76_adversarial_F_cross_event_provenance(self):
        a=prepare();b=prepare(source_tick=110,now=115)
        state=record_observations(a['state'],b['projection'].refs,b['projection'].selected_tick)
        b['temporal']=evaluate_freshness(state,115,(TemporalQuery('ref.a',FreshnessPolicy('p',10)),))
        a['temporal']=b['temporal']
        with self.assertRaisesRegex(ValueError,'exact_occurrence_tick_required'): build(a)
        obs=build(b).observations[0]
        self.assertEqual((obs.observed_tick,obs.age_ticks,obs.temporal_status),(110,5,FRESH))

    def test_77_adversarial_G_two_threats(self):
        result=build(prepare(refs=('ref.a','ref.b')),(claim(),claim('B','ref.b',NOT_VISIBLE)))
        self.assertEqual([(o.threat_id,o.visibility,o.temporal_status) for o in result.observations],
                         [('A',NOT_VISIBLE,FRESH),('B',NOT_VISIBLE,FRESH)])

    def test_78_adversarial_H_mixed_freshness(self):
        bundle=prepare(refs=('ref.a','ref.b'),now=111,policies=(('ref.a','wide',20),('ref.b','tight',10)))
        result=build(bundle,(claim(policy_id='wide'),claim('B','ref.b',NOT_VISIBLE,'tight')))
        self.assertEqual([(o.visibility,o.temporal_status,o.temporal_policy_id) for o in result.observations],
                         [(NOT_VISIBLE,FRESH,'wide'),(NOT_VISIBLE,STALE,'tight')])

    def test_79_ambiguous_key_and_conflicting_threshold_rejected(self):
        bundle=prepare();entry=bundle['temporal'].entries[0]
        bundle['temporal']=replace(bundle['temporal'],entries=(entry,entry))
        with self.assertRaisesRegex(ValueError,'ambiguous_temporal_entry'): build(bundle)
        bundle=prepare(refs=('ref.a','ref.b'))
        a,b=bundle['temporal'].entries
        bundle['temporal']=replace(bundle['temporal'],entries=(a,replace(b,max_age_ticks=20)))
        with self.assertRaisesRegex(ValueError,'conflicting_temporal_policy'): build(bundle)

    def test_80_projection_cannot_forge_selected_stamp(self):
        for changes in ({'selected_tick':99},{'selected_clock_id':'foreign'},{'timestamp_basis':TimestampBasis.RECEIPT}):
            bundle=prepare();bundle['projection']=replace(bundle['projection'],**changes)
            with self.assertRaisesRegex(ValueError,'projection_stamp_mismatch'): build(bundle)

    def test_81_malformed_temporal_entries_defensive(self):
        for changes in ({'status':'fresh'},{'max_age_ticks':True},{'max_age_ticks':-1},
                        {'last_observed_tick':True},{'age_ticks':True},{'age_ticks':-1},{'age_ticks':2}):
            bundle=prepare();entry=replace(bundle['temporal'].entries[0],**changes)
            bundle['temporal']=replace(bundle['temporal'],entries=(entry,))
            with self.assertRaises((ValueError,TypeError)): build(bundle)
        for entries in ([],('bad',)):
            bundle=prepare();bundle['temporal']=replace(bundle['temporal'],entries=entries)
            with self.assertRaises(TypeError): build(bundle)
        for changes in ({'evaluated_at_tick':True},{'tracker_state_id':' '}):
            bundle=prepare();bundle['temporal']=replace(bundle['temporal'],**changes)
            with self.assertRaises((ValueError,TypeError)): build(bundle)

    def test_82_input_immutability_and_temporal_order(self):
        bundle=prepare(refs=('ref.a','ref.b'));claims=(claim('B','ref.b',NOT_VISIBLE),claim())
        before={k:asdict(v) for k,v in bundle.items()};before_claims=tuple(asdict(c) for c in claims)
        first=build(bundle,claims)
        self.assertEqual(before,{k:asdict(v) for k,v in bundle.items()})
        self.assertEqual(before_claims,tuple(asdict(c) for c in claims))
        bundle['temporal']=replace(bundle['temporal'],entries=tuple(reversed(bundle['temporal'].entries)))
        # TemporalSnapshot itself is an ordered input envelope: observations remain
        # canonical but the full upstream snapshot identity intentionally binds it.
        second=build(bundle,claims)
        self.assertEqual(first.observations,second.observations)


    def test_84_output_binds_upstream_envelopes_and_preserves_policy(self):
        bundle=prepare(now=110)
        result=build(bundle);obs=result.observations[0]
        self.assertEqual(result.event_id,bundle['event'].event_id)
        self.assertEqual(result.projection_id,bundle['projection'].projection_id)
        self.assertEqual(result.tracker_state_id,bundle['state'].state_id)
        self.assertEqual(result.temporal_snapshot_id,bundle['temporal'].snapshot_id)
        self.assertEqual((obs.temporal_status,obs.age_ticks,obs.max_age_ticks),
            (bundle['temporal'].entries[0].status,bundle['temporal'].entries[0].age_ticks,bundle['temporal'].entries[0].max_age_ticks))


    def test_85_age_consistency_required(self):
        for age in (1, 9, 11, True):
            bundle=prepare(now=110)
            entry=replace(bundle['temporal'].entries[0],age_ticks=age)
            bundle['temporal']=replace(bundle['temporal'],entries=(entry,))
            with self.assertRaises((ValueError,TypeError)): build(bundle)

    def test_86_silence_requires_explicit_event_and_claim(self):
        bundle=prepare()
        with self.assertRaises(TypeError):
            build_threat_absence_observations(None,bundle['projection'],bundle['temporal'],(claim(),))
        self.assertEqual(build(bundle,()).observations,())
        with self.assertRaisesRegex(ValueError,'claim_ref_not_in_event'):
            build(prepare(refs=('unrelated',)),(claim(),))
        for now in (100,111,1000000):
            self.assertEqual(build(prepare(now=now),()).observations,())

    def test_87_no_coverage_or_completeness_output(self):
        self.check_forbidden_attributes({'coverage','complete','reliability','trust','healthy'})
        result=build(prepare())
        for obj in (result,result.observations[0]):
            self.assertFalse({f.name for f in fields(obj)} & {'coverage','completeness','reliability','confidence'})

    def test_88_no_missing_output_or_direct_safety_mapping(self):
        tree=ast.parse(inspect.getsource(threat))
        self.assertEqual(set(ThreatVisibilityAbsence.__members__),{'NOT_VISIBLE'})
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='MISSING' for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Name) and n.id in {'ThreatState','RelevantThreatObservation','Freshness'} for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.ImportFrom) and n.module in {'safety_evidence','decision'} for n in ast.walk(tree)))
        for now in (100,111):
            obs=build(prepare(now=now)).observations[0]
            self.assertEqual(obs.visibility.value,'NOT_VISIBLE')
            self.assertFalse(hasattr(obs,'missing'))
        # No adapter exists here: negative visibility is not a Safety state.
        self.assertFalse(any(isinstance(n,ast.FunctionDef) and ('safety' in n.name or 'missing' in n.name) for n in tree.body))

    def test_89_same_tick_conflicting_siblings_remain_independent(self):
        from coach02.threat_observation import ThreatSightingClaim,ThreatProximity,build_threat_observations
        bundle=prepare()
        positive=build_threat_observations(bundle['event'],bundle['projection'],bundle['temporal'],
                                           (ThreatSightingClaim('A','ref.a',ThreatProximity.NEARBY,'p'),))
        before=asdict(positive)
        negative=build(bundle)
        self.assertEqual(positive.observations[0].threat_id,negative.observations[0].threat_id)
        self.assertEqual(positive.observations[0].observed_tick,negative.observations[0].observed_tick)
        self.assertEqual(positive.event_id,negative.event_id)
        self.assertEqual(positive.projection_id,negative.projection_id)
        self.assertEqual(positive.observations[0].temporal_status,negative.observations[0].temporal_status)
        self.assertEqual(positive.observations[0].proximity.value,'NEARBY')
        self.assertIs(negative.observations[0].visibility,NOT_VISIBLE)
        self.assertEqual(asdict(positive),before)
        self.assertEqual(build(bundle,()).observations,())
        # A stale positive is not an absence claim.
        stale=prepare(now=111)
        historical=build_threat_observations(stale['event'],stale['projection'],stale['temporal'],
                                            (ThreatSightingClaim('A','ref.a',ThreatProximity.NEARBY,'p'),))
        self.assertIs(historical.observations[0].temporal_status,STALE)
        self.assertEqual(build(stale,()).observations,())
        with self.assertRaises(TypeError):
            build(bundle,(ThreatSightingClaim('A','ref.a',ThreatProximity.NEARBY,'p'),))

    def test_90_no_sibling_dependency(self):
        root=Path(threat.__file__).resolve().parent
        for filename,forbidden in (('threat_absence_observation.py','threat_observation'),
                                   ('threat_observation.py','threat_absence_observation')):
            tree=ast.parse((root/filename).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    self.assertFalse(any(forbidden in a.name.split('.') for a in node.names))
                if isinstance(node,ast.ImportFrom):
                    self.assertNotIn(forbidden,(node.module or '').split('.'))
                    self.assertFalse(any(a.name==forbidden for a in node.names))

    def guards(self):
        # Extract only the existing pure AST guard, without running its test again.
        root=Path(threat.__file__).resolve().parent.parent
        for filename,method in (
            ('test_observation_event.py','test_56_frozen_core_and_dependency_direction_unchanged'),
            ('test_temporal_evidence.py','test_38_frozen_core_hashes_and_no_backward_import')):
            tree=ast.parse((root/'tests'/filename).read_text(encoding='utf-8'))
            fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==method)
            selected=[]
            for n in fn.body:
                if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'authorized_consumers','allowed_contracts','operations'} for t in n.targets):
                    selected.append(n)
                if isinstance(n,ast.FunctionDef) and n.name=='violations': selected.append(n)
            self.assertEqual(len(selected),4)
            scope={'ast':ast}
            exec(compile(ast.Module(body=selected,type_ignores=[]),filename,'exec'),scope)
            yield scope

    def test_91_guard_positive_consumer_remains_allowed(self):
        for guard in self.guards():
            module='observation_event' if 'ObservationEvent' in guard['allowed_contracts'] else 'temporal_evidence'
            for symbol in guard['allowed_contracts']:
                source=f'from .{module} import {symbol} as Contract\ndef bind(value: Contract): return type(value) is Contract'
                self.assertEqual(guard['violations'](source,'coach02/threat_observation.py'),[])

    def test_92_guard_absence_consumer_allowed(self):
        for guard in self.guards():
            self.assertEqual(guard['authorized_consumers'],frozenset({'coach02/threat_observation.py','coach02/threat_absence_observation.py','coach02/strategic_coverage.py', 'coach02/option_exposure.py'}))
            module='observation_event' if 'ObservationEvent' in guard['allowed_contracts'] else 'temporal_evidence'
            for symbol in guard['allowed_contracts']:
                self.assertEqual(guard['violations'](f'from .{module} import {symbol}','coach02/threat_absence_observation.py'),[])

    def test_93_guard_arbitrary_third_consumer_rejected(self):
        for guard in self.guards():
            module='observation_event' if 'ObservationEvent' in guard['allowed_contracts'] else 'temporal_evidence'
            symbol=sorted(guard['allowed_contracts'])[0]
            self.assertTrue(guard['violations'](f'from .{module} import {symbol}','coach02/arbitrary_future_consumer.py'))
            self.assertTrue(guard['violations'](f'from .{module} import {symbol}','coach02/subdir/threat_absence_observation.py'))

    def test_94_guard_orchestration_aliases_wildcards_dynamic_rejected(self):
        for guard in self.guards():
            module='observation_event' if 'ObservationEvent' in guard['allowed_contracts'] else 'temporal_evidence'
            symbol=sorted(guard['allowed_contracts'])[0]
            sources=[f'from .{module} import *',f'import coach02.{module} as foundation',
                     f"import importlib as loader\nloader.import_module('coach02.{module}')",
                     f'from .{module} import {symbol} as Contract\nfactory=Contract\nfactory()']
            for name in ('project_event_time','new_temporal_state','record_observations','evaluate_freshness'):
                sources.extend((f'from .{module} import {name} as run\nalias=run\nalias()',f'foundation.{name}()'))
            for consumer in guard['authorized_consumers']:
                for source in sources:
                    with self.subTest(consumer=consumer,source=source):
                        self.assertTrue(guard['violations'](source,consumer))

    def test_95_all_existing_production_hashes_preserved(self):
        root=Path(threat.__file__).resolve().parent.parent
        for rel,sha in PRODUCTION_HASHES:
            with self.subTest(path=rel):
                self.assertEqual(hashlib.sha256((root/rel).read_bytes()).hexdigest().upper(),sha)

    def test_96_temporal_classification_is_not_recalculated(self):
        # Upstream temporal status is authoritative. This binder checks occurrence
        # and age, not the TTL classification; no local policy is selected.
        bundle=prepare(now=110)
        entry=replace(bundle['temporal'].entries[0],status=STALE)
        bundle['temporal']=replace(bundle['temporal'],entries=(entry,))
        self.assertIs(build(bundle).observations[0].temporal_status,STALE)

    def test_97_explicit_opaque_association_is_preserved(self):
        bundle=prepare(refs=(' unrelated namespace ',))
        obs=build(bundle,(claim(' opaque threat ',' unrelated namespace ',NOT_VISIBLE,'p'),)).observations[0]
        self.assertEqual((obs.threat_id,obs.ref),(' opaque threat ',' unrelated namespace '))
        self.assertIs(obs.visibility,NOT_VISIBLE)

    def test_98_actual_equal_source_receipt_ticks(self):
        bundle=prepare()
        bundle['event']=replace(bundle['event'],receipt_stamp=bundle['event'].source_stamp)
        bundle['projection']=project_event_time(bundle['event'],ObservationTimingPolicy('timing-v1',TimestampBasis.SOURCE))
        self.assertEqual(build(bundle).observations[0].age_ticks,0)
        self.assertEqual(bundle['event'].source_stamp,bundle['event'].receipt_stamp)


PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
