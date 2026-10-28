"""Sparse pair bindings, categorical costs and absence of selection authority."""
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

from coach02 import pairwise_tradeoff_v01 as tradeoff
from coach02.pairwise_tradeoff_v01 import (
    PairwiseTradeoffConclusion, OpportunityCostConclusion, PairwiseTradeoffClaim,
    PairwiseTradeoffEvidenceV1, PairwiseTradeoffSnapshotV1, build_pairwise_tradeoff_snapshot_v1,
)
from test_decision_context_v02 import (
    build as decision, sources, request, binding, objective_claim, outcome_claim,
    without_safety, StrategicObjectiveKnownness, SupportedRiskTolerance,
)
from test_objective_outcome_relation_v01 import (
    build as relations, claim as relation_claim, ObjectiveOutcomeRelation,
)
from test_feasibility_gate_v01 import import_violations


def fixture(names=('A', 'B', 'C'), dims=('x', 'y', 'z'), states=None, triple=None, req=None):
    upstream = sources(outcomes=tuple(outcome_claim(option_id=n, dimension_id=d) for n in names for d in dims)) if triple is None else triple
    context = decision(upstream, request(tuple(binding(option_id=n) for n in names)) if req is None else req)
    claims = tuple(relation_claim(context, option_id=o.option_id, dimension_id=row.dimension_id,
        relation=ObjectiveOutcomeRelation.SUPPORTS if states is None else states[o.option_id][i])
        for o in context.options for i, row in enumerate(o.outcome_evidences))
    snapshot = relations(context, claims)
    return context, snapshot


def claim(context=None, snapshot=None, **changes):
    if context is None: context, snapshot = fixture()
    values = dict(decision_context_id=context.decision_context_id, pairwise_context_id='P',
        left_option_id='A', right_option_id='B',
        left_relation_evidence_ids=tuple(r.evidence_id for r in snapshot.relations if r.option_id=='A'),
        right_relation_evidence_ids=tuple(r.evidence_id for r in snapshot.relations if r.option_id=='B'),
        conclusion=PairwiseTradeoffConclusion.LEFT_ADVANTAGE, basis_tick=context.decision_assembly_tick,
        source_id='pair-source', evidence_refs=('ref-b', 'ref-a'), assessment_policy_id='comparison-policy')
    values.update(changes)
    return PairwiseTradeoffClaim(**values)


def build(context=None, snapshot=None, claims=None):
    if context is None: context, snapshot = fixture()
    return build_pairwise_tradeoff_snapshot_v1(decision_context=context, relation_snapshot=snapshot,
        claims=(claim(context, snapshot),) if claims is None else claims)


def between(context, snapshot, left, right, **changes):
    return claim(context, snapshot, left_option_id=left, right_option_id=right,
        left_relation_evidence_ids=tuple(r.evidence_id for r in snapshot.relations if r.option_id==left),
        right_relation_evidence_ids=tuple(r.evidence_id for r in snapshot.relations if r.option_id==right), **changes)


