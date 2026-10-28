"""Explicit state sequences, consumed-boundary rejection and dependency preservation."""
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

from coach02 import selection_hysteresis_v01 as hysteresis
from coach02.selection_hysteresis_v01 import (
    SelectionHysteresisPolicyV1 as Policy, SelectionHysteresisStateV1 as State,
    SelectionHysteresisStatus as Status, SelectionHysteresisReason as Reason,
    build_selection_hysteresis_state_v1 as transition,
)
from coach02.decision_arbiter_v01 import DecisionArbiterStatus, ArbiterCandidateAdmissionStatus
from test_decision_arbiter_v01 import fixture, build as arbitrate
from test_feasibility_gate_v01 import import_violations
from test_decision_context_v02 import consumer_violations


def policy(hold=10, confirmation=3, context='hysteresis-context', identity='switch-policy'):
    return Policy(context, identity, hold, confirmation)


def current(tick=100, winner='A', names=('A','B'), excluded=(), uncertain=(),
            status='SELECTED', context='decision-context', timeline='timeline', clock='clock'):
    if status=='INDETERMINATE' and not uncertain:
        uncertain=tuple(n for n in names if n not in excluded)[-1:]
    safety=tuple('RISK_BLOCKING' if n in excluded else None if n in uncertain else 'RISK_NOT_BLOCKING' for n in names)
    edges=tuple((left,right,'LEFT_ADVANTAGE' if winner==left and status=='SELECTED' else
                 'RIGHT_ADVANTAGE' if winner==right and status=='SELECTED' else 'TRADE_OFF','P')
                for i,left in enumerate(names) for right in names[i+1:])
    c,f,p,r=fixture(names=names,safety=safety,edges=edges)
    c=replace(c,decision_context_id=context,timeline_id=timeline,selected_clock_id=clock,decision_assembly_tick=tick)
    options={o.option_id:o for o in c.options}
    f=replace(f,decision_context_id=context,timeline_id=timeline,selected_clock_id=clock,
              evaluated_at_tick=tick,decision_context_object_id=c.context_id,
              assessments=tuple(replace(a,base_option_context=options[a.option_id]) for a in f.assessments))
    p=replace(p,decision_context_id=context,timeline_id=timeline,selected_clock_id=clock,
              evaluated_at_tick=tick,decision_context_object_id=c.context_id,
              comparisons=tuple(replace(row,decision_context_id=context,basis_tick=tick) for row in p.comparisons))
    return arbitrate((c,f,p,replace(r,decision_context_id=context)))


def step(result=None, previous=None, pol=None):
    return transition(current_arbiter_result=current() if result is None else result,
                      policy=policy() if pol is None else pol,previous_state=previous)


def forged(value, **changes):
    clone=replace(value)
    for name,content in changes.items():object.__setattr__(clone,name,content)
    return clone


def reverse_violations(source,path):
    allowed={
        'decision_arbiter_v01':{'DecisionArbiterResultV1','DecisionArbiterStatus','ArbiterCandidateAdmissionStatus','ArbiterCandidateAssessmentV1'},
        'decision_context_v02':{'OptionDecisionContextV2'},
    }
    consumer=path=='coach02/selection_hysteresis_v01.py'
    contracts=set().union(*allowed.values());errors=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Import):
            for a in node.names:
                if any(m in a.name.split('.') for m in allowed):errors.append('module import')
                if consumer and (a.name not in ('hashlib','json') or a.asname):errors.append('other import')
        if isinstance(node,ast.ImportFrom):
            module=(node.module or '').split('.')[-1]
            touches=module in allowed or any(a.name in allowed for a in node.names)
            if touches:
                exact=node.level==1 and node.module in allowed or node.level==0 and node.module=='coach02.'+module and module in allowed
                # Existing accepted Arbiter may still import its OptionDecisionContextV2.
                if not consumer:
                    if module=='decision_arbiter_v01':errors.append('unauthorized consumer')
                    elif import_violations(source,path):errors.append('unauthorized context consumer')
                if not exact or consumer and any(a.name not in allowed.get(module,set()) or a.asname for a in node.names):errors.append('symbol/path')
            elif consumer:
                symbols={'dataclass'} if node.module=='dataclasses' else {'Enum'} if node.module=='enum' else set()
                if node.level or not symbols or any(a.name not in symbols or a.asname for a in node.names):errors.append('other domain')
        if consumer and isinstance(node,(ast.Assign,ast.AnnAssign)) and isinstance(node.value,ast.Name) and node.value.id in contracts:errors.append('contract alias')
        if isinstance(node,ast.Call):
            if ast.unparse(node.func) in contracts|{'__import__','eval','exec'} or isinstance(node.func,ast.Attribute) and node.func.attr=='import_module':
                if consumer or any(isinstance(a,ast.Constant) and isinstance(a.value,str) and any(m in a.value for m in allowed) for a in node.args):errors.append('constructor/dynamic import')
    return errors


