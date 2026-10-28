"""Synthetic risk inputs; explicit tolerance and epistemic boundary checks."""
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

from coach02 import option_safety_v02 as gate
from coach02.option_safety_v02 import (
    OptionSafetyGateStatus as Status, SupportedRiskTolerance as Tolerance,
    OptionSafetyGateReason as Reason, OptionSafetyPolicyClaim,
    OptionSafetyEvaluationV2, OptionSafetySnapshotV2, evaluate_option_safety_v2,
)
from coach02.risk_evaluation import (
    RiskEvaluationSnapshot, OptionRiskEvaluation, RiskConclusion as Risk, evaluate_risk,
)
from coach02.threat_relevance import ThreatRelevance as Rel
from coach02.option_exposure import OptionExposureState as Exposure
from test_risk_evaluation import evidence
from test_risk_evidence_assembly_v02 import inputs, build, base_binding, reach_claim


def risk_snapshot(conclusion=Risk.SUPPORTED):
    relevance={Risk.SUPPORTED:Rel.RELEVANT,Risk.NOT_ESTABLISHED:Rel.NOT_RELEVANT,Risk.INDETERMINATE:Rel.UNKNOWN}[conclusion]
    return evaluate_risk(evidence(relevance=relevance))


def claim(tolerance=Tolerance.NOT_TOLERATED,**changes):
    return replace(OptionSafetyPolicyClaim('R','option-A','safety-context',tolerance,'caller-policy-v1'),**changes)


def evaluate(conclusion=Risk.SUPPORTED,tolerance=Tolerance.NOT_TOLERATED):
    return evaluate_option_safety_v2(risk_snapshot(conclusion),() if tolerance is None else (claim(tolerance),))


def multiple():
    return evaluate_risk(build(inputs(base_bindings=(base_binding(),base_binding(option_id='option-B')),
        exposure_rows=(('option-A','EXP-A',Exposure.EXPOSED),('option-B','EXP-A',Exposure.EXPOSED)),
        reach_claims=(reach_claim(),reach_claim(option_id='option-B')))))


