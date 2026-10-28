"""Synthetic caller assessments; no real affectability policy is implemented."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
from enum import Enum
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import threat_reachability as reachability
from coach02.threat_reachability import (
    ThreatReachability as Reach, ThreatReachabilityClaim, ThreatReachabilityAssessment,
    ThreatReachabilitySnapshot, build_threat_reachability,
)
from coach02.threat_state_assembly import build_threat_state, AssembledThreatState as State
from coach02.threat_observation import ThreatProximity
from coach02.visibility_completeness import VisibilityCompleteness as Completeness
from test_missing_threat_resolver import prepare, resolve


def state(kind='MISSING', subjects=('A',), tick=110):
    visible = kind in ('VISIBLE_NEARBY', 'VISIBLE_AWAY')
    negatives = () if visible else subjects
    inputs = prepare(positive_tick=tick-10 if kind == 'MISSING' else tick,
                     absence_tick=tick, positive_now=tick, absence_now=tick,
                     positives=() if kind == 'UNKNOWN' else subjects, absences=negatives,
                     assessments=tuple((s, Completeness.SUFFICIENT) for s in negatives),
                     proximity=ThreatProximity.NEARBY if kind == 'VISIBLE_NEARBY' else ThreatProximity.AWAY)
    return build_threat_state(inputs['positive'], resolve(inputs))


def claim(**changes):
    return replace(ThreatReachabilityClaim('A', 'stay-lane', 'context-A', 'horizon-A',
                                          Reach.CAN_AFFECT, 'policy-v1'), **changes)


def build(snapshot=None, claims=None):
    return build_threat_reachability(state() if snapshot is None else snapshot,
                                    (claim(),) if claims is None else claims)


def forged(value, **changes):
    """Malformed exact-type fixture for defensive builder validation only."""
    result = object.__new__(type(value))
    for f in fields(value): object.__setattr__(result, f.name, changes.get(f.name, getattr(value, f.name)))
    return result


class ThreatReachabilityTests(unittest.TestCase):
    def blank(self, field):
        class Derived(str): pass
        for value in ('', ' \t\n', None, 1, True, Derived('valid')):
            with self.subTest(value=value), self.assertRaises(ValueError): claim(**{field: value})
        value = '  opaque/\u03b1  '
        self.assertEqual(getattr(claim(**{field: value}), field), value)

    def pair(self, kind, value):
        source = state(kind); result = build(source, (claim(reachability=value),))
        row = result.assessments[0]
        self.assertIs(row.reachability, value)
        self.assertIs(row.threat_state_assessment.state, State(kind))
        self.assertIs(row.threat_state_assessment, source.assessments[0])
        return row

    def imports(self):
        tree = ast.parse(inspect.getsource(reachability))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}

    def output_fields(self):
        return {f.name for cls in (ThreatReachabilityAssessment, ThreatReachabilitySnapshot) for f in fields(cls)}

    def no_terms(self, *terms):
        tree = ast.parse(inspect.getsource(reachability))
        identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertTrue(set(terms).isdisjoint(identifiers | self.output_fields()))

    def pure(self, targets):
        source, claims = state(), (claim(),)
        expected = build(source, claims)
        with ExitStack() as stack:
            for owner, name in targets:
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError('impure dependency')))
            result = build(source, claims)
            self.assertEqual(result, expected)
            self.assertEqual(result.snapshot_id, expected.snapshot_id)

    def test_001_exact_enum(self):
        self.assertEqual(Reach.__members__, {n: Reach(n) for n in ('CAN_AFFECT', 'CANNOT_AFFECT', 'UNKNOWN')})
        self.assertEqual(len(Reach.__members__), len(Reach))

    def test_002_no_safety_or_freshness_enum(self):
        self.assertTrue({'SAFE','UNSAFE','REACHABLE','NOT_REACHABLE','LOW','MEDIUM','HIGH','FRESH','STALE'}.isdisjoint(Reach.__members__))
        enums = [v for v in vars(reachability).values() if isinstance(v, type) and issubclass(v, Enum)
                 and v.__module__ == reachability.__name__]
        self.assertEqual(enums, [Reach])

    def test_003_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().option_id = 'different'

    def test_004_assessment_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assessments[0].reachability = Reach.UNKNOWN

    def test_005_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().evaluated_at_tick = 111

    def test_006_blank_threat(self): self.blank('threat_id')
    def test_007_blank_option(self): self.blank('option_id')
    def test_008_blank_context(self): self.blank('reachability_context_id')
    def test_009_blank_horizon(self): self.blank('horizon_id')
    def test_010_blank_policy(self): self.blank('assessment_policy_id')

    def test_011_concrete_reachability_enum(self):
        class Foreign(str, Enum): CAN_AFFECT = 'CAN_AFFECT'
        for value in ('CAN_AFFECT', None, True, Foreign.CAN_AFFECT):
            with self.assertRaises(TypeError): claim(reachability=value)
            with self.assertRaises(TypeError): build(claims=(forged(claim(), reachability=value),))

    def test_012_exact_claim_tuple(self):
        source = state()
        class Derived(ThreatReachabilityClaim): pass
        class TupleSubclass(tuple): pass
        for value in (None, [], [claim()], (None,), (Derived(**asdict(claim())),), TupleSubclass((claim(),))):
            with self.subTest(value=type(value)), self.assertRaises(TypeError):
                build_threat_reachability(source, value)
        for field in ('threat_id','option_id','reachability_context_id','horizon_id','assessment_policy_id'):
            with self.assertRaises(ValueError): build(source, (forged(claim(), **{field: ''}),))

    def test_013_duplicate_exact_tuple(self):
        for other in (claim(), claim(reachability=Reach.UNKNOWN), claim(assessment_policy_id='v2')):
            with self.assertRaises(ValueError): build(claims=(claim(), other))

    def test_014_different_horizons(self):
        result = build(claims=(claim(horizon_id='short', reachability=Reach.CANNOT_AFFECT),
                               claim(horizon_id='long', reachability=Reach.CAN_AFFECT)))
        self.assertEqual({r.horizon_id: r.reachability for r in result.assessments},
                         {'short': Reach.CANNOT_AFFECT, 'long': Reach.CAN_AFFECT})

    def test_015_different_options(self):
        result = build(claims=(claim(), claim(option_id='take-camp-A')))
        self.assertEqual({r.option_id for r in result.assessments}, {'stay-lane', 'take-camp-A'})

    def test_016_different_threats_same_option(self):
        source = state(subjects=('A','B'))
        result = build(source, (claim(), claim(threat_id='B', reachability=Reach.CANNOT_AFFECT)))
        self.assertEqual([(r.threat_id, r.reachability) for r in result.assessments],
                         [('A', Reach.CAN_AFFECT), ('B', Reach.CANNOT_AFFECT)])

    def test_017_same_threat_context_multiple_options(self):
        options = ('stay-lane', 'farm-wave-top', 'take-camp-A', 'rotate-gate', 'push-tier1')
        rows = build(claims=tuple(claim(option_id=o, reachability=Reach.UNKNOWN) for o in options)).assessments
        self.assertEqual({r.option_id for r in rows}, set(options))
        self.assertTrue(all(r.threat_id == 'A' and r.reachability_context_id == 'context-A' for r in rows))

    def test_018_claim_order_independent(self):
        source = state(); claims = (claim(), claim(horizon_id='B'), claim(option_id='rotate-gate'))
        self.assertEqual(build(source, claims), build(source, tuple(reversed(claims))))

    def test_019_empty_claims(self):
        source = state(); result = build(source, ())
        self.assertEqual(result.assessments, ())
        self.assertEqual(result.threat_state_snapshot_id, source.snapshot_id)
        self.assertEqual(build(replace(source, assessments=()), ()).assessments, ())
        with self.assertRaises(ValueError): build(replace(source, timeline_id=''), ())

    def test_020_subset_claims(self):
        result = build(state(subjects=('A','B','C')), (claim(threat_id='B'),))
        self.assertEqual([r.threat_id for r in result.assessments], ['B'])

    def test_021_no_cartesian_product(self):
        source = state(subjects=('A','B','C'))
        claims = (claim(option_id='one'), claim(threat_id='B', option_id='two', horizon_id='two'))
        self.assertEqual(len(build(source, claims).assessments), 2)
        self.assertEqual({(r.threat_id,r.option_id,r.horizon_id) for r in build(source, claims).assessments},
                         {('A','one','horizon-A'), ('B','two','two')})

    def test_022_no_synthesized_unknown(self):
        source = state('UNKNOWN', subjects=('A','B'))
        self.assertEqual(build(source, ()).assessments, ())
        self.assertEqual(len(build(source, (claim(),)).assessments), 1)

    def test_023_unknown_distinct_from_absence(self):
        source = state(); explicit = build(source, (claim(reachability=Reach.UNKNOWN),)); absent = build(source, ())
        self.assertIs(explicit.assessments[0].reachability, Reach.UNKNOWN)
        self.assertEqual(absent.assessments, ())
        self.assertNotEqual(explicit.snapshot_id, absent.snapshot_id)

    def test_024_exact_state_and_structure(self):
        source = state()
        class Derived(type(source)): pass
        for value in (None, {}, Derived(**asdict(source))):
            with self.assertRaises(TypeError): build_threat_reachability(value, ())
        for value in ([], list(source.assessments), (None,)):
            with self.assertRaises(TypeError): build(replace(source, assessments=value))
        for field in ('timeline_id','selected_clock_id','positive_snapshot_id','missing_snapshot_id'):
            for value in ('', ' ', True):
                with self.subTest(field=field), self.assertRaises(ValueError): build(replace(source, **{field:value}), ())
        row = source.assessments[0]
        for changes in ({'state':'MISSING'}, {'reason':row.reason.value}, {'threat_id':''}):
            with self.assertRaises((TypeError,ValueError)):
                build(replace(source, assessments=(forged(row, **changes),)), ())

    def test_025_foreign_threat(self):
        with self.assertRaises(ValueError): build(claims=(claim(threat_id='foreign'),))
        with self.assertRaises(ValueError): build(replace(state(), assessments=()), (claim(),))

    def test_026_exact_subject_match(self):
        for name in ('a', ' A', 'A ', 'A/suffix', 'pos.A'):
            with self.assertRaises(ValueError): build(claims=(claim(threat_id=name),))
        name = '  opaque/\u03b1  '
        source = state(subjects=(name,))
        self.assertEqual(build(source, (claim(threat_id=name),)).assessments[0].threat_id, name)

    def test_027_complete_state_object_preserved(self):
        source = state(); row = build(source).assessments[0]
        self.assertIs(row.threat_state_assessment, source.assessments[0])
        self.assertIs(row.threat_state_assessment.missing_resolution, source.assessments[0].missing_resolution)
        self.assertEqual(asdict(row.threat_state_assessment), asdict(source.assessments[0]))

    def test_028_duplicate_and_exact_state_rows(self):
        source = state(); row = source.assessments[0]
        with self.assertRaises(ValueError): build(replace(source, assessments=(row,row)), ())
        class Derived(type(row)): pass
        with self.assertRaises(TypeError):
            build(replace(source, assessments=(Derived(**{f.name:getattr(row,f.name) for f in fields(row)}),)), ())

    def test_029_timeline_preserved(self):
        source = replace(state(), timeline_id=' external/\u03b1 ')
        self.assertEqual(build(source).timeline_id, source.timeline_id)
        self.assertNotEqual(build(source).snapshot_id, build().snapshot_id)

    def test_030_clock_preserved(self):
        source = replace(state(), selected_clock_id=' exact-clock ')
        self.assertEqual(build(source).selected_clock_id, source.selected_clock_id)
        self.assertNotEqual(build(source).snapshot_id, build().snapshot_id)

    def test_031_evaluation_tick(self):
        for tick in (-100, 0, 110, 100000):
            source = state(tick=tick)
            self.assertEqual(build(source).evaluated_at_tick, tick)
            self.assertEqual(build(source).assessments[0].threat_state_assessment.assembly_tick, tick)

    def test_032_no_wall_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_033_concrete_ticks_and_enclosing_binding(self):
        source = state(); row = source.assessments[0]
        for value in (True, 110.0, None):
            with self.assertRaises(TypeError): build(replace(source, assembly_tick=value), ())
            with self.assertRaises(TypeError): build(replace(source, assessments=(forged(row, assembly_tick=value),)), ())
        with self.assertRaises(ValueError): build(replace(source, assessments=(replace(row, assembly_tick=111),)), ())

    def test_034_nearby_can(self): self.pair('VISIBLE_NEARBY', Reach.CAN_AFFECT)
    def test_035_nearby_cannot(self): self.pair('VISIBLE_NEARBY', Reach.CANNOT_AFFECT)
    def test_036_nearby_unknown(self): self.pair('VISIBLE_NEARBY', Reach.UNKNOWN)
    def test_037_away_can(self): self.pair('VISIBLE_AWAY', Reach.CAN_AFFECT)
    def test_038_away_cannot(self): self.pair('VISIBLE_AWAY', Reach.CANNOT_AFFECT)
    def test_039_away_unknown(self): self.pair('VISIBLE_AWAY', Reach.UNKNOWN)
    def test_040_missing_can(self): self.pair('MISSING', Reach.CAN_AFFECT)
    def test_041_missing_cannot(self): self.pair('MISSING', Reach.CANNOT_AFFECT)
    def test_042_missing_unknown(self): self.pair('MISSING', Reach.UNKNOWN)
    def test_043_unknown_state_can(self): self.pair('UNKNOWN', Reach.CAN_AFFECT)
    def test_044_unknown_state_cannot(self): self.pair('UNKNOWN', Reach.CANNOT_AFFECT)
    def test_045_unknown_state_unknown(self): self.pair('UNKNOWN', Reach.UNKNOWN)
    def test_046_conflict_can(self): self.pair('CONFLICTED', Reach.CAN_AFFECT)
    def test_047_conflict_cannot(self): self.pair('CONFLICTED', Reach.CANNOT_AFFECT)
    def test_048_conflict_unknown(self): self.pair('CONFLICTED', Reach.UNKNOWN)

    def test_049_no_state_inference(self):
        source = inspect.getsource(reachability)
        tree = ast.parse(source)
        self.assertFalse(any(isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and
                             n.value.id == 'AssembledThreatState' for n in ast.walk(tree)))
        for kind in State:
            self.assertEqual(build(state(kind.value), ()).assessments, ())

    def test_050_no_proximity_inference(self):
        a = build(state('VISIBLE_NEARBY'), (claim(reachability=Reach.CANNOT_AFFECT),)).assessments[0]
        b = build(state('VISIBLE_AWAY'), (claim(reachability=Reach.CANNOT_AFFECT),)).assessments[0]
        self.assertIs(a.reachability, b.reachability)
        self.assertNotEqual(a.threat_state_assessment.state, b.threat_state_assessment.state)
        self.no_terms('proximity')

    def test_051_no_missing_derivation_or_refresh(self):
        from coach02 import missing_threat_resolver, threat_state_assembly, temporal_evidence
        self.pure([(missing_threat_resolver,'resolve_missing_threats'),(threat_state_assembly,'build_threat_state'),
                   (temporal_evidence,'evaluate_freshness'),(temporal_evidence,'record_observations')])
        self.no_terms('temporal_status','age_ticks','last_seen_tick','missing_since_tick')

    def test_052_distinct_contexts(self):
        rows = build(claims=(claim(), claim(reachability_context_id='context-B', reachability=Reach.CANNOT_AFFECT))).assessments
        self.assertEqual({r.reachability_context_id:r.reachability for r in rows},
                         {'context-A':Reach.CAN_AFFECT,'context-B':Reach.CANNOT_AFFECT})

    def identity_change(self, **changes):
        source = state()
        self.assertNotEqual(build(source).snapshot_id, build(source, (claim(**changes),)).snapshot_id)

    def test_053_horizon_identity(self): self.identity_change(horizon_id='next-wave-window')
    def test_054_option_identity(self): self.identity_change(option_id='farm-wave-top')
    def test_055_context_identity(self): self.identity_change(reachability_context_id='another-context')
    def test_056_policy_identity(self): self.identity_change(assessment_policy_id='policy-v2')
    def test_057_semantic_identity(self):
        for value in (Reach.CANNOT_AFFECT, Reach.UNKNOWN): self.identity_change(reachability=value)

    def test_058_upstream_snapshot_identity(self):
        source = state(); different = replace(source, positive_snapshot_id='other-accepted-lineage')
        self.assertNotEqual(source.snapshot_id, different.snapshot_id)
        self.assertNotEqual(build(source).snapshot_id, build(different).snapshot_id)
        self.assertEqual(build(different).threat_state_snapshot_id, different.snapshot_id)

    def test_059_nested_evidence_identity(self):
        source = state(); row = source.assessments[0]
        positive = replace(row.positive_observation, source_id='source-B')
        row = replace(row, positive_observation=positive, missing_resolution=replace(row.missing_resolution, positive=positive))
        different = replace(source, assessments=(row,))
        self.assertNotEqual(build(source).snapshot_id, build(different).snapshot_id)
        self.assertIs(build(different).assessments[0].threat_state_assessment, row)

    def test_060_canonical_identity(self):
        result = build(claims=(claim(horizon_id=' horizon/\u03b1 '),))
        payload = json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'threat.reachability_assessment.v1:snapshot:'+hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.snapshot_id, build(claims=(claim(horizon_id=' horizon/\u03b1 '),)).snapshot_id)

    def test_061_order_independent_identity(self):
        source = state(subjects=('B','A'))
        claims = (claim(threat_id='B'), claim(), claim(option_id='other'))
        self.assertEqual(build(source,claims).snapshot_id, build(source,tuple(reversed(claims))).snapshot_id)

    def test_062_canonical_assessment_order(self):
        source = state(subjects=('B','A'))
        claims = (claim(threat_id='B'),claim(option_id='z'),claim(horizon_id='z'),
                  claim(reachability_context_id='z'),claim())
        keys = lambda c:(c.threat_id,c.option_id,c.reachability_context_id,c.horizon_id,c.assessment_policy_id)
        self.assertEqual([keys(r) for r in build(source,claims).assessments],sorted(keys(c) for c in claims))

    def test_063_threat_assessments_isolated(self):
        source = state(subjects=('A','B')); claims = (claim(),claim(threat_id='B',reachability=Reach.CANNOT_AFFECT))
        rows = build(source,claims).assessments
        self.assertIs(rows[0].reachability,Reach.CAN_AFFECT); self.assertIs(rows[1].reachability,Reach.CANNOT_AFFECT)
        self.assertIs(rows[0].threat_state_assessment,source.assessments[0])
        self.assertIs(rows[1].threat_state_assessment,source.assessments[1])

    def test_064_option_assessments_isolated(self):
        rows = build(claims=(claim(option_id='A'),claim(option_id='B',reachability=Reach.CANNOT_AFFECT))).assessments
        self.assertEqual([(r.option_id,r.reachability) for r in rows],[('A',Reach.CAN_AFFECT),('B',Reach.CANNOT_AFFECT)])

    def test_065_no_threat_evidence_borrowing(self):
        source = state(subjects=('A','B'))
        row = build(source,(claim(threat_id='B'),)).assessments[0]
        self.assertEqual(row.threat_state_assessment.threat_id,'B')
        self.assertEqual(row.threat_state_assessment.positive_observation.threat_id,'B')
        self.assertEqual(row.threat_state_assessment.missing_resolution.threat_id,'B')

    def test_066_no_option_evidence_borrowing(self):
        rows = build(claims=(claim(option_id='A'),claim(option_id='B',reachability=Reach.UNKNOWN))).assessments
        self.assertEqual({r.option_id:r.reachability for r in rows},{'A':Reach.CAN_AFFECT,'B':Reach.UNKNOWN})
        self.assertEqual([r.option_id for r in build(claims=(claim(option_id='A'),)).assessments],['A'])

    def test_067_no_horizon_borrowing(self):
        rows = build(claims=(claim(horizon_id='1-tick',reachability=Reach.CANNOT_AFFECT),
                            claim(horizon_id='1000-seconds',reachability=Reach.CAN_AFFECT))).assessments
        self.assertEqual({r.horizon_id:r.reachability for r in rows},
                         {'1-tick':Reach.CANNOT_AFFECT,'1000-seconds':Reach.CAN_AFFECT})
        # Names do not imply a duration or require an ordering relationship.
        self.assertIs(build(claims=(claim(horizon_id='0-seconds'),)).assessments[0].reachability,Reach.CAN_AFFECT)

    def test_068_no_relevance_output(self): self.no_terms('relevance','relevance_assessment','relevance_context_id')
    def test_069_no_coverage_output(self): self.no_terms('coverage','coverage_observation','coverage_context_id')
    def test_070_no_exposure_output(self): self.no_terms('exposure','exposure_observation','exposure_context_id')
    def test_071_no_risk_output(self): self.no_terms('risk','risk_level','danger','risk_score')
    def test_072_no_safety_output(self): self.no_terms('safety','safe','unsafe','recommendation','action')
    def test_073_no_scoring(self): self.no_terms('score','confidence','probability','weight','rank','sum','float','round')
    def test_074_no_distance(self): self.no_terms('distance','path_distance','euclidean_distance')
    def test_075_no_travel_time(self): self.no_terms('eta','ETA','travel_time','arrival_time','duration')
    def test_076_no_pathfinding(self): self.no_terms('pathfind','navmesh','route','shortest_path','neighbors')
    def test_077_no_geometry(self):
        self.no_terms('coordinates','position','terrain','chokepoint','sqrt','hypot','geometry')
        self.assertTrue({'math','numpy','scipy','networkx'}.isdisjoint(self.imports()))
    def test_078_no_movement(self): self.no_terms('movement_speed','velocity','speed','travel_ticks')
    def test_079_no_blink_logic(self): self.no_terms('blink','blink_range','blink_ready','mobility')
    def test_080_no_teleport_logic(self): self.no_terms('teleport','teleport_ready','twin_gate','force_staff')

    def test_081_no_global_spell_logic(self):
        self.no_terms('global_spell','spell','ability','ability_id')
        c = claim(reachability_context_id='synthetic-global-influence',assessment_policy_id='global-effect-example')
        row = build(claims=(c,)).assessments[0]
        self.assertIs(row.reachability,Reach.CAN_AFFECT)
        self.assertEqual(row.reachability_context_id,c.reachability_context_id)

    def test_082_no_cast_range(self): self.no_terms('cast_range','attack_range','initiation_range','range_bonus')
    def test_083_no_cooldown(self): self.no_terms('cooldown','cooldown_remaining','disable_duration','ready_at')
    def test_084_no_hero_lookup(self): self.no_terms('hero','hero_id','hero_lookup','capability','capabilities')
    def test_085_no_item_lookup(self): self.no_terms('item','item_id','inventory','item_lookup')
    def test_086_no_resource_calculation(self): self.no_terms('mana','hp','health','resource','resources','immunity')

    def test_087_no_relevance_dependency(self):
        self.assertNotIn('.threat_relevance',self.imports())
        from test_risk_evidence_assembly import fixtures
        from coach02.threat_relevance import ThreatRelevance
        snapshots = fixtures(relevance=ThreatRelevance.NOT_RELEVANT)
        row = build(snapshots[0]).assessments[0]
        self.assertIs(snapshots[1].assessments[0].relevance,ThreatRelevance.NOT_RELEVANT)
        self.assertIs(row.reachability,Reach.CAN_AFFECT)

    def test_088_no_coverage_dependency(self):
        self.assertNotIn('.strategic_coverage',self.imports())
        self.assertEqual(list(inspect.signature(build_threat_reachability).parameters),['threat_state_snapshot','claims'])

    def test_089_no_exposure_dependency(self):
        self.assertNotIn('.option_exposure',self.imports())
        from test_risk_evidence_assembly import fixtures
        from coach02.option_exposure import OptionExposureState
        snapshots = fixtures(exposure_rows=(('stay-lane','external',OptionExposureState.NOT_EXPOSED),))
        row = build(snapshots[0]).assessments[0]
        self.assertIs(snapshots[3].observations[0].exposure,OptionExposureState.NOT_EXPOSED)
        self.assertIs(row.reachability,Reach.CAN_AFFECT)

    def test_090_no_risk_evidence_dependency(self): self.assertNotIn('.risk_evidence_assembly',self.imports())
    def test_091_no_safety_dependency(self):
        self.assertTrue({'.safety_evidence','.option_safety','.decision'}.isdisjoint(self.imports()))

    def test_092_no_lower_foundation_imports(self):
        self.assertTrue({'.observation_event','.temporal_evidence','.threat_observation',
                         '.threat_absence_observation','.visibility_completeness','.missing_threat_resolver'}.isdisjoint(self.imports()))

    def test_093_pure_import_surface(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.threat_state_assembly'})

    def test_094_no_io(self):
        import builtins,io,os,subprocess,sqlite3
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(subprocess,'Popen'),(sqlite3,'connect')])

    def test_095_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_096_no_environment(self):
        import os
        class Forbidden(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',Forbidden()): self.pure([(os,'getenv')])

    def test_097_no_random(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])

    def test_098_no_mutable_global_or_scheduling(self):
        before = dict(vars(reachability)); build(); build(state('CONFLICTED'))
        self.assertEqual(before,vars(reachability))
        for name,value in vars(reachability).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(list,dict,set,bytearray))
        tree = ast.parse(inspect.getsource(reachability))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))
        self.no_terms('thread','scheduler','schedule','cache','singleton','lru_cache')

    def test_099_upstream_unchanged(self):
        source = state(subjects=('A','B')); claims = (claim(),claim(threat_id='B',reachability=Reach.UNKNOWN))
        before = asdict(source),source.snapshot_id,tuple(asdict(c) for c in claims)
        build(source,claims); build(source,())
        self.assertEqual(before,(asdict(source),source.snapshot_id,tuple(asdict(c) for c in claims)))

    def test_100_future_composition_review(self):
        from coach02.risk_evidence_assembly import RiskEvidenceBinding, ThreatRiskEvidence, RiskEvidenceSnapshot
        self.assertNotIn('horizon_id',{f.name for f in fields(RiskEvidenceBinding)})
        self.assertNotIn('reachability_context_id',{f.name for f in fields(RiskEvidenceBinding)})
        self.assertNotIn('reachability_assessment',{f.name for f in fields(ThreatRiskEvidence)})
        self.assertNotIn('threat_reachability_snapshot_id',{f.name for f in fields(RiskEvidenceSnapshot)})
        doc=(Path(reachability.__file__).resolve().parent.parent/'THREAT_REACHABILITY_V01.md').read_text(encoding='utf-8')
        for text in ('RISK_EVIDENCE_V02_COMPATIBILITY_REVIEW','reachability_context_id','horizon_id',
                     'CURRENT/HISTORICAL/ABSENT','UNKNOWN','evaluated_at_tick'):
            self.assertIn(text,doc)

    def test_101_no_adapter(self):
        from coach02 import risk_evidence_assembly,safety_evidence,option_safety
        self.pure([(risk_evidence_assembly,'build_risk_evidence'),(safety_evidence,'build_risk_awareness'),
                   (option_safety,'build_option_safety')])
        public={name for name,value in vars(reachability).items() if inspect.isfunction(value)
                and value.__module__==reachability.__name__ and not name.startswith('_')}
        self.assertEqual(public,{'build_threat_reachability'})
        self.assertEqual({f.name for f in fields(ThreatReachabilityAssessment)},
                         {'threat_id','option_id','reachability_context_id','horizon_id','reachability',
                          'assessment_policy_id','threat_state_assessment'})

    def guard(self):
        root=Path(reachability.__file__).resolve().parent.parent
        tree=ast.parse((root/'tests/test_threat_state_assembly.py').read_text(encoding='utf-8'))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_101_dependency_direction')
        selected=[n for n in fn.body if
                  isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
                  {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or
                  isinstance(n,ast.FunctionDef) and n.name=='violations']
        self.assertEqual(len(selected),4)
        namespace={'ast':ast}
        exec(compile(ast.Module(body=selected,type_ignores=[]),'state-guard','exec'),namespace)
        return namespace

    def test_102_dependency_direction(self):
        g=self.guard()
        self.assertEqual(g['authorized_consumers'],{'coach02/risk_evidence_assembly.py','coach02/threat_reachability.py'})
        self.assertEqual(g['violations'](inspect.getsource(reachability),'coach02/threat_reachability.py'),[])
        allowed={'ThreatStateSnapshot','ThreatStateAssessment','AssembledThreatState','ThreatStateReason'}
        tree=ast.parse(inspect.getsource(reachability))
        imported={a.name for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='threat_state_assembly' for a in n.names}
        self.assertEqual(imported,allowed)
        for symbol in allowed:
            self.assertEqual(g['violations']('from .threat_state_assembly import '+symbol,'coach02/threat_reachability.py'),[])
        for symbol in ('ThreatObservation','MissingThreatResolution'):
            source='from .threat_state_assembly import '+symbol
            self.assertTrue(g['violations'](source,'coach02/threat_reachability.py'))
            self.assertEqual(g['violations'](source,'coach02/risk_evidence_assembly.py'),[])
        root=Path(reachability.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evidence_assembly_v02.py'})
        allowed_contracts = frozenset(('ThreatReachabilitySnapshot', 'ThreatReachabilityAssessment', 'ThreatReachability'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure', 'build_risk_evidence', 'build_threat_reachability'))

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
                        if 'threat_reachability' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('threat_reachability' in (node.module or '').split('.') or
                               any(a.name == 'threat_reachability' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'threat_reachability') or
                                        (node.level == 0 and node.module == 'coach02.threat_reachability'))
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
                                       and 'threat_reachability' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .threat_reachability import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evidence_assembly_v02.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .threat_reachability import *', 'import coach02.threat_reachability',
                    'from coach02 import threat_reachability', "__import__('coach02.threat_reachability')"]
        for symbol in allowed_contracts:
            rejected.append('from .threat_reachability import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .threat_reachability import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evidence_assembly_v02.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/threat_reachability.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_103_restricted_consumers(self):
        g=self.guard()
        for symbol in g['allowed_contracts']:
            source='from .threat_state_assembly import '+symbol
            for path in ('coach02/arbitrary_future.py','coach02/service.py','coach02/decision.py','run.py'):
                self.assertTrue(g['violations'](source,path))
        sources=['from .threat_state_assembly import *','import coach02.threat_state_assembly',
                 'from coach02 import threat_state_assembly',
                 "import importlib as loader; loader.import_module('coach02.threat_state_assembly')",
                 "from importlib import import_module as load; load('coach02.threat_state_assembly')"]
        for symbol in g['allowed_contracts']:
            sources.append('from .threat_state_assembly import '+symbol+' as C; alias=C; alias()')
        for operation in g['operations']:
            sources.append('from .threat_state_assembly import '+operation+' as run; alias=run; alias()')
            sources.append('runtime.'+operation+'()')
        for source in sources:
            with self.subTest(source=source): self.assertTrue(g['violations'](source,'coach02/threat_reachability.py'))

    def test_104_existing_production_hashes(self):
        root=Path(reachability.__file__).resolve().parent.parent
        self.assertEqual(len(PRODUCTION_HASHES),42)
        for name,sha in PRODUCTION_HASHES:
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),sha)


PRODUCTION_HASHES = (('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'))
