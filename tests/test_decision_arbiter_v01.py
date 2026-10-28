"""Fixed admission, explicit comparisons, exact provenance and no action authority."""
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

from coach02 import decision_arbiter_v01 as arbiter
from coach02.decision_arbiter_v01 import (
    ArbiterCandidateAdmissionStatus as Admission, DecisionArbiterStatus as Status,
    DecisionArbiterReason as Reason, DecisionArbiterRequestV1,
    ArbiterCandidateAssessmentV1, DecisionArbiterResultV1, build_decision_arbiter_result_v1,
)
from coach02.decision_context_v02 import DecisionEvidencePresence as Presence
from coach02.option_safety_v02 import OptionSafetyGateStatus as Safety
from coach02.feasibility_gate_v01 import FeasibilityGateStatus as Feasibility, FeasibilityRequirementState
from coach02.pairwise_tradeoff_v01 import PairwiseTradeoffConclusion as Pair
from test_decision_context_v02 import build as decision, sources, request, binding, outcome_claim, SupportedRiskTolerance
from test_feasibility_gate_v01 import build as feasible, policy, claim as requirement, import_violations
from test_objective_outcome_relation_v01 import build as relations, claim as relation_claim
from test_pairwise_tradeoff_v01 import build as pairwise, between
from test_decision_context_v02 import consumer_violations


def fixture(names=('A', 'B'), safety=None, feasibility=None, edges=(), no_objective=False, none_safety_context=False):
    safety = ('RISK_NOT_BLOCKING',) * len(names) if safety is None else safety
    feasibility = ('FEASIBLE',) * len(names) if feasibility is None else feasibility
    upstream = sources(outcomes=tuple(outcome_claim(option_id=n, dimension_id=d) for n in names for d in ('x','y')),
                       objectives=() if no_objective else None, tolerance=SupportedRiskTolerance.TOLERATED)
    objective, safe, outcome = upstream
    # Explicit synthetic upstream verdicts; the Arbiter must never reopen their nested semantics.
    template = safe.evaluations[0]
    evaluations = tuple(replace(template, option_id=n, gate_status=Safety(s),
        safety_context_id=None if none_safety_context else template.safety_context_id)
        for n,s in sorted(zip(names,safety)) if s is not None)
    context = decision((objective,replace(safe,evaluations=evaluations),outcome),
        request(tuple(binding(option_id=n, safety_context_id=None if none_safety_context else template.safety_context_id) for n in names)))
    policies = tuple(policy(context,option_id=n) for n in names)
    mapping={'FEASIBLE':FeasibilityRequirementState.SATISFIED,'INFEASIBLE':FeasibilityRequirementState.UNSATISFIED,'INDETERMINATE':FeasibilityRequirementState.UNKNOWN}
    claims = tuple(requirement(context,option_id=n,state=mapping[s]) for n,s in zip(names,feasibility))
    fs = feasible(context,policies,claims)
    rs = relations(context,() if no_objective else tuple(relation_claim(context,option_id=n,dimension_id=d) for n in names for d in ('x','y')))
    ps = pairwise(context,rs,tuple(between(context,rs,left,right,conclusion=Pair(conclusion),
        pairwise_context_id=pc) for left,right,conclusion,pc in edges))
    return context,fs,ps,DecisionArbiterRequestV1(context.decision_context_id,'arbiter-context','P')


def build(bundle=None):
    c,f,p,r=fixture() if bundle is None else bundle
    return build_decision_arbiter_result_v1(decision_context=c,feasibility_snapshot=f,pairwise_snapshot=p,request=r)


def edge(left='A',right='B',conclusion='LEFT_ADVANTAGE',context='P'):
    return left,right,conclusion,context


def context_change(bundle,context):
    _,f,p,r=bundle
    by_id={o.option_id:o for o in context.options}
    f=replace(f,decision_context_object_id=context.context_id,
        assessments=tuple(replace(a,base_option_context=by_id[a.option_id]) for a in f.assessments))
    return context,f,replace(p,decision_context_object_id=context.context_id),r


