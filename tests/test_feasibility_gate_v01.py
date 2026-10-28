"""Policy-bound executability, exact time, independence and preservation."""
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

from coach02 import feasibility_gate_v01 as gate
from coach02.feasibility_gate_v01 import (
    FeasibilityRequirementState, FeasibilityGateStatus, FeasibilityGateReason,
    FeasibilityRequirementClaim, OptionFeasibilityPolicyClaim,
    OptionFeasibilityAssessmentV1, FeasibilitySnapshotV1, build_feasibility_snapshot_v1,
)
from test_decision_context_v02 import (
    build as decision, request, binding, sources, without_safety,
    objective_claim, outcome_claim, StrategicObjectiveKnownness,
    OutcomeChange, SupportedRiskTolerance,
)


def policy(context=None, **changes):
    context = decision() if context is None else context
    values = dict(decision_context_id=context.decision_context_id, option_id='option-A',
                  feasibility_context_id='F', required_requirement_ids=('A',), feasibility_policy_id='policy.v1')
    values.update(changes)
    return OptionFeasibilityPolicyClaim(**values)


def claim(context=None, **changes):
    context = decision() if context is None else context
    values = dict(decision_context_id=context.decision_context_id, option_id='option-A',
                  feasibility_context_id='F', requirement_id='A', state=FeasibilityRequirementState.SATISFIED,
                  basis_tick=context.decision_assembly_tick, source_id='source', evidence_refs=('ref-b', 'ref-a'),
                  assessment_policy_id='assessment.v1')
    values.update(changes)
    return FeasibilityRequirementClaim(**values)


def build(context=None, policies=None, claims=None):
    context = decision() if context is None else context
    return build_feasibility_snapshot_v1(decision_context=context,
        policies=(policy(context),) if policies is None else policies,
        requirement_claims=(claim(context),) if claims is None else claims)


def row(states=('SATISFIED',), required=None):
    context = decision()
    ids = tuple(chr(65+i) for i in range(len(states))) if required is None else required
    claims = tuple(claim(context, requirement_id=ids[i], state=FeasibilityRequirementState(state))
                   for i, state in enumerate(states) if state is not None)
    return build(context, (policy(context, required_requirement_ids=ids),), claims).assessments[0]


def import_violations(source, path):
    if path == 'coach02/selection_hysteresis_v01.py':
        allowed = {
            'decision_arbiter_v01': {'DecisionArbiterResultV1', 'DecisionArbiterStatus', 'ArbiterCandidateAdmissionStatus', 'ArbiterCandidateAssessmentV1'},
            'decision_context_v02': {'OptionDecisionContextV2'},
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
    context_contracts = {'DecisionContextV2', 'OptionDecisionContextV2'}
    relation_contracts = {'ObjectiveOutcomeRelationSnapshotV1', 'ObjectiveOutcomeRelationEvidence'}
    consumers = {
        'coach02/feasibility_gate_v01.py': {'decision_context_v02': context_contracts},
        'coach02/objective_outcome_relation_v01.py': {'decision_context_v02': context_contracts},
        'coach02/pairwise_tradeoff_v01.py': {'decision_context_v02': context_contracts,
                                           'objective_outcome_relation_v01': relation_contracts},
    }
    allowed = consumers.get(path, {})
    consumer = bool(allowed)
    contracts = set().union(*allowed.values()) if consumer else context_contracts | relation_contracts
    domains = {'decision_context_v02', 'objective_outcome_relation_v01'}
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if domains.intersection(a.name.split('.')): errors.append('module import')
                if consumer and (a.name not in ('hashlib', 'json') or a.asname): errors.append('other import')
        if isinstance(node, ast.ImportFrom):
            module = (node.module or '').split('.')[-1]
            touches = bool(domains.intersection((node.module or '').split('.'))) or any(a.name in domains for a in node.names)
            if touches:
                exact = node.level == 1 and node.module in domains or node.level == 0 and node.module == 'coach02.' + module and module in domains
                if module not in allowed or not exact: errors.append('consumer/path')
                if any(a.name not in allowed.get(module, set()) or a.asname for a in node.names): errors.append('symbol/alias')
            elif consumer and (node.level or node.module not in ('dataclasses', 'enum')): errors.append('other domain')
        if consumer and isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name) and node.value.id in contracts:
            errors.append('contract alias')
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name in contracts | {'__import__', 'eval', 'exec'} or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                if consumer or any(isinstance(a, ast.Constant) and type(a.value) is str and any(m in a.value for m in domains) for a in node.args):
                    errors.append('constructor/dynamic import')
    return errors


