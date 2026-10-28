"""Explicit execution evidence, temporal chains and immutable upstream preservation."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
import hashlib
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import execution_lifecycle_v01 as lifecycle
from coach02.execution_lifecycle_v01 import (
    ExecutionLifecyclePhase as Phase, ExecutionKnowledgeStatus as Knowledge,
    ExecutionLifecycleBindingV1 as Binding, ExecutionLifecycleObservationV1 as Observation,
    ExecutionLifecycleStateV1 as State, build_execution_lifecycle_state_v1 as build,
)
from test_selection_hysteresis_v01 import current, step as stabilize


def hys(tick=100, **kwargs):
    return stabilize(current(tick=tick, **kwargs))


def binding(selected=None, **changes):
    selected = hys() if selected is None else selected
    values = dict(execution_context_id='execution-context', execution_instance_id='instance-X',
                  option_id='A', hysteresis_state_id=selected.state_id, basis_tick=selected.evaluated_at_tick,
                  source_id='registration-source', evidence_refs=('ref-b', 'ref-a'), binding_policy_id='binding.v1')
    values.update(changes)
    return Binding(**values)


def register(selected=None, bound=None):
    selected = hys() if selected is None else selected
    return build(current_hysteresis_state=selected, binding=binding(selected) if bound is None else bound,
                 observation=None, previous_state=None)


def observation(previous=None, tick=101, phase=Phase.IN_PROGRESS, knowledge=Knowledge.KNOWN, **changes):
    values = dict(execution_context_id='execution-context', execution_instance_id='instance-X', option_id='A',
                  timeline_id='timeline', selected_clock_id='clock', basis_tick=tick, knowledge_status=knowledge,
                  phase=phase, source_id='execution-source', evidence_refs=('obs-b', 'obs-a'), assessment_policy_id='assessment.v1')
    if previous is not None:
        values.update(execution_context_id=previous.execution_context_id, execution_instance_id=previous.execution_instance_id,
                      option_id=previous.option_id, timeline_id=previous.timeline_id, selected_clock_id=previous.selected_clock_id)
    values.update(changes)
    return Observation(**values)


def advance(previous, obs=None, tick=101, selected=None, bound=None):
    return build(current_hysteresis_state=hys(tick) if selected is None else selected,
                 binding=previous.base_binding if bound is None else bound, observation=obs, previous_state=previous)


def known(previous=None, phase=Phase.IN_PROGRESS, tick=101, **kwargs):
    previous = register() if previous is None else previous
    return advance(previous, observation(previous, tick, phase), tick, **kwargs)


def forged(value, **changes):
    clone = replace(value)
    for name, content in changes.items():
        object.__setattr__(clone, name, content)
    return clone


def dependency_violations(source, path):
    tree = ast.parse(source)
    producer = path == 'coach02/execution_lifecycle_v01.py'
    allowed = {'SelectionHysteresisStateV1', 'SelectionHysteresisStatus'}
    domain = 'selection_hysteresis_v01'
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if domain in item.name.split('.') or producer and (item.name not in ('hashlib', 'json') or item.asname):
                    errors.append('module/domain import')
        if isinstance(node, ast.ImportFrom):
            touches = domain in (node.module or '').split('.') or any(a.name == domain for a in node.names)
            if touches:
                exact = node.level == 1 and node.module == domain or node.level == 0 and node.module == 'coach02.'+domain
                if not producer or not exact or any(a.name not in allowed or a.asname for a in node.names):
                    errors.append('consumer/symbol/path')
            elif producer:
                permitted = {'dataclass'} if node.module == 'dataclasses' else {'Enum'} if node.module == 'enum' else set()
                if node.level or not permitted or any(a.name not in permitted or a.asname for a in node.names):
                    errors.append('other domain')
        if producer and isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name) and node.value.id in allowed:
            errors.append('contract alias')
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if producer and name in allowed:
                errors.append('upstream constructor')
            if name in ('__import__', 'eval', 'exec') or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                if producer or any(isinstance(a, ast.Constant) and type(a.value) is str and domain in a.value for a in node.args):
                    errors.append('dynamic import')
    return errors


class ExecutionLifecycleV1Tests(unittest.TestCase):
    def rejects(self, fn, *args, **kwargs):
        with self.assertRaises((TypeError, ValueError)):
            fn(*args, **kwargs)

    def blank(self, factory, names):
        class Text(str): pass
        for name in names:
            for bad in ('', ' \t\n', '\u2003', None, False, 1, Text('value')):
                with self.subTest(name=name, bad=bad):
                    self.rejects(factory, **{name:bad})

    def expected(self, state, phase, knowledge=Knowledge.KNOWN, recorded=101, observed=101):
        self.assertIs(state.last_known_phase, phase)
        self.assertIs(state.knowledge_status, knowledge)
        self.assertEqual((state.last_known_phase_recorded_at_tick, state.last_known_phase_observed_at_tick), (recorded, observed))
        self.assertIs(state.effective_phase, phase if knowledge is Knowledge.KNOWN else None)
        return state

    def test_001_phase_domain(self):
        names=('NOT_STARTED','IN_PROGRESS','COMPLETED','ABORTED','EXPIRED')
        self.assertEqual({k:v.value for k,v in Phase.__members__.items()}, {n:n for n in names})
    def test_002_knowledge_domain(self):
        self.assertEqual({k:v.value for k,v in Knowledge.__members__.items()}, {'KNOWN':'KNOWN','INDETERMINATE':'INDETERMINATE'})
    def test_003_binding_schema_frozen(self):
        self.assertEqual(tuple(f.name for f in fields(Binding)), ('execution_context_id','execution_instance_id','option_id','hysteresis_state_id','basis_tick','source_id','evidence_refs','binding_policy_id'))
        with self.assertRaises(FrozenInstanceError):binding().option_id='B'
    def test_004_observation_schema_frozen(self):
        self.assertEqual(tuple(f.name for f in fields(Observation)), ('execution_context_id','execution_instance_id','option_id','timeline_id','selected_clock_id','basis_tick','knowledge_status','phase','source_id','evidence_refs','assessment_policy_id'))
        with self.assertRaises(FrozenInstanceError):observation().phase=Phase.COMPLETED
    def test_005_state_schema_frozen(self):
        self.assertEqual(tuple(f.name for f in fields(State)), ('base_binding','timeline_id','selected_clock_id','evaluated_at_tick','last_known_phase','last_known_phase_recorded_at_tick','last_known_phase_observed_at_tick','knowledge_status','current_hysteresis_state','current_observation','previous_state_id','ruleset'))
        with self.assertRaises(FrozenInstanceError):register().last_known_phase=Phase.IN_PROGRESS
    def test_006_binding_exact_text(self):
        self.blank(binding, ('execution_context_id','execution_instance_id','option_id','hysteresis_state_id','source_id','binding_policy_id'))
    def test_007_observation_exact_text(self):
        self.blank(observation, ('execution_context_id','execution_instance_id','option_id','timeline_id','selected_clock_id','source_id','assessment_policy_id'))
    def test_008_exact_nonnegative_ticks(self):
        class Tick(int): pass
        for factory in (binding, observation):
            for bad in (False, True, Tick(1), 1.0, '1', None, -1):self.rejects(factory, basis_tick=bad)
    def test_009_refs_validation(self):
        for factory in (binding, observation):
            for bad in ([], 'ref', None, ('',), (' ',), (1,), ('x','x')):self.rejects(factory,evidence_refs=bad)
            self.assertEqual(factory(evidence_refs=()).evidence_refs,())
    def test_010_knowledge_phase_combinations(self):
        for bad in (None, 'KNOWN', False):self.rejects(observation,knowledge=bad)
        for bad in (None, 'IN_PROGRESS', False, Knowledge.KNOWN):self.rejects(observation,phase=bad)
        for p in Phase:self.rejects(observation,knowledge=Knowledge.INDETERMINATE,phase=p)
        self.assertIsNone(observation(knowledge=Knowledge.INDETERMINATE,phase=None).phase)
    def test_011_builder_keyword_api(self):
        params=inspect.signature(build).parameters
        self.assertEqual(tuple(params),('current_hysteresis_state','binding','observation','previous_state'))
        self.assertTrue(all(p.kind==p.KEYWORD_ONLY and p.default==p.empty for p in params.values()))
        self.rejects(build,hys(),binding(),None,None)
    def test_012_exact_roots(self):
        s=register()
        inputs=dict(current_hysteresis_state=hys(101),binding=s.base_binding,observation=None,previous_state=s)
        for name in inputs:
            if name=='observation':base=observation()
            else:base=inputs[name]
            child=object.__new__(type('Child',(type(base),),{}))
            for bad in ({},child):self.rejects(build,**dict(inputs,**{name:bad}))

    def test_013_selection_alone_no_registration(self):
        selected=hys();self.assertEqual(selected.effective_selected_option_id,'A')
        self.rejects(build,current_hysteresis_state=selected,binding=None,observation=None,previous_state=None)
    def test_014_registration_not_started(self):
        s=register();self.expected(s,Phase.NOT_STARTED,recorded=100,observed=100)
        self.assertIsNone(s.current_observation);self.assertIsNone(s.previous_state_id)
    def test_015_registration_exact_objects(self):
        selected=hys();bound=binding(selected);s=register(selected,bound)
        self.assertIs(s.base_binding,bound);self.assertIs(s.current_hysteresis_state,selected)
    def test_016_registration_wrong_option(self):self.rejects(register,bound=binding(option_id='B'))
    def test_017_registration_no_selection(self):self.rejects(register,selected=hys(status='NO_SELECTION'))
    def test_018_registration_indeterminate(self):self.rejects(register,selected=hys(status='INDETERMINATE'))
    def test_019_registration_foreign_hysteresis(self):self.rejects(register,bound=binding(hys(101)))
    def test_020_registration_wrong_tick(self):
        for tick in (99,101):self.rejects(register,bound=binding(basis_tick=tick))
    def test_021_registration_with_observation(self):
        self.rejects(build,current_hysteresis_state=hys(),binding=binding(),observation=observation(tick=100),previous_state=None)
    def test_022_continuation_without_previous(self):
        s=known();self.rejects(build,current_hysteresis_state=hys(102),binding=s.base_binding,observation=None,previous_state=None)
        self.rejects(build,current_hysteresis_state=hys(102),binding=s.base_binding,observation=observation(tick=102),previous_state=None)
    def test_023_new_same_option_instance(self):
        x=known(phase=Phase.COMPLETED);selected=hys(102);b=binding(selected,execution_instance_id='instance-Y');y=register(selected,b)
        self.assertEqual(x.option_id,y.option_id);self.assertNotEqual(x.execution_instance_id,y.execution_instance_id)
        self.assertIsNone(y.previous_state_id);self.assertFalse(y.instance_is_terminal)
    def test_024_instance_not_option_identity(self):
        self.assertNotEqual(binding().binding_id,binding(execution_instance_id='instance-Y').binding_id)
    def test_025_original_binding_retained(self):
        s=register();clone=replace(s.base_binding);out=advance(s,bound=clone)
        self.assertIs(out.base_binding,s.base_binding);self.assertIsNot(out.base_binding,clone)
    def test_026_registration_lineage_stays_original(self):
        s=register();out=known(s,tick=102)
        self.assertEqual(out.registered_hysteresis_state_id,s.current_hysteresis_state_id)
        self.assertNotEqual(out.current_hysteresis_state_id,out.registered_hysteresis_state_id)

    def test_027_start(self):self.expected(known(),Phase.IN_PROGRESS)
    def test_028_sparse_completion(self):self.expected(known(phase=Phase.COMPLETED),Phase.COMPLETED)
    def test_029_abort_before_start(self):self.expected(known(phase=Phase.ABORTED),Phase.ABORTED)
    def test_030_expire_before_start(self):self.expected(known(phase=Phase.EXPIRED),Phase.EXPIRED)
    def test_031_not_started_confirmation(self):self.expected(known(phase=Phase.NOT_STARTED),Phase.NOT_STARTED,recorded=100)
    def test_032_progress_confirmation(self):self.expected(known(known(),tick=102),Phase.IN_PROGRESS,recorded=101,observed=102)
    def test_033_progress_completion(self):self.expected(known(known(),Phase.COMPLETED,102),Phase.COMPLETED,recorded=102,observed=102)
    def test_034_progress_abort(self):self.expected(known(known(),Phase.ABORTED,102),Phase.ABORTED,recorded=102,observed=102)
    def test_035_progress_expiry(self):self.expected(known(known(),Phase.EXPIRED,102),Phase.EXPIRED,recorded=102,observed=102)
    def test_036_no_progress_regression(self):self.rejects(known,known(),Phase.NOT_STARTED,102)
    def test_037_completed_absorbing(self):
        s=known(phase=Phase.COMPLETED)
        for phase in Phase:
            if phase is not Phase.COMPLETED:self.rejects(known,s,phase,102)
    def test_038_aborted_absorbing(self):
        s=known(phase=Phase.ABORTED)
        for phase in Phase:
            if phase is not Phase.ABORTED:self.rejects(known,s,phase,102)
    def test_039_expired_absorbing(self):
        s=known(phase=Phase.EXPIRED)
        for phase in Phase:
            if phase is not Phase.EXPIRED:self.rejects(known,s,phase,102)
    def test_040_terminal_repeat_timestamps(self):
        for phase in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):
            self.expected(known(known(phase=phase),phase,102),phase,recorded=101,observed=102)
    def test_041_terminal_same_selection_no_new_instance(self):
        s=known(phase=Phase.COMPLETED);out=advance(s,tick=102)
        self.assertEqual(out.execution_instance_id,s.execution_instance_id);self.assertTrue(out.instance_is_terminal)
    def test_042_all_phase_transition_pairs(self):
        for before in Phase:
            s=known(phase=before)
            for after in Phase:
                legal=before is Phase.NOT_STARTED or before is Phase.IN_PROGRESS and after is not Phase.NOT_STARTED or before is after
                if legal:self.assertIs(known(s,after,102).last_known_phase,after)
                else:self.rejects(known,s,after,102)

    def test_043_missing_observation_progress(self):self.expected(advance(known(),tick=102),Phase.IN_PROGRESS,Knowledge.INDETERMINATE,101,101)
    def test_044_explicit_indeterminate_progress(self):
        s=known();obs=observation(s,102,None,Knowledge.INDETERMINATE)
        out=self.expected(advance(s,obs,102),Phase.IN_PROGRESS,Knowledge.INDETERMINATE,101,101)
        self.assertIs(out.current_observation,obs)
    def test_045_absent_vs_explicit_provenance(self):
        s=known();a=advance(s,tick=102);b=advance(s,observation(s,102,None,Knowledge.INDETERMINATE),102)
        self.assertEqual(a.effective_phase,b.effective_phase);self.assertIsNone(a.current_observation_id)
        self.assertIsNotNone(b.current_observation_id);self.assertNotEqual(a.state_id,b.state_id)
    def test_046_gap_then_completion(self):self.expected(known(advance(known(),tick=102),Phase.COMPLETED,103),Phase.COMPLETED,recorded=103,observed=103)
    def test_047_gap_then_progress(self):self.expected(known(advance(known(),tick=102),tick=103),Phase.IN_PROGRESS,recorded=101,observed=103)
    def test_048_gap_then_start(self):self.expected(known(advance(register(),tick=101),tick=102),Phase.IN_PROGRESS,recorded=102,observed=102)
    def test_049_explicit_gap_then_abort(self):
        s=known();gap=advance(s,observation(s,102,None,Knowledge.INDETERMINATE),102)
        self.expected(known(gap,Phase.ABORTED,103),Phase.ABORTED,recorded=103,observed=103)
    def test_050_terminal_missing_observation(self):
        for p in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):
            out=self.expected(advance(known(phase=p),tick=102),p,Knowledge.INDETERMINATE,101,101)
            self.assertTrue(out.instance_is_terminal)
    def test_051_terminal_indeterminate_observation(self):
        for p in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):
            s=known(phase=p);out=advance(s,observation(s,102,None,Knowledge.INDETERMINATE),102)
            self.assertIsNone(out.effective_phase);self.assertTrue(out.instance_is_terminal)
    def test_052_terminal_gap_no_reopen(self):
        for p in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):self.rejects(known,advance(known(phase=p),tick=102),Phase.IN_PROGRESS,103)
    def test_053_repeated_gaps_keep_memory_times(self):
        s=known()
        for tick in (102,103,110):s=advance(s,tick=tick)
        self.expected(s,Phase.IN_PROGRESS,Knowledge.INDETERMINATE,101,101)
    def test_054_no_observation_does_not_expire(self):
        self.expected(advance(register(),tick=100000),Phase.NOT_STARTED,Knowledge.INDETERMINATE,100,100)
    def test_055_known_independent_of_prior_knowledge(self):
        for phase in Phase:
            s=known(phase=phase);gap=advance(s,tick=102)
            self.expected(known(gap,phase,103),phase,recorded=100 if phase is Phase.NOT_STARTED else 101,observed=103)
    def test_056_effective_phase_property(self):
        self.assertIs(register().effective_phase,Phase.NOT_STARTED)
        self.assertIsNone(advance(register()).effective_phase)

    def test_057_same_selection_match(self):self.assertIs(known().selection_matches_execution,True)
    def test_058_different_selection_match(self):
        s=known();out=advance(s,tick=102,selected=hys(102,winner='B'))
        self.assertIs(out.selection_matches_execution,False);self.assertEqual(out.current_selection_option_id,'B')
        self.assertEqual(out.option_id,'A');self.assertIs(out.last_known_phase,Phase.IN_PROGRESS)
    def test_059_switch_before_start_no_expiry(self):
        out=advance(register(),selected=hys(101,winner='B'))
        self.expected(out,Phase.NOT_STARTED,Knowledge.INDETERMINATE,100,100)
    def test_060_switch_with_confirmed_progress(self):
        self.expected(known(known(),tick=102,selected=hys(102,winner='B')),Phase.IN_PROGRESS,recorded=101,observed=102)
    def test_061_no_selection_confirmed_progress(self):
        out=known(known(),tick=102,selected=hys(102,status='NO_SELECTION'))
        self.assertIs(out.effective_phase,Phase.IN_PROGRESS);self.assertIs(out.selection_matches_execution,False)
    def test_062_indeterminate_selection_confirmed_progress(self):
        out=known(known(),tick=102,selected=hys(102,status='INDETERMINATE'))
        self.assertIs(out.knowledge_status,Knowledge.KNOWN);self.assertIsNone(out.selection_matches_execution)
    def test_063_no_selection_without_observation(self):
        out=advance(known(),tick=102,selected=hys(102,status='NO_SELECTION'))
        self.assertIsNone(out.effective_phase);self.assertIs(out.last_known_phase,Phase.IN_PROGRESS)
    def test_064_indeterminate_selection_without_observation(self):
        out=advance(known(),tick=102,selected=hys(102,status='INDETERMINATE'))
        self.assertIsNone(out.effective_phase);self.assertIs(out.last_known_phase,Phase.IN_PROGRESS)
    def test_065_current_hysteresis_exact_object(self):
        selected=hys(102,winner='B');out=known(known(),tick=102,selected=selected)
        self.assertIs(out.current_hysteresis_state,selected);self.assertEqual(out.current_hysteresis_state_id,selected.state_id)
    def test_066_selection_absent_option_no_abort(self):
        out=known(known(),tick=102,selected=hys(102,names=('B','C'),winner='B'))
        self.assertEqual(out.option_id,'A');self.assertFalse(out.instance_is_terminal)
    def test_067_current_context_changes_not_binding(self):
        s=known();out=known(s,tick=102,selected=hys(102,context='new-context'))
        self.assertIs(out.base_binding,s.base_binding);self.assertIs(out.effective_phase,Phase.IN_PROGRESS)
    def test_068_selection_memory_not_effective(self):
        previous=stabilize(current())
        selected=stabilize(current(tick=101,status='INDETERMINATE'),previous)
        self.assertEqual(selected.remembered_option_id,'A')
        out=advance(register(),selected=selected)
        self.assertIsNone(out.current_selection_option_id);self.assertIsNone(out.selection_matches_execution)

    def test_069_same_tick_rejected(self):self.rejects(advance,register(),tick=100)
    def test_070_backwards_tick_rejected(self):self.rejects(advance,register(),tick=99)
    def test_071_timeline_change_rejected(self):self.rejects(advance,register(),selected=hys(101,timeline='other'))
    def test_072_clock_change_rejected(self):self.rejects(advance,register(),selected=hys(101,clock='other'))
    def test_073_observation_tick_rejected(self):
        for tick in (100,102):self.rejects(advance,register(),obs=observation(tick=tick))
    def test_074_observation_domains_rejected(self):
        for name in ('timeline_id','selected_clock_id'):self.rejects(advance,register(),obs=observation(**{name:'other'}))
    def test_075_binding_context_rejected(self):self.rejects(advance,register(),bound=binding(execution_context_id='other'))
    def test_076_binding_instance_rejected(self):self.rejects(advance,register(),bound=binding(execution_instance_id='other'))
    def test_077_binding_option_rejected(self):self.rejects(advance,register(),bound=binding(option_id='B'))
    def test_078_binding_provenance_rejected(self):
        s=register()
        for changes in (dict(source_id='other'),dict(binding_policy_id='other'),dict(evidence_refs=('other',)),dict(basis_tick=99),dict(hysteresis_state_id=hys(99).state_id)):
            self.rejects(advance,s,bound=replace(s.base_binding,**changes))
    def test_079_observation_instance_rejected(self):
        for name in ('execution_context_id','execution_instance_id','option_id'):self.rejects(advance,register(),obs=observation(**{name:'other'}))
    def test_080_previous_lineage_id_only(self):
        s=register();out=known(s)
        self.assertEqual(out.previous_state_id,s.state_id)
        self.assertNotIn('previous_state',tuple(f.name for f in fields(State)))

    def test_081_binding_id_canonical_payload(self):
        b=binding();payload={f.name:getattr(b,f.name) for f in fields(b)};payload['ruleset']=lifecycle.RULESET
        expected=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(b.binding_id,'execution.lifecycle.v1:binding:'+expected)
    def test_082_observation_id_canonical_payload(self):
        o=observation();payload={f.name:getattr(o,f.name) for f in fields(o)};payload['ruleset']=lifecycle.RULESET
        expected=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(o.observation_id,'execution.lifecycle.v1:observation:'+expected)
    def test_083_state_id_canonical_payload(self):
        s=known();names=('binding_id','execution_context_id','execution_instance_id','option_id','timeline_id','selected_clock_id','evaluated_at_tick','last_known_phase','last_known_phase_recorded_at_tick','last_known_phase_observed_at_tick','knowledge_status','current_hysteresis_state_id','current_observation_id','previous_state_id','ruleset')
        payload={name:getattr(s,name) for name in names}
        expected=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(s.state_id,'execution.lifecycle.v1:state:'+expected)
    def test_084_binding_all_fields_bound(self):
        b=binding()
        changes=dict(execution_context_id='other',execution_instance_id='other',option_id='other',hysteresis_state_id=hys(99).state_id,basis_tick=99,source_id='other',evidence_refs=('other',),binding_policy_id='other')
        for name,value in changes.items():self.assertNotEqual(b.binding_id,replace(b,**{name:value}).binding_id)
    def test_085_observation_all_fields_bound(self):
        o=observation();changes=dict(execution_context_id='other',execution_instance_id='other',option_id='other',timeline_id='other',selected_clock_id='other',basis_tick=102,phase=Phase.COMPLETED,source_id='other',evidence_refs=('other',),assessment_policy_id='other')
        for name,value in changes.items():self.assertNotEqual(o.observation_id,replace(o,**{name:value}).observation_id)
        self.assertNotEqual(o.observation_id,replace(o,knowledge_status=Knowledge.INDETERMINATE,phase=None).observation_id)
    def test_086_refs_order_preserved_and_bound(self):
        for value in (binding(),observation()):
            clone=replace(value,evidence_refs=tuple(reversed(value.evidence_refs)))
            key='binding_id' if type(value) is Binding else 'observation_id'
            self.assertNotEqual(getattr(value,key),getattr(clone,key))
        s=register();obs=observation(s);out=advance(s,obs)
        self.assertIs(out.current_observation,obs);self.assertEqual(out.current_observation.evidence_refs,('obs-b','obs-a'))
    def test_087_opaque_ids_no_trim(self):
        for name in ('execution_context_id','execution_instance_id','option_id','source_id','binding_policy_id'):
            value=' opaque:/\u03b2 '+name+' ';self.assertEqual(getattr(binding(**{name:value}),name),value)
    def test_088_observation_exact_preservation(self):
        s=register();o=observation(s);out=advance(s,o)
        self.assertIs(out.current_observation,o);self.assertEqual(out.current_observation_id,o.observation_id)
    def test_089_deterministic_repeated_call(self):
        s=register();o=observation(s);a=advance(s,o);b=advance(s,o)
        self.assertEqual(a,b);self.assertEqual(a.state_id,b.state_id)
    def test_090_previous_and_inputs_not_mutated(self):
        s=register();o=observation(s);snap=(s.state_id,o.observation_id,s.binding_id)
        advance(s,o);self.assertEqual(snap,(s.state_id,o.observation_id,s.binding_id))
    def test_091_forged_observation_revalidated(self):
        for changes in (dict(phase='IN_PROGRESS'),dict(basis_tick=True),dict(source_id=''),dict(evidence_refs=('x','x')),dict(knowledge_status='KNOWN')):
            self.rejects(advance,register(),obs=forged(observation(),**changes))
    def test_092_forged_previous_revalidated(self):
        s=known()
        for changes in (dict(ruleset='other'),dict(last_known_phase='IN_PROGRESS'),dict(knowledge_status='KNOWN'),dict(evaluated_at_tick=True),dict(last_known_phase_recorded_at_tick=102),dict(previous_state_id='foreign'),dict(current_observation=None),dict(timeline_id='other')):
            self.rejects(advance,forged(s,**changes),tick=102)

    def test_093_production_import_guard(self):
        self.assertEqual(dependency_violations(inspect.getsource(lifecycle),'coach02/execution_lifecycle_v01.py'),[])
    def test_094_reverse_consumer_guard(self):
        source='from .selection_hysteresis_v01 import SelectionHysteresisStateV1, SelectionHysteresisStatus'
        self.assertEqual(dependency_violations(source,'coach02/execution_lifecycle_v01.py'),[])
        self.assertTrue(dependency_violations(source,'coach02/foreign.py'))
        root=Path(__file__).resolve().parents[1]
        for p in (root/'coach02').glob('*.py'):
            self.assertEqual(dependency_violations(p.read_text(encoding='utf-8'),p.relative_to(root).as_posix()),[],p.name)
    def test_095_guard_adversarial_imports(self):
        for source in ('import coach02.selection_hysteresis_v01','from coach02 import selection_hysteresis_v01','from .selection_hysteresis_v01 import *','from .selection_hysteresis_v01 import SelectionHysteresisStateV1 as S','from .selection_hysteresis_v01 import build_selection_hysteresis_state_v1',"__import__('coach02.selection_hysteresis_v01')",'from .decision_context_v02 import OptionDecisionContextV2','from .selection_hysteresis_v01 import SelectionHysteresisStateV1\nSelectionHysteresisStateV1()','from .selection_hysteresis_v01 import SelectionHysteresisStateV1\nS=SelectionHysteresisStateV1'):
            self.assertTrue(dependency_violations(source,'coach02/execution_lifecycle_v01.py'),source)
    def test_096_upstream_domains_prohibited(self):
        for domain in ('decision_arbiter_v01','decision_context_v02','option_safety_v02','feasibility_gate_v01','pairwise_tradeoff_v01','risk_evaluation','option_outcome_evidence','strategic_objective_context','temporal_evidence','decision','farm_cycle','runtime','service','gsi','vision','voice'):
            self.assertTrue(dependency_violations('from .'+domain+' import Something','coach02/execution_lifecycle_v01.py'))
    def test_097_no_action_microplan_attention(self):
        tree=ast.parse(inspect.getsource(lifecycle));tokens={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}|{n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        schema={f.name for cls in (Binding,Observation,State) for f in fields(cls)}
        self.assertTrue({'Action','Authority','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS','Microplan','route','waypoint','target','urgency','voice','COMMITTED','REVERSIBLE','IRREVERSIBLE','abort_cost','switch_cost'}.isdisjoint(tokens|schema))
    def test_098_no_policy_event_or_idle_contract(self):
        for name in ('ExecutionLifecyclePolicyV1','ExecutionLifecycleEventV1','ExecutionLifecycleEvent','IDLE','NO_EXECUTION'):
            self.assertFalse(hasattr(lifecycle,name));self.assertNotIn(name,Phase.__members__)
    def test_099_no_runtime_side_effects(self):
        with patch('builtins.open',side_effect=AssertionError('filesystem')),patch('socket.socket',side_effect=AssertionError('network')),patch('time.time',side_effect=AssertionError('clock')),patch('time.sleep',side_effect=AssertionError('sleep')):
            s=register();self.assertIs(known(s).effective_phase,Phase.IN_PROGRESS)
        tree=ast.parse(inspect.getsource(lifecycle))
        names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        self.assertTrue({'random','uuid','threading','asyncio','time','socket','Path','open'}.isdisjoint(names))
    def test_100_forged_binding_revalidated(self):
        s=register()
        for changes in (dict(execution_instance_id=''),dict(basis_tick=True),dict(evidence_refs=['ref-b','ref-a']),dict(hysteresis_state_id='foreign')):
            self.rejects(advance,s,bound=forged(s.base_binding,**changes))
    def test_101_forged_hysteresis_revalidated(self):
        selected=hys(101)
        for changes in (dict(ruleset='other'),dict(status='SELECTED'),dict(evaluated_at_tick=True),dict(timeline_id='other'),dict(effective_selected_option_id='B'),dict(effective_selected_option=None),dict(current_arbiter_result_id='foreign')):
            self.rejects(advance,register(),selected=forged(selected,**changes))
    def test_102_state_boundary_validation(self):
        s=register()
        for changes in (dict(last_known_phase=Phase.COMPLETED),dict(knowledge_status=Knowledge.INDETERMINATE),dict(current_observation=observation(tick=100)),dict(last_known_phase_observed_at_tick=99),dict(selected_clock_id='other')):
            self.rejects(replace,s,**changes)
        gap=advance(s)
        self.rejects(replace,gap,last_known_phase_observed_at_tick=101)
        self.rejects(replace,gap,previous_state_id=None)
    def test_103_full_canonical_preservation(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(len(BASELINE_HASHES),139)
        for name,digest in BASELINE_HASHES:
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),digest,name)
    def test_104_documented_semantic_boundaries(self):
        text=(Path(__file__).resolve().parents[1]/'EXECUTION_LIFECYCLE_V01.md').read_text(encoding='utf-8')
        for phrase in ('Selection does not create execution.','Execution registration is explicit.','Missing observation does not establish known continuation.','IN_PROGRESS does not mean COMMITTED.','BLOCKER_BEFORE_COMMITMENT_REVERSIBILITY','BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING','BLOCKER_BEFORE_MICROPLAN','BLOCKER_BEFORE_ATTENTION_GATE','BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION'):
            self.assertIn(phrase,text)


BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'), ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'), ('DECISION_ARBITER_V01.md', '85B662C99AF6BE245D01012D8121023D52F3B79E881EE2BAE29F3EF2E6F6991F'), ('DECISION_CONTEXT_V02.md', 'CB3F1615EC752ADF523DDFB7FA5F3C5A5ECE4EBB3E35E55C19C9449C649507F3'), ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'), ('FEASIBILITY_GATE_V01.md', '9F40450123FA2D511764617500433B90929E1AA90D854BD03A493BCF38A6BDB2'), ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md', '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'), ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'), ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'), ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'), ('OBJECTIVE_OUTCOME_RELATION_V01.md', 'C466F62DB319AFB730EC7ACE4FA67039ABD9A5D22F12CB5794DABDB05D73C7C6'), ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'), ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'), ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'), ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'), ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'), ('OPTION_OUTCOME_EVIDENCE_V01.md', '61D6DAD163B724E2EB9BD6859BBD476E828AC3574D32A3FDDEC7B58F3E7BC53A'), ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'), ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'), ('PAIRWISE_TRADEOFF_V01.md', '7290D806C360314C9771EDF208C5F0BDE7A204AD02663FD22C91EC890AB1E465'), ('README.md', '72A60A5815269D2B2EAED3119841A4D57D26E6564F56BE104C6766F2FAAEF674'), ('RISK_EVALUATION_V01.md', '7A13246FD6D31A4A58C22AA9C1D209FF40727D79C8E90339620EDFDF2A878C32'), ('RISK_EVIDENCE_ASSEMBLY_V01.md', 'D44F8700089A390AC5CF6C670A78481A7340CF84A98A4766D194BF1D821B28B6'), ('RISK_EVIDENCE_ASSEMBLY_V02.md', '60A9C3B76C42C19B42EE94DA50A3A6C7E85400398502117200B3BF4F388D4D76'), ('RUNTIME_ADAPTER_V01.md', '723B87C9FA564CCB0527D6647F66D9752DA127082910C415D10838449E0051AE'), ('Run-Tests.cmd', 'C7D36F01B393C13362D8C6FB35D6C5FFDB9A81DC7AE086B61DE723974240136A'), ('SAFETY_EVIDENCE_V01.md', '160811B5829650324AD3353DD89C85ABAB878D3465B9261D0AFE840F284A8978'), ('SELECTION_HYSTERESIS_V01.md', '7A481B26A5AEAAB72B9664403CA566CFC28EE61DD8C585FD1566FA09F41D2E60'), ('STRATEGIC_COVERAGE_V01.md', '70AB604B5F34613F0BB306CC7E48FFB95CE1CA5419DB38427B91E8D4A8FB9181'), ('STRATEGIC_EVIDENCE_ASSEMBLY_V01.md', 'E2918BA287987AE36DF60BAD083CC45726998CFA97F082A626EB103D2F76FADD'), ('STRATEGIC_OBJECTIVE_CONTEXT_V01.md', 'CC437194EA74D601D78E3BAEC613D0376E0759690A74BB02EF94DA910916B3E7'), ('Start-Bot-Test.cmd', 'A967FFFC010A28FB3957C86B8B2AAF5DA7E98B40BA645B4DE63464FDBF3A11A4'), ('Start-Coach.cmd', '400EF821414BC0036D0BD29ED6382CDCC3477147604DAFCFAE488C7E329A8123'), ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'), ('THREAT_ABSENCE_OBSERVATION_V01.md', '6A37416C544E27A08DB0B8B1BC4D2D07136C833DE0A8674DD17EC79D9F9F0952'), ('THREAT_OBSERVATION_V01.md', '4633E7C0E920F790605DA27635A8D84ACA38DE59A52485CF16DEF1C7EDB8327B'), ('THREAT_REACHABILITY_V01.md', '180A3F7995AD367FD62DFCAA2175C03C6E1940C6C4BCFE80BF05C575DF0F2D42'), ('THREAT_RELEVANCE_V01.md', '51F9BEB03B612559A8EA350AB4C9FF5438C05A40EEAE5798CD40B5D1AD069666'), ('THREAT_STATE_ASSEMBLY_V01.md', 'CD7DDFAAFDBBA7A295616A1820FC267F46651C8B3AEB9ED445532B5C48E9766A'), ('VISIBILITY_COMPLETENESS_V01.md', 'E79A0B25695A39529E324F18792CA9C4CD31BDEB8EF8548C3FD351BB3DAFA7B3'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/decision_arbiter_v01.py', '39AC69E1A1164DD926C0735B8082FA9FC2F909140E125373427D80D2BAB02002'), ('coach02/decision_context_v02.py', '3F07B86C7FABA28118C87B9646D2094A3A7A65C531A9D07255CC0B25BB9D74EF'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/feasibility_gate_v01.py', 'C1C9D6BB47622F880F98DA5783008F7350B332B2992876EF68D9CB87993A1E13'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/objective_outcome_relation_v01.py', '4CE5B30CA77F480B4D7C1C601E92FB096585E73B348C0E6C13BA81CE9E27DA2B'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_outcome_evidence.py', '04D5F650484CD7B067A410E6C7A37892CE054BCC1319835D2C948A0594CA0325'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'), ('coach02/pairwise_tradeoff_v01.py', '93F1DC3A7736D290C47A84F8F14776CE20370C225E6BA3C82C3B7BEF121631C3'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/selection_hysteresis_v01.py', '68E233D8617750AEC3C1A1BF7EAE16BDDBBD5F7779C47DC270400E47D0699576'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/strategic_objective_context.py', '1C217907B23E50C76DB80ED16902A5FBFE58921F5458D3F789FC087987A22A44'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('docs/CHANGES.md', 'A2DBFDAE75A11C1CFD601269E677D6F73F72A6017006D235AAD527A22F26BD9A'), ('docs/DECISIONS.md', '35C72BB38D35D8EE6A804BE9F3631047FB68E4A8E9538908F2259CD3917FB14A'), ('docs/TESTE_REAL.md', '335EC57D975ADB1FD046A358975DDF8831B67BC1F183C1AB4E576DAD675C06A8'), ('docs/VALIDATION.md', '7D5D0E515DE4D46E158DD955B2422F4B997A99000FCB531F61272FB06079A9C5'), ('docs/alpha01-reference/DECISIONS.md', '83D8C8EDD6386C958CB5A770746A1B7016C355596985DB44646EFF0B9ADA7571'), ('docs/alpha01-reference/VALIDATION.md', 'F29B09DD7427543EDA767B0FDBE68033C4A7980E6A9A9ADC3255189F274F619E'), ('docs/baseline-sha256.json', '3561C10064F6BAC12F032FCC51382EBD7D7FBEF70786C31E6C857DC386ECD40D'), ('docs/baseline-verification.json', '7326E1A33FB35E281A6A3211E85DFFD2A081BB22317C33DB7B7FAEE67E2E394B'), ('docs/test-results.txt', 'EE9BBD62124FCF6CB377DF2D79129BF0C927ACEAB2128AB247CABE92F0A7F2B7'), ('requirements-vision.txt', 'ECBC0244A6BC4646A912CF032F999724D47E22CB12CDBFAA231B600465F06711'), ('requirements.txt', 'CE972E5602F1BADF47B56CE597EBF4A3CBC516CA6C8979C95EE75C067D275840'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('tests/test_alpha.py', '17BD7EBFF1558F062577A4677A472B0B3F65B85DC921253D6A9F5C2B705862D5'), ('tests/test_alpha02.py', '9F0839D676974435FA4AB3EE4887F9BE8DF876D07C271CADA4D0AFAA43A43C02'), ('tests/test_context_builder.py', '26A50D99710BAF117FA45AA570BA8BCDC38343835FED5EEF9C2618493E9AE701'), ('tests/test_decision_arbiter_v01.py', 'F24A7006527660AAD7C49FE87040330AF01571AF87D6FFE0AA717E4181EB2AEF'), ('tests/test_decision_context_v02.py', '100702613FFB1038A884C7CE9C7F3648B98C3CA8A7457A7A1ED5D6A25E4775D9'), ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'), ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'), ('tests/test_feasibility_gate_v01.py', '13C1E9585E67BD00E08D24DFF4E243488F4CA9A183B003061F71F472CB3C0DDC'), ('tests/test_missing_threat_resolver.py', '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'), ('tests/test_objective_outcome_relation_v01.py', '4E683FE4C0BEE3F44C37EA47930DF4278AB2315BE54F2D9B78416507F5A7CC7A'), ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'), ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'), ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'), ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'), ('tests/test_option_outcome_evidence.py', '650A4F6FD90A1163A8D7DBEED12EAF121F4AB265C07620A9224E2D099E3FE8E8'), ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'), ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'), ('tests/test_pairwise_tradeoff_v01.py', '6EE9F784F0E20280EA4BE2A035133D0A82B0684DB1BE0B25C6C030E3DE1B2F7B'), ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'), ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'), ('tests/test_risk_evidence_assembly_v02.py', 'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'), ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'), ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'), ('tests/test_selection_hysteresis_v01.py', '7B94660F33EEA4563BD987B6DCC8545424BC5A4F4D4969E55758BA964EA4AF25'), ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'), ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'), ('tests/test_strategic_objective_context.py', 'D9E4442199B6FCC7F6DFAF3E867C7C1CA13FB9FBF2BCC4BA5F2BDC2BC580EA18'), ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'), ('tests/test_threat_absence_observation.py', 'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'), ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'), ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'), ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'), ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'), ('tests/test_visibility_completeness.py', '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
