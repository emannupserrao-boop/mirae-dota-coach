"""Synthetic cross-domain fixtures; upstream orchestration is test-only."""
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

from coach02 import risk_evidence_assembly as assembly
from coach02.risk_evidence_assembly import (
    EvidenceUseStatus as Use, RiskEvidenceBinding, ThreatRiskEvidence,
    OptionRiskEvidenceBundle, RiskEvidenceSnapshot, build_risk_evidence,
)
from coach02.threat_state_assembly import build_threat_state, AssembledThreatState as State
from coach02.threat_relevance import build_threat_relevance, ThreatRelevanceClaim, ThreatRelevance as Rel
from coach02.strategic_coverage import (
    build_strategic_coverage, StrategicCoverageClaim, StrategicCoverageState as Coverage,
)
from coach02.option_exposure import build_option_exposure, OptionExposureClaim, OptionExposureState as Exposure
from coach02.temporal_evidence import TemporalStatus
from coach02.threat_observation import ThreatProximity
from coach02.visibility_completeness import VisibilityCompleteness as Completeness
from test_missing_threat_resolver import prepare, resolve, event_bundle


def fixtures(threat_tick=110, state_kind='MISSING', subjects=('A',),
             relevance=Rel.RELEVANT, relevance_context='REL-7', relevance_subjects=None,
             coverage_now=None, coverage_tick=None, coverage_rows=None,
             exposure_now=None, exposure_tick=None, exposure_rows=None):
    visible = state_kind in ('VISIBLE_NEARBY', 'VISIBLE_AWAY')
    positives = () if state_kind == 'UNKNOWN' else subjects
    absences = () if visible else subjects
    upstream = prepare(
        positive_tick=threat_tick-10 if state_kind == 'MISSING' else threat_tick,
        absence_tick=threat_tick, positive_now=threat_tick, absence_now=threat_tick,
        positives=positives, absences=absences,
        assessments=tuple((s, Completeness.SUFFICIENT) for s in absences),
        proximity=ThreatProximity.NEARBY if state_kind == 'VISIBLE_NEARBY' else ThreatProximity.AWAY)
    positive, missing = upstream['positive'], resolve(upstream)
    states = build_threat_state(positive, missing)
    selected = subjects if relevance_subjects is None else relevance_subjects
    relevances = build_threat_relevance(positive, missing, tuple(
        ThreatRelevanceClaim(s, relevance, relevance_context, 'relevance-v1') for s in selected))
    coverage_now = threat_tick if coverage_now is None else coverage_now
    coverage_tick = coverage_now if coverage_tick is None else coverage_tick
    exposure_now = threat_tick if exposure_now is None else exposure_now
    exposure_tick = exposure_now if exposure_tick is None else exposure_tick
    coverage_rows = (('COV-22', Coverage.SUFFICIENT),) if coverage_rows is None else coverage_rows
    exposure_rows = (('option-A', 'EXP-A', Exposure.EXPOSED),) if exposure_rows is None else exposure_rows
    ce, cp, ct = event_bundle(tuple('r'+str(i) for i in range(len(coverage_rows))),
                             coverage_tick, coverage_now, 10, 'cov')
    coverages = build_strategic_coverage(ce, cp, ct, tuple(
        StrategicCoverageClaim(context, 'cov.r'+str(i), value, 'cov-ttl', 'coverage-v1')
        for i, (context, value) in enumerate(coverage_rows)))
    ee, ep, et = event_bundle(tuple('r'+str(i) for i in range(len(exposure_rows))),
                             exposure_tick, exposure_now, 10, 'exp')
    exposures = build_option_exposure(ee, ep, et, tuple(
        OptionExposureClaim(option, context, 'exp.r'+str(i), value, 'exp-ttl', 'exposure-v1')
        for i, (option, context, value) in enumerate(exposure_rows)))
    return states, relevances, coverages, exposures


def binding(**changes):
    return replace(RiskEvidenceBinding('R', 'option-A', 'REL-7', 'COV-22', 'EXP-A', 'binding-v1'), **changes)


def build(inputs=None, bindings=None):
    return build_risk_evidence(*(fixtures() if inputs is None else inputs),
                               (binding(),) if bindings is None else bindings)


def bundle(inputs=None, bindings=None):
    return build(inputs, bindings).bundles[0]


def threat(inputs=None, bindings=None):
    return bundle(inputs, bindings).threats[0]


def changed(inputs, index, **changes):
    result = list(inputs)
    result[index] = replace(result[index], **changes)
    return tuple(result)


