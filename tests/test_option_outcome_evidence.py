"""Contract and adversarial tests for supplied prospective directional evidence."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
from enum import Enum
import hashlib
import inspect
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import option_outcome_evidence as outcome
from coach02.option_outcome_evidence import (
    OutcomeChange, OptionOutcomeClaim, OptionOutcomeEvidence, OptionOutcomeSnapshot,
    build_option_outcome_evidence,
)


def claim(**changes):
    values=dict(option_id='option',outcome_context_id='context',dimension_id='dimension',
                baseline_id='baseline',horizon_id='horizon',change=OutcomeChange.INCREASE,
                basis_tick=4,source_id='source',evidence_refs=('ref-b','ref-a'),
                assessment_policy_id='assessment.v1')
    values.update(changes)
    return OptionOutcomeClaim(**values)


def build(claims=None,**changes):
    values=dict(timeline_id='timeline',selected_clock_id='clock',evaluated_at_tick=5,
                claims=(claim(),) if claims is None else claims)
    values.update(changes)
    return build_option_outcome_evidence(**values)


class OptionOutcomeEvidenceTests(unittest.TestCase):
    def identifier(self,name):
        class Text(str): pass
        for value in ('',' \t\n',None,0,False,Text('text')):
            with self.subTest(value=value),self.assertRaises((TypeError,ValueError)):
                claim(**{name:value})
        value='  opaque:/Î² '+name+'  '
        source=claim(**{name:value})
        self.assertEqual(getattr(build((source,)).evidences[0],name),value)

    def preserved(self,name,value):
        source=claim(**{name:value}); result=build((source,)); row=result.evidences[0]
        self.assertEqual(getattr(row,name),value)
        self.assertEqual(getattr(row.base_claim,name),value)

    def changed(self,field,value,header=False):
        original=build()
        other=build(**{field:value}) if header else build((claim(**{field:value}),))
        self.assertNotEqual(original.snapshot_id,other.snapshot_id)

    def tokens(self):
        tree=ast.parse(inspect.getsource(outcome))
        return {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)} | {
            n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and type(n.value) is str}

    def absent_terms(self,*terms):
        self.assertTrue(set(terms).isdisjoint(self.tokens()))
        names={f.name for c in (OptionOutcomeClaim,OptionOutcomeEvidence,OptionOutcomeSnapshot) for f in fields(c)}
        self.assertTrue(set(terms).isdisjoint(names))

    def imports(self):
        tree=ast.parse(inspect.getsource(outcome))
        return {('.'*n.level+(n.module or '')) for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}

    def forbidden_imports(self,*names):
        self.assertEqual(self.imports(),{'dataclasses','enum','hashlib','json'})
        self.assertFalse(any(any(name in imported for name in names) for imported in self.imports()))

    def pure(self,targets):
        source=(claim(),claim(option_id='other',change=OutcomeChange.UNKNOWN))
        before=asdict(build(source))
        def denied(*a,**k): raise AssertionError('forbidden side effect')
        with ExitStack() as stack:
            for module,name in targets:stack.enter_context(patch.object(module,name,denied))
            result=build(source)
            identity=result.snapshot_id
        self.assertEqual(asdict(result),before)
        self.assertEqual(identity,build(source).snapshot_id)

    def test_001_exact_change_enum(self):
        self.assertEqual({x.name:x.value for x in OutcomeChange},
                         {x:x for x in ('INCREASE','DECREASE','UNCHANGED','UNKNOWN')})
        self.assertEqual({n for n,v in vars(outcome).items() if isinstance(v,type) and issubclass(v,Enum) and v.__module__==outcome.__name__},{'OutcomeChange'})

    def test_002_no_preference_vocabulary(self):
        self.absent_terms('GOOD','BAD','BETTER','WORSE','FAVORABLE','UNFAVORABLE','PREFERRED','DOMINATED','OPTIMAL','SUBOPTIMAL','RECOMMENDED','AVOID')

    def test_003_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError):claim().option_id='changed'

    def test_004_evidence_frozen(self):
        with self.assertRaises(FrozenInstanceError):build().evidences[0].change=OutcomeChange.UNKNOWN

    def test_005_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError):build().evaluated_at_tick=9

    def test_006_option_identity(self):self.identifier('option_id')
    def test_007_outcome_context_identity(self):self.identifier('outcome_context_id')
    def test_008_dimension_identity(self):self.identifier('dimension_id')
    def test_009_baseline_identity(self):self.identifier('baseline_id')
    def test_010_horizon_identity(self):self.identifier('horizon_id')
    def test_011_source_identity(self):self.identifier('source_id')
    def test_012_policy_identity(self):self.identifier('assessment_policy_id')

    def test_013_concrete_change_and_boundary_revalidation(self):
        class Other(str,Enum): INCREASE='INCREASE'
        for value in ('INCREASE',Other.INCREASE,None,1):
            with self.subTest(value=value),self.assertRaises(TypeError):claim(change=value)
        source=claim();object.__setattr__(source,'change','INCREASE')
        with self.assertRaises(TypeError):build((source,))
        class Child(OptionOutcomeClaim):pass
        child=Child(**asdict(claim()))
        with self.assertRaises(TypeError):build((child,))
        with self.assertRaises(TypeError):build((object(),))

    def test_014_exact_claim_tuple(self):
        class Tuple(tuple):pass
        for value in ([claim()],iter((claim(),)),Tuple((claim(),)),None):
            with self.subTest(value=type(value)),self.assertRaises(TypeError):
                build_option_outcome_evidence(timeline_id='t',selected_clock_id='c',evaluated_at_tick=5,claims=value)

    def test_015_exact_reference_tuple(self):
        class Tuple(tuple):pass
        for value in (['r'],iter(('r',)),Tuple(('r',)),'r',None):
            with self.subTest(value=type(value)),self.assertRaises(TypeError):claim(evidence_refs=value)
        self.assertEqual(build((claim(evidence_refs=()),)).evidences[0].evidence_refs,())

    def test_016_duplicate_refs_reject(self):
        with self.assertRaisesRegex(ValueError,'duplicate_evidence_ref'):claim(evidence_refs=('r','r'))

    def test_017_blank_and_nonconcrete_refs_reject(self):
        class Text(str):pass
        for value in ('',' \n',None,3,Text('r')):
            with self.subTest(value=value),self.assertRaises((TypeError,ValueError)):claim(evidence_refs=(value,))

    def test_018_concrete_basis_tick(self):
        class Number(int):pass
        for value in (4.0,'4',None,Number(4)):
            with self.subTest(value=value),self.assertRaises(TypeError):claim(basis_tick=value)

    def test_019_bool_basis_rejected(self):
        for value in (True,False):
            with self.assertRaises(TypeError):claim(basis_tick=value)

    def test_020_negative_basis_rejected(self):
        with self.assertRaises(ValueError):claim(basis_tick=-1)
        self.assertEqual(build((claim(basis_tick=0),),evaluated_at_tick=0).evidences[0].basis_tick,0)

    def test_021_concrete_evaluation_tick(self):
        class Number(int):pass
        for value in (5.0,'5',None,Number(5)):
            with self.subTest(value=value),self.assertRaises(TypeError):build(evaluated_at_tick=value)

    def test_022_bool_evaluation_rejected(self):
        for value in (True,False):
            with self.assertRaises(TypeError):build((),evaluated_at_tick=value)

    def test_023_negative_evaluation_rejected(self):
        with self.assertRaises(ValueError):build((),evaluated_at_tick=-1)

    def test_024_timeline_concrete_nonblank(self):
        class Text(str):pass
        for value in ('',' \t',None,False,Text('t')):
            with self.subTest(value=value),self.assertRaises((TypeError,ValueError)):build(timeline_id=value)

    def test_025_clock_concrete_nonblank(self):
        class Text(str):pass
        for value in ('',' \t',None,False,Text('c')):
            with self.subTest(value=value),self.assertRaises((TypeError,ValueError)):build(selected_clock_id=value)

    def test_026_future_basis_rejected_atomically(self):
        with self.assertRaisesRegex(ValueError,'basis_after_evaluation'):
            build((claim(),claim(option_id='second',basis_tick=6)))

    def test_027_equal_ticks_valid(self):
        result=build((claim(basis_tick=5),))
        self.assertEqual(result.evidences[0].basis_tick,result.evaluated_at_tick)

    def test_028_old_basis_not_classified(self):
        source=claim(basis_tick=0);result=build((source,),evaluated_at_tick=1000000)
        self.assertIs(result.evidences[0].base_claim,source)
        self.assertEqual(result.evidences[0].basis_tick,0)
        self.absent_terms('freshness','temporal_status','FRESH','STALE','CURRENT','HISTORICAL')

    def test_029_semantic_duplicates_reject_regardless_of_provenance(self):
        original=claim()
        for other in (original,claim(change=OutcomeChange.DECREASE),claim(source_id='other'),claim(assessment_policy_id='other'),claim(basis_tick=3)):
            with self.subTest(other=other),self.assertRaisesRegex(ValueError,'duplicate_semantic_key'):build((original,other))

    def test_030_different_horizons_independent(self):
        result=build((claim(horizon_id='short'),claim(horizon_id='long',change=OutcomeChange.DECREASE)))
        self.assertEqual({r.horizon_id:r.change for r in result.evidences},{'short':OutcomeChange.INCREASE,'long':OutcomeChange.DECREASE})

    def test_031_different_baselines_independent(self):
        self.assertEqual({r.baseline_id for r in build((claim(),claim(baseline_id='other'))).evidences},{'baseline','other'})

    def test_032_different_contexts_independent(self):
        self.assertEqual({r.outcome_context_id for r in build((claim(),claim(outcome_context_id='other'))).evidences},{'context','other'})

    def test_033_mixed_dimensions_have_no_aggregate(self):
        result=build((claim(dimension_id='gold',change=OutcomeChange.INCREASE),claim(dimension_id='access',change=OutcomeChange.DECREASE)))
        self.assertEqual([(r.dimension_id,r.change) for r in result.evidences],[('access',OutcomeChange.DECREASE),('gold',OutcomeChange.INCREASE)])
        self.assertEqual({f.name for f in fields(result)},{'timeline_id','selected_clock_id','evaluated_at_tick','ruleset','evidences'})

    def test_034_same_dimension_different_options(self):
        result=build((claim(option_id='b',change=OutcomeChange.INCREASE),claim(option_id='a',change=OutcomeChange.DECREASE)))
        self.assertEqual([(r.option_id,r.change) for r in result.evidences],[('a',OutcomeChange.DECREASE),('b',OutcomeChange.INCREASE)])

    def test_035_no_claim_no_row(self):self.assertEqual(build(()).evidences,())

    def test_036_absent_distinct_from_unknown(self):
        absent=build(());unknown=build((claim(change=OutcomeChange.UNKNOWN),))
        self.assertNotEqual(absent.snapshot_id,unknown.snapshot_id)
        self.assertEqual(len(absent.evidences),0);self.assertEqual(len(unknown.evidences),1)

    def test_037_unknown_preserved(self):
        row=build((claim(change=OutcomeChange.UNKNOWN),)).evidences[0]
        self.assertIs(row.change,OutcomeChange.UNKNOWN);self.assertIs(row.base_claim.change,OutcomeChange.UNKNOWN)

    def test_038_empty_snapshot_retains_headers(self):
        result=build((),timeline_id='empty',selected_clock_id='explicit',evaluated_at_tick=0)
        self.assertEqual((result.timeline_id,result.selected_clock_id,result.evaluated_at_tick),('empty','explicit',0))
        self.assertTrue(result.snapshot_id.startswith('option.outcome_evidence.v1:snapshot:'))

    def test_039_no_cartesian_product(self):
        result=build((claim(option_id='a',dimension_id='x'),claim(option_id='b',dimension_id='y')))
        self.assertEqual([(r.option_id,r.dimension_id) for r in result.evidences],[('a','x'),('b','y')])

    def test_040_one_row_per_claim_same_source_not_merged(self):
        sources=tuple(claim(dimension_id=str(i)) for i in range(4))
        self.assertEqual(len(build(sources).evidences),4)

    def test_041_no_option_discovery_or_default_binding(self):
        result=build((claim(option_id='opaque/no-action'),))
        self.assertEqual(tuple(r.option_id for r in result.evidences),('opaque/no-action',))
        parameters=inspect.signature(build_option_outcome_evidence).parameters
        self.assertEqual(tuple(parameters),('timeline_id','selected_clock_id','evaluated_at_tick','claims'))
        self.assertTrue(all(p.kind==p.KEYWORD_ONLY and p.default==p.empty for p in parameters.values()))

    def test_042_exact_base_claim_identity(self):
        first=claim(option_id='z');second=claim(option_id='a')
        rows=build((first,second)).evidences
        self.assertIs(rows[0].base_claim,second);self.assertIs(rows[1].base_claim,first)

    def test_043_inputs_not_mutated(self):
        source=(claim(option_id='z'),claim(option_id='a'));before=tuple(asdict(c) for c in source)
        build(source);build(source)
        self.assertEqual(tuple(asdict(c) for c in source),before)
        self.assertEqual(tuple(c.option_id for c in source),('z','a'))

    def test_044_option_preserved(self):self.preserved('option_id','  Ã©/option  ')
    def test_045_context_preserved(self):self.preserved('outcome_context_id','risk-like:opaque')
    def test_046_dimension_preserved(self):self.preserved('dimension_id','gold/commitment.v1')
    def test_047_baseline_preserved(self):self.preserved('baseline_id','explicit/do-not-infer')
    def test_048_horizon_preserved(self):self.preserved('horizon_id','99seconds/not-parsed')
    def test_049_change_preserved(self):
        for value in OutcomeChange:self.preserved('change',value)
    def test_050_basis_preserved(self):self.preserved('basis_tick',2)
    def test_051_source_preserved(self):self.preserved('source_id','fixture/not-authenticated')
    def test_052_references_order_preserved(self):self.preserved('evidence_refs',(' z ','Ã©','a'))
    def test_053_policy_preserved(self):self.preserved('assessment_policy_id','external.policy.v9')

    def test_054_complete_claim_evidence_schema(self):
        expected={'option_id','outcome_context_id','dimension_id','baseline_id','horizon_id','change','basis_tick','source_id','evidence_refs','assessment_policy_id'}
        self.assertEqual({f.name for f in fields(OptionOutcomeClaim)},expected)
        self.assertEqual({f.name for f in fields(OptionOutcomeEvidence)},expected|{'base_claim'})
        source=claim();row=build((source,)).evidences[0]
        self.assertEqual({k:v for k,v in asdict(row).items() if k!='base_claim'},asdict(source))

    def test_055_snapshot_headers_preserved(self):
        result=build(timeline_id=' timeline ',selected_clock_id='clock Î²',evaluated_at_tick=100)
        self.assertEqual((result.timeline_id,result.selected_clock_id,result.evaluated_at_tick),(' timeline ','clock Î²',100))

    def test_056_fixed_ruleset(self):
        self.assertEqual(outcome.RULESET,'option.outcome_evidence.v1')
        self.assertEqual(build().ruleset,outcome.RULESET)
        with self.assertRaises(TypeError):build(ruleset='caller-override')

    def test_057_canonical_snapshot_identity(self):
        result=build((claim(option_id='Ã©'),))
        payload=json.dumps(asdict(result),sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id,'option.outcome_evidence.v1:snapshot:'+hashlib.sha256(payload).hexdigest())
        self.assertEqual(build((claim(option_id='Ã©'),)).snapshot_id,result.snapshot_id)

    def test_058_all_claim_permutations_same_identity(self):
        sources=(claim(option_id='c'),claim(option_id='a'),claim(option_id='b'))
        results=tuple(build(order) for order in itertools.permutations(sources))
        self.assertTrue(all(r==results[0] and r.snapshot_id==results[0].snapshot_id for r in results))

    def test_059_canonical_order_all_semantic_axes(self):
        sources=(claim(option_id='z'),claim(outcome_context_id='a'),claim(dimension_id='a'),claim(baseline_id='a'),claim(horizon_id='a'),claim())
        key=lambda c:(c.option_id,c.outcome_context_id,c.dimension_id,c.baseline_id,c.horizon_id,c.source_id,c.assessment_policy_id)
        self.assertEqual(tuple(r.base_claim for r in build(sources).evidences),tuple(sorted(sources,key=key)))

    def test_060_identity_option(self):self.changed('option_id','new')
    def test_061_identity_context(self):self.changed('outcome_context_id','new')
    def test_062_identity_dimension(self):self.changed('dimension_id','new')
    def test_063_identity_baseline(self):self.changed('baseline_id','new')
    def test_064_identity_horizon(self):self.changed('horizon_id','new')
    def test_065_identity_change(self):self.changed('change',OutcomeChange.DECREASE)
    def test_066_identity_basis(self):self.changed('basis_tick',3)
    def test_067_identity_source(self):self.changed('source_id','new')
    def test_068_identity_reference_content(self):self.changed('evidence_refs',('new',))
    def test_069_identity_assessment_policy(self):self.changed('assessment_policy_id','new')
    def test_070_identity_timeline(self):self.changed('timeline_id','new',True)
    def test_071_identity_clock(self):self.changed('selected_clock_id','new',True)
    def test_072_identity_evaluation_tick(self):self.changed('evaluated_at_tick',6,True)

    def test_073_increase_not_good_for_resource_or_commitment(self):
        rows=build((claim(dimension_id='resource_access.v1'),claim(dimension_id='commitment.v1'))).evidences
        self.assertTrue(all(r.change is OutcomeChange.INCREASE for r in rows))
        self.absent_terms('good','favorable','recommended','gold','commitment','resource_access')

    def test_074_decrease_not_bad_or_special_gold_case(self):
        rows=build(tuple(claim(dimension_id=d,change=OutcomeChange.DECREASE) for d in ('gold','commitment','arbitrary'))).evidences
        self.assertTrue(all(r.change is OutcomeChange.DECREASE for r in rows))
        self.absent_terms('bad','worse','unfavorable')

    def test_075_unchanged_not_safe(self):
        row=build((claim(change=OutcomeChange.UNCHANGED),)).evidences[0]
        self.assertIs(row.change,OutcomeChange.UNCHANGED)
        self.absent_terms('safe','SAFE','safety','risk')

    def test_076_unknown_not_zero(self):
        row=build((claim(change=OutcomeChange.UNKNOWN),)).evidences[0]
        self.assertEqual(row.change.value,'UNKNOWN');self.assertNotEqual(row.change,0)
        self.assertNotIn('value',{f.name for f in fields(row)})

    def test_077_no_scalar_value(self):
        self.absent_terms('value_score','scalar_value','magnitude')
        self.assertTrue(all('value' not in {f.name for f in fields(c)} for c in (OptionOutcomeClaim,OptionOutcomeEvidence,OptionOutcomeSnapshot)))
    def test_078_no_utility(self):self.absent_terms('utility','utility_score','weighted_sum','weights','normalization')
    def test_079_no_expected_value(self):self.absent_terms('expected_value','reward_score','cost_benefit_score')
    def test_080_no_probability(self):self.absent_terms('probability','success_probability','chance')
    def test_081_no_confidence(self):self.absent_terms('confidence','confidence_score','confidence_percentage')
    def test_082_no_combined_rating(self):self.absent_terms('LOW','MEDIUM','HIGH','overall','rating')

    def test_083_order_not_direction_ranking(self):
        for first,last in itertools.product(OutcomeChange,repeat=2):
            rows=build((claim(option_id='z',change=first),claim(option_id='a',change=last))).evidences
            self.assertEqual(tuple(r.option_id for r in rows),('a','z'))
        self.absent_terms('rank','ranking','priority','best_option')

    def test_084_no_selection(self):
        self.assertEqual(len(build((claim(option_id='a'),claim(option_id='b'))).evidences),2)
        self.absent_terms('selected_option','selected_plan','selection','choose')

    def test_085_no_recommendation(self):self.absent_terms('recommendation','recommended','preference','preferred')
    def test_086_no_action_authority(self):self.absent_terms('action','authority','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS','FARM','FIGHT','RETREAT')
    def test_087_no_opportunity_cost(self):self.absent_terms('opportunity_cost','foregone_value','alternative_cost')

    def test_088_no_pairwise_outcome_comparison(self):
        first=claim(option_id='a');second=claim(option_id='b',change=OutcomeChange.DECREASE)
        isolated=build((first,)).evidences[0]
        joint=build((second,first)).evidences[0]
        self.assertEqual(isolated,joint);self.assertIs(joint.base_claim,first)
        self.absent_terms('dominance','dominated','pairwise','subtract','difference')

    def test_089_no_strategic_objective(self):self.forbidden_imports('strategic_objective');self.absent_terms('objective','strategic_objective')
    def test_090_no_safety(self):self.forbidden_imports('option_safety','safety_evidence')
    def test_091_no_risk(self):self.forbidden_imports('risk_evaluation','risk_evidence')
    def test_092_no_decision(self):self.forbidden_imports('decision')
    def test_093_no_farm_strategic_or_availability(self):self.forbidden_imports('farm_context','farm_cycle','strategic_evidence','option_availability')
    def test_094_no_runtime_or_live(self):self.forbidden_imports('runtime_adapter','service','gsi','rules','vision','voice')
    def test_095_no_observation_event(self):self.forbidden_imports('observation_event')
    def test_096_no_temporal_evidence(self):self.forbidden_imports('temporal_evidence')

    def test_097_no_wall_clock(self):
        import time
        self.pure([(time,'time'),(time,'monotonic'),(time,'perf_counter')])

    def test_098_no_io(self):
        import builtins,io,os,subprocess,sqlite3
        self.pure([(builtins,'open'),(io,'open'),(os,'open'),(os,'system'),(subprocess,'Popen'),(sqlite3,'connect')])

    def test_099_no_network(self):
        import socket,http.client
        self.pure([(socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),(http.client.HTTPConnection,'request')])

    def test_100_no_environment(self):
        import os
        class Forbidden(dict):
            def __getitem__(self,key):raise AssertionError('environment access')
            def get(self,*args):raise AssertionError('environment access')
            def __iter__(self):raise AssertionError('environment access')
        with patch.object(os,'environ',Forbidden()):self.pure([(os,'getenv')])

    def test_101_no_random_uuid(self):
        import random,uuid
        self.pure([(random,'random'),(random,'getrandbits'),(uuid,'uuid1'),(uuid,'uuid4')])

    def test_102_no_mutable_globals_or_lifecycle(self):
        before=dict(vars(outcome));build();build(())
        self.assertEqual(before,vars(outcome))
        for name,value in vars(outcome).items():
            if not name.startswith('__'):self.assertNotIsInstance(value,(dict,list,set,bytearray))
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal,ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(ast.parse(inspect.getsource(outcome)))))
        self.absent_terms('Execution','ExecutionState','NOT_STARTED','IN_PROGRESS','COMMITTED','ABORTING','COMPLETED','EXPIRED','urgency','deadline')

    def test_103_legacy_and_handoff_documented(self):
        document=(Path(outcome.__file__).resolve().parent.parent/'OPTION_OUTCOME_EVIDENCE_V01.md').read_text(encoding='utf-8')
        for text in ('OutcomeChange describes direction, not utility.','INCREASE does not mean GOOD.','DECREASE does not mean BAD.',
                     'UNKNOWN is an explicit assessed state; missing evidence is absence, not UNKNOWN.',
                     'Option Outcome Evidence does not compare options.','Option Outcome Evidence does not calculate opportunity cost.',
                     'Option Outcome Evidence does not rank or select.','Dimensions are opaque and cross-role.',
                     'Baselines and horizons are explicit and caller-owned.',
                     'Older basis ticks are preserved but not classified as stale/current in v0.1.',
                     'Option Safety and Option Outcome Evidence remain orthogonal.',
                     'CandidatePlan.expected_future_state','coach02/option_availability.py','coach02/farm_context.py',
                     'OptionSafetySnapshotV2','OptionOutcomeSnapshot','DecisionContextV2',
                     'BLOCKER_BEFORE_DECISION_CONTEXT_V02','BLOCKER_BEFORE_DECISION_ARBITER','BLOCKER_BEFORE_ATTENTION_GATE','BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION'):
            with self.subTest(text=text):self.assertIn(text,document)

    def test_104_existing_production_and_tests_hashes(self):
        root=Path(outcome.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES),115)
        for name,expected in BASELINE_HASHES:
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),expected)


BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'), ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'), ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'), ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md', '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'), ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'), ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'), ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'), ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'), ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'), ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'), ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'), ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'), ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'), ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'), ('README.md', '72A60A5815269D2B2EAED3119841A4D57D26E6564F56BE104C6766F2FAAEF674'), ('RISK_EVALUATION_V01.md', '7A13246FD6D31A4A58C22AA9C1D209FF40727D79C8E90339620EDFDF2A878C32'), ('RISK_EVIDENCE_ASSEMBLY_V01.md', 'D44F8700089A390AC5CF6C670A78481A7340CF84A98A4766D194BF1D821B28B6'), ('RISK_EVIDENCE_ASSEMBLY_V02.md', '60A9C3B76C42C19B42EE94DA50A3A6C7E85400398502117200B3BF4F388D4D76'), ('RUNTIME_ADAPTER_V01.md', '723B87C9FA564CCB0527D6647F66D9752DA127082910C415D10838449E0051AE'), ('Run-Tests.cmd', 'C7D36F01B393C13362D8C6FB35D6C5FFDB9A81DC7AE086B61DE723974240136A'), ('SAFETY_EVIDENCE_V01.md', '160811B5829650324AD3353DD89C85ABAB878D3465B9261D0AFE840F284A8978'), ('STRATEGIC_COVERAGE_V01.md', '70AB604B5F34613F0BB306CC7E48FFB95CE1CA5419DB38427B91E8D4A8FB9181'), ('STRATEGIC_EVIDENCE_ASSEMBLY_V01.md', 'E2918BA287987AE36DF60BAD083CC45726998CFA97F082A626EB103D2F76FADD'), ('Start-Bot-Test.cmd', 'A967FFFC010A28FB3957C86B8B2AAF5DA7E98B40BA645B4DE63464FDBF3A11A4'), ('Start-Coach.cmd', '400EF821414BC0036D0BD29ED6382CDCC3477147604DAFCFAE488C7E329A8123'), ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'), ('THREAT_ABSENCE_OBSERVATION_V01.md', '6A37416C544E27A08DB0B8B1BC4D2D07136C833DE0A8674DD17EC79D9F9F0952'), ('THREAT_OBSERVATION_V01.md', '4633E7C0E920F790605DA27635A8D84ACA38DE59A52485CF16DEF1C7EDB8327B'), ('THREAT_REACHABILITY_V01.md', '180A3F7995AD367FD62DFCAA2175C03C6E1940C6C4BCFE80BF05C575DF0F2D42'), ('THREAT_RELEVANCE_V01.md', '51F9BEB03B612559A8EA350AB4C9FF5438C05A40EEAE5798CD40B5D1AD069666'), ('THREAT_STATE_ASSEMBLY_V01.md', 'CD7DDFAAFDBBA7A295616A1820FC267F46651C8B3AEB9ED445532B5C48E9766A'), ('VISIBILITY_COMPLETENESS_V01.md', 'E79A0B25695A39529E324F18792CA9C4CD31BDEB8EF8548C3FD351BB3DAFA7B3'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('docs/CHANGES.md', 'A2DBFDAE75A11C1CFD601269E677D6F73F72A6017006D235AAD527A22F26BD9A'), ('docs/DECISIONS.md', '35C72BB38D35D8EE6A804BE9F3631047FB68E4A8E9538908F2259CD3917FB14A'), ('docs/TESTE_REAL.md', '335EC57D975ADB1FD046A358975DDF8831B67BC1F183C1AB4E576DAD675C06A8'), ('docs/VALIDATION.md', '7D5D0E515DE4D46E158DD955B2422F4B997A99000FCB531F61272FB06079A9C5'), ('docs/alpha01-reference/DECISIONS.md', '83D8C8EDD6386C958CB5A770746A1B7016C355596985DB44646EFF0B9ADA7571'), ('docs/alpha01-reference/VALIDATION.md', 'F29B09DD7427543EDA767B0FDBE68033C4A7980E6A9A9ADC3255189F274F619E'), ('docs/baseline-sha256.json', '3561C10064F6BAC12F032FCC51382EBD7D7FBEF70786C31E6C857DC386ECD40D'), ('docs/baseline-verification.json', '7326E1A33FB35E281A6A3211E85DFFD2A081BB22317C33DB7B7FAEE67E2E394B'), ('docs/test-results.txt', 'EE9BBD62124FCF6CB377DF2D79129BF0C927ACEAB2128AB247CABE92F0A7F2B7'), ('requirements-vision.txt', 'ECBC0244A6BC4646A912CF032F999724D47E22CB12CDBFAA231B600465F06711'), ('requirements.txt', 'CE972E5602F1BADF47B56CE597EBF4A3CBC516CA6C8979C95EE75C067D275840'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('tests/test_alpha.py', '17BD7EBFF1558F062577A4677A472B0B3F65B85DC921253D6A9F5C2B705862D5'), ('tests/test_alpha02.py', '9F0839D676974435FA4AB3EE4887F9BE8DF876D07C271CADA4D0AFAA43A43C02'), ('tests/test_context_builder.py', '26A50D99710BAF117FA45AA570BA8BCDC38343835FED5EEF9C2618493E9AE701'), ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'), ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'), ('tests/test_missing_threat_resolver.py', '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'), ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'), ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'), ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'), ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'), ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'), ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'), ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'), ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'), ('tests/test_risk_evidence_assembly_v02.py', 'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'), ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'), ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'), ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'), ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'), ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'), ('tests/test_threat_absence_observation.py', 'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'), ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'), ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'), ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'), ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'), ('tests/test_visibility_completeness.py', '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
