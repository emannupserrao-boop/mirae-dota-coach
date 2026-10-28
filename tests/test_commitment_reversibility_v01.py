"""Current execution evidence, adversarial binding and canonical preservation."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
import hashlib
import inspect
import json
from pathlib import Path
import unittest

from coach02 import commitment_reversibility_v01 as evidence
from coach02.commitment_reversibility_v01 import (
    ExecutionCommitmentLevel as C, ExecutionReversibilityLevel as R,
    ExecutionAssessmentPresence as Presence, ExecutionCommitmentClaimV1 as CC,
    ExecutionReversibilityClaimV1 as RC, ExecutionCommitmentAssessmentV1 as CA,
    ExecutionReversibilityAssessmentV1 as RA, ExecutionCommitmentReversibilitySnapshotV1 as Snapshot,
    build_execution_commitment_reversibility_snapshot_v1 as build,
)
from coach02.execution_lifecycle_v01 import ExecutionLifecycleStateV1 as State
from test_execution_lifecycle_v01 import register, known, advance, observation, hys, binding, Phase, Knowledge


def commitment(state=None, **changes):
    state = register() if state is None else state
    values = dict(commitment_context_id='commitment-context', execution_context_id=state.execution_context_id,
                  execution_instance_id=state.execution_instance_id, option_id=state.option_id,
                  lifecycle_state_id=state.state_id, assessed_at_tick=state.evaluated_at_tick,
                  commitment_level=C.SUBSTANTIAL, source_id='commitment-source',
                  evidence_refs=('commitment-b', 'commitment-a'), assessment_policy_id='commitment.policy.v1')
    values.update(changes)
    return CC(**values)


def reversibility(state=None, **changes):
    state = register() if state is None else state
    values = dict(reversibility_context_id='reversibility-context', execution_context_id=state.execution_context_id,
                  execution_instance_id=state.execution_instance_id, option_id=state.option_id,
                  lifecycle_state_id=state.state_id, assessed_at_tick=state.evaluated_at_tick,
                  reversibility_level=R.REVERSIBLE, source_id='reversibility-source',
                  evidence_refs=('reversibility-b', 'reversibility-a'), assessment_policy_id='reversibility.policy.v1')
    values.update(changes)
    return RC(**values)


def snapshot(state=None, c=None, r=None):
    return build(lifecycle_state=register() if state is None else state,
                 commitment_claim=c, reversibility_claim=r)


def forge(value, **changes):
    clone = replace(value)
    for name, content in changes.items():
        object.__setattr__(clone, name, content)
    return clone


def subclass_clone(value):
    cls = type('ForeignSubclass', (type(value),), {})
    clone = object.__new__(cls)
    for f in fields(value):
        object.__setattr__(clone, f.name, getattr(value, f.name))
    return clone


def independent_digest(kind, payload):
    data = dict(payload, ruleset='execution.commitment_reversibility.v1')
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return 'execution.commitment_reversibility.v1:' + kind + ':' + hashlib.sha256(encoded).hexdigest()


def dependency_violations(source, path):
    producer = path in (
        'coach02/commitment_reversibility_v01.py',
        'coach02/abort_cost_v01.py',
    )
    domain = 'execution_lifecycle_v01'
    allowed = {'ExecutionLifecycleStateV1', 'ExecutionLifecyclePhase', 'ExecutionKnowledgeStatus'}
    errors = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for a in node.names:
                if domain in a.name.split('.') or producer and (a.name not in ('hashlib', 'json') or a.asname):
                    errors.append('module/import')
        if isinstance(node, ast.ImportFrom):
            touches = domain in (node.module or '').split('.') or any(a.name == domain for a in node.names)
            if touches:
                exact = node.level == 1 and node.module == domain or node.level == 0 and node.module == 'coach02.' + domain
                if not producer or not exact or any(a.name not in allowed or a.asname for a in node.names):
                    errors.append('consumer/symbol/path')
            elif producer:
                permitted = {'dataclass'} if node.module == 'dataclasses' else {'Enum'} if node.module == 'enum' else set()
                if node.level or not permitted or any(a.name not in permitted or a.asname for a in node.names):
                    errors.append('earlier/other domain')
        if producer and isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Name) and node.value.id in allowed:
            errors.append('contract alias')
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if producer and name in allowed:
                errors.append('upstream constructor')
            if name in ('__import__', 'eval', 'exec') or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                if producer or any(isinstance(a, ast.Constant) and isinstance(a.value, str) and domain in a.value for a in node.args):
                    errors.append('dynamic import')
    return errors


class CommitmentReversibilityV1Tests(unittest.TestCase):
    def reject(self, fn, *args, **kwargs):
        with self.assertRaises((TypeError, ValueError)):
            fn(*args, **kwargs)

    def schema(self, cls, names):
        self.assertEqual(tuple(f.name for f in fields(cls)), tuple(names.split()))

    def bad_text(self, factory, names):
        class Text(str): pass
        for name in names.split():
            for bad in ('', ' \t\n', '\u2003', None, False, 1, Text('value')):
                with self.subTest(name=name, bad=bad): self.reject(factory, **{name:bad})

    def bad_tick(self, factory):
        class Tick(int): pass
        for bad in (-1, True, False, 1.0, None, '100', Tick(100)):
            self.reject(factory, assessed_at_tick=bad)

    def absent(self, row, enum):
        self.assertIs(row.presence, Presence.ABSENT)
        self.assertIs(row.conclusion, enum.INDETERMINATE)
        self.assertIsNone(row.base_claim)

    def both(self, state=None, c=C.SUBSTANTIAL, r=R.REVERSIBLE):
        state = register() if state is None else state
        return snapshot(state, commitment(state, commitment_level=c), reversibility(state, reversibility_level=r))

    def no_tokens(self, terms):
        tree = ast.parse(inspect.getsource(evidence))
        tokens = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertTrue(set(terms.split()).isdisjoint(tokens))

    # Enums/schemas/types/immutability: 12.
    def test_001_commitment_enum(self):
        names=('NOT_ESTABLISHED','LIMITED','SUBSTANTIAL','INDETERMINATE')
        self.assertEqual({k:v.value for k,v in C.__members__.items()}, {n:n for n in names})
    def test_002_reversibility_enum(self):
        names=('REVERSIBLE','CONSTRAINED','NOT_REVERSIBLE','INDETERMINATE')
        self.assertEqual({k:v.value for k,v in R.__members__.items()}, {n:n for n in names})
    def test_003_presence_enum(self):
        self.assertEqual({k:v.value for k,v in Presence.__members__.items()}, {'PRESENT':'PRESENT','ABSENT':'ABSENT'})
    def test_004_commitment_schema(self):
        self.schema(CC,'commitment_context_id execution_context_id execution_instance_id option_id lifecycle_state_id assessed_at_tick commitment_level source_id evidence_refs assessment_policy_id')
    def test_005_reversibility_schema(self):
        self.schema(RC,'reversibility_context_id execution_context_id execution_instance_id option_id lifecycle_state_id assessed_at_tick reversibility_level source_id evidence_refs assessment_policy_id')
    def test_006_commitment_assessment_schema(self):
        self.schema(CA,'lifecycle_state_id assessed_at_tick presence conclusion base_claim')
    def test_007_reversibility_assessment_schema(self):
        self.schema(RA,'lifecycle_state_id assessed_at_tick presence conclusion base_claim')
    def test_008_snapshot_schema(self):
        self.schema(Snapshot,'base_lifecycle_state commitment_assessment reversibility_assessment ruleset')
    def test_009_frozen_contracts(self):
        s=self.both()
        for value in (commitment(),reversibility(),s.commitment_assessment,s.reversibility_assessment,s):
            with self.assertRaises(FrozenInstanceError):setattr(value,fields(value)[0].name,'changed')
    def test_010_builder_signature(self):
        parameters=inspect.signature(build).parameters
        self.assertEqual(tuple(parameters),('lifecycle_state','commitment_claim','reversibility_claim'))
        for p in parameters.values():
            self.assertIs(p.kind,inspect.Parameter.KEYWORD_ONLY)
            self.assertIs(p.default,inspect.Parameter.empty)
        self.reject(build,register(),None,None)
        self.reject(build,lifecycle_state=register())
    def test_011_exact_lifecycle_type(self):
        for bad in (None,object(),{},subclass_clone(register())):
            self.reject(build,lifecycle_state=bad,commitment_claim=None,reversibility_claim=None)
    def test_012_exact_claim_types(self):
        for bad in (object(),reversibility(),subclass_clone(commitment())):self.reject(snapshot,c=bad)
        for bad in (object(),commitment(),subclass_clone(reversibility())):self.reject(snapshot,r=bad)

    # Claims/provenance: 18.
    def test_013_commitment_identifiers(self):
        self.bad_text(commitment,'commitment_context_id execution_context_id execution_instance_id option_id lifecycle_state_id source_id assessment_policy_id')
    def test_014_reversibility_identifiers(self):
        self.bad_text(reversibility,'reversibility_context_id execution_context_id execution_instance_id option_id lifecycle_state_id source_id assessment_policy_id')
    def test_015_commitment_tick(self):self.bad_tick(commitment)
    def test_016_reversibility_tick(self):self.bad_tick(reversibility)
    def test_017_commitment_level_exact(self):
        class Other(str,Enum): SUBSTANTIAL='SUBSTANTIAL'
        for bad in ('SUBSTANTIAL',R.REVERSIBLE,Other.SUBSTANTIAL,None,0):self.reject(commitment,commitment_level=bad)
    def test_018_reversibility_level_exact(self):
        class Other(str,Enum): REVERSIBLE='REVERSIBLE'
        for bad in ('REVERSIBLE',C.SUBSTANTIAL,Other.REVERSIBLE,None,0):self.reject(reversibility,reversibility_level=bad)
    def test_019_commitment_tuple_exact(self):
        class Refs(tuple): pass
        for bad in ([],['a'],'a',None,Refs(('a',))):self.reject(commitment,evidence_refs=bad)
    def test_020_reversibility_tuple_exact(self):
        class Refs(tuple): pass
        for bad in ([],['a'],'a',None,Refs(('a',))):self.reject(reversibility,evidence_refs=bad)
    def test_021_commitment_ref_text(self):
        class Text(str): pass
        for bad in ('',' ',None,False,1,Text('a')):self.reject(commitment,evidence_refs=(bad,))
    def test_022_reversibility_ref_text(self):
        class Text(str): pass
        for bad in ('',' ',None,False,1,Text('a')):self.reject(reversibility,evidence_refs=(bad,))
    def test_023_commitment_duplicate_refs(self):self.reject(commitment,evidence_refs=('a','a'))
    def test_024_reversibility_duplicate_refs(self):self.reject(reversibility,evidence_refs=('a','a'))
    def test_025_empty_refs_allowed(self):
        for factory in (commitment,reversibility):self.assertEqual(factory(evidence_refs=()).evidence_refs,())
    def test_026_order_and_object_preserved(self):
        refs=('z','a')
        for factory in (commitment,reversibility):self.assertIs(factory(evidence_refs=refs).evidence_refs,refs)
    def test_027_no_silent_trim(self):
        for factory in (commitment,reversibility):
            claim=factory(source_id=' source ',assessment_policy_id=' policy ',evidence_refs=(' ref ',))
            self.assertEqual((claim.source_id,claim.assessment_policy_id,claim.evidence_refs),(' source ',' policy ',(' ref ',)))
    def test_028_independent_provenance(self):
        s=self.both();c=s.commitment_assessment.base_claim;r=s.reversibility_assessment.base_claim
        self.assertNotEqual(c.commitment_context_id,r.reversibility_context_id)
        for name in ('source_id','evidence_refs','assessment_policy_id'):self.assertNotEqual(getattr(c,name),getattr(r,name))
    def test_029_forged_commitment_revalidated(self):
        changes=(dict(source_id=''),dict(assessed_at_tick=True),dict(commitment_level='SUBSTANTIAL'),dict(evidence_refs=['a']),dict(evidence_refs=('a','a')),dict(lifecycle_state_id='bad'))
        for change in changes:self.reject(snapshot,c=forge(commitment(),**change))
    def test_030_forged_reversibility_revalidated(self):
        changes=(dict(source_id=''),dict(assessed_at_tick=True),dict(reversibility_level='REVERSIBLE'),dict(evidence_refs=['a']),dict(evidence_refs=('a','a')),dict(lifecycle_state_id='bad'))
        for change in changes:self.reject(snapshot,r=forge(reversibility(),**change))

    # Absence/indeterminate/one-axis-only: 12.
    def test_031_not_started_empty(self):
        s=snapshot();self.absent(s.commitment_assessment,C);self.absent(s.reversibility_assessment,R)
    def test_032_in_progress_empty(self):
        s=snapshot(known());self.absent(s.commitment_assessment,C);self.absent(s.reversibility_assessment,R)
    def test_033_commitment_only(self):
        claim=commitment();s=snapshot(c=claim)
        self.assertIs(s.commitment_assessment.base_claim,claim);self.assertIs(s.commitment_assessment.conclusion,C.SUBSTANTIAL)
        self.absent(s.reversibility_assessment,R)
    def test_034_reversibility_only(self):
        claim=reversibility();s=snapshot(r=claim)
        self.assertIs(s.reversibility_assessment.base_claim,claim);self.assertIs(s.reversibility_assessment.conclusion,R.REVERSIBLE)
        self.absent(s.commitment_assessment,C)
    def test_035_explicit_commitment_indeterminate(self):
        claim=commitment(commitment_level=C.INDETERMINATE);row=snapshot(c=claim).commitment_assessment
        self.assertIs(row.presence,Presence.PRESENT);self.assertIs(row.base_claim,claim);self.assertIs(row.conclusion,C.INDETERMINATE)
    def test_036_explicit_reversibility_indeterminate(self):
        claim=reversibility(reversibility_level=R.INDETERMINATE);row=snapshot(r=claim).reversibility_assessment
        self.assertIs(row.presence,Presence.PRESENT);self.assertIs(row.base_claim,claim);self.assertIs(row.conclusion,R.INDETERMINATE)
    def test_037_both_explicit_indeterminate(self):
        s=self.both(c=C.INDETERMINATE,r=R.INDETERMINATE)
        self.assertIs(s.commitment_assessment.presence,Presence.PRESENT);self.assertIs(s.reversibility_assessment.presence,Presence.PRESENT)
    def test_038_absence_identity_distinct(self):
        ids={snapshot().snapshot_id,snapshot(c=commitment(commitment_level=C.INDETERMINATE)).snapshot_id,
             snapshot(r=reversibility(reversibility_level=R.INDETERMINATE)).snapshot_id,self.both(c=C.INDETERMINATE,r=R.INDETERMINATE).snapshot_id}
        self.assertEqual(len(ids),4)
    def test_039_absent_assessment_invariants(self):
        s=self.both()
        for row in (s.commitment_assessment,s.reversibility_assessment):
            self.reject(replace,row,presence=Presence.ABSENT)
            self.reject(replace,row,presence=Presence.ABSENT,base_claim=None)
    def test_040_present_requires_claim(self):
        s=self.both()
        for row in (s.commitment_assessment,s.reversibility_assessment):self.reject(replace,row,base_claim=None)
    def test_041_assessment_claim_binding(self):
        s=self.both()
        for row,level in ((s.commitment_assessment,C.LIMITED),(s.reversibility_assessment,R.CONSTRAINED)):
            for change in (dict(conclusion=level),dict(assessed_at_tick=101),dict(lifecycle_state_id='execution.lifecycle.v1:state:'+'0'*64),dict(presence='PRESENT')):
                self.reject(replace,row,**change)
    def test_042_snapshot_defensive_assessments(self):
        s=self.both()
        for change in (dict(ruleset='other'),dict(commitment_assessment=forge(s.commitment_assessment,conclusion=C.LIMITED)),
                       dict(reversibility_assessment=forge(s.reversibility_assessment,presence='PRESENT')),
                       dict(commitment_assessment=subclass_clone(s.commitment_assessment)),dict(base_lifecycle_state=known())):
            self.reject(replace,s,**change)

    # Eligibility/knowledge/terminality/selection: 18.
    def test_043_not_started_explicit_categories(self):
        for c in C:
            for r in R:self.assertIs(self.both(c=c,r=r).commitment_assessment.conclusion,c)
    def test_044_in_progress_explicit_categories(self):
        state=known()
        for c in C:
            for r in R:self.assertIs(self.both(state,c,r).reversibility_assessment.conclusion,r)
    def test_045_unknown_not_started_commitment(self):
        state=advance(register());self.assertIsNone(state.effective_phase)
        self.assertIs(snapshot(state,c=commitment(state)).commitment_assessment.conclusion,C.SUBSTANTIAL)
    def test_046_unknown_in_progress_commitment(self):
        state=advance(known(),tick=102)
        self.assertIs(state.knowledge_status,Knowledge.INDETERMINATE)
        self.assertIs(snapshot(state,c=commitment(state)).commitment_assessment.conclusion,C.SUBSTANTIAL)
    def test_047_effective_none_reversibility(self):
        state=advance(known(),tick=102);self.assertIsNone(state.effective_phase)
        self.assertIs(snapshot(state,r=reversibility(state,reversibility_level=R.CONSTRAINED)).reversibility_assessment.conclusion,R.CONSTRAINED)
    def test_048_completed_rejected(self):self.reject(snapshot,known(phase=Phase.COMPLETED))
    def test_049_aborted_rejected(self):self.reject(snapshot,known(phase=Phase.ABORTED))
    def test_050_expired_rejected(self):self.reject(snapshot,known(phase=Phase.EXPIRED))
    def test_051_terminal_claims_rejected(self):
        for phase in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):
            state=known(phase=phase);self.reject(snapshot,state,commitment(state),reversibility(state))
    def test_052_terminal_unknown_empty_rejected(self):
        for phase in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):self.reject(snapshot,advance(known(phase=phase),tick=102))
    def test_053_terminal_unknown_claims_rejected(self):
        for phase in (Phase.COMPLETED,Phase.ABORTED,Phase.EXPIRED):
            state=advance(known(phase=phase),tick=102);self.assertIsNone(state.effective_phase)
            self.reject(snapshot,state,commitment(state),reversibility(state))
    def test_054_selection_mismatch_valid(self):
        state=known(selected=hys(101,winner='B'));self.assertIs(state.selection_matches_execution,False)
        self.assertIs(self.both(state).base_lifecycle_state,state)
    def test_055_no_selection_valid(self):
        state=known(selected=hys(101,status='NO_SELECTION'));self.assertIsNone(state.current_selection_option_id)
        self.assertIs(self.both(state).base_lifecycle_state,state)
    def test_056_hysteresis_indeterminate_valid(self):
        state=known(selected=hys(101,status='INDETERMINATE'));self.assertIsNone(state.selection_matches_execution)
        self.assertIs(self.both(state).base_lifecycle_state,state)
    def test_057_matching_selection_valid(self):
        state=known();self.assertIs(state.selection_matches_execution,True);self.both(state)
    def test_058_multiple_instances_independent(self):
        first=register();second=register(bound=binding(execution_instance_id='instance-Y'))
        a=self.both(first);b=self.both(second)
        self.assertEqual(a.option_id,b.option_id);self.assertNotEqual(a.execution_instance_id,b.execution_instance_id)
        self.assertNotEqual(a.snapshot_id,b.snapshot_id);self.reject(snapshot,second,commitment(first))
    def test_059_upstream_objects_preserved(self):
        state=known();before=(state.state_id,repr(state));c=commitment(state);r=reversibility(state);s=snapshot(state,c,r)
        self.assertIs(s.base_lifecycle_state,state);self.assertIs(s.commitment_assessment.base_claim,c);self.assertIs(s.reversibility_assessment.base_claim,r)
        self.assertEqual((state.state_id,repr(state)),before)
    def test_060_malformed_lifecycle_rejected(self):
        state=known()
        changes=(dict(ruleset='other'),dict(timeline_id=''),dict(selected_clock_id=' '),dict(evaluated_at_tick=True),
                 dict(last_known_phase='IN_PROGRESS'),dict(knowledge_status='KNOWN'),dict(last_known_phase_recorded_at_tick=102),
                 dict(last_known_phase_observed_at_tick=100),dict(base_binding=forge(state.base_binding,source_id='')),
                 dict(base_binding=forge(state.base_binding,basis_tick=True)),dict(previous_state_id='bad'),
                 dict(timeline_id='foreign'),dict(current_observation=forge(state.current_observation,phase=Phase.NOT_STARTED)),
                 dict(base_binding=None),dict(current_hysteresis_state=None),dict(current_observation=object()))
        for change in changes:self.reject(snapshot,forge(state,**change))

    # Execution identity/exact tick: 12.
    def test_061_commitment_foreign_context(self):self.reject(snapshot,c=commitment(execution_context_id='foreign'))
    def test_062_commitment_foreign_instance(self):self.reject(snapshot,c=commitment(execution_instance_id='foreign'))
    def test_063_commitment_foreign_option(self):self.reject(snapshot,c=commitment(option_id='foreign'))
    def test_064_commitment_foreign_state(self):self.reject(snapshot,c=commitment(lifecycle_state_id='execution.lifecycle.v1:state:'+'0'*64))
    def test_065_reversibility_foreign_context(self):self.reject(snapshot,r=reversibility(execution_context_id='foreign'))
    def test_066_reversibility_foreign_instance(self):self.reject(snapshot,r=reversibility(execution_instance_id='foreign'))
    def test_067_reversibility_foreign_option(self):self.reject(snapshot,r=reversibility(option_id='foreign'))
    def test_068_reversibility_foreign_state(self):self.reject(snapshot,r=reversibility(lifecycle_state_id='execution.lifecycle.v1:state:'+'0'*64))
    def test_069_old_ticks_rejected(self):
        self.reject(snapshot,c=commitment(assessed_at_tick=99));self.reject(snapshot,r=reversibility(assessed_at_tick=99))
    def test_070_future_ticks_rejected(self):
        self.reject(snapshot,c=commitment(assessed_at_tick=101));self.reject(snapshot,r=reversibility(assessed_at_tick=101))
    def test_071_same_tick_foreign_lineage(self):
        state=register(bound=binding(source_id='other-registration'))
        self.assertEqual(state.evaluated_at_tick,register().evaluated_at_tick)
        self.reject(snapshot,state,commitment());self.reject(snapshot,state,r=reversibility())
    def test_072_no_carry_forward(self):
        state=register();prior=snapshot(state,c=commitment(state));later=advance(state)
        result=snapshot(later);self.assertIs(prior.commitment_assessment.conclusion,C.SUBSTANTIAL)
        self.absent(result.commitment_assessment,C);self.reject(snapshot,later,prior.commitment_assessment.base_claim)

    # No inference/all combinations: 8.
    def test_073_not_started_does_not_establish_low_commitment(self):
        self.absent(snapshot().commitment_assessment,C)
        self.assertIs(self.both(c=C.SUBSTANTIAL).commitment_assessment.conclusion,C.SUBSTANTIAL)
    def test_074_in_progress_does_not_establish_reversibility(self):
        state=known();self.absent(snapshot(state).reversibility_assessment,R)
        self.assertIs(self.both(state,r=R.REVERSIBLE).reversibility_assessment.conclusion,R.REVERSIBLE)
    def test_075_all_sixteen_combinations(self):
        results=set()
        for c in C:
            for r in R:
                s=self.both(c=c,r=r);results.add((s.commitment_assessment.conclusion,s.reversibility_assessment.conclusion))
        self.assertEqual(len(results),16)
    def test_076_substantial_reversible(self):
        s=self.both(c=C.SUBSTANTIAL,r=R.REVERSIBLE)
        self.assertEqual((s.commitment_assessment.conclusion,s.reversibility_assessment.conclusion),(C.SUBSTANTIAL,R.REVERSIBLE))
    def test_077_not_established_not_reversible(self):
        s=self.both(c=C.NOT_ESTABLISHED,r=R.NOT_REVERSIBLE)
        self.assertEqual((s.commitment_assessment.conclusion,s.reversibility_assessment.conclusion),(C.NOT_ESTABLISHED,R.NOT_REVERSIBLE))
    def test_078_indeterminate_does_not_spread(self):
        s=self.both(c=C.INDETERMINATE,r=R.REVERSIBLE)
        self.assertIs(s.reversibility_assessment.conclusion,R.REVERSIBLE)
        s=self.both(c=C.SUBSTANTIAL,r=R.INDETERMINATE);self.assertIs(s.commitment_assessment.conclusion,C.SUBSTANTIAL)
    def test_079_policy_is_not_configuration(self):
        for policy in ('policy.A','policy.B','0','999','RETREAT'):
            s=snapshot(c=commitment(assessment_policy_id=policy),r=reversibility(assessment_policy_id=policy))
            self.assertIs(s.commitment_assessment.conclusion,C.SUBSTANTIAL);self.assertIs(s.reversibility_assessment.conclusion,R.REVERSIBLE)
    def test_080_option_is_opaque(self):
        for option in ('opaque','SUPPORT_5',' gold ','123'):
            selected=hys(names=(option,),winner=option);state=register(selected,binding(selected,option_id=option))
            self.assertEqual(self.both(state).option_id,option)

    # Deterministic identity: 10.
    def test_081_commitment_identity_vector(self):
        claim=commitment();payload={f.name:getattr(claim,f.name) for f in fields(claim)}
        self.assertEqual(claim.claim_id,independent_digest('commitment',payload));self.assertEqual(claim.claim_id,commitment().claim_id)
    def test_082_reversibility_identity_vector(self):
        claim=reversibility();payload={f.name:getattr(claim,f.name) for f in fields(claim)}
        self.assertEqual(claim.claim_id,independent_digest('reversibility',payload));self.assertEqual(claim.claim_id,reversibility().claim_id)
    def test_083_commitment_ref_order_changes_identity(self):
        self.assertNotEqual(commitment(evidence_refs=('a','b')).claim_id,commitment(evidence_refs=('b','a')).claim_id)
    def test_084_reversibility_ref_order_changes_identity(self):
        self.assertNotEqual(reversibility(evidence_refs=('a','b')).claim_id,reversibility(evidence_refs=('b','a')).claim_id)
    def changed_identity(self,claim,level_name,level):
        for f in fields(claim):
            value=getattr(claim,f.name)
            replacement=(level if f.name==level_name else 101 if f.name=='assessed_at_tick' else ('new-ref',) if f.name=='evidence_refs'
                         else 'execution.lifecycle.v1:state:'+'0'*64 if f.name=='lifecycle_state_id' else value+'.different')
            self.assertNotEqual(claim.claim_id,replace(claim,**{f.name:replacement}).claim_id,f.name)
    def test_085_commitment_binds_every_field(self):self.changed_identity(commitment(),'commitment_level',C.LIMITED)
    def test_086_reversibility_binds_every_field(self):self.changed_identity(reversibility(),'reversibility_level',R.CONSTRAINED)
    def test_087_snapshot_identity_vector(self):
        s=self.both();c=s.commitment_assessment;r=s.reversibility_assessment
        payload=dict(lifecycle_state_id=s.lifecycle_state_id,execution_context_id=s.execution_context_id,execution_instance_id=s.execution_instance_id,
                     option_id=s.option_id,timeline_id=s.timeline_id,selected_clock_id=s.selected_clock_id,assessed_at_tick=s.assessed_at_tick,
                     commitment_presence=c.presence,commitment_conclusion=c.conclusion,commitment_claim_id=c.base_claim.claim_id,
                     reversibility_presence=r.presence,reversibility_conclusion=r.conclusion,reversibility_claim_id=r.base_claim.claim_id)
        self.assertEqual(s.snapshot_id,independent_digest('snapshot',payload))
    def test_088_unicode_and_whitespace_identity(self):
        a=commitment(source_id=' fonte\u2603 ');b=commitment(source_id='fonte\u2603')
        self.assertNotEqual(a.claim_id,b.claim_id)
        self.assertEqual(a.claim_id,independent_digest('commitment',{f.name:getattr(a,f.name) for f in fields(a)}))
    def test_089_snapshot_identity_axes_and_lineage(self):
        first=self.both();different=self.both(c=C.LIMITED)
        later=self.both(known())
        self.assertEqual(len({first.snapshot_id,different.snapshot_id,later.snapshot_id,snapshot().snapshot_id}),4)
    def test_090_snapshot_properties_and_no_recursive_identity(self):
        s=self.both();state=s.base_lifecycle_state
        for name in ('execution_context_id','execution_instance_id','option_id','timeline_id','selected_clock_id'):
            self.assertEqual(getattr(s,name),getattr(state,name))
        self.assertEqual(s.lifecycle_state_id,state.state_id);self.assertEqual(s.assessed_at_tick,state.evaluated_at_tick)
        source=inspect.getsource(Snapshot.snapshot_id.fget)
        self.assertNotIn('asdict',source);self.assertNotIn('previous_state',source)

    # Purity/guards/boundaries/preservation: 14.
    def test_091_exact_import_surface(self):
        tree=ast.parse(inspect.getsource(evidence));actual=[]
        for n in tree.body:
            if isinstance(n,ast.ImportFrom):actual.append((n.level,n.module,tuple(a.name for a in n.names)))
            elif isinstance(n,ast.Import):actual.extend((0,a.name,()) for a in n.names)
        self.assertEqual(actual,[(0,'dataclasses',('dataclass',)),(0,'enum',('Enum',)),(0,'hashlib',()),(0,'json',()),
                                 (1,'execution_lifecycle_v01',('ExecutionLifecycleStateV1','ExecutionLifecyclePhase','ExecutionKnowledgeStatus'))])
    def test_092_producer_guard(self):
        self.assertEqual(dependency_violations(inspect.getsource(evidence),'coach02/commitment_reversibility_v01.py'),[])
    def test_093_reverse_guard_canonical_tree(self):
        root=Path(evidence.__file__).resolve().parent
        for path in root.glob('*.py'):
            self.assertEqual(dependency_violations(path.read_text(encoding='utf-8-sig'),'coach02/'+path.name),[],path.name)
    def test_094_foreign_consumers_rejected(self):
        for symbol in ('ExecutionLifecycleStateV1','ExecutionLifecyclePhase','ExecutionKnowledgeStatus'):
            self.assertTrue(dependency_violations('from .execution_lifecycle_v01 import '+symbol,'coach02/foreign.py'))
    def test_095_import_forms_rejected(self):
        sources=('import coach02.execution_lifecycle_v01','from .execution_lifecycle_v01 import *',
                 'from .execution_lifecycle_v01 import ExecutionLifecycleStateV1 as State',
                 'from coach02 import execution_lifecycle_v01','from .execution_lifecycle_v01 import build_execution_lifecycle_state_v1',
                 'from .execution_lifecycle_v01 import _state','from .selection_hysteresis_v01 import SelectionHysteresisStateV1')
        for source in sources:self.assertTrue(dependency_violations(source,'coach02/commitment_reversibility_v01.py'),source)
    def test_096_dynamic_alias_constructor_rejected(self):
        sources=('__import__("coach02.execution_lifecycle_v01")','importlib.import_module("coach02.execution_lifecycle_v01")',
                 'ExecutionLifecycleStateV1()','State = ExecutionLifecycleStateV1','eval("1")','exec("x=1")')
        for source in sources:self.assertTrue(dependency_violations(source,'coach02/commitment_reversibility_v01.py'),source)
    def test_097_no_action_or_ranking(self):
        self.no_tokens('should_switch should_hold switch_allowed continue_execution abort_execution switchability stickiness priority utility score winner rank select_option start_execution complete_execution')
    def test_098_no_attention(self):self.no_tokens('DIRECTIVE ADVISORY AWARENESS SUPPRESS urgency voice repetition output_authority')
    def test_099_no_microplan(self):self.no_tokens('route waypoint target movement spell_order item_order action_sequence microplan')
    def test_100_no_memory_or_cost(self):
        for cls in (CC,RC,CA,RA,Snapshot):
            self.assertTrue({'previous_state_id','previous_snapshot','abort_cost','switch_cost','sunk_cost','score'}.isdisjoint(f.name for f in fields(cls)))
        self.no_tokens('AbortCostEvidence SwitchCostEvidence SunkCostEvidence previous_snapshot')
    def test_101_pure_repeated_calls(self):
        state=known();c=commitment(state);r=reversibility(state)
        ids={snapshot(state,c,r).snapshot_id for _ in range(10)};self.assertEqual(len(ids),1)
        self.no_tokens('sleep time monotonic perf_counter scheduler Thread socket open Path uuid random asyncio')
        self.assertFalse(any(isinstance(n,(ast.AsyncFunctionDef,ast.Await)) for n in ast.walk(ast.parse(inspect.getsource(evidence)))))
    def test_102_canonical_142_hashes(self):
        root=Path(evidence.__file__).resolve().parent.parent;self.assertEqual(len(BASELINE_HASHES),142)
        for name,digest in BASELINE_HASHES:
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest().upper(),digest,name)
    def test_103_new_files_lf_and_finite_surface(self):
        root=Path(evidence.__file__).resolve().parent.parent
        for name in ('COMMITMENT_REVERSIBILITY_V01.md','coach02/commitment_reversibility_v01.py','tests/test_commitment_reversibility_v01.py'):
            raw=(root/name).read_bytes();self.assertNotIn(b'\r',raw);self.assertTrue(raw.endswith(b'\n'))
        public_classes={n for n,v in vars(evidence).items() if isinstance(v,type) and v.__module__==evidence.__name__ and not n.startswith('_')}
        self.assertEqual(public_classes,{'ExecutionCommitmentLevel','ExecutionReversibilityLevel','ExecutionAssessmentPresence',
                         'ExecutionCommitmentClaimV1','ExecutionReversibilityClaimV1','ExecutionCommitmentAssessmentV1',
                         'ExecutionReversibilityAssessmentV1','ExecutionCommitmentReversibilitySnapshotV1'})
    def test_104_documented_boundaries(self):
        doc=(Path(evidence.__file__).resolve().parent.parent/'COMMITMENT_REVERSIBILITY_V01.md').read_text(encoding='utf-8')
        for marker in ('BLOCKER_BEFORE_ABORT_SWITCH_COST','BLOCKER_BEFORE_EXECUTION_AWARE_SWITCHING',
                       'BLOCKER_BEFORE_MICROPLAN','BLOCKER_BEFORE_ATTENTION_GATE','BLOCKER_BEFORE_LIVE'):
            self.assertIn(marker,doc)


# Populated from the independently recorded pre-feature manifest before installation.
BASELINE_HASHES = (('.gitignore', 'F94F5CED60E70516ABA3474BB107EFBD79AFA8A3708263529DB1CC5CEF5142C1'), ('CONTEXT_BUILDER_V01.md', '961B768BC012415D7DAE3C485FF74CDD4663FC50BDECD127A111A04CB43CC235'), ('DECISION_ARBITER_V01.md', '85B662C99AF6BE245D01012D8121023D52F3B79E881EE2BAE29F3EF2E6F6991F'), ('DECISION_CONTEXT_V02.md', 'CB3F1615EC752ADF523DDFB7FA5F3C5A5ECE4EBB3E35E55C19C9449C649507F3'), ('EXECUTION_LIFECYCLE_V01.md', 'F46C02CBB3B6A75BBD043F7F91F7B014E2936AB86244667A17A3298788C0C91F'), ('FARM_CONTEXT_COMPOSITION_V01.md', '344DB186DD48AD1FF0D94D3D787A4A69FDD90B59ADDE452E601C8031F4B1D6E9'), ('FEASIBILITY_GATE_V01.md', '9F40450123FA2D511764617500433B90929E1AA90D854BD03A493BCF38A6BDB2'), ('GIT_BOOTSTRAP_CANONICAL_FREEZE_V01.md', '5936535803010432064E527B43B0F06703512408261C9D94E0EF2057875C2EC2'), ('Install.cmd', 'A04A07E98E7795B3325E3C3D78FC05C11421B9F76044F8FA37D5B4FCEA5C3CE3'), ('LEIA_PRIMEIRO.txt', 'F39C08C68A997DBE53371D43183A107CF3ABFF2585C914459661C1184C2DD8E4'), ('MISSING_THREAT_RESOLVER_V01.md', '3FCD91DE4FF005173F7461A049F9B66A9E4A7039703157AE4C1373E14B6BC9BF'), ('OBJECTIVE_OUTCOME_RELATION_V01.md', 'C466F62DB319AFB730EC7ACE4FA67039ABD9A5D22F12CB5794DABDB05D73C7C6'), ('OBSERVATION_EVENT_FOUNDATION_V01.md', 'B198EAB49761C3533A6D9449783A96DA481817B66984BE09BE6C50980D0697A9'), ('OFFLINE_CARRY_FARM_CYCLE.md', 'DE6647FE15C167F0DBF2FA3EB63286FC686044C82A94FA6F8151BD4E369A3658'), ('OFFLINE_CORE_V01.md', '082F087D423A109C8F36EE7BB1718476476A156F0B0A695E4A68A6959F381FBB'), ('OPTION_AVAILABILITY_V01.md', 'E2BC42B9C804CDFF9CF3A040549E43635F58675F849511EFA48F2FD8AC94EC98'), ('OPTION_EXPOSURE_V01.md', '634DBDF0CE9ED900521372F7681F2AA97660FBF937D52197C0CDD736DE86AE4A'), ('OPTION_OUTCOME_EVIDENCE_V01.md', '61D6DAD163B724E2EB9BD6859BBD476E828AC3574D32A3FDDEC7B58F3E7BC53A'), ('OPTION_SAFETY_V01.md', '6BA0C710FAD0A78E01D2F630A4E4A163663ECFF6BAD5F300724AF253C05CB8AA'), ('OPTION_SAFETY_V02.md', '6B28E04F8EFFD47B8772B11D470E4914DF4560D25DC44AD9A6869EAF2D65C7B9'), ('PAIRWISE_TRADEOFF_V01.md', '7290D806C360314C9771EDF208C5F0BDE7A204AD02663FD22C91EC890AB1E465'), ('README.md', '72A60A5815269D2B2EAED3119841A4D57D26E6564F56BE104C6766F2FAAEF674'), ('RISK_EVALUATION_V01.md', '7A13246FD6D31A4A58C22AA9C1D209FF40727D79C8E90339620EDFDF2A878C32'), ('RISK_EVIDENCE_ASSEMBLY_V01.md', 'D44F8700089A390AC5CF6C670A78481A7340CF84A98A4766D194BF1D821B28B6'), ('RISK_EVIDENCE_ASSEMBLY_V02.md', '60A9C3B76C42C19B42EE94DA50A3A6C7E85400398502117200B3BF4F388D4D76'), ('RUNTIME_ADAPTER_V01.md', '723B87C9FA564CCB0527D6647F66D9752DA127082910C415D10838449E0051AE'), ('Run-Tests.cmd', 'C7D36F01B393C13362D8C6FB35D6C5FFDB9A81DC7AE086B61DE723974240136A'), ('SAFETY_EVIDENCE_V01.md', '160811B5829650324AD3353DD89C85ABAB878D3465B9261D0AFE840F284A8978'), ('SELECTION_HYSTERESIS_V01.md', '7A481B26A5AEAAB72B9664403CA566CFC28EE61DD8C585FD1566FA09F41D2E60'), ('STRATEGIC_COVERAGE_V01.md', '70AB604B5F34613F0BB306CC7E48FFB95CE1CA5419DB38427B91E8D4A8FB9181'), ('STRATEGIC_EVIDENCE_ASSEMBLY_V01.md', 'E2918BA287987AE36DF60BAD083CC45726998CFA97F082A626EB103D2F76FADD'), ('STRATEGIC_OBJECTIVE_CONTEXT_V01.md', 'CC437194EA74D601D78E3BAEC613D0376E0759690A74BB02EF94DA910916B3E7'), ('Start-Bot-Test.cmd', 'A967FFFC010A28FB3957C86B8B2AAF5DA7E98B40BA645B4DE63464FDBF3A11A4'), ('Start-Coach.cmd', '400EF821414BC0036D0BD29ED6382CDCC3477147604DAFCFAE488C7E329A8123'), ('TEMPORAL_EVIDENCE_V01.md', 'CFDE8BB450A5B864B652B9291329F36D538C90164DF0D2C6EC34853669AC918B'), ('THREAT_ABSENCE_OBSERVATION_V01.md', '6A37416C544E27A08DB0B8B1BC4D2D07136C833DE0A8674DD17EC79D9F9F0952'), ('THREAT_OBSERVATION_V01.md', '4633E7C0E920F790605DA27635A8D84ACA38DE59A52485CF16DEF1C7EDB8327B'), ('THREAT_REACHABILITY_V01.md', '180A3F7995AD367FD62DFCAA2175C03C6E1940C6C4BCFE80BF05C575DF0F2D42'), ('THREAT_RELEVANCE_V01.md', '51F9BEB03B612559A8EA350AB4C9FF5438C05A40EEAE5798CD40B5D1AD069666'), ('THREAT_STATE_ASSEMBLY_V01.md', 'CD7DDFAAFDBBA7A295616A1820FC267F46651C8B3AEB9ED445532B5C48E9766A'), ('VISIBILITY_COMPLETENESS_V01.md', 'E79A0B25695A39529E324F18792CA9C4CD31BDEB8EF8548C3FD351BB3DAFA7B3'), ('coach/__init__.py', '7F11EA1BB3CE6C0337E4BE363DB8E42212DB7162035F0C5E7B5C35EC83EE51FC'), ('coach/config.py', '65D00A6D83DD08CDA8FC3B187C355EC32CBC4F6A1DE07187B7E862C4D64619FD'), ('coach/demo.py', '3BD8D9895B298A85BD5FCFCCDC750CFD41641548B8EEE717571002386CC5E329'), ('coach/gsi.py', 'FBA76A32938890A48277003F156AA9B660668C623B0EC547BBA5AC36DFA876BD'), ('coach/process.py', '365F1B2FE34F5EDAF100801DC410907F2B2E93100DC97C8F13E1B8FB2C4FDD75'), ('coach/rules.py', '4F8D13C4CE767EBA8CCC5C678A6A3403C52054513ACFE1ACC6C8FE6410884B01'), ('coach/service.py', '5F6578DF02FD8217E01EC218B6C75A28B720D4C81786C61EE39893D8D257539C'), ('coach/state.py', '35CEC08572B1E6B3E64105BC5AC54CE609D4A690C5A8A40A21782D6C9B6A78D5'), ('coach/storage.py', '670991046FC26DF49675CB0A586FE3DED55802789521E983745CDEBDC521BC24'), ('coach/ui.py', '18FB3ECFFFA46FED5351E0F8BCD257758A1DA6BBE9D7978A2400D8E05070DBD6'), ('coach/voice.py', '8DAB5D562017EC9391FB6CE8E7FFE214873DF8FE9E7FAA53F03C8EFD85C692F8'), ('coach02/__init__.py', '1551CF04691F85B4038BFCF7BF43E2289AD75EA5CEC74BC65BFD556AA3498BB5'), ('coach02/config.py', 'E49E6E0BE1CE00042E5504A940F284A0ECD89E381B054C007EAB79C38C3A7A4D'), ('coach02/context_builder.py', '066A5F31289C4DA0912F9177939764A6242E90BAB46E138E927F6422976E7D13'), ('coach02/decision.py', 'E45BA2CEF8ED853FEF484D8D3E82F0CDF4F7B7EFAA2EFFDD1AA878D7ACEE1ACD'), ('coach02/decision_arbiter_v01.py', '39AC69E1A1164DD926C0735B8082FA9FC2F909140E125373427D80D2BAB02002'), ('coach02/decision_context_v02.py', '3F07B86C7FABA28118C87B9646D2094A3A7A65C531A9D07255CC0B25BB9D74EF'), ('coach02/execution_lifecycle_v01.py', 'B531F3D856BD0FF0898A25972A9AE5363EA8DFCA9C5F97F15C7C16778AAF7CA4'), ('coach02/farm_context.py', 'F3FAE234E7EBA3B0459BC1EDF55ECBECC1A710DB8C4E2EFCAA5CB24C95C9121E'), ('coach02/farm_cycle.py', 'B5333A79B3CD406B68D1D8161BBEF29DEFF028841C43AC542608D3B281C325FD'), ('coach02/feasibility_gate_v01.py', 'C1C9D6BB47622F880F98DA5783008F7350B332B2992876EF68D9CB87993A1E13'), ('coach02/missing_threat_resolver.py', '70226C19B5565835D68CBC44C0227FA80FD317A3DE81D932E35CE64F01977246'), ('coach02/objective_outcome_relation_v01.py', '4CE5B30CA77F480B4D7C1C601E92FB096585E73B348C0E6C13BA81CE9E27DA2B'), ('coach02/observation_event.py', 'BBC1D4D0CE0D19AC16C6F3DEB482148AF2A06AD2D503620CC0756B4F32E83355'), ('coach02/option_availability.py', 'E2B67B8BD853B44C96A0E6E9D2A05DDE8E3D6F93EAA2AE1B0C5121A646597494'), ('coach02/option_exposure.py', '3BCBEBEAE0778A4A33E7B627B023ED3750D3D4CDB642A39F73F4F4FC10679B63'), ('coach02/option_outcome_evidence.py', '04D5F650484CD7B067A410E6C7A37892CE054BCC1319835D2C948A0594CA0325'), ('coach02/option_safety.py', '05AD27E08457D6FAA4233A50E084FF63B001B9410349E5810454C30D623D537C'), ('coach02/option_safety_v02.py', 'C6773E48AFD0316D6C5EA145DF6048372320FF0FDF7E11ED93367E19BA244E0D'), ('coach02/pairwise_tradeoff_v01.py', '93F1DC3A7736D290C47A84F8F14776CE20370C225E6BA3C82C3B7BEF121631C3'), ('coach02/performance.py', '7063AE12BB02D667490E3C66905287AECC2DC03C32A35CD371A1FF667B2E021D'), ('coach02/policy.py', '9F3DEC983A575F05E781A0DD1C84038D5010455DA8BF5AABE346FCFD7071C9E8'), ('coach02/risk_evaluation.py', 'B177EA4038B91BD5596D7197CB8BDCCC465E69AFB284E3E9F6EA93A8CFC8349C'), ('coach02/risk_evidence_assembly.py', '6565C749DA69327ACF64D684AF4CB9855E86782DE2934BE6CF46E56EF72228B7'), ('coach02/risk_evidence_assembly_v02.py', '3F3A1E76B2D4137A44006957764DA4313392FC9D9BB528EFB5E6DC759A26B694'), ('coach02/rules.py', '9ABCBCD0157CA211C2E5E89C8E822A79AADCB085021CC58703A6134D181F1E64'), ('coach02/runtime_adapter.py', '586688C9E7A18976E45F485FB1E5635AAF9A93126FA4F929CEFA1E355244678B'), ('coach02/safety_evidence.py', 'E76250BE983D24D1B9C93F09F224D0AFE8D2E20DBCEF86FBBD430E2FC8335199'), ('coach02/selection_hysteresis_v01.py', '68E233D8617750AEC3C1A1BF7EAE16BDDBBD5F7779C47DC270400E47D0699576'), ('coach02/service.py', '4436D6B5B3B9356B80F519552E2695E0222899F2AD7A8B23BE663C8867B31E15'), ('coach02/storage.py', '31813F289FEE04211B24AF3CE722C6241F0490E201513B89DC4BE21B55EFEAB3'), ('coach02/strategic_coverage.py', '4BEF8DF8213923AC2DFBB9D5842D4848FD583A422254ADF1758C62C546F9723C'), ('coach02/strategic_evidence.py', 'CEEA78C1A1A6410D7BF2F9123F4990E1E2AA61486674DA94A9C223AFB8E641D5'), ('coach02/strategic_objective_context.py', '1C217907B23E50C76DB80ED16902A5FBFE58921F5458D3F789FC087987A22A44'), ('coach02/temporal_evidence.py', 'D6D1E0EBFB262148F484623FAD66AD5748AB564E641FE94A0CCAECF185FCCC57'), ('coach02/threat_absence_observation.py', '644F989186BEE0ED458C63CAEA25B07D3A6F093F0B439B864599E3F25E9FBB4A'), ('coach02/threat_observation.py', '06C4401DF74367BCD7B7707E9F516F884E11891CFDFE70CE5A89324CEE1BBC1C'), ('coach02/threat_reachability.py', '8BFFC4E53FA87CD434BDC223F76B6B4D01412E7307570B3E440E85B39F278BF0'), ('coach02/threat_relevance.py', '4545311E85BFF955693C3B365A447BFEBD5698DC8FE39BC47AE3CD3741CE70F9'), ('coach02/threat_state_assembly.py', '448EF3128389B9B09D46F7F8FCD8C71F206E08F65BAAD52027773923C8E7AD8B'), ('coach02/ui.py', '83A0E099A80E8F28AF5263DCE3DFD1AF580133646C6391125FA330EFB08B2B89'), ('coach02/visibility_completeness.py', 'F25FD4154C0CDCF54E2C431AB80C99300ACDFEF5FDC1EB10FD333F201F9357BF'), ('coach02/vision.py', '5763212EF319CCC9D4EF0663C276FDBF637A72580246AFE8D2DFFDB1BC3C7873'), ('coach02/voice.py', 'FFEBBEB5F6218D30E02F49B4745023A8F6106F280F86D0EA3083F00C0457DAC1'), ('docs/CHANGES.md', 'A2DBFDAE75A11C1CFD601269E677D6F73F72A6017006D235AAD527A22F26BD9A'), ('docs/DECISIONS.md', '35C72BB38D35D8EE6A804BE9F3631047FB68E4A8E9538908F2259CD3917FB14A'), ('docs/TESTE_REAL.md', '335EC57D975ADB1FD046A358975DDF8831B67BC1F183C1AB4E576DAD675C06A8'), ('docs/VALIDATION.md', '7D5D0E515DE4D46E158DD955B2422F4B997A99000FCB531F61272FB06079A9C5'), ('docs/alpha01-reference/DECISIONS.md', '83D8C8EDD6386C958CB5A770746A1B7016C355596985DB44646EFF0B9ADA7571'), ('docs/alpha01-reference/VALIDATION.md', 'F29B09DD7427543EDA767B0FDBE68033C4A7980E6A9A9ADC3255189F274F619E'), ('docs/baseline-sha256.json', '3561C10064F6BAC12F032FCC51382EBD7D7FBEF70786C31E6C857DC386ECD40D'), ('docs/baseline-verification.json', '7326E1A33FB35E281A6A3211E85DFFD2A081BB22317C33DB7B7FAEE67E2E394B'), ('docs/test-results.txt', 'EE9BBD62124FCF6CB377DF2D79129BF0C927ACEAB2128AB247CABE92F0A7F2B7'), ('requirements-vision.txt', 'ECBC0244A6BC4646A912CF032F999724D47E22CB12CDBFAA231B600465F06711'), ('requirements.txt', 'CE972E5602F1BADF47B56CE597EBF4A3CBC516CA6C8979C95EE75C067D275840'), ('run.py', 'BADDC792525790AED22B40E5F8C05FCDDCA0312325F3D70E5511A124565F7C16'), ('tests/test_alpha.py', '17BD7EBFF1558F062577A4677A472B0B3F65B85DC921253D6A9F5C2B705862D5'), ('tests/test_alpha02.py', '9F0839D676974435FA4AB3EE4887F9BE8DF876D07C271CADA4D0AFAA43A43C02'), ('tests/test_context_builder.py', '26A50D99710BAF117FA45AA570BA8BCDC38343835FED5EEF9C2618493E9AE701'), ('tests/test_decision_arbiter_v01.py', 'F24A7006527660AAD7C49FE87040330AF01571AF87D6FFE0AA717E4181EB2AEF'), ('tests/test_decision_context_v02.py', '100702613FFB1038A884C7CE9C7F3648B98C3CA8A7457A7A1ED5D6A25E4775D9'), ('tests/test_execution_lifecycle_v01.py', '2095F0B158E860CCDE27B112E8C08B56457D57235F19CD4B4FD35344D416D34E'), ('tests/test_farm_context.py', '25BD8B9A371D1E6D29D28B95703CB408790610CB22B2E73C7A8E998EA4499AA3'), ('tests/test_farm_cycle.py', 'AA522B1EF0759E860D869781161668025B0C83D9F6EBCE0CB8B5503FA607689C'), ('tests/test_feasibility_gate_v01.py', '13C1E9585E67BD00E08D24DFF4E243488F4CA9A183B003061F71F472CB3C0DDC'), ('tests/test_missing_threat_resolver.py', '330382C2E16F974FC22B4DF106F0405833DFCAE7D8551AACEB29D79742737E0E'), ('tests/test_objective_outcome_relation_v01.py', '4E683FE4C0BEE3F44C37EA47930DF4278AB2315BE54F2D9B78416507F5A7CC7A'), ('tests/test_observation_event.py', 'D98956D0F8DDD1DC3BFF96F9648F11B18D839565F7956DB9E626180B55C54C69'), ('tests/test_offline_core.py', 'D9FAFCC4A34DFBDBA1A0B09D7C20F21087C17D40E080E9D34CA2C783A4461076'), ('tests/test_option_availability.py', '6B0680FB38B0FF7773FE092D480242E99249AF7BB34C17917FEF98E9BC20E001'), ('tests/test_option_exposure.py', '0BE8813BDE3F2F4597A4A3603FD29BF3987649CFE3C85CA9594A80A0AAC2E6C8'), ('tests/test_option_outcome_evidence.py', '650A4F6FD90A1163A8D7DBEED12EAF121F4AB265C07620A9224E2D099E3FE8E8'), ('tests/test_option_safety.py', '36D218ECBC35DC34947D5165055BDCE269F8C02CF2B69B24836548838D01139C'), ('tests/test_option_safety_v02.py', '72AB624C36D54E72364959CD6BB516E29561807972DD48DEED26AEB61E6D019E'), ('tests/test_pairwise_tradeoff_v01.py', '6EE9F784F0E20280EA4BE2A035133D0A82B0684DB1BE0B25C6C030E3DE1B2F7B'), ('tests/test_risk_evaluation.py', '5D7B2C562B2886FCA7022F49C8676B2AA0B57C5BCDEBD749AD5CB11DBFB2506F'), ('tests/test_risk_evidence_assembly.py', '29EE7F10C27C828366AC76F763E7D87EDCEC44007FE8E437343EDC9456B6212D'), ('tests/test_risk_evidence_assembly_v02.py', 'BAF33606785D6CB95DDECE9F072B84117BE3C4CA99FFF955FEAD02DB824E6337'), ('tests/test_runtime_adapter.py', '2DE193D9E86A1ACDEEEFCD4F9B1CE69421D0DC67E28E499798CC19808285A55B'), ('tests/test_safety_evidence.py', '9BD4B7A0CAF825313EC659C428E65E40E5EA6378E932531C73F60C0D23C4B7AE'), ('tests/test_selection_hysteresis_v01.py', '7B94660F33EEA4563BD987B6DCC8545424BC5A4F4D4969E55758BA964EA4AF25'), ('tests/test_strategic_coverage.py', '8E88B3D14A4B2883516081D2B994C0187A1329866E154C9F4AE523FF244A4A6A'), ('tests/test_strategic_evidence.py', '737FC22A57AEFC7D1077D913787487AF220253B3B6983B6CE672F3EADF208807'), ('tests/test_strategic_objective_context.py', 'D9E4442199B6FCC7F6DFAF3E867C7C1CA13FB9FBF2BCC4BA5F2BDC2BC580EA18'), ('tests/test_temporal_evidence.py', '6933ACEC3D98028524FC97613DDC377BA268CB282546C77653FBEBCED7ED62F0'), ('tests/test_threat_absence_observation.py', 'AB89CA5F77F7955303F8CB7DFB4590AB5AF2A7696B360ADDF878BFF12FBEA1EB'), ('tests/test_threat_observation.py', '44EDB7456B4E47C7A86EFAECD1F49D40F0436C8F541FB294ACB9AD37620C8FEC'), ('tests/test_threat_reachability.py', '6C401B0FC0773780C74F8981FEDD4E280CFC11EF5E4F31C47511155A491D0A0B'), ('tests/test_threat_relevance.py', 'CE9E867D94857D2F889E81ECE7A63E750DF586FFA1897ABAE6CCD2FB7A325CEE'), ('tests/test_threat_state_assembly.py', '8E1DDE3F5C90CA5E3C30F2F86370C4322239E635F241AB66247EB5FD66FB6B79'), ('tests/test_visibility_completeness.py', '9E1FAA5054639C15CC89422AE8A5D9F77008ED524431F5CFA9E6A066AE5BA87C'))