class RiskEvidenceAssemblyTests(unittest.TestCase):
    def blank_binding(self, name):
        class StringSubclass(str): pass
        for value in ('', ' \t\n', None, 1, True, StringSubclass('valid')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                binding(**{name: value})
        opaque = '  opaque/\u03b1  '
        self.assertEqual(getattr(binding(**{name: opaque}), name), opaque)

    def exact_snapshot(self, index):
        inputs = fixtures()
        class Derived(type(inputs[index])): pass
        for value in (None, {}, Derived(**asdict(inputs[index]))):
            invalid = list(inputs); invalid[index] = value
            with self.subTest(value=type(value)), self.assertRaises(TypeError): build(tuple(invalid))

    def invalid_structure(self, index, member):
        inputs = fixtures(); snapshot = inputs[index]
        for value in ([], [getattr(snapshot, member)[0]], (None,)):
            with self.subTest(index=index, value=value), self.assertRaises(TypeError):
                build(changed(inputs, index, **{member: value}))

    def imports(self):
        tree = ast.parse(inspect.getsource(assembly))
        return {'.'*n.level+(n.module or '') for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}

    def output_fields(self):
        return {f.name for cls in (ThreatRiskEvidence, OptionRiskEvidenceBundle, RiskEvidenceSnapshot)
                for f in fields(cls)}

    def test_001_use_status(self):
        self.assertEqual({s.name: s.value for s in Use},
                         {'CURRENT': 'CURRENT', 'HISTORICAL': 'HISTORICAL', 'ABSENT': 'ABSENT'})

    def test_002_no_safety_values(self):
        enums = [v for v in vars(assembly).values() if isinstance(v, type) and issubclass(v, Enum)
                 and v.__module__ == assembly.__name__]
        self.assertEqual(enums, [Use])
        self.assertTrue({'SAFE', 'UNSAFE', 'LOW', 'HIGH'}.isdisjoint(Use.__members__))

    def test_003_immutable_contracts(self):
        result = build()
        for obj in (binding(), result, result.bundles[0], result.bundles[0].threats[0]):
            with self.assertRaises(FrozenInstanceError): setattr(obj, fields(obj)[0].name, 'replacement')
        self.assertIsInstance(result.bundles, tuple)
        self.assertIsInstance(result.bundles[0].threats, tuple)

    def test_004_blank_risk_context(self): self.blank_binding('risk_context_id')
    def test_005_blank_option(self): self.blank_binding('option_id')
    def test_006_blank_relevance_context(self): self.blank_binding('relevance_context_id')
    def test_007_blank_coverage_context(self): self.blank_binding('coverage_context_id')
    def test_008_blank_exposure_context(self): self.blank_binding('exposure_context_id')
    def test_009_blank_binding_policy(self): self.blank_binding('binding_policy_id')

    def test_010_binding_tuple(self):
        inputs = fixtures()
        for value in ([], [binding()], None, (None,), ({},)):
            with self.subTest(value=value), self.assertRaises(TypeError): build_risk_evidence(*inputs, value)

    def test_011_duplicate_pair(self):
        for second in (binding(), binding(coverage_context_id='different')):
            with self.assertRaises(ValueError): build(bindings=(binding(), second))

    def test_012_option_in_distinct_risk_contexts(self):
        result = build(bindings=(binding(), binding(risk_context_id='R2')))
        self.assertEqual([(b.risk_context_id, b.option_id) for b in result.bundles],
                         [('R', 'option-A'), ('R2', 'option-A')])

    def test_013_distinct_options_in_same_risk_context(self):
        result = build(bindings=(binding(), binding(option_id='option-B')))
        self.assertEqual([b.option_id for b in result.bundles], ['option-A', 'option-B'])
        self.assertIs(result.bundles[1].exposure_use, Use.ABSENT)

    def test_014_empty_bindings(self):
        inputs = fixtures()
        result = build(inputs, ())
        self.assertEqual(result.bundles, ())
        self.assertEqual(result.threat_state_snapshot_id, inputs[0].snapshot_id)
        with self.assertRaises(ValueError): build(changed(inputs, 2, timeline_id='foreign'), ())

    def test_015_exact_state_snapshot(self):
        self.exact_snapshot(0); self.invalid_structure(0, 'assessments')

    def test_016_exact_relevance_snapshot(self):
        self.exact_snapshot(1); self.invalid_structure(1, 'assessments')

    def test_017_exact_coverage_snapshot(self):
        self.exact_snapshot(2); self.invalid_structure(2, 'observations')

    def test_018_exact_exposure_snapshot(self):
        self.exact_snapshot(3); self.invalid_structure(3, 'observations')

    def test_019_timeline_binding(self):
        inputs = fixtures()
        for i in range(4):
            for value in ('foreign', '', '  ', True):
                with self.subTest(i=i, value=value), self.assertRaises(ValueError):
                    build(changed(inputs, i, timeline_id=value))

    def test_020_clock_binding(self):
        inputs = fixtures()
        for i in range(4):
            for value in ('foreign', '', '  ', True):
                with self.subTest(i=i, value=value), self.assertRaises(ValueError):
                    build(changed(inputs, i, selected_clock_id=value))

    def test_021_positive_lineage(self):
        for i in (0, 1):
            for value in ('different', ''):
                with self.assertRaises(ValueError): build(changed(fixtures(), i, positive_snapshot_id=value))

    def test_022_missing_lineage(self):
        for i in (0, 1):
            for value in ('different', ''):
                with self.assertRaises(ValueError): build(changed(fixtures(), i, missing_snapshot_id=value))

    def test_023_threat_tick_alignment(self):
        with self.assertRaises(ValueError): build(changed(fixtures(), 1, evaluated_at_tick=111))

    def test_024_foreign_relevance_subject(self):
        inputs = fixtures(subjects=('A', 'B'))
        with self.assertRaises(ValueError): build(changed(inputs, 0, assessments=(inputs[0].assessments[0],)))

    def test_025_relevance_subset(self):
        b = bundle(fixtures(subjects=('A', 'B'), relevance_subjects=('A',)))
        self.assertEqual([t.threat_id for t in b.threats], ['A', 'B'])
        self.assertIs(b.threats[0].relevance_use, Use.CURRENT)
        self.assertIsNone(b.threats[1].relevance_assessment)
        self.assertIs(b.threats[1].relevance_use, Use.ABSENT)

    def test_026_nested_evidence_correspondence(self):
        inputs = fixtures(); row = inputs[1].assessments[0]
        positive = replace(row.positive_observation, source_id='different-source')
        missing = replace(row.missing_resolution, positive=positive)
        for changes in ({'positive_observation': positive}, {'missing_resolution': None},
                        {'positive_observation': positive, 'missing_resolution': missing}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build(changed(inputs, 1, assessments=(replace(row, **changes),)))
        for changes in ({'relevance': 'RELEVANT'}, {'relevance_context_id': ''}, {'assessment_policy_id': ''}):
            with self.assertRaises((TypeError, ValueError)):
                build(changed(inputs, 1, assessments=(replace(row, **changes),)))

    def test_027_duplicate_state(self):
        inputs = fixtures()
        with self.assertRaises(ValueError): build(changed(inputs, 0, assessments=inputs[0].assessments*2))

    def test_028_duplicate_relevance(self):
        inputs = fixtures()
        with self.assertRaises(ValueError): build(changed(inputs, 1, assessments=inputs[1].assessments*2))

    def context_structure(self, index, semantic):
        inputs = fixtures(); row = inputs[index].observations[0]
        with self.assertRaises(ValueError): build(changed(inputs, index, observations=(row, row)))
        identifiers = ('ref', 'source_id', 'temporal_policy_id', 'assessment_policy_id')
        identifiers += ('coverage_context_id',) if index == 2 else ('option_id', 'exposure_context_id')
        for field in identifiers:
            with self.subTest(field=field), self.assertRaises(ValueError):
                build(changed(inputs, index, observations=(replace(row, **{field: ' '}),)))
        for changes in ({semantic: getattr(row, semantic).value}, {'temporal_status': 'FRESH'},
                        {'temporal_status': None}, {'age_ticks': -1}, {'max_age_ticks': -1},
                        {'last_observed_tick': row.last_observed_tick-1}):
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                build(changed(inputs, index, observations=(replace(row, **changes),)))
        for field in ('event_id', 'projection_id', 'tracker_state_id', 'temporal_snapshot_id'):
            with self.assertRaises(ValueError): build(changed(inputs, index, **{field: ''}))

    def test_029_duplicate_coverage_and_structure(self): self.context_structure(2, 'coverage')
    def test_030_duplicate_exposure_and_structure(self): self.context_structure(3, 'exposure')

    def test_031_maximum_tick(self):
        for kwargs, expected in (({}, 110), ({'coverage_now': 120}, 120), ({'exposure_now': 130}, 130),
                                 ({'threat_tick': 140, 'coverage_now': 130, 'exposure_now': 120}, 140)):
            with self.subTest(kwargs=kwargs):
                result = build(fixtures(**kwargs))
                self.assertEqual(result.risk_assembly_tick, expected)
                self.assertTrue(all(b.risk_assembly_tick == expected for b in result.bundles))

    def test_032_negative_ticks(self):
        result = build(fixtures(threat_tick=-20, coverage_now=-15, exposure_now=-10))
        self.assertEqual(result.risk_assembly_tick, -10)
        self.assertIs(result.bundles[0].threats[0].state_use, Use.HISTORICAL)

    def test_033_concrete_integer_ticks(self):
        inputs = fixtures()
        for i in range(4):
            tick_fields = ('assembly_tick',) if i == 0 else ('evaluated_at_tick',)
            if i >= 2: tick_fields += ('selected_tick',)
            for field in tick_fields:
                for value in (True, 110.0):
                    with self.subTest(i=i, field=field), self.assertRaises(TypeError):
                        build(changed(inputs, i, **{field: value}))
        for i in (2, 3):
            row = inputs[i].observations[0]
            for field in ('observed_tick', 'last_observed_tick', 'age_ticks', 'max_age_ticks'):
                with self.assertRaises(TypeError):
                    build(changed(inputs, i, observations=(replace(row, **{field: True}),)))

    def test_034_current_state(self): self.assertIs(threat().state_use, Use.CURRENT)
    def test_035_historical_state(self):
        self.assertIs(threat(fixtures(exposure_now=120)).state_use, Use.HISTORICAL)

    def test_036_historical_missing(self):
        t = threat(fixtures(threat_tick=100, exposure_now=110))
        self.assertIs(t.state_use, Use.HISTORICAL)
        self.assertIs(t.state_assessment.state, State.MISSING)
        self.assertEqual(t.state_assessment.assembly_tick, 100)

    def test_037_historical_conflict(self):
        t = threat(fixtures(state_kind='CONFLICTED', exposure_now=120))
        self.assertIs(t.state_use, Use.HISTORICAL)
        self.assertIs(t.state_assessment.state, State.CONFLICTED)

    def test_038_exact_relevance_context(self):
        inputs = fixtures()
        self.assertIs(threat(inputs).relevance_assessment, inputs[1].assessments[0])

    def test_039_wrong_relevance_context(self):
        t = threat(bindings=(binding(relevance_context_id='elsewhere'),))
        self.assertIsNone(t.relevance_assessment); self.assertIs(t.relevance_use, Use.ABSENT)

    def test_040_missing_relevance(self):
        t = threat(fixtures(relevance_subjects=()))
        self.assertIsNone(t.relevance_assessment); self.assertIs(t.relevance_use, Use.ABSENT)

    def test_041_unknown_relevance_exists(self):
        t = threat(fixtures(relevance=Rel.UNKNOWN, exposure_now=120))
        self.assertIs(t.relevance_assessment.relevance, Rel.UNKNOWN)
        self.assertIs(t.relevance_use, Use.HISTORICAL)

    def test_042_current_relevance(self): self.assertIs(threat().relevance_use, Use.CURRENT)
    def test_043_historical_relevance(self):
        self.assertIs(threat(fixtures(exposure_now=120)).relevance_use, Use.HISTORICAL)

    def test_044_historical_relevance_semantics(self):
        for value in Rel:
            t = threat(fixtures(relevance=value, coverage_now=120))
            self.assertIs(t.relevance_assessment.relevance, value)
            self.assertIs(t.relevance_use, Use.HISTORICAL)

    def test_045_exact_coverage_context(self):
        inputs = fixtures(coverage_rows=(('other', Coverage.UNKNOWN), ('COV-22', Coverage.SUFFICIENT)))
        self.assertIs(bundle(inputs).coverage_observation,
                      next(o for o in inputs[2].observations if o.coverage_context_id == 'COV-22'))

    def test_046_missing_coverage(self):
        b = bundle(fixtures(coverage_rows=()))
        self.assertIsNone(b.coverage_observation); self.assertIs(b.coverage_use, Use.ABSENT)

    def test_047_unknown_coverage_exists(self):
        b = bundle(fixtures(coverage_rows=(('COV-22', Coverage.UNKNOWN),)))
        self.assertIs(b.coverage_observation.coverage, Coverage.UNKNOWN)
        self.assertIs(b.coverage_use, Use.CURRENT)

    def test_048_current_coverage(self): self.assertIs(bundle().coverage_use, Use.CURRENT)
    def test_049_old_fresh_coverage(self):
        b = bundle(fixtures(coverage_now=100))
        self.assertIs(b.coverage_observation.temporal_status, TemporalStatus.FRESH)
        self.assertIs(b.coverage_use, Use.HISTORICAL)

    def test_050_stale_aligned_coverage(self):
        b = bundle(fixtures(coverage_tick=99))
        self.assertIs(b.coverage_observation.temporal_status, TemporalStatus.STALE)
        self.assertIs(b.coverage_use, Use.HISTORICAL)

    def historical_coverage(self, value):
        for kwargs in ({'coverage_now': 100}, {'coverage_tick': 99}):
            b = bundle(fixtures(coverage_rows=(('COV-22', value),), **kwargs))
            self.assertIs(b.coverage_use, Use.HISTORICAL)
            self.assertIs(b.coverage_observation.coverage, value)

    def test_051_historical_sufficient(self): self.historical_coverage(Coverage.SUFFICIENT)
    def test_052_historical_insufficient(self): self.historical_coverage(Coverage.INSUFFICIENT)
    def test_053_historical_unknown_coverage(self): self.historical_coverage(Coverage.UNKNOWN)

    def test_054_exact_exposure_pair(self):
        inputs = fixtures(exposure_rows=(('option-A', 'elsewhere', Exposure.UNKNOWN),
                          ('option-B', 'EXP-A', Exposure.NOT_EXPOSED), ('option-A', 'EXP-A', Exposure.EXPOSED)))
        self.assertIs(bundle(inputs).exposure_observation,
                      next(o for o in inputs[3].observations if (o.option_id, o.exposure_context_id) == ('option-A', 'EXP-A')))

    def test_055_missing_exposure(self):
        b = bundle(fixtures(exposure_rows=()))
        self.assertIsNone(b.exposure_observation); self.assertIs(b.exposure_use, Use.ABSENT)

    def test_056_unknown_exposure_exists(self):
        b = bundle(fixtures(exposure_rows=(('option-A', 'EXP-A', Exposure.UNKNOWN),), exposure_now=100))
        self.assertIs(b.exposure_observation.exposure, Exposure.UNKNOWN)
        self.assertIs(b.exposure_use, Use.HISTORICAL)

    def current_exposure(self, value):
        b = bundle(fixtures(exposure_rows=(('option-A', 'EXP-A', value),)))
        self.assertIs(b.exposure_use, Use.CURRENT)
        self.assertIs(b.exposure_observation.exposure, value)

    def test_057_current_exposed(self): self.current_exposure(Exposure.EXPOSED)
    def test_058_current_not_exposed(self): self.current_exposure(Exposure.NOT_EXPOSED)
    def test_059_current_unknown_exposure(self): self.current_exposure(Exposure.UNKNOWN)

    def test_060_old_fresh_exposure(self):
        b = bundle(fixtures(exposure_now=100))
        self.assertIs(b.exposure_observation.temporal_status, TemporalStatus.FRESH)
        self.assertIs(b.exposure_use, Use.HISTORICAL)

    def test_061_stale_aligned_exposure(self):
        b = bundle(fixtures(exposure_tick=99))
        self.assertIs(b.exposure_observation.temporal_status, TemporalStatus.STALE)
        self.assertIs(b.exposure_use, Use.HISTORICAL)

    def historical_exposure(self, value):
        for kwargs in ({'exposure_now': 100}, {'exposure_tick': 99}):
            b = bundle(fixtures(exposure_rows=(('option-A', 'EXP-A', value),), **kwargs))
            self.assertIs(b.exposure_use, Use.HISTORICAL)
            self.assertIs(b.exposure_observation.exposure, value)

    def test_062_historical_exposed(self): self.historical_exposure(Exposure.EXPOSED)
    def test_063_historical_not_exposed(self): self.historical_exposure(Exposure.NOT_EXPOSED)

    def test_064_absent_coverage_not_unknown(self):
        inputs = fixtures(coverage_rows=(('COV-22', Coverage.UNKNOWN),))
        present, absent = bundle(inputs), bundle(inputs, (binding(coverage_context_id='missing'),))
        self.assertIsNotNone(present.coverage_observation); self.assertIsNone(absent.coverage_observation)
        self.assertIs(present.coverage_use, Use.CURRENT); self.assertIs(absent.coverage_use, Use.ABSENT)

    def test_065_absent_exposure_not_unknown(self):
        inputs = fixtures(exposure_rows=(('option-A', 'EXP-A', Exposure.UNKNOWN),))
        present, absent = bundle(inputs), bundle(inputs, (binding(exposure_context_id='missing'),))
        self.assertIsNotNone(present.exposure_observation); self.assertIsNone(absent.exposure_observation)
        self.assertIs(present.exposure_use, Use.CURRENT); self.assertIs(absent.exposure_use, Use.ABSENT)

    def test_066_absent_relevance_not_unknown(self):
        inputs = fixtures(relevance=Rel.UNKNOWN)
        present, absent = threat(inputs), threat(inputs, (binding(relevance_context_id='missing'),))
        self.assertIsNotNone(present.relevance_assessment); self.assertIsNone(absent.relevance_assessment)
        self.assertIs(present.relevance_use, Use.CURRENT); self.assertIs(absent.relevance_use, Use.ABSENT)

    def test_067_all_threats_in_every_bundle(self):
        inputs = fixtures(subjects=('C', 'A', 'B'), relevance_subjects=('A',), exposure_now=120)
        for b in build(inputs, (binding(), binding(option_id='option-B'))).bundles:
            self.assertEqual([t.threat_id for t in b.threats], ['A', 'B', 'C'])
            self.assertTrue(all(t.state_use is Use.HISTORICAL for t in b.threats))

    def test_068_not_relevant_preserved(self):
        t = threat(fixtures(relevance=Rel.NOT_RELEVANT))
        self.assertIs(t.state_assessment.state, State.MISSING)
        self.assertIs(t.relevance_assessment.relevance, Rel.NOT_RELEVANT)

    def test_069_unknown_relevance_and_state_preserved(self):
        t = threat(fixtures(state_kind='UNKNOWN', relevance=Rel.UNKNOWN))
        self.assertEqual(t.threat_id, 'A')
        self.assertIs(t.state_assessment.state, State.UNKNOWN)
        self.assertIs(t.relevance_assessment.relevance, Rel.UNKNOWN)
        self.assertIs(t.state_use, Use.CURRENT)

    def test_070_absent_relevance_threat_preserved(self):
        b = bundle(fixtures(relevance_subjects=(), coverage_rows=(), exposure_rows=()))
        self.assertEqual(len(b.threats), 1)
        self.assertIs(b.threats[0].state_assessment.state, State.MISSING)
        self.assertIs(b.threats[0].relevance_use, Use.ABSENT)
        self.assertIs(b.coverage_use, Use.ABSENT); self.assertIs(b.exposure_use, Use.ABSENT)

    def test_071_conflicted_preserved(self):
        t = threat(fixtures(state_kind='CONFLICTED'))
        self.assertIs(t.state_assessment.state, State.CONFLICTED)
        self.assertIs(t.state_use, Use.CURRENT)

    def test_072_equal_strings_do_not_autobind(self):
        inputs = fixtures(relevance_context='same', coverage_rows=(('same', Coverage.SUFFICIENT),),
                          exposure_rows=(('same', 'same', Exposure.EXPOSED),))
        self.assertEqual(build(inputs, ()).bundles, ())
        b = bundle(inputs, (binding(risk_context_id='same', option_id='same'),))
        self.assertIs(b.coverage_use, Use.ABSENT); self.assertIs(b.exposure_use, Use.ABSENT)
        self.assertIs(b.threats[0].relevance_use, Use.ABSENT)

    def test_073_different_opaque_contexts(self):
        b = bundle()
        self.assertEqual((b.risk_context_id, b.relevance_context_id, b.coverage_context_id, b.exposure_context_id),
                         ('R', 'REL-7', 'COV-22', 'EXP-A'))
        self.assertTrue(all(u is Use.CURRENT for u in
            (b.coverage_use, b.exposure_use, b.threats[0].state_use, b.threats[0].relevance_use)))

    def test_074_no_binding_no_bundle(self):
        inputs = fixtures(subjects=('A', 'B'), exposure_rows=(('option-A', 'EXP-A', Exposure.EXPOSED),
                                                          ('option-B', 'EXP-B', Exposure.UNKNOWN)))
        self.assertEqual(build(inputs, ()).bundles, ())
        self.assertEqual(len(inputs[0].assessments), 2)

    def test_075_no_option_discovery(self):
        inputs = fixtures(exposure_rows=(('option-A', 'EXP-A', Exposure.EXPOSED),
                                        ('option-B', 'EXP-A', Exposure.EXPOSED)))
        self.assertEqual([b.option_id for b in build(inputs).bundles], ['option-A'])

    def test_076_independent_bindings(self):
        inputs = fixtures(coverage_rows=(('COV-22', Coverage.SUFFICIENT), ('C2', Coverage.INSUFFICIENT)),
                          exposure_rows=(('option-A', 'EXP-A', Exposure.EXPOSED),
                                         ('option-A', 'E2', Exposure.NOT_EXPOSED)))
        result = build(inputs, (binding(), binding(risk_context_id='R2', coverage_context_id='C2',
                                                  exposure_context_id='E2', relevance_context_id='REL-2')))
        a, b = result.bundles
        self.assertIs(a.coverage_observation.coverage, Coverage.SUFFICIENT)
        self.assertIs(b.coverage_observation.coverage, Coverage.INSUFFICIENT)
        self.assertIs(a.exposure_observation.exposure, Exposure.EXPOSED)
        self.assertIs(b.exposure_observation.exposure, Exposure.NOT_EXPOSED)
        self.assertIs(a.threats[0].relevance_use, Use.CURRENT)
        self.assertIs(b.threats[0].relevance_use, Use.ABSENT)

    def test_077_no_cross_option_borrowing(self):
        b = bundle(bindings=(binding(option_id='option-B'),))
        self.assertIsNone(b.exposure_observation); self.assertIs(b.exposure_use, Use.ABSENT)

    def test_078_no_cross_coverage_context_borrowing(self):
        for context in ('COV-2', ' COV-22', 'COV-22/sub', 'cov-22'):
            b = bundle(bindings=(binding(coverage_context_id=context),))
            self.assertIsNone(b.coverage_observation); self.assertIs(b.coverage_use, Use.ABSENT)

    def test_079_no_cross_relevance_context_borrowing(self):
        for context in ('REL', ' REL-7', 'REL-7/sub', 'rel-7'):
            t = threat(bindings=(binding(relevance_context_id=context),))
            self.assertIsNone(t.relevance_assessment); self.assertIs(t.relevance_use, Use.ABSENT)

    def test_080_complete_provenance(self):
        inputs = fixtures(); result = build(inputs); b = result.bundles[0]; t = b.threats[0]
        self.assertEqual((result.threat_state_snapshot_id, result.threat_relevance_snapshot_id,
                          result.strategic_coverage_snapshot_id, result.option_exposure_snapshot_id),
                         tuple(s.snapshot_id for s in inputs))
        self.assertEqual((result.timeline_id, result.selected_clock_id), ('timeline', 'clock'))
        self.assertIs(t.state_assessment, inputs[0].assessments[0])
        self.assertIs(t.relevance_assessment, inputs[1].assessments[0])
        self.assertIs(b.coverage_observation, inputs[2].observations[0])
        self.assertIs(b.exposure_observation, inputs[3].observations[0])

    def test_081_no_mutation_or_refresh(self):
        inputs = fixtures(coverage_now=100, exposure_tick=99)
        before = tuple((asdict(s), s.snapshot_id) for s in inputs)
        result = build(inputs)
        self.assertEqual(before, tuple((asdict(s), s.snapshot_id) for s in inputs))
        self.assertIs(result.bundles[0].coverage_observation.temporal_status, TemporalStatus.FRESH)
        self.assertIs(result.bundles[0].exposure_observation.temporal_status, TemporalStatus.STALE)
        # Accepted status is consumed, not recalculated from the age/threshold.
        inputs = fixtures(); row = inputs[2].observations[0]
        modified = changed(inputs, 2, observations=(replace(row, temporal_status=TemporalStatus.STALE),))
        self.assertIs(bundle(modified).coverage_use, Use.HISTORICAL)

    def test_082_deterministic_identity(self):
        result = build(bindings=(binding(risk_context_id=' contexto/\u03b1 '),))
        content = json.dumps(asdict(result), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        self.assertEqual(result.snapshot_id, 'risk.evidence_assembly.v1:snapshot:'+hashlib.sha256(content).hexdigest())
        self.assertEqual(result, build(bindings=(binding(risk_context_id=' contexto/\u03b1 '),)))

    def test_083_binding_order_independent(self):
        inputs = fixtures(); bindings = (binding(), binding(risk_context_id='R2'), binding(option_id='option-B'))
        self.assertEqual(build(inputs, bindings), build(inputs, tuple(reversed(bindings))))
        self.assertEqual(build(inputs, bindings).snapshot_id, build(inputs, tuple(reversed(bindings))).snapshot_id)

    def test_084_canonical_bundle_order(self):
        bindings = (binding(risk_context_id='Z'), binding(option_id='z'), binding(), binding(risk_context_id='A'))
        rows = build(bindings=bindings).bundles
        names = tuple(f.name for f in fields(RiskEvidenceBinding))
        self.assertEqual([tuple(getattr(b, n) for n in names) for b in rows],
                         sorted(tuple(getattr(b, n) for n in names) for b in bindings))

    def test_085_canonical_threat_order(self):
        inputs = fixtures(subjects=('Z', 'B', 'A'))
        inputs = changed(inputs, 0, assessments=tuple(reversed(inputs[0].assessments)))
        self.assertEqual([t.threat_id for t in bundle(inputs).threats], ['A', 'B', 'Z'])

    def test_086_binding_identity(self):
        inputs = fixtures(); original = build(inputs).snapshot_id
        for field in ('risk_context_id', 'option_id', 'relevance_context_id', 'coverage_context_id', 'exposure_context_id'):
            self.assertNotEqual(original, build(inputs, (binding(**{field: 'different'}),)).snapshot_id)

    def test_087_policy_identity(self):
        self.assertNotEqual(build().snapshot_id, build(bindings=(binding(binding_policy_id='binding-v2'),)).snapshot_id)

    def test_088_state_evidence_identity(self):
        self.assertNotEqual(build().snapshot_id, build(fixtures(state_kind='CONFLICTED')).snapshot_id)

    def test_089_relevance_evidence_identity(self):
        self.assertNotEqual(build().snapshot_id, build(fixtures(relevance=Rel.NOT_RELEVANT)).snapshot_id)

    def test_090_coverage_evidence_identity(self):
        self.assertNotEqual(build().snapshot_id,
                            build(fixtures(coverage_rows=(('COV-22', Coverage.INSUFFICIENT),))).snapshot_id)

    def test_091_exposure_evidence_identity(self):
        self.assertNotEqual(build().snapshot_id,
                            build(fixtures(exposure_rows=(('option-A', 'EXP-A', Exposure.NOT_EXPOSED),))).snapshot_id)

    def test_092_use_status_identity(self):
        result = build(); b = result.bundles[0]; t = b.threats[0]
        for field in ('coverage_use', 'exposure_use'):
            self.assertNotEqual(result.snapshot_id, replace(result, bundles=(replace(b, **{field: Use.HISTORICAL}),)).snapshot_id)
        for field in ('state_use', 'relevance_use'):
            other = replace(b, threats=(replace(t, **{field: Use.HISTORICAL}),))
            self.assertNotEqual(result.snapshot_id, replace(result, bundles=(other,)).snapshot_id)
        for field in ('timeline_id', 'selected_clock_id', 'threat_state_snapshot_id', 'threat_relevance_snapshot_id',
                      'strategic_coverage_snapshot_id', 'option_exposure_snapshot_id'):
            self.assertNotEqual(result.snapshot_id, replace(result, **{field: 'different'}).snapshot_id)
        self.assertNotEqual(result.snapshot_id, replace(result, risk_assembly_tick=111).snapshot_id)

    def test_093_no_risk_verdict(self):
        for kind in ('MISSING', 'VISIBLE_NEARBY', 'CONFLICTED', 'UNKNOWN'):
            b = bundle(fixtures(state_kind=kind))
            self.assertIs(b.threats[0].state_assessment.state, State(kind))
            self.assertIs(b.threats[0].relevance_assessment.relevance, Rel.RELEVANT)
            self.assertIs(b.exposure_observation.exposure, Exposure.EXPOSED)
            self.assertIs(b.coverage_observation.coverage, Coverage.SUFFICIENT)
            self.assertIs(b.threats[0].state_use, Use.CURRENT)
        self.assertTrue({'risk', 'risk_level', 'danger', 'verdict', 'classification'}.isdisjoint(self.output_fields()))

    def test_094_no_score(self):
        self.assertTrue({'score', 'risk_score', 'confidence', 'probability', 'weight', 'rank'}.isdisjoint(self.output_fields()))
        tree = ast.parse(inspect.getsource(assembly))
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and
                             n.func.id in {'sum', 'float', 'round'} for n in ast.walk(tree)))

    def test_095_no_safety_output(self):
        self.assertTrue({'safety', 'safe', 'unsafe', 'safety_state'}.isdisjoint(self.output_fields()))
        self.assertEqual({f.name for f in fields(ThreatRiskEvidence)},
                         {'threat_id', 'state_assessment', 'state_use', 'relevance_assessment', 'relevance_use'})

    def test_096_no_action_output(self):
        self.assertTrue({'action', 'recommendation', 'best_option', 'priority'}.isdisjoint(self.output_fields()))
        self.assertEqual({name for name, value in vars(assembly).items() if inspect.isfunction(value)
                          and value.__module__ == assembly.__name__ and not name.startswith('_')}, {'build_risk_evidence'})

    def test_097_no_safety_import(self): self.assertNotIn('.safety_evidence', self.imports())
    def test_098_no_option_safety_import(self): self.assertNotIn('.option_safety', self.imports())

    def test_099_only_four_semantic_domains(self):
        self.assertEqual(self.imports(), {'dataclasses', 'enum', 'hashlib', 'json', '.threat_state_assembly',
                                         '.threat_relevance', '.strategic_coverage', '.option_exposure'})

    def test_100_pure_no_orchestration(self):
        import builtins, io, os, time, socket, http.client, random, uuid, subprocess, sqlite3
        from coach02 import temporal_evidence, observation_event, threat_observation, threat_absence_observation
        from coach02 import visibility_completeness, missing_threat_resolver, threat_state_assembly
        from coach02 import threat_relevance, strategic_coverage, option_exposure, safety_evidence, option_safety
        inputs = fixtures(); bindings = (binding(),); expected = build(inputs, bindings)
        targets = [(builtins, 'open'), (io, 'open'), (os, 'open'), (os, 'system'), (os, 'getenv'),
                   (time, 'time'), (time, 'monotonic'), (time, 'perf_counter'), (random, 'random'),
                   (random, 'getrandbits'), (uuid, 'uuid4'), (uuid, 'uuid1'), (subprocess, 'Popen'),
                   (sqlite3, 'connect'), (socket, 'socket'), (socket, 'getaddrinfo'),
                   (socket, 'create_connection'), (http.client.HTTPConnection, 'request'),
                   (temporal_evidence, 'new_temporal_state'), (temporal_evidence, 'record_observations'),
                   (temporal_evidence, 'evaluate_freshness'), (observation_event, 'project_event_time'),
                   (threat_observation, 'build_threat_observations'),
                   (threat_absence_observation, 'build_threat_absence_observations'),
                   (visibility_completeness, 'build_visibility_completeness'),
                   (missing_threat_resolver, 'resolve_missing_threats'), (threat_state_assembly, 'build_threat_state'),
                   (threat_relevance, 'build_threat_relevance'), (strategic_coverage, 'build_strategic_coverage'),
                   (option_exposure, 'build_option_exposure'), (safety_evidence, 'build_risk_awareness'),
                   (option_safety, 'build_option_safety')]
        class Forbidden(dict):
            def __getitem__(self, key): raise AssertionError('environment read')
            def get(self, *args): raise AssertionError('environment read')
            def __iter__(self): raise AssertionError('environment read')
        before = dict(vars(assembly))
        with ExitStack() as stack:
            for owner, name in targets:
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError('impure dependency')))
            stack.enter_context(patch.object(os, 'environ', Forbidden()))
            actual = build(inputs, bindings)
            self.assertEqual(actual.snapshot_id, expected.snapshot_id)
        self.assertEqual(before, vars(assembly))
        for name, value in vars(assembly).items():
            if not name.startswith('__'): self.assertNotIsInstance(value, (dict, list, set, bytearray))
        self.assertFalse(any(isinstance(n, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef))
                             for n in ast.walk(ast.parse(inspect.getsource(assembly)))))

    def test_101_legacy_incompatibility_review(self):
        from coach02.safety_evidence import ThreatState, RelevantThreatObservation, CoverageObservation
        from coach02.option_safety import Exposure as LegacyExposure, FarmOptionSafetyObservation
        self.assertEqual({v.value for v in ThreatState}, {'VISIBLE_NEARBY', 'VISIBLE_AWAY', 'MISSING', 'UNKNOWN'})
        with self.assertRaises(ValueError): ThreatState('CONFLICTED')
        self.assertEqual({f.name for f in fields(RelevantThreatObservation)}, {'threat_id', 'state', 'freshness'})
        self.assertEqual({f.name for f in fields(CoverageObservation)}, {'sufficient', 'freshness'})
        self.assertEqual({v.value for v in LegacyExposure}, {'LOW', 'HIGH', 'UNKNOWN'})
        self.assertEqual({f.name for f in fields(FarmOptionSafetyObservation)},
                         {'seed_id', 'option_id', 'action', 'exposure', 'exposure_freshness', 'coverage', 'coverage_freshness'})
        document = (Path(assembly.__file__).resolve().parent.parent/'RISK_EVIDENCE_ASSEMBLY_V01.md').read_text(encoding='utf-8')
        self.assertIn('NO_DIRECT_PRODUCTION_COMPATIBILITY_V01', document)
        self.assertNotIn('safety_for_test', vars(assembly))

    def guards(self):
        root = Path(assembly.__file__).resolve().parent.parent
        for filename, method, module in (
            ('test_threat_state_assembly.py', 'test_101_dependency_direction', 'threat_state_assembly'),
            ('test_threat_relevance.py', 'test_75_dependency_direction', 'threat_relevance'),
            ('test_strategic_coverage.py', 'test_88_dependency_direction', 'strategic_coverage'),
            ('test_option_exposure.py', 'test_101_dependency_direction', 'option_exposure')):
            tree = ast.parse((root/'tests'/filename).read_text(encoding='utf-8'))
            fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
            selected = [n for n in fn.body if
                        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                        {'authorized_consumers', 'allowed_contracts', 'operations'} for t in n.targets) or
                        isinstance(n, ast.FunctionDef) and n.name == 'violations']
            self.assertEqual(len(selected), 4)
            namespace = {'ast': ast}
            exec(compile(ast.Module(body=selected, type_ignores=[]), filename, 'exec'), namespace)
            yield module, namespace

    def test_102_dependency_direction(self):
        source = inspect.getsource(assembly)
        symbols = {n.module: {a.name for a in n.names} for n in ast.parse(source).body
                   if isinstance(n, ast.ImportFrom) and n.level == 1}
        for module, guard in self.guards():
            expected_consumers = {'coach02/risk_evidence_assembly.py'}
            if module == 'threat_state_assembly': expected_consumers.add('coach02/threat_reachability.py')
            self.assertEqual(guard['authorized_consumers'], expected_consumers)
            self.assertEqual(guard['allowed_contracts'], symbols[module])
            self.assertEqual(guard['violations'](source, 'coach02/risk_evidence_assembly.py'), [])
        root = Path(assembly.__file__).resolve().parent.parent
        authorized_consumers = frozenset({'coach02/risk_evidence_assembly_v02.py'})
        allowed_contracts = frozenset(('RiskEvidenceSnapshot', 'OptionRiskEvidenceBundle', 'ThreatRiskEvidence', 'EvidenceUseStatus'))
        operations = frozenset(('project_event_time', 'new_temporal_state', 'record_observations', 'evaluate_freshness', 'build_threat_observations', 'build_threat_absence_observations', 'build_visibility_completeness', 'resolve_missing_threats', 'build_threat_state', 'build_threat_relevance', 'build_strategic_coverage', 'build_option_exposure', 'build_risk_evidence', 'build_threat_reachability'))

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
                        if 'risk_evidence_assembly' in alias.name.split('.'):
                            errors.append('module import bypasses contract allowlist')
                        if alias.name == 'importlib':
                            importers.add((alias.asname or alias.name) + '.import_module')
                elif isinstance(node, ast.ImportFrom):
                    if node.module == 'importlib':
                        importers.update(a.asname or a.name for a in node.names if a.name == 'import_module')
                    if consumer and any(a.name in operations for a in node.names):
                        errors.append('orchestration operation import')
                    touches = ('risk_evidence_assembly' in (node.module or '').split('.') or
                               any(a.name == 'risk_evidence_assembly' for a in node.names))
                    if touches:
                        exact_module = ((node.level == 1 and node.module == 'risk_evidence_assembly') or
                                        (node.level == 0 and node.module == 'coach02.risk_evidence_assembly'))
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
                                       and 'risk_evidence_assembly' in arg.value.split('.') for arg in node.args):
                        errors.append('dynamic foundation import')
            return errors

        for symbol in allowed_contracts:
            source = 'from .risk_evidence_assembly import ' + symbol
            self.assertEqual(violations(source, 'coach02/risk_evidence_assembly_v02.py'), [])
            self.assertTrue(violations(source, 'coach02/arbitrary_future.py'))
        rejected = ['from .risk_evidence_assembly import *', 'import coach02.risk_evidence_assembly',
                    'from coach02 import risk_evidence_assembly', "__import__('coach02.risk_evidence_assembly')"]
        for symbol in allowed_contracts:
            rejected.append('from .risk_evidence_assembly import ' + symbol + ' as C; alias=C; alias()')
        for operation in operations:
            rejected.append('from .risk_evidence_assembly import ' + operation)
            rejected.append('runtime.' + operation + '()')
        for source in rejected:
            self.assertTrue(violations(source, 'coach02/risk_evidence_assembly_v02.py'))
        for path in [root / 'run.py'] + list((root / 'coach').rglob('*.py')) + list((root / 'coach02').rglob('*.py')):
            relative = path.relative_to(root).as_posix()
            if relative == 'coach02/risk_evidence_assembly.py': continue
            self.assertEqual(violations(path.read_text(encoding='utf-8'), relative), [], relative)

    def test_103_restricted_consumers(self):
        for module, guard in self.guards():
            for symbol in guard['allowed_contracts']:
                source = 'from .' + module + ' import ' + symbol
                for path in ('coach02/arbitrary_future.py', 'coach02/service.py', 'coach02/decision.py', 'run.py'):
                    self.assertTrue(guard['violations'](source, path))
            sources = ['from .' + module + ' import *', 'import coach02.' + module,
                       'from coach02 import ' + module,
                       "import importlib as loader; loader.import_module('coach02." + module + "')",
                       "from importlib import import_module as load; load('coach02." + module + "')"]
            for symbol in guard['allowed_contracts']:
                sources.append('from .' + module + ' import ' + symbol + ' as Contract; alias=Contract; alias()')
            for operation in guard['operations']:
                sources.append('from .' + module + ' import ' + operation + ' as run; alias=run; alias()')
                sources.append('runtime.' + operation + '()')
            for source in sources:
                with self.subTest(module=module, source=source):
                    self.assertTrue(guard['violations'](source, 'coach02/risk_evidence_assembly.py'))

    def test_104_existing_production_hashes(self):
        root = Path(assembly.__file__).resolve().parent.parent
        self.assertEqual(len(PRODUCTION_HASHES), 41)
        for path, sha in PRODUCTION_HASHES:
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((root/path).read_bytes()).hexdigest().upper(), sha)


PRODUCTION_HASHES = (('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'))
