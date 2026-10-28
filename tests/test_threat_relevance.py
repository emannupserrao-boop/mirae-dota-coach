"""Explicit relevance with synthetic evidence produced by accepted upstream builders."""
import ast
import copy
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import inspect
import json
from pathlib import Path
import unittest

from coach02 import threat_relevance as relevance
from coach02.threat_relevance import (
    ThreatRelevance as Relevance, ThreatRelevanceClaim as Claim,
    ThreatRelevanceAssessment, ThreatRelevanceSnapshot, build_threat_relevance,
)
from coach02.threat_observation import ThreatProximity, ThreatObservationSnapshot, TemporalStatus
from coach02.missing_threat_resolver import MissingResolutionStatus as Status
from test_missing_threat_resolver import prepare, resolve


def pair(**kwargs):
    bundle = prepare(**kwargs)
    return bundle['positive'], resolve(bundle)


def claim(subject='A', value=Relevance.RELEVANT, context='carry-risk-context-v1', policy='relevance-v1'):
    return Claim(subject, value, context, policy)


def build(claims=None, **kwargs):
    positive, missing = pair(**kwargs)
    return build_threat_relevance(positive, missing, (claim(),) if claims is None else claims)


def row(value=Relevance.RELEVANT, **kwargs):
    return build((claim(value=value),), **kwargs).assessments[0]


def forged(value, **changes):
    value = copy.deepcopy(value)
    for name, replacement in changes.items():
        object.__setattr__(value, name, replacement)
    return value


