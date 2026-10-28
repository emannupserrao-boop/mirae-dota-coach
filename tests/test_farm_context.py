"""Synthetic offline composition fixtures; not verified Dota strategic truth."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
import unittest
from unittest.mock import patch

from coach.demo import payload
from coach.state import normalize
from coach02 import decision, farm_context, farm_cycle
from coach02.context_builder import Eligibility, build_context_seed
from coach02.decision import (Action, Authority, Claim, Execution, ExecutionState,
    Freshness, KnowledgeSnapshotRef, ObservedFact, OptionAssessment,
    PlayerModelSnapshotRef, RuntimeObservation, Source, Truth, context_id)
from coach02.farm_context import FarmStrategicEvidence, compose_farm_context
from coach02.runtime_adapter import adapt_state

Y, N, U = Truth.YES, Truth.NO, Truth.UNKNOWN
F, S = Freshness.FRESH, Freshness.STALE
KNOWLEDGE = KnowledgeSnapshotRef('synthetic-content-not-loaded', 'v1')
PLAYER = PlayerModelSnapshotRef('synthetic-history-not-loaded', 'v1')


def seed(state=None, knowledge=KNOWLEDGE, player=PLAYER):
    return build_context_seed(adapt_state(normalize(payload()) if state is None else state), knowledge, player)


def evidence(runtime_seed, *, wave=Y, farm=N, short=N, risk=N, threat=Y):
    # Separate supplied observations from the author's explicit strategic claims.
    facts = (ObservedFact('fixture.enemy-visible', threat, F),
             ObservedFact('fixture.wave-observed', Y, F),
             ObservedFact('fixture.farm-observed', Y, F),
             ObservedFact('fixture.farm-corridor-observed', Y, F),
             ObservedFact('fixture.short-observed', Y, F),
             ObservedFact('fixture.short-corridor-observed', Y, F))
    def claim(value, ref, rule): return Claim(value, (ref,), 'fixture.'+rule+'.v1')
    options = (
        OptionAssessment('wave', Action.TAKE_ONE_MORE_WAVE,
            claim(Y, 'fixture.wave-observed', 'wave-availability'),
            claim(wave, 'fixture.enemy-visible', 'wave-safety')),
        OptionAssessment('farm', Action.LEAVE_TO_SAFE_FARM,
            claim(farm, 'fixture.farm-observed', 'farm-availability'),
            claim(farm, 'fixture.farm-corridor-observed', 'farm-safety')),
        OptionAssessment('short', Action.SAFE_RESOURCE_THEN_REEVALUATE,
            claim(short, 'fixture.short-observed', 'short-availability'),
            claim(short, 'fixture.short-corridor-observed', 'short-safety')))
    return FarmStrategicEvidence(runtime_seed.seed_id, facts, options,
        claim(risk, 'fixture.enemy-visible', 'risk-assessment'))


def option(context, plan_id):
    return next(o for o in context.options if o.plan_id == plan_id)


class FarmContextTests(unittest.TestCase):
    def test_end_to_end_safe_wave(self):
        # Entire chain is explicit in the test; composition itself stops at context.
        state = normalize(payload(t=603, lh=50))
        obs = adapt_state(state)
        runtime_seed = build_context_seed(obs, KNOWLEDGE, PLAYER)
        ctx = compose_farm_context(runtime_seed, evidence(runtime_seed), Execution())
        result = farm_cycle.plan(ctx)
        self.assertEqual(option(ctx,'wave').safe.value,Y)
        self.assertEqual(result.next_action,Action.TAKE_ONE_MORE_WAVE)
        self.assertEqual(ctx.observation_id,obs.observation_id)

    def test_safe_farm_when_wave_support_unknown(self):
        s=seed()
        ctx=compose_farm_context(s,evidence(s,threat=U,farm=Y),Execution())
        self.assertEqual(option(ctx,'wave').safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.LEAVE_TO_SAFE_FARM)

    def test_productive_information_wait_with_unknown_threats(self):
        s=seed()
        ctx=compose_farm_context(s,evidence(s,threat=U,short=Y),Execution())
        self.assertEqual(option(ctx,'wave').safe.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.SAFE_RESOURCE_THEN_REEVALUATE)

    def test_risk_without_route_is_awareness_compatible(self):
        s=seed()
        ctx=compose_farm_context(s,evidence(s,wave=N,risk=Y),Execution())
        result=farm_cycle.plan(ctx)
        self.assertEqual(ctx.increased_risk.value,Y)
        self.assertEqual(result.next_action,Action.NO_DIRECTIVE)
        self.assertEqual(result.output_authority,Authority.AWARENESS)

    def test_end_to_end_unknown_never_becomes_safe(self):
        s=build_context_seed(adapt_state(normalize(payload())),KNOWLEDGE,PLAYER)
        ctx=compose_farm_context(s,evidence(s,wave=U,farm=U,short=U,risk=U),Execution())
        self.assertTrue(all(o.safe.value==U for o in ctx.options))
        result=farm_cycle.plan(ctx)
        self.assertEqual(result.next_action,Action.HOLD_AND_REEVALUATE)
        self.assertEqual(result.output_authority,Authority.ADVISORY)

    def test_stale_support_cannot_become_current(self):
        s=seed(); e=evidence(s)
        e=replace(e,observations=tuple(replace(f,freshness=S) if f.ref=='fixture.enemy-visible' else f for f in e.observations))
        ctx=compose_farm_context(s,e,Execution())
        self.assertEqual(option(ctx,'wave').safe.value,U)
        self.assertEqual(option(ctx,'wave').safe.freshness,S)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_missing_support_uses_existing_unknown_stale_semantics(self):
        s=seed(); e=evidence(s)
        e=replace(e,observations=tuple(f for f in e.observations if f.ref!='fixture.enemy-visible'))
        ctx=compose_farm_context(s,e,Execution())
        condition=option(ctx,'wave').safe
        self.assertEqual(condition.value,U)
        self.assertEqual(condition.evidence,(ObservedFact('fixture.enemy-visible',U,S),))
        self.assertEqual(condition.freshness,S)

    def test_yes_claim_without_references_is_unknown(self):
        s=seed(); e=evidence(s)
        e=replace(e,assessments=tuple(replace(o,safe=replace(o.safe,evidence_refs=())) if o.plan_id=='wave' else o for o in e.assessments))
        self.assertEqual(option(compose_farm_context(s,e,Execution()),'wave').safe.value,U)

    def test_missing_options_are_omitted_not_available_or_no(self):
        s=seed(); e=evidence(s)
        e=replace(e,assessments=(),increased_risk=Claim(U,(),'fixture.risk-not-supplied.v1'))
        ctx=compose_farm_context(s,e,Execution())
        self.assertEqual(ctx.options,())
        self.assertEqual(ctx.increased_risk.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_ineligible_seed_refused(self):
        for state in (replace(normalize(payload()),alive=False),replace(normalize(payload()),paused=True)):
            s=seed(state)
            self.assertEqual(s.eligibility,Eligibility.INELIGIBLE)
            with self.assertRaisesRegex(ValueError,'seed_not_eligible'):
                compose_farm_context(s,evidence(s),Execution())

    def test_insufficient_seed_refused(self):
        s=seed(replace(normalize(payload()),alive=None))
        self.assertEqual(s.eligibility,Eligibility.INSUFFICIENT_DATA)
        with self.assertRaisesRegex(ValueError,'seed_not_eligible'):
            compose_farm_context(s,evidence(s),Execution())

    def test_forged_eligibility_or_identity_refused(self):
        dead=seed(replace(normalize(payload()),alive=False))
        for s in (replace(dead,eligibility=Eligibility.ELIGIBLE),replace(seed(),seed_id='forged')):
            with self.assertRaisesRegex(ValueError,'inconsistent_seed'):
                compose_farm_context(s,evidence(s),Execution())

    def test_lineage_and_versions_are_preserved(self):
        s=seed(knowledge=replace(KNOWLEDGE,version='v2'),player=replace(PLAYER,version='v3'))
        ctx=compose_farm_context(s,evidence(s),Execution())
        self.assertIs(ctx.knowledge,s.knowledge)
        self.assertIs(ctx.player,s.player)
        self.assertEqual(ctx.observation_id,s.observation_id)

    def test_evidence_for_different_seed_or_lineage_is_refused(self):
        initial=seed(); e=evidence(initial)
        for other in (seed(knowledge=replace(KNOWLEDGE,version='v2')),
                      seed(player=replace(PLAYER,version='v2')),
                      seed(replace(normalize(payload()),gold=999))):
            with self.assertRaisesRegex(ValueError,'strategic_evidence_seed_mismatch'):
                compose_farm_context(other,e,Execution())

    def test_execution_not_started_is_preserved(self):
        s=seed(); execution=Execution()
        ctx=compose_farm_context(s,evidence(s),execution)
        self.assertIs(ctx.execution,execution)
        self.assertEqual(ctx.execution.state,ExecutionState.NOT_STARTED)

    def test_execution_in_progress_is_explicit_and_preserved(self):
        s=seed(); execution=Execution(ExecutionState.IN_PROGRESS,'farm')
        ctx=compose_farm_context(s,evidence(s,farm=Y),execution)
        self.assertIs(ctx.execution,execution)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.LEAVE_TO_SAFE_FARM)

    def test_active_route_becomes_unsafe_supports_abort(self):
        s=seed(); execution=Execution(ExecutionState.IN_PROGRESS,'farm')
        before=compose_farm_context(s,evidence(s,farm=Y),execution)
        self.assertEqual(farm_cycle.plan(before).next_action,Action.LEAVE_TO_SAFE_FARM)
        e=evidence(s,farm=Y)
        e=replace(e,assessments=tuple(replace(o,safe=replace(o.safe,value=N)) if o.plan_id=='farm' else o for o in e.assessments))
        after=compose_farm_context(s,e,execution)
        self.assertEqual(after.execution.plan_id,'farm')
        self.assertEqual(farm_cycle.plan(after).next_action,Action.ABORT_CURRENT_ROUTE)

    def test_unknown_active_route_is_not_inferred_from_scalars(self):
        s=seed(); execution=Execution(ExecutionState.IN_PROGRESS,'not-supplied')
        ctx=compose_farm_context(s,evidence(s),execution)
        self.assertEqual(ctx.execution.plan_id,'not-supplied')
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_reuses_existing_resolver_exactly(self):
        s=seed(); e=evidence(s,threat=U,farm=Y); execution=Execution()
        expected=decision.build_context(RuntimeObservation(s.observation_id,e.observations),
            s.knowledge,s.player,e.assessments,e.increased_risk,execution)
        with patch.object(farm_context,'build_context',wraps=decision.build_context) as resolver:
            actual=compose_farm_context(s,e,execution)
        resolver.assert_called_once()
        self.assertEqual(actual,expected)

    def test_determinism_and_order_independence(self):
        s=seed(); e=evidence(s,farm=Y)
        first=compose_farm_context(s,e,Execution())
        self.assertEqual(first,compose_farm_context(s,e,Execution()))
        reordered=replace(e,observations=tuple(reversed(e.observations)),assessments=tuple(reversed(e.assessments)))
        self.assertEqual(first,compose_farm_context(s,reordered,Execution()))
        self.assertEqual(context_id(first),context_id(compose_farm_context(s,e,Execution())))

    def test_immutable_inputs_and_output(self):
        s=seed(); e=evidence(s); execution=Execution()
        before=(asdict(s),asdict(e),asdict(execution))
        ctx=compose_farm_context(s,e,execution)
        self.assertEqual(before,(asdict(s),asdict(e),asdict(execution)))
        with self.assertRaises(FrozenInstanceError): e.seed_id='changed'
        with self.assertRaises(FrozenInstanceError): e.assessments[0].safe.value=N
        with self.assertRaises(FrozenInstanceError): ctx.observation_id='changed'
        with self.assertRaises(FrozenInstanceError): ctx.options[0].safe.value=N
        self.assertIsInstance(ctx.options,tuple)

    def test_assessment_provenance_remains_separate_from_observations(self):
        s=seed(); e=evidence(s)
        ctx=compose_farm_context(s,e,Execution())
        condition=option(ctx,'wave').safe
        self.assertEqual(condition.evidence,(e.observations[0],))
        self.assertEqual([(p.source,p.ref) for p in condition.provenance],
            [(Source.RUNTIME_OBSERVATION,'fixture.enemy-visible'),
             (Source.EXPERT_HEURISTIC,'fixture.wave-safety.v1')])
        self.assertFalse(any(p.ref.startswith('State.') for c in ctx.conditions for p in c.provenance))

    def test_cannot_relabel_another_declared_assessment_source(self):
        s=seed(); e=evidence(s)
        for source in (Source.RUNTIME_OBSERVATION,Source.KNOWLEDGE_SNAPSHOT,Source.PLAYER_MODEL):
            with self.assertRaisesRegex(ValueError,'unsupported_assessment_source'):
                replace(e,assessment_source=source)

    def test_scalars_never_determine_strategic_conditions(self):
        first=seed(); base=evidence(first)
        original=compose_farm_context(first,base,Execution())
        varied=seed(replace(normalize(payload()),time=9000,hero='synthetic-hero',level=99,
                           gold=0,lh=0,gpm=0,xpm=0))
        ctx=compose_farm_context(varied,replace(base,seed_id=varied.seed_id),Execution())
        self.assertEqual(original.options,ctx.options)
        self.assertEqual(original.increased_risk,ctx.increased_risk)
        self.assertEqual(original.execution,ctx.execution)
        self.assertNotEqual(original.observation_id,ctx.observation_id)

    def test_scalar_refs_cannot_be_supplied_as_strategic_support(self):
        s=seed(); e=evidence(s)
        with self.assertRaisesRegex(ValueError,'runtime_scalar_is_not_strategic_support'):
            replace(e,observations=e.observations+(ObservedFact('State.gold',Y,F),))
        with self.assertRaisesRegex(ValueError,'runtime_scalar_is_not_strategic_support'):
            replace(e,increased_risk=Claim(Y,('State.gpm',),'fixture.no-scalar-threshold.v1'))

    def test_missing_current_evidence_does_not_reuse_previous_context(self):
        s=seed(); e=evidence(s)
        compose_farm_context(s,e,Execution())
        current=compose_farm_context(s,replace(e,observations=()),Execution())
        self.assertTrue(all(o.safe.value==U and o.available.value==U for o in current.options))
        self.assertEqual(current.increased_risk.value,U)

    def test_duplicate_or_invalid_option_rules_reuse_existing_rejection(self):
        s=seed(); e=evidence(s)
        with self.assertRaisesRegex(ValueError,'duplicate_farm_option'):
            compose_farm_context(s,replace(e,assessments=e.assessments+(e.assessments[0],)),Execution())
        invalid=replace(e.assessments[0],action=Action.NO_DIRECTIVE)
        with self.assertRaisesRegex(ValueError,'invalid_farm_option'):
            compose_farm_context(s,replace(e,assessments=(invalid,)),Execution())

    def test_input_boundary_rejects_ambiguous_or_mutable_values(self):
        s=seed(); e=evidence(s)
        with self.assertRaises(TypeError): compose_farm_context({},e,Execution())
        with self.assertRaises(TypeError): compose_farm_context(s,{},Execution())
        with self.assertRaises(TypeError): compose_farm_context(s,e,None)
        with self.assertRaises(ValueError): compose_farm_context(s,e,Execution(ExecutionState.IN_PROGRESS,['farm']))
        with self.assertRaises(TypeError): replace(e,observations=list(e.observations))
        with self.assertRaises(TypeError): replace(e,assessments=list(e.assessments))
        with self.assertRaises(ValueError): replace(e,observations=e.observations+(e.observations[0],))
        with self.assertRaises(ValueError): replace(e,increased_risk=Claim(Y,(123,),'fixture.invalid-ref'))
        with self.assertRaises(ValueError): replace(e,increased_risk=Claim(Y,(),123))

    def test_no_io_environment_clock_or_planner_invocation(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        from coach02 import voice, vision
        s=seed(); e=evidence(s); execution=Execution()
        expected=compose_farm_context(s,e,execution)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (farm_cycle,'plan'),(decision,'authorize_output'),(voice.WindowsBackend,'play'),(vision,'capture_roi')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]
        environment=os.environ
        forbidden=AssertionError('composer crossed pure composition boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=compose_farm_context(s,e,execution)
        self.assertEqual(actual,expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_import_and_live_path_isolation(self):
        tree=ast.parse(Path(farm_context.__file__).read_text(encoding='utf-8'))
        imports=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imports.update(n.name for n in node.names)
            if isinstance(node,ast.ImportFrom): imports.add('.'*node.level+(node.module or ''))
        self.assertEqual(imports,{'dataclasses','.context_builder','.decision'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        self.assertFalse(any(isinstance(n,ast.Call) and ast.unparse(n.func).split('.')[-1] in ('plan','authorize_output') for n in ast.walk(tree)))
        root=Path(farm_context.__file__).resolve().parent.parent
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py',
                     'coach02/runtime_adapter.py','coach02/context_builder.py','coach02/farm_cycle.py'):
            other=ast.parse((root/path).read_text(encoding='utf-8'))
            for node in ast.walk(other):
                if isinstance(node,(ast.Import,ast.ImportFrom,ast.Call)):
                    self.assertNotIn('farm_context',ast.unparse(node),path)


if __name__=='__main__': unittest.main()
