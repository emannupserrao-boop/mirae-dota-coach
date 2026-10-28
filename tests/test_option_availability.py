"""Synthetic presence/access fixtures. All composition and planner calls are explicit."""
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
from coach02 import decision, farm_cycle, option_availability
from coach02.context_builder import build_context_seed
from coach02.decision import (Action, Authority, Execution, Freshness, KnowledgeSnapshotRef,
    ObservationSource, OptionAssessment, PlayerModelSnapshotRef, PRODUCTIVE_ACTIONS, Source, Truth)
from coach02.farm_context import FarmStrategicEvidence, compose_farm_context
from coach02.option_availability import (AvailabilityReason, FarmOptionAvailabilityObservation,
    build_option_availability)
from coach02.option_safety import Exposure, FarmOptionSafetyObservation, build_option_safety
from coach02.runtime_adapter import adapt_state
from coach02.safety_evidence import CoverageObservation, RelevantThreatObservation, ThreatState, build_risk_awareness

Y,N,U=Truth.YES,Truth.NO,Truth.UNKNOWN
F,S=Freshness.FRESH,Freshness.STALE


def seed(**changes):
    return build_context_seed(adapt_state(replace(normalize(payload()),**changes)),
        KnowledgeSnapshotRef('not-loaded','v1'),PlayerModelSnapshotRef('not-loaded','v1'))


def risk_for(s,value=N):
    state={Y:ThreatState.VISIBLE_NEARBY,N:ThreatState.VISIBLE_AWAY,U:ThreatState.UNKNOWN}[value]
    return build_risk_awareness(s.seed_id,(RelevantThreatObservation('enemy',state,F),),CoverageObservation(Y,F))


def observation(s,presence=Y,access=Y,pf=F,af=F,option_id='wave',action=Action.TAKE_ONE_MORE_WAVE):
    return FarmOptionAvailabilityObservation(s.seed_id,option_id,action,presence,pf,access,af)


def availability(s,presence=Y,access=Y,pf=F,af=F,option_id='wave',action=Action.TAKE_ONE_MORE_WAVE):
    return build_option_availability(s.seed_id,(observation(s,presence,access,pf,af,option_id,action),))[0]


def safety(s,risk,exposure=Exposure.LOW,coverage=Y,option_id='wave',action=Action.TAKE_ONE_MORE_WAVE):
    return build_option_safety(s.seed_id,risk,(FarmOptionSafetyObservation(
        s.seed_id,option_id,action,exposure,F,coverage,F),))[0]


def compose(s,risk,pairs):
    # Pairing is explicit. Validate envelopes before dropping their binding fields.
    for available,safe in pairs:
        safe.validate_binding(s.seed_id,risk)
        available.validate_binding(s.seed_id,safe.option_id,safe.action)
    facts={f.ref:f for f in risk.observations}; assessments=[]
    for available,safe in pairs:
        for fact in available.observations+safe.observations:
            if fact.ref in facts and facts[fact.ref]!=fact: raise ValueError('conflicting_fixture_fact')
            facts[fact.ref]=fact
        assessments.append(OptionAssessment(safe.option_id,safe.action,available.availability,safe.safety))
    return compose_farm_context(s,FarmStrategicEvidence(s.seed_id,tuple(facts.values()),
        tuple(assessments),risk.increased_risk),Execution())


class OptionAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.seed=seed()

    def test_present_and_accessible_yes(self):
        e=availability(self.seed)
        self.assertEqual(e.availability.value,Y)
        self.assertEqual(e.reasons,(AvailabilityReason.RESOURCE_PRESENT_AND_ACCESSIBLE,))

    def test_presence_no(self):
        e=availability(self.seed,N)
        self.assertEqual(e.availability.value,N)
        self.assertEqual(e.reasons,(AvailabilityReason.RESOURCE_NOT_PRESENT,))

    def test_access_no(self):
        e=availability(self.seed,Y,N)
        self.assertEqual(e.availability.value,N)
        self.assertEqual(e.reasons,(AvailabilityReason.RESOURCE_NOT_ACCESSIBLE,))

    def test_presence_unknown(self):
        e=availability(self.seed,U)
        self.assertEqual(e.availability.value,U)
        self.assertIn(AvailabilityReason.RESOURCE_PRESENCE_UNKNOWN,e.reasons)

    def test_access_unknown(self):
        e=availability(self.seed,Y,U)
        self.assertEqual(e.availability.value,U)
        self.assertIn(AvailabilityReason.RESOURCE_ACCESS_UNKNOWN,e.reasons)

    def test_presence_stale(self):
        for value in (Y,N,U):
            e=availability(self.seed,value,Y,S)
            self.assertEqual(e.availability.value,U)
            self.assertIn(AvailabilityReason.RESOURCE_PRESENCE_STALE,e.reasons)

    def test_access_stale(self):
        for value in (Y,N,U):
            e=availability(self.seed,Y,value,F,S)
            self.assertEqual(e.availability.value,U)
            self.assertIn(AvailabilityReason.RESOURCE_ACCESS_STALE,e.reasons)

    def test_fresh_no_dominates_unknown_and_stale_in_composition(self):
        s=self.seed; r=risk_for(s); safe=safety(s,r)
        for p,a,pf,af,ref in ((N,U,F,S,'resource_present'),(U,N,S,F,'accessible'),
                              (N,Y,F,S,'resource_present'),(Y,N,S,F,'accessible')):
            e=availability(s,p,a,pf,af)
            self.assertEqual(e.availability.value,N)
            self.assertEqual(e.availability.evidence_refs,('availability.option.wave.'+ref,))
            self.assertEqual(compose(s,r,((e,safe),)).options[0].available.value,N)
            self.assertEqual(len(e.observations),2)

    def test_exhaustive_rule_table_all_actions(self):
        # 36 combinations per action; no timing or action-specific branches.
        for p,a,pf,af,action in product(Truth,Truth,Freshness,Freshness,PRODUCTIVE_ACTIONS):
            with self.subTest(p=p,a=a,pf=pf,af=af,action=action):
                if (p==N and pf==F) or (a==N and af==F): expected=N
                elif (p,a,pf,af)==(Y,Y,F,F): expected=Y
                else: expected=U
                self.assertEqual(availability(self.seed,p,a,pf,af,action=action).availability.value,expected)

    def test_yes_does_not_imply_safety(self):
        s=self.seed; r=risk_for(s,U)
        ctx=compose(s,r,((availability(s),safety(s,r)),))
        self.assertEqual(ctx.options[0].available.value,Y)
        self.assertEqual(ctx.options[0].safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_no_does_not_imply_danger(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,((availability(s,N),safety(s,r)),))
        self.assertEqual(ctx.options[0].available.value,N)
        self.assertEqual(ctx.options[0].safe.value,Y)
        self.assertEqual(ctx.increased_risk.value,N)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_empty_input_no_objects_fabricated(self):
        self.assertEqual(build_option_availability(self.seed.seed_id,()),())

    def test_only_requested_option_exists(self):
        result=build_option_availability(self.seed.seed_id,(observation(self.seed,option_id='requested'),))
        self.assertEqual(tuple(e.option_id for e in result),('requested',))

    def test_seed_binding_at_build_and_composition(self):
        a=self.seed; b=seed(gold=999)
        with self.assertRaisesRegex(ValueError,'availability_observation_seed_mismatch'):
            build_option_availability(b.seed_id,(observation(a),))
        r=risk_for(b)
        with self.assertRaisesRegex(ValueError,'availability_seed_mismatch'):
            compose(b,r,((availability(a),safety(b,r)),))

    def test_option_id_binding_before_composition(self):
        s=self.seed; r=risk_for(s)
        with self.assertRaisesRegex(ValueError,'availability_option_mismatch'):
            compose(s,r,((availability(s,option_id='other'),safety(s,r)),))

    def test_action_binding_before_composition(self):
        s=self.seed; r=risk_for(s)
        with self.assertRaisesRegex(ValueError,'availability_action_mismatch'):
            compose(s,r,((availability(s,action=Action.LEAVE_TO_SAFE_FARM),safety(s,r)),))

    def test_provenance_domain_facts_and_heuristic_claim(self):
        s=self.seed; r=risk_for(s); e=availability(s)
        self.assertTrue(all(f.source is ObservationSource.SAFETY_EVIDENCE for f in e.observations))
        self.assertTrue(all(f.ref.startswith('availability.option.wave.') for f in e.observations))
        condition=compose(s,r,((e,safety(s,r)),)).options[0].available
        self.assertTrue(all(p.source is ObservationSource.SAFETY_EVIDENCE for p in condition.provenance[:-1]))
        self.assertEqual(condition.provenance[-1].source,Source.EXPERT_HEURISTIC)
        self.assertEqual(condition.provenance[-1].ref,e.availability.rule_ref)

    def test_stable_reasons_and_both_negative_supports(self):
        s=self.seed
        self.assertEqual(availability(s).availability.rule_ref,'availability.option.present_and_accessible.v1')
        self.assertEqual(availability(s,N).availability.rule_ref,'availability.option.not_present.v1')
        self.assertEqual(availability(s,Y,N).availability.rule_ref,'availability.option.not_accessible.v1')
        self.assertEqual(availability(s,U).availability.rule_ref,'availability.option.insufficient_support.v1')
        both=availability(s,N,N)
        self.assertEqual(both.reasons,(AvailabilityReason.RESOURCE_NOT_PRESENT,AvailabilityReason.RESOURCE_NOT_ACCESSIBLE))
        self.assertEqual(len(both.availability.evidence_refs),2)

    def test_deterministic_identity_and_all_bindings_in_hash(self):
        s=self.seed; e=availability(s)
        self.assertEqual(e,availability(s))
        data=asdict(e); data.pop('evidence_id')
        raw=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
        self.assertEqual(e.evidence_id,'availability.option_presence.v1:'+hashlib.sha256(raw).hexdigest())
        for other in (availability(s,N),availability(s,pf=S),availability(s,option_id='other'),
                      availability(s,action=Action.LEAVE_TO_SAFE_FARM),availability(seed(gold=999))):
            self.assertNotEqual(e.evidence_id,other.evidence_id)

    def test_order_independence(self):
        s=self.seed
        inputs=(observation(s,option_id='z'),observation(s,N,option_id='a',action=Action.LEAVE_TO_SAFE_FARM))
        self.assertEqual(build_option_availability(s.seed_id,inputs),build_option_availability(s.seed_id,tuple(reversed(inputs))))

    def test_immutable_inputs_and_outputs(self):
        s=self.seed; o=observation(s); before=asdict(o)
        e=build_option_availability(s.seed_id,(o,))[0]
        self.assertEqual(before,asdict(o))
        with self.assertRaises(FrozenInstanceError): o.access_state=N
        with self.assertRaises(FrozenInstanceError): e.option_id='different'
        with self.assertRaises(FrozenInstanceError): e.availability.value=N
        with self.assertRaises(FrozenInstanceError): e.observations[0].value=N

    def test_schema_has_no_safety_risk_or_recommendation(self):
        e=availability(self.seed)
        self.assertEqual(set(asdict(e)),{'evidence_id','seed_id','option_id','action','observations','availability','reasons','ruleset'})
        self.assertEqual(set(asdict(observation(self.seed))),{'seed_id','option_id','action','resource_presence','presence_freshness','access_state','access_freshness'})
        for action in PRODUCTIVE_ACTIONS: self.assertIs(availability(self.seed,action=action).action,action)

    def test_hero_economy_and_match_time_do_not_affect_rule(self):
        original=availability(self.seed)
        changed=availability(seed(hero='other',level=99,gold=999,gpm=0,time=9999))
        self.assertEqual(original.availability,changed.availability)
        self.assertEqual(original.observations,changed.observations)
        self.assertEqual(original.reasons,changed.reasons)

    def test_no_risk_dependency(self):
        s=self.seed; e=availability(s)
        for rv in Truth:
            r=risk_for(s,rv)
            ctx=compose(s,r,((e,safety(s,r)),))
            self.assertEqual(ctx.options[0].available.value,Y)
            self.assertEqual(e,availability(s))

    def test_available_safe_full_chain_selects_each_supplied_action(self):
        s=self.seed; r=risk_for(s)
        for action in PRODUCTIVE_ACTIONS:
            ctx=compose(s,r,((availability(s,action=action),safety(s,r,action=action)),))
            self.assertEqual(farm_cycle.plan(ctx).next_action,action)

    def test_unknown_availability_with_safety_yes_not_actionable(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,((availability(s,Y,U),safety(s,r)),))
        self.assertEqual(ctx.options[0].available.value,U)
        self.assertEqual(ctx.options[0].safe.value,Y)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_available_unsafe_not_actionable(self):
        s=self.seed; r=risk_for(s,Y)
        ctx=compose(s,r,((availability(s),safety(s,r,Exposure.HIGH,N)),))
        self.assertEqual(ctx.options[0].available.value,Y)
        self.assertEqual(ctx.options[0].safe.value,N)
        result=farm_cycle.plan(ctx)
        self.assertEqual(result.next_action,Action.NO_DIRECTIVE)
        self.assertEqual(result.output_authority,Authority.AWARENESS)

    def test_wave_unavailable_farm_available_safe(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,((availability(s,N),safety(s,r)),
            (availability(s,option_id='farm',action=Action.LEAVE_TO_SAFE_FARM),
             safety(s,r,option_id='farm',action=Action.LEAVE_TO_SAFE_FARM))))
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.LEAVE_TO_SAFE_FARM)

    def test_wave_available_safe_has_existing_priority(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,tuple((availability(s,option_id=action.value,action=action),
                              safety(s,r,option_id=action.value,action=action)) for action in PRODUCTIVE_ACTIONS))
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.TAKE_ONE_MORE_WAVE)

    def test_all_options_unavailable_no_fabricated_action(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,tuple((availability(s,N,option_id=action.value,action=action),
                              safety(s,r,option_id=action.value,action=action)) for action in PRODUCTIVE_ACTIONS))
        self.assertTrue(all(o.available.value==N for o in ctx.options))
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_stale_availability_composition_unknown(self):
        s=self.seed; r=risk_for(s)
        ctx=compose(s,r,((availability(s,pf=S),safety(s,r)),))
        self.assertEqual(ctx.options[0].available.value,U)
        self.assertEqual(ctx.options[0].available.freshness,S)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_multiple_options_independent(self):
        s=self.seed
        inputs=(observation(s,N,option_id='wave'),observation(s,option_id='farm',action=Action.LEAVE_TO_SAFE_FARM),
                observation(s,Y,U,option_id='short',action=Action.SAFE_RESOURCE_THEN_REEVALUATE))
        results=build_option_availability(s.seed_id,inputs)
        self.assertEqual({e.option_id:e.availability.value for e in results},{'wave':N,'farm':Y,'short':U})
        for e in results: self.assertTrue(all(f.ref.startswith('availability.option.'+e.option_id+'.') for f in e.observations))

    def test_no_previous_frame_memory(self):
        availability(self.seed)
        self.assertEqual(availability(self.seed,U,U).availability.value,U)

    def test_invalid_input_refused(self):
        s=self.seed
        for name in ('','bad.id','a b','é',None):
            with self.assertRaises(ValueError): observation(s,option_id=name)
        for kwargs in ({'presence':True},{'access':'YES'},{'pf':'FRESH'},{'af':None},
                       {'action':Action.NO_DIRECTIVE},{'action':'TAKE_ONE_MORE_WAVE'}):
            with self.assertRaises(ValueError): observation(s,**kwargs)
        with self.assertRaises(ValueError): build_option_availability('',())
        with self.assertRaises(TypeError): build_option_availability(s.seed_id,[observation(s)])
        with self.assertRaises(TypeError): build_option_availability(s.seed_id,(None,))
        with self.assertRaisesRegex(ValueError,'duplicate_option_id'):
            build_option_availability(s.seed_id,(observation(s),observation(s)))

    def test_no_io_clock_environment_process_or_planner(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        s=self.seed; inputs=(observation(s),); expected=build_option_availability(s.seed_id,inputs)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (farm_cycle,'plan'),(decision,'build_context'),(decision,'authorize_output')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]; environment=os.environ
        forbidden=AssertionError('Availability crossed pure evidence boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=build_option_availability(s.seed_id,inputs)
            actual[0].validate_binding(s.seed_id,'wave',Action.TAKE_ONE_MORE_WAVE)
        self.assertEqual(actual,expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_import_no_timing_scoring_and_live_isolation(self):
        tree=ast.parse(Path(option_availability.__file__).read_text(encoding='utf-8'))
        imports=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(a.name for a in n.names)
            if isinstance(n,ast.ImportFrom): imports.add('.'*n.level+(n.module or ''))
        self.assertEqual(imports,{'dataclasses','enum','hashlib','json','.decision'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Compare) and any(isinstance(op,(ast.Gt,ast.GtE,ast.Lt,ast.LtE)) for op in n.ops) for n in ast.walk(tree)))
        forbidden={'hero','items','level','gold','gpm','time','dimensions','exposure','coverage','increased_risk','respawn','distance'}
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)))
        root=Path(option_availability.__file__).resolve().parent.parent
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py',
                     'coach02/runtime_adapter.py','coach02/context_builder.py','coach02/safety_evidence.py',
                     'coach02/option_safety.py','coach02/farm_context.py','coach02/farm_cycle.py','coach02/vision.py'):
            other=ast.parse((root/path).read_text(encoding='utf-8'))
            for n in ast.walk(other):
                if isinstance(n,(ast.Import,ast.ImportFrom,ast.Call)):
                    self.assertNotIn('option_availability',ast.unparse(n),path)


if __name__=='__main__': unittest.main()
