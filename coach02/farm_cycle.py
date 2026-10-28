"""One deterministic offline planner. Expert heuristics, not verified Dota truth.

plan(context) -> Decision is the seam for a future arbiter. No arbitration or
legacy Policy priority/cooldown logic is imported into this isolated vertical.
"""
from .decision import (Action, Authority, CandidatePlan, Confidence, Decision,
                       ExecutionState, Provenance, Reason, Risk, Source, Truth, context_id)

RULESET = 'carry_farm_cycle.offline.v1'
FUTURE = {
    Action.TAKE_ONE_MORE_WAVE: 'wave_attempted_while_exposed_then_reevaluate',
    Action.LEAVE_TO_SAFE_FARM: 'supplied_safer_farm_route_attempted_then_reevaluate',
    Action.SAFE_RESOURCE_THEN_REEVALUATE: 'supplied_short_resource_attempted_then_reevaluate',
    Action.HOLD_AND_REEVALUATE: 'commitment_paused_pending_information',
    Action.ABORT_CURRENT_ROUTE: 'current_route_aborted_replan_required',
    Action.NO_DIRECTIVE: 'risk_awareness_without_prescribed_route',
}


def plan(context):
    """Qualitative branch order implements only the requested fixture contract.

    It is not a numeric optimization, a pathfinder, or a universal safety rule.
    HOLD means withhold route commitment, not 'stand still here safely'.
    """
    candidates = tuple(CandidatePlan(
        o.plan_id, o.action, o.available.value,
        {Truth.YES: Risk.ACCEPTABLE, Truth.NO: Risk.UNSAFE, Truth.UNKNOWN: Risk.UNKNOWN}[o.safe.value],
        (o.available, o.safe), FUTURE[o.action]) for o in context.options)

    def ready(candidate):
        return candidate.feasibility == Truth.YES and candidate.risk == Risk.ACCEPTABLE

    def finish(selected, reason, authority, confidence):
        identity = context_id(context)
        provenance = (
            Provenance(Source.RUNTIME_OBSERVATION, context.observation_id),
            Provenance(Source.KNOWLEDGE_SNAPSHOT, context.knowledge.snapshot_id + '@' + context.knowledge.version),
            Provenance(Source.PLAYER_MODEL, context.player.snapshot_id + '@' + context.player.version),
            Provenance(Source.EXPERT_HEURISTIC, RULESET))
        provenance += tuple(p for c in selected.dependencies for p in c.provenance)
        all_plans = candidates if selected in candidates else candidates + (selected,)
        return Decision(RULESET + ':' + identity, identity, 'CARRY_FARM_CYCLE', 'farm_without_unsupported_exposure',
                        all_plans, selected, context.execution, confidence, authority,
                        (reason,), tuple(dict.fromkeys(provenance)), context.knowledge, context.player)

    def fallback(action, reason, authority, dependencies=()):
        selected = CandidatePlan('@' + action.value, action, Truth.UNKNOWN, Risk.UNKNOWN,
                                 dependencies, FUTURE[action])
        return finish(selected, reason, authority, Confidence.LIMITED)

    if context.execution.state == ExecutionState.IN_PROGRESS:
        active = next((c for c in candidates if c.plan_id == context.execution.plan_id), None)
        if active and active.risk == Risk.UNSAFE:
            # The new abort depends on current unsafe evidence, not a stale old
            # availability claim. It does not assert a safe replacement route.
            return fallback(Action.ABORT_CURRENT_ROUTE, Reason.ROUTE_UNSAFE,
                            Authority.DIRECTIVE, (active.dependencies[1],))
        if active and ready(active):
            return finish(active, Reason.CONTINUE_ROUTE, Authority.DIRECTIVE, Confidence.SUPPORTED)
        # Even without a contradictory event, an unconfirmed route cannot continue.
        return fallback(Action.HOLD_AND_REEVALUATE, Reason.ROUTE_UNCONFIRMED, Authority.ADVISORY)

    for action, reason in (
            (Action.TAKE_ONE_MORE_WAVE, Reason.SAFE_WAVE),
            (Action.LEAVE_TO_SAFE_FARM, Reason.SAFER_FARM),
            (Action.SAFE_RESOURCE_THEN_REEVALUATE, Reason.PRODUCTIVE_WAIT)):
        candidate = next((c for c in candidates if c.action == action and ready(c)), None)
        if candidate:
            return finish(candidate, reason, Authority.DIRECTIVE, Confidence.SUPPORTED)
    if context.increased_risk.value == Truth.YES:
        return fallback(Action.NO_DIRECTIVE, Reason.RISK_WITHOUT_ROUTE,
                        Authority.AWARENESS, (context.increased_risk,))
    return fallback(Action.HOLD_AND_REEVALUATE, Reason.INSUFFICIENT_EVIDENCE, Authority.ADVISORY)