class OptionSafetyV2Tests(unittest.TestCase):
    def outcome(self,risk,tolerance,status,reason):
        result=evaluate(risk,tolerance).evaluations[0]
        self.assertIs(result.gate_status,status);self.assertIs(result.reason,reason)

    def blank(self,name):
        class Derived(str): pass
        for value in ('',' \t\n',None,True,1,Derived('valid')):
            with self.subTest(value=value),self.assertRaises(ValueError): claim(**{name:value})

    def imports(self):
        tree=ast.parse(inspect.getsource(gate))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def no_terms(self,*terms):
        tree=ast.parse(inspect.getsource(gate))
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        output={f.name for cls in (OptionSafetyPolicyClaim,OptionSafetyEvaluationV2,OptionSafetySnapshotV2) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(names|output))

    def pure(self,targets):
        source=risk_snapshot();claims=(claim(),);expected=evaluate_option_safety_v2(source,claims)
        with ExitStack() as stack:
            for owner,name in targets: stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure dependency')))
            self.assertEqual(evaluate_option_safety_v2(source,claims).snapshot_id,expected.snapshot_id)

    def guard(self):
        root=Path(gate.__file__).resolve().parent.parent
        tree=ast.parse((root/'tests/test_risk_evaluation.py').read_text(encoding='utf-8'))
        fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='test_100_dependency_direction')
        nodes=[n for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in
            {'authorized_consumers','allowed_contracts','operations'} for t in n.targets) or isinstance(n,ast.FunctionDef) and n.name=='violations']
        self.assertEqual(len(nodes),4)
        namespace={'ast':ast};exec(compile(ast.Module(body=nodes,type_ignores=[]),'guard','exec'),namespace)
        return namespace

    def document(self):
        return (Path(gate.__file__).resolve().parent.parent/'OPTION_SAFETY_V02.md').read_text(encoding='utf-8')

    def test_001_exact_gate_domain(self):
        self.assertEqual({s.value for s in Status},{'RISK_BLOCKING','RISK_NOT_BLOCKING','INDETERMINATE'})
        self.assertEqual(len(Status.__members__),3)

    def test_002_no_safe_unsafe_domain(self):
        for value in ('SAFE','UNSAFE','DANGEROUS','GO','STOP'):
            with self.assertRaises(ValueError): Status(value)

    def test_003_exact_tolerance_domain(self):
        self.assertEqual({t.value for t in Tolerance},{'TOLERATED','NOT_TOLERATED','UNKNOWN'})
        self.assertEqual(len(Tolerance.__members__),3)

    def test_004_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().supported_risk_tolerance=Tolerance.TOLERATED

    def test_005_evaluation_frozen(self):
        with self.assertRaises(FrozenInstanceError): evaluate().evaluations[0].gate_status=Status.RISK_NOT_BLOCKING

    def test_006_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): evaluate().risk_assembly_tick=0

    def test_007_risk_context_exact_nonblank(self): self.blank('risk_context_id')
    def test_008_option_exact_nonblank(self): self.blank('option_id')
    def test_009_safety_context_exact_nonblank(self): self.blank('safety_context_id')
    def test_010_policy_exact_nonblank(self): self.blank('safety_policy_id')

    def test_011_concrete_tolerance_enum(self):
        class Other(str,Enum): TOLERATED='TOLERATED'
        for value in ('TOLERATED',Other.TOLERATED,None,True):
            with self.assertRaises(TypeError): claim(value)

    def test_012_exact_claim_tuple_and_type(self):
        source=risk_snapshot()
        class Derived(OptionSafetyPolicyClaim): pass
        for claims in ([],[claim()],None,(None,),(Derived(**asdict(claim())),)):
            with self.assertRaises(TypeError): evaluate_option_safety_v2(source,claims)

    def test_013_duplicate_pair_even_different_policy(self):
        source=risk_snapshot()
        for second in (claim(),claim(Tolerance.TOLERATED,safety_context_id='other',safety_policy_id='other-policy')):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(source,(claim(),second))

    def test_014_same_option_different_risk_contexts(self):
        source=evaluate_risk(build(inputs(base_bindings=(base_binding(),base_binding(risk_context_id='R2')))))
        result=evaluate_option_safety_v2(source,(claim(),claim(Tolerance.TOLERATED,risk_context_id='R2')))
        self.assertEqual([(r.risk_context_id,r.option_id,r.gate_status) for r in result.evaluations],
            [('R','option-A',Status.RISK_BLOCKING),('R2','option-A',Status.RISK_NOT_BLOCKING)])

    def test_015_exact_snapshot_rows_and_conclusions(self):
        source=risk_snapshot();row=source.evaluations[0]
        class Derived(RiskEvaluationSnapshot): pass
        class DerivedRow(OptionRiskEvaluation): pass
        class Other(str,Enum): SUPPORTED='SUPPORTED'
        for value in (None,{},Derived(**asdict(source))):
            with self.assertRaises(TypeError): evaluate_option_safety_v2(value,())
        for rows in ([],[row],(None,),(DerivedRow(**asdict(row)),)):
            with self.assertRaises(TypeError): evaluate_option_safety_v2(replace(source,evaluations=rows),())
        for value in ('SUPPORTED',Other.SUPPORTED,None):
            with self.assertRaises(TypeError): evaluate_option_safety_v2(replace(source,evaluations=(replace(row,conclusion=value),)),())
        with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,evaluations=(row,row)),())

    def test_016_foreign_claim_rejected(self):
        for item in (claim(option_id='foreign'),claim(risk_context_id='foreign')):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(risk_snapshot(),(item,))

    def test_017_subset_claims(self):
        result=evaluate_option_safety_v2(multiple(),(claim(),))
        self.assertEqual([r.gate_status for r in result.evaluations],[Status.RISK_BLOCKING,Status.INDETERMINATE])
        self.assertIsNone(result.evaluations[1].safety_policy_claim)

    def test_018_absent_policy_is_not_unknown_claim(self):
        absent,unknown=evaluate(tolerance=None),evaluate(tolerance=Tolerance.UNKNOWN)
        self.assertIs(absent.evaluations[0].gate_status,unknown.evaluations[0].gate_status)
        self.assertNotEqual(absent.evaluations[0].reason,unknown.evaluations[0].reason)
        self.assertIsNone(absent.evaluations[0].safety_context_id)
        self.assertIsNone(absent.evaluations[0].safety_policy_claim)
        self.assertIsNotNone(unknown.evaluations[0].safety_policy_claim)
        self.assertNotEqual(absent.snapshot_id,unknown.snapshot_id)

    def test_019_supported_not_tolerated(self): self.outcome(Risk.SUPPORTED,Tolerance.NOT_TOLERATED,Status.RISK_BLOCKING,Reason.SUPPORTED_RISK_NOT_TOLERATED)
    def test_020_supported_tolerated(self): self.outcome(Risk.SUPPORTED,Tolerance.TOLERATED,Status.RISK_NOT_BLOCKING,Reason.SUPPORTED_RISK_TOLERATED)
    def test_021_supported_unknown_policy(self): self.outcome(Risk.SUPPORTED,Tolerance.UNKNOWN,Status.INDETERMINATE,Reason.SUPPORTED_RISK_POLICY_UNKNOWN)
    def test_022_supported_absent_policy(self): self.outcome(Risk.SUPPORTED,None,Status.INDETERMINATE,Reason.SUPPORTED_RISK_POLICY_ABSENT)
    def test_023_not_established_absent(self): self.outcome(Risk.NOT_ESTABLISHED,None,Status.RISK_NOT_BLOCKING,Reason.RISK_NOT_ESTABLISHED)
    def test_024_not_established_not_tolerated(self): self.outcome(Risk.NOT_ESTABLISHED,Tolerance.NOT_TOLERATED,Status.RISK_NOT_BLOCKING,Reason.RISK_NOT_ESTABLISHED)
    def test_025_not_established_tolerated(self): self.outcome(Risk.NOT_ESTABLISHED,Tolerance.TOLERATED,Status.RISK_NOT_BLOCKING,Reason.RISK_NOT_ESTABLISHED)
    def test_026_not_established_unknown(self): self.outcome(Risk.NOT_ESTABLISHED,Tolerance.UNKNOWN,Status.RISK_NOT_BLOCKING,Reason.RISK_NOT_ESTABLISHED)
    def test_027_indeterminate_absent(self): self.outcome(Risk.INDETERMINATE,None,Status.INDETERMINATE,Reason.RISK_INDETERMINATE)
    def test_028_indeterminate_tolerated(self): self.outcome(Risk.INDETERMINATE,Tolerance.TOLERATED,Status.INDETERMINATE,Reason.RISK_INDETERMINATE)
    def test_029_indeterminate_not_tolerated(self): self.outcome(Risk.INDETERMINATE,Tolerance.NOT_TOLERATED,Status.INDETERMINATE,Reason.RISK_INDETERMINATE)
    def test_030_indeterminate_unknown(self): self.outcome(Risk.INDETERMINATE,Tolerance.UNKNOWN,Status.INDETERMINATE,Reason.RISK_INDETERMINATE)

    def test_031_unused_claims_preserved_without_outcome_effect(self):
        for risk in (Risk.NOT_ESTABLISHED,Risk.INDETERMINATE):
            source=risk_snapshot(risk);reference=evaluate_option_safety_v2(source,()).evaluations[0]
            for tolerance in Tolerance:
                item=claim(tolerance);result=evaluate_option_safety_v2(source,(item,)).evaluations[0]
                self.assertEqual((result.gate_status,result.reason),(reference.gate_status,reference.reason))
                self.assertIs(result.safety_policy_claim,item)

    def test_032_blocking_not_unsafe(self):
        result=evaluate().evaluations[0]
        self.assertIs(result.gate_status,Status.RISK_BLOCKING)
        self.assertIs(result.base_risk_evaluation.conclusion,Risk.SUPPORTED)
        self.no_terms('UNSAFE','unsafe','safety_verdict')

    def test_033_not_blocking_not_safe(self):
        result=evaluate(tolerance=Tolerance.TOLERATED).evaluations[0]
        self.assertIs(result.gate_status,Status.RISK_NOT_BLOCKING)
        self.assertIs(result.base_risk_evaluation.conclusion,Risk.SUPPORTED)
        self.no_terms('SAFE','safe','globally_safe')

    def test_034_not_blocking_not_recommended(self):
        self.no_terms('RECOMMENDED','recommended','should_take_option','choose_option')
        self.assertEqual({f.name for f in fields(OptionSafetyEvaluationV2)},
            {'risk_context_id','option_id','safety_context_id','gate_status','reason','gate_policy_id','safety_policy_claim','base_risk_evaluation'})

    def test_035_indeterminate_not_danger(self):
        self.no_terms('DANGEROUS','DANGER','danger','danger_level')
        self.assertIs(evaluate(Risk.INDETERMINATE,Tolerance.TOLERATED).evaluations[0].gate_status,Status.INDETERMINATE)

    def test_036_blocking_not_retreat(self):
        self.no_terms('RETREAT','retreat','leave','stop','GO','STOP')
        self.assertEqual({r.value for r in Reason},{'SUPPORTED_RISK_NOT_TOLERATED','SUPPORTED_RISK_TOLERATED',
            'SUPPORTED_RISK_POLICY_UNKNOWN','SUPPORTED_RISK_POLICY_ABSENT','RISK_NOT_ESTABLISHED','RISK_INDETERMINATE'})

    def test_037_one_output_per_input(self):
        source=multiple();result=evaluate_option_safety_v2(source,())
        self.assertEqual([(r.risk_context_id,r.option_id) for r in result.evaluations],[(r.risk_context_id,r.option_id) for r in source.evaluations])

    def test_038_no_blocking_filter(self):
        source=multiple();result=evaluate_option_safety_v2(source,(claim(),claim(option_id='option-B')))
        self.assertEqual(len(result.evaluations),2)
        self.assertTrue(all(r.gate_status is Status.RISK_BLOCKING for r in result.evaluations))

    def test_039_no_indeterminate_filter_or_option_creation(self):
        source=multiple();result=evaluate_option_safety_v2(source,())
        self.assertEqual({r.option_id for r in result.evaluations},{'option-A','option-B'})
        self.assertTrue(all(r.gate_status is Status.INDETERMINATE for r in result.evaluations))

    def test_040_empty_input_empty_result(self):
        source=evaluate_risk(build(inputs(base_bindings=(),reach_claims=()),()))
        result=evaluate_option_safety_v2(source,())
        self.assertEqual(result.evaluations,());self.assertEqual(result.risk_evaluation_snapshot_id,source.snapshot_id)

    def test_041_empty_input_requires_empty_claims(self):
        source=replace(risk_snapshot(),evaluations=())
        with self.assertRaises(ValueError): evaluate_option_safety_v2(source,(claim(),))

    def test_042_complete_base_object_identity(self):
        source=risk_snapshot();result=evaluate_option_safety_v2(source,())
        self.assertIs(result.evaluations[0].base_risk_evaluation,source.evaluations[0])

    def test_043_complete_claim_object_identity(self):
        item=claim(Tolerance.UNKNOWN);result=evaluate_option_safety_v2(risk_snapshot(),(item,))
        self.assertIs(result.evaluations[0].safety_policy_claim,item)

    def test_044_no_input_mutation(self):
        source=risk_snapshot();claims=(claim(),);before=asdict(source),tuple(asdict(c) for c in claims),source.snapshot_id
        evaluate_option_safety_v2(source,claims)
        self.assertEqual((asdict(source),tuple(asdict(c) for c in claims),source.snapshot_id),before)

    def test_045_negative_risk_complete_provenance(self):
        source=risk_snapshot(Risk.NOT_ESTABLISHED)
        row=evaluate_option_safety_v2(source,(claim(),)).evaluations[0]
        self.assertEqual(asdict(row.base_risk_evaluation),asdict(source.evaluations[0]))
        self.assertIs(row.base_risk_evaluation.base_bundle,source.evaluations[0].base_bundle)

    def test_046_uncertain_risk_full_nested_provenance(self):
        source=risk_snapshot(Risk.INDETERMINATE)
        row=evaluate_option_safety_v2(source,(claim(Tolerance.TOLERATED),)).evaluations[0]
        self.assertIs(row.base_risk_evaluation.threat_evaluations,source.evaluations[0].threat_evaluations)
        self.assertEqual(asdict(row.base_risk_evaluation),asdict(source.evaluations[0]))

    def test_047_timeline_preserved_and_nonblank(self):
        source=risk_snapshot();result=evaluate_option_safety_v2(source,())
        self.assertEqual(result.timeline_id,source.timeline_id)
        for value in ('',' ',None,True):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,timeline_id=value),())

    def test_048_clock_preserved_and_nonblank(self):
        source=risk_snapshot();result=evaluate_option_safety_v2(source,())
        self.assertEqual(result.selected_clock_id,source.selected_clock_id)
        for value in ('',' ',None,True):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,selected_clock_id=value),())

    def test_049_exact_risk_identity_and_source_header(self):
        source=risk_snapshot();self.assertEqual(evaluate_option_safety_v2(source,()).risk_evaluation_snapshot_id,source.snapshot_id)
        for value in ('',' ',None,True):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,risk_evidence_snapshot_id=value),())

    def test_050_concrete_tick_and_row_alignment(self):
        source=risk_snapshot();row=source.evaluations[0]
        for value in (True,1.0,None,'110'):
            with self.assertRaises(TypeError): evaluate_option_safety_v2(replace(source,risk_assembly_tick=value),())
            with self.assertRaises(TypeError): evaluate_option_safety_v2(replace(source,evaluations=(replace(row,risk_assembly_tick=value),)),())
        with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,risk_assembly_tick=111),())
        source=replace(source,risk_assembly_tick=-5,evaluations=(replace(row,risk_assembly_tick=-5),))
        self.assertEqual(evaluate_option_safety_v2(source,()).risk_assembly_tick,-5)

    def test_051_upstream_policy_header_consistency(self):
        source=risk_snapshot();row=source.evaluations[0]
        for value in ('',' ',None,True):
            with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,evaluation_policy_id=value),())
            with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,evaluations=(replace(row,evaluation_policy_id=value),)),())
        with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,evaluation_policy_id='different'),())
        self.assertEqual(evaluate_option_safety_v2(source,()).evaluations[0].base_risk_evaluation.evaluation_policy_id,source.evaluation_policy_id)

    def test_052_risk_option_ids_preserved_and_exact(self):
        source=risk_snapshot();row=source.evaluations[0]
        class Derived(str): pass
        for name in ('risk_context_id','option_id'):
            for value in ('',' ',None,True,Derived('valid')):
                with self.assertRaises(ValueError): evaluate_option_safety_v2(replace(source,evaluations=(replace(row,**{name:value}),)),())
        result=evaluate_option_safety_v2(source,(claim(),)).evaluations[0]
        self.assertEqual((result.risk_context_id,result.option_id),(row.risk_context_id,row.option_id))

    def test_053_safety_context_separate_from_risk_context(self):
        item=claim(safety_context_id='entirely-unrelated-context')
        result=evaluate_option_safety_v2(risk_snapshot(),(item,)).evaluations[0]
        self.assertEqual(result.risk_context_id,'R');self.assertEqual(result.safety_context_id,item.safety_context_id)

    def test_054_context_strings_opaque(self):
        source=risk_snapshot();row=source.evaluations[0]
        source=replace(source,evaluations=(replace(row,risk_context_id=' role/support/α ',option_id=' option:99 '),))
        item=claim(risk_context_id=' role/support/α ',option_id=' option:99 ',safety_context_id='no-hierarchy',safety_policy_id=' any-policy/β ')
        result=evaluate_option_safety_v2(source,(item,)).evaluations[0]
        self.assertEqual(result.risk_context_id,item.risk_context_id);self.assertIs(result.gate_status,Status.RISK_BLOCKING)

    def test_055_no_silent_trim_or_context_join(self):
        with self.assertRaises(ValueError): evaluate_option_safety_v2(risk_snapshot(),(claim(risk_context_id=' R '),))
        for name in ('risk_context_id','option_id','safety_context_id','safety_policy_id'):
            self.assertEqual(getattr(claim(**{name:'  opaque  '}),name),'  opaque  ')

    def test_056_two_supported_options_different_policies(self):
        source=multiple();claims=(claim(),claim(Tolerance.TOLERATED,option_id='option-B',safety_context_id='S2',safety_policy_id='P2'))
        result=evaluate_option_safety_v2(source,claims)
        self.assertTrue(all(r.base_risk_evaluation.conclusion is Risk.SUPPORTED for r in result.evaluations))
        self.assertEqual([r.gate_status for r in result.evaluations],[Status.RISK_BLOCKING,Status.RISK_NOT_BLOCKING])

    def test_057_claim_order_does_not_change_identity(self):
        source=multiple();claims=(claim(),claim(Tolerance.TOLERATED,option_id='option-B'))
        one=evaluate_option_safety_v2(source,claims);two=evaluate_option_safety_v2(source,tuple(reversed(claims)))
        self.assertEqual(one,two);self.assertEqual(one.snapshot_id,two.snapshot_id)

    def test_058_canonical_input_order_retained(self):
        source=multiple();result=evaluate_option_safety_v2(source,(claim(),claim(Tolerance.TOLERATED,option_id='option-B')))
        self.assertEqual([r.option_id for r in result.evaluations],[r.option_id for r in source.evaluations])
        self.assertEqual([r.gate_status for r in result.evaluations],[Status.RISK_BLOCKING,Status.RISK_NOT_BLOCKING])

    def test_059_identity_repeatable(self):
        self.assertEqual(evaluate().snapshot_id,evaluate().snapshot_id)
        self.assertTrue(evaluate().snapshot_id.startswith('option.safety_gate.v2:snapshot:'))

    def test_060_canonical_json_identity(self):
        source=risk_snapshot();result=evaluate_option_safety_v2(source,(claim(safety_context_id=' α '),))
        payload=json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'option.safety_gate.v2:snapshot:'+hashlib.sha256(payload).hexdigest())

    def test_061_tolerance_bound_even_when_unused(self):
        for risk in Risk:
            self.assertNotEqual(evaluate(risk,Tolerance.TOLERATED).snapshot_id,evaluate(risk,Tolerance.NOT_TOLERATED).snapshot_id)

    def test_062_safety_context_bound(self):
        source=risk_snapshot()
        self.assertNotEqual(evaluate_option_safety_v2(source,(claim(),)).snapshot_id,evaluate_option_safety_v2(source,(claim(safety_context_id='other'),)).snapshot_id)

    def test_063_caller_policy_identity_bound(self):
        source=risk_snapshot()
        self.assertNotEqual(evaluate_option_safety_v2(source,(claim(),)).snapshot_id,evaluate_option_safety_v2(source,(claim(safety_policy_id='other'),)).snapshot_id)

    def test_064_all_headers_and_nested_provenance_bound(self):
        source=risk_snapshot();before=evaluate_option_safety_v2(source,()).snapshot_id
        for name in ('timeline_id','selected_clock_id','risk_evidence_snapshot_id'):
            self.assertNotEqual(before,evaluate_option_safety_v2(replace(source,**{name:'changed'}),()).snapshot_id)
        row=source.evaluations[0]
        changed=replace(source,evaluations=(replace(row,base_bundle=replace(row.base_bundle,horizon_id='different-horizon')),))
        self.assertNotEqual(before,evaluate_option_safety_v2(changed,()).snapshot_id)
        changed=replace(source,risk_assembly_tick=111,evaluations=(replace(row,risk_assembly_tick=111),))
        self.assertNotEqual(before,evaluate_option_safety_v2(changed,()).snapshot_id)

    def test_065_output_status_reason_and_gate_policy_bound(self):
        result=evaluate();row=result.evaluations[0]
        for changes in ({'gate_status':Status.INDETERMINATE},{'reason':Reason.RISK_INDETERMINATE},{'gate_policy_id':'future'}):
            self.assertNotEqual(result.snapshot_id,replace(result,evaluations=(replace(row,**changes),)).snapshot_id)
        self.assertNotEqual(result.snapshot_id,replace(result,gate_policy_id='future').snapshot_id)

    def test_066_no_risk_recalculation(self):
        from coach02 import risk_evaluation
        self.pure([(risk_evaluation,'evaluate_risk')])

    def test_067_no_risk_evidence_rebuild(self):
        from coach02 import risk_evidence_assembly_v02,risk_evidence_assembly
        self.pure([(risk_evidence_assembly_v02,'build_risk_evidence_v2'),(risk_evidence_assembly,'build_risk_evidence')])

    def test_068_no_threat_or_observation_recomputation(self):
        from coach02 import threat_reachability,threat_state_assembly,threat_relevance,strategic_coverage,option_exposure
        self.pure([(threat_reachability,'build_threat_reachability'),(threat_state_assembly,'build_threat_state'),
            (threat_relevance,'build_threat_relevance'),(strategic_coverage,'build_strategic_coverage'),(option_exposure,'build_option_exposure')])

    def test_069_no_freshness_or_event_recompute(self):
        from coach02 import temporal_evidence,observation_event
        self.pure([(temporal_evidence,'evaluate_freshness'),(temporal_evidence,'record_observations'),
            (temporal_evidence,'new_temporal_state'),(observation_event,'project_event_time')])

    def test_070_risk_conclusion_authoritative_no_nested_rule(self):
        source=risk_snapshot();row=source.evaluations[0]
        changed=replace(source,evaluations=(replace(row,conclusion=Risk.INDETERMINATE),))
        result=evaluate_option_safety_v2(changed,(claim(Tolerance.TOLERATED),)).evaluations[0]
        self.assertIs(result.gate_status,Status.INDETERMINATE)
        self.assertIs(result.base_risk_evaluation.base_bundle,row.base_bundle)
        self.no_terms('base_bundle','threat_evaluations','state_use','reachability_use','relevance_use','coverage_use','exposure_use')

    def test_071_no_severity(self): self.no_terms('severity','magnitude','weight','LOW_RISK','HIGH_RISK')
    def test_072_no_score_probability_confidence(self): self.no_terms('score','risk_score','probability','confidence','sum','round','float')
    def test_073_no_damage_or_death(self): self.no_terms('damage','death','disable','lethal','survivability')
    def test_074_no_reward_expected_value(self): self.no_terms('reward','expected_value','gold','xp','farm_value','objective_value')
    def test_075_no_opportunity_cost(self): self.no_terms('opportunity_cost','power_spike','strategic_objective','net_worth')
    def test_076_no_commitment(self): self.no_terms('commitment','committed','action_cost')
    def test_077_no_reversibility(self): self.no_terms('reversibility','reversible','irreversible')
    def test_078_no_abort_window(self): self.no_terms('abort_window','abort','cancel_action')
    def test_079_no_execution_state(self): self.no_terms('execution_state','executing','urgency','deadline')
    def test_080_no_player_or_future_resource_model(self): self.no_terms('health','mana','items','cooldowns','player','future_resource_access')
    def test_081_no_option_ranking(self): self.no_terms('ranking','rank','best_option','preferred','priority')
    def test_082_no_recommendation(self): self.no_terms('recommendation','speech','suggestion','output_text')
    def test_083_no_action_authority(self): self.no_terms('action','GO','STOP','LEAVE','STAY','RETREAT','FIGHT','FARM','ROTATE','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS')

    def test_084_no_legacy_safety_imports(self): self.assertTrue({'.safety_evidence','.option_safety'}.isdisjoint(self.imports()))
    def test_085_no_evidence_imports(self): self.assertTrue({'.risk_evidence_assembly_v02','.risk_evidence_assembly'}.isdisjoint(self.imports()))
    def test_086_no_reachability_import(self): self.assertNotIn('.threat_reachability',self.imports())
    def test_087_no_state_relevance_imports(self): self.assertTrue({'.threat_state_assembly','.threat_relevance'}.isdisjoint(self.imports()))
    def test_088_no_coverage_exposure_temporal_imports(self): self.assertTrue({'.strategic_coverage','.option_exposure','.observation_event','.temporal_evidence'}.isdisjoint(self.imports()))
    def test_089_no_decision_runtime_imports(self): self.assertTrue({'.decision','.farm_context','.farm_cycle','.runtime_adapter','.service','.vision','.gsi'}.isdisjoint(self.imports()))

    def test_090_only_required_public_contracts(self):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json','.risk_evaluation'})
        node=next(n for n in ast.parse(inspect.getsource(gate)).body if isinstance(n,ast.ImportFrom) and n.level==1)
        self.assertEqual({n.name for n in node.names},{'RiskEvaluationSnapshot','OptionRiskEvaluation','RiskConclusion'})
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

    def test_095_no_random_or_mutable_globals(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])
        before=dict(vars(gate));evaluate();evaluate(Risk.INDETERMINATE)
        self.assertEqual(before,vars(gate))
        for name,value in vars(gate).items():
            if not name.startswith('__'): self.assertNotIsInstance(value,(dict,list,set,bytearray))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(ast.parse(inspect.getsource(gate)))))

    def test_096_legacy_review(self):
        from coach02.option_safety import OptionSafetyEvidence,FarmOptionSafetyObservation,Exposure
        from coach02.safety_evidence import RiskAwarenessEvidence,RelevantThreatObservation
        self.assertEqual({v.value for v in Exposure},{'LOW','HIGH','UNKNOWN'})
        self.assertIn('action',{f.name for f in fields(OptionSafetyEvidence)})
        self.assertIn('exposure_freshness',{f.name for f in fields(FarmOptionSafetyObservation)})
        self.assertEqual({f.name for f in fields(RelevantThreatObservation)},{'threat_id','state','freshness'})
        self.assertNotIn('supported_risk_tolerance',{f.name for f in fields(RiskAwarenessEvidence)})
        self.assertIn('NO_DIRECT_PRODUCTION_COMPATIBILITY_V02',self.document())

    def test_097_no_adapter(self):
        self.assertEqual({n for n,v in vars(gate).items() if inspect.isfunction(v) and v.__module__==gate.__name__ and not n.startswith('_')},{'evaluate_option_safety_v2'})
        self.no_terms('adapter','legacy','to_safety_claim')

    def test_098_decision_handoff_documented(self):
        doc=self.document()
        for text in ('BLOCKER_BEFORE_DECISION_CONTEXT','BLOCKER_BEFORE_ACTION_AUTHORITY','BLOCKER_BEFORE_LIVE','ACCEPTED_V02_LIMITATION',
                     'OptionSafetySnapshotV2','strategic objective','option value/reward','opportunity cost','future resource access',
                     'commitment','reversibility','abort window','execution state','urgency'):
            self.assertIn(text,doc)

    def test_099_exact_consumer_arbitrary_rejected(self):
        g=self.guard()
        self.assertEqual(g['authorized_consumers'],{'coach02/option_safety_v02.py'})
        self.assertEqual(g['allowed_contracts'],{'RiskEvaluationSnapshot','OptionRiskEvaluation','RiskConclusion'})
        self.assertEqual(g['violations'](inspect.getsource(gate),'coach02/option_safety_v02.py'),[])
        for name in g['allowed_contracts']:
            for path in ('coach02/arbitrary.py','coach02/service.py','coach02/decision.py','run.py'):
                self.assertTrue(g['violations']('from .risk_evaluation import '+name,path))

    def test_100_builder_constructor_alias_dynamic_rejected(self):
        g=self.guard();consumer='coach02/option_safety_v02.py'
        rejected=['from .risk_evaluation import evaluate_risk','runtime.evaluate_risk()',
            'from .risk_evaluation import *','import coach02.risk_evaluation','from coach02 import risk_evaluation',
            "__import__('coach02.risk_evaluation')","import importlib as loader; loader.import_module('coach02.risk_evaluation')",
            "from importlib import import_module as load; load('coach02.risk_evaluation')"]
        for name in g['allowed_contracts']:
            rejected.extend(['from .risk_evaluation import '+name+' as C',
                             'from .risk_evaluation import '+name+'; alias='+name+'; alias()'])
        for source in rejected:
            with self.subTest(source=source): self.assertTrue(g['violations'](source,consumer))

    def test_101_existing_production_hashes(self):
        root=Path(gate.__file__).resolve().parent.parent
        self.assertEqual(len(PRODUCTION_HASHES),45)
        for name,sha in PRODUCTION_HASHES:
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),sha)

    def test_102_risk_contract_and_conclusion_preserved(self):
        self.assertEqual({v.value for v in Risk},{'SUPPORTED','NOT_ESTABLISHED','INDETERMINATE'})
        self.assertEqual({f.name for f in fields(RiskEvaluationSnapshot)},
            {'timeline_id','selected_clock_id','risk_evidence_snapshot_id','risk_assembly_tick','evaluation_policy_id','evaluations'})
        for risk in Risk:
            source=risk_snapshot(risk);result=evaluate_option_safety_v2(source,(claim(),))
            self.assertIs(result.evaluations[0].base_risk_evaluation.conclusion,risk)
            self.assertEqual(result.risk_evaluation_snapshot_id,source.snapshot_id)

    def test_103_fixed_gate_policy_distinct_from_caller(self):
        source=risk_snapshot();item=claim(safety_policy_id='external-policy')
        result=evaluate_option_safety_v2(source,(item,));row=result.evaluations[0]
        self.assertEqual(result.gate_policy_id,'option.safety_gate.v2')
        self.assertEqual(row.gate_policy_id,result.gate_policy_id)
        self.assertEqual(row.safety_policy_claim.safety_policy_id,'external-policy')
        self.assertEqual(tuple(inspect.signature(evaluate_option_safety_v2).parameters),('risk_evaluation_snapshot','policy_claims'))
        with self.assertRaises(TypeError): evaluate_option_safety_v2(source)

    def test_104_no_safe_unsafe_output(self):
        self.assertEqual({f.name for f in fields(OptionSafetySnapshotV2)},
            {'timeline_id','selected_clock_id','risk_evaluation_snapshot_id','risk_assembly_tick','gate_policy_id','evaluations'})
        for risk in Risk:
            for tolerance in (*Tolerance,None):
                result=evaluate(risk,tolerance)
                values={result.evaluations[0].gate_status.value,result.evaluations[0].reason.value}
                self.assertTrue({'SAFE','UNSAFE','DANGER','RECOMMENDED','RETREAT'}.isdisjoint(values))


PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