class ThreatRelevanceTests(unittest.TestCase):
    def test_01_exact_enum(self):
        self.assertEqual({s.value for s in Relevance}, {'RELEVANT', 'NOT_RELEVANT', 'UNKNOWN'})

    def test_02_no_safety_states(self):
        self.assertTrue({'SAFE', 'DANGEROUS', 'MISSING', 'VISIBLE'}.isdisjoint(Relevance.__members__))

    def test_03_valid_claim(self):
        self.assertEqual(asdict(claim()), dict(threat_id='A', relevance=Relevance.RELEVANT,
                         relevance_context_id='carry-risk-context-v1', assessment_policy_id='relevance-v1'))

    def test_04_frozen_claim(self):
        with self.assertRaises(FrozenInstanceError): claim().relevance = Relevance.UNKNOWN

    def test_05_blank_subject(self):
        for value in ('', ' \n', None, 1, True):
            with self.subTest(value=value), self.assertRaises(ValueError): claim(subject=value)

    def test_06_blank_context(self):
        for value in ('', '\t', None, 1):
            with self.subTest(value=value), self.assertRaises(ValueError): claim(context=value)

    def test_07_blank_policy(self):
        for value in ('', ' ', None, 1):
            with self.subTest(value=value), self.assertRaises(ValueError): claim(policy=value)

    def test_08_explicit_enum_required(self):
        for value in ('RELEVANT', 'UNKNOWN', None, Status.MISSING):
            with self.subTest(value=value), self.assertRaises(TypeError): claim(value=value)

    def test_09_claim_tuple_required(self):
        for value in ([claim()], iter((claim(),)), None, (object(),)):
            with self.subTest(value=type(value)), self.assertRaises(TypeError):
                build_threat_relevance(*pair(), value)

    def test_10_duplicate_subject(self):
        for other in (claim(), claim(value=Relevance.UNKNOWN), claim(context='another'), claim(policy='v2')):
            with self.subTest(other=other), self.assertRaises(ValueError): build((claim(), other))

    def test_11_claim_order_independent(self):
        p, m = pair(positives=('B', 'A'), absences=(), assessments=())
        claims = (claim('B', Relevance.UNKNOWN), claim('A'))
        self.assertEqual(build_threat_relevance(p, m, claims), build_threat_relevance(p, m, claims[::-1]))

    def test_12_empty_claims(self):
        result = build(())
        self.assertEqual(result.assessments, ())
        self.assertTrue(result.positive_snapshot_id)
        self.assertTrue(result.missing_snapshot_id)

    def test_13_positive_snapshot_required(self):
        _, m = pair()
        for value in (None, {}, m):
            with self.assertRaises(TypeError): build_threat_relevance(value, m, ())

    def test_14_missing_snapshot_required(self):
        p, _ = pair()
        for value in (None, {}, p):
            with self.assertRaises(TypeError): build_threat_relevance(p, value, ())

    def test_15_timeline_match(self):
        p, m = pair()
        with self.assertRaisesRegex(ValueError, 'timeline_mismatch'):
            build_threat_relevance(p, replace(m, timeline_id='other'), ())

    def test_16_clock_match(self):
        p, m = pair()
        with self.assertRaisesRegex(ValueError, 'clock_mismatch'):
            build_threat_relevance(p, replace(m, selected_clock_id='other'), ())

    def test_17_exact_positive_snapshot_binding(self):
        p, m = pair()
        with self.assertRaisesRegex(ValueError, 'positive_snapshot_binding_mismatch'):
            build_threat_relevance(replace(p, event_id='another-event'), m, ())

    def test_18_foreign_subject(self):
        with self.assertRaisesRegex(ValueError, 'foreign_relevance_subject'): build((claim('foreign'),))

    def test_19_positive_only(self):
        assessment = row(absences=(), assessments=())
        self.assertEqual(assessment.positive_observation.threat_id, 'A')
        self.assertIsNone(assessment.missing_resolution)

    def test_20_missing_only_subject(self):
        assessment = row(positives=())
        self.assertIsNone(assessment.positive_observation)
        self.assertIs(assessment.missing_resolution.status, Status.NOT_JUSTIFIED)

    def test_21_both_axes(self):
        assessment = row()
        self.assertIsNotNone(assessment.positive_observation)
        self.assertIsNotNone(assessment.missing_resolution)

    def test_22_positive_object_preserved(self):
        p, m = pair()
        self.assertIs(build_threat_relevance(p, m, (claim(),)).assessments[0].positive_observation, p.observations[0])

    def test_23_missing_object_preserved(self):
        p, m = pair()
        self.assertIs(build_threat_relevance(p, m, (claim(),)).assessments[0].missing_resolution, m.resolutions[0])

    def test_24_missing_relevant(self):
        a = row(Relevance.RELEVANT)
        self.assertIs(a.relevance, Relevance.RELEVANT)
        self.assertIs(a.missing_resolution.status, Status.MISSING)

    def test_25_missing_not_relevant_adversarial_A(self):
        a = row(Relevance.NOT_RELEVANT)
        self.assertIs(a.relevance, Relevance.NOT_RELEVANT)
        self.assertIs(a.missing_resolution.status, Status.MISSING)
        self.assertFalse(hasattr(a, 'safe'))

    def test_26_missing_unknown(self):
        a = row(Relevance.UNKNOWN)
        self.assertIs(a.relevance, Relevance.UNKNOWN)
        self.assertIs(a.missing_resolution.status, Status.MISSING)

    def test_27_visible_away_relevant_adversarial_C(self):
        a = row(Relevance.RELEVANT, absences=(), assessments=())
        self.assertIs(a.positive_observation.proximity, ThreatProximity.AWAY)
        self.assertIs(a.relevance, Relevance.RELEVANT)
        self.assertFalse(hasattr(a, 'danger'))

    def test_28_visible_not_relevant(self):
        a = row(Relevance.NOT_RELEVANT, absences=(), assessments=(), proximity=ThreatProximity.NEARBY)
        self.assertIs(a.relevance, Relevance.NOT_RELEVANT)
        self.assertIs(a.positive_observation.proximity, ThreatProximity.NEARBY)

    def test_29_visible_nearby_unknown_adversarial_B(self):
        a = row(Relevance.UNKNOWN, absences=(), assessments=(), proximity=ThreatProximity.NEARBY)
        self.assertIs(a.relevance, Relevance.UNKNOWN)
        self.assertIs(a.positive_observation.temporal_status, TemporalStatus.FRESH)
        self.assertIs(a.positive_observation.proximity, ThreatProximity.NEARBY)

    def test_30_not_justified_any_relevance_adversarial_E(self):
        for value in Relevance:
            a = row(value, positive_tick=120)
            self.assertIs(a.relevance, value)
            self.assertIs(a.missing_resolution.status, Status.NOT_JUSTIFIED)

    def test_31_conflicted_any_relevance_adversarial_D(self):
        for value in Relevance:
            a = row(value, positive_tick=110)
            self.assertIs(a.relevance, value)
            self.assertIs(a.missing_resolution.status, Status.CONFLICTED)

    def test_32_no_automatic_unknown_adversarial_F(self):
        self.assertEqual(build((), positives=('A', 'B')).assessments, ())

    def test_33_subset_claims(self):
        result = build((claim('B'),), positives=('A', 'B'))
        self.assertEqual(tuple(a.threat_id for a in result.assessments), ('B',))

    def test_34_unclaimed_subject_absent(self):
        result = build((claim('A'),), positives=('A', 'B'))
        self.assertNotIn('B', {a.threat_id for a in result.assessments})

    def test_35_unknown_distinct_from_no_claim(self):
        unknown, empty = build((claim(value=Relevance.UNKNOWN),)), build(())
        self.assertEqual(len(unknown.assessments), 1)
        self.assertNotEqual(unknown.snapshot_id, empty.snapshot_id)

    def test_36_not_relevant_not_safe(self):
        a = row(Relevance.NOT_RELEVANT, positive_tick=110)
        self.assertIs(a.missing_resolution.status, Status.CONFLICTED)
        self.assertNotIn('safe', {f.name for f in fields(a)})

    def test_37_relevant_not_dangerous(self):
        a = row(Relevance.RELEVANT, positives=())
        self.assertIs(a.missing_resolution.status, Status.NOT_JUSTIFIED)
        self.assertNotIn('dangerous', {f.name for f in fields(a)})

    def test_38_no_current_state(self):
        self.assertEqual({f.name for f in fields(ThreatRelevanceAssessment)}, {
            'threat_id', 'relevance', 'relevance_context_id', 'assessment_policy_id',
            'positive_observation', 'missing_resolution'})

    def test_39_no_positive_precedence(self):
        a = row(proximity=ThreatProximity.NEARBY)
        self.assertIs(a.missing_resolution.status, Status.MISSING)
        self.assertIs(a.positive_observation.proximity, ThreatProximity.NEARBY)

    def test_40_no_missing_precedence(self):
        a = row(positive_ttl=1)
        self.assertIs(a.positive_observation.temporal_status, TemporalStatus.STALE)
        self.assertIs(a.missing_resolution.status, Status.MISSING)
        self.assertIs(a.missing_resolution.positive, a.positive_observation)

    def output_fields(self):
        return {f.name for cls in (ThreatRelevanceAssessment, ThreatRelevanceSnapshot) for f in fields(cls)}

    def test_41_no_risk_output(self):
        self.assertTrue({'risk', 'danger', 'increased_risk', 'recommendation', 'route'}.isdisjoint(self.output_fields()))

    def test_42_no_safety_output(self):
        self.assertTrue({'safe', 'unsafe', 'authority', 'action', 'safety'}.isdisjoint(self.output_fields()))

    def test_43_no_algorithm(self):
        self.assertEqual(tuple(inspect.signature(build_threat_relevance).parameters),
                         ('positive_snapshot', 'missing_snapshot', 'claims'))
        for proximity in ThreatProximity:
            for value in Relevance:
                self.assertIs(row(value, proximity=proximity).relevance, value)

    def test_44_opaque_hero_identity(self):
        a = build((claim('hero:any:Ω'),), positives=('hero:any:Ω',), absences=(), assessments=()).assessments[0]
        self.assertEqual(a.threat_id, 'hero:any:Ω')

    def test_45_no_mobility_logic(self):
        for context in ('global-teleport', 'no-mobility'):
            a = build((claim(value=Relevance.UNKNOWN, context=context),)).assessments[0]
            self.assertIs(a.relevance, Relevance.UNKNOWN)
            self.assertEqual(a.relevance_context_id, context)

    def test_46_no_item_logic(self):
        for policy in ('blink-item-equipped', 'no-item'):
            self.assertIs(build((claim(value=Relevance.NOT_RELEVANT, policy=policy),)).assessments[0].relevance,
                          Relevance.NOT_RELEVANT)

    def test_47_no_distance_path_logic(self):
        for proximity in ThreatProximity:
            self.assertIs(row(Relevance.UNKNOWN, proximity=proximity).relevance, Relevance.UNKNOWN)

    def test_48_opaque_objective_context(self):
        for context in ('farm-cycle-context-A', 'objective:ancient'):
            self.assertEqual(build((claim(context=context),)).assessments[0].relevance_context_id, context)

    def test_49_no_numeric_confidence(self):
        self.assertTrue({'score', 'confidence', 'probability'}.isdisjoint(self.output_fields()))

    def test_50_snapshot_frozen(self):
        with self.assertRaises(FrozenInstanceError): build().evaluated_at_tick = 123

    def test_51_assessment_frozen(self):
        with self.assertRaises(FrozenInstanceError): row().relevance_context_id = 'changed'

    def test_52_canonical_identity(self):
        result = build((claim(context='á\ncontext'),))
        digest = hashlib.sha256(json.dumps(asdict(result), sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(result.snapshot_id, 'threat.relevance_assessment.v1:snapshot:' + digest)
        self.assertEqual(result.snapshot_id, build((claim(context='á\ncontext'),)).snapshot_id)

    def test_53_input_order_same_identity(self):
        args = dict(positives=('B', 'A'), absences=(), assessments=())
        claims = (claim('A'), claim('B', Relevance.UNKNOWN))
        self.assertEqual(build(claims, **args).snapshot_id, build(claims[::-1], **args).snapshot_id)

    def test_54_relevance_changes_identity(self):
        self.assertEqual(len({build((claim(value=v),)).snapshot_id for v in Relevance}), 3)

    def test_55_context_changes_identity_adversarial_K(self):
        self.assertNotEqual(build((claim(context='one'),)).snapshot_id, build((claim(context='two'),)).snapshot_id)

    def test_56_policy_changes_identity(self):
        self.assertNotEqual(build((claim(policy='v1'),)).snapshot_id, build((claim(policy='v2'),)).snapshot_id)

    def test_57_positive_snapshot_changes_identity(self):
        first, second = build((), positive_tick=100), build((), positive_tick=101)
        self.assertNotEqual(first.positive_snapshot_id, second.positive_snapshot_id)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)

    def test_58_missing_snapshot_changes_identity(self):
        first, second = build((), absence_tick=110), build((), absence_tick=111)
        self.assertNotEqual(first.missing_snapshot_id, second.missing_snapshot_id)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)

    def test_59_nested_evidence_serialized(self):
        result = build()
        a = result.assessments[0]
        modified = replace(a, positive_observation=replace(a.positive_observation, source_id='changed'))
        self.assertNotEqual(result.snapshot_id, replace(result, assessments=(modified,)).snapshot_id)
        nested = replace(a.missing_resolution.assessment, scope_id='another-scope')
        modified = replace(a, missing_resolution=replace(a.missing_resolution, assessment=nested))
        self.assertNotEqual(result.snapshot_id, replace(result, assessments=(modified,)).snapshot_id)

    def test_60_two_threats_mixed_adversarial_J(self):
        result = build((claim('B', Relevance.UNKNOWN), claim('A')),
                       positives=('A', 'B'), absences=(), assessments=())
        self.assertEqual([(a.threat_id, a.relevance) for a in result.assessments],
                         [('A', Relevance.RELEVANT), ('B', Relevance.UNKNOWN)])

    def test_61_no_subject_borrowing(self):
        result = build((claim('A'), claim('B')), positives=('A', 'B'), absences=(), assessments=())
        for a in result.assessments:
            self.assertEqual(a.positive_observation.threat_id, a.threat_id)
            self.assertEqual(a.positive_observation.ref, 'pos.' + a.threat_id)
        with self.assertRaises(ValueError): build((claim('pos.A'),))

    def test_62_evaluation_tick(self):
        p, m = pair(positive_now=200)
        result = build_threat_relevance(p, m, (claim(),))
        self.assertEqual(result.evaluated_at_tick, max(p.evaluated_at_tick, m.resolved_at_tick))
        self.assertEqual(result.evaluated_at_tick, 200)

    def test_63_metadata_does_not_refresh(self):
        p, m = pair(positive_now=200)
        before = asdict(m)
        a = build_threat_relevance(p, m, (claim(),)).assessments[0]
        self.assertEqual(asdict(a.missing_resolution), before['resolutions'][0])
        self.assertEqual(a.missing_resolution.absence.age_ticks, 0)
        self.assertIs(a.missing_resolution.absence.temporal_status, TemporalStatus.FRESH)
        self.assertIs(a.positive_observation.temporal_status, TemporalStatus.STALE)

    def imports(self):
        tree = ast.parse(inspect.getsource(relevance))
        return {'.' * n.level + (n.module or '') for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}

    def calls(self):
        return {ast.unparse(n.func) for n in ast.walk(ast.parse(inspect.getsource(relevance))) if isinstance(n, ast.Call)}

    def test_64_no_observation_event_import(self):
        self.assertNotIn('.observation_event', self.imports())

    def test_65_no_temporal_import(self):
        self.assertNotIn('.temporal_evidence', self.imports())
        self.assertTrue({'.threat_absence_observation', '.visibility_completeness'}.isdisjoint(self.imports()))

    def test_66_no_safety_import(self):
        self.assertNotIn('.safety_evidence', self.imports())

    def test_67_no_decision_import(self):
        self.assertNotIn('.decision', self.imports())

    def test_68_semantic_imports_only(self):
        self.assertEqual(self.imports(), {'dataclasses', 'enum', 'hashlib', 'json',
                                        '.threat_observation', '.missing_threat_resolver'})

    def test_69_no_wall_clock(self):
        self.assertFalse(self.calls() & {'time.time', 'time.monotonic', 'datetime.now', 'datetime.utcnow'})

    def test_70_no_io(self):
        self.assertFalse(self.calls() & {'open', 'print', 'input', 'Path', 'eval', 'exec', '__import__'})

    def test_71_no_network(self):
        self.assertFalse(self.imports() & {'socket', 'urllib', 'requests', 'http', 'httpx'})

    def test_72_no_environment(self):
        self.assertFalse(self.imports() & {'os', 'sys'})

    def test_73_no_random(self):
        self.assertFalse(self.imports() & {'random', 'uuid', 'secrets'})

    def test_74_no_mutable_globals(self):
        tree = ast.parse(inspect.getsource(relevance))
        assigns = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))]
        self.assertEqual(len(assigns), 1)
        self.assertEqual(ast.literal_eval(assigns[0].value), 'threat.relevance_assessment.v1')
        self.assertFalse(any(isinstance(n, (ast.AsyncFunctionDef, ast.Global, ast.Nonlocal)) for n in ast.walk(tree)))

    def guards(self):
        root = Path(relevance.__file__).resolve().parent.parent
        for filename, method, module in (
            ('test_threat_observation.py', 'test_70_no_backward_production_import_or_orchestration', 'threat_observation'),
            ('test_missing_threat_resolver.py', 'test_85_no_backward_dependency', 'missing_threat_resolver')):
            tree = ast.parse((root / 'tests' / filename).read_text(encoding='utf-8'))
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
            selected = [n for n in fn.body if
                        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                        {'authorized_consumers', 'allowed_contracts', 'operations'} for t in n.targets) or
                        isinstance(n, ast.FunctionDef) and n.name == 'violations']
            self.assertEqual(len(selected), 4)
            namespace = {'ast': ast}
            exec(compile(ast.Module(body=selected, type_ignores=[]), filename, 'exec'), namespace)
            yield module, namespace

    def test_75_dependency_direction(self):
        for module, g in self.guards():
            self.assertEqual(g['violations'](inspect.getsource(relevance), 'coach02/threat_relevance.py'), [])
        root = Path(relevance.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evidence_assembly.py'})
        allowed_contracts = frozenset(('ThreatRelevanceSnapshot', 'ThreatRelevanceAssessment', 'ThreatRelevance'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure'))

        def violations(source, relative_path):
            tree = ast.parse(source)
            consumer = relative_path in authorized_consumers
            errors = []
            blocked_calls = set(operations) if consumer else set()
            if consumer:
                blocked_calls.update(allowed_contracts)
                blocked_calls.update({'getattr', 'eval', 'exec'})
            importers = {'__import__', 'importlib.import_module'}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if 'threat_relevance' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('threat_relevance' in (node.module or '').split('.') or
                               any(a.name == 'threat_relevance' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'threat_relevance') or
                                        (node.level == 0 and node.module == 'coach02.threat_relevance'))
                        if not consumer or not exact_module:
                            errors.append('unauthorized production consumer or import path')
                        for alias in node.names:
                            if alias.name not in allowed_contracts:
                                errors.append('non-contract symbol import')
                            else:
                                blocked_calls.add(alias.asname or alias.name)
            # Follow simple local aliases too; importing a contract does not grant
            # permission to instantiate it through a renamed factory reference.
            changed = True
            while changed:
                changed = False
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        value = node.value
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        if isinstance(value, ast.Name) and value.id in blocked_calls:
                            for target in targets:
                                if isinstance(target, ast.Name) and target.id not in blocked_calls:
                                    blocked_calls.add(target.id)
                                    changed = True
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = ast.unparse(node.func)
                if (name in blocked_calls or
                        consumer and isinstance(node.func, ast.Attribute) and node.func.attr in operations):
                    errors.append('constructor or orchestration call')
                if name in importers:
                    if consumer or any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                       and 'threat_relevance' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .threat_relevance import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evidence_assembly.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .threat_relevance import *', 'import coach02.threat_relevance',
                    'from coach02 import threat_relevance',
                    "__import__('coach02.threat_relevance')"]
        for symbol in allowed_contracts:
            rejected.append('from .threat_relevance import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .threat_relevance import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evidence_assembly.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/threat_relevance.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_76_arbitrary_consumer_rejected(self):
        for module, g in self.guards():
            for symbol in g['allowed_contracts']:
                source = 'from .' + module + ' import ' + symbol
                self.assertEqual(g['violations'](source, 'coach02/threat_relevance.py'), [])
                for path in ('coach02/arbitrary_future.py', 'coach02/service.py', 'coach02/decision.py', 'run.py'):
                    self.assertTrue(g['violations'](source, path))
            self.assertTrue(g['violations']('from .' + module + ' import UnapprovedContract', 'coach02/threat_relevance.py'))

    def test_77_orchestration_rejected(self):
        for module, g in self.guards():
            sources = ['from .' + module + ' import *', 'import coach02.' + module + ' as foundation',
                       'from coach02 import ' + module,
                       "import importlib as loader; loader.import_module('coach02." + module + "')",
                       "from importlib import import_module as load; load('coach02." + module + "')"]
            for symbol in g['allowed_contracts']:
                sources.append('from .' + module + ' import ' + symbol + ' as Contract; alias = Contract; alias()')
            for operation in g['operations']:
                sources.append('from .' + module + ' import ' + operation + ' as run; alias = run; alias()')
                sources.append('runtime.' + operation + '()')
            for source in sources:
                with self.subTest(module=module, source=source):
                    self.assertTrue(g['violations'](source, 'coach02/threat_relevance.py'))

    def test_78_existing_production_hashes(self):
        root = Path(relevance.__file__).resolve().parent.parent
        for path, sha in PRODUCTION_HASHES:
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest().upper(), sha)

    def test_79_duplicate_positive_subjects(self):
        p, m = pair()
        with self.assertRaisesRegex(ValueError, 'duplicate_positive_subject'):
            build_threat_relevance(replace(p, observations=p.observations * 2), m, ())

    def test_80_duplicate_missing_subjects(self):
        p, m = pair()
        with self.assertRaisesRegex(ValueError, 'duplicate_resolution_subject'):
            build_threat_relevance(p, replace(m, resolutions=m.resolutions * 2), ())

    def test_81_immutable_input_collections(self):
        p, m = pair()
        for positive, missing in ((replace(p, observations=list(p.observations)), m),
                                  (p, replace(m, resolutions=list(m.resolutions)))):
            with self.assertRaises(TypeError): build_threat_relevance(positive, missing, ())

    def test_82_exact_snapshot_types(self):
        p, m = pair()
        class Subtype(ThreatObservationSnapshot): pass
        with self.assertRaises(TypeError): build_threat_relevance(Subtype(**p.__dict__), m, ())

    def test_83_meaningful_positive_lineage(self):
        p, m = pair()
        for field in ('timeline_id', 'selected_clock_id', 'event_id', 'projection_id', 'tracker_state_id', 'temporal_snapshot_id'):
            for value in ('', ' ', 5):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_threat_relevance(replace(p, **{field: value}), m, ())

    def test_84_meaningful_missing_lineage(self):
        p, m = pair()
        for field in ('timeline_id', 'selected_clock_id', 'positive_snapshot_id', 'absence_snapshot_id', 'completeness_snapshot_id'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_threat_relevance(p, replace(m, **{field: ' '}), ())

    def test_85_bool_tick_rejected(self):
        p, m = pair()
        for positive, missing in ((replace(p, selected_tick=True), m), (replace(p, evaluated_at_tick=True), m),
                                  (p, replace(m, resolved_at_tick=True))):
            with self.assertRaises(TypeError): build_threat_relevance(positive, missing, ())

    def test_86_positive_enum_validation(self):
        p, m = pair()
        for changes in ({'proximity': 'NEARBY'}, {'temporal_status': 'FRESH'}, {'temporal_status': TemporalStatus.NEVER_SEEN}):
            bad = replace(p.observations[0], **changes)
            with self.assertRaises(TypeError): build_threat_relevance(replace(p, observations=(bad,)), m, ())

    def test_87_missing_enum_validation(self):
        p, m = pair()
        for changes in ({'status': 'MISSING'}, {'reason': 'JUSTIFIED_MISSING'}):
            bad = forged(m.resolutions[0], **changes)
            with self.assertRaises(TypeError): build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_88_resolution_lineage_validation(self):
        p, m = pair()
        for field in ('positive_snapshot_id', 'absence_snapshot_id', 'completeness_snapshot_id'):
            bad = replace(m.resolutions[0], **{field: 'other-snapshot'})
            with self.assertRaisesRegex(ValueError, 'resolution_snapshot_lineage_mismatch'):
                build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_89_positive_binding_not_just_id(self):
        p, m = pair()
        bad = replace(m.resolutions[0], positive=replace(p.observations[0], source_id='different'))
        with self.assertRaisesRegex(ValueError, 'resolution_positive_binding_mismatch'):
            build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_90_absence_subject_not_borrowed(self):
        p, m = pair()
        bad = replace(m.resolutions[0], absence=replace(m.resolutions[0].absence, threat_id='B'))
        with self.assertRaisesRegex(ValueError, 'nested_absence_subject_mismatch'):
            build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_91_completeness_subject_not_borrowed(self):
        p, m = pair()
        bad = replace(m.resolutions[0], assessment=replace(m.resolutions[0].assessment, threat_id='B'))
        with self.assertRaisesRegex(ValueError, 'nested_completeness_subject_mismatch'):
            build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_92_nested_enum_validation(self):
        p, m = pair()
        resolution = m.resolutions[0]
        bad_rows = (replace(resolution, absence=replace(resolution.absence, visibility='NOT_VISIBLE')),
                    replace(resolution, assessment=replace(resolution.assessment, completeness='SUFFICIENT')),
                    replace(resolution, assessment=replace(resolution.assessment, absence_temporal_status='FRESH')))
        for bad in bad_rows:
            with self.assertRaises(TypeError): build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_93_no_input_mutation(self):
        p, m = pair()
        claims = (claim(),)
        before = copy.deepcopy((p, m, claims))
        build_threat_relevance(p, m, claims)
        self.assertEqual((p, m, claims), before)

    def test_94_empty_universe(self):
        p, m = pair(positives=(), absences=(), assessments=())
        self.assertEqual(build_threat_relevance(p, m, ()).assessments, ())
        with self.assertRaises(ValueError): build_threat_relevance(p, m, (claim(),))

    def test_95_identifiers_no_trim(self):
        a = build((claim(subject=' A ', context=' C ', policy=' P '),), positives=(' A ',), absences=(), assessments=()).assessments[0]
        self.assertEqual((a.threat_id, a.relevance_context_id, a.assessment_policy_id), (' A ', ' C ', ' P '))
        with self.assertRaises(ValueError): build((claim(' A '),))

    def test_96_exact_identifier_type(self):
        class String(str): pass
        for kwargs in ({'subject': String('A')}, {'context': String('C')}, {'policy': String('P')}):
            with self.assertRaises(ValueError): claim(**kwargs)

    def test_97_no_missing_rerun(self):
        self.assertFalse(self.calls() & {'resolve_missing_threats', '_reason', 'build_threat_observations',
                                        'build_visibility_completeness', 'evaluate_freshness'})
        for kwargs in ({'assessments': ()}, {'positive_tick': 110}, {'positive_tick': 120}, {'absence_now': 130}):
            p, m = pair(**kwargs)
            a = build_threat_relevance(p, m, (claim(),)).assessments[0]
            self.assertIs(a.missing_resolution, m.resolutions[0])

    def test_98_all_nested_provenance_preserved(self):
        p, m = pair()
        a = build_threat_relevance(p, m, (claim(),)).assessments[0]
        self.assertEqual(asdict(a.positive_observation), asdict(p.observations[0]))
        self.assertEqual(asdict(a.missing_resolution), asdict(m.resolutions[0]))
        self.assertIs(a.missing_resolution.assessment, m.resolutions[0].assessment)
        self.assertIs(a.missing_resolution.absence, m.resolutions[0].absence)

    def test_99_unclaimed_invalid_evidence_rejected(self):
        p, m = pair(positives=('A', 'B'), absences=(), assessments=())
        bad = replace(p.observations[1], ref=' ')
        with self.assertRaises(ValueError): build_threat_relevance(replace(p, observations=(p.observations[0], bad)), m, (claim('A'),))

    def test_100_collection_elements_concrete(self):
        p, m = pair()
        for positive, missing in ((replace(p, observations=({},)), m), (p, replace(m, resolutions=({},)))):
            with self.assertRaises(TypeError): build_threat_relevance(positive, missing, ())

    def test_101_nested_types_concrete(self):
        p, m = pair()
        for field in ('positive', 'absence', 'assessment'):
            bad = forged(m.resolutions[0], **{field: {}})
            with self.assertRaises(TypeError): build_threat_relevance(p, replace(m, resolutions=(bad,)), ())

    def test_102_integer_metadata_and_nonnegative_ages(self):
        p, m = pair()
        for field in ('observed_tick', 'last_observed_tick', 'age_ticks', 'max_age_ticks'):
            bad = replace(p.observations[0], **{field: True})
            with self.assertRaises(TypeError): build_threat_relevance(replace(p, observations=(bad,)), m, ())
        for field in ('age_ticks', 'max_age_ticks'):
            bad = replace(p.observations[0], **{field: -1})
            with self.assertRaises(ValueError): build_threat_relevance(replace(p, observations=(bad,)), m, ())

    def test_103_context_per_subject_no_merging(self):
        result = build((claim('A', context='one'), claim('B', context='two')),
                       positives=('A', 'B'), absences=(), assessments=())
        self.assertEqual([a.relevance_context_id for a in result.assessments], ['one', 'two'])

    def test_104_claim_values_defensively_checked(self):
        for bad in (forged(claim(), relevance='RELEVANT'), forged(claim(), relevance_context_id=' ')):
            with self.assertRaises((TypeError, ValueError)): build((bad,))


# Frozen production hashes inserted from the canonical pre-flight manifest before gates.
PRODUCTION_HASHES = (('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'))
