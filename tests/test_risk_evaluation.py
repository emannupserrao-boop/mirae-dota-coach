"""Synthetic accepted evidence and adversarial conservative-policy checks."""
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

from coach02 import risk_evaluation as policy
from coach02.risk_evaluation import (
    RiskConclusion as Risk, RiskConclusionReason as Reason,
    ThreatContributionStatus as Contribution, ThreatContributionReason as Why,
    ThreatRiskEvaluation, OptionRiskEvaluation, RiskEvaluationSnapshot, evaluate_risk,
)
from coach02.risk_evidence_assembly_v02 import RiskEvidenceSnapshotV2
from coach02.risk_evidence_assembly import EvidenceUseStatus as Use
from coach02.threat_reachability import ThreatReachability as Reach
from coach02.threat_relevance import ThreatRelevance as Rel
from coach02.threat_state_assembly import AssembledThreatState as State
from coach02.option_exposure import OptionExposureState as Exposure
from coach02.strategic_coverage import StrategicCoverageState as Coverage
from test_risk_evidence_assembly_v02 import inputs, build, reach_claim, base_binding


def with_rows(snapshot, rows):
    bundle=snapshot.bundles[0]
    base=replace(bundle.base_bundle,threats=tuple(r.base_threat_evidence for r in rows))
    return replace(snapshot,bundles=(replace(bundle,base_bundle=base,threats=rows),))


def with_base(snapshot, **changes):
    bundle=snapshot.bundles[0]
    return replace(snapshot,bundles=(replace(bundle,base_bundle=replace(bundle.base_bundle,**changes)),))


def evidence(*,state='MISSING',subjects=('A',),relevance=Rel.RELEVANT,reachability=Reach.CAN_AFFECT,
             exposure=Exposure.EXPOSED,coverage=Coverage.SUFFICIENT,
             state_use=Use.CURRENT,relevance_use=Use.CURRENT,reachability_use=Use.CURRENT,
             exposure_use=Use.CURRENT,coverage_use=Use.CURRENT):
    snapshot=build(inputs(state_kind=state,subjects=subjects,relevance=relevance,
        reach_claims=tuple(reach_claim(threat_id=t,reachability=reachability) for t in subjects),
        exposure_rows=(('option-A','EXP-A',exposure),),coverage_rows=(('COV-22',coverage),)))
    bundle=snapshot.bundles[0]; base=bundle.base_bundle
    rows=tuple(replace(r,base_threat_evidence=replace(r.base_threat_evidence,state_use=state_use,
        relevance_use=relevance_use,relevance_assessment=None if relevance_use is Use.ABSENT else r.base_threat_evidence.relevance_assessment),
        reachability_use=reachability_use,reachability_assessment=None if reachability_use is Use.ABSENT else r.reachability_assessment)
        for r in bundle.threats)
    snapshot=with_rows(snapshot,rows)
    return with_base(snapshot,exposure_use=exposure_use,coverage_use=coverage_use,
        exposure_observation=None if exposure_use is Use.ABSENT else base.exposure_observation,
        coverage_observation=None if coverage_use is Use.ABSENT else base.coverage_observation)


def option(**kwargs): return evaluate_risk(evidence(**kwargs)).evaluations[0]


def threat(**kwargs): return option(**kwargs).threat_evaluations[0]


