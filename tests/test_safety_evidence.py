"""Synthetic domain observations only. No live Safety/vision claims."""
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
from coach02 import decision, farm_cycle, safety_evidence
from coach02.context_builder import build_context_seed
from coach02.decision import (Action, Authority, Claim, Execution, Freshness,
    KnowledgeSnapshotRef, ObservedFact, ObservationSource, OptionAssessment,
    PlayerModelSnapshotRef, Provenance, Source, Truth)
from coach02.farm_context import FarmStrategicEvidence, compose_farm_context
from coach02.runtime_adapter import adapt_state
from coach02.safety_evidence import (CoverageObservation, RelevantThreatObservation,
    RiskAwarenessEvidence, RiskReason, ThreatState, build_risk_awareness)

Y, N, U = Truth.YES, Truth.NO, Truth.UNKNOWN
F, S = Freshness.FRESH, Freshness.STALE
NEAR, AWAY, MISSING, UNKNOWN = (ThreatState.VISIBLE_NEARBY, ThreatState.VISIBLE_AWAY,
                              ThreatState.MISSING, ThreatState.UNKNOWN)


def runtime_seed(**changes):
    state = replace(normalize(payload()), **changes)
    return build_context_seed(adapt_state(state), KnowledgeSnapshotRef('not-loaded','v1'),
                              PlayerModelSnapshotRef('not-profiled','v1'))


def threat(state, freshness=F, name='enemy_mid'):
    return RelevantThreatObservation(name, state, freshness)


def build(threats, coverage=Y, freshness=F, seed_id='synthetic-seed'):
    return build_risk_awareness(seed_id, threats, CoverageObservation(coverage,freshness))


def compose(runtime, risk, *, farm=U, short=U):
    # Option assessments are separate explicit fixtures, never produced by Safety.
    support = (ObservedFact('fixture.farm-observed',Y,F), ObservedFact('fixture.short-observed',Y,F))
    options = (
        OptionAssessment('farm',Action.LEAVE_TO_SAFE_FARM,
            Claim(farm,('fixture.farm-observed',),'fixture.farm-availability.v1'),
            Claim(farm,('fixture.farm-observed',),'fixture.farm-safety.v1')),
        OptionAssessment('short',Action.SAFE_RESOURCE_THEN_REEVALUATE,
            Claim(short,('fixture.short-observed',),'fixture.short-availability.v1'),
            Claim(short,('fixture.short-observed',),'fixture.short-safety.v1')))
    return compose_farm_context(runtime,FarmStrategicEvidence(risk.seed_id,risk.observations+support,
        options,risk.increased_risk),Execution())


