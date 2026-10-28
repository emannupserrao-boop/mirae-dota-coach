"""Observed intervals, independent clocks, absent/invalid input and bounded memory."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from coach02 import farm_cadence_evidence_v01 as farm
from coach02.live_runtime_v01 import (LiveRuntimePolicyV1, RuntimeInputV1, RuntimeInputKind,
    RuntimeUpdateReason, canonical_json, sanitize_gsi_payload_v1,
    new_live_runtime_state_v1, advance_live_runtime_v1)

FIXTURE=json.loads((Path(__file__).parent/'fixtures/real_minimal_producers_v01/SYNTHETIC.json').read_text(encoding='utf-8'))
DROP=object()
FOUNDATION=LiveRuntimePolicyV1('foundation.v1',30_000_000_000,'fresh.v1',5_000_000_000)


def payload(*, source_time=0,lh=0,changes=None):
    value=deepcopy(FIXTURE['payload']);value['map']['clock_time']=source_time;value['player']['last_hits']=lh
    for path,replacement in (changes or {}).items():
        owner=value;parts=path.split('.')
        for part in parts[:-1]: owner=owner[part]
        if replacement is DROP: owner.pop(parts[-1],None)
        else: owner[parts[-1]]=deepcopy(replacement)
    return value


def occurrence(*, source_time=0,lh=0,receipt=0,previous=None,changes=None):
    state=new_live_runtime_state_v1(run_id='synthetic-run',policy=FOUNDATION) if previous is None else previous.next_state
    body=canonical_json(sanitize_gsi_payload_v1(payload=payload(source_time=source_time,lh=lh,changes=changes)))
    inp=RuntimeInputV1(RuntimeInputKind.RECEIVED,receipt,state.receive_sequence+1,body)
    return advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=FOUNDATION)


def control(previous,receipt,kind=RuntimeInputKind.TIME_ADVANCE):
    return advance_live_runtime_v1(previous_state=previous.next_state,
        runtime_input=RuntimeInputV1(kind,receipt),policy=FOUNDATION)


def policy(**changes):
    value=dict(policy_id='farm.v1',minimum_gameplay_interval_seconds=2,max_receipt_gap_ns=3_000_000_000,max_source_step_seconds=3)
    value.update(changes);return farm.FarmCadencePolicyV1(**value)


def step(result,old=None,pol=None):
    pol=policy() if pol is None else pol
    state=farm.new_farm_cadence_state_v1(policy=pol) if old is None else old.next_state
    return farm.advance_farm_cadence_v1(previous_state=state,runtime_result=result,policy=pol)


def interval(*,initial_lh=0,final_lh=2,receipt_end=1_000_000_000,source_end=2):
    a=occurrence(lh=initial_lh);b=occurrence(previous=a,lh=final_lh,source_time=source_end,receipt=receipt_end)
    return a,b,step(b,step(a))


class FarmCadenceTests(unittest.TestCase):
    def indeterminate(self,result): self.assertIs(result.evidence.status,farm.FarmCadenceStatus.INDETERMINATE)
    def test_01_exact_domains(self):
        self.assertEqual([s.value for s in farm.FarmCadenceStatus],['OBSERVED_INTERVAL','INDETERMINATE'])
        self.assertEqual([s.value for s in farm.SemanticInputPresence],['PRESENT','ABSENT'])
    def test_02_frozen_policy(self):
        with self.assertRaises(FrozenInstanceError): policy().policy_id='changed'
    def test_03_policy_identifiers(self):
        for bad in ('',' ',None,1):
            with self.subTest(bad=bad),self.assertRaises((ValueError,TypeError)):policy(policy_id=bad)
        self.assertEqual(policy(policy_id=' opaque ').policy_id,' opaque ')
    def test_04_policy_numeric_boundaries(self):
        for field in ('minimum_gameplay_interval_seconds','max_receipt_gap_ns','max_source_step_seconds'):
            for bad in (True,0,-1,'1',float('inf'),float('nan')):
                with self.subTest(field=field,bad=bad),self.assertRaises((ValueError,TypeError)):policy(**{field:bad})
    def test_05_first_anchor(self):
        out=step(occurrence());self.indeterminate(out);self.assertEqual(out.evidence.reason.value,'INITIAL_ANCHOR');self.assertIsNotNone(out.next_state.anchor)
    def test_06_incomplete_window(self):
        a=occurrence();b=occurrence(previous=a,source_time=1,lh=1,receipt=1)
        out=step(b,step(a));self.indeterminate(out);self.assertIsNone(out.evidence.gameplay_duration)
    def test_07_observed_rate(self):
        a,b,out=interval();self.assertIs(out.evidence.status,farm.FarmCadenceStatus.OBSERVED_INTERVAL)
        self.assertEqual((out.evidence.delta_lh,out.evidence.gameplay_duration,out.evidence.lh_per_game_minute),(2,2,60))
    def test_08_zero_rate_is_observed(self):
        out=interval(final_lh=0)[2];self.assertIs(out.evidence.status,farm.FarmCadenceStatus.OBSERVED_INTERVAL);self.assertEqual(out.evidence.lh_per_game_minute,0)
    def test_09_receipt_does_not_compute_rate(self):
        self.assertEqual(interval(receipt_end=100)[2].evidence.lh_per_game_minute,interval(receipt_end=2_000_000_000)[2].evidence.lh_per_game_minute)
    def test_10_same_time_same_count(self):
        a=occurrence();b=occurrence(previous=a,receipt=1)
        out=step(b,step(a));self.indeterminate(out);self.assertEqual(out.evidence.reason.value,'SAME_SOURCE_TIME');self.assertEqual(out.next_state.anchor.runtime_snapshot_id,a.snapshot.snapshot_id)
    def test_11_same_time_changed_count(self):
        a=occurrence();b=occurrence(previous=a,receipt=1,lh=1)
        out=step(b,step(a));self.indeterminate(out);self.assertEqual(out.evidence.reason.value,'SAME_TIME_LH_CHANGE');self.assertEqual(out.next_state.anchor.lh,1)
    def test_12_missing_lh(self):
        out=step(occurrence(changes={'player.last_hits':DROP}));self.indeterminate(out);self.assertIsNone(out.next_state.anchor)
    def test_13_fractional_negative_bool_lh(self):
        for bad in (-1,.5,True,'0'):
            with self.subTest(bad=bad):self.indeterminate(step(occurrence(lh=bad)))
    def test_14_integer_float_counter(self):
        self.assertEqual(step(occurrence(lh=2.0)).next_state.anchor.lh,2)
    def test_15_missing_source_time(self): self.indeterminate(step(occurrence(changes={'map.clock_time':DROP})))
    def test_16_invalid_source_time(self):
        for bad in (-1,True,'1'):
            with self.subTest(bad=bad):self.indeterminate(step(occurrence(source_time=bad)))
    def test_17_pause_unknown(self): self.indeterminate(step(occurrence(changes={'map.paused':DROP})))
    def test_18_pause_true(self):
        out=step(occurrence(changes={'map.paused':True}));self.indeterminate(out);self.assertIsNone(out.next_state.anchor)
    def test_19_alive_unknown(self): self.indeterminate(step(occurrence(changes={'hero.alive':DROP})))
    def test_20_death_breaks_interval(self):
        a=occurrence();b=occurrence(previous=a,source_time=1,receipt=1,changes={'hero.alive':False})
        out=step(b,step(a));self.indeterminate(out);self.assertIsNone(out.next_state.anchor)
    def test_21_respawn_new_anchor(self):
        a=occurrence(changes={'hero.alive':False});b=occurrence(previous=a,source_time=2,receipt=1)
        out=step(b,step(a));self.indeterminate(out);self.assertEqual(out.next_state.anchor.source_match_time,2)
    def test_22_nonlocal_scope(self):
        self.indeterminate(step(occurrence(changes={'player.activity':'spectating'})))
    def test_23_no_session(self):
        self.indeterminate(step(occurrence(changes={'map.game_state':'MENU'})))
    def test_24_lh_regression(self):
        a=occurrence(lh=5);b=occurrence(previous=a,source_time=1,lh=4,receipt=1)
        out=step(b,step(a));self.assertEqual(out.evidence.reason.value,'LH_REGRESSION');self.assertEqual(out.next_state.anchor.lh,4)
    def test_25_receipt_gap(self):
        a,b,out=interval(receipt_end=4_000_000_000);self.indeterminate(out);self.assertEqual(out.evidence.reason.value,'CONTINUITY_GAP')
    def test_26_source_jump(self):
        out=interval(source_end=4)[2];self.indeterminate(out);self.assertEqual(out.evidence.reason.value,'CONTINUITY_GAP')
    def test_27_rewind_resets(self):
        a=occurrence(source_time=10);b=occurrence(previous=a,source_time=9,receipt=1)
        out=step(b,step(a));self.indeterminate(out);self.assertNotEqual(out.next_state.timeline_id,a.snapshot.timeline_id)
    def test_28_hero_session_change(self):
        a=occurrence();b=occurrence(previous=a,source_time=2,receipt=1,changes={'hero.name':'other'})
        out=step(b,step(a));self.indeterminate(out);self.assertNotEqual(out.next_state.session_id,a.snapshot.session_id)
    def test_29_explicit_reset(self):
        a=occurrence();out=step(control(a,1,RuntimeInputKind.RESET),step(a));self.indeterminate(out);self.assertIsNone(out.next_state.anchor)
    def test_30_time_advance_not_sample(self):
        a=occurrence();out=step(control(a,1),step(a));self.indeterminate(out);self.assertIs(out.evidence.input_presence,farm.SemanticInputPresence.ABSENT);self.assertIsNone(out.evidence.end_sample);self.assertEqual(out.next_state.anchor.runtime_snapshot_id,a.snapshot.snapshot_id)
    def test_31_staleness_control(self):
        a=occurrence();out=step(control(a,6_000_000_000),step(a));self.assertIsNone(out.next_state.anchor)
    def test_32_foundation_gap_control(self):
        a=occurrence();out=step(control(a,31_000_000_000),step(a));self.assertIsNone(out.next_state.anchor)
    def test_33_shutdown(self):
        a=occurrence();out=step(control(a,1,RuntimeInputKind.SHUTDOWN),step(a));self.assertIsNone(out.next_state.anchor)
    def test_34_policy_change(self):
        a=occurrence();b=occurrence(previous=a,source_time=2,receipt=1)
        out=step(b,step(a),policy(policy_id='next'));self.indeterminate(out);self.assertEqual(out.next_state.policy.policy_id,'next')
    def test_35_nonoverlapping_windows(self):
        a,b,out=interval();c=occurrence(previous=b,source_time=4,lh=3,receipt=2_000_000_000)
        final=step(c,out);self.assertEqual(final.evidence.start_sample.source_match_time,2);self.assertEqual(final.evidence.delta_lh,1)
    def test_36_exact_ordering(self):
        a=occurrence()
        with self.assertRaises(ValueError):step(a,step(a))
    def test_37_lineage_tamper_rejected(self):
        a=occurrence();bad=replace(a,snapshot=replace(a.snapshot,timeline_id='foreign'))
        with self.assertRaises(ValueError):step(bad)
    def test_38_frozen_bounded_state(self):
        out=step(occurrence())
        with self.assertRaises(FrozenInstanceError):out.next_state.hero='other'
        self.assertNotIn('history',asdict(out.next_state));self.assertIs(out.next_state.anchor,out.next_state.last_sample)
    def test_39_identity_and_provenance(self):
        a=occurrence();one=step(a);two=step(a);self.assertEqual(one.evidence.evidence_id,two.evidence.evidence_id)
        self.assertEqual(one.next_state.anchor.payload_id,a.snapshot.payload_id);self.assertEqual(one.next_state.anchor.observation_event_id,a.observation_event.event_id)
    def test_40_purity_and_import_boundary(self):
        import time,socket,builtins
        a=occurrence()
        with patch.object(time,'time',side_effect=AssertionError),patch.object(time,'monotonic',side_effect=AssertionError),patch.object(socket,'socket',side_effect=AssertionError),patch.object(builtins,'open',side_effect=AssertionError):step(a)
        tree=ast.parse(inspect.getsource(farm));deps={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level}
        self.assertEqual(deps,{'live_runtime_v01'})
    def test_41_rejected_input_breaks(self):
        a=occurrence();inp=RuntimeInputV1(RuntimeInputKind.REJECTED,1,2,rejection_reason=RuntimeUpdateReason.INVALID_JSON)
        result=advance_live_runtime_v1(previous_state=a.next_state,runtime_input=inp,policy=FOUNDATION)
        out=step(result,step(a));self.assertIsNone(out.next_state.anchor);self.assertIs(out.evidence.input_presence,farm.SemanticInputPresence.ABSENT)
    def test_42_fixture_explicitly_synthetic(self):
        self.assertEqual(FIXTURE['origin'],'SYNTHETIC');self.assertEqual(len({v['name'] for v in FIXTURE['vectors']}),14)
    def test_43_snapshot_does_not_fill_forward(self):
        a=occurrence();b=occurrence(previous=a,source_time=2,receipt=1,changes={'player.last_hits':DROP})
        out=step(b,step(a));self.indeterminate(out);self.assertIsNone(out.next_state.anchor)
    def test_44_provider_time_not_duration(self):
        a=occurrence(changes={'provider.timestamp':999999});b=occurrence(previous=a,source_time=2,lh=2,receipt=1,changes={'provider.timestamp':0})
        self.assertEqual(step(b,step(a)).evidence.lh_per_game_minute,60)
    def test_45_unchanged_out_of_order_rejection_clears_memory(self):
        a=occurrence(receipt=10)
        rejected=advance_live_runtime_v1(previous_state=a.next_state,
            runtime_input=RuntimeInputV1(RuntimeInputKind.TIME_ADVANCE,9),policy=FOUNDATION)
        out=step(rejected,step(a));self.assertIsNone(out.next_state.anchor)
        self.assertIs(out.evidence.input_presence,farm.SemanticInputPresence.ABSENT)
    def test_46_rate_overflow_abstains(self):
        pol=policy(minimum_gameplay_interval_seconds=1e-300)
        a=occurrence();b=occurrence(previous=a,source_time=1e-300,lh=1e300,receipt=1)
        out=step(b,step(a,pol=pol),pol);self.indeterminate(out)
        self.assertEqual(out.evidence.reason.value,'RATE_NOT_REPRESENTABLE')
        self.assertIsNone(out.evidence.lh_per_game_minute)
