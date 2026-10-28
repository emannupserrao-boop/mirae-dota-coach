"""Synthetic resolver contract tests. Foundation orchestration and Safety adapter are test-only."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError,asdict,fields,replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import missing_threat_resolver as resolver
from coach02.missing_threat_resolver import (
    MissingResolutionStatus as Status, MissingResolutionReason as Reason,
    MissingThreatResolution, MissingThreatResolutionSnapshot, resolve_missing_threats,
)
from coach02.threat_observation import (
    ThreatProximity, ThreatSightingClaim, build_threat_observations,
)
from coach02.threat_absence_observation import (
    ThreatVisibilityAbsence, ThreatAbsenceClaim, build_threat_absence_observations,
)
from coach02.visibility_completeness import (
    VisibilityCompleteness as Completeness, VisibilityCompletenessClaim, build_visibility_completeness,
)
from coach02.observation_event import (
    ObservationEvent,ObservationSource,ClockStamp,ObservationTimingPolicy,TimestampBasis,project_event_time,
)
from coach02.temporal_evidence import (
    TemporalStatus,TemporalQuery,FreshnessPolicy,new_temporal_state,record_observations,evaluate_freshness,
)
from coach02.safety_evidence import RelevantThreatObservation,ThreatState
from coach02.decision import Freshness


def event_bundle(subjects,tick,now,ttl,kind):
    refs=tuple(kind+'.'+s for s in subjects)
    event=ObservationEvent('timeline',ObservationSource(kind,'synthetic','v1'),refs,
                           ClockStamp('clock',tick),ClockStamp('clock',tick))
    projection=project_event_time(event,ObservationTimingPolicy('source-v1',TimestampBasis.SOURCE))
    state=record_observations(new_temporal_state('timeline','clock'),refs,tick)
    temporal=evaluate_freshness(state,now,tuple(TemporalQuery(ref,FreshnessPolicy(kind+'-ttl',ttl)) for ref in refs))
    return event,projection,temporal


def prepare(positive_tick=100,absence_tick=110,positive_now=None,absence_now=None,
            positive_ttl=10,absence_ttl=10,positives=('A',),absences=('A',),
            assessments=(('A',Completeness.SUFFICIENT),),proximity=ThreatProximity.AWAY):
    pe,pp,pt=event_bundle(positives,positive_tick,
        max(positive_tick,absence_tick) if positive_now is None else positive_now,positive_ttl,'pos')
    ae,ap,at=event_bundle(absences,absence_tick,absence_tick if absence_now is None else absence_now,absence_ttl,'neg')
    positive=build_threat_observations(pe,pp,pt,
        tuple(ThreatSightingClaim(s,'pos.'+s,proximity,'pos-ttl') for s in positives))
    absence=build_threat_absence_observations(ae,ap,at,
        tuple(ThreatAbsenceClaim(s,'neg.'+s,ThreatVisibilityAbsence.NOT_VISIBLE,'neg-ttl') for s in absences))
    complete=build_visibility_completeness(absence,
        tuple(VisibilityCompletenessClaim(s,'neg.'+s,'scope-'+s,value,'assessment-v1') for s,value in assessments))
    return dict(positive=positive,absence=absence,complete=complete)


def resolve(bundle=None):
    b=prepare() if bundle is None else bundle
    return resolve_missing_threats(b['positive'],b['absence'],b['complete'])


def row(bundle=None): return resolve(bundle).resolutions[0]


def safety_for_test(resolution):
    """Explicit compatibility only; this does not select strategic relevance."""
    if resolution.status is not Status.MISSING or resolution.absence.temporal_status is not TemporalStatus.FRESH:
        raise ValueError('only_justified_fresh_missing_can_map')
    return RelevantThreatObservation(resolution.threat_id,ThreatState.MISSING,Freshness.FRESH)


class MissingThreatResolverTests(unittest.TestCase):
    def check_result(self,b,status,reason):
        r=row(b)
        self.assertIs(r.status,status);self.assertIs(r.reason,reason)
        self.assertEqual(r.missing_since_tick,r.absence.observed_tick if status is Status.MISSING else None)
        return r

    def test_01_status_enum(self):
        self.assertEqual({s.value for s in Status},{'MISSING','NOT_JUSTIFIED','CONFLICTED'})

    def test_02_no_not_missing(self):
        self.assertNotIn('NOT_MISSING',Status.__members__)
        self.assertNotIn('UNKNOWN',Status.__members__)

    def test_03_reason_enum(self):
        self.assertEqual({r.value for r in Reason},{
            'JUSTIFIED_MISSING','NO_PRIOR_POSITIVE_SIGHTING','NO_COMPLETENESS_ASSESSMENT',
            'COMPLETENESS_INSUFFICIENT','COMPLETENESS_UNKNOWN','ABSENCE_STALE',
            'SAME_TICK_POSITIVE_NEGATIVE_CONFLICT','NEWER_POSITIVE_SIGHTING'})

    def test_04_valid_status_reason_pairs(self):
        base=row()
        for reason in Reason:
            status=Status.MISSING if reason is Reason.JUSTIFIED_MISSING else Status.CONFLICTED if reason is Reason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT else Status.NOT_JUSTIFIED
            value=replace(base,status=status,reason=reason,missing_since_tick=110 if status is Status.MISSING else None)
            self.assertIs(value.reason,reason)

    def test_05_invalid_status_reason_pairs(self):
        base=row()
        for status in Status:
            for reason in Reason:
                valid=(status is Status.MISSING and reason is Reason.JUSTIFIED_MISSING or
                       status is Status.CONFLICTED and reason is Reason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT or
                       status is Status.NOT_JUSTIFIED and reason not in (Reason.JUSTIFIED_MISSING,Reason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT))
                if not valid:
                    with self.assertRaises(ValueError):
                        replace(base,status=status,reason=reason,missing_since_tick=110 if status is Status.MISSING else None)
        for changes in ({'status':'MISSING'},{'reason':'JUSTIFIED_MISSING'}):
            with self.assertRaises(TypeError): replace(base,**changes)

    def test_06_positive_required(self):
        b=prepare();b['positive']=None
        with self.assertRaises(TypeError): resolve(b)
    def test_07_absence_required(self):
        b=prepare();b['absence']={}
        with self.assertRaises(TypeError): resolve(b)
    def test_08_completeness_required(self):
        b=prepare();b['complete']=None
        with self.assertRaises(TypeError): resolve(b)

    def test_09_timeline_required(self):
        for key in ('positive','absence','complete'):
            b=prepare();b[key]=replace(b[key],timeline_id='other')
            with self.assertRaisesRegex(ValueError,'timeline_mismatch'): resolve(b)

    def test_10_same_clock_required(self):
        for key in ('positive','absence','complete'):
            b=prepare();b[key]=replace(b[key],selected_clock_id='other')
            with self.assertRaisesRegex(ValueError,'clock_mismatch'): resolve(b)

    def changed_binding(self,field,value):
        b=prepare();b['complete']=replace(b['complete'],**{field:value})
        with self.assertRaisesRegex(ValueError,'completeness_snapshot_binding_mismatch'): resolve(b)

    def test_11_exact_absence_id(self): self.changed_binding('absence_snapshot_id','other')
    def test_12_exact_event(self): self.changed_binding('event_id','other')
    def test_13_exact_projection(self): self.changed_binding('projection_id','other')
    def test_14_exact_tracker(self): self.changed_binding('tracker_state_id','other')
    def test_15_exact_temporal(self): self.changed_binding('temporal_snapshot_id','other')
    def test_16_exact_selected_tick(self): self.changed_binding('selected_tick',109)
    def test_17_exact_evaluated_tick(self): self.changed_binding('evaluated_at_tick',111)

    def test_18_empty_absence(self):
        self.assertEqual(resolve(prepare(absences=(),assessments=())).resolutions,())

    def test_19_positive_only_no_row(self):
        b=prepare(positives=('A','B'))
        self.assertEqual([r.threat_id for r in resolve(b).resolutions],['A'])

    def test_20_no_completeness(self):
        r=self.check_result(prepare(assessments=()),Status.NOT_JUSTIFIED,Reason.NO_COMPLETENESS_ASSESSMENT)
        self.assertIsNone(r.assessment)

    def test_21_insufficient(self):
        self.check_result(prepare(assessments=(('A',Completeness.INSUFFICIENT),)),Status.NOT_JUSTIFIED,Reason.COMPLETENESS_INSUFFICIENT)

    def test_22_unknown(self):
        self.check_result(prepare(assessments=(('A',Completeness.UNKNOWN),)),Status.NOT_JUSTIFIED,Reason.COMPLETENESS_UNKNOWN)

    def test_23_sufficient(self):
        self.check_result(prepare(),Status.MISSING,Reason.JUSTIFIED_MISSING)

    def test_24_stale_absence(self):
        self.check_result(prepare(absence_now=121),Status.NOT_JUSTIFIED,Reason.ABSENCE_STALE)

    def test_25_no_positive(self):
        r=self.check_result(prepare(positives=()),Status.NOT_JUSTIFIED,Reason.NO_PRIOR_POSITIVE_SIGHTING)
        self.assertIsNone(r.positive);self.assertIsNone(r.last_seen_tick)

    def test_26_fresh_positive(self):
        r=row();self.assertIs(r.positive.temporal_status,TemporalStatus.FRESH);self.assertIs(r.status,Status.MISSING)

    def test_27_stale_positive(self):
        r=row(prepare(positive_ttl=0))
        self.assertIs(r.positive.temporal_status,TemporalStatus.STALE);self.assertIs(r.status,Status.MISSING)

    def test_28_prior_positive(self):
        r=self.check_result(prepare(),Status.MISSING,Reason.JUSTIFIED_MISSING)
        self.assertLess(r.last_seen_tick,r.absence.observed_tick)

    def test_29_same_tick_conflict(self):
        self.check_result(prepare(positive_tick=110),Status.CONFLICTED,Reason.SAME_TICK_POSITIVE_NEGATIVE_CONFLICT)

    def test_30_newer_positive(self):
        self.check_result(prepare(positive_tick=112),Status.NOT_JUSTIFIED,Reason.NEWER_POSITIVE_SIGHTING)

    def test_31_last_seen(self): self.assertEqual(row().last_seen_tick,100)
    def test_32_missing_since(self): self.assertEqual(row().missing_since_tick,110)
    def test_33_non_missing_has_no_since(self):
        for b in (prepare(positive_tick=110),prepare(positive_tick=112),prepare(assessments=())):
            self.assertIsNone(row(b).missing_since_tick)

    def test_34_proximity_preserved(self):
        for value in ThreatProximity:
            self.assertIs(row(prepare(proximity=value)).positive.proximity,value)

    def test_35_positive_provenance(self):
        b=prepare();r=row(b)
        self.assertEqual(r.positive,b['positive'].observations[0])
        self.assertEqual(r.positive_snapshot_id,b['positive'].snapshot_id)

    def test_36_absence_provenance(self):
        b=prepare();r=row(b)
        self.assertEqual(r.absence,b['absence'].observations[0])
        self.assertEqual(r.absence_snapshot_id,b['absence'].snapshot_id)

    def test_37_scope_preserved(self): self.assertEqual(row().assessment.scope_id,'scope-A')
    def test_38_policy_preserved(self): self.assertEqual(row().assessment.assessment_policy_id,'assessment-v1')

    def test_39_exact_subject(self):
        self.check_result(prepare(positives=('B',)),Status.NOT_JUSTIFIED,Reason.NO_PRIOR_POSITIVE_SIGHTING)

    def test_40_no_ref_borrowing(self):
        b=prepare(positives=('B',))
        obs=replace(b['positive'].observations[0],ref='neg.A')
        b['positive']=replace(b['positive'],observations=(obs,))
        self.check_result(b,Status.NOT_JUSTIFIED,Reason.NO_PRIOR_POSITIVE_SIGHTING)

    def test_41_no_completeness_borrowing(self):
        b=prepare(absences=('A','B'),assessments=(('B',Completeness.SUFFICIENT),))
        rows=resolve(b).resolutions
        self.assertIs(rows[0].reason,Reason.NO_COMPLETENESS_ASSESSMENT)
        self.assertIs(rows[1].reason,Reason.NO_PRIOR_POSITIVE_SIGHTING)

    def test_42_multiple_independent(self):
        b=prepare(positives=('A','B'),absences=('A','B'),assessments=(('A',Completeness.SUFFICIENT),('B',Completeness.UNKNOWN)))
        a,b=resolve(b).resolutions
        self.assertEqual((a.threat_id,a.status),('A',Status.MISSING))
        self.assertEqual((b.threat_id,b.reason),('B',Reason.COMPLETENESS_UNKNOWN))

    def test_43_mixed_outcomes(self):
        b=prepare(positives=('A','B'),absences=('A','B','C'),
                  assessments=(('A',Completeness.SUFFICIENT),('B',Completeness.UNKNOWN),('C',Completeness.SUFFICIENT)))
        self.assertEqual([r.reason for r in resolve(b).resolutions],
                         [Reason.JUSTIFIED_MISSING,Reason.COMPLETENESS_UNKNOWN,Reason.NO_PRIOR_POSITIVE_SIGHTING])

    def test_44_order_by_subject(self):
        b=prepare(positives=('B','A'),absences=('B','A'),assessments=(('B',Completeness.SUFFICIENT),('A',Completeness.SUFFICIENT)))
        self.assertEqual([r.threat_id for r in resolve(b).resolutions],['A','B'])

    def test_45_empty_assessment_not_unknown(self):
        r=row(prepare(assessments=()))
        self.assertIsNone(r.assessment);self.assertIs(r.reason,Reason.NO_COMPLETENESS_ASSESSMENT)

    def test_46_silence_never_missing(self):
        self.assertEqual(resolve(prepare(absences=(),assessments=())).resolutions,())

    def test_47_negative_alone_never_missing(self):
        self.check_result(prepare(positives=(),assessments=()),Status.NOT_JUSTIFIED,Reason.NO_COMPLETENESS_ASSESSMENT)

    def test_48_sufficient_alone_never_missing(self):
        self.check_result(prepare(positives=()),Status.NOT_JUSTIFIED,Reason.NO_PRIOR_POSITIVE_SIGHTING)

    def test_49_stale_never_missing(self):
        self.assertIs(row(prepare(absence_now=121)).status,Status.NOT_JUSTIFIED)

    def test_50_newer_never_missing(self):
        self.assertIs(row(prepare(positive_tick=112)).status,Status.NOT_JUSTIFIED)

    def test_51_same_tick_never_missing(self):
        self.assertIs(row(prepare(positive_tick=110)).status,Status.CONFLICTED)

    def test_52_not_justified_not_not_missing(self):
        self.assertEqual(row(prepare(positives=())).status.value,'NOT_JUSTIFIED')
        self.assertNotIn('NOT_MISSING',Status.__members__)

    def test_53_conflict_not_missing(self):
        self.assertNotEqual(row(prepare(positive_tick=110)).status,Status.MISSING)

    def forbidden(self,names):
        tree=ast.parse(inspect.getsource(resolver))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in names for n in ast.walk(tree)))
        for cls in (MissingThreatResolution,MissingThreatResolutionSnapshot):
            self.assertFalse({f.name for f in fields(cls)} & names)

    def test_54_no_risk(self): self.forbidden({'risk','danger','danger_score'})
    def test_55_no_safety(self): self.forbidden({'safety','safe','unsafe'})
    def test_56_no_relevance(self): self.forbidden({'relevance','relevant','role','kill_potential'})
    def test_57_no_coverage(self): self.forbidden({'coverage','ward','map_control'})
    def test_58_no_recommendation(self): self.forbidden({'recommendation','action','route','authority'})
    def test_59_no_hero_logic(self):
        self.forbidden({'hero','inventory','level','gold','gpm','ability','mobility','damage','teleport'})
        # items() on the local subject dictionary is iteration, not inventory.
        tree=ast.parse(inspect.getsource(resolver))
        for n in ast.walk(tree):
            if isinstance(n,ast.Attribute) and n.attr=='items':
                self.assertEqual(ast.unparse(n.value),'absences')
    def test_60_no_prediction(self): self.forbidden({'movement','destination','arrival','speed'})
    def test_61_no_geometry(self): self.forbidden({'coordinates','distance','path','x','y'})
    def test_62_no_scores(self): self.forbidden({'score','confidence','probability','percentage'})

    def pure(self,sinks):
        b=prepare();expected=resolve(b);before={k:asdict(v) for k,v in b.items()}
        with ExitStack() as stack:
            for owner,name in sinks:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure resolver')))
            actual=resolve_missing_threats(b['positive'],b['absence'],b['complete'])
            identity=actual.snapshot_id
        self.assertEqual(expected,actual);self.assertEqual(identity,expected.snapshot_id)
        self.assertEqual(before,{k:asdict(v) for k,v in b.items()})

    def test_63_no_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])
    def test_64_no_io(self):
        import builtins,io,os,sqlite3,subprocess
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(sqlite3,'connect'),(subprocess,'Popen')])
    def test_65_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])
    def test_66_no_environment(self):
        import os
        class ForbiddenEnvironment(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',ForbiddenEnvironment()): self.pure([(os,'getenv')])
    def test_67_no_random(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])
    def test_68_no_global_state(self):
        before=dict(vars(resolver));expected=resolve()
        resolve(prepare(absences=(),assessments=()))
        self.assertEqual(expected,resolve());self.assertEqual(before,vars(resolver))
        for name,value in vars(resolver).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray,MissingThreatResolutionSnapshot))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(ast.parse(inspect.getsource(resolver)))))

    def test_69_snapshot_frozen(self):
        r=resolve()
        with self.assertRaises(FrozenInstanceError): r.resolved_at_tick=0
        self.assertIs(type(r.resolutions),tuple)
    def test_70_resolution_frozen(self):
        r=row()
        with self.assertRaises(FrozenInstanceError): r.status=Status.NOT_JUSTIFIED

    def test_71_canonical_identity(self):
        r=resolve()
        digest=hashlib.sha256(json.dumps(asdict(r),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(r.snapshot_id,'threat.missing_resolver.v1:snapshot:'+digest)
        self.assertEqual(r.snapshot_id,resolve().snapshot_id)

    def test_72_canonical_input_order(self):
        a=prepare(positives=('A','B'),absences=('A','B'),assessments=(('A',Completeness.SUFFICIENT),('B',Completeness.UNKNOWN)))
        b=prepare(positives=('B','A'),absences=('B','A'),assessments=(('B',Completeness.UNKNOWN),('A',Completeness.SUFFICIENT)))
        self.assertEqual(resolve(a),resolve(b))
        self.assertEqual(resolve(a).snapshot_id,resolve(b).snapshot_id)

    def test_73_reason_changes_id(self):
        a=resolve(prepare(assessments=(('A',Completeness.UNKNOWN),)))
        b=resolve(prepare(assessments=(('A',Completeness.INSUFFICIENT),)))
        self.assertNotEqual(a.snapshot_id,b.snapshot_id)

    def test_74_positive_snapshot_changes_id(self):
        b=prepare();first=resolve(b)
        b['positive']=replace(b['positive'],event_id='new-event')
        self.assertNotEqual(first.snapshot_id,resolve(b).snapshot_id)

    def test_75_absence_changes_id(self):
        b=prepare();first=resolve(b)
        b['absence']=replace(b['absence'],event_id='new-event')
        b['complete']=replace(b['complete'],event_id='new-event',absence_snapshot_id=b['absence'].snapshot_id)
        self.assertNotEqual(first.snapshot_id,resolve(b).snapshot_id)

    def test_76_completeness_changes_id(self):
        self.assertNotEqual(resolve().snapshot_id,resolve(prepare(assessments=())).snapshot_id)

    def test_77_scope_policy_changes_id(self):
        for field in ('scope_id','assessment_policy_id'):
            b=prepare();before=resolve(b)
            assessment=replace(b['complete'].assessments[0],**{field:'other'})
            b['complete']=replace(b['complete'],assessments=(assessment,))
            self.assertNotEqual(before.snapshot_id,resolve(b).snapshot_id)

    def test_78_resolved_tick_max(self):
        self.assertEqual(resolve(prepare(positive_now=150)).resolved_at_tick,150)
        self.assertEqual(resolve(prepare(absence_now=115)).resolved_at_tick,115)

    def test_79_resolution_tick_does_not_refresh(self):
        b=prepare(positive_now=150,absence_now=121)
        r=self.check_result(b,Status.NOT_JUSTIFIED,Reason.ABSENCE_STALE)
        self.assertEqual((r.last_seen_tick,r.absence.age_ticks,r.absence.temporal_status),(100,11,TemporalStatus.STALE))
        self.assertEqual(resolve(b).resolved_at_tick,150)

    def test_80_test_only_safety_missing(self):
        self.assertEqual(safety_for_test(row()),RelevantThreatObservation('A',ThreatState.MISSING,Freshness.FRESH))
    def test_81_no_safety_not_justified(self):
        with self.assertRaises(ValueError): safety_for_test(row(prepare(positives=())))
    def test_82_no_safety_conflict(self):
        with self.assertRaises(ValueError): safety_for_test(row(prepare(positive_tick=110)))

    def imports(self):
        tree=ast.parse(inspect.getsource(resolver))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def test_83_no_safety_import(self):
        self.assertNotIn('.safety_evidence',self.imports());self.assertNotIn('.decision',self.imports())
    def test_84_semantic_imports_only(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.threat_observation',
                                        '.threat_absence_observation','.visibility_completeness'})

    def test_85_no_backward_dependency(self):
        root=Path(resolver.__file__).resolve().parent.parent
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/threat_relevance.py', 'coach02/threat_state_assembly.py'})
        allowed_contracts = frozenset(('MissingThreatResolution', 'MissingThreatResolutionSnapshot', 'MissingResolutionStatus', 'MissingResolutionReason', 'ThreatAbsenceObservation', 'ThreatVisibilityAbsence', 'VisibilityCompletenessAssessment', 'VisibilityCompleteness'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats'))

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
                        if 'missing_threat_resolver' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('missing_threat_resolver' in (node.module or '').split('.') or
                               any(a.name == 'missing_threat_resolver' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'missing_threat_resolver') or
                                        (node.level == 0 and node.module == 'coach02.missing_threat_resolver'))
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
                                       and 'missing_threat_resolver' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .missing_threat_resolver import MissingThreatResolutionSnapshot',
            'from coach02.missing_threat_resolver import MissingThreatResolutionSnapshot as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.missing_threat_resolver as foundation',
            'from coach02 import missing_threat_resolver as foundation',
            'from .missing_threat_resolver import *',
            'from ..missing_threat_resolver import MissingThreatResolutionSnapshot',
            'from .missing_threat_resolver import MissingThreatResolutionSnapshot as Contract\nContract()',
            'from .missing_threat_resolver import MissingThreatResolutionSnapshot as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.missing_threat_resolver')",
            "from importlib import import_module as load\nload('coach02.missing_threat_resolver')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .missing_threat_resolver import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.missing_threat_resolver')"
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
            if path.relative_to(root).as_posix() == 'coach02/missing_threat_resolver.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))

    def guards(self):
        root=Path(resolver.__file__).resolve().parent.parent
        for filename,method,module in (
            ('test_threat_observation.py','test_70_no_backward_production_import_or_orchestration','threat_observation'),
            ('test_threat_absence_observation.py','test_70_no_backward_production_import_or_orchestration','threat_absence_observation'),
            ('test_visibility_completeness.py','test_69_no_backward_production_import','visibility_completeness')):
            tree=ast.parse((root/'tests'/filename).read_text())
            fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==method)
            selected=[n for n in fn.body if
                isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or
                isinstance(n,ast.FunctionDef) and n.name=='violations']
            self.assertEqual(len(selected),4)
            namespace={'ast':ast}
            exec(compile(ast.Module(body=selected,type_ignores=[]),filename,'exec'),namespace)
            yield module,namespace

    def test_86_guard_arbitrary_consumer_rejected(self):
        for module,g in self.guards():
            symbols=g['allowed_contracts']-({'TemporalStatus'} if module=='threat_absence_observation' else set())
            for symbol in symbols:
                source='from .'+module+' import '+symbol
                self.assertEqual(g['violations'](source,'coach02/missing_threat_resolver.py'),[])
                for target in ('coach02/arbitrary_future.py','coach02/service.py','run.py'):
                    self.assertTrue(g['violations'](source,target))
            if module=='threat_absence_observation':
                self.assertTrue(g['violations']('from .threat_absence_observation import TemporalStatus','coach02/missing_threat_resolver.py'))

    def test_87_guard_orchestration_rejected(self):
        for module,g in self.guards():
            sources=['from .'+module+' import *','import coach02.'+module+' as foundation',
                     "import importlib as loader; loader.import_module('coach02."+module+"')"]
            for op in ('project_event_time','new_temporal_state','record_observations','evaluate_freshness',
                       'build_threat_observations','build_threat_absence_observations','build_visibility_completeness'):
                sources.append('from .'+module+' import '+op+' as run; alias=run; alias()')
            for source in sources:
                with self.subTest(source=source):
                    self.assertTrue(g['violations'](source,'coach02/missing_threat_resolver.py'))
        self.assertFalse({ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(resolver))) if isinstance(n,ast.Call)} &
            {'project_event_time','new_temporal_state','record_observations','evaluate_freshness','build_threat_observations',
             'build_threat_absence_observations','build_visibility_completeness'})

    def test_88_production_hashes_preserved(self):
        root=Path(resolver.__file__).resolve().parent.parent
        for rel,sha in PRODUCTION_HASHES:
            with self.subTest(path=rel): self.assertEqual(hashlib.sha256((root/rel).read_bytes()).hexdigest().upper(),sha)

    def test_89_precedence_no_completeness_first(self):
        self.check_result(prepare(positive_tick=110,absence_now=121,assessments=()),Status.NOT_JUSTIFIED,Reason.NO_COMPLETENESS_ASSESSMENT)

    def test_90_precedence_completeness_before_stale_conflict(self):
        for value,reason in ((Completeness.UNKNOWN,Reason.COMPLETENESS_UNKNOWN),(Completeness.INSUFFICIENT,Reason.COMPLETENESS_INSUFFICIENT)):
            self.check_result(prepare(positive_tick=110,absence_now=121,assessments=(('A',value),)),Status.NOT_JUSTIFIED,reason)

    def test_91_precedence_stale_before_conflict_or_absent_positive(self):
        self.check_result(prepare(positive_tick=110,absence_now=121),Status.NOT_JUSTIFIED,Reason.ABSENCE_STALE)
        self.check_result(prepare(positives=(),absence_now=121),Status.NOT_JUSTIFIED,Reason.ABSENCE_STALE)

    def test_92_extra_completeness_rejected(self):
        b=prepare();a=replace(b['complete'].assessments[0],threat_id='extra',absence_ref='other')
        b['complete']=replace(b['complete'],assessments=b['complete'].assessments+(a,))
        with self.assertRaisesRegex(ValueError,'extra_completeness_subject'): resolve(b)

    def test_93_assessment_exact_binding_all_metadata(self):
        for field,value in (('absence_ref','wrong'),('source_id','wrong'),('observed_tick',109),
                            ('absence_temporal_status',TemporalStatus.STALE),('absence_age_ticks',1),
                            ('absence_last_observed_tick',109),('absence_temporal_policy_id','wrong'),('absence_max_age_ticks',11)):
            b=prepare();a=replace(b['complete'].assessments[0],**{field:value})
            b['complete']=replace(b['complete'],assessments=(a,))
            with self.assertRaisesRegex(ValueError,'assessment_absence_binding_mismatch'): resolve(b)

    def test_94_duplicate_subjects_rejected(self):
        for key,field in (('positive','observations'),('absence','observations'),('complete','assessments')):
            b=prepare();values=getattr(b[key],field)
            b[key]=replace(b[key],**{field:values+values})
            if key=='absence':
                b['complete']=replace(b['complete'],absence_snapshot_id=b['absence'].snapshot_id)
            with self.assertRaisesRegex(ValueError,'duplicate_'): resolve(b)

    def test_95_unsupported_temporal_states_rejected(self):
        for key in ('positive','absence'):
            for bad in (TemporalStatus.NEVER_SEEN,'FRESH',None):
                b=prepare();o=replace(b[key].observations[0],temporal_status=bad)
                b[key]=replace(b[key],observations=(o,))
                with self.assertRaisesRegex(ValueError,'supported_temporal_status_required'): resolve(b)

    def test_96_defensive_structural_types(self):
        for key,field in (('positive','observations'),('absence','observations'),('complete','assessments')):
            for bad in ([],(None,)):
                b=prepare();b[key]=replace(b[key],**{field:bad})
                with self.assertRaises(TypeError): resolve(b)
        for field in ('selected_tick','evaluated_at_tick'):
            b=prepare();b['positive']=replace(b['positive'],**{field:True})
            with self.assertRaises(TypeError): resolve(b)

    def test_97_reject_malformed_tick_or_visibility(self):
        for key,changes in (('positive',{'proximity':'AWAY'}),('absence',{'visibility':'NOT_VISIBLE'}),
                            ('positive',{'age_ticks':True}),('absence',{'observed_tick':109})):
            b=prepare();b[key]=replace(b[key],observations=(replace(b[key].observations[0],**changes),))
            with self.assertRaises((ValueError,TypeError)): resolve(b)

    def test_98_negative_ticks(self):
        r=row(prepare(positive_tick=-10,absence_tick=-1))
        self.assertEqual((r.last_seen_tick,r.missing_since_tick),(-10,-1))
        self.assertIs(r.status,Status.MISSING)

    def test_99_inputs_unchanged(self):
        b=prepare();before={k:asdict(v) for k,v in b.items()}
        resolve(b)
        self.assertEqual(before,{k:asdict(v) for k,v in b.items()})

    def test_100_invalid_resolution_time_metadata(self):
        base=row()
        for changes in ({'last_seen_tick':None},{'last_seen_tick':99},{'missing_since_tick':None},
                        {'missing_since_tick':100},{'last_seen_tick':True}):
            with self.assertRaises((ValueError,TypeError)): replace(base,**changes)
        n=row(prepare(positives=()))
        with self.assertRaises(ValueError): replace(n,missing_since_tick=110)

    def test_101_no_namespace_interpretation(self):
        tree=ast.parse(inspect.getsource(resolver))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in {'split','startswith','endswith','partition'} for n in ast.walk(tree)))

    def test_102_complete_metadata_preserved(self):
        b=prepare();r=row(b)
        self.assertEqual(r.assessment,b['complete'].assessments[0])
        self.assertEqual(r.completeness_snapshot_id,b['complete'].snapshot_id)
        self.assertEqual(r.positive.last_observed_tick,100)
        self.assertEqual(r.absence.temporal_policy_id,'neg-ttl')

    def test_103_no_authenticity_repair(self):
        b=prepare();b['complete']=replace(b['complete'],absence_snapshot_id=prepare(absence_tick=111)['absence'].snapshot_id)
        with self.assertRaises(ValueError): resolve(b)

    def test_104_upstream_row_order_preserves_resolution_order(self):
        b=prepare(positives=('A','B'),absences=('A','B'),assessments=(('A',Completeness.SUFFICIENT),('B',Completeness.UNKNOWN)))
        original=resolve(b)
        b['positive']=replace(b['positive'],observations=b['positive'].observations[::-1])
        b['absence']=replace(b['absence'],observations=b['absence'].observations[::-1])
        b['complete']=replace(b['complete'],absence_snapshot_id=b['absence'].snapshot_id,assessments=b['complete'].assessments[::-1])
        result=resolve(b)
        self.assertEqual([r.threat_id for r in result.resolutions],['A','B'])
        self.assertEqual([r.reason for r in original.resolutions],[r.reason for r in result.resolutions])
        # Upstream content identities bind their supplied ordering; never erase that provenance.
        self.assertNotEqual(original.snapshot_id,result.snapshot_id)


PRODUCTION_HASHES = (('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'))