class SafetyEvidenceTests(unittest.TestCase):
    def test_fresh_nearby_is_positive(self):
        r=build((threat(NEAR),))
        self.assertEqual(r.increased_risk.value,Y)
        self.assertEqual(r.reasons,(RiskReason.VISIBLE_RELEVANT_THREAT,))
        self.assertEqual(r.increased_risk.evidence_refs,('safety.threat.enemy_mid.visible_nearby',))

    def test_one_missing_without_coverage_is_positive(self):
        r=build((threat(MISSING),),N)
        self.assertEqual(r.increased_risk.value,Y)
        self.assertEqual(r.reasons,(RiskReason.MISSING_THREAT_WITHOUT_COVERAGE,))
        self.assertEqual(r.increased_risk.evidence_refs,('safety.threat.enemy_mid.missing','safety.coverage.sufficient'))

    def test_missing_with_coverage_is_unknown_not_low_risk(self):
        r=build((threat(MISSING),),Y)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.MISSING_THREAT_WITH_COVERAGE,r.reasons)

    def test_all_fresh_away_with_coverage_is_no(self):
        r=build((threat(AWAY,name='enemy_a'),threat(AWAY,name='enemy_b')),Y)
        self.assertEqual(r.increased_risk.value,N)
        self.assertEqual(r.reasons,(RiskReason.ALL_RELEVANT_THREATS_VISIBLE_AWAY_WITH_COVERAGE,))

    def test_away_with_unknown_coverage_is_unknown(self):
        r=build((threat(AWAY),),U)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.COVERAGE_UNKNOWN,r.reasons)

    def test_away_with_stale_coverage_is_unknown(self):
        r=build((threat(AWAY),),Y,S)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.COVERAGE_STALE,r.reasons)

    def test_stale_missing_without_coverage_is_unknown(self):
        r=build((threat(MISSING,S),),N)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.THREAT_INFORMATION_STALE,r.reasons)

    def test_unknown_threat_never_becomes_known_location(self):
        r=build((threat(UNKNOWN),),Y)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.THREAT_INFORMATION_UNKNOWN,r.reasons)
        self.assertTrue(all(f.value==U for f in r.observations if '.threat.' in f.ref))

    def test_fresh_direct_evidence_dominates_unrelated_unknown_and_stale(self):
        s=runtime_seed()
        r=build((threat(NEAR,name='direct'),threat(UNKNOWN,name='unknown'),threat(AWAY,S,'old')),U,S,seed_id=s.seed_id)
        self.assertEqual(r.increased_risk.value,Y)
        self.assertEqual(r.increased_risk.evidence_refs,('safety.threat.direct.visible_nearby',))
        self.assertTrue(any(f.value==U for f in r.observations))
        self.assertEqual(compose(s,r).increased_risk.value,Y)

    def test_missing_positive_trigger_survives_other_stale_threats(self):
        s=runtime_seed()
        r=build((threat(MISSING,name='current'),threat(UNKNOWN,S,'old')),N,seed_id=s.seed_id)
        self.assertEqual(r.increased_risk.value,Y)
        self.assertEqual(compose(s,r).increased_risk.value,Y)

    def test_empty_threats_unknown_even_with_fresh_coverage(self):
        r=build((),Y)
        self.assertEqual(r.increased_risk.value,U)
        self.assertIn(RiskReason.NO_RELEVANT_THREAT_EVIDENCE,r.reasons)

    def test_no_is_not_safe_and_does_not_create_options(self):
        s=runtime_seed(); r=build((threat(AWAY),),Y,seed_id=s.seed_id)
        self.assertEqual(r.increased_risk.value,N)
        self.assertEqual(set(asdict(r)),{'evidence_id','seed_id','observations','increased_risk','reasons','ruleset'})
        self.assertFalse(hasattr(r,'safe'))
        self.assertFalse(hasattr(r,'recommended_action'))
        ctx=compose(s,r)
        self.assertTrue(all(o.safe.value==U for o in ctx.options))
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.HOLD_AND_REEVALUATE)

    def test_no_missing_count_threshold(self):
        for names in (('one',),('a','b'),('a','b','c','d')):
            r=build(tuple(threat(MISSING,name=n) for n in names),N)
            self.assertEqual(r.increased_risk.value,Y)
            self.assertEqual(r.increased_risk.rule_ref,'safety.risk.missing_without_coverage.v1')
        tree=ast.parse(Path(safety_evidence.__file__).read_text(encoding='utf-8'))
        # Length is used solely to reject duplicate identifiers, never as risk score.
        comparisons=[ast.unparse(n) for n in ast.walk(tree) if isinstance(n,ast.Compare)]
        self.assertEqual([c for c in comparisons if 'len(' in c],
                         ['len({t.threat_id for t in threats}) != len(threats)'])

    def test_order_independence_and_determinism(self):
        threats=(threat(MISSING,name='z'),threat(AWAY,name='a'))
        first=build(threats,N)
        self.assertEqual(first,build(tuple(reversed(threats)),N))
        self.assertEqual(first,build(threats,N))
        data=asdict(first); data.pop('evidence_id')
        encoded=json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')
        self.assertEqual(first.evidence_id,'safety.risk_awareness.v1:'+hashlib.sha256(encoded).hexdigest())

    def test_inputs_unchanged_and_output_immutable(self):
        threats=(threat(MISSING),); coverage=CoverageObservation(N,F)
        before=(asdict(threats[0]),asdict(coverage))
        r=build_risk_awareness('seed',threats,coverage)
        self.assertEqual(before,(asdict(threats[0]),asdict(coverage)))
        with self.assertRaises(FrozenInstanceError): r.seed_id='other'
        with self.assertRaises(FrozenInstanceError): r.observations[0].source=Source.RUNTIME_OBSERVATION
        with self.assertRaises(FrozenInstanceError): r.increased_risk.value=N
        self.assertIsInstance(r.observations,tuple)

    def test_reason_and_rule_identifiers_are_stable(self):
        r=build((threat(NEAR),))
        self.assertEqual(r.ruleset,'safety.risk_awareness.v1')
        self.assertEqual(r.increased_risk.rule_ref,'safety.risk.visible_relevant_threat.v1')
        self.assertEqual(r.reasons[0].value,r.increased_risk.rule_ref)

    def test_safety_facts_have_explicit_allowed_source_and_namespace(self):
        r=build((threat(MISSING),),N)
        self.assertTrue(all(f.source is ObservationSource.SAFETY_EVIDENCE for f in r.observations))
        self.assertTrue(all(f.ref.startswith('safety.') and not f.ref.startswith('State.') for f in r.observations))
        self.assertEqual(next(f for f in r.observations if f.ref.endswith('.missing')).value,Y)
        self.assertEqual(next(f for f in r.observations if f.ref.endswith('.visible_away')).value,N)

    def test_composed_risk_provenance_is_safety_plus_heuristic(self):
        s=runtime_seed(); r=build((threat(MISSING),),N,seed_id=s.seed_id)
        ctx=compose(s,r)
        provenance=ctx.increased_risk.provenance
        self.assertEqual([p.source for p in provenance],
            [ObservationSource.SAFETY_EVIDENCE,ObservationSource.SAFETY_EVIDENCE,Source.EXPERT_HEURISTIC])
        self.assertEqual(provenance[-1],Provenance(Source.EXPERT_HEURISTIC,r.increased_risk.rule_ref))
        self.assertEqual(ctx.increased_risk.value,Y)
        self.assertTrue(all(o.safe.provenance[0].source is Source.RUNTIME_OBSERVATION for o in ctx.options))

    def test_evidence_cannot_silently_attach_to_another_seed(self):
        original=runtime_seed(); other=runtime_seed(gold=999)
        r=build((threat(NEAR),),seed_id=original.seed_id)
        with self.assertRaisesRegex(ValueError,'strategic_evidence_seed_mismatch'): compose(other,r)
        changed=build((threat(NEAR),),seed_id=other.seed_id)
        self.assertNotEqual(r.evidence_id,changed.evidence_id)
        self.assertEqual(r.observations,changed.observations)

    def test_hero_and_runtime_metrics_do_not_change_rule(self):
        a=runtime_seed(); b=runtime_seed(hero='synthetic_other_hero',level=99,time=9999,gpm=0,gold=0)
        ra=build((threat(MISSING),),N,seed_id=a.seed_id)
        rb=build((threat(MISSING),),N,seed_id=b.seed_id)
        self.assertEqual(ra.increased_risk,rb.increased_risk)
        self.assertEqual(ra.reasons,rb.reasons)
        self.assertEqual(ra.observations,rb.observations)

    def test_old_observed_fact_constructor_and_source_enumeration(self):
        fact=ObservedFact('legacy',Y,F)
        self.assertIs(fact.source,Source.RUNTIME_OBSERVATION)
        self.assertEqual(fact,ObservedFact('legacy',Y,F,source=Source.RUNTIME_OBSERVATION))
        self.assertEqual({s.value for s in Source},
            {'RUNTIME_OBSERVATION','KNOWLEDGE_SNAPSHOT','PLAYER_MODEL','EXPERT_HEURISTIC'})
        self.assertEqual(asdict(fact),dict(ref='legacy',value=Y,freshness=F,source=Source.RUNTIME_OBSERVATION))

    def test_invalid_observational_sources_are_not_accepted(self):
        for source in (Source.KNOWLEDGE_SNAPSHOT,Source.PLAYER_MODEL,Source.EXPERT_HEURISTIC,
                       'SAFETY_EVIDENCE','RUNTIME_OBSERVATION',None):
            with self.assertRaisesRegex(ValueError,'invalid_observational_source'):
                ObservedFact('invalid',Y,F,source=source)

    def test_unknown_risk_with_separately_supplied_short_resource(self):
        s=runtime_seed(); r=build((threat(UNKNOWN),),U,seed_id=s.seed_id)
        ctx=compose(s,r,short=Y)
        self.assertEqual(ctx.increased_risk.value,U)
        self.assertEqual(farm_cycle.plan(ctx).next_action,Action.SAFE_RESOURCE_THEN_REEVALUATE)

    def test_positive_risk_without_route_yields_awareness_only(self):
        s=runtime_seed(); r=build((threat(NEAR),),seed_id=s.seed_id)
        result=farm_cycle.plan(compose(s,r))
        self.assertEqual(result.next_action,Action.NO_DIRECTIVE)
        self.assertEqual(result.output_authority,Authority.AWARENESS)

    def test_positive_risk_does_not_invent_safe_farm(self):
        s=runtime_seed(); r=build((threat(MISSING),),N,seed_id=s.seed_id)
        self.assertEqual(farm_cycle.plan(compose(s,r)).next_action,Action.NO_DIRECTIVE)
        self.assertEqual(farm_cycle.plan(compose(s,r,farm=Y)).next_action,Action.LEAVE_TO_SAFE_FARM)

    def test_stale_nearby_not_reinterpreted_as_current(self):
        r=build((threat(NEAR,S),),N)
        self.assertEqual(r.increased_risk.value,U)
        self.assertTrue(all(f.freshness==S for f in r.observations if '.threat.' in f.ref))

    def test_away_without_coverage_is_not_low_risk(self):
        r=build((threat(AWAY),),N)
        self.assertEqual(r.increased_risk.value,U)
        self.assertEqual(r.reasons,(RiskReason.INSUFFICIENT_RISK_SUPPORT,))

    def test_no_previous_frame_state(self):
        build((threat(NEAR),))
        self.assertEqual(build((),U).increased_risk.value,U)

    def test_malformed_inputs_fail_explicitly(self):
        for name in ('','a.b','a/b','a b','é',123):
            with self.assertRaises(ValueError): threat(NEAR,name=name)
        with self.assertRaises(ValueError): threat('VISIBLE_NEARBY')
        with self.assertRaises(ValueError): threat(NEAR,'FRESH')
        with self.assertRaises(ValueError): CoverageObservation(True,F)
        with self.assertRaises(ValueError): CoverageObservation(Y,'FRESH')
        with self.assertRaises(TypeError): build([threat(NEAR)])
        with self.assertRaises(TypeError): build_risk_awareness('seed',(),None)
        with self.assertRaises(ValueError): build((),seed_id='')
        with self.assertRaisesRegex(ValueError,'duplicate_threat_id'): build((threat(NEAR),threat(AWAY)))

    def test_no_io_environment_clock_process_or_planner(self):
        import builtins, io, os, random, socket, sqlite3, subprocess, time, uuid
        import http.client
        threats=(threat(NEAR),); coverage=CoverageObservation(U,S)
        expected=build_risk_awareness('seed',threats,coverage)
        sinks=[(builtins,'open'),(io,'open'),(os,'open'),(os,'getenv'),(os,'system'),
            (socket,'socket'),(socket,'getaddrinfo'),(socket,'create_connection'),
            (http.client.HTTPConnection,'request'),(sqlite3,'connect'),(subprocess,'Popen'),
            (time,'time'),(time,'monotonic'),(time,'perf_counter'),(uuid,'uuid4'),(random,'random'),
            (farm_cycle,'plan'),(decision,'build_context'),(decision,'authorize_output')]
        originals=[(o,n,getattr(o,n)) for o,n in sinks]; environment=os.environ
        forbidden=AssertionError('Safety builder crossed pure risk boundary')
        class NoEnvironment(dict):
            def __getitem__(self,key): raise forbidden
            def get(self,*args): raise forbidden
            def __iter__(self): raise forbidden
        with ExitStack() as stack:
            for owner,name in sinks: stack.enter_context(patch.object(owner,name,side_effect=forbidden))
            stack.enter_context(patch.object(os,'environ',NoEnvironment()))
            actual=build_risk_awareness('seed',threats,coverage)
        self.assertEqual(actual,expected)
        for owner,name,original in originals: self.assertIs(getattr(owner,name),original)
        self.assertIs(os.environ,environment)

    def test_import_and_live_isolation(self):
        tree=ast.parse(Path(safety_evidence.__file__).read_text(encoding='utf-8'))
        imports=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import): imports.update(a.name for a in n.names)
            if isinstance(n,ast.ImportFrom): imports.add('.'*n.level+(n.module or ''))
        self.assertEqual(imports,{'dataclasses','enum','hashlib','json','.decision'})
        self.assertFalse(any(isinstance(n,(ast.Global,ast.Nonlocal)) for n in ast.walk(tree)))
        root=Path(safety_evidence.__file__).resolve().parent.parent
        for path in ('run.py','coach/service.py','coach02/service.py','coach/gsi.py','coach02/policy.py',
                     'coach02/runtime_adapter.py','coach02/context_builder.py','coach02/farm_context.py',
                     'coach02/farm_cycle.py','coach02/vision.py'):
            other=ast.parse((root/path).read_text(encoding='utf-8'))
            for n in ast.walk(other):
                if isinstance(n,(ast.Import,ast.ImportFrom,ast.Call)):
                    self.assertNotIn('safety_evidence',ast.unparse(n),path)


if __name__=='__main__': unittest.main()