class DecisionArbiterV1Tests(unittest.TestCase):
    def domain(self,enum,names):
        self.assertEqual({k:v.value for k,v in enum.__members__.items()},{n:n for n in names})
    def rejects(self,bundle):
        with self.assertRaises((TypeError,ValueError)):build(bundle)
    def header(self,index,field,value='foreign'):
        b=list(fixture());b[index]=replace(b[index],**{field:value});self.rejects(b)
    def expected(self,bundle,status,reason,selected=None):
        result=build(bundle)
        self.assertIs(result.status,Status(status));self.assertIs(result.reason,Reason(reason))
        self.assertEqual(result.selected_option_id,selected)
        if selected is None:self.assertIsNone(result.selected_option)
        else:self.assertIs(result.selected_option,next(o for o in bundle[0].options if o.option_id==selected))
        return result
    def matrix(self,safety,feasibility,status):
        b=fixture(names=('A',),safety=(safety,),feasibility=(feasibility,));a=build(b).candidate_assessments[0]
        self.assertIs(a.admission_status,Admission(status));self.assertIs(a.safety_gate_status,None if safety is None else Safety(safety))
        self.assertIs(a.base_option_context,b[0].options[0]);self.assertIs(a.base_feasibility_assessment,b[1].assessments[0])
    def no_terms(self,*terms):
        tree=ast.parse(inspect.getsource(arbiter))
        tokens={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}|{n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        self.assertTrue(set(terms).isdisjoint(tokens))
    def changed_safety(self,**changes):
        b=fixture();o=b[0].options[0];o=replace(o,safety_evaluation=replace(o.safety_evaluation,**changes))
        return context_change(b,replace(b[0],options=(o,*b[0].options[1:])))

    def test_001_admission_domain(self):self.domain(Admission,('ADMITTED','EXCLUDED','INDETERMINATE'))
    def test_002_status_domain(self):self.domain(Status,('SELECTED','NO_SELECTION','INDETERMINATE'))
    def test_003_reason_domain(self):self.domain(Reason,('SINGLE_ADMITTED_OPTION','UNIQUE_DIRECT_ADVANTAGE','NO_ADMITTED_OPTIONS','NO_UNIQUE_DIRECT_ADVANTAGE','CANDIDATE_ADMISSION_INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE','PAIRWISE_EVIDENCE_INDETERMINATE'))
    def test_004_request_frozen_revalidated(self):
        b=fixture()
        with self.assertRaises(FrozenInstanceError):b[3].arbiter_context_id='other'
        object.__setattr__(b[3],'arbiter_context_id',' ');self.rejects(b)
    def test_005_assessment_frozen(self):
        with self.assertRaises(FrozenInstanceError):build().candidate_assessments[0].admission_status=Admission.EXCLUDED
    def test_006_result_frozen(self):
        with self.assertRaises(FrozenInstanceError):build().status=Status.SELECTED
        self.assertEqual(tuple(f.name for f in fields(DecisionArbiterResultV1)),('decision_context_id','decision_context_object_id','feasibility_snapshot_id','pairwise_snapshot_id','timeline_id','selected_clock_id','evaluated_at_tick','base_request','candidate_assessments','considered_pairwise_evidence','status','reason','selected_option_id','selected_option','ruleset'))
    def test_007_exact_strings(self):
        class Text(str):pass
        r=fixture()[3]
        for name in ('decision_context_id','arbiter_context_id','pairwise_context_id'):
            for bad in (Text('x'),1,False,None):
                with self.subTest(name=name,bad=bad),self.assertRaises(ValueError):replace(r,**{name:bad})
    def test_008_blank_strings(self):
        for name in ('decision_context_id','arbiter_context_id','pairwise_context_id'):
            for bad in ('',' \t\n','\u2003'):
                with self.assertRaises(ValueError):replace(fixture()[3],**{name:bad})
    def test_009_no_trim_opaque_roles(self):
        for name in (' Carry ','Mid','Offlane','Support 4','Support 5','Roshan/魔法'):
            b=fixture(names=(name,));r=replace(b[3],arbiter_context_id=' β ',pairwise_context_id=' P ')
            result=build((*b[:3],r));self.assertEqual(result.selected_option_id,name);self.assertIs(result.base_request,r)
    def test_010_exact_contracts_tuples_and_api(self):
        b=fixture()
        for i,obj in enumerate(b):
            child=type('Child',(type(obj),),{})(**{f.name:getattr(obj,f.name) for f in fields(obj)})
            for invalid in (None,{},child):
                altered=list(b);altered[i]=invalid;self.rejects(altered)
        class Tuple(tuple):pass
        for i,field in ((0,'options'),(1,'assessments'),(2,'comparisons')):
            for bad in ([],Tuple(getattr(b[i],field))):
                altered=list(b);altered[i]=replace(b[i],**{field:bad});self.rejects(altered)
        option=b[0].options[0];child=type('Child',(type(option),),{})(**{f.name:getattr(option,f.name) for f in fields(option)})
        self.rejects((replace(b[0],options=(child,*b[0].options[1:])),*b[1:]))
        self.rejects((replace(b[0],options=b[0].options*2),*b[1:]))
        parameters=inspect.signature(build_decision_arbiter_result_v1).parameters
        self.assertEqual(tuple(parameters),('decision_context','feasibility_snapshot','pairwise_snapshot','request'))
        self.assertTrue(all(p.kind==p.KEYWORD_ONLY and p.default==p.empty for p in parameters.values()))
    def test_011_decision_context_id(self):
        for i in range(4):self.header(i,'decision_context_id')
    def test_012_feasibility_context_identity(self):self.header(1,'decision_context_object_id')
    def test_013_pairwise_context_identity(self):self.header(2,'decision_context_object_id')
    def test_014_timeline_exact(self):
        for i in range(3):self.header(i,'timeline_id')
    def test_015_clock_exact(self):
        for i in range(3):self.header(i,'selected_clock_id')
    def test_016_tick_exact(self):
        class Tick(int):pass
        for i,field in ((0,'decision_assembly_tick'),(1,'evaluated_at_tick'),(2,'evaluated_at_tick')):
            for value in (True,-1,1.5,Tick(100),fixture()[0].decision_assembly_tick+1):self.header(i,field,value)
    def test_017_objective_context(self):self.header(2,'objective_context_id')
    def test_018_objective_horizon(self):self.header(2,'objective_horizon_id')
    def test_019_objective_id(self):
        self.header(2,'objective_id');self.header(2,'objective_id',None)
        b=fixture(no_objective=True);self.rejects((b[0],b[1],replace(b[2],objective_id='foreign'),b[3]))
    def test_020_foreign_rulesets_lineage_ids(self):
        for i in range(3):self.header(i,'ruleset')
        for value in ('',None):self.header(2,'relation_snapshot_id',value)
    def test_021_complete_assessment_mapping(self):
        b=fixture(names=('C','A','B'));r=build(b)
        self.assertEqual([a.option_id for a in r.candidate_assessments],['A','B','C'])
        for a in r.candidate_assessments:self.assertIs(a.base_feasibility_assessment,next(x for x in b[1].assessments if x.option_id==a.option_id))
    def test_022_missing_assessment(self):
        b=fixture();self.rejects((b[0],replace(b[1],assessments=b[1].assessments[:1]),*b[2:]))
    def test_023_extra_assessment(self):
        b=fixture();self.rejects((b[0],replace(b[1],assessments=b[1].assessments+(replace(b[1].assessments[0],option_id='X'),)),*b[2:]))
    def test_024_duplicate_assessment(self):
        b=fixture();self.rejects((b[0],replace(b[1],assessments=b[1].assessments*2),*b[2:]))
    def test_025_base_option_exact_identity(self):
        b=fixture();a=b[1].assessments[0]
        self.rejects((b[0],replace(b[1],assessments=(replace(a,base_option_context=replace(a.base_option_context)),*b[1].assessments[1:])),*b[2:]))
    def test_026_feasibility_type_enum(self):
        class Other(str,Enum):FEASIBLE='FEASIBLE'
        b=fixture();a=b[1].assessments[0]
        for bad in ('FEASIBLE',Other.FEASIBLE,None):self.rejects((b[0],replace(b[1],assessments=(replace(a,status=bad),*b[1].assessments[1:])),*b[2:]))
        child=type('Child',(type(a),),{})(**{f.name:getattr(a,f.name) for f in fields(a)})
        self.rejects((b[0],replace(b[1],assessments=(child,*b[1].assessments[1:])),*b[2:]))
    def test_027_absent_requires_none(self):
        b=fixture();o=replace(b[0].options[0],safety_presence=Presence.ABSENT)
        self.rejects(context_change(b,replace(b[0],options=(o,*b[0].options[1:]))))
    def test_028_present_exact_evaluation(self):
        b=fixture();o=b[0].options[0];evaluation=o.safety_evaluation
        child=type('Child',(type(evaluation),),{})(**{f.name:getattr(evaluation,f.name) for f in fields(evaluation)})
        for bad in (None,child):
            self.rejects(context_change(b,replace(b[0],options=(replace(o,safety_evaluation=bad),*b[0].options[1:]))))
    def test_029_exact_safety_enum_and_presence(self):
        class Other(str,Enum):RISK_NOT_BLOCKING='RISK_NOT_BLOCKING'
        for bad in ('RISK_NOT_BLOCKING',Other.RISK_NOT_BLOCKING,None):self.rejects(self.changed_safety(gate_status=bad))
        b=fixture();o=replace(b[0].options[0],safety_presence='PRESENT')
        self.rejects(context_change(b,replace(b[0],options=(o,*b[0].options[1:]))))
    def test_030_none_context_present(self):
        r=build(fixture(names=('A',),none_safety_context=True));self.assertIs(r.status,Status.SELECTED)
        self.assertIs(r.candidate_assessments[0].safety_presence,Presence.PRESENT)
    def test_031_safety_option_binding(self):self.rejects(self.changed_safety(option_id='B'))
    def test_032_safety_risk_binding(self):self.rejects(self.changed_safety(risk_context_id='other'))
    def test_033_safety_context_binding(self):self.rejects(self.changed_safety(safety_context_id='other'))
    def test_034_blocking_feasible(self):self.matrix('RISK_BLOCKING','FEASIBLE','EXCLUDED')
    def test_035_blocking_infeasible(self):self.matrix('RISK_BLOCKING','INFEASIBLE','EXCLUDED')
    def test_036_blocking_indeterminate(self):self.matrix('RISK_BLOCKING','INDETERMINATE','EXCLUDED')
    def test_037_nonblocking_feasible(self):self.matrix('RISK_NOT_BLOCKING','FEASIBLE','ADMITTED')
    def test_038_nonblocking_infeasible(self):self.matrix('RISK_NOT_BLOCKING','INFEASIBLE','EXCLUDED')
    def test_039_nonblocking_indeterminate(self):self.matrix('RISK_NOT_BLOCKING','INDETERMINATE','INDETERMINATE')
    def test_040_uncertain_feasible(self):self.matrix('INDETERMINATE','FEASIBLE','INDETERMINATE')
    def test_041_uncertain_infeasible(self):self.matrix('INDETERMINATE','INFEASIBLE','EXCLUDED')
    def test_042_uncertain_indeterminate(self):self.matrix('INDETERMINATE','INDETERMINATE','INDETERMINATE')
    def test_043_absent_feasible(self):self.matrix(None,'FEASIBLE','INDETERMINATE')
    def test_044_absent_infeasible(self):self.matrix(None,'INFEASIBLE','EXCLUDED')
    def test_045_absent_indeterminate(self):self.matrix(None,'INDETERMINATE','INDETERMINATE')
    def test_046_any_admission_indeterminate(self):
        self.expected(fixture(names=('A','B','C'),safety=('RISK_NOT_BLOCKING','RISK_NOT_BLOCKING',None),edges=(edge(),)),'INDETERMINATE','CANDIDATE_ADMISSION_INDETERMINATE')
    def test_047_pairwise_cannot_override_admission(self):
        b=fixture(safety=('INDETERMINATE','RISK_NOT_BLOCKING'),edges=(edge(conclusion='RIGHT_ADVANTAGE'),))
        with patch.object(arbiter,'_advantage',side_effect=AssertionError('pairwise selection executed')):r=build(b)
        self.assertEqual(r.considered_pairwise_evidence,())
    def test_048_all_excluded(self):
        r=self.expected(fixture(safety=('RISK_BLOCKING','RISK_BLOCKING')),'NO_SELECTION','NO_ADMITTED_OPTIONS')
        self.assertEqual(len(r.candidate_assessments),2);self.assertEqual(r.considered_pairwise_evidence,())
    def test_049_empty_context(self):
        r=self.expected(fixture(names=(),no_objective=True),'NO_SELECTION','NO_ADMITTED_OPTIONS')
        self.assertEqual(r.candidate_assessments,());self.assertEqual(r.considered_pairwise_evidence,())
    def test_050_single_admitted_no_objective(self):self.expected(fixture(names=('A',),no_objective=True),'SELECTED','SINGLE_ADMITTED_OPTION','A')
    def test_051_selected_object_exact(self):
        b=fixture(safety=('RISK_BLOCKING','RISK_NOT_BLOCKING'));r=build(b);self.assertIs(r.selected_option,b[0].options[1])
    def test_052_selected_id_exact(self):self.assertEqual(build(fixture(names=(' z ',))).selected_option_id,' z ')
    def test_053_two_complete(self):self.expected(fixture(edges=(edge(),)),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A')
    def test_054_missing_pair(self):self.expected(fixture(),'INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE')
    def test_055_three_complete(self):self.expected(fixture(names=('A','B','C'),edges=(edge(),edge('A','C'),edge('B','C'))),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A')
    def test_056_one_of_three_missing(self):self.expected(fixture(names=('A','B','C'),edges=(edge(),edge('B','C'))),'INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE')
    def test_057_selected_context(self):
        b=fixture(edges=(edge(context='P'),edge(conclusion='RIGHT_ADVANTAGE',context='Q')))
        self.expected((*b[:3],replace(b[3],pairwise_context_id='Q')),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','B')
    def test_058_other_context_not_backfill(self):self.expected(fixture(edges=(edge(context='Q'),)),'INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE')
    def test_059_excluded_rows_ignored(self):
        b=fixture(names=('A','B','C'),safety=('RISK_NOT_BLOCKING','RISK_NOT_BLOCKING','RISK_BLOCKING'),edges=(edge(),edge('C','A'),edge('C','B')))
        r=self.expected(b,'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A');self.assertEqual(len(r.considered_pairwise_evidence),1)
    def test_060_valid_extra_rows(self):
        b=fixture(edges=(edge(),edge(conclusion='INDETERMINATE',context='Q')))
        self.expected(b,'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A')
    def test_061_malformed_irrelevant_rows(self):
        b=fixture(safety=('RISK_BLOCKING','RISK_BLOCKING'),edges=(edge(context='Q'),));row=b[2].comparisons[0]
        class Other(str,Enum):LEFT_ADVANTAGE='LEFT_ADVANTAGE'
        changes=({'left_option_id':'foreign'},{'right_option_id':'A'},{'pairwise_context_id':' '},{'decision_context_id':'foreign'},
                 {'basis_tick':True},{'basis_tick':row.basis_tick+1},{'conclusion':'LEFT_ADVANTAGE'},{'conclusion':Other.LEFT_ADVANTAGE})
        for change in changes:self.rejects((b[0],b[1],replace(b[2],comparisons=(replace(row,**change),)),b[3]))
        child=type('Child',(type(row),),{})(**{f.name:getattr(row,f.name) for f in fields(row)})
        self.rejects((b[0],b[1],replace(b[2],comparisons=(child,)),b[3]))
        reverse=replace(row,left_option_id='B',right_option_id='A')
        for duplicate in (row,reverse):self.rejects((b[0],b[1],replace(b[2],comparisons=(row,duplicate)),b[3]))
    def test_062_required_indeterminate_even_among_others(self):
        b=fixture(names=('A','B','C'),edges=(edge(),edge('A','C'),edge('B','C','INDETERMINATE')))
        self.expected(b,'INDETERMINATE','PAIRWISE_EVIDENCE_INDETERMINATE')
    def test_063_incomplete_precedes_indeterminate(self):
        self.expected(fixture(names=('A','B','C'),edges=(edge(conclusion='INDETERMINATE'),)),'INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE')
    def test_064_left_advantage(self):self.expected(fixture(edges=(edge(),)),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A')
    def test_065_right_advantage(self):self.expected(fixture(edges=(edge(conclusion='RIGHT_ADVANTAGE'),)),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','B')
    def test_066_universal_candidate_not_lexical_first(self):
        self.expected(fixture(names=('A','B','Z'),edges=(edge(),edge('Z','A'),edge('Z','B'))),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','Z')
    def test_067_reverse_orientation(self):self.expected(fixture(edges=(edge('B','A','RIGHT_ADVANTAGE'),)),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','A')
    def test_068_no_most_wins_fallback(self):
        b=fixture(names=('A','B','C','D'),edges=(edge(),edge('A','C'),edge('D','A'),edge('B','C'),edge('B','D'),edge('C','D')))
        self.expected(b,'NO_SELECTION','NO_UNIQUE_DIRECT_ADVANTAGE');self.no_terms('win_count','loss_count','Counter','count')
    def test_069_no_transitivity(self):
        self.expected(fixture(names=('A','B','C'),edges=(edge(),edge('B','C'))),'INDETERMINATE','PAIRWISE_EVIDENCE_INCOMPLETE')
    def test_070_no_graph_closure(self):
        self.no_terms('closure','topological_sort','transitive','cycle_detection')
        b=fixture(names=('A','B','C'),edges=(edge(),edge('B','C')));before=b[2].snapshot_id;build(b)
        self.assertEqual(b[2].snapshot_id,before);self.assertEqual(len(b[2].comparisons),2)
    def test_071_three_cycle(self):self.expected(fixture(names=('A','B','C'),edges=(edge(),edge('B','C'),edge('C','A'))),'NO_SELECTION','NO_UNIQUE_DIRECT_ADVANTAGE')
    def test_072_tradeoff(self):self.expected(fixture(edges=(edge(conclusion='TRADE_OFF'),)),'NO_SELECTION','NO_UNIQUE_DIRECT_ADVANTAGE')
    def test_073_equivalent(self):self.expected(fixture(edges=(edge(conclusion='EQUIVALENT'),)),'NO_SELECTION','NO_UNIQUE_DIRECT_ADVANTAGE')
    def test_074_mixed_determined_no_winner(self):
        self.expected(fixture(names=('A','B','C'),edges=(edge(),edge('A','C','TRADE_OFF'),edge('B','C','EQUIVALENT'))),'NO_SELECTION','NO_UNIQUE_DIRECT_ADVANTAGE')
    def test_075_universal_over_cycle(self):
        self.expected(fixture(names=('A','B','C','D'),edges=(edge(),edge('B','C'),edge('C','A'),edge('D','A'),edge('D','B'),edge('D','C'))),'SELECTED','UNIQUE_DIRECT_ADVANTAGE','D')
    def test_076_no_utility(self):self.no_terms('utility','reward','expected_value')
    def test_077_no_weighted_sum(self):self.no_terms('weight','weights','sum')
    def test_078_no_win_score(self):self.no_terms('score','points','win_ratio','elo','majority')
    def test_079_no_ranking_output(self):
        names={f.name for kind in (DecisionArbiterRequestV1,ArbiterCandidateAssessmentV1,DecisionArbiterResultV1) for f in fields(kind)}
        self.assertTrue({'rank','ranking','score','runner_up','best','worst'}.isdisjoint(names));self.no_terms('ranking','rank','ranked')
    def test_080_no_cost_aggregation(self):self.no_terms('OpportunityCostConclusion','left_opportunity_cost','right_opportunity_cost')
    def test_081_no_relation_or_risk_inspection(self):self.no_terms('left_relation_evidences','right_relation_evidences','base_risk_evaluation','RiskConclusion','supported_risk_tolerance')
    def test_082_selected_id_object_invariants(self):
        for b in (fixture(names=('A',)),fixture(edges=(edge(),))):
            r=build(b);self.assertIs(r.status,Status.SELECTED);self.assertIs(type(r.selected_option_id),str)
            self.assertEqual(r.selected_option.option_id,r.selected_option_id)
            self.assertTrue(any(r.selected_option is o for o in b[0].options))
    def test_083_no_selection_nulls(self):
        for b in (fixture(names=()),fixture(edges=(edge(conclusion='TRADE_OFF'),))):
            r=build(b);self.assertIs(r.status,Status.NO_SELECTION);self.assertIsNone(r.selected_option);self.assertIsNone(r.selected_option_id)
    def test_084_indeterminate_nulls(self):
        for b in (fixture(),fixture(safety=(None,None)),fixture(edges=(edge(conclusion='INDETERMINATE'),))):
            r=build(b);self.assertIs(r.status,Status.INDETERMINATE);self.assertIsNone(r.selected_option);self.assertIsNone(r.selected_option_id)
    def test_085_single_no_considered_pairs(self):
        b=fixture(safety=('RISK_NOT_BLOCKING','RISK_BLOCKING'),edges=(edge(),));self.assertEqual(build(b).considered_pairwise_evidence,())
    def test_086_admission_uncertain_no_considered_pairs(self):self.assertEqual(build(fixture(safety=(None,'RISK_NOT_BLOCKING'),edges=(edge(),))).considered_pairwise_evidence,())
    def test_087_incomplete_preserves_available(self):
        b=fixture(names=('A','B','C'),edges=(edge(),));r=build(b)
        self.assertEqual(len(r.considered_pairwise_evidence),1);self.assertIs(r.considered_pairwise_evidence[0],b[2].comparisons[0])
    def test_088_full_preserves_exact_rows(self):
        b=fixture(names=('A','B','C'),edges=(edge(),edge('A','C'),edge('B','C')));r=build(b)
        for row,base in zip(r.considered_pairwise_evidence,b[2].comparisons):self.assertIs(row,base)
    def test_089_ruleset(self):self.assertEqual(build().ruleset,'decision.arbiter.v1')
    def test_090_deterministic_identity(self):
        b=fixture(edges=(edge(),));a=build(b);self.assertEqual(a.result_id,build(b).result_id)
        payload={n:getattr(a,n) for n in ('decision_context_id','decision_context_object_id','feasibility_snapshot_id','pairwise_snapshot_id','timeline_id','selected_clock_id','evaluated_at_tick','status','reason','selected_option_id','ruleset')}
        payload['base_request']=asdict(a.base_request)
        payload['candidate_assessments']=[{n:getattr(row,n) for n in ('option_id','admission_status','safety_presence','safety_gate_status','feasibility_status')} for row in a.candidate_assessments]
        payload['considered_pairwise_evidence']=[row.evidence_id for row in a.considered_pairwise_evidence]
        expected=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(a.result_id,'decision.arbiter.v1:result:'+expected)
    def test_091_request_changes_identity(self):
        b=fixture(names=('A',));a=build(b)
        for field in ('arbiter_context_id','pairwise_context_id'):
            self.assertNotEqual(a.result_id,build((*b[:3],replace(b[3],**{field:'other'}))).result_id)
    def test_092_context_identity_changes(self):
        b=fixture();a=build(b);c=replace(b[0],context_binding_policy_id='other')
        self.assertNotEqual(a.result_id,build(context_change(b,c)).result_id)
    def test_093_feasibility_snapshot_identity(self):
        b=fixture(names=('A',));a=build(b);row=b[1].assessments[0]
        f=replace(b[1],assessments=(replace(row,policy=replace(row.policy,feasibility_policy_id='other')),))
        self.assertNotEqual(a.result_id,build((b[0],f,*b[2:])).result_id)
    def test_094_pairwise_snapshot_identity(self):
        b=fixture(names=('A',));a=build(b)
        self.assertNotEqual(a.result_id,build((b[0],b[1],replace(b[2],relation_snapshot_id='different'),b[3])).result_id)
    def test_095_status_reason_bound(self):
        r=build()
        for change in ({'status':Status.NO_SELECTION},{'reason':Reason.NO_ADMITTED_OPTIONS}):self.assertNotEqual(r.result_id,replace(r,**change).result_id)
    def test_096_selected_id_bound(self):
        r=build(fixture(edges=(edge(),)));self.assertNotEqual(r.result_id,replace(r,selected_option_id='B').result_id)
    def test_097_semantically_equivalent_order(self):
        e=(edge(),edge('A','C'),edge('B','C'));a=fixture(names=('A','B','C'),edges=e);b=fixture(names=('C','B','A'),edges=e[::-1])
        self.assertEqual(build(a).result_id,build(b).result_id)
        c,f,p,r=a
        fs=feasible(c,tuple(policy(c,option_id=n,required_requirement_ids=('x','y')) for n in ('A','B','C')),
            tuple(requirement(c,option_id=n,requirement_id=d) for n in ('A','B','C') for d in ('x','y')))
        alternate=replace(fs,assessments=tuple(replace(row,policy=replace(row.policy,required_requirement_ids=('y','x'))) for row in fs.assessments))
        self.assertEqual(fs.snapshot_id,alternate.snapshot_id);self.assertEqual(build((c,fs,p,r)).result_id,build((c,alternate,p,r)).result_id)
        swapped=replace(p,comparisons=tuple(replace(row,base_claim=replace(row.base_claim,
            left_relation_evidence_ids=row.base_claim.left_relation_evidence_ids[::-1],
            right_relation_evidence_ids=row.base_claim.right_relation_evidence_ids[::-1])) for row in p.comparisons))
        self.assertEqual(p.snapshot_id,swapped.snapshot_id);self.assertEqual(build(a).result_id,build((c,f,swapped,r)).result_id)
    def test_098_assessment_order_not_preference(self):
        r=build(fixture(names=('Z','A','M'),safety=('RISK_NOT_BLOCKING','RISK_BLOCKING',None)))
        self.assertEqual([a.option_id for a in r.candidate_assessments],['A','M','Z'])
    def test_099_canonical_pair_order(self):
        b=fixture(names=('A','B','C'),edges=(edge('C','B'),edge('C','A'),edge('B','A')));r=build(b)
        self.assertEqual([tuple(sorted((row.left_option_id,row.right_option_id))) for row in r.considered_pairwise_evidence],[('A','B'),('A','C'),('B','C')])
    def test_100_exact_imports_no_legacy(self):
        tree=ast.parse(inspect.getsource(arbiter));actual={n.module:{a.name for a in n.names} for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level}
        self.assertEqual(actual,CONTRACTS);self.assertTrue(all(a.asname is None for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) for a in n.names))
        self.no_terms('Decision','DecisionContext','CandidatePlan','FarmStrategicEvidence')
    def test_101_no_lower_domain_consumption(self):
        self.no_terms('ObjectiveOutcomeRelationSnapshotV1','ObjectiveOutcomeRelationEvidence','OptionOutcomeEvidence','StrategicObjectiveSnapshot','RiskEvaluationSnapshot','OpportunityCostConclusion')
    def test_102_purity_and_no_mutation(self):
        import builtins,io,os,socket,subprocess,time,random,uuid
        b=fixture(edges=(edge(),));expected=build(b);before=tuple(asdict(x) for x in b);state=dict(vars(arbiter))
        with ExitStack() as stack:
            for module,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),(socket,'getaddrinfo'),(subprocess,'Popen'),(time,'time'),(time,'monotonic'),(random,'random'),(uuid,'uuid4')):
                stack.enter_context(patch.object(module,name,side_effect=AssertionError('impure')))
            self.assertEqual(build(b).result_id,expected.result_id)
        self.assertEqual(before,tuple(asdict(x) for x in b));self.assertEqual(state,vars(arbiter))
        for name,value in vars(arbiter).items():
            if not name.startswith('__'):self.assertNotIsInstance(value,(dict,list,set,bytearray))
        tree=ast.parse(inspect.getsource(arbiter))
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names},{'hashlib','json'})
        self.assertEqual({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and not n.level},{'dataclasses','enum'})
    def test_103_no_authority_documented(self):
        self.no_terms('Action','Authority','Execution','ExecutionState','output_authority','next_action','planner','Microplan','previous_selected_option','switch_cost','minimum_hold','urgency','speech','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS')
        doc=(Path(arbiter.__file__).resolve().parent.parent/'DECISION_ARBITER_V01.md').read_text(encoding='utf-8')
        for text in REQUIRED_DOC:self.assertIn(text,doc)
    def test_104_guard_chain_and_preservation(self):
        root=Path(arbiter.__file__).resolve().parent.parent;path='coach02/decision_arbiter_v01.py';source=inspect.getsource(arbiter)
        self.assertEqual(import_violations(source,path),[]);self.assertEqual(consumer_violations(source,path),[])
        for module,symbols in CONTRACTS.items():
            for symbol in symbols:
                good='from .'+module+' import '+symbol
                self.assertEqual(import_violations(good,path),[])
                for bad in (good+' as C',good+'\nalias='+symbol,good+'\n'+symbol+'()', 'from .'+module+' import *','import coach02.'+module,"__import__('coach02."+module+"')"):
                    self.assertTrue(import_violations(bad,path))
                if module in ('decision_context_v02','option_safety_v02'):
                    self.assertEqual(consumer_violations(good,path),[])
                    self.assertTrue((consumer_violations if module=='option_safety_v02' else import_violations)(good,'coach02/arbitrary.py'))
        for bad in ('from .risk_evaluation import RiskConclusion','from .objective_outcome_relation_v01 import ObjectiveOutcomeRelationEvidence','from .decision_context_v02 import build_decision_context_v2','from .pairwise_tradeoff_v01 import OpportunityCostConclusion'):
            self.assertTrue(import_violations(bad,path))
        self.assertEqual(len(BASELINE_HASHES),133)
        for name,digest in BASELINE_HASHES:
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),digest)


CONTRACTS = {
    'decision_context_v02': {'DecisionContextV2','OptionDecisionContextV2','DecisionEvidencePresence'},
    'option_safety_v02': {'OptionSafetyEvaluationV2','OptionSafetyGateStatus'},
    'feasibility_gate_v01': {'FeasibilitySnapshotV1','OptionFeasibilityAssessmentV1','FeasibilityGateStatus'},
    'pairwise_tradeoff_v01': {'PairwiseTradeoffSnapshotV1','PairwiseTradeoffEvidenceV1','PairwiseTradeoffConclusion'},
}

REQUIRED_DOC = (
    'Decision Arbiter v0.1 selects a decision candidate; it does not execute an action.',
    'RISK_BLOCKING is an Arbiter exclusion signal under this fixed policy, not a global UNSAFE verdict.',
    'INFEASIBLE is an Arbiter exclusion signal, not a strategically BAD verdict.',
    'Any admission-indeterminate candidate blocks global selection.',
    'A single admitted candidate can be selected without pairwise evidence.',
    'With multiple admitted candidates, complete explicit pairwise coverage is required.',
    'Pairwise evidence is never inferred.',
    'A direct winner must have explicit direct advantage over every other admitted candidate.',
    'No transitivity, scoring, win counting or ranking is used.',
    'Cycles, TRADE_OFF and EQUIVALENT may produce NO_SELECTION.',
    'SELECTED does not authorize action, execution or communication.',
    'BLOCKER_BEFORE_HYSTERESIS','BLOCKER_BEFORE_EXECUTION','BLOCKER_BEFORE_ATTENTION_GATE',
    'BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION',
)

BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'),
 ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'),
 ('DECISION_CONTEXT_V02.md', 'CB3F1615EC752ADF523DDFB7FA5F3C5A5ECE4EBB3E35E55C19C9449C649507F3'),
 ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'),
 ('FEASIBILITY_GATE_V01.md', '9F40450123FA2D511764617500433B90929E1AA90D854BD03A493BCF38A6BDB2'),
 ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md',
  '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'),
 ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'),
 ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'),
 ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'),
 ('OBJECTIVE_OUTCOME_RELATION_V01.md', 'C466F62DB319AFB730EC7ACE4FA67039ABD9A5D22F12CB5794DABDB05D73C7C6'),
 ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'),
 ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'),
 ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'),
 ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'),
 ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'),
 ('OPTION_OUTCOME_EVIDENCE_V01.md', '61D6DAD163B724E2EB9BD6859BBD476E828AC3574D32A3FDDEC7B58F3E7BC53A'),
 ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'),
 ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'),
 ('PAIRWISE_TRADEOFF_V01.md', '7290D806C360314C9771EDF208C5F0BDE7A204AD02663FD22C91EC890AB1E465'),
 ('README.md', '72A60A5815269D2B2EAED3119841A4D57D26E6564F56BE104C6766F2FAAEF674'),
 ('RISK_EVALUATION_V01.md', '7A13246FD6D31A4A58C22AA9C1D209FF40727D79C8E90339620EDFDF2A878C32'),
 ('RISK_EVIDENCE_ASSEMBLY_V01.md', 'D44F8700089A390AC5CF6C670A78481A7340CF84A98A4766D194BF1D821B28B6'),
 ('RISK_EVIDENCE_ASSEMBLY_V02.md', '60A9C3B76C42C19B42EE94DA50A3A6C7E85400398502117200B3BF4F388D4D76'),
 ('RUNTIME_ADAPTER_V01.md', '723B87C9FA564CCB0527D6647F66D9752DA127082910C415D10838449E0051AE'),
 ('Run-Tests.cmd', 'C7D36F01B393C13362D8C6FB35D6C5FFDB9A81DC7AE086B61DE723974240136A'),
 ('SAFETY_EVIDENCE_V01.md', '160811B5829650324AD3353DD89C85ABAB878D3465B9261D0AFE840F284A8978'),
 ('STRATEGIC_COVERAGE_V01.md', '70AB604B5F34613F0BB306CC7E48FFB95CE1CA5419DB38427B91E8D4A8FB9181'),
 ('STRATEGIC_EVIDENCE_ASSEMBLY_V01.md', 'E2918BA287987AE36DF60BAD083CC45726998CFA97F082A626EB103D2F76FADD'),
 ('STRATEGIC_OBJECTIVE_CONTEXT_V01.md', 'CC437194EA74D601D78E3BAEC613D0376E0759690A74BB02EF94DA910916B3E7'),
 ('Start-Bot-Test.cmd', 'A967FFFC010A28FB3957C86B8B2AAF5DA7E98B40BA645B4DE63464FDBF3A11A4'),
 ('Start-Coach.cmd', '400EF821414BC0036D0BD29ED6382CDCC3477147604DAFCFAE488C7E329A8123'),
 ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'),
 ('THREAT_ABSENCE_OBSERVATION_V01.md', '6A37416C544E27A08DB0B8B1BC4D2D07136C833DE0A8674DD17EC79D9F9F0952'),
 ('THREAT_OBSERVATION_V01.md', '4633E7C0E920F790605DA27635A8D84ACA38DE59A52485CF16DEF1C7EDB8327B'),
 ('THREAT_REACHABILITY_V01.md', '180A3F7995AD367FD62DFCAA2175C03C6E1940C6C4BCFE80BF05C575DF0F2D42'),
 ('THREAT_RELEVANCE_V01.md', '51F9BEB03B612559A8EA350AB4C9FF5438C05A40EEAE5798CD40B5D1AD069666'),
 ('THREAT_STATE_ASSEMBLY_V01.md', 'CD7DDFAAFDBBA7A295616A1820FC267F46651C8B3AEB9ED445532B5C48E9766A'),
 ('VISIBILITY_COMPLETENESS_V01.md', 'E79A0B25695A39529E324F18792CA9C4CD31BDEB8EF8548C3FD351BB3DAFA7B3'),
 ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'),
 ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'),
 ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'),
 ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'),
 ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'),
 ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'),
 ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'),
 ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'),
 ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'),
 ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'),
 ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'),
 ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'),
 ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'),
 ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'),
 ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'),
 ('coach02/decision_context_v02.py', '3F07B86C7FABA28118C87B9646D2094A3A7A65C531A9D07255CC0B25BB9D74EF'),
 ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'),
 ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'),
 ('coach02/feasibility_gate_v01.py', 'C1C9D6BB47622F880F98DA5783008F7350B332B2992876EF68D9CB87993A1E13'),
 ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'),
 ('coach02/objective_outcome_relation_v01.py',
  '4CE5B30CA77F480B4D7C1C601E92FB096585E73B348C0E6C13BA81CE9E27DA2B'),
 ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'),
 ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'),
 ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'),
 ('coach02/option_outcome_evidence.py', '04D5F650484CD7B067A410E6C7A37892CE054BCC1319835D2C948A0594CA0325'),
 ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'),
 ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'),
 ('coach02/pairwise_tradeoff_v01.py', '93F1DC3A7736D290C47A84F8F14776CE20370C225E6BA3C82C3B7BEF121631C3'),
 ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'),
 ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'),
 ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'),
 ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'),
 ('coach02/risk_evidence_assembly_v02.py',
  '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'),
 ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'),
 ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'),
 ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'),
 ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'),
 ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'),
 ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'),
 ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'),
 ('coach02/strategic_objective_context.py',
  '1C217907B23E50C76DB80ED16902A5FBFE58921F5458D3F789FC087987A22A44'),
 ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'),
 ('coach02/threat_absence_observation.py',
  '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'),
 ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'),
 ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'),
 ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'),
 ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'),
 ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'),
 ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'),
 ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'),
 ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'),
 ('docs/CHANGES.md', 'A2DBFDAE75A11C1CFD601269E677D6F73F72A6017006D235AAD527A22F26BD9A'),
 ('docs/DECISIONS.md', '35C72BB38D35D8EE6A804BE9F3631047FB68E4A8E9538908F2259CD3917FB14A'),
 ('docs/TESTE_REAL.md', '335EC57D975ADB1FD046A358975DDF8831B67BC1F183C1AB4E576DAD675C06A8'),
 ('docs/VALIDATION.md', '7D5D0E515DE4D46E158DD955B2422F4B997A99000FCB531F61272FB06079A9C5'),
 ('docs/alpha01-reference/DECISIONS.md', '83D8C8EDD6386C958CB5A770746A1B7016C355596985DB44646EFF0B9ADA7571'),
 ('docs/alpha01-reference/VALIDATION.md', 'F29B09DD7427543EDA767B0FDBE68033C4A7980E6A9A9ADC3255189F274F619E'),
 ('docs/baseline-sha256.json', '3561C10064F6BAC12F032FCC51382EBD7D7FBEF70786C31E6C857DC386ECD40D'),
 ('docs/baseline-verification.json', '7326E1A33FB35E281A6A3211E85DFFD2A081BB22317C33DB7B7FAEE67E2E394B'),
 ('docs/test-results.txt', 'EE9BBD62124FCF6CB377DF2D79129BF0C927ACEAB2128AB247CABE92F0A7F2B7'),
 ('requirements-vision.txt', 'ECBC0244A6BC4646A912CF032F999724D47E22CB12CDBFAA231B600465F06711'),
 ('requirements.txt', 'CE972E5602F1BADF47B56CE597EBF4A3CBC516CA6C8979C95EE75C067D275840'),
 ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'),
 ('tests/test_alpha.py', '17BD7EBFF1558F062577A4677A472B0B3F65B85DC921253D6A9F5C2B705862D5'),
 ('tests/test_alpha02.py', '9F0839D676974435FA4AB3EE4887F9BE8DF876D07C271CADA4D0AFAA43A43C02'),
 ('tests/test_context_builder.py', '26A50D99710BAF117FA45AA570BA8BCDC38343835FED5EEF9C2618493E9AE701'),
 ('tests/test_decision_context_v02.py', '100702613FFB1038A884C7CE9C7F3648B98C3CA8A7457A7A1ED5D6A25E4775D9'),
 ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'),
 ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'),
 ('tests/test_feasibility_gate_v01.py', '13C1E9585E67BD00E08D24DFF4E243488F4CA9A183B003061F71F472CB3C0DDC'),
 ('tests/test_missing_threat_resolver.py',
  '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'),
 ('tests/test_objective_outcome_relation_v01.py',
  '4E683FE4C0BEE3F44C37EA47930DF4278AB2315BE54F2D9B78416507F5A7CC7A'),
 ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'),
 ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'),
 ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'),
 ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'),
 ('tests/test_option_outcome_evidence.py',
  '650A4F6FD90A1163A8D7DBEED12EAF121F4AB265C07620A9224E2D099E3FE8E8'),
 ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'),
 ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'),
 ('tests/test_pairwise_tradeoff_v01.py', '6EE9F784F0E20280EA4BE2A035133D0A82B0684DB1BE0B25C6C030E3DE1B2F7B'),
 ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'),
 ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'),
 ('tests/test_risk_evidence_assembly_v02.py',
  'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'),
 ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'),
 ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'),
 ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'),
 ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'),
 ('tests/test_strategic_objective_context.py',
  'D9E4442199B6FCC7F6DFAF3E867C7C1CA13FB9FBF2BCC4BA5F2BDC2BC580EA18'),
 ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'),
 ('tests/test_threat_absence_observation.py',
  'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'),
 ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'),
 ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'),
 ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'),
 ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'),
 ('tests/test_visibility_completeness.py',
  '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