class RiskEvaluationTests(unittest.TestCase):
    def contribution(self,status,reason,**kwargs):
        result=threat(**kwargs)
        self.assertIs(result.contribution,status); self.assertIs(result.reason,reason)

    def conclusion(self,status,reason,**kwargs):
        result=option(**kwargs)
        self.assertIs(result.conclusion,status); self.assertIs(result.reason,reason)

    def imports(self):
        return {'.'*n.level+(n.module or '') for n in ast.walk(ast.parse(inspect.getsource(policy))) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(ast.parse(inspect.getsource(policy))) if isinstance(n,ast.Import) for a in n.names}

    def no_terms(self,*terms):
        tree=ast.parse(inspect.getsource(policy))
        identifiers={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        output={f.name for cls in (ThreatRiskEvaluation,OptionRiskEvaluation,RiskEvaluationSnapshot) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(identifiers|output))

    def pure(self,targets):
        source=evidence(); expected=evaluate_risk(source)
        with ExitStack() as stack:
            for owner,name in targets: stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure dependency')))
            self.assertEqual(evaluate_risk(source).snapshot_id,expected.snapshot_id)

    def guard(self):
        root=Path(policy.__file__).resolve().parent.parent
        tree=ast.parse((root/'tests/test_risk_evidence_assembly_v02.py').read_text(encoding='utf-8'))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_101_dependency_direction')
        nodes=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
            {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or isinstance(n,ast.FunctionDef) and n.name=='violations']
        self.assertEqual(len(nodes),4)
        namespace={'ast':ast};exec(compile(ast.Module(body=nodes,type_ignores=[]),'guard','exec'),namespace)
        return namespace

    def document(self):
        return (Path(policy.__file__).resolve().parent.parent/'RISK_EVALUATION_V01.md').read_text(encoding='utf-8')

    def test_001_exact_risk_domain(self):
        self.assertEqual({v.value for v in Risk},{'SUPPORTED','NOT_ESTABLISHED','INDETERMINATE'})
        self.assertEqual(len(Risk.__members__),3)

    def test_002_no_safety_or_severity_values(self):
        for v in ('SAFE','UNSAFE','LOW_RISK','MEDIUM_RISK','HIGH_RISK','CRITICAL'):
            with self.assertRaises(ValueError): Risk(v)

    def test_003_exact_contribution_domain(self):
        self.assertEqual({v.value for v in Contribution},{'CONTRIBUTING','NON_CONTRIBUTING','INDETERMINATE'})
        self.assertEqual(len(Contribution.__members__),3)

    def test_004_threat_frozen(self):
        with self.assertRaises(FrozenInstanceError): threat().contribution=Contribution.NON_CONTRIBUTING

    def test_005_option_frozen(self):
        with self.assertRaises(FrozenInstanceError): option().conclusion=Risk.NOT_ESTABLISHED

    def test_006_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): evaluate_risk(evidence()).risk_assembly_tick=0

    def test_007_exact_snapshot_and_headers(self):
        source=evidence()
        class Derived(RiskEvidenceSnapshotV2): pass
        for value in (None,{},Derived(**asdict(source))):
            with self.assertRaises(TypeError): evaluate_risk(value)
        for name in ('timeline_id','selected_clock_id','base_risk_evidence_snapshot_id','threat_reachability_snapshot_id'):
            for value in ('',' \t',None,True):
                with self.assertRaises(ValueError): evaluate_risk(replace(source,**{name:value}))
        for value in ([],(None,)):
            with self.assertRaises(TypeError): evaluate_risk(replace(source,bundles=value))

    def test_008_empty_contexts_not_negative_risk(self):
        source=build(inputs(base_bindings=(),reach_claims=()),())
        result=evaluate_risk(source)
        self.assertEqual(result.evaluations,())
        self.assertEqual(result.risk_evidence_snapshot_id,source.snapshot_id)

    def test_009_exactly_one_per_bundle_and_unique_keys(self):
        source=build(inputs(base_bindings=(base_binding(),base_binding(risk_context_id='R2'))))
        result=evaluate_risk(source)
        self.assertEqual([(r.risk_context_id,r.option_id) for r in result.evaluations],[('R','option-A'),('R2','option-A')])
        with self.assertRaises(ValueError): evaluate_risk(replace(source,bundles=source.bundles+source.bundles[:1]))
        with self.assertRaises(TypeError): evaluate_risk(replace(source,bundles=(replace(source.bundles[0],base_bundle=None),)))

    def test_010_fixed_policy_identity(self):
        result=evaluate_risk(evidence())
        self.assertEqual(result.evaluation_policy_id,'risk.evaluation.conservative.v1')
        self.assertEqual(result.evaluations[0].evaluation_policy_id,result.evaluation_policy_id)
        self.assertEqual(tuple(inspect.signature(evaluate_risk).parameters),('snapshot',))

    def test_011_not_established_is_not_safe(self):
        result=option(relevance=Rel.NOT_RELEVANT)
        self.assertIs(result.conclusion,Risk.NOT_ESTABLISHED)
        self.no_terms('safe','safety','safety_state','SAFE')

    def test_012_supported_is_not_unsafe(self):
        self.assertIs(option().conclusion,Risk.SUPPORTED)
        self.no_terms('unsafe','UNSAFE','retreat','fight','stay')

    def test_013_indeterminate_not_danger(self):
        self.assertIs(option(relevance=Rel.UNKNOWN).conclusion,Risk.INDETERMINATE)
        self.no_terms('danger','dangerous','danger_level')

    def test_014_current_not_relevant_first(self):
        self.contribution(Contribution.NON_CONTRIBUTING,Why.NOT_RELEVANT,relevance=Rel.NOT_RELEVANT,reachability=Reach.CANNOT_AFFECT,state_use=Use.HISTORICAL)

    def test_015_current_cannot_affect_before_state(self):
        self.contribution(Contribution.NON_CONTRIBUTING,Why.CANNOT_AFFECT,reachability=Reach.CANNOT_AFFECT,state_use=Use.HISTORICAL,relevance=Rel.UNKNOWN)

    def test_016_not_relevant_absent_or_unknown_reach(self):
        for use in (Use.ABSENT,Use.HISTORICAL,Use.CURRENT):
            self.contribution(Contribution.NON_CONTRIBUTING,Why.NOT_RELEVANT,relevance=Rel.NOT_RELEVANT,reachability=Reach.UNKNOWN,reachability_use=use)

    def test_017_cannot_affect_absent_or_unknown_relevance(self):
        for use in (Use.ABSENT,Use.HISTORICAL,Use.CURRENT):
            self.contribution(Contribution.NON_CONTRIBUTING,Why.CANNOT_AFFECT,relevance=Rel.UNKNOWN,relevance_use=use,reachability=Reach.CANNOT_AFFECT)

    def test_018_state_not_current_precedence(self):
        for use in (Use.HISTORICAL,Use.ABSENT):
            self.contribution(Contribution.INDETERMINATE,Why.STATE_NOT_CURRENT,state_use=use,relevance_use=Use.ABSENT)

    def test_019_relevance_absent_precedence(self):
        self.contribution(Contribution.INDETERMINATE,Why.RELEVANCE_ABSENT,relevance_use=Use.ABSENT,reachability_use=Use.ABSENT)

    def test_020_relevance_historical_not_negative(self):
        for value in Rel:
            self.contribution(Contribution.INDETERMINATE,Why.RELEVANCE_HISTORICAL,relevance=value,relevance_use=Use.HISTORICAL)

    def test_021_relevance_unknown_precedence(self):
        self.contribution(Contribution.INDETERMINATE,Why.RELEVANCE_UNKNOWN,relevance=Rel.UNKNOWN,reachability_use=Use.ABSENT)

    def test_022_reachability_absent(self):
        self.contribution(Contribution.INDETERMINATE,Why.REACHABILITY_ABSENT,reachability_use=Use.ABSENT)

    def test_023_reachability_historical_not_negative(self):
        for value in Reach:
            self.contribution(Contribution.INDETERMINATE,Why.REACHABILITY_HISTORICAL,reachability=value,reachability_use=Use.HISTORICAL)

    def test_024_reachability_unknown(self):
        self.contribution(Contribution.INDETERMINATE,Why.REACHABILITY_UNKNOWN,reachability=Reach.UNKNOWN)

    def test_025_current_positive_contribution(self):
        self.contribution(Contribution.CONTRIBUTING,Why.RELEVANT_AND_CAN_AFFECT)

    def test_026_missing_contributes(self):
        self.assertIs(threat(state='MISSING').contribution,Contribution.CONTRIBUTING)

    def test_027_nearby_contributes(self):
        self.assertIs(threat(state='VISIBLE_NEARBY').contribution,Contribution.CONTRIBUTING)

    def test_028_away_contributes(self):
        self.assertIs(threat(state='VISIBLE_AWAY').contribution,Contribution.CONTRIBUTING)

    def test_029_unknown_state_contributes(self):
        self.assertIs(threat(state='UNKNOWN').contribution,Contribution.CONTRIBUTING)

    def test_030_conflicted_contributes(self):
        self.assertIs(threat(state='CONFLICTED').contribution,Contribution.CONTRIBUTING)

    def test_031_state_category_does_not_define_severity(self):
        values=[option(state=s.value) for s in State]
        self.assertEqual({(r.conclusion,r.reason) for r in values},{(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT)})
        self.assertEqual({r.threat_evaluations[0].base_threat_evidence.base_threat_evidence.state_assessment.state for r in values},set(State))

    def test_032_exposure_absent_blocks_positive(self):
        self.conclusion(Risk.INDETERMINATE,Reason.EXPOSURE_ABSENT,exposure_use=Use.ABSENT)

    def test_033_exposure_historical_blocks_positive(self):
        self.conclusion(Risk.INDETERMINATE,Reason.EXPOSURE_HISTORICAL,exposure_use=Use.HISTORICAL)

    def test_034_exposure_unknown_blocks_positive(self):
        self.conclusion(Risk.INDETERMINATE,Reason.EXPOSURE_UNKNOWN,exposure=Exposure.UNKNOWN)

    def test_035_exposed_contributing_supported(self):
        self.conclusion(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT)

    def test_036_positive_despite_absent_coverage(self):
        self.conclusion(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT,coverage_use=Use.ABSENT)

    def test_037_positive_despite_historical_coverage(self):
        self.conclusion(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT,coverage_use=Use.HISTORICAL)

    def test_038_positive_despite_insufficient_coverage(self):
        self.conclusion(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT,coverage=Coverage.INSUFFICIENT)

    def test_039_positive_despite_unknown_coverage(self):
        self.conclusion(Risk.SUPPORTED,Reason.CURRENT_EXPOSURE_WITH_CONTRIBUTING_THREAT,coverage=Coverage.UNKNOWN)

    def test_040_not_exposed_and_contributing(self):
        self.conclusion(Risk.INDETERMINATE,Reason.NOT_EXPOSED_WITH_CONTRIBUTING_THREAT,exposure=Exposure.NOT_EXPOSED)

    def test_041_indeterminate_threat_before_coverage(self):
        self.conclusion(Risk.INDETERMINATE,Reason.THREAT_EVIDENCE_INDETERMINATE,relevance=Rel.UNKNOWN,coverage_use=Use.ABSENT)

    def test_042_zero_threats_never_imply_no_risk(self):
        self.conclusion(Risk.INDETERMINATE,Reason.COVERAGE_ABSENT,subjects=(),coverage_use=Use.ABSENT)
        self.assertEqual(option(subjects=()).threat_evaluations,())

    def test_043_negative_absent_coverage(self):
        self.conclusion(Risk.INDETERMINATE,Reason.COVERAGE_ABSENT,relevance=Rel.NOT_RELEVANT,coverage_use=Use.ABSENT)

    def test_044_negative_historical_coverage(self):
        self.conclusion(Risk.INDETERMINATE,Reason.COVERAGE_HISTORICAL,relevance=Rel.NOT_RELEVANT,coverage_use=Use.HISTORICAL)

    def test_045_negative_insufficient_coverage(self):
        self.conclusion(Risk.INDETERMINATE,Reason.COVERAGE_INSUFFICIENT,reachability=Reach.CANNOT_AFFECT,coverage=Coverage.INSUFFICIENT)

    def test_046_negative_unknown_coverage(self):
        self.conclusion(Risk.INDETERMINATE,Reason.COVERAGE_UNKNOWN,reachability=Reach.CANNOT_AFFECT,coverage=Coverage.UNKNOWN)

    def test_047_negative_requires_current_sufficient(self):
        self.conclusion(Risk.NOT_ESTABLISHED,Reason.SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT,relevance=Rel.NOT_RELEVANT)

    def test_048_empty_threats_sufficient(self):
        for exposure in (Exposure.EXPOSED,Exposure.NOT_EXPOSED):
            self.conclusion(Risk.NOT_ESTABLISHED,Reason.SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT,subjects=(),exposure=exposure)

    def test_049_exposed_but_cannot_affect(self):
        self.conclusion(Risk.NOT_ESTABLISHED,Reason.SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT,reachability=Reach.CANNOT_AFFECT)

    def test_050_not_exposed_no_contributors(self):
        self.conclusion(Risk.NOT_ESTABLISHED,Reason.SUFFICIENT_COVERAGE_NO_CONTRIBUTING_THREAT,exposure=Exposure.NOT_EXPOSED,relevance=Rel.NOT_RELEVANT)

    def test_051_unknown_and_absent_are_distinct(self):
        a,b=option(relevance=Rel.UNKNOWN),option(relevance_use=Use.ABSENT)
        self.assertIs(a.conclusion,b.conclusion)
        self.assertNotEqual(a.threat_evaluations[0].reason,b.threat_evaluations[0].reason)
        self.assertIsNotNone(a.threat_evaluations[0].base_threat_evidence.base_threat_evidence.relevance_assessment)
        self.assertIsNone(b.threat_evaluations[0].base_threat_evidence.base_threat_evidence.relevance_assessment)

    def test_052_absent_none_pairing_required(self):
        source=evidence(); b=source.bundles[0]; row=b.threats[0]; base=row.base_threat_evidence
        for axis in ('coverage','exposure'):
            with self.assertRaises(ValueError): evaluate_risk(with_base(source,**{axis+'_use':Use.ABSENT}))
            with self.assertRaises(TypeError): evaluate_risk(with_base(source,**{axis+'_observation':None}))
        with self.assertRaises(ValueError): evaluate_risk(with_rows(source,(replace(row,reachability_use=Use.ABSENT),)))
        with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,reachability_assessment=None),)))
        with self.assertRaises(ValueError): evaluate_risk(with_rows(source,(replace(row,base_threat_evidence=replace(base,relevance_use=Use.ABSENT)),)))
        with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,base_threat_evidence=replace(base,relevance_assessment=None)),)))

    def test_053_one_positive_over_indeterminate(self):
        source=evidence(subjects=('A','B')); a,b=source.bundles[0].threats
        b=replace(b,reachability_assessment=replace(b.reachability_assessment,reachability=Reach.UNKNOWN))
        result=evaluate_risk(with_rows(source,(a,b))).evaluations[0]
        self.assertIs(result.conclusion,Risk.SUPPORTED)
        self.assertEqual([r.contribution for r in result.threat_evaluations],[Contribution.CONTRIBUTING,Contribution.INDETERMINATE])

    def test_054_many_positive_same_category(self):
        one,many=option(),option(subjects=('A','B','C','D','E'))
        self.assertEqual((one.conclusion,one.reason),(many.conclusion,many.reason))
        self.assertEqual(len(many.threat_evaluations),5)

    def test_055_five_negative_one_positive_no_scoring(self):
        source=evidence(subjects=('A','B','C','D','E','F')); rows=source.bundles[0].threats
        mixed=tuple(replace(r,reachability_assessment=replace(r.reachability_assessment,reachability=Reach.CANNOT_AFFECT)) for r in rows[:-1])+(rows[-1],)
        result=evaluate_risk(with_rows(source,mixed)).evaluations[0]
        self.assertIs(result.conclusion,Risk.SUPPORTED)
        self.assertEqual([r.contribution for r in result.threat_evaluations],[Contribution.NON_CONTRIBUTING]*5+[Contribution.CONTRIBUTING])

    def test_056_not_relevant_preserved(self):
        r=threat(relevance=Rel.NOT_RELEVANT)
        self.assertIs(r.base_threat_evidence.base_threat_evidence.relevance_assessment.relevance,Rel.NOT_RELEVANT)

    def test_057_cannot_affect_preserved(self):
        r=threat(reachability=Reach.CANNOT_AFFECT)
        self.assertIs(r.base_threat_evidence.reachability_assessment.reachability,Reach.CANNOT_AFFECT)

    def test_058_historical_evidence_preserved(self):
        r=threat(reachability_use=Use.HISTORICAL)
        self.assertIs(r.base_threat_evidence.reachability_use,Use.HISTORICAL)
        self.assertIs(r.base_threat_evidence.reachability_assessment.reachability,Reach.CAN_AFFECT)

    def test_059_conflicted_provenance_preserved(self):
        r=threat(state='CONFLICTED'); state=r.base_threat_evidence.base_threat_evidence.state_assessment
        self.assertIs(state.state,State.CONFLICTED)
        self.assertIsNotNone(state.positive_observation);self.assertIsNotNone(state.missing_resolution)

    def test_060_complete_base_threat_object_identity(self):
        source=evidence(); r=evaluate_risk(source).evaluations[0].threat_evaluations[0]
        self.assertIs(r.base_threat_evidence,source.bundles[0].threats[0])

    def test_061_complete_base_bundle_identity(self):
        source=evidence(); r=evaluate_risk(source).evaluations[0]
        self.assertIs(r.base_bundle,source.bundles[0])
        self.assertIs(r.base_bundle.base_bundle,source.bundles[0].base_bundle)

    def test_062_no_upstream_mutation(self):
        source=evidence(); before=asdict(source),source.snapshot_id
        evaluate_risk(source)
        self.assertEqual((asdict(source),source.snapshot_id),before)

    def test_063_exact_threat_rows_and_unique_ids(self):
        source=evidence(); b=source.bundles[0]; r=b.threats[0]
        self.assertEqual(len(evaluate_risk(source).evaluations[0].threat_evaluations),len(b.threats))
        for rows in ([],(None,)):
            with self.assertRaises(TypeError): evaluate_risk(replace(source,bundles=(replace(b,threats=rows),)))
        with self.assertRaises(ValueError): evaluate_risk(with_rows(source,(r,r)))
        with self.assertRaises(ValueError): evaluate_risk(replace(source,bundles=(replace(b,threats=()),)))
        with self.assertRaises(TypeError): evaluate_risk(replace(source,bundles=(replace(b,threats=(replace(r,base_threat_evidence=None),)),)))
        with self.assertRaises(ValueError): evaluate_risk(with_rows(source,(replace(r,base_threat_evidence=replace(r.base_threat_evidence,threat_id='other')),)))

    def test_064_no_option_filtering(self):
        source=build(inputs(base_bindings=(base_binding(),base_binding(option_id='B'))))
        result=evaluate_risk(source)
        self.assertEqual(len(result.evaluations),2)
        self.assertEqual({r.option_id for r in result.evaluations},{'B','option-A'})
        self.assertEqual({r.conclusion for r in result.evaluations},{Risk.SUPPORTED,Risk.INDETERMINATE})

    def test_065_no_options_created(self):
        source=evidence(); result=evaluate_risk(source)
        self.assertEqual({(r.risk_context_id,r.option_id) for r in result.evaluations},
            {(b.base_bundle.risk_context_id,b.base_bundle.option_id) for b in source.bundles})

    def test_066_no_ranking_by_conclusion(self):
        source=build(inputs(base_bindings=(base_binding(),base_binding(option_id='B'))))
        result=evaluate_risk(source)
        self.assertEqual([r.option_id for r in result.evaluations],[b.base_bundle.option_id for b in source.bundles])
        self.assertEqual([r.conclusion for r in result.evaluations],[Risk.INDETERMINATE,Risk.SUPPORTED])
        self.no_terms('rank','best_option','preferred','sort_by_risk')

    def test_067_canonical_order(self):
        source=evidence(subjects=('C','A','B')); result=evaluate_risk(source)
        self.assertEqual([r.threat_id for r in result.evaluations[0].threat_evaluations],['A','B','C'])
        self.assertEqual(result,evaluate_risk(evidence(subjects=('B','C','A'))))

    def test_068_canonical_json_identity(self):
        source=replace(evidence(),timeline_id=' opaque/\u03b1 ')
        result=evaluate_risk(source)
        encoded=json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'risk.evaluation.v1:snapshot:'+hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result.snapshot_id,evaluate_risk(source).snapshot_id)

    def test_069_evidence_and_header_identity(self):
        source=evidence(); original=evaluate_risk(source)
        for name in ('timeline_id','selected_clock_id','base_risk_evidence_snapshot_id','threat_reachability_snapshot_id'):
            self.assertNotEqual(original.snapshot_id,evaluate_risk(replace(source,**{name:'changed'})).snapshot_id)
        for name in ('coverage_observation','exposure_observation'):
            b=source.bundles[0].base_bundle
            altered=with_base(source,**{name:replace(getattr(b,name),source_id='other-source')})
            self.assertNotEqual(original.snapshot_id,evaluate_risk(altered).snapshot_id)

    def test_070_contribution_participates_in_identity(self):
        s=evaluate_risk(evidence()); o=s.evaluations[0]; t=o.threat_evaluations[0]
        changed=replace(s,evaluations=(replace(o,threat_evaluations=(replace(t,contribution=Contribution.INDETERMINATE),)),))
        self.assertNotEqual(s.snapshot_id,changed.snapshot_id)

    def test_071_all_reasons_participate_in_identity(self):
        s=evaluate_risk(evidence()); o=s.evaluations[0]; t=o.threat_evaluations[0]
        for altered in (replace(o,reason=Reason.THREAT_EVIDENCE_INDETERMINATE),
                        replace(o,threat_evaluations=(replace(t,reason=Why.REACHABILITY_UNKNOWN),))):
            self.assertNotEqual(s.snapshot_id,replace(s,evaluations=(altered,)).snapshot_id)

    def test_072_conclusion_participates_in_identity(self):
        s=evaluate_risk(evidence()); o=s.evaluations[0]
        self.assertNotEqual(s.snapshot_id,replace(s,evaluations=(replace(o,conclusion=Risk.INDETERMINATE),)).snapshot_id)

    def test_073_policy_participates_in_identity(self):
        s=evaluate_risk(evidence()); o=s.evaluations[0]
        self.assertNotEqual(s.snapshot_id,replace(s,evaluation_policy_id='future-policy').snapshot_id)
        self.assertNotEqual(s.snapshot_id,replace(s,evaluations=(replace(o,evaluation_policy_id='future-policy'),)).snapshot_id)

    def test_074_concrete_risk_tick_and_consistent_header(self):
        source=evidence()
        for tick in (True,1.0,'110',None):
            with self.assertRaises(TypeError): evaluate_risk(replace(source,risk_assembly_tick=tick))
            with self.assertRaises(TypeError): evaluate_risk(with_base(source,risk_assembly_tick=tick))
        with self.assertRaises(ValueError): evaluate_risk(with_base(source,risk_assembly_tick=111))
        changed=replace(with_base(source,risk_assembly_tick=-7),risk_assembly_tick=-7)
        result=evaluate_risk(changed)
        self.assertEqual(result.risk_assembly_tick,-7);self.assertEqual(result.evaluations[0].risk_assembly_tick,-7)

    def test_075_currentness_not_recomputed(self):
        source=evidence(state_use=Use.HISTORICAL,reachability_use=Use.HISTORICAL)
        result=evaluate_risk(source)
        self.assertEqual(result.selected_clock_id,source.selected_clock_id)
        self.assertEqual(result.risk_assembly_tick,source.risk_assembly_tick)
        self.assertIs(result.evaluations[0].threat_evaluations[0].reason,Why.STATE_NOT_CURRENT)

    def test_076_no_risk_score(self): self.no_terms('score','risk_score','sum','round')
    def test_077_no_probability(self): self.no_terms('probability','likelihood')
    def test_078_no_confidence_number(self): self.no_terms('confidence','confidence_score','float')
    def test_079_no_severity_weighting(self): self.no_terms('severity','magnitude','weight','weights')
    def test_080_no_damage_model(self): self.no_terms('damage','disable','disable_duration')
    def test_081_no_capability_model(self): self.no_terms('capability','mobility','speed','cooldown','eta')
    def test_082_no_player_resources(self): self.no_terms('health','hp','mana','player','survivability')
    def test_083_no_item_logic(self): self.no_terms('item','items','inventory','hero','power_spike')
    def test_084_no_reward_logic(self): self.no_terms('reward','reward_value','net_worth','farm_value','objective_value')
    def test_085_no_opportunity_cost(self): self.no_terms('opportunity_cost','commitment','escape_resources')
    def test_086_no_safety_import(self): self.assertNotIn('.safety_evidence',self.imports())
    def test_087_no_option_safety_import(self): self.assertNotIn('.option_safety',self.imports())
    def test_088_no_decision_import(self): self.assertNotIn('.decision',self.imports())
    def test_089_no_farm_imports(self): self.assertTrue({'.farm_context','.farm_cycle'}.isdisjoint(self.imports()))

    def test_090_only_v2_contract_imports(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.risk_evidence_assembly_v02'})
        node=next(n for n in ast.parse(inspect.getsource(policy)).body if isinstance(n,ast.ImportFrom) and n.level==1)
        self.assertEqual({n.name for n in node.names},{'RiskEvidenceSnapshotV2','OptionRiskEvidenceBundleV2','ThreatRiskEvidenceV2','EvidenceUseStatus'})
        self.assertTrue(all(n.asname is None for n in node.names))

    def test_091_no_wall_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_092_no_io(self):
        import builtins,io,os,subprocess,sqlite3
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(subprocess,'Popen'),(sqlite3,'connect')])

    def test_093_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_094_no_environment(self):
        import os
        class Forbidden(dict):
            def __getitem__(self,key): raise AssertionError('environment read')
            def get(self,*args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        with patch.object(os,'environ',Forbidden()): self.pure([(os,'getenv')])

    def test_095_no_random_uuid(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])

    def test_096_no_mutable_global_state(self):
        before=dict(vars(policy));option();option(relevance=Rel.UNKNOWN)
        self.assertEqual(before,vars(policy))
        for name,value in vars(policy).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(ast.parse(inspect.getsource(policy)))))

    def test_097_legacy_safety_review(self):
        from coach02.safety_evidence import ThreatState, RelevantThreatObservation, RiskAwarenessEvidence
        from coach02.option_safety import Exposure as LegacyExposure, OptionSafetyEvidence
        self.assertNotIn('CONFLICTED',{s.value for s in ThreatState})
        self.assertEqual({f.name for f in fields(RelevantThreatObservation)},{'threat_id','state','freshness'})
        self.assertEqual({v.value for v in LegacyExposure},{'LOW','HIGH','UNKNOWN'})
        self.assertNotIn('base_bundle',{f.name for f in fields(RiskAwarenessEvidence)})
        self.assertIn('action',{f.name for f in fields(OptionSafetyEvidence)})
        self.assertIn('NO_DIRECT_PRODUCTION_COMPATIBILITY_V01',self.document())

    def test_098_no_adapter_or_action_authority(self):
        self.assertEqual({n for n,v in vars(policy).items() if inspect.isfunction(v) and v.__module__==policy.__name__ and not n.startswith('_')},{'evaluate_risk'})
        self.no_terms('action','recommendation','speech','priority','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS','adapter')

    def test_099_handoff_and_limits_documented(self):
        doc=self.document()
        for text in ('BLOCKER_BEFORE_RISK_SEVERITY','BLOCKER_BEFORE_SAFETY_V02','BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION',
                     'SUPPORTED does not mean UNSAFE.','NOT_ESTABLISHED does not mean SAFE.',
                     'INDETERMINATE is not a danger level.','Positive evidence and negative evidence are intentionally asymmetric.',
                     'Coverage incompleteness does not erase known positive risk.',
                     'Negative risk conclusions require CURRENT SUFFICIENT coverage.',
                     'Risk Evaluation v0.1 does not rank options.','Risk Evaluation v0.1 does not issue actions.',
                     'Threat State semantic category does not define severity.',
                     'Risk Evaluation consumes accepted Risk Evidence v0.2 without recomputing it.'):
            self.assertIn(text,doc)

    def test_100_dependency_direction(self):
        guard=self.guard()
        self.assertEqual(guard['authorized_consumers'],{'coach02/risk_evaluation.py'})
        self.assertEqual(guard['allowed_contracts'],{'RiskEvidenceSnapshotV2','OptionRiskEvidenceBundleV2','ThreatRiskEvidenceV2','EvidenceUseStatus'})
        self.assertEqual(guard['violations'](inspect.getsource(policy),'coach02/risk_evaluation.py'),[])
        root=Path(policy.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/option_safety_v02.py'})
        allowed_contracts = frozenset(('RiskEvaluationSnapshot', 'OptionRiskEvaluation', 'RiskConclusion'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure', 'build_risk_evidence', 'build_risk_evidence_v2', 'evaluate_risk', 'build_threat_reachability'))

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
                        if 'risk_evaluation' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('risk_evaluation' in (node.module or '').split('.') or
                               any(a.name == 'risk_evaluation' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'risk_evaluation') or
                                        (node.level == 0 and node.module == 'coach02.risk_evaluation'))
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
                                       and 'risk_evaluation' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .risk_evaluation import ' + symbol
            self.assertEqual(violations(source, 'coach02/option_safety_v02.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .risk_evaluation import *', 'import coach02.risk_evaluation',
                    'from coach02 import risk_evaluation', "__import__('coach02.risk_evaluation')"]
        for symbol in allowed_contracts:
            rejected.append('from .risk_evaluation import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .risk_evaluation import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/option_safety_v02.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/risk_evaluation.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_101_arbitrary_consumers_rejected(self):
        guard=self.guard()
        for symbol in guard['allowed_contracts']:
            source='from .risk_evidence_assembly_v02 import '+symbol
            for path in ('coach02/arbitrary.py','coach02/service.py','coach02/decision.py','run.py'):
                self.assertTrue(guard['violations'](source,path))

    def test_102_builder_constructors_aliases_dynamic_rejected(self):
        guard=self.guard(); consumer='coach02/risk_evaluation.py'
        rejected=['from .risk_evidence_assembly_v02 import build_risk_evidence_v2',
            'from .risk_evidence_assembly_v02 import *','import coach02.risk_evidence_assembly_v02',
            'from coach02 import risk_evidence_assembly_v02',
            "import importlib as loader; loader.import_module('coach02.risk_evidence_assembly_v02')",
            "from importlib import import_module as load; load('coach02.risk_evidence_assembly_v02')",
            "__import__('coach02.risk_evidence_assembly_v02')",'runtime.build_risk_evidence_v2()']
        for name in guard['allowed_contracts']:
            rejected.extend(['from .risk_evidence_assembly_v02 import '+name+' as C',
                'from .risk_evidence_assembly_v02 import '+name+'; alias='+name+'; alias()'])
        for source in rejected:
            with self.subTest(source=source): self.assertTrue(guard['violations'](source,consumer))

    def test_103_existing_production_hashes(self):
        root=Path(policy.__file__).resolve().parent.parent
        self.assertEqual(len(PRODUCTION_HASHES),44)
        for name,sha in PRODUCTION_HASHES:
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),sha)

    def test_104_v2_authoritative_concrete_contracts(self):
        from coach02 import risk_evidence_assembly_v02,risk_evidence_assembly,threat_reachability
        from coach02 import threat_state_assembly,threat_relevance,strategic_coverage,option_exposure,temporal_evidence
        self.pure([(risk_evidence_assembly_v02,'build_risk_evidence_v2'),(risk_evidence_assembly,'build_risk_evidence'),
            (threat_reachability,'build_threat_reachability'),(threat_state_assembly,'build_threat_state'),
            (threat_relevance,'build_threat_relevance'),(strategic_coverage,'build_strategic_coverage'),
            (option_exposure,'build_option_exposure'),(temporal_evidence,'evaluate_freshness')])
        source=evidence(); b=source.bundles[0]; row=b.threats[0]; base=row.base_threat_evidence
        class Pretend(str,Enum): CURRENT='CURRENT'; RELEVANT='RELEVANT'; CAN_AFFECT='CAN_AFFECT'; MISSING='MISSING'; SUFFICIENT='SUFFICIENT'; EXPOSED='EXPOSED'
        for invalid in ('CURRENT',Pretend.CURRENT,None):
            for name in ('coverage_use','exposure_use'):
                with self.assertRaises(TypeError): evaluate_risk(with_base(source,**{name:invalid}))
            for name in ('state_use','relevance_use'):
                with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,base_threat_evidence=replace(base,**{name:invalid})),)))
            with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,reachability_use=invalid),)))
        for name,semantic,value in (('coverage_observation','coverage',Pretend.SUFFICIENT),('exposure_observation','exposure',Pretend.EXPOSED)):
            for invalid in (value,value.value):
                with self.assertRaises(TypeError): evaluate_risk(with_base(source,**{name:replace(getattr(b.base_bundle,name),**{semantic:invalid})}))
        for invalid in (Pretend.RELEVANT,'RELEVANT'):
            with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,base_threat_evidence=replace(base,relevance_assessment=replace(base.relevance_assessment,relevance=invalid))),)))
        for invalid in (Pretend.CAN_AFFECT,'CAN_AFFECT'):
            with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,reachability_assessment=replace(row.reachability_assessment,reachability=invalid)),)))
        for invalid in (Pretend.MISSING,'MISSING'):
            with self.assertRaises(TypeError): evaluate_risk(with_rows(source,(replace(row,base_threat_evidence=replace(base,state_assessment=replace(base.state_assessment,state=invalid))),)))


PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
