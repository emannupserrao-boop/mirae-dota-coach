"""Architectural fixtures, not claims about universal Dota safety or timing."""
from dataclasses import FrozenInstanceError, asdict, replace
import json
import unittest

from coach02.decision import (Action, Authority, Claim, Confidence, Execution,
    ExecutionState, Freshness, KnowledgeSnapshotRef, ObservedFact, OptionAssessment,
    PlayerModelSnapshotRef, Reason, Risk, RuntimeObservation, Source, Truth,
    Validity, authorize_output, build_context, validate_decision)
from coach02.farm_cycle import plan

Y, N, U = Truth.YES, Truth.NO, Truth.UNKNOWN
F, S = Freshness.FRESH, Freshness.STALE
KNOWLEDGE = KnowledgeSnapshotRef('fixture-mechanics-not-loaded', 'fixture-v1')
PLAYER = PlayerModelSnapshotRef('fixture-player-not-profiled', 'fixture-v1')


def fixture(*, wave=Y, farm=N, resource=N, risk=N, stale_threats=False,
            unknown_threats=False, execution=Execution(), observation_id='sample-1'):
    # Facts are reports of visibility/availability, never route-safety facts.
    # The safety claims below are separately supplied expert fixture assessments.
    facts = (
        ObservedFact('enemy-a-visible', U if unknown_threats else Y, S if stale_threats else F),
        ObservedFact('enemy-b-visible', U if unknown_threats else Y, S if stale_threats else F),
        ObservedFact('coverage-observed', N if stale_threats or unknown_threats else Y, F),
        ObservedFact('wave-observed', Y, F),
        ObservedFact('farm-resource-observed', Y, F),
        ObservedFact('farm-corridor-observed', Y, F),
        ObservedFact('short-resource-observed', Y, F),
        ObservedFact('short-corridor-observed', Y, F),
    )
    def claim(value, *refs): return Claim(value, refs, 'fixture.assessment.v1')
    assessments = (
        OptionAssessment('wave', Action.TAKE_ONE_MORE_WAVE,
                         claim(Y, 'wave-observed'),
                         claim(wave, 'enemy-a-visible', 'enemy-b-visible', 'coverage-observed')),
        OptionAssessment('farm', Action.LEAVE_TO_SAFE_FARM,
                         claim(farm, 'farm-resource-observed'), claim(farm, 'farm-corridor-observed')),
        OptionAssessment('short', Action.SAFE_RESOURCE_THEN_REEVALUATE,
                         claim(resource, 'short-resource-observed'), claim(resource, 'short-corridor-observed')),
    )
    return (RuntimeObservation(observation_id, facts), KNOWLEDGE, PLAYER, assessments,
            claim(risk, 'coverage-observed'), execution)


def context(**kwargs): return build_context(*fixture(**kwargs))


