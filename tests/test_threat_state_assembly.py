"""Synthetic accepted upstream envelopes; no observation or live integration."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import threat_state_assembly as assembly
from coach02.threat_state_assembly import (
    AssembledThreatState as State, ThreatStateReason as Reason,
    ThreatStateAssessment, ThreatStateSnapshot, build_threat_state,
)
from coach02.threat_observation import ThreatObservationSnapshot, ThreatProximity, TemporalStatus
from coach02.missing_threat_resolver import MissingThreatResolutionSnapshot, MissingResolutionStatus as Status
from coach02.visibility_completeness import VisibilityCompleteness as Completeness
from test_missing_threat_resolver import prepare, resolve


def pair(**kwargs):
    b = prepare(**kwargs)
    return b['positive'], resolve(b)


def positive_only(**kwargs):
    options = dict(positive_tick=100, absence_tick=100, absences=(), assessments=())
    options.update(kwargs)
    return pair(**options)


def unresolved(**kwargs):
    options = dict(positive_tick=110, absence_tick=100, assessments=())
    options.update(kwargs)
    return pair(**options)


def build(inputs=None):
    return build_threat_state(*(pair() if inputs is None else inputs))


def row(inputs=None):
    return build(inputs).assessments[0]


def at_tick(inputs, tick):
    p, m = inputs
    return p, replace(m, resolved_at_tick=tick)


def rebind_positive(inputs, positive):
    _, m = inputs
    index = {o.threat_id:o for o in positive.observations}
    resolutions = tuple(replace(r, positive=index.get(r.threat_id),
        last_seen_tick=None if r.threat_id not in index else index[r.threat_id].observed_tick,
        positive_snapshot_id=positive.snapshot_id) for r in m.resolutions)
    return positive, replace(m, positive_snapshot_id=positive.snapshot_id, resolutions=resolutions)


def change_absence(inputs, **changes):
    p, m = inputs; r = m.resolutions[0]
    absence = replace(r.absence, **changes)
    assessment = r.assessment
    if assessment is not None:
        assessment = replace(assessment, absence_ref=absence.ref, source_id=absence.source_id,
            observed_tick=absence.observed_tick, absence_temporal_status=absence.temporal_status,
            absence_last_observed_tick=absence.last_observed_tick, absence_age_ticks=absence.age_ticks,
            absence_temporal_policy_id=absence.temporal_policy_id, absence_max_age_ticks=absence.max_age_ticks)
    r = replace(r, absence=absence, assessment=assessment,
                missing_since_tick=absence.observed_tick if r.status is Status.MISSING else None)
    return p, replace(m, resolutions=(r,)+m.resolutions[1:])


class ThreatStateAssemblyTests(unittest.TestCase):
    def assert_state(self, inputs, state, reason=None):
        result = row(inputs)
        self.assertIs(result.state, state)
        if reason is not None: self.assertIs(result.reason, reason)
        return result

    def imports(self):
        tree = ast.parse(inspect.getsource(assembly))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def output_fields(self):
        return {f.name for cls in (ThreatStateAssessment,ThreatStateSnapshot) for f in fields(cls)}

    def calls(self):
        return {ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(assembly))) if isinstance(n,ast.Call)}

    def pure(self, sinks):
        inputs = pair(); expected = build(inputs); before = tuple(asdict(v) for v in inputs)
        with ExitStack() as stack:
            for owner,name in sinks:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure assembly')))
            result = build(inputs); identity = result.snapshot_id
        self.assertEqual(result,expected); self.assertEqual(identity,expected.snapshot_id)
        self.assertEqual(before,tuple(asdict(v) for v in inputs))

    def test_001_exact_states(self):
        self.assertEqual({s.value for s in State},{'VISIBLE_NEARBY','VISIBLE_AWAY','MISSING','UNKNOWN','CONFLICTED'})

    def test_002_no_safety_states(self):
        self.assertTrue({'SAFE','UNSAFE','DANGEROUS','RELEVANT','NOT_RELEVANT'}.isdisjoint(State.__members__))

    def test_003_assessment_frozen_valid_pairs(self):
        r = row()
        with self.assertRaises(FrozenInstanceError): r.state = State.UNKNOWN
        for state in State:
            for reason in Reason:
                valid = (state in (State.VISIBLE_NEARBY,State.VISIBLE_AWAY) and reason is Reason.CURRENT_POSITIVE or
                         state is State.MISSING and reason is Reason.JUSTIFIED_MISSING or
                         state is State.CONFLICTED and reason is Reason.VALIDATED_CONFLICT or
                         state is State.UNKNOWN and reason in (Reason.NO_CURRENT_POSITIVE,
                            Reason.UNRESOLVED_NEGATIVE_EVIDENCE,Reason.TEMPORAL_MISALIGNMENT))
                if valid: self.assertIs(replace(r,state=state,reason=reason).reason,reason)
                else:
                    with self.assertRaises(ValueError): replace(r,state=state,reason=reason)
        for changes in ({'state':'MISSING'},{'reason':'JUSTIFIED_MISSING'}):
            with self.assertRaises(TypeError): replace(r,**changes)

    def test_004_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assembly_tick = 1

    def test_005_exact_positive_type(self):
        p,m = pair()
        class Sub(ThreatObservationSnapshot): pass
        for bad in (None,{},Sub(**p.__dict__)):
            with self.assertRaises(TypeError): build((bad,m))

    def test_006_exact_missing_type(self):
        p,m = pair()
        class Sub(MissingThreatResolutionSnapshot): pass
        for bad in (None,{},Sub(**m.__dict__)):
            with self.assertRaises(TypeError): build((p,bad))

    def test_007_timeline_mismatch(self):
        p,m = pair()
        with self.assertRaisesRegex(ValueError,'timeline_mismatch'): build((p,replace(m,timeline_id='other')))

    def test_008_clock_mismatch(self):
        p,m = pair()
        with self.assertRaisesRegex(ValueError,'clock_mismatch'): build((p,replace(m,selected_clock_id='other')))

    def test_009_positive_snapshot_binding(self):
        p,m = positive_only()
        with self.assertRaisesRegex(ValueError,'positive_snapshot_binding_mismatch'):
            build((p,replace(m,positive_snapshot_id='other')))
        p,m = pair(); r = replace(m.resolutions[0],absence_snapshot_id='other')
        with self.assertRaisesRegex(ValueError,'resolution_snapshot_lineage_mismatch'):
            build((p,replace(m,resolutions=(r,))))

    def test_010_duplicate_positive_and_tuple(self):
        p,m = positive_only()
        with self.assertRaisesRegex(ValueError,'duplicate_positive_subject'):
            build((replace(p,observations=p.observations*2),m))
        for bad in (list(p.observations),(None,)):
            with self.assertRaises(TypeError): build((replace(p,observations=bad),m))
        for changes in ({'threat_id':' '},{'ref':' '},{'source_id':' '},{'temporal_policy_id':' '},
                        {'proximity':'NEARBY'},{'temporal_status':'FRESH'},
                        {'temporal_status':TemporalStatus.NEVER_SEEN},{'age_ticks':-1},{'max_age_ticks':-1}):
            changed = replace(p,observations=(replace(p.observations[0],**changes),))
            with self.assertRaises((TypeError,ValueError)): build((changed,m))

    def test_011_duplicate_resolution_and_tuple(self):
        p,m = pair()
        with self.assertRaisesRegex(ValueError,'duplicate_resolution_subject'):
            build((p,replace(m,resolutions=m.resolutions*2)))
        for bad in (list(m.resolutions),(None,)):
            with self.assertRaises(TypeError): build((p,replace(m,resolutions=bad)))
        for key in ('positive_snapshot_id','absence_snapshot_id','completeness_snapshot_id'):
            with self.assertRaises(ValueError): build((p,replace(m,**{key:' '})))

    def test_012_subject_union(self):
        inputs = pair(positives=('A','B'),absences=('B','C'),assessments=(('B',Completeness.SUFFICIENT),))
        self.assertEqual([r.threat_id for r in build(inputs).assessments],['A','B','C'])

    def test_013_empty_union(self):
        result = build(pair(positives=(),absences=(),assessments=()))
        self.assertEqual(result.assessments,())
        self.assertEqual(result.assembly_tick,110)

    def test_014_current_nearby_A(self):
        self.assert_state(positive_only(proximity=ThreatProximity.NEARBY),State.VISIBLE_NEARBY,Reason.CURRENT_POSITIVE)

    def test_015_current_away(self):
        self.assert_state(positive_only(),State.VISIBLE_AWAY)

    def test_016_stale_positive(self):
        self.assert_state(positive_only(positive_now=120),State.UNKNOWN,Reason.NO_CURRENT_POSITIVE)

    def test_017_fresh_but_old_B(self):
        self.assert_state(at_tick(positive_only(proximity=ThreatProximity.NEARBY),110),State.UNKNOWN,Reason.TEMPORAL_MISALIGNMENT)

    def test_018_no_extrapolation_even_long_ttl(self):
        inputs = at_tick(positive_only(positive_ttl=100000),101)
        r = self.assert_state(inputs,State.UNKNOWN)
        self.assertIs(r.positive_observation.temporal_status,TemporalStatus.FRESH)
        self.assertEqual(r.positive_observation.age_ticks,0)

    def test_019_current_missing_C(self):
        self.assert_state(pair(),State.MISSING,Reason.JUSTIFIED_MISSING)

    def test_020_old_missing_D(self):
        self.assert_state(pair(positive_now=120),State.UNKNOWN,Reason.TEMPORAL_MISALIGNMENT)

    def test_021_no_completeness_rerun(self):
        p,m = pair(); r = m.resolutions[0]
        for assessment in (None,replace(r.assessment,completeness=Completeness.UNKNOWN)):
            # Structural envelope only: upstream conclusions are trusted, not certified.
            changed = replace(m,resolutions=(replace(r,assessment=assessment),))
            self.assert_state((p,changed),State.MISSING)

    def test_022_no_prior_positive_rerun(self):
        inputs = pair(); p = replace(inputs[0],observations=())
        changed = rebind_positive(inputs,p)
        self.assertIsNone(changed[1].resolutions[0].positive)
        self.assert_state(changed,State.MISSING)

    def test_023_current_conflict_E(self):
        self.assert_state(pair(positive_tick=110),State.CONFLICTED,Reason.VALIDATED_CONFLICT)

    def test_024_old_conflict(self):
        self.assert_state(at_tick(pair(positive_tick=110),120),State.UNKNOWN,Reason.TEMPORAL_MISALIGNMENT)

    def test_025_conflict_never_picks_positive(self):
        r = self.assert_state(pair(positive_tick=110,proximity=ThreatProximity.NEARBY),State.CONFLICTED)
        self.assertIs(r.positive_observation.temporal_status,TemporalStatus.FRESH)

    def test_026_conflict_never_picks_negative(self):
        r = self.assert_state(pair(positive_tick=110),State.CONFLICTED)
        self.assertIs(r.missing_resolution.status,Status.CONFLICTED)
        self.assertIsNot(r.state,State.MISSING)

    def test_027_not_justified_not_missing(self):
        for assessments in ((),(('A',Completeness.UNKNOWN),),(('A',Completeness.INSUFFICIENT),)):
            inputs = pair(assessments=assessments)
            self.assertIs(inputs[1].resolutions[0].status,Status.NOT_JUSTIFIED)
            self.assert_state(inputs,State.UNKNOWN)

    def test_028_newer_nearby_F(self):
        self.assert_state(unresolved(proximity=ThreatProximity.NEARBY),State.VISIBLE_NEARBY)

    def test_029_newer_away_all_blockers(self):
        for assessments in ((),(('A',Completeness.UNKNOWN),),(('A',Completeness.INSUFFICIENT),),(('A',Completeness.SUFFICIENT),)):
            self.assert_state(unresolved(assessments=assessments),State.VISIBLE_AWAY)

    def test_030_newer_stale(self):
        self.assert_state(unresolved(positive_now=121),State.UNKNOWN,Reason.NO_CURRENT_POSITIVE)

    def test_031_newer_misaligned_I(self):
        self.assert_state(at_tick(unresolved(),120),State.UNKNOWN,Reason.TEMPORAL_MISALIGNMENT)

    def test_032_equal_not_justified_H(self):
        self.assert_state(unresolved(positive_tick=100),State.UNKNOWN,Reason.UNRESOLVED_NEGATIVE_EVIDENCE)

    def test_033_older_positive_G(self):
        inputs = unresolved(positive_tick=90)
        self.assertIs(inputs[0].observations[0].temporal_status,TemporalStatus.FRESH)
        self.assert_state(inputs,State.UNKNOWN)

    def test_034_no_prior_positive_K(self):
        self.assert_state(pair(positives=()),State.UNKNOWN,Reason.UNRESOLVED_NEGATIVE_EVIDENCE)

    def test_035_no_invented_subject(self):
        inputs = positive_only(positives=(' opaque enemy.safe Ω ',))
        self.assertEqual([r.threat_id for r in build(inputs).assessments],[' opaque enemy.safe Ω '])
        self.assertEqual(tuple(inspect.signature(build_threat_state).parameters),('positive_snapshot','missing_snapshot'))

    def test_036_nested_positive_matches(self):
        p,m = pair(); r = m.resolutions[0]
        changed = replace(r,positive=replace(r.positive,ref='other'))
        with self.assertRaisesRegex(ValueError,'resolution_positive_binding_mismatch'):
            build((p,replace(m,resolutions=(changed,))))

    def test_037_nested_absence_subject(self):
        p,m = pair(); r = m.resolutions[0]
        changed = replace(r,absence=replace(r.absence,threat_id='B'))
        with self.assertRaisesRegex(ValueError,'nested_absence_subject_mismatch'):
            build((p,replace(m,resolutions=(changed,))))

    def test_038_nested_assessment_binding(self):
        p,m = pair(); r = m.resolutions[0]
        for changes in ({'threat_id':'B'},{'absence_ref':'other'},{'absence_age_ticks':1}):
            changed = replace(r,assessment=replace(r.assessment,**changes))
            with self.assertRaises(ValueError): build((p,replace(m,resolutions=(changed,))))
        for changes in ({'completeness':'SUFFICIENT'},{'absence_temporal_status':'FRESH'},
                        {'absence_age_ticks':True}):
            changed = replace(r,assessment=replace(r.assessment,**changes))
            with self.assertRaises(TypeError): build((p,replace(m,resolutions=(changed,))))

    def test_039_assembly_deterministic(self):
        self.assertEqual(build().assembly_tick,build().assembly_tick)
        self.assertEqual(build().assembly_tick,110)

    def test_040_same_clock_max(self):
        p,m = positive_only(positive_now=110)
        for tick in (100,110,120):
            result = build((p,replace(m,resolved_at_tick=tick)))
            self.assertEqual(result.assembly_tick,max(110,tick))

    def test_041_evaluation_sum(self):
        inputs = positive_only(positive_now=105)
        r = self.assert_state(inputs,State.VISIBLE_AWAY)
        self.assertEqual(r.positive_observation.last_observed_tick+r.positive_observation.age_ticks,105)
        self.assertEqual(r.assembly_tick,105)

    def test_042_exact_age_alignment(self):
        p,m = positive_only(positive_now=105)
        changed = replace(p,observations=(replace(p.observations[0],age_ticks=4),))
        with self.assertRaisesRegex(ValueError,'positive_evaluation_binding_mismatch'):
            build(rebind_positive((p,m),changed))
        self.assert_state(at_tick((p,m),106),State.UNKNOWN)

    def test_043_bool_ticks(self):
        p,m = pair()
        for key in ('selected_tick','evaluated_at_tick'):
            with self.assertRaises(TypeError): build((replace(p,**{key:True}),m))
        with self.assertRaises(TypeError): build((p,replace(m,resolved_at_tick=True)))
        for key in ('observed_tick','last_observed_tick','age_ticks','max_age_ticks'):
            bad = replace(p,observations=(replace(p.observations[0],**{key:True}),))
            with self.assertRaises(TypeError): build((bad,m))
        with self.assertRaises(TypeError): build(change_absence((p,m),age_ticks=True))

    def test_044_float_ticks(self):
        p,m = positive_only()
        with self.assertRaises(TypeError): build((replace(p,evaluated_at_tick=100.0),m))
        with self.assertRaises(TypeError): build((p,replace(m,resolved_at_tick=100.0)))

    def test_045_negative_ticks(self):
        r = self.assert_state(positive_only(positive_tick=-100,absence_tick=-100,positive_now=-95),State.VISIBLE_AWAY)
        self.assertEqual(r.assembly_tick,-95)

    def test_046_equal_ticks(self):
        r = self.assert_state(positive_only(),State.VISIBLE_AWAY)
        self.assertEqual(r.positive_observation.age_ticks,0)

    def test_047_nearby_not_dangerous(self):
        r = row(positive_only(proximity=ThreatProximity.NEARBY))
        self.assertIs(r.state,State.VISIBLE_NEARBY); self.assertFalse(hasattr(r,'danger'))

    def test_048_away_not_safe(self):
        r = row(positive_only()); self.assertIs(r.state,State.VISIBLE_AWAY)
        self.assertFalse(hasattr(r,'safe'))

    def test_049_missing_not_dangerous(self):
        r = row(); self.assertIs(r.state,State.MISSING); self.assertFalse(hasattr(r,'danger'))

    def test_050_unknown_not_safe(self):
        r = row(unresolved(positive_tick=100)); self.assertIs(r.state,State.UNKNOWN)
        self.assertFalse(hasattr(r,'safe'))

    def test_051_conflict_not_dangerous(self):
        r = row(pair(positive_tick=110)); self.assertIs(r.state,State.CONFLICTED)
        self.assertFalse(hasattr(r,'danger'))

    def test_052_no_relevance(self):
        self.assertNotIn('relevance',self.output_fields())

    def test_053_no_coverage(self):
        self.assertNotIn('coverage',self.output_fields())

    def test_054_no_exposure(self):
        self.assertNotIn('exposure',self.output_fields())

    def test_055_no_risk(self):
        self.assertTrue({'risk','danger','increased_risk'}.isdisjoint(self.output_fields()))

    def test_056_no_safety(self):
        self.assertTrue({'safety','safe','unsafe'}.isdisjoint(self.output_fields()))

    def test_057_no_recommendation(self):
        self.assertTrue({'recommendation','action','authority','route'}.isdisjoint(self.output_fields()))

    def test_058_deterministic_identity(self):
        result = build()
        data = json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'threat.state_assembly.v1:snapshot:'+hashlib.sha256(data).hexdigest())
        self.assertEqual(result.snapshot_id,build().snapshot_id)

    def test_059_state_identity(self):
        inputs = positive_only(); p,m = inputs
        other = rebind_positive(inputs,replace(p,observations=(replace(p.observations[0],proximity=ThreatProximity.NEARBY),)))
        self.assertNotEqual(build(inputs).snapshot_id,build(other).snapshot_id)

    def test_060_reason_identity(self):
        result = build(unresolved(positive_tick=100)); r = result.assessments[0]
        other = replace(result,assessments=(replace(r,reason=Reason.NO_CURRENT_POSITIVE),))
        self.assertIs(other.assessments[0].state,State.UNKNOWN)
        self.assertNotEqual(result.snapshot_id,other.snapshot_id)

    def test_061_positive_evidence_identity(self):
        inputs = pair(); p,m = inputs
        other = rebind_positive(inputs,replace(p,observations=(replace(p.observations[0],ref='opaque.new'),)))
        self.assertNotEqual(build(inputs).snapshot_id,build(other).snapshot_id)

    def test_062_missing_evidence_identity(self):
        inputs = pair(); changed = change_absence(inputs,ref='opaque.other')
        self.assertNotEqual(build(inputs).snapshot_id,build(changed).snapshot_id)

    def test_063_lineage_identity(self):
        inputs = pair(); p,m = inputs
        changed = rebind_positive(inputs,replace(p,event_id='different-event'))
        self.assertNotEqual(build(inputs).snapshot_id,build(changed).snapshot_id)

    def test_064_assembly_tick_identity(self):
        inputs = positive_only()
        self.assertNotEqual(build(at_tick(inputs,110)).snapshot_id,build(at_tick(inputs,111)).snapshot_id)

    def test_065_canonical_order(self):
        inputs = pair(positives=('B','A'),absences=('B','A'),assessments=(('B',Completeness.SUFFICIENT),('A',Completeness.SUFFICIENT)))
        other = pair(positives=('A','B'),absences=('A','B'),assessments=(('A',Completeness.SUFFICIENT),('B',Completeness.SUFFICIENT)))
        self.assertEqual(build(inputs),build(other))
        self.assertEqual(build(inputs).snapshot_id,build(other).snapshot_id)
        self.assertEqual([r.threat_id for r in build(inputs).assessments],['A','B'])

    def test_066_multiple_subjects_independent(self):
        inputs = pair(positives=('A','B'),absences=('A',)); before = build(inputs)
        p,m = inputs; changed = replace(p,observations=(p.observations[0],replace(p.observations[1],proximity=ThreatProximity.NEARBY)))
        after = build(rebind_positive(inputs,changed))
        self.assertIs(before.assessments[0].state,after.assessments[0].state)
        self.assertIsNot(before.assessments[1].state,after.assessments[1].state)

    def test_067_no_cross_subject_borrowing(self):
        inputs = pair(positives=('A','B'),absences=('A',)); p,m = inputs
        r = replace(m.resolutions[0],positive=p.observations[1])
        with self.assertRaisesRegex(ValueError,'resolution_positive_binding_mismatch'):
            build((p,replace(m,resolutions=(r,))))

    def test_068_missing_and_visible_J(self):
        result = build(pair(positives=('A','B'),absences=('A',)))
        self.assertEqual([(r.threat_id,r.state) for r in result.assessments],[('A',State.MISSING),('B',State.VISIBLE_AWAY)])

    def test_069_conflict_and_unknown(self):
        result = build(pair(positive_tick=110,positives=('A',),absences=('A','B')))
        self.assertEqual([r.state for r in result.assessments],[State.CONFLICTED,State.UNKNOWN])

    def test_070_positive_and_resolution_only(self):
        result = build(pair(positives=('A',),absences=('B',),assessments=()))
        self.assertEqual([(r.threat_id,r.state) for r in result.assessments],[('A',State.VISIBLE_AWAY),('B',State.UNKNOWN)])

    def test_071_exact_objects(self):
        inputs = pair(); r = row(inputs)
        self.assertIs(r.positive_observation,inputs[0].observations[0])
        self.assertIs(r.missing_resolution,inputs[1].resolutions[0])

    def test_072_resolution_preserved(self):
        inputs = unresolved(); before = asdict(inputs[1].resolutions[0])
        r = self.assert_state(inputs,State.VISIBLE_AWAY)
        self.assertEqual(asdict(r.missing_resolution),before)

    def test_073_positive_preserved(self):
        inputs = pair(positive_ttl=0); before = asdict(inputs[0].observations[0])
        self.assertIs(row(inputs).state,State.MISSING)
        self.assertEqual(asdict(row(inputs).positive_observation),before)

    def test_074_inputs_not_mutated(self):
        inputs = pair(); before = tuple(asdict(s) for s in inputs)
        build(inputs); self.assertEqual(tuple(asdict(s) for s in inputs),before)

    def test_075_relevance_independent_M(self):
        self.assertNotIn('.threat_relevance',self.imports())
        from coach02.threat_relevance import ThreatRelevance, ThreatRelevanceClaim, build_threat_relevance
        inputs = pair(); external = build_threat_relevance(*inputs,(ThreatRelevanceClaim('A',ThreatRelevance.NOT_RELEVANT,'ctx','policy'),))
        self.assertIs(external.assessments[0].relevance,ThreatRelevance.NOT_RELEVANT)
        self.assert_state(inputs,State.MISSING)

    def test_076_coverage_independent_N(self):
        self.assertNotIn('.strategic_coverage',self.imports())
        from test_strategic_coverage import row as external_row
        from coach02.strategic_coverage import StrategicCoverageState
        self.assertIs(external_row(StrategicCoverageState.UNKNOWN).coverage,StrategicCoverageState.UNKNOWN)
        self.assert_state(pair(),State.MISSING)

    def test_077_exposure_independent_O(self):
        self.assertNotIn('.option_exposure',self.imports())
        from test_option_exposure import row as external_row
        from coach02.option_exposure import OptionExposureState
        self.assertIs(external_row().exposure,OptionExposureState.EXPOSED)
        self.assert_state(pair(),State.MISSING)

    def test_078_no_safety_import(self):
        self.assertNotIn('.safety_evidence',self.imports())

    def test_079_no_option_safety_import(self):
        self.assertNotIn('.option_safety',self.imports())

    def test_080_no_event_import(self):
        self.assertNotIn('.observation_event',self.imports())

    def test_081_no_temporal_import(self):
        self.assertNotIn('.temporal_evidence',self.imports())

    def test_082_no_absence_import(self):
        self.assertNotIn('.threat_absence_observation',self.imports())

    def test_083_no_completeness_import(self):
        self.assertNotIn('.visibility_completeness',self.imports())

    def test_084_no_runtime_imports(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.threat_observation','.missing_threat_resolver'})

    def test_085_no_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_086_no_io(self):
        import builtins,io,os,sqlite3,subprocess
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(sqlite3,'connect'),(subprocess,'Popen')])

    def test_087_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_088_no_environment(self):
        import os
        class Forbidden(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',Forbidden()): self.pure([(os,'getenv')])

    def test_089_no_random(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid4'),(uuid,'uuid1')])

    def test_090_no_mutable_globals(self):
        before = dict(vars(assembly)); build(); build(positive_only())
        self.assertEqual(before,vars(assembly))
        for name,value in vars(assembly).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef)) for n in ast.walk(ast.parse(inspect.getsource(assembly)))))

    def test_091_no_temporal_refresh(self):
        from coach02 import temporal_evidence
        self.pure([(temporal_evidence,'new_temporal_state'),(temporal_evidence,'record_observations'),(temporal_evidence,'evaluate_freshness')])

    def test_092_no_freshness_recalculation(self):
        inputs = positive_only(); p,m = inputs
        changed = replace(p,observations=(replace(p.observations[0],temporal_status=TemporalStatus.STALE),))
        self.assert_state(rebind_positive(inputs,changed),State.UNKNOWN)
        inputs = change_absence(pair(),temporal_status=TemporalStatus.STALE)
        self.assert_state(inputs,State.UNKNOWN,Reason.UNRESOLVED_NEGATIVE_EVIDENCE)
        inputs = change_absence(pair(),age_ticks=5,max_age_ticks=0)
        self.assert_state(at_tick(inputs,115),State.MISSING)

    def test_093_no_missing_derivation(self):
        from coach02 import missing_threat_resolver
        self.pure([(missing_threat_resolver,'resolve_missing_threats'),(missing_threat_resolver,'_reason')])

    def test_094_no_completeness_evaluation(self):
        from coach02 import visibility_completeness
        self.pure([(visibility_completeness,'build_visibility_completeness')])

    def test_095_no_relevance_calculation(self):
        from coach02 import threat_relevance
        self.pure([(threat_relevance,'build_threat_relevance')])

    def test_096_no_threat_weighting(self):
        self.assertTrue({'weight','priority','rank'}.isdisjoint(self.output_fields()))
        tree = ast.parse(inspect.getsource(assembly))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in {'weight','rank','hero','distance','coordinates'} for n in ast.walk(tree)))

    def test_097_no_score(self):
        self.assertTrue({'score','confidence','probability'}.isdisjoint(self.output_fields()))

    def test_098_legacy_contract_review(self):
        from coach02.safety_evidence import ThreatState, RelevantThreatObservation
        self.assertIsNot(State,ThreatState)
        self.assertEqual({s.value for s in ThreatState},{'VISIBLE_NEARBY','VISIBLE_AWAY','MISSING','UNKNOWN'})
        self.assertEqual({f.name for f in fields(RelevantThreatObservation)},{'threat_id','state','freshness'})

    def test_099_conflicted_incompatibility(self):
        from coach02.safety_evidence import ThreatState
        with self.assertRaises(ValueError): ThreatState(State.CONFLICTED.value)
        self.assert_state(pair(positive_tick=110),State.CONFLICTED)

    def test_100_no_lossy_adapter(self):
        from coach02 import safety_evidence,option_safety
        self.pure([(safety_evidence,'build_risk_awareness'),(option_safety,'build_option_safety')])
        self.assertFalse(hasattr(assembly,'safety_for_test'))
        self.assertTrue({'RelevantThreatObservation','build_risk_awareness','build_option_safety'}.isdisjoint(self.calls()))

    def guards(self):
        root = Path(assembly.__file__).resolve().parent.parent
        for filename, method, module in (
            ('test_threat_observation.py', 'test_70_no_backward_production_import_or_orchestration', 'threat_observation'),
            ('test_missing_threat_resolver.py', 'test_85_no_backward_dependency', 'missing_threat_resolver')):
            tree = ast.parse((root / 'tests' / filename).read_text(encoding='utf-8'))
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
            selected = [n for n in fn.body if
                        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                        {'authorized_consumers', 'allowed_contracts', 'operations'} for t in n.targets) or
                        isinstance(n, ast.FunctionDef) and n.name == 'violations']
            self.assertEqual(len(selected), 4)
            namespace = {'ast': ast}
            exec(compile(ast.Module(body=selected, type_ignores=[]), filename, 'exec'), namespace)
            yield module, namespace

    def test_101_dependency_direction(self):
        for module, g in self.guards():
            self.assertEqual(g['violations'](inspect.getsource(assembly), 'coach02/threat_state_assembly.py'), [])
        root = Path(assembly.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evidence_assembly.py', 'coach02/threat_reachability.py'})
        allowed_contracts = frozenset(('ThreatStateSnapshot', 'ThreatStateAssessment', 'AssembledThreatState', 'ThreatStateReason', 'ThreatObservation', 'MissingThreatResolution'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure'))

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            contracts = (frozenset({'ThreatStateSnapshot', 'ThreatStateAssessment', 'AssembledThreatState', 'ThreatStateReason'})
                         if relative_path == 'coach02/threat_reachability.py' else allowed_contracts)
            errors = []
            blocked_calls = set(operations) if consumer else set()
            if consumer:
                blocked_calls.update(allowed_contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'threat_state_assembly' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('threat_state_assembly' in (node.module or '').split('.') or
                               any(a.name == 'threat_state_assembly' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'threat_state_assembly') or
                                        (node.level == 0 and node.module == 'coach02.threat_state_assembly'))
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
                                       and 'threat_state_assembly' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .threat_state_assembly import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evidence_assembly.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .threat_state_assembly import *', 'import coach02.threat_state_assembly',
                    'from coach02 import threat_state_assembly',
                    "__import__('coach02.threat_state_assembly')"]
        for symbol in allowed_contracts:
            rejected.append('from .threat_state_assembly import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .threat_state_assembly import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evidence_assembly.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/threat_state_assembly.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_102_arbitrary_consumer_rejected(self):
        for module, g in self.guards():
            for symbol in g['allowed_contracts']:
                source = 'from .' + module + ' import ' + symbol
                self.assertEqual(g['violations'](source, 'coach02/threat_state_assembly.py'), [])
                for path in ('coach02/arbitrary_future.py', 'coach02/service.py', 'coach02/decision.py', 'run.py'):
                    self.assertTrue(g['violations'](source, path))
            self.assertTrue(g['violations']('from .' + module + ' import UnapprovedContract', 'coach02/threat_state_assembly.py'))

    def test_103_orchestration_rejected(self):
        for module, g in self.guards():
            sources = ['from .' + module + ' import *', 'import coach02.' + module + ' as foundation',
                       'from coach02 import ' + module,
                       "import importlib as loader; loader.import_module('coach02." + module + "')",
                       "from importlib import import_module as load; load('coach02." + module + "')"]
            for symbol in g['allowed_contracts']:
                sources.append('from .' + module + ' import ' + symbol + ' as Contract; alias = Contract; alias()')
            for operation in g['operations']:
                sources.append('from .' + module + ' import ' + operation + ' as run; alias = run; alias()')
                sources.append('runtime.' + operation + '()')
            for source in sources:
                with self.subTest(module=module, source=source):
                    self.assertTrue(g['violations'](source, 'coach02/threat_state_assembly.py'))

    def test_104_existing_production_hashes(self):
        root = Path(assembly.__file__).resolve().parent.parent
        for path, sha in PRODUCTION_HASHES:
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest().upper(), sha)


PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