class FeasibilityGateV1Tests(unittest.TestCase):
    def no_terms(self, *terms):
        tree = ast.parse(inspect.getsource(gate))
        tokens = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {f.name for cls in (FeasibilityRequirementClaim, OptionFeasibilityPolicyClaim,
                                   OptionFeasibilityAssessmentV1, FeasibilitySnapshotV1) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(tokens | names))

    def assert_gate(self, states, status, reason, required=None):
        result = row(states, required)
        self.assertEqual(result.status.value, status)
        self.assertEqual(result.reason.value, reason)
        return result

    def test_001_requirement_enum(self):
        self.assertEqual({k: v.value for k, v in FeasibilityRequirementState.__members__.items()}, {x: x for x in ('SATISFIED', 'UNSATISFIED', 'UNKNOWN')})
        class Other(str, Enum): SATISFIED = 'SATISFIED'
        for value in ('SATISFIED', Other.SATISFIED, None, 1):
            with self.assertRaises(TypeError): claim(state=value)
    def test_002_status_enum(self):
        self.assertEqual({k: v.value for k, v in FeasibilityGateStatus.__members__.items()}, {x: x for x in ('FEASIBLE', 'INFEASIBLE', 'INDETERMINATE')})
    def test_003_reason_enum(self):
        self.assertEqual({k: v.value for k, v in FeasibilityGateReason.__members__.items()}, {x: x for x in ('ALL_REQUIRED_REQUIREMENTS_SATISFIED', 'REQUIRED_REQUIREMENT_UNSATISFIED', 'REQUIRED_REQUIREMENT_UNKNOWN', 'REQUIRED_REQUIREMENT_ABSENT', 'FEASIBILITY_POLICY_ABSENT')})
    def test_004_claim_frozen(self):
        with self.assertRaises(FrozenInstanceError): claim().state = FeasibilityRequirementState.UNKNOWN
    def test_005_policy_frozen(self):
        with self.assertRaises(FrozenInstanceError): policy().required_requirement_ids = ()
    def test_006_assessment_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assessments[0].policy = None
    def test_007_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().assessments = ()
    def test_008_exact_concrete_ids(self):
        class Text(str): pass
        context = decision()
        for factory, names in ((claim, ('decision_context_id', 'option_id', 'feasibility_context_id', 'requirement_id', 'source_id', 'assessment_policy_id')),
                               (policy, ('decision_context_id', 'option_id', 'feasibility_context_id', 'feasibility_policy_id'))):
            for name in names:
                for value in (Text('id'), None, 1, False):
                    with self.subTest(name=name, value=value), self.assertRaises(ValueError): factory(context, **{name: value})
    def test_009_no_trim_unicode_and_no_mutation(self):
        context = decision(); text = '  β/要求  '
        p = policy(context, feasibility_context_id=text, required_requirement_ids=(text,))
        c = claim(context, feasibility_context_id=text, requirement_id=text, evidence_refs=(' r ', 'β'))
        before = (asdict(context), asdict(p), asdict(c))
        result = build(context, (p,), (c,))
        self.assertEqual(result.assessments[0].requirement_claims[0].requirement_id, text)
        self.assertEqual(before, (asdict(context), asdict(p), asdict(c)))
    def test_010_blanks_rejected(self):
        context = decision()
        for factory, names in ((claim, ('decision_context_id', 'option_id', 'feasibility_context_id', 'requirement_id', 'source_id', 'assessment_policy_id')),
                               (policy, ('decision_context_id', 'option_id', 'feasibility_context_id', 'feasibility_policy_id'))):
            for name in names:
                for value in ('', ' \t\n', '\u2003'):
                    with self.assertRaises(ValueError): factory(context, **{name: value})
    def test_011_exact_int_tick(self):
        class Number(int): pass
        for value in (True, False, 1.0, '1', None, Number(1)):
            with self.assertRaises(TypeError): claim(basis_tick=value)
    def test_012_negative_tick(self):
        with self.assertRaises(ValueError): claim(basis_tick=-1)
        self.assertEqual(claim(basis_tick=0).basis_tick, 0)
    def test_013_exact_refs_tuple_and_elements(self):
        class Tuple(tuple): pass
        class Text(str): pass
        for value in ([], 'r', None, Tuple(('r',))):
            with self.assertRaises(TypeError): claim(evidence_refs=value)
        for value in ('', ' ', None, Text('r'), 1):
            with self.assertRaises(ValueError): claim(evidence_refs=(value,))
    def test_014_duplicate_refs(self):
        with self.assertRaises(ValueError): claim(evidence_refs=('r', 'r'))
    def test_015_empty_refs_valid(self):
        context = decision(); c = claim(context, evidence_refs=())
        self.assertIs(build(context, claims=(c,)).assessments[0].requirement_claims[0], c)
    def test_016_duplicate_claim_key(self):
        context = decision(); c = claim(context)
        for other in (c, replace(c, source_id='other'), replace(c, state=FeasibilityRequirementState.UNKNOWN), replace(c, assessment_policy_id='other')):
            with self.assertRaisesRegex(ValueError, 'duplicate_requirement_claim'): build(context, claims=(c, other))
    def test_017_exact_policy_ids_tuple(self):
        class Tuple(tuple): pass
        class Text(str): pass
        for value in ([], 'A', None, Tuple(('A',))):
            with self.assertRaises(TypeError): policy(required_requirement_ids=value)
        for value in ('', ' ', None, Text('A'), 1):
            with self.assertRaises(ValueError): policy(required_requirement_ids=(value,))
    def test_018_duplicate_required_ids(self):
        with self.assertRaises(ValueError): policy(required_requirement_ids=('A', 'A'))
    def test_019_empty_policy_rejected(self):
        with self.assertRaises(ValueError): policy(required_requirement_ids=())
    def test_020_unique_policy_option(self):
        context = decision(); p = policy(context)
        for other in (p, replace(p, feasibility_context_id='other'), replace(p, feasibility_policy_id='other')):
            with self.assertRaisesRegex(ValueError, 'duplicate_option_policy'): build(context, (p, other), ())
    def test_021_exact_context_and_candidates(self):
        context = decision(); Child = type('Child', (type(context),), {})
        for value in (None, {}, Child(**{f.name: getattr(context, f.name) for f in fields(context)})):
            with self.assertRaises(TypeError): build_feasibility_snapshot_v1(decision_context=value, policies=(), requirement_claims=())
        for options in (list(context.options), (object(),)):
            with self.assertRaises(TypeError): build(replace(context, options=options), (), ())
        with self.assertRaises(ValueError): build(replace(context, options=context.options*2), (), ())
        for name, value in (('timeline_id', ''), ('selected_clock_id', None), ('decision_assembly_tick', True), ('decision_assembly_tick', -1), ('ruleset', 'other')):
            with self.assertRaises((TypeError, ValueError)): build(replace(context, **{name: value}), (), ())
    def test_022_foreign_policy_option(self):
        with self.assertRaisesRegex(ValueError, 'foreign_policy_option'): build(policies=(policy(option_id='foreign'),), claims=())
    def test_023_foreign_claim_option(self):
        with self.assertRaisesRegex(ValueError, 'foreign_claim_option'): build(claims=(claim(option_id='foreign'),))
    def test_024_foreign_policy_decision(self):
        with self.assertRaisesRegex(ValueError, 'foreign_policy_decision_context'): build(policies=(policy(decision_context_id='other'),), claims=())
    def test_025_foreign_claim_decision(self):
        with self.assertRaisesRegex(ValueError, 'foreign_claim_decision_context'): build(claims=(claim(decision_context_id='other'),))
    def test_026_claim_without_policy(self):
        with self.assertRaisesRegex(ValueError, 'claim_without_policy'): build(policies=())
    def test_027_wrong_feasibility_context(self):
        with self.assertRaisesRegex(ValueError, 'foreign_feasibility_context'): build(claims=(claim(feasibility_context_id='other'),))
    def test_028_unrequired_claim(self):
        with self.assertRaisesRegex(ValueError, 'unrequired_claim'): build(claims=(claim(requirement_id='other'),))
    def test_029_all_satisfied(self): self.assert_gate(('SATISFIED',)*3, 'FEASIBLE', 'ALL_REQUIRED_REQUIREMENTS_SATISFIED')
    def test_030_one_unsatisfied(self): self.assert_gate(('SATISFIED', 'UNSATISFIED'), 'INFEASIBLE', 'REQUIRED_REQUIREMENT_UNSATISFIED')
    def test_031_unsatisfied_dominates_unknown(self): self.assert_gate(('SATISFIED', 'UNKNOWN', 'UNSATISFIED'), 'INFEASIBLE', 'REQUIRED_REQUIREMENT_UNSATISFIED')
    def test_032_unsatisfied_dominates_missing(self):
        result = self.assert_gate(('UNSATISFIED', 'UNKNOWN', None), 'INFEASIBLE', 'REQUIRED_REQUIREMENT_UNSATISFIED')
        self.assertEqual(result.missing_requirement_ids, ('C',))
    def test_033_explicit_unknown(self): self.assert_gate(('UNKNOWN',), 'INDETERMINATE', 'REQUIRED_REQUIREMENT_UNKNOWN')
    def test_034_unknown_dominates_missing(self):
        result = self.assert_gate(('UNKNOWN', None), 'INDETERMINATE', 'REQUIRED_REQUIREMENT_UNKNOWN')
        self.assertEqual(result.missing_requirement_ids, ('B',))
    def test_035_required_missing(self): self.assert_gate(('SATISFIED', None), 'INDETERMINATE', 'REQUIRED_REQUIREMENT_ABSENT')
    def test_036_no_policy(self):
        result = build(policies=(), claims=()).assessments[0]
        self.assertIs(result.status, FeasibilityGateStatus.INDETERMINATE)
        self.assertIsNone(result.feasibility_context_id)
        self.assertIsNone(result.policy)
        self.assertEqual((result.requirement_claims, result.missing_requirement_ids), ((), ()))
    def test_037_no_policy_reason(self): self.assertIs(build(policies=(), claims=()).assessments[0].reason, FeasibilityGateReason.FEASIBILITY_POLICY_ABSENT)
    def test_038_missing_reason(self):
        result = row((None, None)); self.assertIs(result.reason, FeasibilityGateReason.REQUIRED_REQUIREMENT_ABSENT)
        self.assertEqual(result.missing_requirement_ids, ('A', 'B'))
    def test_039_unknown_reason(self):
        result = row(('UNKNOWN', 'UNKNOWN')); self.assertIs(result.reason, FeasibilityGateReason.REQUIRED_REQUIREMENT_UNKNOWN)
        self.assertEqual(result.missing_requirement_ids, ())
    def test_040_unsatisfied_reason(self):
        result = row(('UNSATISFIED',)*2); self.assertIs(result.reason, FeasibilityGateReason.REQUIRED_REQUIREMENT_UNSATISFIED)
    def test_041_satisfied_reason(self):
        self.assertIs(row().reason, FeasibilityGateReason.ALL_REQUIRED_REQUIREMENTS_SATISFIED)
    def test_042_missing_distinct_unknown(self):
        absent = row((None,)); unknown = row(('UNKNOWN',))
        self.assertEqual(absent.requirement_claims, ())
        self.assertEqual(absent.missing_requirement_ids, ('A',))
        self.assertEqual(unknown.missing_requirement_ids, ())
        self.assertIs(unknown.requirement_claims[0].state, FeasibilityRequirementState.UNKNOWN)
    def test_043_absent_policy_distinct_unknown(self):
        absent = build(policies=(), claims=()).assessments[0]; unknown = row(('UNKNOWN',))
        self.assertIsNone(absent.policy); self.assertIsNotNone(unknown.policy)
        self.assertNotEqual(absent.reason, unknown.reason)
    def test_044_claim_identity(self):
        context = decision(); c = claim(context)
        self.assertIs(build(context, claims=(c,)).assessments[0].requirement_claims[0], c)
    def test_045_policy_identity_and_original_order(self):
        context = decision(); p = policy(context, required_requirement_ids=('Z', 'A'))
        result = build(context, (p,), ()).assessments[0]
        self.assertIs(result.policy, p); self.assertEqual(p.required_requirement_ids, ('Z', 'A'))
    def test_046_base_option_identity(self):
        context = decision(); self.assertIs(build(context).assessments[0].base_option_context, context.options[0])
    def test_047_all_context_options_assessed(self):
        context = decision(req=request((binding(option_id='a'), binding(), binding(option_id='z'))))
        self.assertEqual([r.option_id for r in build(context).assessments], [o.option_id for o in context.options])
    def test_048_infeasible_retained(self): self.assertEqual(row(('UNSATISFIED',)).option_id, 'option-A')
    def test_049_indeterminate_retained(self): self.assertEqual(row(('UNKNOWN',)).option_id, 'option-A')
    def test_050_feasible_retained(self): self.assertEqual(row().option_id, 'option-A')
    def test_051_no_eligible_list(self):
        self.assertEqual(tuple(f.name for f in fields(FeasibilitySnapshotV1)), ('decision_context_id', 'decision_context_object_id', 'timeline_id', 'selected_clock_id', 'evaluated_at_tick', 'ruleset', 'assessments'))
        self.no_terms('eligible_options', 'filtered_options', 'eligible')
    def test_052_exact_tick_valid(self):
        context = decision(); result = build(context)
        self.assertEqual(result.assessments[0].requirement_claims[0].basis_tick, context.decision_assembly_tick)
    def test_053_old_tick_rejected(self):
        context = decision()
        self.assertGreater(context.decision_assembly_tick, 0)
        with self.assertRaisesRegex(ValueError, 'exact_decision_tick_required'): build(context, claims=(claim(context, basis_tick=context.decision_assembly_tick-1),))
    def test_054_future_tick_rejected_atomically(self):
        context = decision()
        with patch.object(gate, 'OptionFeasibilityAssessmentV1') as constructor:
            with self.assertRaisesRegex(ValueError, 'exact_decision_tick_required'): build(context, claims=(claim(context, basis_tick=context.decision_assembly_tick+1),))
            constructor.assert_not_called()
    def test_055_no_max_tick(self): self.no_terms('max', 'latest_tick')
    def test_056_no_freshness_or_policy_tick(self):
        self.no_terms('freshness', 'FRESH', 'STALE', 'CURRENT', 'HISTORICAL')
        self.assertNotIn('basis_tick', {f.name for f in fields(OptionFeasibilityPolicyClaim)})
    def test_057_timeline_inherited(self):
        context = decision(); self.assertEqual(build(context).timeline_id, context.timeline_id)
    def test_058_clock_inherited(self):
        context = decision(); self.assertEqual(build(context).selected_clock_id, context.selected_clock_id)
    def test_059_tick_inherited(self):
        context = decision(); self.assertEqual(build(context).evaluated_at_tick, context.decision_assembly_tick)
    def test_060_context_object_id(self):
        context = decision(); self.assertEqual(build(context).decision_context_object_id, context.context_id)
    def test_061_context_id_inherited(self):
        context = decision(req=request(decision_context_id='  β/context  '))
        self.assertEqual(build(context).decision_context_id, context.decision_context_id)
    def test_062_fixed_ruleset(self): self.assertEqual(build().ruleset, 'option.feasibility_gate.v1')
    def test_063_canonical_snapshot_identity(self):
        context = decision(); p = policy(context, required_requirement_ids=('β', 'A'))
        result = build(context, (p,), ())
        content = asdict(result)
        for assessment in content['assessments']:
            if assessment['policy'] is not None: assessment['policy']['required_requirement_ids'] = sorted(assessment['policy']['required_requirement_ids'])
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id, 'option.feasibility_gate.v1:snapshot:' + digest)
        self.assertEqual(result.snapshot_id, build(context, (p,), ()).snapshot_id)
    def test_064_policy_and_required_order_invariant(self):
        context = decision(req=request((binding(), binding(option_id='z'))))
        policies = (policy(context, required_requirement_ids=('Z', 'A')), policy(context, option_id='z'))
        one = build(context, policies, ())
        other = (policies[1], replace(policies[0], required_requirement_ids=('A', 'Z')))
        self.assertEqual(one.snapshot_id, build(context, other, ()).snapshot_id)
    def test_065_claim_order_invariant(self):
        context = decision(); p = policy(context, required_requirement_ids=('A', 'B'))
        claims = (claim(context), claim(context, requirement_id='B', state=FeasibilityRequirementState.UNKNOWN))
        self.assertEqual(build(context, (p,), claims).snapshot_id, build(context, (p,), tuple(reversed(claims))).snapshot_id)
    def test_066_assessment_order(self):
        context = decision(req=request((binding(option_id='z'), binding(option_id='a'))))
        self.assertEqual([r.option_id for r in build(context, (), ()).assessments], ['a', 'z'])
    def test_067_requirement_order(self):
        context = decision(); p = policy(context, required_requirement_ids=('z', 'a'))
        claims = (claim(context, requirement_id='z'), claim(context, requirement_id='a', source_id='z'))
        self.assertEqual([c.requirement_id for c in build(context, (p,), claims).assessments[0].requirement_claims], ['a', 'z'])
    def test_068_missing_order(self):
        context = decision(); p = policy(context, required_requirement_ids=('z', 'a', 'm'))
        self.assertEqual(build(context, (p,), ()).assessments[0].missing_requirement_ids, ('a', 'm', 'z'))
    def test_069_all_retained_content_binds_identity(self):
        original = build(); assessment = original.assessments[0]
        for name, value in (('timeline_id', 'other'), ('selected_clock_id', 'other'), ('evaluated_at_tick', original.evaluated_at_tick+1), ('ruleset', 'other')):
            self.assertNotEqual(original.snapshot_id, replace(original, **{name: value}).snapshot_id)
        for changed in (replace(assessment, missing_requirement_ids=('X',)), replace(assessment, reason=FeasibilityGateReason.REQUIRED_REQUIREMENT_UNKNOWN),
                        replace(assessment, base_option_context=replace(assessment.base_option_context, risk_context_id='other')),
                        replace(assessment, requirement_claims=(replace(assessment.requirement_claims[0], source_id='other'),))):
            self.assertNotEqual(original.snapshot_id, replace(original, assessments=(changed,)).snapshot_id)
    def test_070_context_identity_changes_snapshot(self):
        context = decision(); altered = replace(context, context_binding_policy_id='other')
        self.assertNotEqual(build(context).snapshot_id, build(altered).snapshot_id)
    def test_071_policy_id_binds_identity(self):
        context = decision(); self.assertNotEqual(build(context).snapshot_id, build(context, (policy(context, feasibility_policy_id='other'),)).snapshot_id)
    def test_072_state_binds_identity(self):
        context = decision(); self.assertNotEqual(build(context).snapshot_id, build(context, claims=(claim(context, state=FeasibilityRequirementState.UNSATISFIED),)).snapshot_id)
    def test_073_refs_order_is_content(self):
        context = decision(); c = claim(context)
        self.assertNotEqual(build(context, claims=(c,)).snapshot_id, build(context, claims=(replace(c, evidence_refs=tuple(reversed(c.evidence_refs))),)).snapshot_id)
    def test_074_empty_context_valid(self): self.assertEqual(build(decision(req=request(())), (), ()).assessments, ())
    def test_075_empty_context_keeps_lineage(self):
        context = decision(req=request(())); result = build(context, (), ())
        self.assertEqual(result.decision_context_object_id, context.context_id)
    def test_076_empty_context_rejects_policy(self):
        with self.assertRaises(ValueError): build(decision(req=request(())), (policy(),), ())
    def test_077_empty_context_rejects_claim(self):
        with self.assertRaises(ValueError): build(decision(req=request(())), (), (claim(),))
    def test_078_blocking_safety_not_blocking_feasibility(self):
        context = decision(); self.assertEqual(context.options[0].safety_evaluation.gate_status.value, 'RISK_BLOCKING')
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_079_not_blocking_safety_not_feasibility(self):
        context = decision(sources(tolerance=SupportedRiskTolerance.TOLERATED))
        self.assertEqual(context.options[0].safety_evaluation.gate_status.value, 'RISK_NOT_BLOCKING')
        result = build(context, claims=(claim(context, state=FeasibilityRequirementState.UNSATISFIED),))
        self.assertIs(result.assessments[0].status, FeasibilityGateStatus.INFEASIBLE)
    def test_080_absent_safety_not_infeasible(self):
        context = decision(without_safety(sources()))
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_081_increase_not_feasibility(self):
        self.assertIs(build(claims=()).assessments[0].reason, FeasibilityGateReason.REQUIRED_REQUIREMENT_ABSENT)
    def test_082_decrease_not_infeasibility(self):
        context = decision(sources(outcomes=(outcome_claim(change=OutcomeChange.DECREASE),)))
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_083_absent_outcome_not_controlling(self):
        context = decision(sources(outcomes=()))
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_084_known_objective_not_feasibility(self):
        self.assertIs(build(claims=(claim(state=FeasibilityRequirementState.UNKNOWN),)).assessments[0].status, FeasibilityGateStatus.INDETERMINATE)
    def test_085_unknown_objective_not_blocking(self):
        context = decision(sources(objectives=(objective_claim(knownness=StrategicObjectiveKnownness.UNKNOWN, objective_id=None),)))
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_086_absent_objective_not_controlling(self):
        context = decision(sources(objectives=()))
        self.assertIs(build(context).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
    def test_087_feasible_not_recommended(self): self.no_terms('recommended', 'recommendation', 'desirability', 'GOOD')
    def test_088_infeasible_not_unsafe(self): self.no_terms('UNSAFE', 'unsafe', 'danger', 'risk')
    def test_089_indeterminate_not_dangerous(self): self.no_terms('dangerous', 'DANGEROUS', 'severity', 'risk_level')
    def test_090_no_score(self): self.no_terms('score', 'utility', 'weight', 'reward')
    def test_091_no_ranking(self): self.no_terms('rank', 'ranking', 'ranked', 'best')
    def test_092_no_option_selection(self): self.no_terms('selected_option', 'selected_plan', 'winner', 'select_option')
    def test_093_no_opportunity_cost(self): self.no_terms('opportunity_cost', 'dominance', 'trade_off', 'foregone_value')
    def test_094_no_action(self): self.no_terms('action', 'Action', 'FARM', 'FIGHT', 'PUSH', 'RETREAT')
    def test_095_no_execution_lifecycle(self): self.no_terms('Execution', 'ExecutionState', 'execution', 'COMMITTED', 'ABORTING', 'COMPLETED')
    def test_096_no_attention_authority(self): self.no_terms('authority', 'urgency', 'priority', 'speech', 'voice', 'attention', 'SUPPRESS')
    def test_097_path_requirement_opaque(self):
        context = decision(); p = policy(context, required_requirement_ids=('path.exists',))
        c = claim(context, requirement_id='path.exists')
        self.assertIs(build(context, (p,), (c,)).assessments[0].status, FeasibilityGateStatus.FEASIBLE)
        self.no_terms('pathfind', 'pathfinding', 'geometry', 'coordinates')
    def test_098_mechanics_and_roles_opaque(self):
        context = decision(); ids = ('mana.available', 'cooldown.ready', 'target.in_range', 'resource.present', 'channel.not_blocked', 'Carry', 'Mid', 'Offlane', 'Support 4', 'Support 5')
        result = build(context, (policy(context, required_requirement_ids=ids),), tuple(claim(context, requirement_id=x) for x in ids))
        self.assertIs(result.assessments[0].status, FeasibilityGateStatus.FEASIBLE)
        self.assertEqual({c.requirement_id for c in result.assessments[0].requirement_claims}, set(ids))
        self.no_terms('mana', 'cooldown', 'range', 'hero', 'role', 'inventory', 'spell', 'gold')
    def test_099_no_availability_dependency(self):
        self.no_terms('OptionAvailabilityEvidence', 'build_option_availability', 'Truth', 'Freshness')
    def test_100_no_legacy_and_exact_imports(self):
        tree = ast.parse(inspect.getsource(gate))
        self.assertEqual({(n.level, n.module): {a.name for a in n.names} for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)},
                         {(0, 'dataclasses'): {'asdict', 'dataclass'}, (0, 'enum'): {'Enum'}, (1, 'decision_context_v02'): {'DecisionContextV2', 'OptionDecisionContextV2'}})
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}, {'hashlib', 'json'})
    def test_101_no_embedded_semantic_access(self):
        self.no_terms('gate_status', 'safety_evaluation', 'safety_presence', 'outcome_presence', 'outcome_evidences', 'objective_assessment', 'objective_presence', 'knownness', 'objective_id', 'RiskConclusion', 'OutcomeChange')
    def test_102_pure_defensive_api(self):
        import builtins
        import os
        import random
        import socket
        import time
        import uuid
        context = decision(); p = policy(context); c = claim(context)
        expected = build(context, (p,), (c,)).snapshot_id
        with ExitStack() as stack:
            for owner, name in ((builtins, 'open'), (Path, 'read_text'), (socket, 'socket'), (socket, 'getaddrinfo'), (os, 'getenv'), (time, 'time'), (time, 'monotonic'), (random, 'random'), (uuid, 'uuid4')):
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError('impure operation')))
            self.assertEqual(build(context, (p,), (c,)).snapshot_id, expected)
        self.assertFalse(any(isinstance(v, (dict, list, set, bytearray)) for k, v in vars(gate).items() if not k.startswith('__')))
        signature = inspect.signature(build_feasibility_snapshot_v1)
        self.assertEqual(tuple(signature.parameters), ('decision_context', 'policies', 'requirement_claims'))
        self.assertTrue(all(p.kind == p.KEYWORD_ONLY and p.default == p.empty for p in signature.parameters.values()))
        class Tuple(tuple): pass
        for bad in ([], None, Tuple((p,)), (object(),)):
            with self.assertRaises(TypeError): build_feasibility_snapshot_v1(decision_context=context, policies=bad, requirement_claims=())
        for bad in ([], None, Tuple((c,)), (object(),)):
            with self.assertRaises(TypeError): build_feasibility_snapshot_v1(decision_context=context, policies=(p,), requirement_claims=bad)
        for original in (p, c):
            Child = type('Child', (type(original),), {})
            child = Child(**{f.name: getattr(original, f.name) for f in fields(original)})
            with self.assertRaises(TypeError): build(context, (child,) if original is p else (p,), (child,) if original is c else (c,))
        object.__setattr__(p, 'required_requirement_ids', ())
        with self.assertRaises(ValueError): build(context, (p,), ())
        object.__setattr__(c, 'state', 'SATISFIED')
        with self.assertRaises(TypeError): build(context, claims=(c,))
    def test_103_guard_exactness_and_documentation(self):
        root = Path(gate.__file__).resolve().parent.parent
        for path in [root/'run.py', *sorted((root/'coach').rglob('*.py')), *sorted((root/'coach02').rglob('*.py'))]:
            self.assertEqual(import_violations(path.read_text(encoding='utf-8'), path.relative_to(root).as_posix()), [], str(path))
        for symbol in ('DecisionContextV2', 'OptionDecisionContextV2'):
            good = 'from .decision_context_v02 import ' + symbol
            self.assertEqual(import_violations(good, 'coach02/feasibility_gate_v01.py'), [])
            self.assertTrue(import_violations(good, 'coach02/arbitrary.py'))
            for bad in (good+' as C', good+'\nalias='+symbol, good+'\n'+symbol+'()', 'from .decision_context_v02 import *',
                        'import coach02.decision_context_v02', 'from coach02 import decision_context_v02',
                        "__import__('coach02.decision_context_v02')", 'from .decision_context_v02 import build_decision_context_v2'):
                self.assertTrue(import_violations(bad, 'coach02/feasibility_gate_v01.py'))
        document = (root/'FEASIBILITY_GATE_V01.md').read_text(encoding='utf-8')
        for text in ('Feasibility Gate v0.1 evaluates modeled executability requirements; it does not choose actions.',
                     'FEASIBLE does not mean SAFE, GOOD, RECOMMENDED or SELECTED.', 'INFEASIBLE does not mean UNSAFE or strategically bad.',
                     'INDETERMINATE is epistemic/policy incompleteness, not danger.', 'Missing required claim is distinct from explicit UNKNOWN.',
                     'Safety, Outcome and Strategic Objective do not determine feasibility.',
                     'Legacy Option Availability v0.1 is farm/resource-specific and is not reused.',
                     'Feasibility Gate does not pathfind or compute Dota mechanics.', 'BLOCKER_BEFORE_DECISION_ARBITER',
                     'BLOCKER_BEFORE_EXECUTION', 'BLOCKER_BEFORE_ATTENTION_GATE', 'BLOCKER_BEFORE_LIVE', 'ACCEPTED_V01_LIMITATION',
                     'coach02/option_availability.py', 'OPTION_AVAILABILITY_V01.md', 'DecisionContextSeed', 'No adapter/reuse'):
            with self.subTest(text=text): self.assertIn(text, document)
    def test_104_existing_project_hashes(self):
        root = Path(gate.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES), 124)
        for name, expected in BASELINE_HASHES:
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(), expected)


BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'),
 ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'),
 ('DECISION_CONTEXT_V02.md', 'CB3F1615EC752ADF523DDFB7FA5F3C5A5ECE4EBB3E35E55C19C9449C649507F3'),
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
 ('coach02/decision_context_v02.py', '3F07B86C7FABA28118C87B9646D2094A3A7A65C531A9D07255CC0B25BB9D74EF'),
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
 ('tests/test_decision_context_v02.py', '100702613FFB1038A884C7CE9C7F3648B98C3CA8A7457A7A1ED5D6A25E4775D9'),
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
