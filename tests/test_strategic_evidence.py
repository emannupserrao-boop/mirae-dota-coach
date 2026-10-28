"""Complete synthetic pipeline through canonical assembly, never manual merging."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import normalize
from coach02 import (context_builder, decision, farm_context, farm_cycle,
    option_availability, option_safety, safety_evidence, strategic_evidence)
from coach02.context_builder import build_context_seed
from coach02.decision import (Action, Authority, Claim, Execution, ExecutionState,
    Freshness, KnowledgeSnapshotRef, ObservedFact, ObservationSource,
    PlayerModelSnapshotRef, Source, Truth)
from coach02.farm_context import compose_farm_context
from coach02.option_availability import FarmOptionAvailabilityObservation, build_option_availability
from coach02.option_safety import Exposure, FarmOptionSafetyObservation, OptionSafetyEvidence, build_option_safety
from coach02.runtime_adapter import adapt_state
from coach02.safety_evidence import CoverageObservation, RelevantThreatObservation, ThreatState, build_risk_awareness
from coach02.strategic_evidence import assemble_farm_evidence

Y,N,U=Truth.YES,Truth.NO,Truth.UNKNOWN
F,S=Freshness.FRESH,Freshness.STALE
WAVE,FARM,SHORT=Action.TAKE_ONE_MORE_WAVE,Action.LEAVE_TO_SAFE_FARM,Action.SAFE_RESOURCE_THEN_REEVALUATE


def seed(**changes):
    return build_context_seed(adapt_state(replace(normalize(payload()),**changes)),
        KnowledgeSnapshotRef('not-loaded','v1'),PlayerModelSnapshotRef('not-loaded','v1'))


def risk_for(s,value=N,name='enemy'):
    state={Y:ThreatState.VISIBLE_NEARBY,N:ThreatState.VISIBLE_AWAY,U:ThreatState.UNKNOWN}[value]
    return build_risk_awareness(s.seed_id,(RelevantThreatObservation(name,state,F),),CoverageObservation(Y,F))


def envelopes(s,r,option_id='wave',action=WAVE,exposure=Exposure.LOW,coverage=Y,presence=Y,access=Y):
    safe=build_option_safety(s.seed_id,r,(FarmOptionSafetyObservation(
        s.seed_id,option_id,action,exposure,F,coverage,F),))[0]
    available=build_option_availability(s.seed_id,(FarmOptionAvailabilityObservation(
        s.seed_id,option_id,action,presence,F,access,F),))[0]
    return safe,available


def assemble(s,r,pairs=(),execution=Execution()):
    # No OptionAssessment, fact merge or FarmStrategicEvidence construction here.
    return assemble_farm_evidence(s,r,tuple(p[0] for p in pairs),tuple(p[1] for p in pairs),execution)


def consume(s,assembly):
    return compose_farm_context(s,assembly.strategic_evidence,assembly.execution)


def independent_safety(s,r,option_id,action):
    # Explicit independent fixture, NOT an output claimed for the Option Safety
    # v0.1 rules (which cannot yield YES with global risk YES).
    rule='fixture.independent_option_safety.v1'
    fact=ObservedFact('fixture.independent.'+option_id,Y,F,source=ObservationSource.SAFETY_EVIDENCE)
    result=OptionSafetyEvidence('',s.seed_id,option_id,action,(fact,),
        Claim(Y,(fact.ref,),rule),(rule,),rule,r.evidence_id)
    raw=json.dumps(asdict(result),sort_keys=True,separators=(',',':')).encode()
    return replace(result,evidence_id=rule+':'+hashlib.sha256(raw).hexdigest())


class StrategicEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.seed=seed(); self.risk=risk_for(self.seed)
        self.safe,self.available=envelopes(self.seed,self.risk)

    def test_safe_wave_complete_pipeline(self):
        s=self.seed; a=assemble(s,self.risk,((self.safe,self.available),))
        self.assertEqual(farm_cycle.plan(consume(s,a)).next_action,WAVE)

    def test_unsafe_wave_and_independently_safe_farm(self):
        s=self.seed; r=risk_for(s,Y)
        wave=envelopes(s,r,exposure=Exposure.HIGH,coverage=N)
        _,available=envelopes(s,r,'farm',FARM)
        safe=independent_safety(s,r,'farm',FARM)
        a=assemble(s,r,(wave,(safe,available)))
        ctx=consume(s,a)
        self.assertEqual(next(o for o in ctx.options if o.plan_id=='wave').safe.value,N)
        self.assertEqual(farm_cycle.plan(ctx).next_action,FARM)

    def test_productive_information_wait(self):
        s=self.seed; r=risk_for(s,U)
        wave=envelopes(s,r); farm=envelopes(s,r,'farm',FARM)
        _,available=envelopes(s,r,'short',SHORT)
        safe=independent_safety(s,r,'short',SHORT)
        a=assemble(s,r,(wave,farm,(safe,available)))
        self.assertEqual(farm_cycle.plan(consume(s,a)).next_action,SHORT)

    def test_risk_without_route(self):
        s=self.seed; r=risk_for(s,Y)
        a=assemble(s,r,(envelopes(s,r,exposure=Exposure.HIGH,coverage=N),))
        result=farm_cycle.plan(consume(s,a))
        self.assertEqual(result.next_action,Action.NO_DIRECTIVE)
        self.assertEqual(result.output_authority,Authority.AWARENESS)

    def test_unknown_preserved(self):
        s=self.seed; r=risk_for(s,U)
        a=assemble(s,r,(envelopes(s,r,presence=U),))
        ctx=consume(s,a)
        self.assertEqual(ctx.increased_risk.value,U)
        self.assertEqual(ctx.options[0].safe.value,U)
        self.assertEqual(ctx.options[0].available.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_active_route_becomes_unsafe(self):
        s=self.seed; execution=Execution(ExecutionState.IN_PROGRESS,'farm')
        before=assemble(s,self.risk,(envelopes(s,self.risk,'farm',FARM),),execution)
        self.assertEqual(farm_cycle.plan(consume(s,before)).next_action,FARM)
        r=risk_for(s,Y)
        after=assemble(s,r,(envelopes(s,r,'farm',FARM,Exposure.HIGH,N),),execution)
        self.assertIs(after.execution,execution)
        self.assertEqual(farm_cycle.plan(consume(s,after)).next_action,Action.ABORT_CURRENT_ROUTE)

    def test_unavailable_safe_option_not_actionable(self):
        s=self.seed; a=assemble(s,self.risk,(envelopes(s,self.risk,presence=N),))
        ctx=consume(s,a)
        self.assertEqual(ctx.options[0].safe.value,Y)
        self.assertEqual(ctx.options[0].available.value,N)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_available_unsafe_option_not_actionable(self):
        s=self.seed; r=risk_for(s,Y)
        ctx=consume(s,assemble(s,r,(envelopes(s,r,exposure=Exposure.HIGH,coverage=N),)))
        self.assertEqual(ctx.options[0].available.value,Y)
        self.assertEqual(ctx.options[0].safe.value,N)
        self.assertNotEqual(farm_cycle.plan(ctx).next_action,WAVE)

    def test_orphan_safety(self):
        with self.assertRaisesRegex(ValueError,'unpaired_option_safety'):
            assemble_farm_evidence(self.seed,self.risk,(self.safe,),(),Execution())

    def test_orphan_availability(self):
        with self.assertRaisesRegex(ValueError,'unpaired_option_availability'):
            assemble_farm_evidence(self.seed,self.risk,(),(self.available,),Execution())

    def test_seed_mismatches(self):
        other=seed(gold=999)
        with self.assertRaisesRegex(ValueError,'risk_seed_mismatch'):
            assemble(other,self.risk)
        with self.assertRaisesRegex(ValueError,'option_safety_seed_mismatch'):
            assemble(self.seed,self.risk,((replace(self.safe,seed_id=other.seed_id),self.available),))
        with self.assertRaisesRegex(ValueError,'availability_seed_mismatch'):
            assemble(self.seed,self.risk,((self.safe,replace(self.available,seed_id=other.seed_id)),))

    def test_exact_risk_identity_mismatch(self):
        other=risk_for(self.seed,N,'another-enemy')
        with self.assertRaisesRegex(ValueError,'option_safety_risk_mismatch'):
            assemble(self.seed,other,((self.safe,self.available),))

    def test_action_mismatch_same_option_id(self):
        with self.assertRaisesRegex(ValueError,'availability_action_mismatch'):
            assemble(self.seed,self.risk,((self.safe,replace(self.available,action=FARM)),))

    def test_option_mismatch_same_action_not_paired(self):
        with self.assertRaisesRegex(ValueError,'unpaired_option_safety'):
            assemble(self.seed,self.risk,((self.safe,replace(self.available,option_id='other')),))

    def test_fact_collisions_value_freshness_and_source(self):
        fact=self.risk.observations[0]
        variants=(replace(fact,value=U),replace(fact,freshness=S),replace(fact,source=Source.RUNTIME_OBSERVATION))
        for changed in variants:
            modified=replace(self.available,observations=self.available.observations+(changed,))
            with self.assertRaisesRegex(ValueError,'conflicting_observation_ref'):
                assemble(self.seed,self.risk,((self.safe,modified),))

    def test_conflicts_inside_one_envelope_not_overwritten(self):
        fact=self.available.observations[0]
        modified=replace(self.available,observations=self.available.observations+(replace(fact,value=U),))
        with self.assertRaisesRegex(ValueError,'conflicting_observation_ref'):
            assemble(self.seed,self.risk,((self.safe,modified),))

    def test_identical_shared_facts_deduplicated_by_full_equality(self):
        available=replace(self.available,observations=self.available.observations+self.risk.observations)
        a=assemble(self.seed,self.risk,((self.safe,available),))
        expected={f.ref:f for f in self.risk.observations+self.safe.observations+available.observations}
        self.assertEqual(a.strategic_evidence.observations,tuple(expected[k] for k in sorted(expected)))
        self.assertEqual(len(a.strategic_evidence.observations),len(expected))

    def test_multiple_options_same_action_explicitly_unsupported(self):
        other=envelopes(self.seed,self.risk,'another-wave',WAVE)
        with self.assertRaisesRegex(ValueError,'multiple_options_per_action_not_supported'):
            assemble(self.seed,self.risk,((self.safe,self.available),other))

    def test_duplicate_safety_option_id(self):
        with self.assertRaisesRegex(ValueError,'duplicate_safety_option_id'):
            assemble_farm_evidence(self.seed,self.risk,(self.safe,self.safe),(self.available,),Execution())

    def test_duplicate_availability_option_id(self):
        with self.assertRaisesRegex(ValueError,'duplicate_availability_option_id'):
            assemble_farm_evidence(self.seed,self.risk,(self.safe,),(self.available,self.available),Execution())

    def test_empty_options_valid_and_conservative(self):
        for value in Truth:
            r=risk_for(self.seed,value); a=assemble(self.seed,r)
            self.assertEqual(a.option_pairs,())
            self.assertEqual(a.strategic_evidence.assessments,())
            result=farm_cycle.plan(consume(self.seed,a))
            self.assertIn(result.next_action,(Action.NO_DIRECTIVE,Action.HOLD_AND_REEVALUATE))

    def test_missing_risk_support_even_without_options(self):
        r=replace(self.risk,increased_risk=replace(self.risk.increased_risk,evidence_refs=('missing',)))
        with self.assertRaisesRegex(ValueError,'missing_claim_support'): assemble(self.seed,r)

    def test_missing_safety_support_cannot_be_backfilled_from_availability(self):
        safe=replace(self.safe,safety=replace(self.safe.safety,evidence_refs=(self.available.observations[0].ref,)))
        with self.assertRaisesRegex(ValueError,'missing_claim_support'):
            assemble(self.seed,self.risk,((safe,self.available),))

    def test_missing_availability_support_cannot_be_backfilled_from_safety(self):
        available=replace(self.available,availability=replace(self.available.availability,
            evidence_refs=(self.safe.observations[0].ref,)))
        with self.assertRaisesRegex(ValueError,'missing_claim_support'):
            assemble(self.seed,self.risk,((self.safe,available),))

    def test_safety_can_reference_accepted_upstream_risk(self):
        own=tuple(f for f in self.safe.observations if f.ref.startswith('safety.option.'))
        safe=replace(self.safe,observations=own)
        a=assemble(self.seed,self.risk,((safe,self.available),))
        self.assertIs(a.strategic_evidence.assessments[0].safe,safe.safety)
        self.assertEqual(consume(self.seed,a).options[0].safe.value,Y)

    def test_audit_envelope_retains_complete_upstream_after_context(self):
        execution=Execution(); a=assemble(self.seed,self.risk,((self.safe,self.available),),execution)
        consume(self.seed,a)
        self.assertEqual(a.seed_id,self.seed.seed_id)
        self.assertIs(a.risk,self.risk)
        self.assertIs(a.option_pairs[0].safety,self.safe)
        self.assertIs(a.option_pairs[0].availability,self.available)
        self.assertIs(a.execution,execution)
        self.assertEqual(a.option_pairs[0].option_id,'wave')
        self.assertIs(a.option_pairs[0].action,WAVE)

    def test_claims_preserved_without_semantic_recalculation(self):
        # Contradict the producer rules deliberately: assembly validates structure,
        # not mechanical truth. It must not author new values/rules.
        safe=replace(self.safe,safety=Claim(N,self.safe.safety.evidence_refs,'fixture.supplied_safety.v1'))
        available=replace(self.available,availability=Claim(U,self.available.availability.evidence_refs,'fixture.supplied_availability.v1'))
        a=assemble(self.seed,self.risk,((safe,available),))
        assessment=a.strategic_evidence.assessments[0]
        self.assertIs(assessment.safe,safe.safety)
        self.assertIs(assessment.available,available.availability)
        self.assertIs(a.strategic_evidence.increased_risk,self.risk.increased_risk)

    def test_provenance_unchanged_in_composition(self):
        a=assemble(self.seed,self.risk,((self.safe,self.available),))
        ctx=consume(self.seed,a)
        for c in ctx.conditions:
            self.assertTrue(all(p.source is ObservationSource.SAFETY_EVIDENCE for p in c.provenance[:-1]))
            self.assertIs(c.provenance[-1].source,Source.EXPERT_HEURISTIC)
            self.assertNotEqual(c.provenance[-1].ref,a.ruleset)
        self.assertEqual(ctx.options[0].safe.provenance[-1].ref,self.safe.safety.rule_ref)

    def test_runtime_fact_source_not_relabelled(self):
        extra=ObservedFact('fixture.runtime',Y,F)
        available=replace(self.available,observations=self.available.observations+(extra,),
            availability=Claim(Y,(extra.ref,),'fixture.runtime-supported-availability.v1'))
        a=assemble(self.seed,self.risk,((self.safe,available),))
        self.assertIs(consume(self.seed,a).options[0].available.provenance[0].source,Source.RUNTIME_OBSERVATION)

    def test_collection_order_does_not_pair_by_position_or_change_id(self):
        sf,af=envelopes(self.seed,self.risk,'farm',FARM)
        first=assemble_farm_evidence(self.seed,self.risk,(self.safe,sf),(af,self.available),Execution())
        second=assemble_farm_evidence(self.seed,self.risk,(sf,self.safe),(self.available,af),Execution())
        self.assertEqual(first,second)
        self.assertEqual(tuple(p.option_id for p in first.option_pairs),('farm','wave'))

    def test_identity_changes_for_upstream_content_and_execution(self):
        base=assemble(self.seed,self.risk,((self.safe,self.available),))
        variants=(replace(self.available,evidence_id='fixture.other-id'),
                  replace(self.available,availability=replace(self.available.availability,value=U)))
        for available in variants:
            self.assertNotEqual(base.assembly_id,assemble(self.seed,self.risk,((self.safe,available),)).assembly_id)
        active=assemble(self.seed,self.risk,((self.safe,self.available),),Execution(ExecutionState.IN_PROGRESS,'wave'))
        self.assertNotEqual(base.assembly_id,active.assembly_id)
        self.assertTrue(base.assembly_id.startswith('strategic.farm_evidence_assembly.v1:'))

    def test_observation_order_is_not_hash_semantics(self):
        base=assemble(self.seed,self.risk,((self.safe,self.available),))
        safe=replace(self.safe,observations=tuple(reversed(self.safe.observations)))
        available=replace(self.available,observations=tuple(reversed(self.available.observations)))
        changed=assemble(self.seed,self.risk,((safe,available),))
        self.assertEqual(base.assembly_id,changed.assembly_id)
        self.assertIs(changed.option_pairs[0].safety,safe)

    def test_determinism_immutability_no_input_mutation(self):
        before=(asdict(self.seed),asdict(self.risk),asdict(self.safe),asdict(self.available))
        a=assemble(self.seed,self.risk,((self.safe,self.available),))
        self.assertEqual(a,assemble(self.seed,self.risk,((self.safe,self.available),)))
        self.assertEqual(before,(asdict(self.seed),asdict(self.risk),asdict(self.safe),asdict(self.available)))
        with self.assertRaises(FrozenInstanceError): a.seed_id='changed'
        with self.assertRaises(FrozenInstanceError): a.option_pairs[0].option_id='changed'
        with self.assertRaises(FrozenInstanceError): a.strategic_evidence.increased_risk.value=Y

    def test_eligibility_remains_with_composer(self):
        s=seed(alive=False); r=risk_for(s)
        a=assemble(s,r,(envelopes(s,r),))
        with self.assertRaisesRegex(ValueError,'seed_not_eligible'): consume(s,a)

    def test_execution_not_inferred_or_modified(self):
        for execution in (Execution(),Execution(ExecutionState.IN_PROGRESS,'not-supplied')):
            a=assemble(self.seed,self.risk,(),execution)
            self.assertIs(a.execution,execution)
        invalid=Execution(ExecutionState.IN_PROGRESS,['mutable'])
        with self.assertRaisesRegex(ValueError,'execution_plan_reference_must_be_string'):
            assemble(self.seed,self.risk,(),invalid)

    def test_invalid_shapes_fail_explicitly(self):
        args=(self.seed,self.risk,(self.safe,),(self.available,),Execution())
        for index,value in ((0,self.seed.seed_id),(1,None),(2,[self.safe]),(3,[self.available]),(4,None)):
            changed=list(args); changed[index]=value
            with self.assertRaises(TypeError): assemble_farm_evidence(*changed)
        for safe in (replace(self.safe,reasons=['mutable']),replace(self.safe,evidence_id=''),
                     replace(self.safe,observations=list(self.safe.observations))):
            with self.assertRaises((ValueError,TypeError)):
                assemble(self.seed,self.risk,((safe,self.available),))

    def test_no_previous_assembly_state(self):
        assemble(self.seed,self.risk,((self.safe,self.available),))
        self.assertEqual(assemble(self.seed,self.risk).option_pairs,())

    def test_no_io_builders_composer_planner_or_eligibility_recalculation(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        args=(self.seed,self.risk,(self.safe,),(self.available,),Execution())
        expected=assemble_farm_evidence(*args)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (farm_cycle,'plan'),(decision,'build_context'),(decision,'authorize_output'),
            (context_builder,'build_context_seed'),(farm_context,'compose_farm_context'),
            (safety_evidence,'build_risk_awareness'),(option_safety,'build_option_safety'),
            (option_availability,'build_option_availability')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]; environment=os.environ
        forbidden=AssertionError('Assembly crossed pure envelope boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=assemble_farm_evidence(*args)
        self.assertEqual(actual,expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_no_gameplay_interpretation_or_live_integration(self):
        tree=ast.parse(Path(strategic_evidence.__file__).read_text(encoding='utf-8'))
        imports=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(a.name for a in n.names)
            if isinstance(n,ast.ImportFrom): imports.add('.'*n.level+(n.module or ''))
        self.assertEqual(imports,{'dataclasses','hashlib','json','.context_builder','.decision',
            '.farm_context','.option_availability','.option_safety','.safety_evidence'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        forbidden={'value','hero','inventory','level','gold','gpm','time','route','score',
                   'exposure','coverage','resource_presence','access_state','eligibility','dimensions'}

        def gameplay_attributes(parsed):
            parents={child:parent for parent in ast.walk(parsed) for child in ast.iter_child_nodes(parent)}
            violations=[]
            for node in ast.walk(parsed):
                if not isinstance(node,ast.Attribute): continue
                if node.attr in forbidden:
                    violations.append(ast.unparse(node))
                elif node.attr=='items':
                    call=parents.get(node)
                    iteration=parents.get(call)
                    receiver=node.value
                    # A bare/nested gameplay inventory attribute remains forbidden,
                    # even when called in a loop. Exempt only generic mapping.items()
                    # used as a normal key/value iterator; not arbitrary items calls.
                    generic_receiver=(isinstance(receiver,ast.Name) and not
                        {'state','hero','player','inventory'}.intersection(receiver.id.lower().split('_')))
                    mapping_iteration=(generic_receiver and isinstance(call,ast.Call)
                        and call.func is node and not call.args and not call.keywords
                        and isinstance(iteration,(ast.For,ast.comprehension))
                        and iteration.iter is call and isinstance(iteration.target,(ast.Tuple,ast.List))
                        and len(iteration.target.elts)==2)
                    if not mapping_iteration: violations.append(ast.unparse(node))
            return violations

        # Guard the exception itself without adding/disabling a discovered test.
        for snippet in ('for k, v in source.items(): pass',
                        '{k: v for k, v in value.items()}',
                        '[(k, v) for k, v in some_mapping.items()]'):
            with self.subTest(container_iteration=snippet):
                self.assertEqual(gameplay_attributes(ast.parse(snippet)),[])
        for snippet in ('state.items','hero.items','player.items','inventory.items',
                        'bag.items','state.inventory','hero_state.items',
                        'for k, v in state.items(): pass',
                        '{k: v for k, v in inventory.items()}',
                        'for k, v in state.inventory.items(): pass',
                        'some_mapping.items()', 'for item in some_mapping.items(): pass',
                        'state.hero','state.level','state.gold','state.gpm','state.time',
                        'planner.route','candidate.score'):
            with self.subTest(gameplay_access=snippet):
                self.assertTrue(gameplay_attributes(ast.parse(snippet)))
        self.assertEqual(gameplay_attributes(tree),[])
        root=Path(strategic_evidence.__file__).resolve().parent.parent
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py',
                     'coach02/runtime_adapter.py','coach02/context_builder.py','coach02/safety_evidence.py',
                     'coach02/option_safety.py','coach02/option_availability.py','coach02/farm_context.py',
                     'coach02/farm_cycle.py','coach02/vision.py'):
            other=ast.parse((root/path).read_text(encoding='utf-8'))
            for n in ast.walk(other):
                if isinstance(n,(ast.Import,ast.ImportFrom)):
                    self.assertNotIn('strategic_evidence',ast.unparse(n),path)
                if isinstance(n,ast.Call):
                    self.assertNotIn('strategic_evidence',ast.unparse(n.func),path)
        # The new pipeline never constructs legacy assessments/evidence in tests.
        tests=ast.parse(Path(__file__).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.Call) and ast.unparse(n.func) in
                            ('OptionAssessment','FarmStrategicEvidence') for n in ast.walk(tests)))


if __name__=='__main__': unittest.main()
