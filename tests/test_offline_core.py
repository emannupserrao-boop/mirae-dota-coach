"""Adversarial cross-layer gate. Synthetic evidence, no production orchestrator."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import normalize
from coach02 import decision, farm_cycle
from coach02.context_builder import Eligibility, build_context_seed
from coach02.decision import (Action, Authority, Claim, Execution, ExecutionState, Freshness,
    Knownness, KnowledgeSnapshotRef, ObservedFact, ObservationSource, PlayerModelSnapshotRef,
    Reason, Source, Truth, Validity, authorize_output, validate_decision)
from coach02.runtime_adapter import adapt_state
from coach02.safety_evidence import (CoverageObservation, RelevantThreatObservation, ThreatState,
    build_risk_awareness)
from coach02.option_safety import (Exposure, FarmOptionSafetyObservation, OptionSafetyEvidence,
    build_option_safety)
from coach02.option_availability import FarmOptionAvailabilityObservation, build_option_availability
from coach02.strategic_evidence import assemble_farm_evidence
from coach02.farm_context import compose_farm_context

Y,N,U=Truth.YES,Truth.NO,Truth.UNKNOWN
F,S=Freshness.FRESH,Freshness.STALE
WAVE,FARM,SHORT=Action.TAKE_ONE_MORE_WAVE,Action.LEAVE_TO_SAFE_FARM,Action.SAFE_RESOURCE_THEN_REEVALUATE


@dataclass(frozen=True)
class Spec:
    option_id: str='wave'
    action: Action=WAVE
    exposure: Exposure=Exposure.LOW
    coverage: Truth=Y
    exposure_freshness: Freshness=F
    coverage_freshness: Freshness=F
    presence: Truth=Y
    access: Truth=Y
    presence_freshness: Freshness=F
    access_freshness: Freshness=F


def observed(name='enemy',state=ThreatState.VISIBLE_AWAY,freshness=F):
    return RelevantThreatObservation(name,state,freshness)


def prepare(state=None,threats=None,coverage=None,specs=(Spec(),),knowledge=None,player=None,reverse=False):
    state=normalize(payload()) if state is None else state
    runtime=adapt_state(state)
    seed=build_context_seed(runtime,knowledge or KnowledgeSnapshotRef('synthetic-not-loaded','v1'),
        player or PlayerModelSnapshotRef('synthetic-not-loaded','v1'))
    risk=build_risk_awareness(seed.seed_id,(observed(),) if threats is None else threats,
                            CoverageObservation(Y,F) if coverage is None else coverage)
    safe=build_option_safety(seed.seed_id,risk,tuple(FarmOptionSafetyObservation(seed.seed_id,o.option_id,
        o.action,o.exposure,o.exposure_freshness,o.coverage,o.coverage_freshness) for o in specs))
    available=build_option_availability(seed.seed_id,tuple(FarmOptionAvailabilityObservation(seed.seed_id,
        o.option_id,o.action,o.presence,o.presence_freshness,o.access,o.access_freshness) for o in specs))
    return dict(state=state,runtime=runtime,seed=seed,risk=risk,
                safety=tuple(reversed(safe)) if reverse else safe,
                availability=tuple(reversed(available)) if reverse else available)


def finish(prepared,execution=Execution()):
    p=dict(prepared)
    p['assembly']=assemble_farm_evidence(p['seed'],p['risk'],p['safety'],p['availability'],execution)
    p['context']=compose_farm_context(p['seed'],p['assembly'].strategic_evidence,p['assembly'].execution)
    p['decision']=farm_cycle.plan(p['context'])
    p['output']=authorize_output(p['decision'],p['context'])
    return p


def full(**kwargs):
    return finish(prepare(**kwargs))


def independent_short(p):
    # Explicit independent expert fixture, never claimed as output of the narrow
    # Option Safety v0.1 ruleset. Used only for productive information wait.
    rule='fixture.core.independent_short_safety.v1'
    fact=ObservedFact('fixture.core.short-supported',Y,F,source=ObservationSource.SAFETY_EVIDENCE)
    result=OptionSafetyEvidence('',p['seed'].seed_id,'short',SHORT,(fact,),
        Claim(Y,(fact.ref,),rule),(rule,),rule,p['risk'].evidence_id)
    raw=json.dumps(asdict(result),sort_keys=True,separators=(',',':')).encode()
    return replace(result,evidence_id=rule+':'+hashlib.sha256(raw).hexdigest())


class OfflineCoreTests(unittest.TestCase):
    def test_clean_wave_and_disabled_output_authority(self):
        p=full()
        self.assertEqual(p['output'].next_action,WAVE)
        self.assertEqual(p['output'].authority,Authority.DIRECTIVE)
        self.assertEqual(authorize_output(p['decision'],p['context'],enabled=False).authority,Authority.SUPPRESS)
        self.assertEqual(p['decision'].output_authority,Authority.DIRECTIVE)

    def test_unknown_and_stale_threat_do_not_certify_safe(self):
        for threat in (observed(state=ThreatState.UNKNOWN),observed(freshness=S)):
            p=full(threats=(threat,))
            self.assertEqual(p['risk'].increased_risk.value,U)
            self.assertEqual(p['context'].options[0].safe.value,U)
            self.assertEqual(p['output'].authority,Authority.ADVISORY)
            self.assertEqual(p['output'].next_action,Action.HOLD_AND_REEVALUATE)

    def test_high_risk_unsafe_wave_does_not_invent_safe_farm(self):
        p=full(threats=(observed(state=ThreatState.VISIBLE_NEARBY),),specs=(
            Spec(exposure=Exposure.HIGH,coverage=N),Spec('farm',FARM)))
        options={o.plan_id:o for o in p['context'].options}
        self.assertEqual(options['wave'].safe.value,N)
        self.assertEqual(options['farm'].safe.value,U)
        self.assertEqual(p['decision'].next_action,Action.NO_DIRECTIVE)
        self.assertEqual(p['output'].authority,Authority.AWARENESS)

    def test_safety_availability_independence_and_explicit_unavailable(self):
        cases=((Spec(access=U),Y,U),(Spec(exposure=Exposure.UNKNOWN),U,Y),(Spec(presence=N),Y,N))
        for spec,safe,available in cases:
            p=full(specs=(spec,)); option=p['context'].options[0]
            self.assertEqual((option.safe.value,option.available.value),(safe,available))
            self.assertEqual(p['output'].authority,Authority.ADVISORY)
            self.assertEqual(p['output'].next_action,Action.HOLD_AND_REEVALUATE)

    def test_risk_without_any_option_is_awareness(self):
        p=full(threats=(observed(state=ThreatState.VISIBLE_NEARBY),),specs=())
        self.assertEqual(p['assembly'].option_pairs,())
        self.assertEqual(p['output'].authority,Authority.AWARENESS)
        self.assertEqual(p['output'].next_action,Action.NO_DIRECTIVE)

    def test_productive_information_wait_independent_fixture_labelled(self):
        p=prepare(threats=(observed(state=ThreatState.UNKNOWN),),specs=(Spec(),Spec('farm',FARM),Spec('short',SHORT)))
        independent=independent_short(p)
        p['safety']=tuple(independent if e.option_id=='short' else e for e in p['safety'])
        p=finish(p)
        self.assertEqual(p['output'].next_action,SHORT)
        self.assertIn('fixture.core.independent',independent.ruleset)
        self.assertEqual(p['context'].increased_risk.value,U)
        self.assertTrue(all(o.safe.value==U for o in p['context'].options if o.plan_id!='short'))

    def test_active_route_becomes_unsafe(self):
        execution=Execution(ExecutionState.IN_PROGRESS,'farm')
        a=finish(prepare(specs=(Spec('farm',FARM),)),execution)
        b=finish(prepare(threats=(observed(state=ThreatState.VISIBLE_NEARBY),),
            specs=(Spec('farm',FARM,Exposure.HIGH,N),)),execution)
        self.assertEqual(a['decision'].next_action,FARM)
        self.assertEqual(b['decision'].next_action,Action.ABORT_CURRENT_ROUTE)
        self.assertEqual(b['output'].authority,Authority.DIRECTIVE)
        self.assertEqual(authorize_output(a['decision'],b['context']).authority,Authority.SUPPRESS)

    def test_active_route_loses_confirmation_without_material_danger(self):
        execution=Execution(ExecutionState.IN_PROGRESS,'farm')
        a=finish(prepare(specs=(Spec('farm',FARM),)),execution)
        for spec in (Spec('farm',FARM,Exposure.UNKNOWN),Spec('farm',FARM,exposure_freshness=S)):
            b=finish(prepare(specs=(spec,)),execution)
            self.assertEqual(b['decision'].next_action,Action.HOLD_AND_REEVALUATE)
            self.assertEqual(b['output'].authority,Authority.ADVISORY)
            self.assertIn(Reason.ROUTE_UNCONFIRMED,b['decision'].reason_codes)
            self.assertEqual(authorize_output(a['decision'],b['context']).authority,Authority.SUPPRESS)

    def test_old_decision_expires_from_stale_observation_without_truth_change(self):
        a=full(); b=full(specs=(Spec(presence_freshness=S),))
        old_facts={f.ref:f for f in a['availability'][0].observations}
        new_facts={f.ref:f for f in b['availability'][0].observations}
        self.assertEqual({k:f.value for k,f in old_facts.items()},{k:f.value for k,f in new_facts.items()})
        self.assertEqual(validate_decision(a['decision'],b['context']).state,Validity.EXPIRED)
        self.assertEqual(authorize_output(a['decision'],b['context']).authority,Authority.SUPPRESS)

    def test_old_decision_invalidates_from_evidence_and_execution_change(self):
        a=full(); b=full(specs=(Spec(presence=N),))
        self.assertEqual(validate_decision(a['decision'],b['context']).state,Validity.INVALID)
        self.assertEqual(authorize_output(a['decision'],b['context']).authority,Authority.SUPPRESS)
        active=finish(prepare(),Execution(ExecutionState.IN_PROGRESS,'wave'))
        self.assertIn(Reason.EXECUTION_CHANGED,validate_decision(a['decision'],active['context']).reasons)

    def test_snapshot_version_changes_invalidate_without_loading_contents(self):
        a=full()
        for kwargs in ({'knowledge':KnowledgeSnapshotRef('synthetic-not-loaded','v2')},
                       {'player':PlayerModelSnapshotRef('synthetic-not-loaded','v2')}):
            b=full(**kwargs)
            self.assertEqual(a['runtime'],b['runtime'])
            self.assertNotEqual(a['seed'].seed_id,b['seed'].seed_id)
            self.assertIn(Reason.SNAPSHOT_CHANGED,validate_decision(a['decision'],b['context']).reasons)
            self.assertEqual(authorize_output(a['decision'],b['context']).authority,Authority.SUPPRESS)

    def test_foreign_seed_each_envelope_rejected(self):
        a=prepare(); b=prepare(state=replace(a['state'],gold=999))
        for field in ('risk','safety','availability'):
            mixed=dict(a); mixed[field]=b[field]
            with self.assertRaises(ValueError): finish(mixed)

    def test_foreign_risk_same_truth_rejected(self):
        a=prepare(); b=prepare(threats=(observed('different'),))
        self.assertEqual(a['risk'].increased_risk.value,b['risk'].increased_risk.value)
        self.assertNotEqual(a['risk'].evidence_id,b['risk'].evidence_id)
        a['risk']=b['risk']
        with self.assertRaisesRegex(ValueError,'option_safety_risk_mismatch'): finish(a)

    def test_orphans_and_action_mismatch_rejected(self):
        for field,error in (('safety','unpaired_option_availability'),('availability','unpaired_option_safety')):
            p=prepare(); p[field]=()
            with self.assertRaisesRegex(ValueError,error): finish(p)
        p=prepare(); p['availability']=(replace(p['availability'][0],action=FARM),)
        with self.assertRaisesRegex(ValueError,'availability_action_mismatch'): finish(p)

    def test_collision_value_freshness_source_rejected(self):
        for attribute,value in (('value',U),('freshness',S),('source',Source.RUNTIME_OBSERVATION)):
            p=prepare(); fact=replace(p['risk'].observations[0],**{attribute:value})
            p['availability']=(replace(p['availability'][0],observations=p['availability'][0].observations+(fact,)),)
            with self.assertRaisesRegex(ValueError,'conflicting_observation_ref'): finish(p)

    def test_multiple_options_same_action_rejected(self):
        p=prepare(specs=(Spec('one',FARM),Spec('two',FARM)))
        with self.assertRaisesRegex(ValueError,'multiple_options_per_action_not_supported'): finish(p)

    def test_cross_option_isolation_and_assembler_claim_identity(self):
        p=full(specs=(Spec(presence=N),Spec('farm',FARM),Spec('short',SHORT,Exposure.HIGH)))
        conditions={o.plan_id:o for o in p['context'].options}
        self.assertEqual((conditions['wave'].available.value,conditions['farm'].available.value),(N,Y))
        self.assertEqual((conditions['farm'].safe.value,conditions['short'].safe.value),(Y,U))
        self.assertEqual(p['decision'].next_action,FARM)
        for pair in p['assembly'].option_pairs:
            a=next(o for o in p['assembly'].strategic_evidence.assessments if o.plan_id==pair.option_id)
            self.assertIs(a.safe,pair.safety.safety)
            self.assertIs(a.available,pair.availability.availability)
            self.assertTrue(all(ref.startswith('availability.option.'+pair.option_id+'.') for ref in a.available.evidence_refs))
            self.assertTrue(all(ref.startswith('safety.option.'+pair.option_id+'.') for ref in a.safe.evidence_refs if ref.startswith('safety.option.')))
            self.assertEqual(conditions[pair.option_id].safe.provenance[-1].ref,pair.safety.safety.rule_ref)
        self.assertIs(p['assembly'].strategic_evidence.increased_risk,p['risk'].increased_risk)

    def test_optional_economy_unknown_not_strategy_or_ineligibility(self):
        a=full(); state=replace(a['state'],gold=None,lh=None,gpm=None,xpm=None)
        b=full(state=state)
        self.assertEqual(b['seed'].eligibility,Eligibility.ELIGIBLE)
        dims={s.provenance.ref:s for s in b['runtime'].scalars}
        for name in ('gold','lh','gpm','xpm'): self.assertEqual(dims['State.'+name].knownness,Knownness.UNKNOWN)
        self.assertEqual(a['context'].conditions,b['context'].conditions)
        self.assertEqual(a['decision'].next_action,b['decision'].next_action)

    def test_nonlocal_dead_and_unknown_required_block_composition(self):
        base=normalize(payload())
        for change,status in (({'local':False},Eligibility.INELIGIBLE),({'alive':False},Eligibility.INELIGIBLE),
                              ({'alive':None},Eligibility.INSUFFICIENT_DATA)):
            p=prepare(state=replace(base,**change))
            self.assertEqual(p['seed'].eligibility,status)
            with self.assertRaisesRegex(ValueError,'seed_not_eligible'): finish(p)

    def test_observed_zero_false_stay_known(self):
        state=normalize(payload(t=0,lh=0,gold=0,gpm=0,xpm=0))
        runtime=adapt_state(replace(state,alive=False))
        dims={s.provenance.ref:s for s in runtime.scalars}
        for name in ('time','gold','lh','gpm','xpm'):
            self.assertEqual(dims['State.'+name].knownness,Knownness.KNOWN)
            self.assertEqual(dims['State.'+name].value,0)
        for name in ('alive','buyback'):
            self.assertEqual(dims['State.'+name].knownness,Knownness.KNOWN)
            self.assertIs(dims['State.'+name].value,False)

    def test_entire_pipeline_deterministic_and_immutable(self):
        first=full(); second=full()
        self.assertEqual(first,second)
        with self.assertRaises(FrozenInstanceError): first['seed'].seed_id='mutated'
        with self.assertRaises(FrozenInstanceError): first['assembly'].execution.plan_id='mutated'
        with self.assertRaises(FrozenInstanceError): first['decision'].selected_plan.plan_id='mutated'

    def test_permutations_of_all_unordered_inputs(self):
        threats=(observed('z'),observed('a'))
        specs=(Spec(),Spec('farm',FARM),Spec('short',SHORT))
        a=full(threats=threats,specs=specs)
        b=full(threats=tuple(reversed(threats)),specs=tuple(reversed(specs)),reverse=True)
        for key in ('runtime','seed','risk','assembly','context','decision','output'):
            self.assertEqual(a[key],b[key],key)
        for key in ('safety','availability'):
            self.assertEqual({e.option_id:e for e in a[key]},{e.option_id:e for e in b[key]})

    def test_meaningful_changes_affect_only_dependent_identities(self):
        a=full(); b=full(specs=(Spec(presence=N),))
        for key in ('runtime','seed','risk','safety'): self.assertEqual(a[key],b[key],key)
        self.assertNotEqual(a['availability'][0].evidence_id,b['availability'][0].evidence_id)
        self.assertNotEqual(a['assembly'].assembly_id,b['assembly'].assembly_id)
        self.assertNotEqual(a['decision'].decision_id,b['decision'].decision_id)

    def test_no_carry_forward_and_old_advisory_is_not_permanent(self):
        full()
        unknown=full(threats=(observed(state=ThreatState.UNKNOWN),))
        self.assertEqual(unknown['risk'].increased_risk.value,U)
        self.assertEqual(unknown['output'].authority,Authority.ADVISORY)
        fresh=full()
        self.assertEqual(authorize_output(unknown['decision'],fresh['context']).authority,Authority.SUPPRESS)

    def test_audit_lineage_and_provenance(self):
        p=full()
        audit={key:asdict(p[key]) for key in ('state','runtime','seed','risk','assembly','context','decision','output')}
        audit['safety']=[asdict(e) for e in p['safety']]
        audit['availability']=[asdict(e) for e in p['availability']]
        json.dumps(audit,allow_nan=False)
        self.assertTrue(all(s.provenance.source is Source.RUNTIME_OBSERVATION for s in p['runtime'].scalars))
        self.assertEqual(p['runtime'].facts,())
        self.assertTrue(all(f.source is ObservationSource.SAFETY_EVIDENCE for f in p['assembly'].strategic_evidence.observations))
        self.assertEqual({s.source for s in p['decision'].provenance},
            {Source.RUNTIME_OBSERVATION,Source.KNOWLEDGE_SNAPSHOT,Source.PLAYER_MODEL,Source.EXPERT_HEURISTIC,ObservationSource.SAFETY_EVIDENCE})
        self.assertIn(farm_cycle.RULESET,{v.ref for v in p['decision'].provenance})
        self.assertNotIn(p['assembly'].ruleset,{v.ref for v in p['decision'].provenance})
        for condition in p['context'].conditions:
            self.assertIs(condition.provenance[-1].source,Source.EXPERT_HEURISTIC)
        self.assertEqual(p['seed'].observation_id,p['runtime'].observation_id)
        self.assertEqual(p['decision'].knowledge,p['seed'].knowledge)
        self.assertEqual(p['decision'].player,p['seed'].player)
        self.assertEqual(p['assembly'].risk.evidence_id,p['risk'].evidence_id)
        self.assertEqual(p['assembly'].option_pairs[0].safety,p['safety'][0])
        self.assertEqual(p['assembly'].option_pairs[0].availability,p['availability'][0])
        self.assertEqual(p['assembly'].execution,p['decision'].execution)

    def test_missing_information_never_creates_enemy_location(self):
        for state in (ThreatState.MISSING,ThreatState.UNKNOWN):
            p=full(threats=(observed(state=state),),coverage=CoverageObservation(N,F))
            expected=Y if state==ThreatState.MISSING else U
            self.assertEqual(p['risk'].increased_risk.value,expected)
            self.assertEqual(set(asdict(p['risk'])),{'evidence_id','seed_id','observations','increased_risk','reasons','ruleset'})
            forbidden=('gank_confirmed','enemy_position','coordinates','rotation_target','probability')
            self.assertFalse(any(word in json.dumps(asdict(p['risk'])) for word in forbidden))
            self.assertNotEqual(p['output'].authority,Authority.DIRECTIVE)

    def test_hero_and_economy_values_not_strategic_rules(self):
        a=full(); b=full(state=replace(a['state'],hero='generic-other',level=99,gold=99999,lh=999,gpm=9999,xpm=9999,time=9999))
        self.assertNotEqual(a['seed'].seed_id,b['seed'].seed_id)
        self.assertEqual(a['context'].conditions,b['context'].conditions)
        self.assertEqual(a['decision'].next_action,b['decision'].next_action)
        self.assertEqual(a['decision'].reason_codes,b['decision'].reason_codes)

    def test_inventory_and_abilities_are_not_in_offline_projection(self):
        base=payload(); changed=payload()
        changed['items']={'slot0':{'name':'item_bfury'},'slot1':{'name':'item_black_king_bar'}}
        changed['abilities']={'ability0':{'name':'other','level':99,'cooldown':999,'can_cast':False}}
        a=full(state=normalize(base)); b=full(state=normalize(changed))
        self.assertNotEqual(a['state'],b['state'])
        for key in ('runtime','seed','risk','safety','availability','assembly','context','decision','output'):
            self.assertEqual(a[key],b[key],key)

    def test_independent_fresh_fact_can_dominate_unrelated_uncertainty(self):
        p=full(threats=(observed('direct',ThreatState.VISIBLE_NEARBY),observed('old',ThreatState.UNKNOWN,S)),
            coverage=CoverageObservation(U,S),specs=(Spec(exposure=Exposure.HIGH,coverage=N,presence=N,access=U,access_freshness=S),))
        self.assertEqual(p['context'].increased_risk.value,Y)
        self.assertEqual(p['context'].options[0].safe.value,N)
        self.assertEqual(p['context'].options[0].available.value,N)
        self.assertEqual(p['output'].authority,Authority.AWARENESS)

    def test_complete_core_is_pure_without_hidden_global_changes(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        # Existing local fixture is constructed before blocking sinks. The actual
        # core including normalize, all builders, assembly and output runs inside.
        data=payload(); expected=full(state=normalize(data)); before=json.dumps(data,sort_keys=True)
        future=dict(farm_cycle.FUTURE)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]; environment=os.environ
        forbidden=AssertionError('Offline core crossed pure evaluation boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=full(state=normalize(data))
        self.assertEqual(actual,expected)
        self.assertEqual(before,json.dumps(data,sort_keys=True))
        self.assertEqual(future,farm_cycle.FUTURE)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_dependency_direction_no_live_call_and_no_numeric_strategy(self):
        root=Path(decision.__file__).resolve().parent.parent
        allowed={
            'decision':set(), 'runtime_adapter':{'decision'}, 'context_builder':{'decision','runtime_adapter'},
            'safety_evidence':{'decision'}, 'option_safety':{'decision','safety_evidence'},
            'option_availability':{'decision'},
            'strategic_evidence':{'context_builder','decision','farm_context','option_availability','option_safety','safety_evidence'},
            'farm_context':{'context_builder','decision'}, 'farm_cycle':{'decision'}}
        graph={}
        for module,expected in allowed.items():
            tree=ast.parse((root/'coach02'/f'{module}.py').read_text(encoding='utf-8'))
            deps={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level==1}
            self.assertEqual(deps,expected,module); graph[module]=deps
            calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
            self.assertNotIn('plan',calls); self.assertNotIn('farm_cycle.plan',calls)
            self.assertNotIn('compose_farm_context',calls)
            if module not in ('decision','runtime_adapter','context_builder'):
                self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in
                    {'hero','level','gold','gpm','xpm','time','inventory','score','probability'} for n in ast.walk(tree)),module)
            # dict.items is container iteration, not inventory inspection.
            self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr=='items' and
                isinstance(n.value,ast.Name) and n.value.id in {'state','hero','player','inventory'} for n in ast.walk(tree)),module)
        def visit(node,path):
            self.assertNotIn(node,path)
            for dep in graph[node]: visit(dep,path+(node,))
        for module in graph: visit(module,())
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py','coach02/vision.py'):
            tree=ast.parse((root/path).read_text(encoding='utf-8'))
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom): self.assertNotIn((n.module or '').split('.')[-1],allowed,path)
                if isinstance(n,ast.Import):
                    self.assertFalse(any(a.name.split('.')[-1] in allowed for a in n.names),path)
        tests=ast.parse(Path(__file__).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.Call) and ast.unparse(n.func) in
            {'DecisionContext','FarmStrategicEvidence','OptionAssessment'} for n in ast.walk(tests)))


if __name__=='__main__': unittest.main()
