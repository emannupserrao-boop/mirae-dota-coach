"""Offline explicit scope assessments; no Safety/MISSING conversion."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import visibility_completeness as scope
from coach02.visibility_completeness import (
    VisibilityCompleteness, VisibilityCompletenessClaim,
    VisibilityCompletenessAssessment, VisibilityCompletenessSnapshot,
    build_visibility_completeness,
)
from coach02.threat_absence_observation import (
    ThreatAbsenceClaim, ThreatVisibilityAbsence, ThreatAbsenceObservation,
    ThreatAbsenceObservationSnapshot, build_threat_absence_observations,
)
from coach02.observation_event import (
    ObservationEvent, ObservationSource, ClockStamp, TimestampBasis,
    ObservationTimingPolicy, project_event_time,
)
from coach02.temporal_evidence import (
    TemporalStatus, FreshnessPolicy, TemporalQuery,
    new_temporal_state, record_observations, evaluate_freshness,
)

SUFFICIENT = VisibilityCompleteness.SUFFICIENT
INSUFFICIENT = VisibilityCompleteness.INSUFFICIENT
UNKNOWN = VisibilityCompleteness.UNKNOWN
FRESH = TemporalStatus.FRESH
STALE = TemporalStatus.STALE


def claim(threat_id='A', absence_ref='ref.a', scope_id='scope-A',
          completeness=SUFFICIENT, policy='assessment-v1'):
    return VisibilityCompletenessClaim(threat_id, absence_ref, scope_id, completeness, policy)


def prepare(now=100, subjects=(('A', 'ref.a'),), tick=100, ttl=10):
    refs=tuple(ref for _,ref in subjects)
    event=ObservationEvent('timeline-A',ObservationSource('source-A','opaque','schema-v1'),
                           refs,ClockStamp('clock',tick+3),ClockStamp('clock',tick))
    projection=project_event_time(event,ObservationTimingPolicy('timing-v1',TimestampBasis.SOURCE))
    state=record_observations(new_temporal_state('timeline-A','clock'),refs,tick)
    temporal=evaluate_freshness(state,now,tuple(TemporalQuery(ref,FreshnessPolicy('fresh-v1',ttl)) for ref in refs))
    absence=build_threat_absence_observations(event,projection,temporal,
        tuple(ThreatAbsenceClaim(threat_id,ref,ThreatVisibilityAbsence.NOT_VISIBLE,'fresh-v1') for threat_id,ref in subjects))
    return dict(event=event,projection=projection,state=state,temporal=temporal,absence=absence)


def build(absence=None, claims=None):
    return build_visibility_completeness(prepare()['absence'] if absence is None else absence,
                                       (claim(),) if claims is None else claims)


class VisibilityCompletenessTests(unittest.TestCase):
    def test_01_enum_exact(self):
        self.assertEqual({x.value for x in VisibilityCompleteness},{'SUFFICIENT','INSUFFICIENT','UNKNOWN'})

    def test_02_no_missing_enum(self):
        self.assertNotIn('MISSING',VisibilityCompleteness.__members__)
        self.assertNotIn('NOT_MISSING',VisibilityCompleteness.__members__)

    def test_03_valid_claim(self):
        self.assertEqual(asdict(claim()),dict(threat_id='A',absence_ref='ref.a',scope_id='scope-A',
                         completeness=SUFFICIENT,assessment_policy_id='assessment-v1'))

    def test_04_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().completeness=UNKNOWN

    def check_blank(self, field):
        for bad in ('',' ','\t',None,True,1):
            # The whitespace tab case is supplied as a real character too.
            if bad=='\t': bad=chr(9)
            with self.subTest(field=field,value=bad):
                with self.assertRaises(ValueError): claim(**{field:bad})

    def test_05_blank_threat(self): self.check_blank('threat_id')
    def test_06_blank_ref(self): self.check_blank('absence_ref')
    def test_07_blank_scope(self): self.check_blank('scope_id')
    def test_08_blank_policy(self): self.check_blank('policy')

    def test_09_explicit_enum_only(self):
        for bad in ('SUFFICIENT','INSUFFICIENT','UNKNOWN',None,True,FRESH):
            with self.assertRaises(TypeError): claim(completeness=bad)

    def test_10_tuple_required(self):
        for bad in ([claim()],None,('bad',),{claim()}):
            with self.assertRaises(TypeError):
                build_visibility_completeness(prepare()['absence'],bad)

    def test_11_duplicate_threat_rejected(self):
        absence=prepare(subjects=(('A','ref.a'),('B','ref.b')))['absence']
        for claims in ((claim(),claim()),(claim(),claim(scope_id='other',completeness=UNKNOWN))):
            with self.assertRaisesRegex(ValueError,'duplicate_threat_id'): build(absence,claims)

    def test_12_order_independence(self):
        absence=prepare(subjects=(('B','ref.b'),('A','ref.a')))['absence']
        claims=(claim('B','ref.b',completeness=UNKNOWN),claim())
        self.assertEqual(build(absence,claims),build(absence,tuple(reversed(claims))))
        self.assertEqual([x.threat_id for x in build(absence,claims).assessments],['A','B'])

    def test_13_empty_valid(self):
        absence=prepare()['absence'];result=build(absence,())
        self.assertEqual(result.assessments,())
        self.assertEqual(result.absence_snapshot_id,absence.snapshot_id)

    def test_14_absence_snapshot_required(self):
        for bad in (None,{},(),prepare()['temporal']):
            with self.assertRaises(TypeError): build_visibility_completeness(bad,(claim(),))

    def test_15_exact_threat_required(self):
        with self.assertRaisesRegex(ValueError,'exact_absence_observation_required'):
            build(claims=(claim(threat_id='different'),))

    def test_16_exact_ref_required(self):
        with self.assertRaisesRegex(ValueError,'exact_absence_observation_required'):
            build(claims=(claim(absence_ref='other'),))

    def test_17_zero_match_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact_absence_observation_required'):
            build(prepare(subjects=())['absence'])

    def test_18_ambiguous_match_rejected(self):
        absence=prepare()['absence']
        with self.assertRaisesRegex(ValueError,'ambiguous_absence_observation'):
            build(replace(absence,observations=absence.observations*2))

    def check_axes(self, completeness, now, status):
        result=build(prepare(now=now)['absence'],(claim(completeness=completeness),))
        self.assertEqual((result.assessments[0].completeness,result.assessments[0].absence_temporal_status),
                         (completeness,status))
        self.assertFalse(hasattr(result,'missing'))

    def test_19_fresh_sufficient(self): self.check_axes(SUFFICIENT,100,FRESH)
    def test_20_fresh_insufficient(self): self.check_axes(INSUFFICIENT,100,FRESH)
    def test_21_fresh_unknown(self): self.check_axes(UNKNOWN,100,FRESH)
    def test_22_stale_sufficient(self): self.check_axes(SUFFICIENT,111,STALE)
    def test_23_stale_insufficient(self): self.check_axes(INSUFFICIENT,111,STALE)
    def test_24_stale_unknown(self): self.check_axes(UNKNOWN,111,STALE)

    def test_25_stale_does_not_mutate_completeness(self):
        for value in VisibilityCompleteness:
            for now in (100,110,111,100000):
                self.assertIs(build(prepare(now=now)['absence'],(claim(completeness=value),)).assessments[0].completeness,value)

    def test_26_no_default_completeness_or_policy(self):
        with self.assertRaises(TypeError): VisibilityCompletenessClaim('A','ref.a','scope-A')
        with self.assertRaises(TypeError): VisibilityCompletenessClaim('A','ref.a','scope-A',SUFFICIENT)

    def test_27_unknown_is_distinct(self):
        unknown=build(claims=(claim(completeness=UNKNOWN),))
        insufficient=build(claims=(claim(completeness=INSUFFICIENT),))
        self.assertNotEqual(unknown,insufficient)
        self.assertIs(unknown.assessments[0].completeness,UNKNOWN)

    def test_28_empty_never_creates_unknown(self):
        for now in (100,111):
            self.assertEqual(build(prepare(now=now)['absence'],()).assessments,())

    def forbidden(self, names):
        tree=ast.parse(inspect.getsource(scope))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in names for n in ast.walk(tree)))
        for cls in (VisibilityCompletenessClaim,VisibilityCompletenessAssessment,VisibilityCompletenessSnapshot):
            self.assertFalse({f.name for f in fields(cls)} & names)

    def test_29_no_missing_output(self):
        self.forbidden({'missing','not_missing','MISSING','NOT_MISSING'})

    def test_30_sufficient_never_derives_missing(self):
        for now in (100,111):
            value=build(prepare(now=now)['absence']).assessments[0]
            self.assertIs(value.completeness,SUFFICIENT)
            self.assertFalse(hasattr(value,'missing'))

    def test_31_fresh_sufficient_is_only_assessment(self):
        value=build().assessments[0]
        self.assertIs(type(value),VisibilityCompletenessAssessment)
        self.assertIs(value.absence_temporal_status,FRESH)
        self.assertIs(value.completeness,SUFFICIENT)

    def test_32_no_safety(self): self.forbidden({'safety','safe','ThreatState','RelevantThreatObservation'})
    def test_33_no_risk(self): self.forbidden({'risk','danger','dangerous'})
    def test_34_no_relevance(self): self.forbidden({'relevance','relevant','role','matchup'})
    def test_35_no_coverage(self): self.forbidden({'coverage','Coverage','map_coverage'})

    def imports(self):
        tree=ast.parse(inspect.getsource(scope))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def test_36_no_positive_import(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.threat_absence_observation'})
    def test_37_no_safety_import(self): self.assertNotIn('.safety_evidence',self.imports())
    def test_38_no_decision_import(self): self.assertNotIn('.decision',self.imports())

    def check_calls_absent(self,names):
        calls={ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(scope))) if isinstance(n,ast.Call)}
        self.assertFalse(calls & names)

    def test_39_no_event_orchestration(self):
        self.assertNotIn('.observation_event',self.imports())
        self.check_calls_absent({'ObservationEvent','ObservationTimingPolicy','project_event_time'})

    def test_40_no_temporal_orchestration(self):
        self.assertNotIn('.temporal_evidence',self.imports())
        self.check_calls_absent({'new_temporal_state','record_observations','evaluate_freshness','build_threat_absence_observations'})

    def check_pure(self,sinks):
        absence=prepare(now=111)['absence'];claims=(claim(),)
        expected=build(absence,claims);before=asdict(absence)
        with ExitStack() as stack:
            for owner,name in sinks:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure completeness')))
            actual=build_visibility_completeness(absence,claims)
            identity=actual.snapshot_id
        self.assertEqual(actual,expected)
        self.assertEqual(identity,expected.snapshot_id)
        self.assertEqual(asdict(absence),before)

    def test_41_no_wall_clock(self):
        import time
        self.check_pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_42_no_io(self):
        import builtins,io,os,sqlite3,subprocess
        self.check_pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(sqlite3,'connect'),(subprocess,'Popen')])

    def test_43_no_network(self):
        import socket,http.client
        self.check_pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_44_no_environment(self):
        import os
        class ForbiddenEnvironment(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',ForbiddenEnvironment()):
            self.check_pure([(os,'getenv')])

    def test_45_no_random_uuid(self):
        import random,uuid
        self.check_pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])

    def test_46_no_mutable_global(self):
        before=dict(vars(scope))
        first=build();build(prepare(now=111)['absence'],())
        self.assertEqual(first,build())
        self.assertEqual(vars(scope),before)
        for name,value in vars(scope).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray,VisibilityCompletenessSnapshot))
        tree=ast.parse(inspect.getsource(scope))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))

    def test_47_no_ref_parsing(self): self.forbidden({'startswith','endswith','split','partition'})
    def test_48_no_hero_logic(self): self.forbidden({'hero','items','level','gold','gpm','damage','spell'})
    def test_49_no_map_geometry(self): self.forbidden({'x','y','coordinates','distance','camera','viewport'})
    def test_50_no_visibility_polygon(self): self.forbidden({'polygon','pixels','minimap','fog','occlusion'})
    def test_51_no_numeric_score(self): self.forbidden({'score','probability','confidence','percentage','quality_score','completeness_score'})

    def test_52_snapshot_frozen(self):
        result=build()
        with self.assertRaises(FrozenInstanceError): result.selected_tick=5
        self.assertIs(type(result.assessments),tuple)

    def test_53_assessment_frozen(self):
        result=build().assessments[0]
        with self.assertRaises(FrozenInstanceError): result.completeness=UNKNOWN

    def test_54_deterministic_snapshot_id(self):
        result=build()
        digest=hashlib.sha256(json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id,'threat.visibility_completeness.v1:snapshot:'+digest)
        self.assertEqual(result.snapshot_id,build().snapshot_id)

    def test_55_order_does_not_change_id(self):
        absence=prepare(subjects=(('B','ref.b'),('A','ref.a')))['absence']
        claims=(claim('B','ref.b',completeness=UNKNOWN),claim())
        self.assertEqual(build(absence,claims).snapshot_id,build(absence,claims[::-1]).snapshot_id)

    def test_56_completeness_changes_id(self):
        self.assertEqual(len({build(claims=(claim(completeness=v),)).snapshot_id for v in VisibilityCompleteness}),3)

    def test_57_scope_changes_id(self):
        self.assertNotEqual(build().snapshot_id,build(claims=(claim(scope_id='other'),)).snapshot_id)

    def test_58_policy_changes_id(self):
        self.assertNotEqual(build().snapshot_id,build(claims=(claim(policy='assessment-v2'),)).snapshot_id)

    def test_59_absence_changes_id(self):
        absence=prepare()['absence']
        other=replace(absence,event_id='different-event')
        self.assertNotEqual(build(absence).snapshot_id,build(other).snapshot_id)
        self.assertEqual(build(other).absence_snapshot_id,other.snapshot_id)

    def test_60_subject_changes_id(self):
        other=prepare(subjects=(('B','ref.a'),))['absence']
        self.assertNotEqual(build().snapshot_id,build(other,(claim('B'),)).snapshot_id)

    def test_61_upstream_lineage_preserved(self):
        absence=prepare()['absence'];result=build(absence);a=result.assessments[0];o=absence.observations[0]
        self.assertEqual(result.absence_snapshot_id,absence.snapshot_id)
        for name in ('timeline_id','event_id','projection_id','tracker_state_id','temporal_snapshot_id',
                     'selected_clock_id','selected_tick','evaluated_at_tick'):
            self.assertEqual(getattr(result,name),getattr(absence,name))
        for out,original in (('threat_id','threat_id'),('absence_ref','ref'),('source_id','source_id'),
                             ('observed_tick','observed_tick'),('absence_last_observed_tick','last_observed_tick'),
                             ('absence_temporal_policy_id','temporal_policy_id'),('absence_max_age_ticks','max_age_ticks')):
            self.assertEqual(getattr(a,out),getattr(o,original))

    def test_62_absence_status_preserved(self):
        for now in (100,111):
            absence=prepare(now=now)['absence']
            self.assertIs(build(absence).assessments[0].absence_temporal_status,absence.observations[0].temporal_status)

    def test_63_absence_age_preserved(self):
        for now in (100,110,111):
            absence=prepare(now=now)['absence']
            self.assertEqual(build(absence).assessments[0].absence_age_ticks,now-100)

    def test_64_multiple_threats_isolated(self):
        absence=prepare(subjects=(('A','ref.a'),('B','ref.b')))['absence']
        a,b=build(absence,(claim(),claim('B','ref.b',completeness=UNKNOWN))).assessments
        self.assertEqual((a.threat_id,a.absence_ref,a.completeness),('A','ref.a',SUFFICIENT))
        self.assertEqual((b.threat_id,b.absence_ref,b.completeness),('B','ref.b',UNKNOWN))

    def test_65_no_ref_borrowing(self):
        absence=prepare(subjects=(('A','ref.a'),('B','ref.b')))['absence']
        with self.assertRaises(ValueError): build(absence,(claim('A','ref.b'),))

    def test_66_scope_opaque(self):
        value=' visible-region.contract A '
        self.assertEqual(build(claims=(claim(scope_id=value),)).assessments[0].scope_id,value)

    def test_67_policy_opaque(self):
        value=' observer-policy.v2: no parsing '
        self.assertEqual(build(claims=(claim(policy=value),)).assessments[0].assessment_policy_id,value)

    def test_68_positive_conflict_not_reconciled(self):
        from coach02.threat_observation import ThreatSightingClaim,ThreatProximity,build_threat_observations
        bundle=prepare()
        positive=build_threat_observations(bundle['event'],bundle['projection'],bundle['temporal'],
                                         (ThreatSightingClaim('A','ref.a',ThreatProximity.NEARBY,'fresh-v1'),))
        before=asdict(positive)
        assessed=build(bundle['absence'])
        self.assertEqual(assessed.assessments[0].observed_tick,positive.observations[0].observed_tick)
        self.assertEqual(assessed.assessments[0].threat_id,positive.observations[0].threat_id)
        self.assertIs(assessed.assessments[0].completeness,SUFFICIENT)
        self.assertEqual(asdict(positive),before)

    def test_69_no_backward_production_import(self):
        root=Path(scope.__file__).resolve().parent.parent
        # Only these downstream consumers may bind foundation contracts. This is
        # not permission to construct events, run a tracker, or add live wiring.
        authorized_consumers = frozenset({'coach02/missing_threat_resolver.py'})
        allowed_contracts = frozenset(('VisibilityCompleteness', 'VisibilityCompletenessAssessment', 'VisibilityCompletenessSnapshot'))
        operations = frozenset({'project_event_time', 'new_temporal_state',
                                'record_observations', 'evaluate_freshness', 'build_visibility_completenesss'})

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
                        if 'visibility_completeness' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('visibility_completeness' in (node.module or '').split('.') or
                               any(a.name == 'visibility_completeness' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'visibility_completeness') or
                                        (node.level == 0 and node.module == 'coach02.visibility_completeness'))
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
                                       and 'visibility_completeness' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        # Synthetic source is parsed, never executed. Keep the module test count
        # stable while proving this exception cannot authorize another consumer.
        valid = (
            'from .visibility_completeness import VisibilityCompletenessAssessment',
            'from coach02.visibility_completeness import VisibilityCompletenessAssessment as Contract\ndef bind(value: Contract): return type(value) is Contract',
        )
        for consumer in sorted(authorized_consumers):
            for source in valid:
                with self.subTest(authorized=source):
                    self.assertEqual(violations(source, consumer), [])
                with self.subTest(unauthorized=source):
                    self.assertTrue(violations(source, 'coach02/arbitrary_future_consumer.py'))
        rejected = [
            'import coach02.visibility_completeness as foundation',
            'from coach02 import visibility_completeness as foundation',
            'from .visibility_completeness import *',
            'from ..visibility_completeness import VisibilityCompletenessAssessment',
            'from .visibility_completeness import VisibilityCompletenessAssessment as Contract\nContract()',
            'from .visibility_completeness import VisibilityCompletenessAssessment as Contract\nfactory = Contract\nfactory()',
            "import importlib as loader\nloader.import_module('coach02.visibility_completeness')",
            "from importlib import import_module as load\nload('coach02.visibility_completeness')",
        ]
        for operation in sorted(operations):
            rejected.extend((
                'from .visibility_completeness import ' + operation + ' as run\nrun()',
                'runtime.' + operation + '()',
            ))
        for consumer in sorted(authorized_consumers):
            for source in rejected:
                with self.subTest(rejected=source):
                    self.assertTrue(violations(source, consumer))
        dynamic = "from importlib import import_module as load\nload('coach02.visibility_completeness')"
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
            if path.relative_to(root).as_posix() == 'coach02/visibility_completeness.py':
                continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()),
                             [], str(path))

    def test_70_existing_production_hashes_preserved(self):
        root=Path(scope.__file__).resolve().parent.parent
        for rel,sha in PRODUCTION_HASHES:
            with self.subTest(path=rel):
                self.assertEqual(hashlib.sha256((root/rel).read_bytes()).hexdigest().upper(),sha)

    def test_71_unsupported_temporal_states_rejected(self):
        absence=prepare()['absence'];obs=absence.observations[0]
        for bad in (TemporalStatus.NEVER_SEEN,'fresh','FRESH','STALE',None,SUFFICIENT):
            with self.assertRaisesRegex(ValueError,'supported_absence_temporal_status_required'):
                build(replace(absence,observations=(replace(obs,temporal_status=bad),)))

    def test_72_invalid_visibility_rejected(self):
        absence=prepare()['absence'];obs=absence.observations[0]
        for bad in ('NOT_VISIBLE','MISSING',None):
            with self.assertRaises(ValueError): build(replace(absence,observations=(replace(obs,visibility=bad),)))

    def test_73_snapshot_structure_defensive(self):
        absence=prepare()['absence']
        for name in ('timeline_id','event_id','projection_id','tracker_state_id','temporal_snapshot_id','selected_clock_id'):
            with self.assertRaises(ValueError): build(replace(absence,**{name:' '}))
        for name in ('selected_tick','evaluated_at_tick'):
            for bad in (True,1.5,None):
                with self.assertRaises(TypeError): build(replace(absence,**{name:bad}))
        for bad in ([],(None,),('bad',)):
            with self.assertRaises(TypeError): build(replace(absence,observations=bad))

    def test_74_observation_structure_defensive(self):
        absence=prepare()['absence'];obs=absence.observations[0]
        for name in ('threat_id','ref','source_id','temporal_policy_id'):
            with self.assertRaises(ValueError): build(replace(absence,observations=(replace(obs,**{name:' '}),)))
        for name in ('observed_tick','last_observed_tick','age_ticks','max_age_ticks'):
            for bad in (True,None,0.5):
                with self.assertRaises(TypeError): build(replace(absence,observations=(replace(obs,**{name:bad}),)))
        for name in ('age_ticks','max_age_ticks'):
            with self.assertRaises(ValueError): build(replace(absence,observations=(replace(obs,**{name:-1}),)))

    def test_75_negative_ticks_preserved(self):
        absence=prepare(tick=-100,now=-90)['absence']
        value=build(absence).assessments[0]
        self.assertEqual((value.observed_tick,value.absence_age_ticks),(-100,10))

    def test_76_inputs_immutable(self):
        absence=prepare()['absence'];claims=(claim(),)
        before=asdict(absence),tuple(asdict(c) for c in claims)
        build(absence,claims)
        self.assertEqual(before,(asdict(absence),tuple(asdict(c) for c in claims)))

    def test_77_upstream_classification_not_recomputed(self):
        absence=prepare(now=110)['absence']
        historical=replace(absence,observations=(replace(absence.observations[0],temporal_status=STALE),))
        result=build(historical)
        self.assertIs(result.assessments[0].absence_temporal_status,STALE)
        self.assertIs(result.assessments[0].completeness,SUFFICIENT)

    def test_78_whole_absence_identity_bound(self):
        a=prepare()['absence']
        b=prepare(subjects=(('A','ref.a'),('B','ref.b')))['absence']
        self.assertEqual(build(a).assessments,build(b).assessments)
        self.assertNotEqual(build(a).snapshot_id,build(b).snapshot_id)

    def guard(self):
        root=Path(scope.__file__).resolve().parent.parent
        tree=ast.parse((root/'tests/test_threat_absence_observation.py').read_text(encoding='utf-8'))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_70_no_backward_production_import_or_orchestration')
        selected=[]
        for n in fn.body:
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'authorized_consumers','allowed_contracts','operations'} for t in n.targets):
                selected.append(n)
            if isinstance(n,ast.FunctionDef) and n.name=='violations': selected.append(n)
        self.assertEqual(len(selected),4)
        namespace={'ast':ast}
        exec(compile(ast.Module(body=selected,type_ignores=[]),'<guard>','exec'),namespace)
        return namespace

    def test_79_guard_only_exact_consumer(self):
        g=self.guard()
        self.assertEqual(g['authorized_consumers'],frozenset({'coach02/visibility_completeness.py','coach02/missing_threat_resolver.py'}))
        self.assertEqual(g['allowed_contracts'],frozenset({'ThreatAbsenceObservation','ThreatAbsenceObservationSnapshot','ThreatVisibilityAbsence','TemporalStatus'}))
        for symbol in g['allowed_contracts']:
            text='from .threat_absence_observation import '+symbol
            self.assertEqual(g['violations'](text,'coach02/visibility_completeness.py'),[])
            for path in ('run.py','coach02/service.py','coach02/threat_observation.py','coach02/unknown.py'):
                self.assertTrue(g['violations'](text,path))

    def test_80_guard_no_orchestration_or_dynamic_imports(self):
        g=self.guard();consumer='coach02/visibility_completeness.py'
        sources=['from .threat_absence_observation import *','import coach02.threat_absence_observation as foundation',
                 "import importlib as loader; loader.import_module('coach02.threat_absence_observation')",
                 'from .threat_absence_observation import ThreatAbsenceObservationSnapshot as Contract; factory=Contract; factory()']
        for name in ('project_event_time','new_temporal_state','record_observations','evaluate_freshness','build_threat_absence_observations'):
            sources.extend(('from .threat_absence_observation import '+name+' as run; alias=run; alias()','foundation.'+name+'()'))
        for source in sources:
            with self.subTest(source=source): self.assertTrue(g['violations'](source,consumer))

    def test_81_exact_output_schema(self):
        self.assertEqual({f.name for f in fields(VisibilityCompletenessAssessment)},{
            'threat_id','absence_ref','source_id','observed_tick','absence_temporal_status','absence_last_observed_tick',
            'absence_age_ticks','absence_temporal_policy_id','absence_max_age_ticks','scope_id','completeness','assessment_policy_id'})
        self.assertEqual({f.name for f in fields(VisibilityCompletenessSnapshot)},{
            'timeline_id','absence_snapshot_id','event_id','projection_id','tracker_state_id','temporal_snapshot_id',
            'selected_clock_id','selected_tick','evaluated_at_tick','assessments'})

    def test_82_shared_ref_does_not_replace_subject_binding(self):
        a=prepare()['absence'];obs=a.observations[0]
        a=replace(a,observations=(obs,replace(obs,threat_id='B')))
        result=build(a,(claim('A'),claim('B',completeness=UNKNOWN)))
        self.assertEqual([x.completeness for x in result.assessments],[SUFFICIENT,UNKNOWN])

    def test_83_empty_snapshot_preserves_envelope(self):
        a=prepare(subjects=())['absence'];result=build(a,())
        self.assertEqual(result.absence_snapshot_id,a.snapshot_id)
        self.assertEqual(result.assessments,())

    def test_84_atomic_validation(self):
        a=prepare(subjects=(('A','ref.a'),('B','ref.b')))['absence'];before=asdict(a)
        with self.assertRaises(ValueError): build(a,(claim(),claim('B','wrong')))
        self.assertEqual(asdict(a),before)


PRODUCTION_HASHES = (('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'))
