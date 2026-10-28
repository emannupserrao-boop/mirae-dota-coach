"""Exact semantic bindings, independent dimensions, lineage and nonauthority."""
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

from coach02 import objective_outcome_relation_v01 as relation
from coach02.objective_outcome_relation_v01 import (
    ObjectiveOutcomeRelation, ObjectiveOutcomeRelationClaim,
    ObjectiveOutcomeRelationEvidence, ObjectiveOutcomeRelationSnapshotV1,
    build_objective_outcome_relation_snapshot_v1,
)
from test_decision_context_v02 import (
    build as decision, sources, request, binding, objective_claim, outcome_claim,
    without_safety, OutcomeChange, StrategicObjectiveKnownness, SupportedRiskTolerance,
)
from test_feasibility_gate_v01 import import_violations


def claim(context=None, **changes):
    context = decision() if context is None else context
    values = dict(decision_context_id=context.decision_context_id, option_id='option-A',
        objective_context_id=context.objective_context_id, objective_horizon_id=context.objective_horizon_id,
        objective_id='opaque-intent', outcome_context_id='O', outcome_baseline_id='B',
        outcome_horizon_id='H-out', dimension_id='dim', relation=ObjectiveOutcomeRelation.SUPPORTS,
        basis_tick=context.decision_assembly_tick, source_id='relation-source', evidence_refs=('ref-b', 'ref-a'),
        assessment_policy_id='relation-policy')
    values.update(changes)
    return ObjectiveOutcomeRelationClaim(**values)


def build(context=None, claims=None):
    context = decision() if context is None else context
    return build_objective_outcome_relation_snapshot_v1(decision_context=context,
        claims=(claim(context),) if claims is None else claims)


def multi(states):
    outcomes = tuple(outcome_claim(dimension_id=str(i)) for i in range(len(states)))
    context = decision(sources(outcomes=outcomes))
    claims = tuple(claim(context, dimension_id=str(i), relation=ObjectiveOutcomeRelation(s))
                   for i, s in enumerate(states))
    return context, claims


