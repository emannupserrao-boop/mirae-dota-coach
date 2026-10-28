"""Explicit assembly, absence, alignment, lineage and architecture boundaries."""
import ast
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import decision_context_v02 as assembly
from coach02.decision_context_v02 import (
    DecisionEvidencePresence, DecisionOptionBindingV2, DecisionContextRequestV2,
    OptionDecisionContextV2, DecisionContextV2, build_decision_context_v2,
)
from coach02.strategic_objective_context import (
    StrategicObjectiveKnownness, StrategicObjectiveClaim, build_strategic_objective_context,
)
from coach02.option_outcome_evidence import OutcomeChange, OptionOutcomeClaim, build_option_outcome_evidence
from coach02.option_safety_v02 import SupportedRiskTolerance, OptionSafetyGateStatus
from test_option_safety_v02 import evaluate


def binding(**changes):
    values = dict(option_id='option-A', risk_context_id='R', safety_context_id='safety-context',
                  outcome_context_id='O', outcome_baseline_id='B', outcome_horizon_id='H-out')
    values.update(changes)
    return DecisionOptionBindingV2(**values)


def request(bindings=None, **changes):
    values = dict(decision_context_id='D', objective_context_id='OBJ', objective_horizon_id='H-object',
                  context_binding_policy_id='binding.v2', option_bindings=(binding(),) if bindings is None else bindings)
    values.update(changes)
    return DecisionContextRequestV2(**values)


def objective_claim(**changes):
    values = dict(objective_context_id='OBJ', knownness=StrategicObjectiveKnownness.KNOWN,
                  objective_id='opaque-intent', horizon_id='H-object', basis_tick=0,
                  source_id='objective-source', evidence_refs=(), assessment_policy_id='objective-policy')
    values.update(changes)
    return StrategicObjectiveClaim(**values)


def outcome_claim(**changes):
    values = dict(option_id='option-A', outcome_context_id='O', dimension_id='dim', baseline_id='B',
                  horizon_id='H-out', change=OutcomeChange.INCREASE, basis_tick=0, source_id='outcome-source',
                  evidence_refs=(), assessment_policy_id='outcome-policy')
    values.update(changes)
    return OptionOutcomeClaim(**values)


def sources(objectives=None, outcomes=None, tolerance=SupportedRiskTolerance.NOT_TOLERATED):
    safety = evaluate(tolerance=tolerance)
    headers = dict(timeline_id=safety.timeline_id, selected_clock_id=safety.selected_clock_id,
                   evaluated_at_tick=safety.risk_assembly_tick)
    objective = build_strategic_objective_context(**headers, claims=(objective_claim(),) if objectives is None else objectives)
    outcome = build_option_outcome_evidence(**headers, claims=(outcome_claim(),) if outcomes is None else outcomes)
    return objective, safety, outcome


def build(triple=None, req=None):
    objective, safety, outcome = sources() if triple is None else triple
    return build_decision_context_v2(strategic_objective_snapshot=objective,
        option_safety_snapshot=safety, option_outcome_snapshot=outcome,
        request=request() if req is None else req)


def without_safety(triple):
    objective, safety, outcome = triple
    return objective, replace(safety, evaluations=()), outcome


CONTRACTS = {
    'strategic_objective_context': {'StrategicObjectiveSnapshot', 'StrategicObjectiveAssessment'},
    'option_safety_v02': {'OptionSafetySnapshotV2', 'OptionSafetyEvaluationV2'},
    'option_outcome_evidence': {'OptionOutcomeSnapshot', 'OptionOutcomeEvidence'},
}


