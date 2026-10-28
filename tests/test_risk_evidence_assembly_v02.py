"""Version recovery and explicit reachability extension using synthetic evidence."""
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

from coach02 import risk_evidence_assembly_v02 as extension
from coach02.risk_evidence_assembly_v02 import (
    RiskEvidenceReachabilityBinding, ThreatRiskEvidenceV2, OptionRiskEvidenceBundleV2,
    RiskEvidenceSnapshotV2, build_risk_evidence_v2,
)
from coach02.risk_evidence_assembly import EvidenceUseStatus as Use, build_risk_evidence
from coach02.threat_reachability import ThreatReachability as Reach, ThreatReachabilityClaim, build_threat_reachability
from coach02.threat_state_assembly import AssembledThreatState as State
from coach02.threat_relevance import ThreatRelevance as Rel
from coach02.option_exposure import OptionExposureState as Exposure
from coach02.strategic_coverage import StrategicCoverageState as Coverage
from test_risk_evidence_assembly import fixtures, binding as base_binding


def reach_claim(**changes):
    return replace(ThreatReachabilityClaim('A','option-A','REACH-3','H-short',Reach.CAN_AFFECT,'reach-v1'),**changes)


def binding(**changes):
    return replace(RiskEvidenceReachabilityBinding('R','option-A','REACH-3','H-short','extension-v1'),**changes)


def inputs(base_bindings=None, reach_claims=None, **kwargs):
    four=fixtures(**kwargs)
    base=build_risk_evidence(*four,(base_binding(),) if base_bindings is None else base_bindings)
    claims=(tuple(reach_claim(threat_id=r.threat_id) for r in four[0].assessments)
            if reach_claims is None else reach_claims)
    return base,build_threat_reachability(four[0],claims)


def build(pair=None, bindings=None):
    base,reach=inputs() if pair is None else pair
    selected=(tuple(binding(risk_context_id=b.risk_context_id,option_id=b.option_id) for b in base.bundles)
              if bindings is None else bindings)
    return build_risk_evidence_v2(base,reach,selected)


def row(pair=None, bindings=None): return build(pair,bindings).bundles[0].threats[0]