class ObjectiveOutcomeRelationV1Tests(unittest.TestCase):
    def no_terms(self, *terms):
        tree = ast.parse(inspect.getsource(relation))
        tokens = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        schema = {f.name for cls in (ObjectiveOutcomeRelationClaim, ObjectiveOutcomeRelationEvidence,
                                    ObjectiveOutcomeRelationSnapshotV1) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(tokens | schema))

    def foreign(self, field):
        with self.assertRaises(ValueError): build(claims=(claim(**{field: 'foreign'}),))

    def direction(self, change, explicit):
        context = decision(sources(outcomes=(outcome_claim(change=change),)))
        row = build(context, (claim(context, relation=explicit),)).relations[0]
        self.assertIs(row.relation, explicit)
        self.assertIs(row.base_outcome_evidence.change, change)
        self.assertEqual(build(context, ()).relations, ())

    def test_001_exact_enum(self):
        self.assertEqual({n: v.value for n, v in ObjectiveOutcomeRelation.__members__.items()},
                         {v: v for v in ('SUPPORTS', 'OPPOSES', 'NEUTRAL', 'UNKNOWN')})
        class Other(str, Enum): SUPPORTS = 'SUPPORTS'
        for invalid in ('SUPPORTS', Other.SUPPORTS, None):
            with self.assertRaises(TypeError): claim(relation=invalid)
    def test_002_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().source_id = 'x'
    def test_003_evidence_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().relations[0].relation = ObjectiveOutcomeRelation.OPPOSES
    def test_004_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().relations = ()
    def test_005_concrete_strings_and_revalidation(self):
        class Text(str): pass
        c = claim()
        names = tuple(f.name for f in fields(c) if f.type is str)
        self.assertEqual(len(names), 11)
        for name in names:
            for invalid in (None, False, 1, Text('value')):
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ValueError):
                    claim(**{name: invalid})
            forged = claim(); object.__setattr__(forged, name, Text('forged'))
            with self.assertRaises(ValueError): build(claims=(forged,))
    def test_006_blank_identifiers(self):
        for f in fields(claim()):
            if f.type is str:
                for invalid in ('', ' \t\n'):
                    with self.subTest(name=f.name), self.assertRaises(ValueError): claim(**{f.name: invalid})
    def test_007_opaque_whitespace_preserved(self):
        c = claim(source_id=' source:/β ', assessment_policy_id=' policy ', evidence_refs=(' ref ',))
        row = build(claims=(c,)).relations[0]
        self.assertEqual((row.source_id, row.assessment_policy_id, row.evidence_refs), (' source:/β ', ' policy ', (' ref ',)))
    def test_008_objective_concrete(self):
        with self.assertRaises(ValueError): claim(objective_id=None)
        with self.assertRaises(ValueError): claim(objective_id=' ')
    def test_009_exact_tick_type(self):
        class Integer(int): pass
        for tick in (True, False, 1.0, '1', Integer(1), None):
            with self.assertRaises(TypeError): claim(basis_tick=tick)
        self.assertEqual(claim(basis_tick=0).basis_tick, 0)
    def test_010_negative_tick(self):
        with self.assertRaises(ValueError): claim(basis_tick=-1)
        forged = claim(); object.__setattr__(forged, 'basis_tick', True)
        with self.assertRaises(TypeError): build(claims=(forged,))
    def test_011_exact_refs_tuple(self):
        class Tuple(tuple): pass
        class Text(str): pass
        for refs in ([], ['r'], None, Tuple(('r',))):
            with self.assertRaises(TypeError): claim(evidence_refs=refs)
        for refs in (('',), (' ',), (1,), (Text('r'),)):
            with self.assertRaises(ValueError): claim(evidence_refs=refs)
    def test_012_duplicate_refs(self):
        with self.assertRaises(ValueError): claim(evidence_refs=('r', 'r'))
        c = claim(); object.__setattr__(c, 'evidence_refs', ['r'])
        with self.assertRaises(TypeError): build(claims=(c,))
    def test_013_empty_and_ordered_refs(self):
        self.assertEqual(build(claims=(claim(evidence_refs=()),)).relations[0].evidence_refs, ())
        a, b = claim(evidence_refs=('a', 'b')), claim(evidence_refs=('b', 'a'))
        self.assertNotEqual(build(claims=(a,)).snapshot_id, build(claims=(b,)).snapshot_id)
    def test_014_semantic_duplicate_regardless_provenance(self):
        c = claim()
        for other in (c, replace(c, source_id='other'), replace(c, assessment_policy_id='other'),
                      replace(c, relation=ObjectiveOutcomeRelation.OPPOSES)):
            with self.assertRaisesRegex(ValueError, 'duplicate_relation_semantic_key'): build(claims=(c, other))
    def test_015_foreign_decision(self): self.foreign('decision_context_id')
    def test_016_foreign_option(self): self.foreign('option_id')
    def test_017_foreign_objective_context(self): self.foreign('objective_context_id')
    def test_018_foreign_objective_horizon(self): self.foreign('objective_horizon_id')
    def test_019_foreign_objective_id(self): self.foreign('objective_id')
    def test_020_foreign_outcome_context(self): self.foreign('outcome_context_id')
    def test_021_foreign_baseline(self): self.foreign('outcome_baseline_id')
    def test_022_foreign_outcome_horizon(self): self.foreign('outcome_horizon_id')
    def test_023_foreign_dimension(self): self.foreign('dimension_id')
    def test_024_missing_and_other_option_outcome(self):
        context = decision(sources(outcomes=()))
        with self.assertRaisesRegex(ValueError, 'missing_exact_outcome'): build(context)
        context = decision(sources(outcomes=(outcome_claim(option_id='other'),)),
                           request((binding(), binding(option_id='other'))))
        with self.assertRaisesRegex(ValueError, 'missing_exact_outcome'): build(context)
    def test_025_exact_binding_and_structural_duplicates(self):
        context = decision(); option = context.options[0]
        self.assertEqual(build(context).relations[0].dimension_id, option.outcome_evidences[0].dimension_id)
        duplicate = replace(context, options=(replace(option, outcome_evidences=option.outcome_evidences * 2),))
        with self.assertRaisesRegex(ValueError, 'duplicate_embedded_outcome'): build(duplicate, ())
        foreign = replace(option.outcome_evidences[0], option_id='foreign')
        with self.assertRaisesRegex(ValueError, 'foreign_embedded_outcome'):
            build(replace(context, options=(replace(option, outcome_evidences=(foreign,)),)), ())
    def test_026_exact_objective_object(self):
        context = decision()
        self.assertIs(build(context).relations[0].base_objective_assessment, context.objective_assessment)
        foreign = replace(context.objective_assessment, horizon_id='foreign')
        with self.assertRaisesRegex(ValueError, 'foreign_embedded_objective'):
            build(replace(context, objective_assessment=foreign), ())
    def test_027_exact_outcome_object(self):
        context = decision()
        self.assertIs(build(context).relations[0].base_outcome_evidence, context.options[0].outcome_evidences[0])
    def test_028_exact_claim_object(self):
        context = decision(); c = claim(context)
        self.assertIs(build(context, (c,)).relations[0].base_claim, c)
    def test_029_objective_absent_empty(self):
        context = decision(sources(objectives=()))
        result = build(context, ())
        self.assertIsNone(result.objective_id); self.assertEqual(result.relations, ())
        self.assertEqual(result.decision_context_object_id, context.context_id)
    def test_030_objective_absent_reject_claim(self):
        with self.assertRaisesRegex(ValueError, 'concrete_objective_required'): build(decision(sources(objectives=())))
    def test_031_objective_unknown_empty(self):
        context = decision(sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),)))
        result = build(context, ())
        self.assertIsNone(result.objective_id); self.assertEqual(result.relations, ())
    def test_032_objective_unknown_reject_claim(self):
        context = decision(sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),)))
        with self.assertRaisesRegex(ValueError, 'concrete_objective_required'): build(context)
    def test_033_known_objective_zero_claims(self):
        result = build(claims=())
        self.assertEqual(result.objective_id, 'opaque-intent'); self.assertEqual(result.relations, ())
    def test_034_no_synthetic_unknown(self):
        context, claims = multi(('SUPPORTS', 'OPPOSES', 'UNKNOWN'))
        self.assertEqual(len(build(context, claims[:1]).relations), 1)
    def test_035_explicit_unknown(self):
        self.assertIs(build(claims=(claim(relation=ObjectiveOutcomeRelation.UNKNOWN),)).relations[0].relation, ObjectiveOutcomeRelation.UNKNOWN)
    def test_036_absence_distinct_unknown(self):
        absent = build(claims=()); unknown = build(claims=(claim(relation=ObjectiveOutcomeRelation.UNKNOWN),))
        self.assertEqual(len(absent.relations), 0); self.assertEqual(len(unknown.relations), 1)
        self.assertNotEqual(absent.snapshot_id, unknown.snapshot_id)
    def test_037_supports_retained(self):
        self.assertIs(build().relations[0].relation, ObjectiveOutcomeRelation.SUPPORTS)
    def test_038_opposes_retained(self):
        self.assertIs(build(claims=(claim(relation=ObjectiveOutcomeRelation.OPPOSES),)).relations[0].relation, ObjectiveOutcomeRelation.OPPOSES)
    def test_039_neutral_retained(self):
        self.assertIs(build(claims=(claim(relation=ObjectiveOutcomeRelation.NEUTRAL),)).relations[0].relation, ObjectiveOutcomeRelation.NEUTRAL)
    def test_040_increase_can_oppose(self): self.direction(OutcomeChange.INCREASE, ObjectiveOutcomeRelation.OPPOSES)
    def test_041_decrease_can_support(self): self.direction(OutcomeChange.DECREASE, ObjectiveOutcomeRelation.SUPPORTS)
    def test_042_unchanged_can_support(self): self.direction(OutcomeChange.UNCHANGED, ObjectiveOutcomeRelation.SUPPORTS)
    def test_043_unknown_has_no_mapping(self): self.direction(OutcomeChange.UNKNOWN, ObjectiveOutcomeRelation.NEUTRAL)
    def test_044_unknown_outcome_accepts_each_explicit_relation(self):
        for value in ObjectiveOutcomeRelation: self.direction(OutcomeChange.UNKNOWN, value)
    def test_045_multiple_dimensions_preserved(self):
        context, claims = multi(('SUPPORTS', 'NEUTRAL', 'OPPOSES', 'UNKNOWN'))
        rows = build(context, claims).relations
        self.assertEqual(tuple(r.relation for r in rows), tuple(c.relation for c in claims))
        self.assertTrue(all(r.base_claim is c for r, c in zip(rows, claims)))
    def test_046_mixed_support_opposition(self):
        context, claims = multi(('SUPPORTS', 'OPPOSES'))
        self.assertEqual(tuple(r.relation.value for r in build(context, claims).relations), ('SUPPORTS', 'OPPOSES'))
    def test_047_unknown_and_support(self):
        context, claims = multi(('UNKNOWN', 'SUPPORTS'))
        self.assertEqual(tuple(r.relation.value for r in build(context, claims).relations), ('UNKNOWN', 'SUPPORTS'))
    def test_048_no_option_verdict(self): self.no_terms('alignment', 'option_alignment', 'OPTION_SUPPORTS_OBJECTIVE', 'OPTION_ALIGNED', 'OPTION_MISALIGNED', 'option_verdict')
    def test_049_no_majority(self):
        context, claims = multi(('SUPPORTS', 'SUPPORTS', 'SUPPORTS', 'OPPOSES'))
        self.assertEqual(tuple(r.relation for r in build(context, claims).relations), tuple(c.relation for c in claims))
        self.no_terms('majority', 'vote', 'net_relation')
    def test_050_no_counting_preference(self): self.no_terms('Counter', 'count', 'sum', 'support_count', 'opposition_count')
    def test_051_no_scores(self): self.no_terms('score', 'option_score', 'objective_score', 'alignment_score')
    def test_052_no_weights(self): self.no_terms('weight', 'weights', 'weighted')
    def test_053_no_priorities(self): self.no_terms('priority', 'importance', 'tier')
    def test_054_no_magnitude(self): self.no_terms('magnitude', 'strength', 'relation_strength')
    def test_055_no_confidence(self): self.no_terms('confidence', 'Confidence')
    def test_056_no_probability(self): self.no_terms('probability', 'likelihood')
    def test_057_no_utility(self): self.no_terms('utility', 'reward')
    def test_058_no_expected_value(self): self.no_terms('expected_value', 'future_value')
    def test_059_no_ranking(self): self.no_terms('rank', 'ranking', 'ranked', 'best')
    def test_060_no_selection(self): self.no_terms('selected', 'selected_option', 'winner', 'select')
    def test_061_no_recommendation(self): self.no_terms('recommended', 'recommendation', 'preferred')
    def test_062_no_action(self): self.no_terms('action', 'Action', 'authority', 'Authority')
    def test_063_no_opportunity_cost(self): self.no_terms('opportunity_cost', 'foregone_value', 'regret')
    def test_064_no_pairwise_comparison(self): self.no_terms('pairwise', 'compare', 'comparison', 'alternative')
    def test_065_no_dominance(self): self.no_terms('dominance', 'dominated', 'dominates')
    def test_066_no_pareto(self): self.no_terms('pareto', 'Pareto', 'pareto_verdict')
    def test_067_no_tradeoff(self): self.no_terms('trade_off', 'tradeoff', 'lexicographic', 'best_alternative')
    def test_068_safety_independent(self):
        self.no_terms('safety_presence', 'safety_evaluation', 'gate_status', 'supported_risk_tolerance')
        for tolerance in SupportedRiskTolerance:
            context = decision(sources(tolerance=tolerance))
            self.assertIs(build(context).relations[0].relation, ObjectiveOutcomeRelation.SUPPORTS)
    def test_069_risk_blocking_supports(self):
        context = decision()
        self.assertEqual(context.options[0].safety_evaluation.gate_status.value, 'RISK_BLOCKING')
        self.assertIs(build(context).relations[0].relation, ObjectiveOutcomeRelation.SUPPORTS)
    def test_070_safety_absent_supports(self):
        context = decision(without_safety(sources()))
        self.assertIsNone(context.options[0].safety_evaluation)
        self.assertEqual(len(build(context).relations), 1)
    def test_071_no_feasibility_import(self):
        imports = [n.module for n in ast.walk(ast.parse(inspect.getsource(relation))) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any('feasibility' in str(n) for n in imports))
        self.no_terms('FeasibilitySnapshotV1', 'FeasibilityGateStatus', 'build_feasibility_snapshot_v1')
    def test_072_infeasible_elsewhere_independent(self):
        from test_feasibility_gate_v01 import build as feasibility, claim as requirement, FeasibilityRequirementState
        context = decision(); before = build(context)
        result = feasibility(context, claims=(requirement(context, state=FeasibilityRequirementState.UNSATISFIED),))
        self.assertEqual(result.assessments[0].status.value, 'INFEASIBLE')
        self.assertEqual(build(context), before)
    def test_073_no_execution(self): self.no_terms('execution', 'Execution', 'commitment', 'reversibility', 'abort', 'COMMITTED', 'COMPLETED')
    def test_074_no_attention_output(self): self.no_terms('urgency', 'speech', 'directive', 'advisory', 'awareness', 'suppress', 'output_authority', 'cognitive_load')
    def test_075_exact_tick_and_no_input_mutation(self):
        context = decision(); c = claim(context); before = asdict(context), asdict(c)
        result = build(context, (c,))
        self.assertEqual(result.relations[0].basis_tick, context.decision_assembly_tick)
        self.assertEqual((asdict(context), asdict(c)), before)
    def test_076_old_tick_rejected(self):
        context = decision(); self.assertGreater(context.decision_assembly_tick, 0)
        with self.assertRaisesRegex(ValueError, 'exact_decision_tick_required'):
            build(context, (claim(context, basis_tick=context.decision_assembly_tick - 1),))
    def test_077_future_tick_rejected(self):
        context = decision()
        with self.assertRaisesRegex(ValueError, 'exact_decision_tick_required'):
            build(context, (claim(context, basis_tick=context.decision_assembly_tick + 1),))
    def test_078_no_reaging(self):
        self.no_terms('max', 'latest_tick', 'freshness', 'age', 'time', 'clock_conversion')
        row = build().relations[0]
        self.assertEqual(row.base_outcome_evidence.basis_tick, 0)
        self.assertEqual(row.base_objective_assessment.basis_tick, 0)
    def test_079_timeline(self):
        context = decision(); self.assertEqual(build(context).timeline_id, context.timeline_id)
    def test_080_clock(self):
        context = decision(); self.assertEqual(build(context).selected_clock_id, context.selected_clock_id)
    def test_081_tick(self):
        context = decision(); self.assertEqual(build(context).evaluated_at_tick, context.decision_assembly_tick)
    def test_082_ruleset_and_api(self):
        self.assertEqual(build().ruleset, 'objective.outcome_relation.v1')
        parameters = inspect.signature(build_objective_outcome_relation_snapshot_v1).parameters
        self.assertEqual(tuple(parameters), ('decision_context', 'claims'))
        self.assertTrue(all(p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty for p in parameters.values()))
    def test_083_evidence_canonical_identity(self):
        row = build().relations[0]
        encoded = json.dumps(asdict(row), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(row.evidence_id, 'objective.outcome_relation.v1:evidence:' + hashlib.sha256(encoded).hexdigest())
        self.assertEqual(row.evidence_id, build().relations[0].evidence_id)
    def test_084_snapshot_canonical_identity(self):
        result = build()
        encoded = json.dumps(asdict(result), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id, 'objective.outcome_relation.v1:snapshot:' + hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result.snapshot_id, build().snapshot_id)
    def test_085_permutation_invariance(self):
        from itertools import permutations
        context, claims = multi(('UNKNOWN', 'SUPPORTS', 'OPPOSES'))
        expected = build(context, claims)
        for ordering in permutations(claims): self.assertEqual(build(context, ordering).snapshot_id, expected.snapshot_id)
    def test_086_canonical_order_not_relation(self):
        context, claims = multi(('UNKNOWN', 'NEUTRAL', 'OPPOSES', 'SUPPORTS'))
        self.assertEqual(tuple(r.dimension_id for r in build(context, claims[::-1]).relations), ('0', '1', '2', '3'))
        context = decision(sources(outcomes=(outcome_claim(option_id='z'), outcome_claim(option_id='a'))),
                           request((binding(option_id='z'), binding(option_id='a'))))
        result = build(context, (claim(context, option_id='z'), claim(context, option_id='a')))
        self.assertEqual(tuple(r.option_id for r in result.relations), ('a', 'z'))
    def test_087_source_identity(self):
        self.assertNotEqual(build().snapshot_id, build(claims=(claim(source_id='other'),)).snapshot_id)
        self.assertNotEqual(build().relations[0].evidence_id, build(claims=(claim(source_id='other'),)).relations[0].evidence_id)
    def test_088_policy_identity(self):
        self.assertNotEqual(build().snapshot_id, build(claims=(claim(assessment_policy_id='other'),)).snapshot_id)
    def test_089_relation_identity(self):
        self.assertEqual(len({build(claims=(claim(relation=r),)).snapshot_id for r in ObjectiveOutcomeRelation}), 4)
    def test_090_base_outcome_identity(self):
        a = decision(); b = decision(sources(outcomes=(outcome_claim(source_id='other', change=OutcomeChange.DECREASE),)))
        self.assertNotEqual(build(a).relations[0].evidence_id, build(b).relations[0].evidence_id)
    def test_091_objective_identity(self):
        context = decision(sources(objectives=(objective_claim(source_id='other'),)))
        self.assertNotEqual(build().relations[0].evidence_id, build(context).relations[0].evidence_id)
        context = decision(sources(objectives=(objective_claim(objective_id='another-intent'),)))
        self.assertNotEqual(build().snapshot_id, build(context, (claim(context, objective_id='another-intent'),)).snapshot_id)
    def test_092_context_lineage_identity(self):
        context = decision(); other = decision(req=request(context_binding_policy_id='other-policy'))
        a, b = build(context), build(other)
        self.assertEqual(a.decision_context_object_id, context.context_id)
        self.assertNotEqual(a.snapshot_id, b.snapshot_id)
        self.assertEqual(a.relations[0].evidence_id, b.relations[0].evidence_id)
    def test_093_unclaimed_outcomes_allowed(self):
        context, claims = multi(('SUPPORTS', 'OPPOSES'))
        result = build(context, claims[:1])
        self.assertEqual(len(result.relations), 1); self.assertEqual(len(context.options[0].outcome_evidences), 2)
    def test_094_extra_candidate_without_claims(self):
        context = decision(req=request((binding(), binding(option_id='other'))))
        result = build(context)
        self.assertEqual(len(context.options), 2); self.assertEqual(len(result.relations), 1)
    def test_095_empty_candidates_valid(self):
        context = decision(req=request(())); result = build(context, ())
        self.assertEqual(result.relations, ()); self.assertEqual(result.decision_context_object_id, context.context_id)
    def test_096_empty_candidates_reject_claims(self):
        with self.assertRaisesRegex(ValueError, 'foreign_option'): build(decision(req=request(())))
    def test_097_exact_boundary_and_no_discovery(self):
        context = decision(); option = context.options[0]; c = claim(context)
        for original in (context, option, c):
            Child = type('Child', (type(original),), {})
            child = Child(**{f.name: getattr(original, f.name) for f in fields(original)})
            with self.assertRaises(TypeError):
                build(child if original is context else replace(context, options=(child,)) if original is option else context,
                      (child,) if original is c else (c,))
        class Tuple(tuple): pass
        for invalid in ([], [c], Tuple((c,)), (object(),)):
            with self.assertRaises(TypeError): build(context, invalid)
        with self.assertRaises(ValueError): build(replace(context, options=(option, option)), ())
        with self.assertRaises(TypeError): build(replace(context, options=[option]), ())
        with self.assertRaises(TypeError): build(replace(context, options=(replace(option, outcome_evidences=[]),)), ())
        for kwargs in ({'ruleset': 'other'}, {'timeline_id': ' '}, {'decision_assembly_tick': True}):
            with self.assertRaises((TypeError, ValueError)): build(replace(context, **kwargs), ())
        forged = claim(); object.__setattr__(forged, 'relation', 'SUPPORTS')
        with self.assertRaises(TypeError): build(claims=(forged,))
    def test_098_cross_role_genericity(self):
        for role in ('Carry', 'Mid', 'Offlane', 'Support 4', 'Support 5', ' opaque:/β '):
            context = decision(sources(outcomes=(outcome_claim(option_id=role),)), request((binding(option_id=role),)))
            result = build(context, (claim(context, option_id=role),))
            self.assertEqual(result.relations[0].option_id, role)
    def test_099_opaque_dota_dimension_names(self):
        for dimension, change, value in (('exposure', OutcomeChange.DECREASE, ObjectiveOutcomeRelation.SUPPORTS),
                                         ('gold', OutcomeChange.INCREASE, ObjectiveOutcomeRelation.OPPOSES),
                                         (' spell.cooldown:/β ', OutcomeChange.UNKNOWN, ObjectiveOutcomeRelation.NEUTRAL)):
            context = decision(sources(outcomes=(outcome_claim(dimension_id=dimension, change=change),)))
            self.assertIs(build(context, (claim(context, dimension_id=dimension, relation=value),)).relations[0].relation, value)
    def test_100_no_legacy_imports(self):
        source = inspect.getsource(relation)
        imports = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {'dataclasses', 'enum', 'decision_context_v02'})
    def test_101_only_two_upstream_contracts(self):
        tree = ast.parse(inspect.getsource(relation))
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == 'decision_context_v02']
        self.assertEqual(len(imports), 1)
        self.assertEqual({a.name for a in imports[0].names}, {'DecisionContextV2', 'OptionDecisionContextV2'})
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}, {'hashlib', 'json'})
    def test_102_purity(self):
        import builtins, io, os, socket, subprocess, time, random, uuid
        context = decision(); c = claim(context); expected = build(context, (c,)); before = dict(vars(relation))
        with ExitStack() as stack:
            for module, name in ((builtins, 'open'), (io, 'open'), (os, 'getenv'), (subprocess, 'Popen'),
                                 (socket, 'socket'), (socket, 'getaddrinfo'), (time, 'time'), (time, 'monotonic'),
                                 (random, 'random'), (uuid, 'uuid4')):
                stack.enter_context(patch.object(module, name, side_effect=AssertionError('impure access')))
            class Forbidden(dict):
                def __getitem__(self, key): raise AssertionError('environment access')
                def get(self, *args): raise AssertionError('environment access')
                def __iter__(self): raise AssertionError('environment access')
            stack.enter_context(patch.object(os, 'environ', Forbidden()))
            self.assertEqual(build(context, (c,)).snapshot_id, expected.snapshot_id)
        self.assertEqual(before, vars(relation))
        for name, value in vars(relation).items():
            if not name.startswith('__'): self.assertNotIsInstance(value, (dict, list, set, bytearray))
    def test_103_exact_guard_and_documentation(self):
        root = Path(relation.__file__).resolve().parent.parent
        path = 'coach02/objective_outcome_relation_v01.py'
        self.assertEqual(import_violations(inspect.getsource(relation), path), [])
        for symbol in ('DecisionContextV2', 'OptionDecisionContextV2'):
            good = 'from .decision_context_v02 import ' + symbol
            self.assertEqual(import_violations(good, path), [])
            self.assertTrue(import_violations(good, 'coach02/arbitrary.py'))
            for bad in (good + ' as C', good + '\nalias=' + symbol, good + '\n' + symbol + '()',
                        'from .decision_context_v02 import *', 'import coach02.decision_context_v02',
                        'from .decision_context_v02 import build_decision_context_v2',
                        'from .decision_context_v02 import OptionOutcomeEvidence',
                        "__import__('coach02.decision_context_v02')", 'from .feasibility_gate_v01 import FeasibilitySnapshotV1'):
                self.assertTrue(import_violations(bad, path))
        document = (root/'OBJECTIVE_OUTCOME_RELATION_V01.md').read_text(encoding='utf-8')
        for text in ('Objective–Outcome Relation Evidence v0.1 is a semantic bridge, not an optimizer.',
                     'SUPPORTS does not mean GOOD, PREFERRED or RECOMMENDED.', 'OPPOSES does not mean BAD or REJECT.',
                     'Missing relation evidence is distinct from explicit UNKNOWN.',
                     'OutcomeChange does not mechanically determine objective relation.',
                     'Relation evidence is per exact outcome dimension; there is no option-level alignment verdict.',
                     'No counting, weighting, scoring, ranking, selection or opportunity cost occurs here.',
                     'Safety and Feasibility remain independent axes.', 'BLOCKER_BEFORE_TRADEOFF_EVIDENCE',
                     'BLOCKER_BEFORE_DECISION_ARBITER', 'BLOCKER_BEFORE_EXECUTION', 'BLOCKER_BEFORE_ATTENTION_GATE',
                     'BLOCKER_BEFORE_LIVE', 'ACCEPTED_V01_LIMITATION'):
            self.assertIn(text, document)
    def test_104_prior_file_preservation(self):
        root = Path(relation.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES), 127)
        for name, expected in BASELINE_HASHES:
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(), expected)


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
