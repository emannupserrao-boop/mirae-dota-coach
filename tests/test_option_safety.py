"""Supplied synthetic observations only; planner calls are explicit test steps."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
from itertools import product
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import normalize
from coach02 import decision, farm_cycle, option_safety, safety_evidence
from coach02.context_builder import build_context_seed
from coach02.decision import (Action, Authority, Claim, Execution, Freshness,
    KnowledgeSnapshotRef, ObservedFact, ObservationSource, OptionAssessment,
    PlayerModelSnapshotRef, PRODUCTIVE_ACTIONS, Source, Truth)
from coach02.farm_context import FarmStrategicEvidence, compose_farm_context
from coach02.option_safety import (Exposure, FarmOptionSafetyObservation,
    OptionSafetyReason, build_option_safety)
from coach02.runtime_adapter import adapt_state
from coach02.safety_evidence import (CoverageObservation, RelevantThreatObservation,
    ThreatState, build_risk_awareness)

Y, N, U = Truth.YES, Truth.NO, Truth.UNKNOWN
F, S = Freshness.FRESH, Freshness.STALE
LOW, HIGH, UNKNOWN = Exposure.LOW, Exposure.HIGH, Exposure.UNKNOWN


def seed(**changes):
    return build_context_seed(adapt_state(replace(normalize(payload()), **changes)),
        KnowledgeSnapshotRef('not-loaded','v1'), PlayerModelSnapshotRef('not-loaded','v1'))


def risk_for(s, value):
    state = {Y:ThreatState.VISIBLE_NEARBY, N:ThreatState.VISIBLE_AWAY, U:ThreatState.UNKNOWN}[value]
    return build_risk_awareness(s.seed_id, (RelevantThreatObservation('enemy',state,F),), CoverageObservation(Y,F))


def observation(s, exposure=LOW, coverage=Y, ef=F, cf=F, option_id='wave', action=Action.TAKE_ONE_MORE_WAVE):
    return FarmOptionSafetyObservation(s.seed_id,option_id,action,exposure,ef,coverage,cf)


def assess(risk=N, exposure=LOW, coverage=Y, ef=F, cf=F):
    s=seed(); r=risk_for(s,risk)
    return build_option_safety(s.seed_id,r,(observation(s,exposure,coverage,ef,cf),))[0]


def compose(s, risk, results, available=Y, independent_farm=False):
    # Binding must be checked BEFORE unpacking envelopes into legacy Claim objects.
    facts={f.ref:f for f in risk.observations}; assessments=[]
    for result in results:
        result.validate_binding(s.seed_id,risk)
        for fact in result.observations:
            if fact.ref in facts and facts[fact.ref] != fact:
                raise ValueError('conflicting_fixture_fact')
            facts[fact.ref]=fact
        ref='fixture.available.'+result.option_id
        facts[ref]=ObservedFact(ref,available,F)
        assessments.append(OptionAssessment(result.option_id,result.action,
            Claim(available,(ref,),'fixture.availability.v1'),result.safety))
    if independent_farm:
        # Separate explicit fixture, NOT a conclusion from global risk or this builder.
        refs=('fixture.farm-present','fixture.farm-corridor')
        for ref in refs: facts[ref]=ObservedFact(ref,Y,F)
        assessments.append(OptionAssessment('independent-farm',Action.LEAVE_TO_SAFE_FARM,
            Claim(Y,(refs[0],),'fixture.farm-availability.v1'),
            Claim(Y,(refs[1],),'fixture.independent-farm-safety.v1')))
    return compose_farm_context(s,FarmStrategicEvidence(s.seed_id,
        tuple(facts.values()),tuple(assessments),risk.increased_risk),Execution())


class OptionSafetyTests(unittest.TestCase):
    def test_rule_a_no(self):
        result=assess(Y,HIGH,N)
        self.assertEqual(result.safety.value,N)
        self.assertEqual(result.reasons,(OptionSafetyReason.HIGH_EXPOSURE_WITH_INCREASED_RISK_AND_NO_COVERAGE,))

    def test_rule_b_yes(self):
        result=assess(N,LOW,Y)
        self.assertEqual(result.safety.value,Y)
        self.assertEqual(result.reasons,(OptionSafetyReason.LOW_EXPOSURE_WITH_LOW_RISK_AND_COVERAGE,))

    def test_risk_yes_low_exposure_unknown(self):
        self.assertEqual(assess(Y,LOW,N).safety.value,U)

    def test_risk_yes_coverage_yes_unknown(self):
        self.assertEqual(assess(Y,HIGH,Y).safety.value,U)

    def test_risk_no_high_exposure_unknown(self):
        result=assess(N,HIGH,Y)
        self.assertEqual(result.safety.value,U)
        self.assertIn(OptionSafetyReason.GLOBAL_RISK_LOW_BUT_OPTION_EXPOSURE_HIGH,result.reasons)

    def test_risk_no_coverage_no_unknown(self):
        self.assertEqual(assess(N,LOW,N).safety.value,U)

    def test_global_unknown_remains_unknown(self):
        result=assess(U,LOW,Y)
        self.assertEqual(result.safety.value,U)
        self.assertIn(OptionSafetyReason.GLOBAL_RISK_UNKNOWN,result.reasons)

    def test_exposure_unknown(self):
        result=assess(N,UNKNOWN,Y)
        self.assertEqual(result.safety.value,U)
        self.assertIn(OptionSafetyReason.OPTION_EXPOSURE_UNKNOWN,result.reasons)
        self.assertTrue(all(f.value==U for f in result.observations if '.exposure_' in f.ref))

    def test_exposure_stale(self):
        for risk,exposure,coverage in ((N,LOW,Y),(Y,HIGH,N)):
            result=assess(risk,exposure,coverage,S)
            self.assertEqual(result.safety.value,U)
            self.assertIn(OptionSafetyReason.OPTION_EXPOSURE_STALE,result.reasons)

    def test_coverage_unknown(self):
        result=assess(N,LOW,U)
        self.assertEqual(result.safety.value,U)
        self.assertIn(OptionSafetyReason.OPTION_COVERAGE_UNKNOWN,result.reasons)

    def test_coverage_stale(self):
        for risk,exposure,coverage in ((N,LOW,Y),(Y,HIGH,N)):
            result=assess(risk,exposure,coverage,F,S)
            self.assertEqual(result.safety.value,U)
            self.assertIn(OptionSafetyReason.OPTION_COVERAGE_STALE,result.reasons)

    def test_only_two_definitive_combinations_for_every_action(self):
        # Exhaustive finite domain: 108 combinations per action; only A and B decide.
        s=seed(); risks={v:risk_for(s,v) for v in Truth}
        for rv,exposure,coverage,ef,cf,action in product(Truth,Exposure,Truth,Freshness,Freshness,PRODUCTIVE_ACTIONS):
            with self.subTest(risk=rv,exposure=exposure,coverage=coverage,ef=ef,cf=cf,action=action):
                expected={(Y,HIGH,N,F,F):N,(N,LOW,Y,F,F):Y}.get((rv,exposure,coverage,ef,cf),U)
                actual=build_option_safety(s.seed_id,risks[rv],(observation(s,exposure,coverage,ef,cf,action=action),))[0]
                self.assertEqual(actual.safety.value,expected)

    def test_missing_options_not_fabricated(self):
        s=seed(); risk=risk_for(s,Y)
        self.assertEqual(build_option_safety(s.seed_id,risk,()),())
        only=build_option_safety(s.seed_id,risk,(observation(s,option_id='one'),))
        self.assertEqual(tuple(o.option_id for o in only),('one',))

    def test_yes_and_no_are_documented_heuristics(self):
        doc=build_option_safety.__doc__
        self.assertIn('not guaranteed safe',doc)
        self.assertIn('not death certainty',doc)
        for value,exposure,coverage in ((N,LOW,Y),(Y,HIGH,N)):
            s=seed(); r=risk_for(s,value)
            e=build_option_safety(s.seed_id,r,(observation(s,exposure,coverage),))
            safe=compose(s,r,e).options[0].safe
            self.assertEqual(safe.provenance[-1].source,Source.EXPERT_HEURISTIC)

    def test_global_risk_alone_never_decides_option_safety(self):
        for risk in (Y,N):
            self.assertEqual(assess(risk,UNKNOWN,U).safety.value,U)

    def test_seed_binding_checked_at_build_and_consumption(self):
        a=seed(); b=seed(gold=987); r=risk_for(a,N)
        with self.assertRaisesRegex(ValueError,'risk_seed_mismatch'):
            build_option_safety(b.seed_id,r,())
        with self.assertRaisesRegex(ValueError,'option_observation_seed_mismatch'):
            build_option_safety(a.seed_id,r,(observation(b),))
        e=build_option_safety(a.seed_id,r,(observation(a),))
        with self.assertRaisesRegex(ValueError,'option_safety_seed_mismatch'):
            compose(b,risk_for(b,N),e)

    def test_exact_upstream_risk_binding_even_when_same_truth(self):
        s=seed(); r1=risk_for(s,N)
        r2=build_risk_awareness(s.seed_id,(RelevantThreatObservation('different',ThreatState.VISIBLE_AWAY,F),),CoverageObservation(Y,F))
        e=build_option_safety(s.seed_id,r1,(observation(s),))
        self.assertEqual(r1.increased_risk.value,r2.increased_risk.value)
        self.assertNotEqual(r1.evidence_id,r2.evidence_id)
        with self.assertRaisesRegex(ValueError,'option_safety_risk_mismatch'): compose(s,r2,e)
        self.assertEqual(e[0].upstream_risk_evidence_id,r1.evidence_id)

    def test_support_is_underlying_facts_not_opaque_id_or_derived_risk_fact(self):
        s=seed()
        for rv,exposure,coverage,predicate in ((Y,HIGH,N,'exposure_high'),(N,LOW,Y,'exposure_low')):
            r=risk_for(s,rv); e=build_option_safety(s.seed_id,r,(observation(s,exposure,coverage),))[0]
            expected=set(r.increased_risk.evidence_refs)|{'safety.option.wave.'+predicate,'safety.option.wave.coverage_sufficient'}
            self.assertEqual(set(e.safety.evidence_refs),expected)
            facts={f.ref:f for f in e.observations}
            self.assertTrue(expected<=facts.keys())
            self.assertNotIn(r.evidence_id,e.safety.evidence_refs)
            self.assertTrue(all(facts[f.ref]==f for f in r.observations))

    def test_provenance_preserved_through_composition(self):
        s=seed(); r=risk_for(s,N)
        results=build_option_safety(s.seed_id,r,(observation(s),))
        self.assertTrue(all(f.source is ObservationSource.SAFETY_EVIDENCE for f in results[0].observations))
        ctx=compose(s,r,results); safe=ctx.options[0].safe
        self.assertTrue(all(p.source is ObservationSource.SAFETY_EVIDENCE for p in safe.provenance[:-1]))
        self.assertEqual(safe.provenance[-1].source,Source.EXPERT_HEURISTIC)
        self.assertEqual(safe.provenance[-1].ref,results[0].safety.rule_ref)
        self.assertEqual(ctx.increased_risk.provenance[-1].ref,r.increased_risk.rule_ref)
        self.assertEqual(ctx.options[0].available.provenance[0].source,Source.RUNTIME_OBSERVATION)

    def test_deterministic_identity(self):
        first=assess(); self.assertEqual(first,assess())
        data=asdict(first); data.pop('evidence_id')
        encoded=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
        self.assertEqual(first.evidence_id,first.ruleset+':'+hashlib.sha256(encoded).hexdigest())
        self.assertNotEqual(first.evidence_id,assess(coverage=N).evidence_id)

    def test_order_independence(self):
        s=seed(); r=risk_for(s,N)
        options=(observation(s,option_id='b'),observation(s,option_id='a',action=Action.LEAVE_TO_SAFE_FARM))
        first=build_option_safety(s.seed_id,r,options)
        reordered=replace(r,observations=tuple(reversed(r.observations)),
            increased_risk=replace(r.increased_risk,evidence_refs=tuple(reversed(r.increased_risk.evidence_refs))))
        self.assertEqual(first,build_option_safety(s.seed_id,reordered,tuple(reversed(options))))

    def test_immutability_no_input_mutation(self):
        s=seed(); r=risk_for(s,N); o=observation(s)
        before=(asdict(r),asdict(o)); e=build_option_safety(s.seed_id,r,(o,))[0]
        self.assertEqual(before,(asdict(r),asdict(o)))
        with self.assertRaises(FrozenInstanceError): o.coverage=N
        with self.assertRaises(FrozenInstanceError): e.option_id='changed'
        with self.assertRaises(FrozenInstanceError): e.safety.value=N
        with self.assertRaises(FrozenInstanceError): e.observations[0].value=N

    def test_schema_never_infers_availability_or_selects_action(self):
        e=assess()
        self.assertEqual(set(asdict(e)),{'evidence_id','seed_id','option_id','action','observations','safety','reasons','ruleset','upstream_risk_evidence_id'})
        self.assertNotIn('available',asdict(e)); self.assertNotIn('recommended_action',asdict(e))
        s=seed(); r=risk_for(s,N)
        for action in PRODUCTIVE_ACTIONS:
            e=build_option_safety(s.seed_id,r,(observation(s,action=action),))[0]
            self.assertIs(e.action,action)
            self.assertEqual(e.safety.value,Y)

    def test_no_hero_or_economy_logic(self):
        a=seed(); b=seed(hero='another-hero',level=99,gold=99999,gpm=0,time=9999)
        ra=build_option_safety(a.seed_id,risk_for(a,N),(observation(a),))[0]
        rb=build_option_safety(b.seed_id,risk_for(b,N),(observation(b),))[0]
        self.assertEqual(ra.safety,rb.safety)
        self.assertEqual(ra.reasons,rb.reasons)
        self.assertEqual(ra.observations,rb.observations)
        self.assertNotEqual(ra.evidence_id,rb.evidence_id)

    def test_no_numeric_scoring_or_threat_rules(self):
        tree=ast.parse(Path(option_safety.__file__).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.Compare) and any(isinstance(op,(ast.Gt,ast.GtE,ast.Lt,ast.LtE)) for op in n.ops) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Name) and n.id in ('ThreatState','CoverageObservation','build_risk_awareness') for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in ('hero','items','level','gold','gpm','time','dimensions') for n in ast.walk(tree)))

    def test_end_to_end_wave_unsafe_to_independent_safe_farm(self):
        s=seed(); r=risk_for(s,Y)
        results=build_option_safety(s.seed_id,r,(observation(s,HIGH,N),))
        ctx=compose(s,r,results,independent_farm=True)
        self.assertEqual(next(o for o in ctx.options if o.plan_id=='wave').safe.value,N)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.LEAVE_TO_SAFE_FARM)

    def test_high_risk_covered_short_resource_stays_unknown(self):
        s=seed(); r=risk_for(s,Y)
        results=build_option_safety(s.seed_id,r,(observation(s,LOW,Y,option_id='short',action=Action.SAFE_RESOURCE_THEN_REEVALUATE),))
        ctx=compose(s,r,results)
        self.assertEqual(ctx.options[0].safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.NO_DIRECTIVE)

    def test_low_risk_supported_available_option_can_be_chosen(self):
        s=seed(); r=risk_for(s,N)
        for action in PRODUCTIVE_ACTIONS:
            results=build_option_safety(s.seed_id,r,(observation(s,action=action),))
            self.assertEqual(farm_cycle.plan(compose(s,r,results)).next_action,action)

    def test_end_to_end_unknown_risk_preserves_uncertainty(self):
        s=seed(); r=risk_for(s,U)
        ctx=compose(s,r,build_option_safety(s.seed_id,r,(observation(s),)))
        self.assertEqual(ctx.increased_risk.value,U)
        self.assertEqual(ctx.options[0].safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_global_risk_yes_alone_never_creates_safe_farm(self):
        s=seed(); r=risk_for(s,Y)
        ctx=compose(s,r,build_option_safety(s.seed_id,r,()))
        self.assertEqual(ctx.options,())
        result=farm_cycle.plan(ctx)
        self.assertEqual(result.next_action,Action.NO_DIRECTIVE)
        self.assertEqual(result.output_authority,Authority.AWARENESS)

    def test_safety_yes_availability_unknown_not_actionable(self):
        s=seed(); r=risk_for(s,N)
        ctx=compose(s,r,build_option_safety(s.seed_id,r,(observation(s),)),available=U)
        self.assertEqual(ctx.options[0].safe.value,Y)
        self.assertEqual(ctx.options[0].available.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_available_yes_safety_unknown_not_actionable(self):
        s=seed(); r=risk_for(s,N)
        ctx=compose(s,r,build_option_safety(s.seed_id,r,(observation(s,HIGH),)))
        self.assertEqual(ctx.options[0].available.value,Y)
        self.assertEqual(ctx.options[0].safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_multiple_options_have_independent_results(self):
        s=seed(); r=risk_for(s,N)
        results=build_option_safety(s.seed_id,r,(observation(s,HIGH,option_id='wave'),
            observation(s,LOW,Y,option_id='farm',action=Action.LEAVE_TO_SAFE_FARM),
            observation(s,LOW,N,option_id='short',action=Action.SAFE_RESOURCE_THEN_REEVALUATE)))
        self.assertEqual({e.option_id:e.safety.value for e in results},{'wave':U,'farm':Y,'short':U})
        self.assertEqual(farm_cycle.plan(compose(s,r,results)).next_action,Action.LEAVE_TO_SAFE_FARM)
        for e in results:
            option_refs=[f.ref for f in e.observations if f.ref.startswith('safety.option.')]
            self.assertTrue(all(ref.startswith('safety.option.'+e.option_id+'.') for ref in option_refs))

    def test_unrelated_unknown_upstream_facts_do_not_erase_supported_no(self):
        s=seed()
        r=build_risk_awareness(s.seed_id,(RelevantThreatObservation('direct',ThreatState.VISIBLE_NEARBY,F),
            RelevantThreatObservation('unknown',ThreatState.UNKNOWN,S)),CoverageObservation(U,S))
        results=build_option_safety(s.seed_id,r,(observation(s,HIGH,N),))
        self.assertEqual(results[0].safety.value,N)
        self.assertEqual(compose(s,r,results).options[0].safe.value,N)
        self.assertTrue(any(f.value==U for f in results[0].observations))

    def test_stable_reasons_and_rule_refs(self):
        self.assertEqual(assess(Y,HIGH,N).safety.rule_ref,'safety.option.high_risk_exposed_uncovered.v1')
        self.assertEqual(assess(N,LOW,Y).safety.rule_ref,'safety.option.low_risk_low_exposure_covered.v1')
        self.assertEqual(assess(U).safety.rule_ref,'safety.option.insufficient_support.v1')
        self.assertEqual(assess().ruleset,'safety.option_assessment.v1')

    def test_malformed_inputs_refused(self):
        s=seed(); r=risk_for(s,N)
        for name in ('','bad.id','with space','é',5):
            with self.assertRaises(ValueError): observation(s,option_id=name)
        for action in (Action.NO_DIRECTIVE,Action.ABORT_CURRENT_ROUTE,'TAKE_ONE_MORE_WAVE'):
            with self.assertRaises(ValueError): observation(s,action=action)
        for kwargs in ({'exposure':'LOW'},{'coverage':True},{'ef':'FRESH'},{'cf':None}):
            with self.assertRaises(ValueError): observation(s,**kwargs)
        with self.assertRaises(TypeError): build_option_safety(s.seed_id,r,[observation(s)])
        with self.assertRaises(TypeError): build_option_safety(s.seed_id,r,(None,))
        with self.assertRaises(TypeError): build_option_safety(s.seed_id,None,())
        with self.assertRaisesRegex(ValueError,'duplicate_option_id'):
            build_option_safety(s.seed_id,r,(observation(s),observation(s)))
        with self.assertRaises(ValueError): build_option_safety('',r,())

    def test_malformed_risk_support_cannot_promote_safety(self):
        s=seed(); r=risk_for(s,N)
        variants=(replace(r,observations=()),replace(r,evidence_id=''),
            replace(r,observations=r.observations+r.observations),
            replace(r,increased_risk=replace(r.increased_risk,evidence_refs=())),
            replace(r,observations=tuple(replace(f,freshness=S) for f in r.observations)),
            replace(r,observations=tuple(replace(f,source=Source.RUNTIME_OBSERVATION) for f in r.observations)))
        for invalid in variants:
            with self.assertRaises(ValueError): build_option_safety(s.seed_id,invalid,(observation(s),))

    def test_previous_frame_not_retained(self):
        assess(N,LOW,Y)
        self.assertEqual(assess(U,UNKNOWN,U).safety.value,U)

    def test_no_io_environment_clock_or_planner(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        s=seed(); r=risk_for(s,N); options=(observation(s),)
        expected=build_option_safety(s.seed_id,r,options)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (farm_cycle,'plan'),(decision,'build_context'),(decision,'authorize_output'),
            (safety_evidence,'build_risk_awareness')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]; environment=os.environ
        forbidden=AssertionError('Option safety crossed pure assessment boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=build_option_safety(s.seed_id,r,options)
            actual[0].validate_binding(s.seed_id,r)
        self.assertEqual(actual,expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_import_and_live_isolation(self):
        tree=ast.parse(Path(option_safety.__file__).read_text(encoding='utf-8'))
        imports=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(a.name for a in n.names)
            if isinstance(n,ast.ImportFrom): imports.add('.'*n.level+(n.module or ''))
        self.assertEqual(imports,{'dataclasses','enum','hashlib','json','.decision','.safety_evidence'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        root=Path(option_safety.__file__).resolve().parent.parent
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py',
                     'coach02/runtime_adapter.py','coach02/context_builder.py','coach02/safety_evidence.py',
                     'coach02/farm_context.py','coach02/farm_cycle.py','coach02/vision.py'):
            other=ast.parse((root/path).read_text(encoding='utf-8'))
            for n in ast.walk(other):
                if isinstance(n,(ast.Import,ast.ImportFrom,ast.Call)):
                    self.assertNotIn('option_safety',ast.unparse(n),path)


if __name__=='__main__': unittest.main()