class RiskEvidenceV2Tests(unittest.TestCase):
    def blank(self,field):
        class Derived(str): pass
        for value in ('',' \t',None,True,Derived('value')):
            with self.assertRaises(ValueError): binding(**{field:value})
        value=' opaque/\u03b1 '
        self.assertEqual(getattr(binding(**{field:value}),field),value)

    def imports(self):
        tree=ast.parse(inspect.getsource(extension))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def no_terms(self,*terms):
        tree=ast.parse(inspect.getsource(extension))
        identifiers={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        outputs={f.name for cls in (ThreatRiskEvidenceV2,OptionRiskEvidenceBundleV2,RiskEvidenceSnapshotV2) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(identifiers|outputs))

    def pure(self,targets):
        pair=inputs(); bindings=(binding(),); expected=build(pair,bindings)
        with ExitStack() as stack:
            for owner,name in targets:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure call')))
            result=build(pair,bindings)
            self.assertEqual(result,expected); self.assertEqual(result.snapshot_id,expected.snapshot_id)

    def test_001_exact_binding_type(self):
        class Derived(RiskEvidenceReachabilityBinding): pass
        for value in (None,{},Derived(**asdict(binding()))):
            with self.assertRaises(TypeError): build(bindings=(value,))

    def test_002_frozen_contracts(self):
        result=build()
        for obj in (binding(),result,result.bundles[0],result.bundles[0].threats[0]):
            with self.assertRaises(FrozenInstanceError): setattr(obj,fields(obj)[0].name,None)

    def test_003_blank_risk_context(self): self.blank('risk_context_id')
    def test_004_blank_option(self): self.blank('option_id')
    def test_005_blank_reachability_context(self): self.blank('reachability_context_id')
    def test_006_blank_horizon(self): self.blank('horizon_id')
    def test_007_blank_extension_policy(self): self.blank('reachability_binding_policy_id')

    def test_008_exact_binding_tuple(self):
        pair=inputs()
        class Derived(tuple): pass
        for value in ([],[binding()],None,Derived((binding(),))):
            with self.assertRaises(TypeError): build_risk_evidence_v2(*pair,value)

    def test_009_duplicate_extension(self):
        for other in (binding(),binding(horizon_id='other'),binding(reachability_binding_policy_id='v2')):
            with self.assertRaises(ValueError): build(bindings=(binding(),other))

    def test_010_complete_extension(self):
        pair=inputs(base_bindings=(base_binding(),base_binding(option_id='option-B')))
        result=build(pair,(binding(),binding(option_id='option-B')))
        self.assertEqual(len(result.bundles),2)
        self.assertIs(result.bundles[1].threats[0].reachability_use,Use.ABSENT)

    def test_011_missing_extension(self):
        with self.assertRaises(ValueError): build(bindings=())
        pair=inputs(base_bindings=(base_binding(),base_binding(option_id='B')))
        with self.assertRaises(ValueError): build(pair,(binding(),))

    def test_012_extra_extension(self):
        with self.assertRaises(ValueError): build(bindings=(binding(),binding(option_id='foreign')))
        with self.assertRaises(ValueError): build(bindings=(binding(risk_context_id='foreign'),))

    def test_013_empty_base(self):
        pair=inputs(base_bindings=())
        self.assertEqual(build(pair,()).bundles,())
        with self.assertRaises(ValueError): build(pair,(binding(),))
        pair=inputs(base_bindings=(),reach_claims=())
        self.assertEqual(build(pair,()).bundles,())

    def test_014_exact_base_and_containers(self):
        base,reach=inputs()
        class Derived(type(base)): pass
        for value in (None,{},Derived(**asdict(base))):
            with self.assertRaises(TypeError): build_risk_evidence_v2(value,reach,())
        for value in ([],list(base.bundles),(None,)):
            with self.assertRaises(TypeError): build_risk_evidence_v2(replace(base,bundles=value),reach,())
        with self.assertRaises(ValueError): build((replace(base,bundles=base.bundles*2),reach))
        b=base.bundles[0]
        for value in ([],(None,)):
            with self.assertRaises(TypeError): build((replace(base,bundles=(replace(b,threats=value),)),reach))
        with self.assertRaises(ValueError): build((replace(base,bundles=(replace(b,threats=b.threats*2),)),reach))
        for field in ('timeline_id','selected_clock_id','threat_state_snapshot_id','threat_relevance_snapshot_id',
                      'strategic_coverage_snapshot_id','option_exposure_snapshot_id'):
            with self.assertRaises(ValueError): build((replace(base,**{field:''}),reach))
        for field in ('risk_context_id','option_id','relevance_context_id','coverage_context_id','exposure_context_id','binding_policy_id'):
            with self.assertRaises(ValueError): build((replace(base,bundles=(replace(b,**{field:''}),)),reach))

    def test_015_exact_reachability_and_structure(self):
        base,reach=inputs()
        class Derived(type(reach)): pass
        for value in (None,{},Derived(**asdict(reach))):
            with self.assertRaises(TypeError): build_risk_evidence_v2(base,value,())
        for value in ([],list(reach.assessments),(None,)):
            with self.assertRaises(TypeError): build((base,replace(reach,assessments=value)))
        r=reach.assessments[0]
        for field in ('threat_id','option_id','reachability_context_id','horizon_id','assessment_policy_id'):
            with self.assertRaises(ValueError): build((base,replace(reach,assessments=(replace(r,**{field:''}),))))
        with self.assertRaises(TypeError):
            build((base,replace(reach,assessments=(replace(r,reachability='CAN_AFFECT'),))))

    def test_016_timeline_mismatch(self):
        base,reach=inputs()
        for value in ('foreign','',True):
            with self.assertRaises(ValueError): build((base,replace(reach,timeline_id=value)))

    def test_017_clock_mismatch(self):
        base,reach=inputs()
        for value in ('foreign','',True):
            with self.assertRaises(ValueError): build((base,replace(reach,selected_clock_id=value)))

    def test_018_exact_state_identity(self):
        base,reach=inputs()
        with self.assertRaises(ValueError): build((base,replace(reach,threat_state_snapshot_id='other')))

    def test_019_preserved_state_lineage(self):
        base,reach=inputs(); other=inputs(state_kind='CONFLICTED')[1]
        with self.assertRaises(ValueError): build((base,other))
        with self.assertRaises(ValueError): build((base,replace(other,threat_state_snapshot_id=base.threat_state_snapshot_id)))
        with self.assertRaises(ValueError): build((base,replace(reach,evaluated_at_tick=109)))
        r=reach.assessments[0]
        with self.assertRaises(ValueError): build((base,replace(reach,assessments=(replace(r,threat_id='B'),))))

    def test_020_concrete_ticks(self):
        base,reach=inputs()
        for value in (110.0,'110',None):
            with self.assertRaises(TypeError): build((replace(base,risk_assembly_tick=value),reach))
            with self.assertRaises(TypeError): build((base,replace(reach,evaluated_at_tick=value)))

    def test_021_bool_ticks(self):
        base,reach=inputs()
        with self.assertRaises(TypeError): build((base,replace(reach,evaluated_at_tick=True)))
        with self.assertRaises(TypeError): build((replace(base,risk_assembly_tick=True),reach))
        b=base.bundles[0]
        with self.assertRaises(TypeError): build((replace(base,bundles=(replace(b,risk_assembly_tick=True),)),reach))

    def test_022_common_tick(self):
        for kwargs in ({},{'coverage_now':120},{'exposure_now':130},{'threat_tick':-20,'exposure_now':-10}):
            pair=inputs(**kwargs); result=build(pair)
            self.assertEqual(result.risk_assembly_tick,max(pair[0].risk_assembly_tick,pair[1].evaluated_at_tick))
            self.assertEqual(result.risk_assembly_tick,pair[0].risk_assembly_tick)

    def test_023_later_reachability_rejected(self):
        base,reach=inputs()
        with self.assertRaisesRegex(ValueError,'V02_TEMPORAL_EXTENSION_ALIGNMENT_RULE'):
            build((base,replace(reach,evaluated_at_tick=111)))

    def test_024_alignment_applies_even_empty(self):
        base,reach=inputs(base_bindings=(),reach_claims=())
        with self.assertRaisesRegex(ValueError,'V02_TEMPORAL_EXTENSION_ALIGNMENT_RULE'):
            build((base,replace(reach,evaluated_at_tick=111)),())
        self.assertEqual(build((base,reach),()).risk_assembly_tick,110)

    def preserved_use(self,field,kwargs,threat_axis=False):
        pair=inputs(**kwargs); original=pair[0].bundles[0]
        result=build(pair).bundles[0]
        if threat_axis:
            self.assertIs(getattr(result.threats[0].base_threat_evidence,field),getattr(original.threats[0],field))
        else: self.assertIs(getattr(result.base_bundle,field),getattr(original,field))

    def test_025_state_use_preserved(self):
        for kwargs in ({},{'exposure_now':120}): self.preserved_use('state_use',kwargs,True)

    def test_026_relevance_use_preserved(self):
        for kwargs in ({},{'exposure_now':120},{'relevance_subjects':()}): self.preserved_use('relevance_use',kwargs,True)

    def test_027_coverage_use_preserved(self):
        for kwargs in ({},{'coverage_now':100},{'coverage_tick':99},{'coverage_rows':()}): self.preserved_use('coverage_use',kwargs)

    def test_028_exposure_use_preserved(self):
        for kwargs in ({},{'exposure_now':100},{'exposure_tick':99},{'exposure_rows':()}): self.preserved_use('exposure_use',kwargs)

    def test_029_base_bundle_object_preserved(self):
        pair=inputs(); self.assertIs(build(pair).bundles[0].base_bundle,pair[0].bundles[0])

    def test_030_base_threat_object_preserved(self):
        pair=inputs(); self.assertIs(row(pair).base_threat_evidence,pair[0].bundles[0].threats[0])

    def test_031_exact_threat_correspondence(self):
        pair=inputs(subjects=('C','A','B'),base_bindings=(base_binding(),base_binding(option_id='B')))
        for old,new in zip(pair[0].bundles,build(pair).bundles):
            self.assertEqual(tuple(r.base_threat_evidence for r in new.threats),old.threats)
            self.assertTrue(all(r.base_threat_evidence is b for r,b in zip(new.threats,old.threats)))

    def test_032_no_subject_added(self):
        pair=inputs(reach_claims=(reach_claim(option_id='unselected'),))
        self.assertEqual([r.base_threat_evidence.threat_id for r in build(pair).bundles[0].threats],['A'])

    def test_033_no_subject_removed(self):
        pair=inputs(subjects=('A','B','C'),reach_claims=())
        rows=build(pair).bundles[0].threats
        self.assertEqual(len(rows),3); self.assertTrue(all(r.reachability_use is Use.ABSENT for r in rows))

    def test_034_exact_reachability_object(self):
        pair=inputs(); self.assertIs(row(pair).reachability_assessment,pair[1].assessments[0])

    def test_035_threat_selection(self):
        pair=inputs(subjects=('A','B'),reach_claims=(reach_claim(threat_id='B'),))
        a,b=build(pair).bundles[0].threats
        self.assertIs(a.reachability_use,Use.ABSENT); self.assertEqual(b.reachability_assessment.threat_id,'B')

    def test_036_option_selection(self):
        claims=(reach_claim(),reach_claim(option_id='B',reachability=Reach.CANNOT_AFFECT))
        pair=inputs(base_bindings=(base_binding(),base_binding(option_id='B')),reach_claims=claims)
        found={b.base_bundle.option_id:b.threats[0].reachability_assessment.reachability for b in build(pair).bundles}
        self.assertEqual(found,{'option-A':Reach.CAN_AFFECT,'B':Reach.CANNOT_AFFECT})

    def test_037_context_selection(self):
        claims=(reach_claim(),reach_claim(reachability_context_id='other',reachability=Reach.CANNOT_AFFECT))
        selected=row(inputs(reach_claims=claims),(binding(reachability_context_id='other'),))
        self.assertIs(selected.reachability_assessment.reachability,Reach.CANNOT_AFFECT)

    def test_038_horizon_selection(self):
        claims=(reach_claim(),reach_claim(horizon_id='long',reachability=Reach.UNKNOWN))
        self.assertIs(row(inputs(reach_claims=claims),(binding(horizon_id='long'),)).reachability_assessment.reachability,Reach.UNKNOWN)

    def test_039_wrong_context_absent(self):
        r=row(bindings=(binding(reachability_context_id='other'),))
        self.assertIsNone(r.reachability_assessment); self.assertIs(r.reachability_use,Use.ABSENT)

    def test_040_wrong_horizon_absent(self):
        r=row(bindings=(binding(horizon_id='long'),))
        self.assertIsNone(r.reachability_assessment); self.assertIs(r.reachability_use,Use.ABSENT)

    def test_041_wrong_option_absent(self):
        r=row(inputs(reach_claims=(reach_claim(option_id='B'),)))
        self.assertIsNone(r.reachability_assessment); self.assertIs(r.reachability_use,Use.ABSENT)

    def test_042_unknown_versus_absent(self):
        pair=inputs(reach_claims=(reach_claim(reachability=Reach.UNKNOWN),))
        current=build(pair); absent=build(pair,(binding(horizon_id='unselected'),))
        self.assertIs(current.bundles[0].threats[0].reachability_assessment.reachability,Reach.UNKNOWN)
        self.assertIs(current.bundles[0].threats[0].reachability_use,Use.CURRENT)
        self.assertIsNone(absent.bundles[0].threats[0].reachability_assessment)
        self.assertIs(absent.bundles[0].threats[0].reachability_use,Use.ABSENT)
        self.assertNotEqual(current.snapshot_id,absent.snapshot_id)

    def current(self,value):
        r=row(inputs(reach_claims=(reach_claim(reachability=value),)))
        self.assertIs(r.reachability_assessment.reachability,value); self.assertIs(r.reachability_use,Use.CURRENT)

    def test_043_can_current(self): self.current(Reach.CAN_AFFECT)
    def test_044_cannot_current(self): self.current(Reach.CANNOT_AFFECT)
    def test_045_unknown_current(self): self.current(Reach.UNKNOWN)

    def historical(self,value):
        pair=inputs(exposure_now=120,reach_claims=(reach_claim(reachability=value),))
        r=row(pair)
        self.assertIs(r.reachability_assessment.reachability,value); self.assertIs(r.reachability_use,Use.HISTORICAL)
        self.assertIs(r.reachability_assessment,pair[1].assessments[0])

    def test_046_can_historical(self): self.historical(Reach.CAN_AFFECT)
    def test_047_cannot_historical(self): self.historical(Reach.CANNOT_AFFECT)
    def test_048_unknown_historical(self): self.historical(Reach.UNKNOWN)

    def test_049_current_alignment(self):
        pair=inputs(); result=build(pair)
        self.assertEqual(pair[1].evaluated_at_tick,result.risk_assembly_tick)
        self.assertIs(result.bundles[0].threats[0].reachability_use,Use.CURRENT)

    def test_050_historical_alignment(self):
        pair=inputs(coverage_now=120); result=build(pair)
        self.assertLess(pair[1].evaluated_at_tick,result.risk_assembly_tick)
        self.assertIs(result.bundles[0].threats[0].reachability_use,Use.HISTORICAL)

    def test_051_no_new_freshness_enum(self):
        self.assertIs(extension.EvidenceUseStatus,Use)
        self.assertFalse(any(isinstance(v,type) and issubclass(v,Enum) and v.__module__==extension.__name__ for v in vars(extension).values()))
        self.no_terms('FRESH','STALE','temporal_status','max_age_ticks','age_ticks')

    def test_052_valid_extra_assessments(self):
        claims=(reach_claim(),reach_claim(option_id='other',reachability_context_id='unused',horizon_id='unused'))
        pair=inputs(reach_claims=claims)
        self.assertEqual(len(build(pair).bundles[0].threats),1)
        self.assertEqual(row(pair).reachability_assessment.option_id,'option-A')

    def test_053_extra_option_ignored(self):
        pair=inputs(reach_claims=(reach_claim(option_id='other'),))
        self.assertIs(row(pair).reachability_use,Use.ABSENT)
        self.assertEqual(len(build(pair).bundles),1)

    def test_054_extra_horizon_ignored(self):
        pair=inputs(reach_claims=(reach_claim(horizon_id='long'),))
        self.assertIs(row(pair).reachability_use,Use.ABSENT)
        self.assertEqual(build(pair).bundles[0].horizon_id,'H-short')

    def test_055_not_relevant_preserved(self):
        r=row(inputs(relevance=Rel.NOT_RELEVANT))
        self.assertIs(r.base_threat_evidence.relevance_assessment.relevance,Rel.NOT_RELEVANT)
        self.assertIs(r.reachability_assessment.reachability,Reach.CAN_AFFECT)

    def test_056_conflicted_preserved(self):
        r=row(inputs(state_kind='CONFLICTED'))
        self.assertIs(r.base_threat_evidence.state_assessment.state,State.CONFLICTED)
        self.assertIs(r.reachability_assessment.reachability,Reach.CAN_AFFECT)

    def test_057_unknown_state_preserved(self):
        self.assertIs(row(inputs(state_kind='UNKNOWN')).base_threat_evidence.state_assessment.state,State.UNKNOWN)

    def test_058_absent_relevance_preserved(self):
        r=row(inputs(relevance_subjects=()))
        self.assertIsNone(r.base_threat_evidence.relevance_assessment)
        self.assertIs(r.base_threat_evidence.relevance_use,Use.ABSENT)

    def test_059_cannot_not_dropped(self):
        result=build(inputs(reach_claims=(reach_claim(reachability=Reach.CANNOT_AFFECT),)))
        self.assertEqual(len(result.bundles[0].threats),1)
        self.assertIs(result.bundles[0].threats[0].reachability_assessment.reachability,Reach.CANNOT_AFFECT)

    def test_060_can_not_promoted(self):
        pair=inputs(subjects=('A','B'),reach_claims=(reach_claim(threat_id='B'),))
        self.assertEqual([r.base_threat_evidence.threat_id for r in build(pair).bundles[0].threats],['A','B'])

    def test_061_no_reachability_filter(self):
        claims=tuple(reach_claim(threat_id=t,reachability=v) for t,v in zip(('A','B','C'),Reach))
        rows=build(inputs(subjects=('C','B','A'),reach_claims=claims)).bundles[0].threats
        self.assertEqual([r.base_threat_evidence.threat_id for r in rows],['A','B','C'])
        self.assertEqual({r.reachability_assessment.reachability for r in rows},set(Reach))

    def test_062_no_risk_classification(self):
        self.no_terms('risk','risk_level','danger','verdict','risk_score','SAFE','UNSAFE')
        pair=inputs(); b=build(pair).bundles[0]; t=b.threats[0]
        self.assertIs(t.base_threat_evidence.state_assessment.state,State.MISSING)
        self.assertIs(t.base_threat_evidence.relevance_assessment.relevance,Rel.RELEVANT)
        self.assertIs(b.base_bundle.coverage_observation.coverage,Coverage.SUFFICIENT)
        self.assertIs(b.base_bundle.exposure_observation.exposure,Exposure.EXPOSED)
        self.assertIs(t.reachability_assessment.reachability,Reach.CAN_AFFECT)
        self.assertIs(t.reachability_use,Use.CURRENT)

    def test_063_no_safety_classification(self):
        self.no_terms('safety','safe','unsafe','safety_state')
        for value in (Exposure.EXPOSED,Exposure.NOT_EXPOSED):
            pair=inputs(exposure_rows=(('option-A','EXP-A',value),))
            b=build(pair).bundles[0]
            self.assertIs(b.base_bundle.exposure_observation.exposure,value)
            self.assertIs(b.threats[0].reachability_assessment.reachability,Reach.CAN_AFFECT)

    def test_064_no_score(self): self.no_terms('score','weight','rank','sum','round')
    def test_065_no_probability(self): self.no_terms('probability','confidence','likelihood')
    def test_066_no_recommendation(self): self.no_terms('recommendation','action','best_option','priority')
    def test_067_no_capability_calculation(self): self.no_terms('capability','capabilities','damage','disable_duration','mana','health')
    def test_068_no_distance(self): self.no_terms('distance','coordinates','position','sqrt','hypot','travel_time','eta')
    def test_069_no_pathfinding(self): self.no_terms('pathfind','navmesh','route','shortest_path','terrain')
    def test_070_no_mobility(self): self.no_terms('mobility','speed','blink','teleport','global_spell','cast_range')
    def test_071_no_cooldown(self): self.no_terms('cooldown','cooldown_remaining','ready_at')
    def test_072_no_hero_item_lookup(self): self.no_terms('hero','hero_id','item','inventory','item_id')

    def test_073_no_original_domain_imports(self):
        self.assertTrue({'.threat_state_assembly','.threat_relevance','.strategic_coverage','.option_exposure',
            '.observation_event','.temporal_evidence','.missing_threat_resolver','.visibility_completeness',
            '.threat_observation','.threat_absence_observation'}.isdisjoint(self.imports()))

    def test_074_no_safety_import(self): self.assertNotIn('.safety_evidence',self.imports())
    def test_075_no_option_safety_import(self): self.assertNotIn('.option_safety',self.imports())
    def test_076_no_decision_import(self): self.assertNotIn('.decision',self.imports())
    def test_077_only_contract_imports(self):
        self.assertEqual(self.imports(),{'dataclasses','hashlib','json','.risk_evidence_assembly','.threat_reachability'})

    def test_078_no_wall_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_079_no_io(self):
        import builtins,io,os,subprocess,sqlite3
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(subprocess,'Popen'),(sqlite3,'connect')])

    def test_080_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_081_no_environment(self):
        import os
        class Forbidden(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',Forbidden()): self.pure([(os,'getenv')])

    def test_082_no_random(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])

    def test_083_no_mutable_globals(self):
        before=dict(vars(extension)); build(); build(inputs(exposure_now=120))
        self.assertEqual(before,vars(extension))
        for name,value in vars(extension).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray))
        tree=ast.parse(inspect.getsource(extension))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(tree)))
        self.no_terms('cache','scheduler','thread','singleton','lru_cache')

    def test_084_deterministic_identity(self):
        result=build(bindings=(binding(reachability_binding_policy_id=' policy/\u03b1 '),))
        payload=json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'risk.evidence_assembly.v2:snapshot:'+hashlib.sha256(payload).hexdigest())
        self.assertEqual(result.snapshot_id,build(bindings=(binding(reachability_binding_policy_id=' policy/\u03b1 '),)).snapshot_id)

    def test_085_binding_order_independent(self):
        pair=inputs(base_bindings=(base_binding(option_id='B'),base_binding()))
        bindings=(binding(),binding(option_id='B'))
        first,second=build(pair,bindings),build(pair,tuple(reversed(bindings)))
        self.assertEqual(first,second); self.assertEqual(first.snapshot_id,second.snapshot_id)
        self.assertEqual(tuple(b.base_bundle for b in first.bundles),pair[0].bundles)

    def test_086_reachability_state_identity(self):
        self.assertNotEqual(build().snapshot_id,build(inputs(reach_claims=(reach_claim(reachability=Reach.CANNOT_AFFECT),))).snapshot_id)

    def test_087_reachability_context_identity(self):
        self.assertNotEqual(build().snapshot_id,build(bindings=(binding(reachability_context_id='other'),)).snapshot_id)

    def test_088_horizon_identity(self):
        self.assertNotEqual(build().snapshot_id,build(bindings=(binding(horizon_id='other'),)).snapshot_id)

    def test_089_extension_policy_identity(self):
        pair=inputs(); one=build(pair); two=build(pair,(binding(reachability_binding_policy_id='v2'),))
        self.assertNotEqual(one.snapshot_id,two.snapshot_id)
        self.assertIs(one.bundles[0].base_bundle,two.bundles[0].base_bundle)
        self.assertEqual(two.bundles[0].base_bundle.binding_policy_id,'binding-v1')

    def test_090_reachability_snapshot_identity(self):
        one=build(); two=build(inputs(reach_claims=(reach_claim(),reach_claim(option_id='unused'))))
        self.assertNotEqual(one.threat_reachability_snapshot_id,two.threat_reachability_snapshot_id)
        self.assertNotEqual(one.snapshot_id,two.snapshot_id)
        self.assertEqual(one.bundles,two.bundles)

    def test_091_base_snapshot_identity(self):
        base,reach=inputs(); other=replace(base,option_exposure_snapshot_id='another-accepted-source')
        one,two=build((base,reach)),build((other,reach))
        self.assertNotEqual(one.base_risk_evidence_snapshot_id,two.base_risk_evidence_snapshot_id)
        self.assertNotEqual(one.snapshot_id,two.snapshot_id)
        self.assertEqual(one.bundles,two.bundles)

    def test_092_use_status_identity(self):
        original=build(); b=original.bundles[0]; r=b.threats[0]
        changed=replace(original,bundles=(replace(b,threats=(replace(r,reachability_use=Use.HISTORICAL),)),))
        self.assertNotEqual(original.snapshot_id,changed.snapshot_id)

    def test_093_base_identity_and_inputs_unchanged(self):
        pair=inputs(exposure_now=120); before=tuple((asdict(s),s.snapshot_id) for s in pair)
        result=build(pair)
        self.assertEqual(before,tuple((asdict(s),s.snapshot_id) for s in pair))
        self.assertEqual(asdict(result.bundles[0].base_bundle),asdict(pair[0].bundles[0]))
        self.assertEqual(result.base_risk_evidence_snapshot_id,pair[0].snapshot_id)

    def test_094_strip_extension_recovers_v1(self):
        pair=inputs(subjects=('A','B'),relevance_subjects=('A',),coverage_now=100,
                    base_bindings=(base_binding(),base_binding(risk_context_id='R2')))
        recovered=tuple(b.base_bundle for b in build(pair).bundles)
        self.assertEqual(recovered,pair[0].bundles)
        self.assertTrue(all(a is b for a,b in zip(recovered,pair[0].bundles)))
        self.assertEqual(replace(pair[0],bundles=recovered).snapshot_id,pair[0].snapshot_id)

    def test_095_empty_deterministic(self):
        pair=inputs(base_bindings=(),reach_claims=())
        one,two=build(pair,()),build(pair,())
        self.assertEqual(one.bundles,()); self.assertEqual(one.snapshot_id,two.snapshot_id)
        self.assertEqual(one.base_risk_evidence_snapshot_id,pair[0].snapshot_id)
        self.assertEqual(one.threat_reachability_snapshot_id,pair[1].snapshot_id)

    def test_096_multiple_options_independent(self):
        pair=inputs(base_bindings=(base_binding(),base_binding(option_id='B')),
                    reach_claims=(reach_claim(),reach_claim(option_id='B',reachability=Reach.UNKNOWN)))
        values={b.base_bundle.option_id:b.threats[0].reachability_assessment.reachability for b in build(pair).bundles}
        self.assertEqual(values,{'option-A':Reach.CAN_AFFECT,'B':Reach.UNKNOWN})

    def test_097_same_option_multiple_risk_contexts(self):
        pair=inputs(base_bindings=(base_binding(),base_binding(risk_context_id='R2')),
                    reach_claims=(reach_claim(),reach_claim(horizon_id='long',reachability=Reach.CANNOT_AFFECT)))
        rows=build(pair,(binding(),binding(risk_context_id='R2',horizon_id='long'))).bundles
        self.assertIs(rows[0].threats[0].reachability_assessment.reachability,Reach.CAN_AFFECT)
        self.assertIs(rows[1].threats[0].reachability_assessment.reachability,Reach.CANNOT_AFFECT)
        self.assertEqual(rows[0].base_bundle.option_id,rows[1].base_bundle.option_id)

    def test_098_no_cross_option_borrowing(self):
        pair=inputs(base_bindings=(base_binding(),base_binding(option_id='B')))
        values={b.base_bundle.option_id:b.threats[0].reachability_use for b in build(pair).bundles}
        self.assertEqual(values,{'option-A':Use.CURRENT,'B':Use.ABSENT})

    def test_099_no_cross_threat_borrowing(self):
        pair=inputs(subjects=('A','B'),reach_claims=(reach_claim(),))
        values={r.base_threat_evidence.threat_id:r.reachability_use for r in build(pair).bundles[0].threats}
        self.assertEqual(values,{'A':Use.CURRENT,'B':Use.ABSENT})

    def test_100_duplicate_reachability_rejected(self):
        base,reach=inputs()
        with self.assertRaises(ValueError): build((base,replace(reach,assessments=reach.assessments*2)))
        base,reach=inputs(reach_claims=(reach_claim(option_id='unselected'),))
        with self.assertRaises(ValueError): build((base,replace(reach,assessments=reach.assessments*2)))

    def guards(self):
        root=Path(extension.__file__).resolve().parent.parent
        for filename,module in (('test_risk_evidence_assembly.py','risk_evidence_assembly'),
                                ('test_threat_reachability.py','threat_reachability')):
            tree=ast.parse((root/'tests'/filename).read_text(encoding='utf-8'))
            fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_102_dependency_direction')
            selected=[n for n in fn.body if
                      isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
                      {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or
                      isinstance(n,ast.FunctionDef) and n.name=='violations']
            self.assertEqual(len(selected),4)
            namespace={'ast':ast}
            exec(compile(ast.Module(body=selected,type_ignores=[]),filename,'exec'),namespace)
            yield module,namespace

    def test_101_dependency_direction(self):
        source=inspect.getsource(extension)
        symbols={n.module:{a.name for a in n.names} for n in ast.parse(source).body if isinstance(n,ast.ImportFrom) and n.level==1}
        for module,g in self.guards():
            self.assertEqual(g['authorized_consumers'],{'coach02/risk_evidence_assembly_v02.py'})
            self.assertEqual(g['allowed_contracts'],symbols[module])
            self.assertEqual(g['violations'](source,'coach02/risk_evidence_assembly_v02.py'),[])
        root=Path(extension.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evaluation.py'})
        allowed_contracts = frozenset(('RiskEvidenceSnapshotV2', 'OptionRiskEvidenceBundleV2', 'ThreatRiskEvidenceV2', 'EvidenceUseStatus'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure', 'build_risk_evidence', 'build_risk_evidence_v2', 'build_threat_reachability'))

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
                        if 'risk_evidence_assembly_v02' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('risk_evidence_assembly_v02' in (node.module or '').split('.') or
                               any(a.name == 'risk_evidence_assembly_v02' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'risk_evidence_assembly_v02') or
                                        (node.level == 0 and node.module == 'coach02.risk_evidence_assembly_v02'))
                        if not consumer or not exact_module:
                            errors.append('unauthorized production consumer or import path')
                        for alias in node.names:
                            if alias.asname is not None:
                                errors.append('contract import alias not required')
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
                        if (isinstance(value, ast.Name) and value.id in blocked_calls or
                                consumer and value is not None and any(isinstance(n, ast.Attribute) and n.attr == '__annotations__' for n in ast.walk(value))):
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
                                       and 'risk_evidence_assembly_v02' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .risk_evidence_assembly_v02 import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evaluation.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .risk_evidence_assembly_v02 import *', 'import coach02.risk_evidence_assembly_v02',
                    'from coach02 import risk_evidence_assembly_v02', "__import__('coach02.risk_evidence_assembly_v02')"]
        for symbol in allowed_contracts:
            rejected.append('from .risk_evidence_assembly_v02 import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .risk_evidence_assembly_v02 import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evaluation.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/risk_evidence_assembly_v02.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_102_restricted_consumers(self):
        for module,g in self.guards():
            for symbol in g['allowed_contracts']:
                source='from .'+module+' import '+symbol
                for path in ('coach02/arbitrary_future.py','coach02/service.py','coach02/decision.py','run.py'):
                    self.assertTrue(g['violations'](source,path))
            sources=['from .'+module+' import *','import coach02.'+module,'from coach02 import '+module,
                     "import importlib as loader; loader.import_module('coach02."+module+"')",
                     "from importlib import import_module as load; load('coach02."+module+"')"]
            for symbol in g['allowed_contracts']:
                sources.append('from .'+module+' import '+symbol+' as C; alias=C; alias()')
            for operation in g['operations']:
                sources.append('from .'+module+' import '+operation+' as run; alias=run; alias()')
                sources.append('runtime.'+operation+'()')
            for source in sources:
                with self.subTest(module=module,source=source):
                    self.assertTrue(g['violations'](source,'coach02/risk_evidence_assembly_v02.py'))

    def test_103_existing_production_hashes(self):
        root=Path(extension.__file__).resolve().parent.parent
        self.assertEqual(len(PRODUCTION_HASHES),43)
        for path,sha in PRODUCTION_HASHES:
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((root/path).read_bytes()).hexdigest().upper(),sha)

    def test_104_v1_contract_preserved(self):
        from coach02 import risk_evidence_assembly,threat_reachability,threat_state_assembly
        from coach02 import threat_relevance,strategic_coverage,option_exposure,temporal_evidence
        self.pure([(risk_evidence_assembly,'build_risk_evidence'),(threat_reachability,'build_threat_reachability'),
                   (threat_state_assembly,'build_threat_state'),(threat_relevance,'build_threat_relevance'),
                   (strategic_coverage,'build_strategic_coverage'),(option_exposure,'build_option_exposure'),
                   (temporal_evidence,'evaluate_freshness')])
        self.assertEqual(risk_evidence_assembly.RULESET,'risk.evidence_assembly.v1')
        self.assertEqual({f.name for f in fields(risk_evidence_assembly.ThreatRiskEvidence)},
                         {'threat_id','state_assessment','state_use','relevance_assessment','relevance_use'})
        pair=inputs(); old=pair[0]; new=build(pair)
        self.assertEqual(tuple(b.base_bundle for b in new.bundles),old.bundles)
        root=Path(extension.__file__).resolve().parent.parent
        pinned=dict(PRODUCTION_HASHES)
        for name in ('coach02/risk_evidence_assembly.py','coach02/threat_reachability.py'):
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),pinned[name])


PRODUCTION_HASHES = (('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'))