def consumer_violations(source, path):
    if path == 'coach02/decision_arbiter_v01.py':
        allowed = {
            'decision_context_v02': {'DecisionContextV2', 'OptionDecisionContextV2', 'DecisionEvidencePresence'},
            'option_safety_v02': {'OptionSafetyEvaluationV2', 'OptionSafetyGateStatus'},
            'feasibility_gate_v01': {'FeasibilitySnapshotV1', 'OptionFeasibilityAssessmentV1', 'FeasibilityGateStatus'},
            'pairwise_tradeoff_v01': {'PairwiseTradeoffSnapshotV1', 'PairwiseTradeoffEvidenceV1', 'PairwiseTradeoffConclusion'},
        }
        contracts = set().union(*allowed.values())
        errors = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                if any(a.name not in ('hashlib', 'json') or a.asname for a in node.names):
                    errors.append('other/module import')
            if isinstance(node, ast.ImportFrom):
                module = (node.module or '').split('.')[-1]
                exact = (node.level == 1 and node.module in allowed or
                         node.level == 0 and node.module == 'coach02.' + module and module in allowed)
                if exact:
                    permitted = allowed[module]
                elif node.level == 0 and node.module in ('dataclasses', 'enum'):
                    permitted = {'dataclass'} if node.module == 'dataclasses' else {'Enum'}
                else:
                    permitted = set()
                    errors.append('other domain/path')
                if any(a.name not in permitted or a.asname for a in node.names):
                    errors.append('symbol/alias')
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name) and node.value.id in contracts:
                errors.append('contract alias')
            if isinstance(node, ast.Call):
                if (ast.unparse(node.func) in contracts | {'__import__', 'eval', 'exec'} or
                        isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'):
                    errors.append('constructor/dynamic import')
        return errors
    tree = ast.parse(source)
    errors = []
    consumer = path == 'coach02/decision_context_v02.py'
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(m in alias.name.split('.') for m in CONTRACTS): errors.append('module import')
                if consumer and (alias.name not in ('hashlib', 'json') or alias.asname): errors.append('unexpected import')
        if isinstance(node, ast.ImportFrom):
            module = (node.module or '').split('.')[-1]
            touches = module in CONTRACTS or any(a.name in CONTRACTS for a in node.names)
            if touches:
                exact = (node.level == 1 and node.module in CONTRACTS or
                         node.level == 0 and node.module == 'coach02.' + module and module in CONTRACTS)
                if not consumer or not exact: errors.append('unauthorized consumer/path')
                for alias in node.names:
                    if alias.asname or alias.name not in CONTRACTS.get(module, set()): errors.append('noncontract/alias')
                    imports.add(alias.name)
            elif consumer and (node.level or node.module not in ('dataclasses', 'enum')):
                errors.append('other domain')
    blocked = set().union(*CONTRACTS.values()) | {'__import__', 'eval', 'exec'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if ast.unparse(node.func) in blocked or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                if consumer or any(isinstance(arg, ast.Constant) and type(arg.value) is str and
                                   any(m in arg.value for m in CONTRACTS) for arg in node.args):
                    errors.append('constructor/dynamic import')
        if consumer and isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name) and node.value.id in imports:
            errors.append('contract alias')
    return errors


class DecisionContextV2Tests(unittest.TestCase):
    def blank(self, factory, field):
        class Text(str): pass
        for value in ('', ' \t\n', None, False, 1, Text('valid')):
            with self.subTest(field=field, value=value), self.assertRaises((TypeError, ValueError)):
                factory(**{field: value})
        value = ' opaque:/β ' + field + ' '
        self.assertEqual(getattr(factory(**{field: value}), field), value)

    def no_terms(self, *names):
        tree = ast.parse(inspect.getsource(assembly))
        tokens = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        schema = {f.name for cls in (DecisionOptionBindingV2, DecisionContextRequestV2,
                                    OptionDecisionContextV2, DecisionContextV2) for f in fields(cls)}
        self.assertTrue(set(names).isdisjoint(tokens | schema))

    def presence(self, triple, safety, outcome):
        row = build(triple).options[0]
        self.assertIs(row.safety_presence, safety)
        self.assertIs(row.outcome_presence, outcome)

    def snapshot_type(self, index):
        triple = sources()
        original = triple[index]
        Child = type('Child', (type(original),), {})
        child = Child(**{f.name: getattr(original, f.name) for f in fields(original)})
        for invalid in (None, {}, child):
            values = list(triple); values[index] = invalid
            with self.assertRaises(TypeError): build(tuple(values))
        container = ('assessments', 'evaluations', 'evidences')[index]
        rows = getattr(original, container)
        for invalid in (list(rows), (object(),)):
            values = list(triple); values[index] = replace(original, **{container: invalid})
            with self.assertRaises(TypeError): build(tuple(values))
        values = list(triple); values[index] = replace(original, **{container: rows * 2})
        with self.assertRaisesRegex(ValueError, 'duplicate_upstream_key'): build(tuple(values))

    def test_001_exact_presence_domain(self):
        self.assertEqual({k: v.value for k, v in DecisionEvidencePresence.__members__.items()},
                         {'PRESENT': 'PRESENT', 'ABSENT': 'ABSENT'})
    def test_002_presence_not_semantic_uncertainty(self):
        self.assertNotIn('UNKNOWN', DecisionEvidencePresence.__members__)
        self.no_terms('CURRENT', 'HISTORICAL', 'INELIGIBLE', 'UNSAFE')
    def test_003_request_frozen(self):
        with self.assertRaises(FrozenInstanceError): request().decision_context_id = 'x'
    def test_004_binding_frozen(self):
        with self.assertRaises(FrozenInstanceError): binding().option_id = 'x'
    def test_005_option_context_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().options[0].outcome_evidences = ()
    def test_006_root_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().options = ()
    def test_007_decision_id(self): self.blank(request, 'decision_context_id')
    def test_008_objective_context_id(self): self.blank(request, 'objective_context_id')
    def test_009_objective_horizon_id(self): self.blank(request, 'objective_horizon_id')
    def test_010_binding_policy_id(self): self.blank(request, 'context_binding_policy_id')
    def test_011_exact_bindings_and_request(self):
        class Tuple(tuple): pass
        class Child(DecisionOptionBindingV2): pass
        for value in ([], [binding()], Tuple((binding(),)), None, (object(),), (Child(**asdict(binding())),)):
            with self.assertRaises(TypeError): request(option_bindings=value)
        triple = sources()
        with self.assertRaises(TypeError):
            build_decision_context_v2(strategic_objective_snapshot=triple[0], option_safety_snapshot=triple[1],
                                     option_outcome_snapshot=triple[2], request=None)
        forged = request(); object.__setattr__(forged, 'option_bindings', [binding()])
        with self.assertRaises(TypeError): build(triple, forged)
    def test_012_option_id(self): self.blank(binding, 'option_id')
    def test_013_risk_context(self): self.blank(binding, 'risk_context_id')
    def test_014_none_safety_context(self): self.assertIsNone(binding(safety_context_id=None).safety_context_id)
    def test_015_concrete_safety_context(self):
        class Text(str): pass
        for value in ('', ' \t', False, 1, Text('valid')):
            with self.assertRaises(ValueError): binding(safety_context_id=value)
        self.assertEqual(binding(safety_context_id=' β ').safety_context_id, ' β ')
    def test_016_outcome_context(self): self.blank(binding, 'outcome_context_id')
    def test_017_outcome_baseline(self): self.blank(binding, 'outcome_baseline_id')
    def test_018_outcome_horizon(self): self.blank(binding, 'outcome_horizon_id')
    def test_019_duplicate_option_rejected(self):
        for other in (binding(), binding(risk_context_id='other'), binding(outcome_context_id='other')):
            with self.assertRaisesRegex(ValueError, 'duplicate_option_binding'): request((binding(), other))
    def test_020_distinct_options_and_opaque_roles(self):
        ids = ('Carry/FARM', 'Mid', 'Offlane', 'Support 4', 'Support 5', '  β  ')
        result = build(req=request(tuple(binding(option_id=x) for x in ids)))
        self.assertEqual([r.option_id for r in result.options], sorted(ids))
    def test_021_exact_objective_snapshot_and_rows(self): self.snapshot_type(0)
    def test_022_exact_safety_snapshot_and_rows(self): self.snapshot_type(1)
    def test_023_exact_outcome_snapshot_and_rows(self): self.snapshot_type(2)
    def test_024_timeline_alignment(self):
        triple = sources()
        for i in range(3):
            changed = list(triple); changed[i] = replace(changed[i], timeline_id='other')
            with self.assertRaisesRegex(ValueError, 'EXACT_ALIGNMENT'): build(tuple(changed))
        for bad in ('', ' ', None, False):
            changed = tuple(replace(s, timeline_id=bad) for s in triple)
            with self.assertRaises(ValueError): build(changed)
    def test_025_clock_alignment(self):
        triple = sources()
        for i in range(3):
            changed = list(triple); changed[i] = replace(changed[i], selected_clock_id='other')
            with self.assertRaisesRegex(ValueError, 'EXACT_ALIGNMENT'): build(tuple(changed))
    def test_026_tick_alignment(self):
        triple = sources()
        for i, field in enumerate(('evaluated_at_tick', 'risk_assembly_tick', 'evaluated_at_tick')):
            changed = list(triple); changed[i] = replace(changed[i], **{field: getattr(changed[i], field) + 1})
            with self.assertRaisesRegex(ValueError, 'EXACT_ALIGNMENT'): build(tuple(changed))
        for bad in (True, 1.0, '1', -1):
            changed = tuple(replace(s, **{field: bad}) for s, field in zip(triple,
                ('evaluated_at_tick', 'risk_assembly_tick', 'evaluated_at_tick')))
            with self.assertRaises((TypeError, ValueError)): build(changed)
    def test_027_no_max_tick(self):
        self.no_terms('max')
        o, s, u = sources()
        with self.assertRaises(ValueError): build((o, replace(s, risk_assembly_tick=s.risk_assembly_tick + 1), u))
    def test_028_no_temporal_refresh(self):
        o, s, u = sources()
        result = build((o, s, u))
        self.assertEqual(result.decision_assembly_tick, s.risk_assembly_tick)
        self.assertEqual(result.objective_assessment.basis_tick, 0)
        self.no_terms('freshness', 'FRESH', 'STALE', 'CURRENT', 'HISTORICAL')
    def test_029_objective_exact_pair(self):
        triple = sources(objectives=(objective_claim(objective_context_id='other'),
                                     objective_claim(horizon_id='other'), objective_claim()))
        self.assertEqual(build(triple).objective_assessment.base_claim, objective_claim())
    def test_030_objective_present(self): self.assertIs(build().objective_presence, DecisionEvidencePresence.PRESENT)
    def test_031_objective_absent(self):
        result = build(req=request(objective_horizon_id='missing'))
        self.assertIs(result.objective_presence, DecisionEvidencePresence.ABSENT)
        self.assertIsNone(result.objective_assessment)
    def test_032_unknown_objective_present(self):
        result = build(sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),)))
        self.assertIs(result.objective_presence, DecisionEvidencePresence.PRESENT)
        self.assertIs(result.objective_assessment.knownness, StrategicObjectiveKnownness.UNKNOWN)
    def test_033_objective_absent_not_unknown(self):
        absent = build(sources(objectives=()))
        unknown = build(sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),)))
        self.assertIsNone(absent.objective_assessment)
        self.assertIsNotNone(unknown.objective_assessment)
        self.assertNotEqual(absent.context_id, unknown.context_id)
    def test_034_safety_exact_risk_option(self):
        triple = sources()
        for field in ('risk_context_id', 'option_id'):
            row = build(triple, request((binding(**{field: 'other'}),))).options[0]
            self.assertIs(row.safety_presence, DecisionEvidencePresence.ABSENT)
    def test_035_safety_context_matches(self):
        triple = sources(); row = build(triple).options[0]
        self.assertEqual(row.safety_context_id, triple[1].evaluations[0].safety_context_id)
    def test_036_mismatched_safety_context_rejects(self):
        for value in ('other', None):
            with self.assertRaisesRegex(ValueError, 'safety_context_binding_mismatch'):
                build(req=request((binding(safety_context_id=value),)))
    def test_037_policy_absent_none_binding(self):
        triple = sources(tolerance=None)
        row = build(triple, request((binding(safety_context_id=None),))).options[0]
        self.assertIs(row.safety_presence, DecisionEvidencePresence.PRESENT)
        self.assertIsNone(row.safety_evaluation.safety_policy_claim)
        with self.assertRaises(ValueError): build(triple)
    def test_038_safety_missing_absent(self):
        row = build(without_safety(sources())).options[0]
        self.assertIs(row.safety_presence, DecisionEvidencePresence.ABSENT)
        self.assertIsNone(row.safety_evaluation)
    def test_039_indeterminate_present(self):
        row = build(sources(tolerance=SupportedRiskTolerance.UNKNOWN)).options[0]
        self.assertIs(row.safety_presence, DecisionEvidencePresence.PRESENT)
        self.assertIs(row.safety_evaluation.gate_status, OptionSafetyGateStatus.INDETERMINATE)
    def test_040_absent_not_indeterminate(self):
        a = build(without_safety(sources())); b = build(sources(tolerance=SupportedRiskTolerance.UNKNOWN))
        self.assertNotEqual(a.options[0].safety_presence, b.options[0].safety_presence)
        self.assertNotEqual(a.context_id, b.context_id)
    def test_041_outcome_exact_four_selectors(self):
        for field in ('option_id', 'outcome_context_id', 'outcome_baseline_id', 'outcome_horizon_id'):
            row = build(req=request((binding(**{field: 'other'}),))).options[0]
            self.assertEqual(row.outcome_evidences, ())
    def test_042_one_dimension(self): self.assertEqual(len(build().options[0].outcome_evidences), 1)
    def test_043_independent_dimensions(self):
        triple = sources(outcomes=(outcome_claim(dimension_id='x'), outcome_claim(dimension_id='y', change=OutcomeChange.DECREASE)))
        rows = build(triple).options[0].outcome_evidences
        self.assertEqual([(r.dimension_id, r.change) for r in rows], [('x', OutcomeChange.INCREASE), ('y', OutcomeChange.DECREASE)])
    def test_044_no_outcome_absent(self):
        row = build(sources(outcomes=())).options[0]
        self.assertIs(row.outcome_presence, DecisionEvidencePresence.ABSENT)
        self.assertEqual(row.outcome_evidences, ())
    def test_045_explicit_unknown_outcome_present(self):
        row = build(sources(outcomes=(outcome_claim(change=OutcomeChange.UNKNOWN),))).options[0]
        self.assertIs(row.outcome_presence, DecisionEvidencePresence.PRESENT)
        self.assertIs(row.outcome_evidences[0].change, OutcomeChange.UNKNOWN)
    def test_046_outcome_absent_not_unknown(self):
        a = build(sources(outcomes=())); b = build(sources(outcomes=(outcome_claim(change=OutcomeChange.UNKNOWN),)))
        self.assertNotEqual(a.options[0].outcome_presence, b.options[0].outcome_presence)
        self.assertNotEqual(a.context_id, b.context_id)
    def test_047_no_synthetic_dimensions(self):
        row = build(sources(outcomes=(outcome_claim(dimension_id='only'),))).options[0]
        self.assertEqual([r.dimension_id for r in row.outcome_evidences], ['only'])
    def test_048_extra_objective_ignored(self):
        triple = sources(objectives=(objective_claim(), objective_claim(objective_context_id='extra')))
        self.assertEqual(build(triple).objective_assessment.objective_context_id, 'OBJ')
    def test_049_extra_safety_ignored(self):
        o, s, u = sources(); extra = replace(s.evaluations[0], option_id='extra')
        result = build((o, replace(s, evaluations=s.evaluations + (extra,)), u))
        self.assertEqual([r.option_id for r in result.options], ['option-A'])
    def test_050_extra_outcome_ignored(self):
        triple = sources(outcomes=(outcome_claim(), outcome_claim(baseline_id='foreign', dimension_id='reward')))
        self.assertEqual([r.baseline_id for r in build(triple).options[0].outcome_evidences], ['B'])
    def test_051_no_safety_option_discovery(self):
        self.assertEqual(build(req=request(())).options, ())
    def test_052_no_outcome_option_discovery(self):
        triple = sources(outcomes=(outcome_claim(option_id='attractive/unbound'),))
        self.assertEqual([r.option_id for r in build(triple).options], ['option-A'])
    def test_053_no_objective_option_discovery(self):
        triple = sources(objectives=(objective_claim(objective_id='option-B'),))
        self.assertEqual([r.option_id for r in build(triple).options], ['option-A'])
    def test_054_both_present(self): self.presence(sources(), DecisionEvidencePresence.PRESENT, DecisionEvidencePresence.PRESENT)
    def test_055_safety_only(self): self.presence(sources(outcomes=()), DecisionEvidencePresence.PRESENT, DecisionEvidencePresence.ABSENT)
    def test_056_outcome_only(self): self.presence(without_safety(sources()), DecisionEvidencePresence.ABSENT, DecisionEvidencePresence.PRESENT)
    def test_057_both_absent(self): self.presence(without_safety(sources(outcomes=())), DecisionEvidencePresence.ABSENT, DecisionEvidencePresence.ABSENT)
    def test_058_incomplete_candidate_retained(self):
        result = build(req=request((binding(option_id='unseen'),)))
        self.assertEqual(len(result.options), 1)
        self.assertEqual(result.options[0].option_id, 'unseen')
        self.assertIs(result.options[0].safety_presence, DecisionEvidencePresence.ABSENT)
        self.assertIs(result.options[0].outcome_presence, DecisionEvidencePresence.ABSENT)
    def test_059_empty_options_absent_objective(self):
        result = build(sources(objectives=()), request(()))
        self.assertEqual(result.options, ())
        self.assertIs(result.objective_presence, DecisionEvidencePresence.ABSENT)
    def test_060_empty_options_shared_objective(self):
        result = build(req=request(()))
        self.assertEqual(result.options, ())
        self.assertIs(result.objective_presence, DecisionEvidencePresence.PRESENT)
    def test_061_exact_objective_object(self):
        triple = sources(); self.assertIs(build(triple).objective_assessment, triple[0].assessments[0])
    def test_062_exact_safety_object(self):
        triple = sources(); self.assertIs(build(triple).options[0].safety_evaluation, triple[1].evaluations[0])
    def test_063_exact_outcome_objects(self):
        triple = sources(outcomes=(outcome_claim(dimension_id='x'), outcome_claim(dimension_id='y')))
        for result, original in zip(build(triple).options[0].outcome_evidences, triple[2].evidences): self.assertIs(result, original)
    def test_064_exact_base_binding(self):
        source = binding(); self.assertIs(build(req=request((source,))).options[0].base_binding, source)
    def test_065_exact_base_request(self):
        source = request(); self.assertIs(build(req=source).base_request, source)
    def test_066_no_mutation(self):
        triple = sources(); req = request((binding(option_id='z'), binding()))
        before = [asdict(x) for x in (*triple, req)]
        build(triple, req).context_id
        self.assertEqual(before, [asdict(x) for x in (*triple, req)])
    def test_067_upstream_ids_preserved(self):
        triple = sources(); result = build(triple)
        self.assertEqual((result.strategic_objective_snapshot_id, result.option_safety_snapshot_id,
                          result.option_outcome_snapshot_id), tuple(s.snapshot_id for s in triple))
    def test_068_fixed_ruleset(self):
        self.assertEqual(build().ruleset, 'decision.context.v2')
        self.assertTrue(build().context_id.startswith('decision.context.v2:context:'))
    def test_069_canonical_json_identity(self):
        result = build(req=request((binding(option_id='z'), binding()), decision_context_id='é/決定'))
        content = asdict(result)
        content['base_request']['option_bindings'] = sorted(content['base_request']['option_bindings'], key=lambda b: b['option_id'])
        expected = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.context_id, 'decision.context.v2:context:' + expected)
        self.assertEqual(result.context_id, result.context_id)
        self.assertNotEqual(result.context_id, replace(result, ruleset='other').context_id)
    def test_070_binding_order_invariant_identity(self):
        triple = sources(); bindings = (binding(option_id='z'), binding())
        one = build(triple, request(bindings)); two = build(triple, request(tuple(reversed(bindings))))
        self.assertEqual(one.context_id, two.context_id)
        self.assertNotEqual(one.base_request.option_bindings, two.base_request.option_bindings)
    def test_071_canonical_option_order(self):
        result = build(req=request((binding(option_id='z'), binding(option_id='a'), binding())))
        self.assertEqual([r.option_id for r in result.options], ['a', 'option-A', 'z'])
    def test_072_outcome_order_normalized(self):
        o, s, u = sources(outcomes=(outcome_claim(dimension_id='z'), outcome_claim(dimension_id='a')))
        first = build((o, s, u)); second = build((o, s, replace(u, evidences=tuple(reversed(u.evidences)))))
        self.assertEqual(first.options[0].outcome_evidences, second.options[0].outcome_evidences)
        self.assertEqual([r.dimension_id for r in second.options[0].outcome_evidences], ['a', 'z'])
    def test_073_decision_context_id_binds_identity(self):
        triple = sources(); self.assertNotEqual(build(triple).context_id, build(triple, request(decision_context_id='other')).context_id)
    def test_074_policy_binds_identity(self):
        triple = sources(); self.assertNotEqual(build(triple).context_id, build(triple, request(context_binding_policy_id='other')).context_id)
    def test_075_objective_selector_binds_identity(self):
        triple = sources(objectives=())
        self.assertNotEqual(build(triple).context_id, build(triple, request(objective_horizon_id='other')).context_id)
        self.assertNotEqual(build(triple).context_id, build(triple, request(objective_context_id='other')).context_id)
    def test_076_objective_presence_and_content_bind_identity(self):
        result = build()
        self.assertNotEqual(result.context_id, replace(result, objective_presence=DecisionEvidencePresence.ABSENT).context_id)
        row = replace(result.objective_assessment, source_id='other')
        self.assertNotEqual(result.context_id, replace(result, objective_assessment=row).context_id)
    def test_077_safety_presence_and_content_bind_identity(self):
        result = build(); row = result.options[0]
        self.assertNotEqual(result.context_id, replace(result, options=(replace(row, safety_presence=DecisionEvidencePresence.ABSENT),)).context_id)
        changed = replace(row, safety_evaluation=replace(row.safety_evaluation, gate_policy_id='other'))
        self.assertNotEqual(result.context_id, replace(result, options=(changed,)).context_id)
    def test_078_outcome_presence_and_content_bind_identity(self):
        result = build(); row = result.options[0]
        self.assertNotEqual(result.context_id, replace(result, options=(replace(row, outcome_presence=DecisionEvidencePresence.ABSENT),)).context_id)
        changed = replace(row, outcome_evidences=(replace(row.outcome_evidences[0], source_id='other'),))
        self.assertNotEqual(result.context_id, replace(result, options=(changed,)).context_id)
    def test_079_lineage_and_complete_bindings_bind_identity(self):
        result = build()
        for name in ('strategic_objective_snapshot_id', 'option_safety_snapshot_id', 'option_outcome_snapshot_id', 'timeline_id', 'selected_clock_id'):
            self.assertNotEqual(result.context_id, replace(result, **{name: 'other'}).context_id)
        self.assertNotEqual(result.context_id, replace(result, base_request=request(context_binding_policy_id='other')).context_id)
        row = result.options[0]
        self.assertNotEqual(result.context_id, replace(result, options=(replace(row, base_binding=binding(risk_context_id='other')),)).context_id)
        extra = build(sources(objectives=(objective_claim(), objective_claim(objective_context_id='extra'))))
        self.assertEqual(result.options, extra.options)
        self.assertNotEqual(result.context_id, extra.context_id)
    def test_080_tick_binds_identity(self):
        triple = sources(); tick = triple[1].risk_assembly_tick + 1
        other = (replace(triple[0], evaluated_at_tick=tick), replace(triple[1], risk_assembly_tick=tick), replace(triple[2], evaluated_at_tick=tick))
        self.assertNotEqual(build(triple).context_id, build(other).context_id)
    def test_081_no_safety_filtering(self):
        for tolerance in SupportedRiskTolerance:
            self.assertEqual(len(build(sources(tolerance=tolerance)).options), 1)
        self.no_terms('gate_status', 'reason', 'supported_risk_tolerance', 'RiskConclusion')
    def test_082_risk_blocking_retained(self):
        result = build(); self.assertIs(result.options[0].safety_evaluation.gate_status, OptionSafetyGateStatus.RISK_BLOCKING)
    def test_083_not_blocking_not_recommended(self):
        result = build(sources(tolerance=SupportedRiskTolerance.TOLERATED))
        self.assertIs(result.options[0].safety_evaluation.gate_status, OptionSafetyGateStatus.RISK_NOT_BLOCKING)
        self.no_terms('recommended', 'recommendation')
    def test_084_indeterminate_not_dropped(self):
        result = build(sources(tolerance=SupportedRiskTolerance.UNKNOWN), request((binding(), binding(option_id='other'))))
        self.assertEqual(len(result.options), 2)
    def test_085_no_outcome_utility_interpretation(self):
        self.no_terms('change', 'OutcomeChange', 'utility', 'reward', 'GOOD', 'BAD')
    def test_086_increase_not_preferred(self):
        self.assertEqual([r.option_id for r in build(req=request((binding(option_id='a'), binding()))).options], ['a', 'option-A'])
        self.no_terms('preferred', 'best', 'optimal')
    def test_087_decrease_not_penalized(self):
        result = build(sources(outcomes=(outcome_claim(change=OutcomeChange.DECREASE),)))
        self.assertIs(result.options[0].outcome_evidences[0].change, OutcomeChange.DECREASE)
        self.no_terms('penalty', 'penalized')
    def test_088_no_objective_alignment_and_independent_horizons(self):
        result = build()
        self.assertNotEqual(result.objective_horizon_id, result.options[0].outcome_horizon_id)
        self.no_terms('knownness', 'objective_id', 'alignment', 'supports_objective', 'opposes_objective')
    def test_089_unknown_objective_not_filtering(self):
        triple = sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),))
        self.assertEqual([r.option_id for r in build(triple).options], ['option-A'])
    def test_090_no_score(self): self.no_terms('score', 'weight', 'priority', 'importance')
    def test_091_no_rank(self): self.no_terms('rank', 'ranking', 'ranked')
    def test_092_no_selection(self): self.no_terms('selected', 'selected_option', 'selected_plan', 'winner')
    def test_093_no_opportunity_cost(self): self.no_terms('opportunity_cost', 'dominance', 'foregone_value', 'best_alternative', 'trade_off')
    def test_094_no_feasibility_availability(self): self.no_terms('feasible', 'available', 'feasibility', 'availability', 'EXECUTABLE', 'INFEASIBLE')
    def test_095_no_action_authority(self): self.no_terms('action', 'Action', 'authority', 'Authority', 'speech', 'voice', 'speak')
    def test_096_no_execution_lifecycle(self): self.no_terms('execution', 'Execution', 'ExecutionState', 'IN_PROGRESS', 'COMMITTED', 'ABORTING', 'COMPLETED', 'EXPIRED')
    def test_097_no_urgency_attention(self): self.no_terms('urgency', 'attention', 'DIRECTIVE', 'ADVISORY', 'AWARENESS', 'SUPPRESS')
    def test_098_exact_import_contract_allowlist(self):
        source = inspect.getsource(assembly)
        self.assertEqual(consumer_violations(source, 'coach02/decision_context_v02.py'), [])
        tree = ast.parse(source)
        imports = {(n.level, n.module): {a.name for a in n.names} for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {(0, 'dataclasses'): {'asdict', 'dataclass'}, (0, 'enum'): {'Enum'},
                                  **{(1, module): names for module, names in CONTRACTS.items()}})
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}, {'json', 'hashlib'})
        for module, names in CONTRACTS.items():
            for name in names:
                good = 'from .' + module + ' import ' + name
                self.assertEqual(consumer_violations(good, 'coach02/decision_context_v02.py'), [])
                self.assertTrue(consumer_violations(good, 'coach02/arbitrary.py'))
                for bad in (good + ' as C', good + '\nalias=' + name, good + '\n' + name + '()',
                            'from .' + module + ' import *', 'import coach02.' + module,
                            'from coach02 import ' + module, "__import__('coach02." + module + "')",
                            'from .' + module + ' import build_upstream'):
                    self.assertTrue(consumer_violations(bad, 'coach02/decision_context_v02.py'))
    def test_099_no_legacy_farm_or_arbitrary_consumers(self):
        root = Path(assembly.__file__).resolve().parent.parent
        for path in [root/'run.py', *sorted((root/'coach').rglob('*.py')), *sorted((root/'coach02').rglob('*.py'))]:
            self.assertEqual(consumer_violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()), [], str(path))
        self.no_terms('Decision', 'DecisionContext', 'FarmStrategicEvidence', 'assemble_farm_evidence', 'compose_farm_context')
    def test_100_no_lower_risk_import_or_upstream_builders(self):
        self.no_terms('RiskEvaluationSnapshot', 'evaluate_risk', 'build_risk_evidence', 'evaluate_option_safety_v2',
                      'build_option_outcome_evidence', 'build_strategic_objective_context')
    def test_101_no_runtime_and_required_api(self):
        self.no_terms('runtime_adapter', 'service', 'gsi', 'RuntimeObservation', 'PlayerModelSnapshotRef', 'planner')
        parameters = inspect.signature(build_decision_context_v2).parameters
        self.assertEqual(tuple(parameters), ('strategic_objective_snapshot', 'option_safety_snapshot', 'option_outcome_snapshot', 'request'))
        self.assertTrue(all(p.kind == p.KEYWORD_ONLY and p.default == p.empty for p in parameters.values()))
    def test_102_pure_and_no_mutable_globals(self):
        import builtins
        import os
        import random
        import socket
        import time
        import uuid
        triple = sources(); req = request(); expected = build(triple, req)
        before = {k: id(v) for k, v in vars(assembly).items() if not k.startswith('__')}
        self.assertFalse(any(isinstance(v, (dict, list, set, bytearray)) for k, v in vars(assembly).items() if not k.startswith('__')))
        with ExitStack() as stack:
            for owner, name in ((builtins, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
                                (socket, 'socket'), (socket, 'getaddrinfo'), (os, 'getenv'),
                                (time, 'time'), (time, 'monotonic'), (random, 'random'), (uuid, 'uuid4')):
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError('impure operation')))
            self.assertEqual(build(triple, req).context_id, expected.context_id)
        self.assertEqual(before, {k: id(v) for k, v in vars(assembly).items() if not k.startswith('__')})
    def test_103_documentation_boundaries(self):
        document = (Path(assembly.__file__).resolve().parent.parent/'DECISION_CONTEXT_V02.md').read_text(encoding='utf-8')
        for text in ('Decision Context v0.2 assembles evidence; it does not decide.',
                     'PRESENT/ABSENT are evidence-presence states, not semantic verdicts.',
                     'Safety ABSENT is not Safety INDETERMINATE.', 'Outcome ABSENT is not Outcome UNKNOWN.',
                     'Objective ABSENT is not Objective UNKNOWN.', 'RISK_BLOCKING does not remove a candidate from Decision Context.',
                     'Outcome direction does not become utility.', 'Decision Context does not evaluate objective alignment.',
                     'Decision Context does not rank or select options.', 'Decision Context does not evaluate feasibility.',
                     'Decision Context does not calculate opportunity cost.', 'Decision Context has no action or communication authority.',
                     'DECISION_CONTEXT_V02_EXACT_ALIGNMENT_RULE', 'BLOCKER_BEFORE_FEASIBILITY_GATE',
                     'BLOCKER_BEFORE_DECISION_ARBITER', 'BLOCKER_BEFORE_EXECUTION', 'BLOCKER_BEFORE_ATTENTION_GATE',
                     'BLOCKER_BEFORE_LIVE', 'ACCEPTED_V02_LIMITATION', 'No adapter', 'coach02/context_builder.py',
                     'coach02/decision.py', 'coach02/farm_context.py', 'coach02/strategic_evidence.py'):
            with self.subTest(text=text): self.assertIn(text, document)
    def test_104_existing_project_hashes(self):
        root = Path(assembly.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES), 121)
        for name, expected in BASELINE_HASHES:
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(), expected)


BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'),
 ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'),
 ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'),
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
 ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'),
 ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'),
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
 ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'),
 ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'),
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