class PairwiseTradeoffV1Tests(unittest.TestCase):
    def no_terms(self, *terms):
        tree = ast.parse(inspect.getsource(tradeoff))
        tokens = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        schema = {f.name for cls in (PairwiseTradeoffClaim, PairwiseTradeoffEvidenceV1, PairwiseTradeoffSnapshotV1) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(tokens | schema))

    def cost(self, conclusion, left, right):
        row = build(claims=(claim(conclusion=PairwiseTradeoffConclusion(conclusion)),)).comparisons[0]
        self.assertEqual((row.left_opportunity_cost.value, row.right_opportunity_cost.value), (left, right))
        return row

    def mismatch(self, **changes):
        context, snapshot = fixture()
        with self.assertRaises((TypeError, ValueError)): build(context, replace(snapshot, **changes), ())

    def test_001_pairwise_enum(self):
        self.assertEqual({n:v.value for n,v in PairwiseTradeoffConclusion.__members__.items()},
                         {n:n for n in ('LEFT_ADVANTAGE','RIGHT_ADVANTAGE','TRADE_OFF','EQUIVALENT','INDETERMINATE')})
        class Other(str, Enum): LEFT_ADVANTAGE='LEFT_ADVANTAGE'
        for x in ('LEFT_ADVANTAGE', Other.LEFT_ADVANTAGE, None):
            with self.assertRaises(TypeError): claim(conclusion=x)
    def test_002_cost_enum(self):
        self.assertEqual({n:v.value for n,v in OpportunityCostConclusion.__members__.items()},
                         {n:n for n in ('ESTABLISHED','NOT_ESTABLISHED','INDETERMINATE')})
    def test_003_claim_frozen_and_revalidated(self):
        c=claim()
        with self.assertRaises(FrozenInstanceError): c.source_id='changed'
        object.__setattr__(c,'conclusion','LEFT_ADVANTAGE')
        with self.assertRaises(TypeError): build(claims=(c,))
    def test_004_evidence_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().comparisons[0].left_option_id='x'
    def test_005_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().comparisons=()
    def test_006_concrete_identifiers(self):
        class Text(str): pass
        for f in fields(claim()):
            if f.type is str:
                for invalid in ('',' \t',None,False,1,Text('opaque')):
                    with self.subTest(field=f.name), self.assertRaises(ValueError): claim(**{f.name:invalid})
    def test_007_no_trim_refs_preserved(self):
        c=claim(pairwise_context_id=' /β ',source_id=' source ',assessment_policy_id=' policy ',evidence_refs=(' ref ',))
        row=build(claims=(c,)).comparisons[0]
        self.assertEqual((row.pairwise_context_id,row.source_id,row.assessment_policy_id,row.evidence_refs),(' /β ',' source ',' policy ',(' ref ',)))
    def test_008_distinct_options(self):
        with self.assertRaisesRegex(ValueError,'distinct_options_required'): claim(right_option_id='A')
    def test_009_exact_bundle_tuples(self):
        class Tuple(tuple): pass
        class Text(str): pass
        for field in ('left_relation_evidence_ids','right_relation_evidence_ids'):
            for invalid in ([],['id'],Tuple(('id',)),None):
                with self.assertRaises(TypeError): claim(**{field:invalid})
            for invalid in (('',),(' ',),(1,),(Text('id'),)):
                with self.assertRaises(ValueError): claim(**{field:invalid})
    def test_010_empty_left_reject(self):
        with self.assertRaisesRegex(ValueError,'nonempty_bundle_required'): claim(left_relation_evidence_ids=())
    def test_011_empty_right_reject(self):
        with self.assertRaisesRegex(ValueError,'nonempty_bundle_required'): claim(right_relation_evidence_ids=())
    def test_012_duplicate_bundle_ids(self):
        for field in ('left_relation_evidence_ids','right_relation_evidence_ids'):
            with self.assertRaises(ValueError): claim(**{field:('id','id')})
        c=claim();object.__setattr__(c,'left_relation_evidence_ids',())
        with self.assertRaises(ValueError): build(claims=(c,))
    def test_013_tick_exact_int(self):
        class Integer(int): pass
        for value in (True,False,1.0,'1',Integer(1),None):
            with self.assertRaises(TypeError): claim(basis_tick=value)
        self.assertEqual(claim(basis_tick=0).basis_tick,0)
    def test_014_negative_tick(self):
        with self.assertRaises(ValueError): claim(basis_tick=-1)
    def test_015_exact_refs(self):
        class Tuple(tuple): pass
        for refs in ([],None,Tuple(('r',))):
            with self.assertRaises(TypeError): claim(evidence_refs=refs)
        self.assertEqual(build(claims=(claim(evidence_refs=()),)).comparisons[0].evidence_refs,())
    def test_016_duplicate_refs(self):
        with self.assertRaises(ValueError): claim(evidence_refs=('r','r'))
        a=build(claims=(claim(evidence_refs=('a','b')),));b=build(claims=(claim(evidence_refs=('b','a')),))
        self.assertNotEqual(a.snapshot_id,b.snapshot_id)
    def test_017_left_table(self): self.cost('LEFT_ADVANTAGE','NOT_ESTABLISHED','ESTABLISHED')
    def test_018_right_table(self): self.cost('RIGHT_ADVANTAGE','ESTABLISHED','NOT_ESTABLISHED')
    def test_019_tradeoff_table(self): self.cost('TRADE_OFF','ESTABLISHED','ESTABLISHED')
    def test_020_equivalent_table(self): self.cost('EQUIVALENT','NOT_ESTABLISHED','NOT_ESTABLISHED')
    def test_021_indeterminate_table(self): self.cost('INDETERMINATE','INDETERMINATE','INDETERMINATE')
    def test_022_not_established_not_zero(self):
        row=self.cost('EQUIVALENT','NOT_ESTABLISHED','NOT_ESTABLISHED')
        self.assertNotEqual(row.left_opportunity_cost.value,'ZERO_COST')
        self.no_terms('ZERO_COST','NO_OPPORTUNITY_COST_EXISTS','numeric_cost','cost_units')
    def test_023_absence_not_indeterminate(self):
        absent=build(claims=());explicit=build(claims=(claim(conclusion=PairwiseTradeoffConclusion.INDETERMINATE),))
        self.assertEqual(absent.comparisons,());self.assertEqual(len(explicit.comparisons),1)
        self.assertNotEqual(absent.snapshot_id,explicit.snapshot_id)
    def test_024_sparse_pairs(self):
        context,snapshot=fixture()
        self.assertEqual(len(context.options),3);self.assertEqual(len(build(context,snapshot).comparisons),1)
    def test_025_no_automatic_pairs_and_empty_cases(self):
        for names in ((),('A',),('A','B','C','D')):
            context,snapshot=fixture(names=names)
            self.assertEqual(build(context,snapshot,()).comparisons,())
        context,snapshot=fixture();empty=relations(context,())
        self.assertEqual(build(context,empty,()).comparisons,())
        with self.assertRaises(ValueError): build(context,empty,(claim(context,snapshot),))
    def test_026_foreign_context(self):
        with self.assertRaisesRegex(ValueError,'foreign_decision_context'): build(claims=(claim(decision_context_id='other'),))
        self.mismatch(decision_context_id='other')
    def test_027_foreign_left(self):
        with self.assertRaisesRegex(ValueError,'foreign_option'): build(claims=(claim(left_option_id='other'),))
    def test_028_foreign_right(self):
        with self.assertRaisesRegex(ValueError,'foreign_option'): build(claims=(claim(right_option_id='other'),))
    def test_029_forged_self_pair(self):
        c=claim();object.__setattr__(c,'right_option_id','A')
        with self.assertRaisesRegex(ValueError,'distinct_options_required'): build(claims=(c,))
    def test_030_lineage_exact_and_defensive_types(self):
        self.mismatch(decision_context_object_id='other');self.mismatch(ruleset='other')
        context,snapshot=fixture();c=claim(context,snapshot)
        for original in (context,snapshot,c,snapshot.relations[0],context.options[0]):
            Child=type('Child',(type(original),),{})
            child=Child(**{f.name:getattr(original,f.name) for f in fields(original)})
            ctx=child if original is context else replace(context,options=(child,*context.options[1:])) if original is context.options[0] else context
            snap=child if original is snapshot else replace(snapshot,relations=(child,*snapshot.relations[1:])) if original is snapshot.relations[0] else snapshot
            with self.assertRaises(TypeError): build(ctx,snap,(child,) if original is c else (c,))
        class Tuple(tuple): pass
        for invalid in ([],Tuple((c,)),(object(),)):
            with self.assertRaises(TypeError): build(context,snapshot,invalid)
        with self.assertRaises(TypeError): build(context,replace(snapshot,relations=list(snapshot.relations)),())
        with self.assertRaises(ValueError): build(context,replace(snapshot,relations=snapshot.relations*2),())
        with self.assertRaises(ValueError): build(replace(context,options=context.options*2),snapshot,())
    def test_031_timeline_exact(self): self.mismatch(timeline_id='other')
    def test_032_clock_exact(self): self.mismatch(selected_clock_id='other')
    def test_033_snapshot_tick_exact(self):
        context,snapshot=fixture()
        self.mismatch(evaluated_at_tick=context.decision_assembly_tick+1)
        self.mismatch(evaluated_at_tick=True)
    def test_034_old_claim_tick(self):
        c=claim()
        with self.assertRaisesRegex(ValueError,'exact_decision_tick_required'): build(claims=(replace(c,basis_tick=c.basis_tick-1),))
    def test_035_future_claim_tick(self):
        c=claim()
        with self.assertRaisesRegex(ValueError,'exact_decision_tick_required'): build(claims=(replace(c,basis_tick=c.basis_tick+1),))
    def test_036_no_objective_empty_valid(self):
        for objs in ((),(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN,objective_id=None),)):
            context=decision(sources(objectives=objs),request((binding(option_id='A'),binding(option_id='B'))))
            snapshot=relations(context,())
            result=build(context,snapshot,());self.assertIsNone(result.objective_id);self.assertEqual(result.comparisons,())
    def test_037_no_objective_rejects_claim(self):
        context=decision(sources(objectives=()),request((binding(option_id='A'),binding(option_id='B'))))
        with self.assertRaisesRegex(ValueError,'concrete_objective_required'): build(context,relations(context,()),(claim(),))
        for field in ('objective_id','objective_context_id','objective_horizon_id'): self.mismatch(**{field:'foreign'})
    def test_038_missing_left_evidence(self):
        with self.assertRaisesRegex(ValueError,'missing_relation_evidence'): build(claims=(claim(left_relation_evidence_ids=('missing',)),))
    def test_039_missing_right_evidence(self):
        with self.assertRaisesRegex(ValueError,'missing_relation_evidence'): build(claims=(claim(right_relation_evidence_ids=('missing',)),))
    def test_040_wrong_side_or_third_option(self):
        context,snapshot=fixture();c=claim(context,snapshot)
        third=tuple(r.evidence_id for r in snapshot.relations if r.option_id=='C')
        for change in ({'left_relation_evidence_ids':c.right_relation_evidence_ids},{'right_relation_evidence_ids':c.left_relation_evidence_ids},{'left_relation_evidence_ids':third}):
            with self.assertRaisesRegex(ValueError,'wrong_side_relation_evidence'): build(context,snapshot,(replace(c,**change),))
    def test_041_exact_left_objects(self):
        context,snapshot=fixture();row=build(context,snapshot).comparisons[0]
        by_id={r.evidence_id:r for r in snapshot.relations}
        self.assertTrue(all(r is by_id[r.evidence_id] for r in row.left_relation_evidences))
    def test_042_exact_right_objects(self):
        context,snapshot=fixture();row=build(context,snapshot).comparisons[0]
        by_id={r.evidence_id:r for r in snapshot.relations}
        self.assertTrue(all(r is by_id[r.evidence_id] for r in row.right_relation_evidences))
    def test_043_exact_claim_and_nonmutation(self):
        context,snapshot=fixture();c=claim(context,snapshot);before=(asdict(context),asdict(snapshot),asdict(c))
        self.assertIs(build(context,snapshot,(c,)).comparisons[0].base_claim,c)
        self.assertEqual((asdict(context),asdict(snapshot),asdict(c)),before)
    def test_044_multiple_left_rows(self): self.assertEqual(len(build().comparisons[0].left_relation_evidences),3)
    def test_045_multiple_right_rows(self): self.assertEqual(len(build().comparisons[0].right_relation_evidences),3)
    def test_046_unreferenced_rows_allowed(self):
        context,snapshot=fixture();c=claim(context,snapshot)
        result=build(context,snapshot,(replace(c,left_relation_evidence_ids=c.left_relation_evidence_ids[:1]),))
        self.assertEqual(len(snapshot.relations),9);self.assertEqual(len(result.comparisons[0].left_relation_evidences),1)
    def test_047_no_auto_bundles(self):
        c=claim();one=replace(c,left_relation_evidence_ids=c.left_relation_evidence_ids[:1],right_relation_evidence_ids=c.right_relation_evidence_ids[-1:])
        row=build(claims=(one,)).comparisons[0]
        self.assertEqual((len(row.left_relation_evidences),len(row.right_relation_evidences)),(1,1))
    def test_048_unordered_pair_unique(self):
        c=claim()
        for other in (c,replace(c,source_id='other'),replace(c,assessment_policy_id='other'),replace(c,conclusion=PairwiseTradeoffConclusion.RIGHT_ADVANTAGE)):
            with self.assertRaisesRegex(ValueError,'duplicate_unordered_pair'): build(claims=(c,other))
    def test_049_reverse_duplicate(self):
        context,snapshot=fixture();forward=between(context,snapshot,'A','B');reverse=between(context,snapshot,'B','A')
        with self.assertRaisesRegex(ValueError,'duplicate_unordered_pair'): build(context,snapshot,(forward,reverse))
        row=build(context,snapshot,(reverse,)).comparisons[0]
        self.assertEqual((row.left_option_id,row.right_option_id),('B','A'))
    def test_050_distinct_contexts(self):
        c=claim();result=build(claims=(c,replace(c,pairwise_context_id='other')))
        self.assertEqual(len(result.comparisons),2)
    def test_051_no_context_reconciliation(self):
        context,snapshot=fixture()
        a=between(context,snapshot,'A','B',pairwise_context_id='X')
        b=between(context,snapshot,'B','A',pairwise_context_id='Y')
        self.assertEqual(len(build(context,snapshot,(a,b)).comparisons),2)
    def test_052_caller_conclusion_not_recomputed(self):
        states={'A':(ObjectiveOutcomeRelation.SUPPORTS,ObjectiveOutcomeRelation.OPPOSES,ObjectiveOutcomeRelation.UNKNOWN),
                'B':(ObjectiveOutcomeRelation.SUPPORTS,)*3,'C':(ObjectiveOutcomeRelation.NEUTRAL,)*3}
        context,snapshot=fixture(states=states)
        for value in PairwiseTradeoffConclusion:
            self.assertIs(build(context,snapshot,(claim(context,snapshot,conclusion=value),)).comparisons[0].conclusion,value)
    def test_053_support_counts_ignored(self):
        c=claim();c=replace(c,left_relation_evidence_ids=c.left_relation_evidence_ids[:1])
        self.assertIs(build(claims=(c,)).comparisons[0].conclusion,PairwiseTradeoffConclusion.LEFT_ADVANTAGE)
    def test_054_opposition_counts_ignored(self):
        states={'A':(ObjectiveOutcomeRelation.OPPOSES,)*3,'B':(ObjectiveOutcomeRelation.SUPPORTS,)*3,'C':(ObjectiveOutcomeRelation.UNKNOWN,)*3}
        context,snapshot=fixture(states=states)
        c=claim(context,snapshot,conclusion=PairwiseTradeoffConclusion.EQUIVALENT)
        self.assertIs(build(context,snapshot,(c,)).comparisons[0].conclusion,PairwiseTradeoffConclusion.EQUIVALENT)
    def test_055_no_relation_ordering(self): self.no_terms('SUPPORTS','OPPOSES','NEUTRAL')
    def test_056_no_relation_enum_consumption(self): self.no_terms('ObjectiveOutcomeRelation','relation')
    def test_057_no_majority(self): self.no_terms('majority','support_count','opposition_count')
    def test_058_no_voting(self): self.no_terms('vote','votes','Counter','count')
    def test_059_no_weighted_sum(self): self.no_terms('weight','weights','sum','weighted')
    def test_060_no_scalar_score(self): self.no_terms('score','points','scalar')
    def test_061_no_utility(self): self.no_terms('utility','reward')
    def test_062_no_expected_value(self): self.no_terms('expected_value','future_value')
    def test_063_no_probability(self): self.no_terms('probability','likelihood')
    def test_064_no_confidence(self): self.no_terms('confidence','Confidence')
    def test_065_no_magnitude(self): self.no_terms('magnitude','strength','numeric_cost')
    def test_066_tradeoff_not_tie(self):
        row=self.cost('TRADE_OFF','ESTABLISHED','ESTABLISHED');self.assertNotEqual(row.conclusion.value,'TIE')
        self.no_terms('tie','indifferent','equally_good')
    def test_067_equivalent_local_only(self):
        context,snapshot=fixture();ab=between(context,snapshot,'A','B',conclusion=PairwiseTradeoffConclusion.EQUIVALENT)
        bc=between(context,snapshot,'B','C',conclusion=PairwiseTradeoffConclusion.EQUIVALENT)
        self.assertEqual(len(build(context,snapshot,(ab,bc)).comparisons),2)
        self.no_terms('equivalence_class','globally_equivalent')
    def test_068_indeterminate_not_tie(self):
        row=self.cost('INDETERMINATE','INDETERMINATE','INDETERMINATE');self.assertNotEqual(row.conclusion.value,'TIE')
        self.no_terms('BAD','SAFE','AVOID','UNUSABLE')
    def test_069_left_not_selected(self):
        self.assertIs(build().comparisons[0].conclusion,PairwiseTradeoffConclusion.LEFT_ADVANTAGE)
        self.no_terms('SELECT_LEFT','selected_left')
    def test_070_right_not_selected(self):
        self.cost('RIGHT_ADVANTAGE','ESTABLISHED','NOT_ESTABLISHED');self.no_terms('SELECT_RIGHT','selected_right')
    def test_071_no_transitivity_cycles_allowed(self):
        context,snapshot=fixture();claims=tuple(between(context,snapshot,l,r) for l,r in (('A','B'),('B','C'),('C','A')))
        self.assertEqual(len(build(context,snapshot,claims).comparisons),3)
        self.no_terms('transitive','transitivity')
    def test_072_no_inferred_ac(self):
        context,snapshot=fixture();claims=(between(context,snapshot,'A','B'),between(context,snapshot,'B','C'))
        result=build(context,snapshot,claims)
        self.assertEqual({(r.left_option_id,r.right_option_id) for r in result.comparisons},{('A','B'),('B','C')})
    def test_073_no_graph_closure(self): self.no_terms('closure','topological_sort','graph','combinations','product')
    def test_074_no_ranking(self): self.no_terms('rank','ranking','ranked','best','worst')
    def test_075_no_winner(self): self.no_terms('winner','loser','dominant_option','tournament')
    def test_076_no_condorcet(self): self.no_terms('condorcet','Condorcet','win_count','loss_count')
    def test_077_no_elo_points(self): self.no_terms('elo','Elo','points','rating')
    def test_078_no_aggregate_cost(self): self.no_terms('aggregate_cost','average_cost','maximum_cost','minimum_cost')
    def test_079_no_total_cost(self): self.no_terms('total_opportunity_cost','total_cost','cost_score')
    def test_080_no_feasible_filtering(self):
        from test_feasibility_gate_v01 import build as feasibility, policy, claim as requirement, FeasibilityRequirementState
        context,snapshot=fixture();before=build(context,snapshot)
        result=feasibility(context,policies=(policy(context,option_id='A'),),claims=(requirement(context,option_id='A',state=FeasibilityRequirementState.UNSATISFIED),))
        self.assertEqual(result.assessments[0].status.value,'INFEASIBLE')
        self.assertEqual(build(context,snapshot).snapshot_id,before.snapshot_id)
    def test_081_no_feasibility_import(self): self.no_terms('FeasibilitySnapshotV1','FeasibilityGateStatus','build_feasibility_snapshot_v1')
    def test_082_no_safety_branching(self):
        context,snapshot=fixture(names=('option-A','B','C'))
        c=between(context,snapshot,'option-A','B')
        option=next(o for o in context.options if o.option_id=='option-A')
        self.assertEqual(option.safety_evaluation.gate_status.value,'RISK_BLOCKING')
        self.assertIs(build(context,snapshot,(c,)).comparisons[0].conclusion,PairwiseTradeoffConclusion.LEFT_ADVANTAGE)
        self.no_terms('safety_presence','safety_evaluation','gate_status')
    def test_083_no_safety_import(self): self.no_terms('OptionSafetySnapshotV2','OptionSafetyGateStatus','RiskConclusion')
    def test_084_no_action(self): self.no_terms('action','Action','authority','Authority')
    def test_085_no_recommendation(self): self.no_terms('recommended','recommendation','choose','selected')
    def test_086_no_execution(self): self.no_terms('ExecutionState','execution','started','committed','completed','aborted')
    def test_087_no_commitment_reversibility(self): self.no_terms('commitment','reversible','irreversible','abort_cost','switch_cost')
    def test_088_no_attention(self): self.no_terms('DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS','urgency','speech','output_authority','cognitive_load')
    def test_089_generic_roles(self):
        for role in ('Carry','Mid','Offlane','Support 4','Support 5'):
            context,snapshot=fixture(names=(role,'Other'),dims=('opaque',))
            row=build(context,snapshot,(between(context,snapshot,role,'Other'),)).comparisons[0]
            self.assertEqual(row.left_option_id,role)
    def test_090_opaque_dota_names(self):
        for dim in ('gold','Roshan','hero.spell',' vision:/β '):
            context,snapshot=fixture(dims=(dim,))
            self.assertIs(build(context,snapshot).comparisons[0].conclusion,PairwiseTradeoffConclusion.LEFT_ADVANTAGE)
    def test_091_ruleset_api_and_inherited_headers(self):
        context,snapshot=fixture();result=build(context,snapshot)
        self.assertEqual(result.ruleset,'decision.pairwise_tradeoff.v1')
        self.assertEqual((result.timeline_id,result.selected_clock_id,result.evaluated_at_tick),(context.timeline_id,context.selected_clock_id,context.decision_assembly_tick))
        params=inspect.signature(build_pairwise_tradeoff_snapshot_v1).parameters
        self.assertEqual(tuple(params),('decision_context','relation_snapshot','claims'))
        self.assertTrue(all(p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty for p in params.values()))
    def test_092_evidence_identity(self):
        row=build().comparisons[0];content=asdict(row)
        for field in ('left_relation_evidence_ids','right_relation_evidence_ids'):content['base_claim'][field]=sorted(content['base_claim'][field])
        digest=hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(row.evidence_id,'decision.pairwise_tradeoff.v1:evidence:'+digest)
    def test_093_snapshot_identity(self):
        result=build();content=asdict(result)
        for row in content['comparisons']:
            for field in ('left_relation_evidence_ids','right_relation_evidence_ids'):row['base_claim'][field]=sorted(row['base_claim'][field])
        digest=hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id,'decision.pairwise_tradeoff.v1:snapshot:'+digest)
        self.assertEqual(result.snapshot_id,build().snapshot_id)
    def test_094_claim_permutation(self):
        from itertools import permutations
        context,snapshot=fixture();claims=(between(context,snapshot,'A','B'),between(context,snapshot,'B','C'),between(context,snapshot,'C','A'))
        expected=build(context,snapshot,claims).snapshot_id
        for perm in permutations(claims):self.assertEqual(build(context,snapshot,perm).snapshot_id,expected)
    def test_095_bundle_order_identity_and_original_tuple(self):
        context,snapshot=fixture();c=claim(context,snapshot);reversed_claim=replace(c,left_relation_evidence_ids=c.left_relation_evidence_ids[::-1],right_relation_evidence_ids=c.right_relation_evidence_ids[::-1])
        a=build(context,snapshot,(c,));b=build(context,snapshot,(reversed_claim,))
        self.assertEqual(a.snapshot_id,b.snapshot_id);self.assertEqual(a.comparisons[0].evidence_id,b.comparisons[0].evidence_id)
        self.assertIs(b.comparisons[0].base_claim,reversed_claim)
        self.assertEqual(b.comparisons[0].base_claim.left_relation_evidence_ids,c.left_relation_evidence_ids[::-1])
        self.assertEqual(tuple(r.evidence_id for r in b.comparisons[0].left_relation_evidences),tuple(sorted(c.left_relation_evidence_ids)))
    def test_096_canonical_comparison_order(self):
        context,snapshot=fixture();claims=(between(context,snapshot,'C','B',pairwise_context_id='X'),between(context,snapshot,'B','A',pairwise_context_id='X'),between(context,snapshot,'C','A',pairwise_context_id='A'))
        rows=build(context,snapshot,claims).comparisons
        self.assertEqual(tuple((r.pairwise_context_id,r.left_option_id,r.right_option_id) for r in rows),(('A','C','A'),('X','B','A'),('X','C','B')))
    def test_097_conclusion_identity(self):
        self.assertEqual(len({build(claims=(claim(conclusion=c),)).snapshot_id for c in PairwiseTradeoffConclusion}),5)
    def test_098_policy_and_provenance_identity(self):
        a=build()
        for change in ({'assessment_policy_id':'other'},{'source_id':'other'},{'evidence_refs':('other',)},{'pairwise_context_id':'other'}):
            self.assertNotEqual(a.snapshot_id,build(claims=(claim(**change),)).snapshot_id)
    def test_099_bundle_membership_identity(self):
        c=claim();b=replace(c,left_relation_evidence_ids=c.left_relation_evidence_ids[:1])
        self.assertNotEqual(build(claims=(c,)).comparisons[0].evidence_id,build(claims=(b,)).comparisons[0].evidence_id)
    def test_100_context_lineage_identity(self):
        context,snapshot=fixture();other_context,other_snapshot=fixture(req=request(tuple(binding(option_id=n) for n in ('A','B','C')),context_binding_policy_id='other'))
        a=build(context,snapshot);b=build(other_context,other_snapshot)
        self.assertNotEqual(a.snapshot_id,b.snapshot_id)
        self.assertEqual(a.decision_context_object_id,context.context_id)
        with self.assertRaisesRegex(ValueError,'exact_relation_lineage_required'):build(other_context,snapshot,())
    def test_101_relation_snapshot_identity(self):
        context,snapshot=fixture();short=replace(snapshot,relations=tuple(r for r in snapshot.relations if r.option_id!='C'))
        a=build(context,snapshot);b=build(context,short)
        self.assertNotEqual(a.snapshot_id,b.snapshot_id);self.assertEqual(a.comparisons[0].evidence_id,b.comparisons[0].evidence_id)
        self.assertEqual(a.relation_snapshot_id,snapshot.snapshot_id)
    def test_102_purity_and_boundary_imports(self):
        import builtins,io,os,socket,subprocess,time,random,uuid
        context,snapshot=fixture();c=claim(context,snapshot);expected=build(context,snapshot,(c,));before=dict(vars(tradeoff))
        with ExitStack() as stack:
            for module,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),(socket,'getaddrinfo'),(subprocess,'Popen'),(time,'time'),(time,'monotonic'),(random,'random'),(uuid,'uuid4')):
                stack.enter_context(patch.object(module,name,side_effect=AssertionError('impure')))
            self.assertEqual(build(context,snapshot,(c,)).snapshot_id,expected.snapshot_id)
        self.assertEqual(before,vars(tradeoff))
        for name,value in vars(tradeoff).items():
            if not name.startswith('__'):self.assertNotIsInstance(value,(dict,list,set,bytearray))
        tree=ast.parse(inspect.getsource(tradeoff))
        self.assertEqual({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)},{'dataclasses','enum','decision_context_v02','objective_outcome_relation_v01'})
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names},{'hashlib','json'})
    def test_103_guard_exactness_documentation(self):
        path='coach02/pairwise_tradeoff_v01.py';root=Path(tradeoff.__file__).resolve().parent.parent
        self.assertEqual(import_violations(inspect.getsource(tradeoff),path),[])
        for module,symbols in {'decision_context_v02':('DecisionContextV2','OptionDecisionContextV2'),
                               'objective_outcome_relation_v01':('ObjectiveOutcomeRelationSnapshotV1','ObjectiveOutcomeRelationEvidence')}.items():
            for symbol in symbols:
                good='from .'+module+' import '+symbol
                self.assertEqual(import_violations(good,path),[])
                self.assertTrue(import_violations(good,'coach02/arbitrary.py'))
                for bad in (good+' as C',good+'\nalias='+symbol,good+'\n'+symbol+'()',
                            'from .'+module+' import *','import coach02.'+module,"__import__('coach02."+module+"')"):
                    self.assertTrue(import_violations(bad,path))
        for bad in ('from .decision_context_v02 import build_decision_context_v2',
                    'from .objective_outcome_relation_v01 import ObjectiveOutcomeRelation',
                    'from .objective_outcome_relation_v01 import build_objective_outcome_relation_snapshot_v1',
                    'from .feasibility_gate_v01 import FeasibilitySnapshotV1',
                    'from .option_safety_v02 import OptionSafetySnapshotV2'):
            self.assertTrue(import_violations(bad,path))
        doc=(root/'PAIRWISE_TRADEOFF_V01.md').read_text(encoding='utf-8')
        for text in ('Pairwise Trade-off v0.1 compares explicit evidence bundles; it does not rank the candidate set.',
            'LEFT_ADVANTAGE does not mean SELECT_LEFT.','RIGHT_ADVANTAGE does not mean SELECT_RIGHT.',
            'TRADE_OFF is not a tie.','EQUIVALENT is local to the explicit comparison and does not mean globally equivalent options.',
            'NOT_ESTABLISHED opportunity cost does not mean zero opportunity cost.',
            'Missing pairwise evidence is distinct from explicit INDETERMINATE.','No pair is automatically generated.',
            'No transitivity or graph closure occurs.','Safety and Feasibility remain independent.',
            'BLOCKER_BEFORE_DECISION_ARBITER','BLOCKER_BEFORE_EXECUTION','BLOCKER_BEFORE_ATTENTION_GATE','BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION'):
            self.assertIn(text,doc)
    def test_104_previous_files_preserved(self):
        root=Path(tradeoff.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES),130)
        for name,expected in BASELINE_HASHES:
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),expected)


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