class SelectionHysteresisV1Tests(unittest.TestCase):
    def expected(self,s,reason,selected='A',remembered='A',since=100,pending=None,pending_since=None,status='SELECTED'):
        self.assertIs(s.status,Status(status));self.assertIs(s.reason,Reason(reason))
        self.assertEqual((s.effective_selected_option_id,s.remembered_option_id,s.remembered_since_tick,
                          s.pending_challenger_option_id,s.pending_challenger_since_tick),
                         (selected,remembered,since,pending,pending_since))
        if selected is None:self.assertIsNone(s.effective_selected_option)
        else:self.assertIs(s.effective_selected_option,next(a.base_option_context for a in s.current_arbiter_result.candidate_assessments if a.option_id==selected))
        return s
    def sequence(self,steps,pol=None):
        state=None
        for kwargs in steps:state=step(current(**kwargs),state,pol)
        return state
    def rejects(self,result=None,previous=None,pol=None):
        with self.assertRaises((TypeError,ValueError)):step(result,previous,pol)
    def domain(self,enum,names):self.assertEqual({k:v.value for k,v in enum.__members__.items()},{n:n for n in names})
    def pending(self,pol=None):return self.sequence([{},dict(tick=101,winner='B')],pol)
    def released(self,absent=False,status='SELECTED'):
        previous=self.pending(policy(1000,1000))
        result=current(tick=102,names=('B','C') if absent else ('A','B','C'),excluded=() if absent else ('A',),winner='B',status=status)
        return step(result,previous,policy(1000,1000))
    def no_terms(self,*terms):
        tree=ast.parse(inspect.getsource(hysteresis))
        tokens={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}|{n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}
        schema={f.name for cls in (Policy,State) for f in fields(cls)}
        self.assertTrue(set(terms).isdisjoint(tokens|schema))

    # Contracts/types: 12
    def test_001_status_domain(self):self.domain(Status,('SELECTED','NO_SELECTION','INDETERMINATE'))
    def test_002_reason_domain(self):self.domain(Reason,('INITIAL_SELECTION','UNCHANGED_SELECTION','HELD_PREVIOUS_NO_SELECTION','SWITCH_PENDING_MINIMUM_HOLD','SWITCH_PENDING_CONFIRMATION','SWITCH_CONFIRMED','PREVIOUS_OPTION_EXCLUDED','PREVIOUS_OPTION_ABSENT','CURRENT_ARBITER_INDETERMINATE','NO_CURRENT_SELECTION'))
    def test_003_policy_schema_frozen(self):
        self.assertEqual(tuple(f.name for f in fields(Policy)),('hysteresis_context_id','switch_policy_id','minimum_hold_ticks','challenger_confirmation_ticks'))
        with self.assertRaises(FrozenInstanceError):policy().minimum_hold_ticks=0
    def test_004_state_schema_frozen(self):
        self.assertEqual(tuple(f.name for f in fields(State)),('hysteresis_context_id','switch_policy_id','minimum_hold_ticks','challenger_confirmation_ticks','timeline_id','selected_clock_id','evaluated_at_tick','remembered_option_id','remembered_since_tick','effective_selected_option_id','effective_selected_option','pending_challenger_option_id','pending_challenger_since_tick','status','reason','current_arbiter_result_id','current_arbiter_result','previous_state_id','ruleset'))
        with self.assertRaises(FrozenInstanceError):step().reason=Reason.NO_CURRENT_SELECTION
    def test_005_policy_blank_ids(self):
        for field in ('hysteresis_context_id','switch_policy_id'):
            for bad in ('',' \t\n','\u2003'):
                with self.assertRaises(ValueError):replace(policy(),**{field:bad})
    def test_006_policy_exact_ids(self):
        class Text(str):pass
        for field in ('hysteresis_context_id','switch_policy_id'):
            for bad in (None,False,1,Text('x')):
                with self.assertRaises(ValueError):replace(policy(),**{field:bad})
    def test_007_threshold_exact_types(self):
        class Tick(int):pass
        for field in ('minimum_hold_ticks','challenger_confirmation_ticks'):
            for bad in (False,1.0,'1',None,Tick(1)):
                with self.assertRaises(TypeError):replace(policy(),**{field:bad})
    def test_008_threshold_nonnegative(self):
        for field in ('minimum_hold_ticks','challenger_confirmation_ticks'):
            with self.assertRaises(ValueError):replace(policy(),**{field:-1})
    def test_009_root_exact_types(self):
        for obj,kw in ((current(),'current_arbiter_result'),(policy(),'policy'),(step(),'previous_state')):
            child=type('Child',(type(obj),),{})(**{f.name:getattr(obj,f.name) for f in fields(obj)}) if not isinstance(obj,State) else object.__new__(type('Child',(State,),{}))
            for bad in ({},child):
                args=dict(current_arbiter_result=current(101),policy=policy(),previous_state=None);args[kw]=bad
                with self.assertRaises(TypeError):transition(**args)
    def test_010_builder_api(self):
        params=inspect.signature(transition).parameters
        self.assertEqual(tuple(params),('current_arbiter_result','policy','previous_state'))
        self.assertTrue(all(p.kind==p.KEYWORD_ONLY and p.default==p.empty for p in params.values()))
        with self.assertRaises(TypeError):transition(current(),policy(),None)
    def test_011_rulesets(self):
        self.assertEqual(step().ruleset,'selection.hysteresis.v1')
        for value in ('','decision.arbiter.v2',None):self.rejects(replace(current(),ruleset=value))
        self.rejects(current(101),forged(step(),ruleset='other'))
    def test_012_candidate_boundary(self):
        r=current();row=r.candidate_assessments[0]
        for bad in ([],tuple(r.candidate_assessments)*2,(object(),)):
            self.rejects(replace(r,candidate_assessments=bad))
        self.rejects(replace(r,considered_pairwise_evidence=[]))
        for field,bad in (('option_id',' '),('admission_status','ADMITTED'),('base_option_context',object())):
            self.rejects(replace(r,candidate_assessments=(replace(row,**{field:bad}),*r.candidate_assessments[1:])))

    # First state/same selection: 12
    def test_013_initial_selection(self):self.expected(step(),'INITIAL_SELECTION')
    def test_014_initial_no_selection(self):self.expected(step(current(status='NO_SELECTION')),'NO_CURRENT_SELECTION',None,None,None,status='NO_SELECTION')
    def test_015_initial_indeterminate(self):self.expected(step(current(status='INDETERMINATE')),'CURRENT_ARBITER_INDETERMINATE',None,None,None,status='INDETERMINATE')
    def test_016_initial_zero_tick(self):self.expected(step(current(0)),'INITIAL_SELECTION',since=0)
    def test_017_initial_zero_policy(self):self.expected(step(pol=policy(0,0)),'INITIAL_SELECTION')
    def test_018_initial_retains_result(self):
        r=current();s=step(r);self.assertIs(s.current_arbiter_result,r);self.assertEqual(s.current_arbiter_result_id,r.result_id);self.assertIsNone(s.previous_state_id)
    def test_019_same_selection(self):self.expected(step(current(101),step()),'UNCHANGED_SELECTION')
    def test_020_same_preserves_since(self):self.expected(step(current(10000),step()),'UNCHANGED_SELECTION')
    def test_021_same_clears_pending(self):self.expected(step(current(102),self.pending()),'UNCHANGED_SELECTION')
    def test_022_same_uses_current_object(self):
        old=step();new=step(current(101),old);self.assertIsNot(new.effective_selected_option,old.effective_selected_option);self.expected(new,'UNCHANGED_SELECTION')
    def test_023_reacquire_after_empty(self):
        s=step(current(status='NO_SELECTION'));self.expected(step(current(101),s),'INITIAL_SELECTION',since=101)
    def test_024_same_opaque_option(self):
        name=' Carry /ÃŽÂ² ';r=current(names=(name,),winner=name);s=step(r);self.expected(step(current(101,names=(name,),winner=name),s),'UNCHANGED_SELECTION',name,name)

    # NO_SELECTION/uncertainty/memory restoration: 16
    def test_025_no_selection_holds(self):self.expected(step(current(101,status='NO_SELECTION'),step()),'HELD_PREVIOUS_NO_SELECTION')
    def test_026_no_selection_keeps_since(self):self.expected(step(current(200,status='NO_SELECTION'),step()),'HELD_PREVIOUS_NO_SELECTION')
    def test_027_no_selection_clears_pending(self):self.expected(step(current(102,status='NO_SELECTION'),self.pending()),'HELD_PREVIOUS_NO_SELECTION')
    def test_028_no_selection_retains_original_result(self):
        r=current(101,status='NO_SELECTION');s=step(r,step());self.assertIs(s.current_arbiter_result,r);self.assertIs(r.status,DecisionArbiterStatus.NO_SELECTION)
    def test_029_indeterminate_hides_effective(self):self.expected(step(current(101,status='INDETERMINATE'),step()),'CURRENT_ARBITER_INDETERMINATE',None,'A',status='INDETERMINATE')
    def test_030_indeterminate_clears_pending(self):self.expected(step(current(102,status='INDETERMINATE'),self.pending()),'CURRENT_ARBITER_INDETERMINATE',None,'A',status='INDETERMINATE')
    def test_031_indeterminate_memory_admission_uncertain(self):self.expected(step(current(101,status='INDETERMINATE',uncertain=('A',)),step()),'CURRENT_ARBITER_INDETERMINATE',None,'A',status='INDETERMINATE')
    def test_032_repeated_uncertainty_preserves_memory(self):
        s=self.sequence([{},dict(tick=101,status='INDETERMINATE'),dict(tick=102,status='INDETERMINATE')]);self.expected(s,'CURRENT_ARBITER_INDETERMINATE',None,'A',status='INDETERMINATE')
    def test_033_restore_after_uncertainty(self):self.expected(self.sequence([{},dict(tick=101,status='INDETERMINATE'),dict(tick=102,status='NO_SELECTION')]),'HELD_PREVIOUS_NO_SELECTION')
    def test_034_same_after_uncertainty(self):self.expected(self.sequence([{},dict(tick=101,status='INDETERMINATE'),dict(tick=102)]),'UNCHANGED_SELECTION')
    def test_035_challenger_after_uncertainty(self):self.expected(self.sequence([{},dict(tick=101,status='INDETERMINATE'),dict(tick=102,winner='B')]),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=102)
    def test_036_uncertainty_resets_confirmation(self):
        s=self.sequence([{},dict(tick=101,winner='B'),dict(tick=102,status='INDETERMINATE'),dict(tick=110,winner='B')]);self.expected(s,'SWITCH_PENDING_CONFIRMATION',pending='B',pending_since=110)
    def test_037_hold_elapsed_includes_uncertain_gap(self):
        s=self.sequence([{},dict(tick=101,status='INDETERMINATE'),dict(tick=110,winner='B')],policy(10,0));self.expected(s,'SWITCH_CONFIRMED','B','B',110)
    def test_038_uncertain_without_memory_then_initial(self):
        s=step(current(status='INDETERMINATE'));self.expected(step(current(101),s),'INITIAL_SELECTION',since=101)
    def test_039_no_selection_without_memory(self):
        s=step(current(status='NO_SELECTION'));self.expected(step(current(101,status='NO_SELECTION'),s),'NO_CURRENT_SELECTION',None,None,None,status='NO_SELECTION')
    def test_040_malformed_unselected_arbiter(self):
        for status in ('NO_SELECTION','INDETERMINATE'):
            r=current(status=status)
            self.rejects(replace(r,selected_option_id='A'))
            self.rejects(replace(r,selected_option=r.candidate_assessments[0].base_option_context))

    # Challenger/thresholds: 18
    def test_041_challenger_starts(self):self.expected(self.pending(),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=101)
    def test_042_challenger_persists(self):self.expected(step(current(102,winner='B'),self.pending()),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=101)
    def test_043_challenger_changes(self):
        s=self.sequence([dict(names=('A','B','C')),dict(tick=101,names=('A','B','C'),winner='B'),dict(tick=102,names=('A','B','C'),winner='C')]);self.expected(s,'SWITCH_PENDING_MINIMUM_HOLD',pending='C',pending_since=102)
    def test_044_challenger_returns_to_previous(self):self.expected(step(current(102),self.pending()),'UNCHANGED_SELECTION')
    def test_045_hold_unsatisfied_confirmation_satisfied(self):self.expected(step(current(104,winner='B'),self.pending()),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=101)
    def test_046_hold_satisfied_confirmation_unsatisfied(self):self.expected(step(current(110,winner='B'),step()),'SWITCH_PENDING_CONFIRMATION',pending='B',pending_since=110)
    def test_047_both_satisfied(self):self.expected(step(current(110,winner='B'),self.pending()),'SWITCH_CONFIRMED','B','B',110)
    def test_048_hold_boundary_inclusive(self):self.expected(self.sequence([{},dict(tick=110,winner='B')],policy(10,0)),'SWITCH_CONFIRMED','B','B',110)
    def test_049_confirmation_boundary_inclusive(self):self.expected(step(current(104,winner='B'),self.pending(policy(0,3)),policy(0,3)),'SWITCH_CONFIRMED','B','B',104)
    def test_050_hold_one_tick_before(self):self.expected(self.sequence([{},dict(tick=109,winner='B')],policy(10,0)),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=109)
    def test_051_confirmation_one_tick_before(self):self.expected(step(current(103,winner='B'),self.pending(policy(0,3)),policy(0,3)),'SWITCH_PENDING_CONFIRMATION',pending='B',pending_since=101)
    def test_052_zero_both(self):self.expected(self.sequence([{},dict(tick=101,winner='B')],policy(0,0)),'SWITCH_CONFIRMED','B','B',101)
    def test_053_zero_hold_only(self):self.expected(self.pending(policy(0,3)),'SWITCH_PENDING_CONFIRMATION',pending='B',pending_since=101)
    def test_054_zero_confirmation_only(self):self.expected(self.pending(policy(10,0)),'SWITCH_PENDING_MINIMUM_HOLD',pending='B',pending_since=101)
    def test_055_confirmation_accumulates_during_hold(self):self.expected(step(current(110,winner='B'),self.pending()),'SWITCH_CONFIRMED','B','B',110)
    def test_056_switch_resets_hold_origin(self):
        s=step(current(110,winner='B'),self.pending());n=step(current(111),s);self.expected(n,'SWITCH_PENDING_MINIMUM_HOLD','B','B',110,'A',111)
    def test_057_sparse_tick_gap_is_allowed(self):self.expected(step(current(10000,winner='B'),self.pending()),'SWITCH_CONFIRMED','B','B',10000)
    def test_058_changed_challenger_no_inherited_time(self):
        s=self.sequence([dict(names=('A','B','C')),dict(tick=101,winner='B',names=('A','B','C')),dict(tick=110,winner='C',names=('A','B','C'))]);self.expected(s,'SWITCH_PENDING_CONFIRMATION',pending='C',pending_since=110)

    # Exclusion/absence: 12
    def test_059_excluded_selected_replacement(self):self.expected(self.released(),'PREVIOUS_OPTION_EXCLUDED','B','B',102)
    def test_060_excluded_no_selection(self):self.expected(self.released(status='NO_SELECTION'),'PREVIOUS_OPTION_EXCLUDED',None,None,None,status='NO_SELECTION')
    def test_061_excluded_indeterminate(self):self.expected(self.released(status='INDETERMINATE'),'PREVIOUS_OPTION_EXCLUDED',None,None,None,status='INDETERMINATE')
    def test_062_absent_selected_replacement(self):self.expected(self.released(True),'PREVIOUS_OPTION_ABSENT','B','B',102)
    def test_063_absent_no_selection(self):self.expected(self.released(True,'NO_SELECTION'),'PREVIOUS_OPTION_ABSENT',None,None,None,status='NO_SELECTION')
    def test_064_absent_indeterminate(self):self.expected(self.released(True,'INDETERMINATE'),'PREVIOUS_OPTION_ABSENT',None,None,None,status='INDETERMINATE')
    def test_065_exclusion_bypasses_hold(self):self.assertIs(self.released().reason,Reason.PREVIOUS_OPTION_EXCLUDED)
    def test_066_absence_bypasses_confirmation(self):self.assertIsNone(self.released(True).pending_challenger_option_id)
    def test_067_empty_universe_releases(self):self.expected(step(current(101,names=(),status='NO_SELECTION'),step()),'PREVIOUS_OPTION_ABSENT',None,None,None,status='NO_SELECTION')
    def test_068_all_excluded_clears(self):self.expected(step(current(101,excluded=('A','B'),status='NO_SELECTION'),step()),'PREVIOUS_OPTION_EXCLUDED',None,None,None,status='NO_SELECTION')
    def test_069_exclusion_after_uncertainty(self):
        s=self.sequence([{},dict(tick=101,status='INDETERMINATE')]);self.expected(step(current(102,winner='B',excluded=('A',)),s),'PREVIOUS_OPTION_EXCLUDED','B','B',102)
    def test_070_reappearance_after_absence_is_new(self):
        s=step(current(101,names=(),status='NO_SELECTION'),step());self.expected(step(current(102),s),'INITIAL_SELECTION',since=102)

    # Time/policy/continuity: 14
    def test_071_same_tick_rejected(self):self.rejects(current(),step())
    def test_072_backward_tick_rejected(self):self.rejects(current(99),step())
    def test_073_timeline_mismatch(self):self.rejects(current(101,timeline='other'),step())
    def test_074_clock_mismatch(self):self.rejects(current(101,clock='other'),step())
    def test_075_switch_policy_mismatch(self):self.rejects(current(101),step(),policy(identity='other'))
    def test_076_hysteresis_context_mismatch(self):self.rejects(current(101),step(),policy(context='other'))
    def test_077_hold_mismatch(self):self.rejects(current(101),step(),policy(11,3))
    def test_078_confirmation_mismatch(self):self.rejects(current(101),step(),policy(10,4))
    def test_079_new_policy_fresh_chain(self):
        s=step(current(101),pol=policy(20,7,context='new',identity='new-policy'));self.expected(s,'INITIAL_SELECTION',since=101)
    def test_080_decision_context_may_change(self):self.expected(step(current(101,context='another'),step()),'UNCHANGED_SELECTION')
    def test_081_source_ids_may_change(self):
        r=current(101);r=replace(r,feasibility_snapshot_id='other-feasibility',pairwise_snapshot_id='other-pairwise',base_request=replace(r.base_request,arbiter_context_id='other'))
        self.expected(step(r,step()),'UNCHANGED_SELECTION')
    def test_082_tick_type_and_negative(self):
        class Tick(int):pass
        for bad in (True,1.0,None,'101',Tick(101),-1):self.rejects(replace(current(),evaluated_at_tick=bad))
    def test_083_current_blank_ids(self):
        for field in ('decision_context_id','decision_context_object_id','feasibility_snapshot_id','pairwise_snapshot_id','timeline_id','selected_clock_id'):
            self.rejects(replace(current(),**{field:' '}))
    def test_084_previous_state_revalidated(self):
        s=step()
        changes=({'current_arbiter_result_id':'foreign'},{'evaluated_at_tick':99},{'remembered_since_tick':101},{'minimum_hold_ticks':True},
                 {'remembered_option_id':None},{'effective_selected_option':current().selected_option},{'previous_state_id':'bad'},
                 {'status':'SELECTED'},{'reason':'INITIAL_SELECTION'},{'pending_challenger_option_id':'A','pending_challenger_since_tick':100})
        for change in changes:self.rejects(current(101),forged(s,**change))

    # Identity/current objects/purity: 10
    def test_085_deterministic_id(self):self.assertEqual(step().state_id,step().state_id)
    def test_086_exact_identity_payload(self):
        s=self.pending();content={f.name:getattr(s,f.name) for f in fields(s) if f.name not in ('effective_selected_option','current_arbiter_result')}
        expected=hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8')).hexdigest()
        self.assertEqual(s.state_id,'selection.hysteresis.v1:state:'+expected)
    def test_087_lineage_id_only(self):
        p=step();s=step(current(101),p);self.assertEqual(s.previous_state_id,p.state_id);self.assertFalse(any(getattr(s,f.name) is p for f in fields(s)))
    def test_088_identity_policy_changes(self):
        r=current();self.assertNotEqual(step(r).state_id,step(r,pol=policy(11,3)).state_id)
    def test_089_identity_binds_current_result(self):
        r=current();s=step(r);self.assertNotEqual(s.state_id,step(replace(r,pairwise_snapshot_id='different')).state_id)
    def test_090_current_object_hold_and_restore(self):
        old=step();r=current(101,status='NO_SELECTION');s=step(r,old);self.assertIsNot(s.effective_selected_option,old.effective_selected_option)
        r2=current(103,status='NO_SELECTION');s2=step(r2,step(current(102,status='INDETERMINATE'),s));self.expected(s2,'HELD_PREVIOUS_NO_SELECTION')
    def test_091_current_object_switch_and_release(self):
        r=current(110,winner='B');s=step(r,self.pending());self.assertIs(s.effective_selected_option,r.selected_option)
        r=current(101,winner='B',excluded=('A',));self.assertIs(step(r,step()).effective_selected_option,r.selected_option)
    def test_092_pure_no_io_mutation(self):
        import builtins,io,os,socket,subprocess,time,random,uuid
        p=step();r=current(101,winner='B');pol=policy();before=tuple(asdict(x) for x in (p,r,pol));module=dict(vars(hysteresis));expected=step(r,p,pol).state_id
        with ExitStack() as stack:
            for owner,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),(subprocess,'Popen'),(time,'time'),(time,'monotonic'),(time,'sleep'),(random,'random'),(uuid,'uuid4')):
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('impure')))
            self.assertEqual(step(r,p,pol).state_id,expected)
        self.assertEqual(before,tuple(asdict(x) for x in (p,r,pol)));self.assertEqual(module,vars(hysteresis))
    def test_093_no_recursive_growth(self):
        s=step();counts=[]
        for tick in range(101,111):
            s=step(current(tick),s);counts.append(len(fields(s)));self.assertFalse(any(isinstance(getattr(s,f.name),State) for f in fields(s)))
        self.assertEqual(set(counts),{19})
    def test_094_state_optional_pairs_and_objects(self):
        s=step()
        for change in ({'remembered_since_tick':None},{'pending_challenger_option_id':'B'}, {'pending_challenger_since_tick':101},
                       {'remembered_since_tick':-1},{'effective_selected_option_id':'B'}, {'current_arbiter_result_id':'other'}):
            with self.assertRaises((TypeError,ValueError)):replace(s,**change)

    # Imports/preservation/boundaries: 10
    def test_095_exact_production_imports(self):
        source=inspect.getsource(hysteresis);path='coach02/selection_hysteresis_v01.py'
        self.assertEqual(reverse_violations(source,path),[]);self.assertEqual(import_violations(source,path),[]);self.assertEqual(consumer_violations(source,path),[])
        root=Path(hysteresis.__file__).resolve().parent
        for candidate in root.rglob('*.py'):
            self.assertEqual(reverse_violations(candidate.read_text(encoding='utf-8'),candidate.relative_to(root.parent).as_posix()),[],str(candidate))
        tree=ast.parse(source)
        self.assertEqual({a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names},{'hashlib','json'})
        self.assertEqual({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level},{'decision_arbiter_v01','decision_context_v02'})
    def test_096_reverse_guard_exact_path(self):
        for symbol in ('DecisionArbiterResultV1','DecisionArbiterStatus','ArbiterCandidateAdmissionStatus','ArbiterCandidateAssessmentV1'):
            good='from .decision_arbiter_v01 import '+symbol
            self.assertEqual(reverse_violations(good,'coach02/selection_hysteresis_v01.py'),[])
            self.assertTrue(reverse_violations(good,'coach02/arbitrary.py'))
    def test_097_reverse_guard_bad_imports(self):
        path='coach02/selection_hysteresis_v01.py'
        for bad in ('from .decision_arbiter_v01 import *','from .decision_arbiter_v01 import DecisionArbiterReason','from .decision_arbiter_v01 import build_decision_arbiter_result_v1','import coach02.decision_arbiter_v01','from .decision_arbiter_v01 import DecisionArbiterResultV1 as R','from .decision_arbiter_v01 import DecisionArbiterResultV1\nDecisionArbiterResultV1()','from .decision_arbiter_v01 import DecisionArbiterResultV1\nalias=DecisionArbiterResultV1',"__import__('coach02.decision_arbiter_v01')",'from .risk_evaluation import RiskConclusion'):
            self.assertTrue(reverse_violations(bad,path))
    def test_098_feasibility_guard_only_option_contract(self):
        good='from .decision_context_v02 import OptionDecisionContextV2';path='coach02/selection_hysteresis_v01.py'
        self.assertEqual(import_violations(good,path),[])
        for bad in (good+' as O',good+'\nOptionDecisionContextV2()',good+'\nalias=OptionDecisionContextV2','from .decision_context_v02 import DecisionContextV2','from .decision_context_v02 import *','import coach02.decision_context_v02','from .decision_arbiter_v01 import DecisionArbiterReason'):
            self.assertTrue(import_violations(bad,path))
        self.assertTrue(import_violations(good,'coach02/arbitrary.py'))
    def test_099_authority_boundaries(self):self.no_terms('Action','Execution','ExecutionState','Authority','Microplan','DIRECTIVE','ADVISORY','AWARENESS','SUPPRESS','commitment','reversibility','speech','urgency','output_authority','next_action')
    def test_100_no_lower_semantic_recomputation(self):self.no_terms('RiskConclusion','OptionSafetyGateStatus','FeasibilityGateStatus','PairwiseTradeoffConclusion','supported_risk_tolerance','base_risk_evaluation','base_feasibility_assessment','considered_pairwise_evidence_conclusion','_admission','_selection','_advantage')
    def test_101_documented_semantics_and_blockers(self):
        doc=(Path(hysteresis.__file__).resolve().parent.parent/'SELECTION_HYSTERESIS_V01.md').read_text(encoding='utf-8')
        for text in REQUIRED_DOC:self.assertIn(text,doc)
    def test_102_generic_opaque_roles(self):
        for name in ('Carry','Mid','Offlane','Support 4','Support 5',' farm:/ÃŽÂ² '):
            r=current(winner=name,names=(name,));s=step(r,pol=policy(context=' H ',identity=' P '));self.assertEqual(s.remembered_option_id,name);self.assertEqual(s.hysteresis_context_id,' H ')
    def test_103_no_automatic_reset_or_mutable_globals(self):
        self.rejects(current(101,timeline='different'),step())
        for name,value in vars(hysteresis).items():
            if not name.startswith('__'):self.assertNotIsInstance(value,(dict,list,set,bytearray))
        self.no_terms('uuid','random','time','sleep','thread','scheduler','asyncio','socket','open','getenv')
    def test_104_baseline_preservation_and_boundary_forgery(self):
        root=Path(hysteresis.__file__).resolve().parent.parent
        self.assertEqual(len(BASELINE_HASHES),136)
        for name,digest in BASELINE_HASHES:
            with self.subTest(name=name):self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),digest)
        r=current();self.rejects(replace(r,selected_option=replace(r.selected_option)))
        self.rejects(replace(r,status='SELECTED'))
        self.rejects(replace(r,selected_option_id='foreign'))
        row=r.candidate_assessments[0]
        self.rejects(replace(r,candidate_assessments=(replace(row,admission_status=ArbiterCandidateAdmissionStatus.INDETERMINATE),*r.candidate_assessments[1:])))