class FarmCycleTests(unittest.TestCase):
    def test_safe_wave(self):
        ctx = context()
        decision = plan(ctx)
        self.assertEqual(decision.next_action, Action.TAKE_ONE_MORE_WAVE)
        self.assertEqual(decision.selected_plan.feasibility, Y)
        self.assertEqual(decision.selected_plan.risk, Risk.ACCEPTABLE)
        self.assertEqual(decision.confidence, Confidence.SUPPORTED)
        self.assertEqual(authorize_output(decision, ctx).authority, Authority.DIRECTIVE)
        self.assertIn(Reason.SAFE_WAVE, decision.reason_codes)

    def test_stale_threats_and_insufficient_coverage_choose_supported_farm(self):
        ctx = context(stale_threats=True, unknown_threats=True, farm=Y, risk=Y)
        decision = plan(ctx)
        self.assertEqual(decision.next_action, Action.LEAVE_TO_SAFE_FARM)
        wave = next(c for c in decision.candidate_plans if c.plan_id == 'wave')
        self.assertEqual(wave.risk, Risk.UNKNOWN)
        self.assertEqual(wave.dependencies[1].freshness, S)
        # The farm route has its own fresh evidence; stale lane evidence cannot
        # globally invalidate an independently supported alternative.
        self.assertEqual(authorize_output(decision, ctx).authority, Authority.DIRECTIVE)

    def test_productive_information_wait(self):
        ctx = context(unknown_threats=True, resource=Y, risk=Y)
        decision = plan(ctx)
        self.assertEqual(decision.next_action, Action.SAFE_RESOURCE_THEN_REEVALUATE)
        self.assertIn(Reason.PRODUCTIVE_WAIT, decision.reason_codes)
        self.assertIn('reevaluate', decision.selected_plan.expected_future_state)

    def test_insufficient_observability_emits_awareness_without_route(self):
        ctx = context(unknown_threats=True, farm=U, resource=U, risk=Y)
        decision = plan(ctx)
        output = authorize_output(decision, ctx)
        self.assertEqual(output.authority, Authority.AWARENESS)
        self.assertEqual(output.next_action, Action.NO_DIRECTIVE)
        self.assertEqual(decision.confidence, Confidence.LIMITED)
        self.assertIn(Reason.RISK_WITHOUT_ROUTE, decision.reason_codes)

    def test_route_valid_started_then_unsafe_aborts_and_requires_replan(self):
        initial = context(wave=N, farm=Y)
        suggested = plan(initial)
        self.assertEqual(suggested.selected_plan.plan_id, 'farm')
        running = Execution(ExecutionState.IN_PROGRESS, suggested.selected_plan.plan_id)
        safe_ctx = context(wave=N, farm=Y, execution=running)
        active = plan(safe_ctx)
        self.assertEqual(active.execution.state, ExecutionState.IN_PROGRESS)
        self.assertIn(Reason.CONTINUE_ROUTE, active.reason_codes)
        unsafe_args = list(fixture(wave=N, farm=Y, execution=running, observation_id='sample-2'))
        options = unsafe_args[3]
        unsafe_args[3] = tuple(replace(o, safe=replace(o.safe, value=N)) if o.plan_id == 'farm' else o for o in options)
        unsafe = build_context(*unsafe_args)
        self.assertEqual(validate_decision(active, unsafe).state, Validity.INVALID)
        aborted = plan(unsafe)
        self.assertEqual(aborted.next_action, Action.ABORT_CURRENT_ROUTE)
        self.assertEqual(authorize_output(aborted, unsafe).authority, Authority.DIRECTIVE)
        self.assertIn(Reason.ROUTE_UNSAFE, aborted.reason_codes)
        self.assertEqual(aborted.execution.plan_id, 'farm')
        self.assertIn('replan_required', aborted.selected_plan.expected_future_state)

    def test_unknown_is_not_safe_even_when_fixture_claims_safe(self):
        known = plan(context())
        unknown = plan(context(unknown_threats=True))
        self.assertEqual(known.next_action, Action.TAKE_ONE_MORE_WAVE)
        self.assertEqual(unknown.next_action, Action.HOLD_AND_REEVALUATE)
        self.assertEqual(unknown.output_authority, Authority.ADVISORY)
        self.assertNotEqual(unknown.selected_plan.risk, Risk.ACCEPTABLE)

    def test_fresh_unknown_assessment_is_not_safe(self):
        decision = plan(context(wave=U, farm=U, resource=U, risk=U))
        self.assertEqual(decision.next_action, Action.HOLD_AND_REEVALUATE)
        self.assertEqual(decision.output_authority, Authority.ADVISORY)

    def test_decision_expires_from_staleness_without_contradictory_values(self):
        fresh = context()
        decision = plan(fresh)
        args = list(fixture())
        args[0] = replace(args[0], facts=tuple(replace(f, freshness=S) if f.ref.startswith('enemy-') else f for f in args[0].facts))
        stale = build_context(*args)
        validation = validate_decision(decision, stale)
        self.assertEqual(validation.state, Validity.EXPIRED)
        self.assertIn(Reason.EVIDENCE_STALE, validation.reasons)
        output = authorize_output(decision, stale)
        self.assertEqual(output.authority, Authority.SUPPRESS)
        self.assertEqual(output.next_action, Action.NO_DIRECTIVE)
        self.assertNotEqual(plan(stale).next_action, Action.TAKE_ONE_MORE_WAVE)

    def test_stale_active_route_pauses_commitment_without_claiming_material_unsafety(self):
        running = Execution(ExecutionState.IN_PROGRESS, 'wave')
        decision = plan(context(stale_threats=True, execution=running))
        self.assertEqual(decision.next_action, Action.HOLD_AND_REEVALUATE)
        self.assertEqual(decision.output_authority, Authority.ADVISORY)
        self.assertIn(Reason.ROUTE_UNCONFIRMED, decision.reason_codes)

    def test_unknown_active_route_is_not_replaced_by_new_wave(self):
        decision = plan(context(execution=Execution(ExecutionState.IN_PROGRESS, 'not-in-context')))
        self.assertEqual(decision.next_action, Action.HOLD_AND_REEVALUATE)

    def test_continue_valid_route_instead_of_switching_to_new_wave(self):
        ctx = context(farm=Y, execution=Execution(ExecutionState.IN_PROGRESS, 'farm'))
        self.assertEqual(plan(ctx).next_action, Action.LEAVE_TO_SAFE_FARM)

    def test_missing_evidence_cannot_confirm_safety(self):
        args = list(fixture())
        args[0] = replace(args[0], facts=tuple(f for f in args[0].facts if f.ref != 'enemy-a-visible'))
        self.assertEqual(plan(build_context(*args)).next_action, Action.HOLD_AND_REEVALUATE)

    def test_no_dependencies_cannot_assert_safe(self):
        args = list(fixture())
        args[3] = tuple(replace(o, safe=replace(o.safe, evidence_refs=())) for o in args[3])
        self.assertEqual(plan(build_context(*args)).next_action, Action.HOLD_AND_REEVALUATE)

    def test_stale_alternative_cannot_be_recommended(self):
        args = list(fixture(wave=N, farm=Y, risk=Y))
        args[0] = replace(args[0], facts=tuple(replace(f, freshness=S) if f.ref == 'farm-corridor-observed' else f for f in args[0].facts))
        self.assertEqual(plan(build_context(*args)).output_authority, Authority.AWARENESS)

    def test_provenance_distinguishes_observations_refs_and_expert_heuristics(self):
        decision = plan(context())
        self.assertEqual({p.source for p in decision.provenance}, set(Source))
        self.assertTrue(all(c.provenance[-1].source == Source.EXPERT_HEURISTIC for c in decision.evidence_dependencies))
        self.assertTrue(all(c.freshness == F for c in decision.evidence_dependencies))
        self.assertEqual(decision.knowledge, KNOWLEDGE)
        self.assertEqual(decision.player, PLAYER)
        self.assertIn(decision.selected_plan, decision.candidate_plans)
        json.dumps(asdict(decision), allow_nan=False)

    def test_snapshot_reference_change_invalidates(self):
        ctx = context()
        decision = plan(ctx)
        for changed in (replace(ctx, knowledge=replace(KNOWLEDGE, version='fixture-v2')),
                        replace(ctx, player=replace(PLAYER, version='fixture-v2'))):
            self.assertIn(Reason.SNAPSHOT_CHANGED, validate_decision(decision, changed).reasons)

    def test_unknown_dependency_invalidates_existing_decision(self):
        decision = plan(context())
        changed = context(unknown_threats=True)
        self.assertEqual(validate_decision(decision, changed).state, Validity.INVALID)
        self.assertEqual(authorize_output(decision, changed).authority, Authority.SUPPRESS)

    def test_attention_disabled_suppresses_without_mutating_decision(self):
        ctx = context()
        decision = plan(ctx)
        output = authorize_output(decision, ctx, enabled=False)
        self.assertEqual(output.authority, Authority.SUPPRESS)
        self.assertEqual(output.next_action, Action.NO_DIRECTIVE)
        self.assertIn(Reason.OUTPUT_DISABLED, output.reason_codes)
        self.assertEqual(decision.output_authority, Authority.DIRECTIVE)

    def test_fallback_is_reconsidered_when_new_context_arrives(self):
        old = context(wave=U)
        decision = plan(old)
        self.assertEqual(authorize_output(decision, old).authority, Authority.ADVISORY)
        self.assertEqual(authorize_output(decision, context()).authority, Authority.SUPPRESS)

    def test_decision_already_invalid_cannot_be_reauthorized(self):
        ctx = context()
        for status in (Validity.INVALID, Validity.EXPIRED):
            decision = replace(plan(ctx), validity=status)
            output = authorize_output(decision, ctx)
            self.assertEqual(output.authority, Authority.SUPPRESS)
            self.assertEqual(output.validity.state, status)
            self.assertIn(Reason.NOT_VALID, output.reason_codes)

    def test_deterministic_and_input_order_independent(self):
        args = list(fixture(farm=Y, resource=Y))
        before = build_context(*args)
        args[3] = tuple(reversed(args[3]))
        self.assertEqual(plan(before), plan(build_context(*args)))
        self.assertEqual(plan(before), plan(before))
        with self.assertRaises(FrozenInstanceError):
            KNOWLEDGE.version = 'mutated'

    def test_invalid_inputs_fail_explicitly_not_safe_by_default(self):
        with self.assertRaises(ValueError): ObservedFact('fact', None, F)
        with self.assertRaises(ValueError): ObservedFact('fact', True, F)
        with self.assertRaises(ValueError): ObservedFact('fact', Y, None)
        with self.assertRaises(ValueError): Execution(ExecutionState.IN_PROGRESS)
        with self.assertRaises(ValueError): Execution(ExecutionState.NOT_STARTED, 'farm')
        args = list(fixture())
        args[0] = replace(args[0], facts=args[0].facts + (ObservedFact('extra', U, F),))
        with self.assertRaises(ValueError): replace(args[0], facts=args[0].facts + (args[0].facts[0],))
        with self.assertRaises(ValueError): build_context(args[0], replace(KNOWLEDGE, version=''), *args[2:])

    def test_multiple_routes_for_same_action_are_explicitly_out_of_scope(self):
        args = list(fixture())
        args[3] += (replace(args[3][1], plan_id='second-farm-route'),)
        with self.assertRaisesRegex(ValueError, 'duplicate_farm_option'):
            build_context(*args)


if __name__ == '__main__': unittest.main()
