"""Atomic predicates, conservative collections, independent presence and transitions."""
import ast
from dataclasses import FrozenInstanceError, asdict, replace
import inspect
import json
import unittest
from unittest.mock import patch

from coach02 import local_readiness_evidence_v01 as ready
from coach02.farm_cadence_evidence_v01 import SemanticInputPresence
from coach02.live_runtime_v01 import RuntimeInputKind
from test_farm_cadence_evidence_v01 import occurrence, control, DROP, FOUNDATION, advance_live_runtime_v1, RuntimeInputV1


def policy(**changes):
    values=dict(policy_id='readiness.v1',ability_selectors=('test_active',),item_selectors=('item_test',))
    values.update(changes);return ready.LocalReadinessPolicyV1(**values)


def snapshot(result=None,pol=None):
    return ready.build_local_readiness_snapshot_v1(runtime_result=occurrence() if result is None else result,policy=policy() if pol is None else pol)


def step(result,old=None,pol=None):
    pol=policy() if pol is None else pol
    state=ready.new_local_readiness_state_v1(policy=pol) if old is None else old.next_state
    return ready.advance_local_readiness_v1(previous_state=state,runtime_result=result,policy=pol)


class LocalReadinessTests(unittest.TestCase):
    def ability(self,changes=None):return snapshot(occurrence(changes=changes)).abilities[0]
    def test_01_domains(self):
        self.assertEqual([s.value for s in ready.LocalReadinessStatus],['READY','NOT_READY','INDETERMINATE'])
        self.assertEqual([s.value for s in ready.ItemPresenceStatus],['PRESENT','NOT_REPORTED','INDETERMINATE'])
    def test_02_policy_exact_strings(self):
        self.assertEqual(policy(policy_id=' opaque ').policy_id,' opaque ')
        for bad in ('',' ',None,1):
            with self.subTest(bad=bad),self.assertRaises((ValueError,TypeError)):policy(policy_id=bad)
    def test_03_selector_validation(self):
        for bad in (['a'],('a','a'),('',),(' ',),(None,),tuple(str(n) for n in range(33))):
            with self.subTest(bad=bad),self.assertRaises((ValueError,TypeError)):policy(ability_selectors=bad)
    def test_04_predicate_and_gap_validation(self):
        with self.assertRaises(ValueError):policy(predicate_id='combat')
        for bad in (0,-1,True,1.0):
            with self.assertRaises(ValueError):policy(max_receipt_gap_ns=bad)
    def test_05_frozen_contracts(self):
        s=snapshot()
        with self.assertRaises(FrozenInstanceError):s.hero='other'
        with self.assertRaises(FrozenInstanceError):s.abilities[0].status=ready.LocalReadinessStatus.NOT_READY
    def test_06_ready_limited_predicate(self):
        row=self.ability();self.assertIs(row.status,ready.LocalReadinessStatus.READY);self.assertEqual(row.matching_slots,('ability0',))
    def test_07_cooldown_zero_not_can_cast(self):
        self.assertIs(self.ability({'abilities.ability0.can_cast':False}).status,ready.LocalReadinessStatus.NOT_READY)
    def test_08_positive_cooldown(self):
        self.assertIs(self.ability({'abilities.ability0.cooldown':1}).status,ready.LocalReadinessStatus.NOT_READY)
    def test_09_unlearned_level(self):
        self.assertIs(self.ability({'abilities.ability0.level':0}).status,ready.LocalReadinessStatus.NOT_READY)
    def test_10_dead_local_predicate(self):
        self.assertIs(self.ability({'hero.alive':False}).status,ready.LocalReadinessStatus.NOT_READY)
    def test_11_missing_level(self):
        self.assertIs(self.ability({'abilities.ability0.level':DROP}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_12_invalid_level(self):
        for bad in (True,-1,.5,'1'):
            with self.subTest(bad=bad):self.assertIs(self.ability({'abilities.ability0.level':bad}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_13_cooldown_missing_invalid(self):
        for bad in (DROP,True,-1,'0',{}):
            with self.subTest(bad=bad):self.assertIs(self.ability({'abilities.ability0.cooldown':bad}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_14_can_cast_missing_invalid(self):
        for bad in (DROP,1,'true',{}):
            with self.subTest(bad=bad):self.assertIs(self.ability({'abilities.ability0.can_cast':bad}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_15_passive_not_active_query(self):
        self.assertIs(self.ability({'abilities.ability0.passive':True}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_16_classification_unknown_and_conflict(self):
        for changes in ({'abilities.ability0.passive':DROP},{'abilities.ability0.is_passive':True},{'abilities.ability0.passive':'false'}):
            with self.subTest(changes=changes):self.assertIs(self.ability(changes).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_17_is_passive_alternative(self):
        self.assertIs(self.ability({'abilities.ability0.passive':DROP,'abilities.ability0.is_passive':False}).status,ready.LocalReadinessStatus.READY)
    def test_18_ability_collection_absent(self):
        self.assertIs(self.ability({'abilities':DROP}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_19_identity_absent(self):
        self.assertIs(self.ability({'abilities':{}}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_20_identity_duplicated(self):
        changes={'abilities.ability1':{'name':'test_active','level':1,'cooldown':0,'can_cast':True,'passive':False}}
        row=self.ability(changes);self.assertIs(row.status,ready.LocalReadinessStatus.INDETERMINATE);self.assertEqual(row.matching_slots,('ability0','ability1'))
    def test_21_identity_invalid(self):
        self.assertIs(self.ability({'abilities.ability0.name':True}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_22_pause_absent_true(self):
        for value in (DROP,True):
            with self.subTest(value=value):self.assertIs(self.ability({'map.paused':value}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_23_alive_unknown(self):
        self.assertIs(self.ability({'hero.alive':DROP}).status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_24_ineligible_scope(self):
        for changes in ({'player.activity':'spectating'},{'map.game_state':'MENU'}):
            self.assertFalse(snapshot(occurrence(changes=changes)).eligible_scope)
    def test_25_hero_selector(self):
        self.assertFalse(snapshot(pol=policy(hero_selector='other')).eligible_scope)
        self.assertTrue(snapshot(pol=policy(hero_selector='npc_test_hero')).eligible_scope)
    def test_26_mana_not_needed_not_inferred(self):
        one=snapshot(occurrence(changes={'hero.mana':0}));two=snapshot(occurrence(changes={'hero.mana':999}))
        self.assertIs(one.abilities[0].status,ready.LocalReadinessStatus.READY);self.assertIs(two.abilities[0].status,ready.LocalReadinessStatus.READY)
        self.assertNotIn('mana',one.abilities[0].evidence_refs)
    def test_27_item_present(self):
        row=snapshot().items[0];self.assertIs(row.status,ready.ItemPresenceStatus.PRESENT);self.assertEqual(row.matching_slots,('slot0',))
    def test_28_item_not_reported_scoped(self):
        row=snapshot(pol=policy(item_selectors=('item_other',))).items[0];self.assertIs(row.status,ready.ItemPresenceStatus.NOT_REPORTED)
    def test_29_missing_item_collection(self):
        self.assertIs(snapshot(occurrence(changes={'items':DROP})).items[0].status,ready.ItemPresenceStatus.INDETERMINATE)
    def test_30_empty_collection_report(self):
        self.assertIs(snapshot(occurrence(changes={'items':{}})).items[0].status,ready.ItemPresenceStatus.NOT_REPORTED)
    def test_31_item_duplicate_ambiguous(self):
        row=snapshot(occurrence(changes={'items.slot1':{'name':'item_test'}})).items[0]
        self.assertIs(row.status,ready.ItemPresenceStatus.INDETERMINATE);self.assertEqual(len(row.matching_slots),2)
    def test_32_item_entry_invalid(self):
        self.assertIs(snapshot(occurrence(changes={'items.slot0':{}})).items[0].status,ready.ItemPresenceStatus.INDETERMINATE)
    def test_33_slots_provenance_preserved(self):
        row=snapshot(occurrence(changes={'items':{'stash2':{'name':'item_test','charges':2,'purchaser':-1}}})).items[0]
        self.assertEqual(row.matching_slots,('stash2',));self.assertEqual(json.loads(row.observed_fields_json)['stash2']['charges'],2)
    def test_34_no_query_no_unknown_row(self):
        s=snapshot(pol=policy(ability_selectors=(),item_selectors=()));self.assertEqual((s.abilities,s.items),((),()))
    def test_35_first_no_transition(self):self.assertEqual(step(occurrence()).transitions,())
    def test_36_real_status_change_transition(self):
        a=occurrence(changes={'abilities.ability0.can_cast':False});b=occurrence(previous=a,receipt=1)
        out=step(b,step(a));self.assertEqual(len(out.transitions),1);self.assertEqual((out.transitions[0].previous_status.value,out.transitions[0].current_status.value),('NOT_READY','READY'))
    def test_37_same_status_no_transition(self):
        a=occurrence();b=occurrence(previous=a,receipt=1);self.assertEqual(step(b,step(a)).transitions,())
    def test_38_death_respawn_current_assessment(self):
        a=occurrence();b=occurrence(previous=a,receipt=1,changes={'hero.alive':False});c=occurrence(previous=b,receipt=2)
        dead=step(b,step(a));alive=step(c,dead);self.assertEqual(dead.transitions[0].current_status.value,'NOT_READY');self.assertEqual(alive.transitions[0].current_status.value,'READY')
    def test_39_session_timeline_policy_break(self):
        a=occurrence();old=step(a)
        for changes,pol in (({'hero.name':'other'},policy()),({},policy(policy_id='next'))):
            b=occurrence(previous=a,receipt=1,changes=changes);self.assertEqual(step(b,old,pol).transitions,())
        reset=control(a,1,RuntimeInputKind.RESET);cleared=step(reset,old);b=occurrence(previous=reset,receipt=2);self.assertEqual(step(b,cleared).transitions,())
    def test_40_fresh_control_preserves_only_comparison(self):
        a=occurrence();out=step(control(a,1),step(a));self.assertIs(out.snapshot.input_presence,SemanticInputPresence.ABSENT);self.assertEqual(out.transitions,());self.assertIsNotNone(out.next_state.last_snapshot)
    def test_41_stale_and_shutdown_clear(self):
        a=occurrence()
        for receipt,kind in ((6_000_000_000,RuntimeInputKind.TIME_ADVANCE),(1,RuntimeInputKind.SHUTDOWN)):
            self.assertIsNone(step(control(a,receipt,kind),step(a)).next_state.last_snapshot)
    def test_42_pause_resume_no_bridge(self):
        a=occurrence();b=occurrence(previous=a,receipt=1,changes={'map.paused':True});c=occurrence(previous=b,receipt=2)
        out=step(b,step(a));self.assertIsNone(out.next_state.last_snapshot);self.assertEqual(step(c,out).transitions,())
    def test_43_explicit_unknown_transition(self):
        a=occurrence(changes={'abilities':{}});b=occurrence(previous=a,receipt=1)
        out=step(b,step(a));self.assertEqual((out.transitions[0].previous_status.value,out.transitions[0].current_status.value),('INDETERMINATE','READY'))
    def test_44_ordering_identity_and_boundedness(self):
        a=occurrence();out=step(a)
        with self.assertRaises(ValueError):step(a,out)
        self.assertEqual(snapshot(a).snapshot_id,snapshot(a).snapshot_id);self.assertNotIn('history',asdict(out.next_state))
    def test_45_purity_and_dependencies(self):
        import time,socket,builtins
        a=occurrence()
        with patch.object(time,'time',side_effect=AssertionError),patch.object(time,'monotonic',side_effect=AssertionError),patch.object(socket,'socket',side_effect=AssertionError),patch.object(builtins,'open',side_effect=AssertionError):snapshot(a)
        tree=ast.parse(inspect.getsource(ready));self.assertEqual({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level},{'farm_cadence_evidence_v01'})
    def test_46_lineage_and_evidence_refs(self):
        a=occurrence();s=snapshot(a);self.assertEqual(s.runtime_snapshot_id,a.snapshot.snapshot_id);self.assertEqual(s.abilities[0].source_id,a.observation_event.source.source_id)
        self.assertIn('abilities.ability0.can_cast',s.abilities[0].evidence_refs)
    def test_47_selectors_opaque_no_trim(self):
        s=snapshot(pol=policy(ability_selectors=(' test_active ',)));self.assertIs(s.abilities[0].status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_48_current_absence_never_old_ready(self):
        a=occurrence();b=occurrence(previous=a,receipt=1,changes={'abilities':DROP})
        self.assertIs(step(b,step(a)).snapshot.abilities[0].status,ready.LocalReadinessStatus.INDETERMINATE)
    def test_49_unchanged_rejection_clears_comparison(self):
        a=occurrence(receipt=10)
        rejected=advance_live_runtime_v1(previous_state=a.next_state,
            runtime_input=RuntimeInputV1(RuntimeInputKind.TIME_ADVANCE,9),policy=FOUNDATION)
        out=step(rejected,step(a));self.assertIsNone(out.next_state.last_snapshot)
        self.assertEqual(out.transitions,())