REQUIRED_DOC=(
    'Selection Hysteresis stabilizes selection; it does not execute decisions.',
    'Remembered selection is historical memory and may differ from effective current selection.',
    'Arbiter INDETERMINATE never exposes the remembered option as currently selected.',
    'NO_SELECTION may retain a previously stabilized option when that option remains ADMITTED.',
    'EXCLUDED or absent remembered options are released immediately and bypass switching thresholds.',
    'Normal switches require both minimum hold and challenger confirmation.',
    'Challenger confirmation measures persistence across supplied state transitions, not proof of continuity during omitted ticks.',
    'Ticks are opaque units in the selected clock domain, not seconds.',
    'No Safety, Feasibility or Pairwise semantics are recomputed.',
    'No action, lifecycle, commitment, Attention or communication authority occurs.',
    'BLOCKER_BEFORE_EXECUTION_LIFECYCLE','BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING',
    'BLOCKER_BEFORE_ATTENTION_GATE','BLOCKER_BEFORE_LIVE','ACCEPTED_V01_LIMITATION',
)

BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'),
 ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'),
 ('DECISION_ARBITER_V01.md', '85B662C99AF6BE245D01012D8121023D52F3B79E881EE2BAE29F3EF2E6F6991F'),
 ('DECISION_CONTEXT_V02.md', 'CB3F1615EC752ADF523DDFB7FA5F3C5A5ECE4EBB3E35E55C19C9449C649507F3'),
 ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'),
 ('FEASIBILITY_GATE_V01.md', '9F40450123FA2D511764617500433B90929E1AA90D854BD03A493BCF38A6BDB2'),
 ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md', '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'),
 ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'),
 ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'),
 ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'),
 ('OBJECTIVE_OUTCOME_RELATION_V01.md', 'C466F62DB319AFB730EC7ACE4FA67039ABD9A5D22F12CB5794DABDB05D73C7C6'),
 ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'),
 ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'),
 ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'),
 ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'),
 ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'),
 ('OPTION_OUTCOME_EVIDENCE_V01.md', '61D6DAD163B724E2EB9BD6859BBD476E828AC3574D32A3FDDEC7B58F3E7BC53A'),
 ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'),
 ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'),
 ('PAIRWISE_TRADEOFF_V01.md', '7290D806C360314C9771EDF208C5F0BDE7A204AD02663FD22C91EC890AB1E465'),
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
 ('coach02/decision_arbiter_v01.py', '39AC69E1A1164DD926C0735B8082FA9FC2F909140E125373427D80D2BAB02002'),
 ('coach02/decision_context_v02.py', '3F07B86C7FABA28118C87B9646D2094A3A7A65C531A9D07255CC0B25BB9D74EF'),
 ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'),
 ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'),
 ('coach02/feasibility_gate_v01.py', 'C1C9D6BB47622F880F98DA5783008F7350B332B2992876EF68D9CB87993A1E13'),
 ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'),
 ('coach02/objective_outcome_relation_v01.py', '4CE5B30CA77F480B4D7C1C601E92FB096585E73B348C0E6C13BA81CE9E27DA2B'),
 ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'),
 ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'),
 ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'),
 ('coach02/option_outcome_evidence.py', '04D5F650484CD7B067A410E6C7A37892CE054BCC1319835D2C948A0594CA0325'),
 ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'),
 ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'),
 ('coach02/pairwise_tradeoff_v01.py', '93F1DC3A7736D290C47A84F8F14776CE20370C225E6BA3C82C3B7BEF121631C3'),
 ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'),
 ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'),
 ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'),
 ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'),
 ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'),
 ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'),
 ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'),
 ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'),
 ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'),
 ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'),
 ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'),
 ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'),
 ('coach02/strategic_objective_context.py', '1C217907B23E50C76DB80ED16902A5FBFE58921F5458D3F789FC087987A22A44'),
 ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'),
 ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'),
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
 ('tests/test_decision_arbiter_v01.py', 'F24A7006527660AAD7C49FE87040330AF01571AF87D6FFE0AA717E4181EB2AEF'),
 ('tests/test_decision_context_v02.py', '100702613FFB1038A884C7CE9C7F3648B98C3CA8A7457A7A1ED5D6A25E4775D9'),
 ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'),
 ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'),
 ('tests/test_feasibility_gate_v01.py', '13C1E9585E67BD00E08D24DFF4E243488F4CA9A183B003061F71F472CB3C0DDC'),
 ('tests/test_missing_threat_resolver.py', '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'),
 ('tests/test_objective_outcome_relation_v01.py', '4E683FE4C0BEE3F44C37EA47930DF4278AB2315BE54F2D9B78416507F5A7CC7A'),
 ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'),
 ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'),
 ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'),
 ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'),
 ('tests/test_option_outcome_evidence.py', '650A4F6FD90A1163A8D7DBEED12EAF121F4AB265C07620A9224E2D099E3FE8E8'),
 ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'),
 ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'),
 ('tests/test_pairwise_tradeoff_v01.py', '6EE9F784F0E20280EA4BE2A035133D0A82B0684DB1BE0B25C6C030E3DE1B2F7B'),
 ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'),
 ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'),
 ('tests/test_risk_evidence_assembly_v02.py', 'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'),
 ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'),
 ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'),
 ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'),
 ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'),
 ('tests/test_strategic_objective_context.py', 'D9E4442199B6FCC7F6DFAF3E867C7C1CA13FB9FBF2BCC4BA5F2BDC2BC580EA18'),
 ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'),
 ('tests/test_threat_absence_observation.py', 'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'),
 ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'),
 ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'),
 ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'),
 ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'),
 ('tests/test_visibility_completeness.py', '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
