"""Synthetic explicit sightings. Only tests orchestrate foundations/downstream mapping."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import threat_observation as threat
from coach02.threat_observation import (
    ThreatProximity, ThreatSightingClaim, ThreatObservation, ThreatObservationSnapshot,
    build_threat_observations,
)
from coach02.observation_event import (
    ObservationSource, ObservationEvent, ClockStamp, TimestampBasis,
    ObservationTimingPolicy, project_event_time,
)
from coach02.temporal_evidence import (
    TemporalStatus, TemporalSnapshot, TemporalEvidenceStatus, FreshnessPolicy,
    TemporalQuery, new_temporal_state, record_observations, evaluate_freshness,
)
from coach02.safety_evidence import RelevantThreatObservation, ThreatState
from coach02.decision import Freshness


NEAR = ThreatProximity.NEARBY
AWAY = ThreatProximity.AWAY
FRESH = TemporalStatus.FRESH
STALE = TemporalStatus.STALE


def claim(threat_id='A', ref='ref.a', proximity=NEAR, policy_id='p'):
    return ThreatSightingClaim(threat_id, ref, proximity, policy_id)


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
    return build_threat_observations(bundle['event'],bundle['projection'],bundle['temporal'],
                                     (claim(),) if claims is None else claims)


def safety_for_test(observation):
    """Compatibility only, no relevance selection or production risk integration."""
    if observation.proximity is NEAR:
        state = ThreatState.VISIBLE_NEARBY
    elif observation.proximity is AWAY:
        state = ThreatState.VISIBLE_AWAY
    else:
        raise ValueError('unsupported_positive_sighting')
    if observation.temporal_status is FRESH:
        freshness = Freshness.FRESH
    elif observation.temporal_status is STALE:
        freshness = Freshness.STALE
    else:
        raise ValueError('unsupported_observed_temporal_status')
    return RelevantThreatObservation(observation.threat_id,state,freshness)


def pure_exercise(sinks):
    bundle = prepare(now=111)
    expected = build(bundle)
    before = asdict(bundle['state'])
    with ExitStack() as stack:
        for owner,name in sinks:
            stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure threat builder')))
        actual = build_threat_observations(bundle['event'],bundle['projection'],bundle['temporal'],(claim(),))
        identity = actual.snapshot_id
    return actual,expected,identity,before,asdict(bundle['state'])


class ThreatObservationTests(unittest.TestCase):
    def test_01_proximity_exact_enum(self):
        self.assertEqual({x.value for x in ThreatProximity},{'NEARBY','AWAY'})

    def test_02_no_missing_enum(self):
        self.assertNotIn('MISSING',ThreatProximity.__members__)

    def test_03_no_unknown_enum(self):
        self.assertNotIn('UNKNOWN',ThreatProximity.__members__)

    def test_04_valid_claim(self):
        self.assertEqual(asdict(claim()),dict(threat_id='A',ref='ref.a',proximity=NEAR,temporal_policy_id='p'))
        self.assertEqual(claim(' A ',' ref ',AWAY,' p ').threat_id,' A ')

    def test_05_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().proximity = AWAY

    def test_06_blank_threat_rejected(self):
        for bad in ('',' ','\t',None,True,1):
            with self.assertRaises(ValueError): claim(threat_id=bad)

    def test_07_blank_ref_rejected(self):
        for bad in ('',' ','\n',None,1):
            with self.assertRaises(ValueError): claim(ref=bad)

    def test_08_blank_policy_rejected(self):
        for bad in ('',' ','\t',None,1):
            with self.assertRaises(ValueError): claim(policy_id=bad)

    def test_09_invalid_proximity_rejected(self):
        for bad in ('NEARBY','MISSING','UNKNOWN',None,1,ThreatState.VISIBLE_NEARBY):
            with self.assertRaises(TypeError): claim(proximity=bad)

    def test_10_claim_tuple_required(self):
        bundle=prepare()
        for bad in ([claim()],None,('bad',),{claim()}):
            with self.assertRaises(TypeError):
                build_threat_observations(bundle['event'],bundle['projection'],bundle['temporal'],bad)

    def test_11_duplicate_threat_id_rejected(self):
        bundle = prepare(refs=('ref.a','ref.b'))
        for claims in ((claim(),claim()),(claim(),claim(ref='ref.b',proximity=AWAY))):
            with self.assertRaisesRegex(ValueError,'duplicate_threat_id'): build(bundle,claims)

    def test_12_claim_order_independent(self):
        bundle = prepare(refs=('ref.b','ref.a'))
        claims = (claim('B','ref.b',AWAY),claim())
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

    def test_29_stale_preserves_proximity(self):
        for proximity in (NEAR,AWAY):
            observation=build(prepare(now=111),(claim(proximity=proximity),)).observations[0]
            self.assertIs(observation.proximity,proximity)
            self.assertIs(observation.temporal_status,STALE)
            self.assertEqual((observation.observed_tick,observation.last_observed_tick,observation.age_ticks),(100,100,11))

    def test_30_fresh_preserves_proximity(self):
        for proximity in (NEAR,AWAY):
            observation=build(prepare(now=110),(claim(proximity=proximity),)).observations[0]
            self.assertIs(observation.proximity,proximity)
            self.assertIs(observation.temporal_status,FRESH)

    def test_31_stale_never_becomes_missing(self):
        for now in (111,120,1000000):
            result=build(prepare(now=now))
            self.assertEqual(len(result.observations),1)
            self.assertIs(result.observations[0].proximity,NEAR)
            self.assertIs(result.observations[0].temporal_status,STALE)

    def test_32_absence_never_creates_sighting(self):
        self.assertEqual(build(prepare(now=1000000),()).observations,())
        self.assertEqual(build(prepare(recorded=False),()).observations,())
        self.assertEqual(build(prepare(refs=()),()).observations,())

    def test_33_multiple_threats_isolated(self):
        bundle=prepare(refs=('ref.a','ref.b'),now=111,policies=(('ref.a','tight',10),('ref.b','wide',20)))
        result=build(bundle,(claim(policy_id='tight'),claim('B','ref.b',AWAY,'wide')))
        a,b=result.observations
        self.assertEqual((a.threat_id,a.ref,a.proximity,a.temporal_status,a.max_age_ticks),('A','ref.a',NEAR,STALE,10))
        self.assertEqual((b.threat_id,b.ref,b.proximity,b.temporal_status,b.max_age_ticks),('B','ref.b',AWAY,FRESH,20))

    def test_34_no_borrowing_another_ref_entry(self):
        bundle=prepare(refs=('ref.a','ref.b'),policies=(('ref.b','p',10),))
        with self.assertRaisesRegex(ValueError,'temporal_entry_required'): build(bundle,(claim(),))
        self.assertEqual(build(bundle,(claim('B','ref.b',AWAY),)).observations[0].ref,'ref.b')

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
        with self.assertRaises(FrozenInstanceError): observation.proximity=AWAY

    def test_43_snapshot_id_canonical(self):
        result=build(prepare())
        expected=hashlib.sha256(json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id,threat.RULESET+':snapshot:'+expected)
        self.assertEqual(result.snapshot_id,build(prepare()).snapshot_id)

    def test_44_order_independent_identity(self):
        bundle=prepare(refs=('ref.b','ref.a'))
        claims=(claim('B','ref.b',AWAY),claim())
        self.assertEqual(build(bundle,claims).snapshot_id,build(bundle,tuple(reversed(claims))).snapshot_id)

    def test_45_subject_changes_identity(self):
        bundle=prepare()
        self.assertNotEqual(build(bundle).snapshot_id,build(bundle,(claim('different'),)).snapshot_id)

    def test_46_proximity_changes_identity(self):
        bundle=prepare()
        self.assertNotEqual(build(bundle).snapshot_id,build(bundle,(claim(proximity=AWAY),)).snapshot_id)

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
                self.assertNotIsInstance(value,(dict,list,set,bytearray,ThreatObservationSnapshot))
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
        allowed={'threat_id','ref','proximity','source_id','observed_tick','temporal_status',
                 'last_observed_tick','age_ticks','temporal_policy_id','max_age_ticks'}
        self.assertEqual({f.name for f in fields(ThreatObservation)},allowed)
        self.assertEqual({f.name for f in fields(ThreatObservationSnapshot)},
            {'timeline_id','event_id','projection_id','tracker_state_id','temporal_snapshot_id',
             'selected_clock_id','selected_tick','evaluated_at_tick','observations'})

    def test_62_no_relevance_selection(self):
        bundle=prepare(refs=('ref.a','ref.b'))
        result=build(bundle,(claim(),claim('B','ref.b',AWAY)))
        self.assertEqual(len(result.observations),2)
        self.check_forbidden_attributes({'relevance','relevant','matchup','role','objective','damage','mobility'})

    def test_63_test_only_nearby_safety(self):
        value=safety_for_test(build(prepare()).observations[0])
        self.assertEqual(value,RelevantThreatObservation('A',ThreatState.VISIBLE_NEARBY,Freshness.FRESH))

    def test_64_test_only_away_safety(self):
        value=safety_for_test(build(prepare(),(claim(proximity=AWAY),)).observations[0])
        self.assertEqual(value,RelevantThreatObservation('A',ThreatState.VISIBLE_AWAY,Freshness.FRESH))

    def test_65_test_only_stale_safety(self):
        for proximity,state in ((NEAR,ThreatState.VISIBLE_NEARBY),(AWAY,ThreatState.VISIBLE_AWAY)):
            value=safety_for_test(build(prepare(now=111),(claim(proximity=proximity),)).observations[0])
            self.assertEqual(value,RelevantThreatObservation('A',state,Freshness.STALE))

    def test_66_adapter_has_no_missing_mapping(self):
        tree=ast.parse(inspect.getsource(safety_for_test))
        states={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='ThreatState'}
        self.assertEqual(states,{'VISIBLE_NEARBY','VISIBLE_AWAY'})
        bad=replace(build(prepare()).observations[0],temporal_status=TemporalStatus.NEVER_SEEN)
        with self.assertRaises(ValueError): safety_for_test(bad)
        with self.assertRaises(ValueError): safety_for_test(replace(bad,proximity='MISSING'))

    def check_hashes(self,group):
        root=Path(threat.__file__).resolve().parent.parent
        for rel,sha in ACCEPTED_HASHES:
            kind='event' if 'observation_event' in rel.lower() else 'temporal' if 'temporal_evidence' in rel.lower() else 'core'
            if kind==group:
                with self.subTest(path=rel): self.assertEqual(hashlib.sha256((root/rel).read_bytes()).hexdigest().upper(),sha)

    def test_67_observation_event_preserved(self): self.check_hashes('event')
    def test_68_temporal_preserved(self): self.check_hashes('temporal')
    def test_69_offline_core_preserved(self): self.check_hashes('core')

    def test_70_no_backward_production_import_or_orchestration(self):
        root=Path(threat.__file__).resolve().parent.parent
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/missing_threat_resolver.py', 'coach02/threat_relevance.py', 'coach02/threat_state_assembly.py'})
        allowed_contracts = frozenset(('ThreatObservation', 'ThreatObservationSnapshot', 'ThreatProximity', 'TemporalStatus'))
        operations = frozenset({'project_event_time', 'new_temporal_state',
                                'record_observations', 'evaluate_freshness', 'build_threat_observations'})

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
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
                blocked_calls.update(allowed_contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'threat_observation' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('threat_observation' in (node.module or '').split('.') or
                               any(a.name == 'threat_observation' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'threat_observation') or
                                        (node.level == 0 and node.module == 'coach02.threat_observation'))
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
                                       and 'threat_observation' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .threat_observation import ThreatObservationSnapshot',
            'from coach02.threat_observation import ThreatObservationSnapshot as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.threat_observation as foundation',
            'from coach02 import threat_observation as foundation',
            'from .threat_observation import *',
            'from ..threat_observation import ThreatObservationSnapshot',
            'from .threat_observation import ThreatObservationSnapshot as Contract\nContract()',
            'from .threat_observation import ThreatObservationSnapshot as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.threat_observation')",
            "from importlib import import_module as load\nload('coach02.threat_observation')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .threat_observation import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.threat_observation')"
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
            if path.relative_to(root).as_posix() == 'coach02/threat_observation.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))
        tree=ast.parse(inspect.getsource(threat))
        calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'project_event_time','record_observations','evaluate_freshness',
            'build_risk_awareness','RelevantThreatObservation','plan','eval','exec','__import__'})

    def test_71_adversarial_A_fresh_nearby(self):
        result=build(prepare());obs=result.observations[0]
        self.assertEqual((obs.proximity,obs.temporal_status),(NEAR,FRESH))
        self.assertEqual(obs.last_observed_tick,result.selected_tick)

    def test_72_adversarial_B_fresh_away(self):
        obs=build(prepare(),(claim(proximity=AWAY),)).observations[0]
        self.assertEqual((obs.proximity,obs.temporal_status),(AWAY,FRESH))

    def test_73_adversarial_C_stale_nearby(self):
        obs=build(prepare(now=111)).observations[0]
        self.assertEqual((obs.proximity,obs.temporal_status),(NEAR,STALE))
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
        result=build(prepare(refs=('ref.a','ref.b')),(claim(),claim('B','ref.b',AWAY)))
        self.assertEqual([(o.threat_id,o.proximity,o.temporal_status) for o in result.observations],
                         [('A',NEAR,FRESH),('B',AWAY,FRESH)])

    def test_78_adversarial_H_mixed_freshness(self):
        bundle=prepare(refs=('ref.a','ref.b'),now=111,policies=(('ref.a','wide',20),('ref.b','tight',10)))
        result=build(bundle,(claim(policy_id='wide'),claim('B','ref.b',AWAY,'tight')))
        self.assertEqual([(o.proximity,o.temporal_status,o.temporal_policy_id) for o in result.observations],
                         [(NEAR,FRESH,'wide'),(AWAY,STALE,'tight')])

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
        bundle=prepare(refs=('ref.a','ref.b'));claims=(claim('B','ref.b',AWAY),claim())
        before={k:asdict(v) for k,v in bundle.items()};before_claims=tuple(asdict(c) for c in claims)
        first=build(bundle,claims)
        self.assertEqual(before,{k:asdict(v) for k,v in bundle.items()})
        self.assertEqual(before_claims,tuple(asdict(c) for c in claims))
        bundle['temporal']=replace(bundle['temporal'],entries=tuple(reversed(bundle['temporal'].entries)))
        # TemporalSnapshot itself is an ordered input envelope: observations remain
        # canonical but the full upstream snapshot identity intentionally binds it.
        second=build(bundle,claims)
        self.assertEqual(first.observations,second.observations)

    def test_83_test_adapter_preserves_downstream_id_validation(self):
        obs=build(prepare(),(claim(threat_id=' opaque threat '),)).observations[0]
        self.assertEqual(obs.threat_id,' opaque threat ')
        with self.assertRaises(ValueError): safety_for_test(obs)

    def test_84_output_binds_upstream_envelopes_and_preserves_policy(self):
        bundle=prepare(now=110)
        result=build(bundle);obs=result.observations[0]
        self.assertEqual(result.event_id,bundle['event'].event_id)
        self.assertEqual(result.projection_id,bundle['projection'].projection_id)
        self.assertEqual(result.tracker_state_id,bundle['state'].state_id)
        self.assertEqual(result.temporal_snapshot_id,bundle['temporal'].snapshot_id)
        self.assertEqual((obs.temporal_status,obs.age_ticks,obs.max_age_ticks),
            (bundle['temporal'].entries[0].status,bundle['temporal'].entries[0].age_ticks,bundle['temporal'].entries[0].max_age_ticks))


# Accepted immutable hashes appended during preparation, before any test run.

ACCEPTED_HASHES = (('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'), ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'), ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'), ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'))

if __name__ == "__main__":
    unittest.main()
