"""SYNTHETIC exact-contract and continuity regression vectors."""
import ast
import copy
from dataclasses import FrozenInstanceError, replace
import inspect
import json
from pathlib import Path
import unittest
from coach.state import normalize
from coach02 import live_runtime_v01 as live

FIXTURES = json.loads((Path(__file__).parent/'fixtures/live_runtime_v01/SYNTHETIC.json').read_text())
def payload(name='valid_local'):
    return copy.deepcopy(FIXTURES['scenarios'][name])
def policy(**changes):
    return replace(live.LiveRuntimePolicyV1('policy',100,'fresh',20),**changes)
def initial():
    return live.new_live_runtime_state_v1(run_id='run',policy=policy())
def receive(state=None, raw=None, tick=10, seq=None):
    state=initial() if state is None else state
    raw=payload() if raw is None else raw
    inp=live.RuntimeInputV1(live.RuntimeInputKind.RECEIVED,tick,
        state.receive_sequence+1 if seq is None else seq,
        live.canonical_json(live.sanitize_gsi_payload_v1(payload=raw)))
    return live.advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=policy())
def control(state,tick,kind=live.RuntimeInputKind.TIME_ADVANCE):
    return live.advance_live_runtime_v1(previous_state=state,
        runtime_input=live.RuntimeInputV1(kind,tick),policy=policy())
def cap(result,field):
    return next(c for c in result.snapshot.capabilities if c.field_id==field)

class LiveRuntimeTests(unittest.TestCase):
    def test_exact_enums(self):
        for cls,values in ((live.RuntimeUpdateStatus,('ACCEPTED','REJECTED','CONTROL','ERROR')),
                          (live.RuntimeCapabilitySupport,('SUPPORTED','UNSUPPORTED')),
                          (live.RuntimeFieldPresence,('PRESENT','ABSENT')),
                          (live.RuntimeFieldValidity,('VALID','INVALID','NOT_ASSESSED'))):
            self.assertEqual(tuple(e.value for e in cls),values)
    def test_initial_empty(self):
        s=initial(); self.assertIsNone(s.session_id); self.assertEqual(s.temporal_state.marks,())
        self.assertEqual(s.timeline_id,'run/timeline/0'); self.assertEqual(s.receive_sequence,0)
    def test_initial_is_deterministic(self): self.assertEqual(initial().state_id,initial().state_id)
    def test_local_starts_episode(self):
        r=receive(); self.assertEqual(r.snapshot.session_id,'run/session/1')
        self.assertIn(live.RuntimeUpdateReason.SESSION_START,r.reason_codes)
    def test_menu_no_session(self): self.assertIsNone(receive(raw=payload('menu')).snapshot.session_id)
    def test_start_requires_phase(self):
        p=payload(); p['map'].pop('game_state'); self.assertIsNone(receive(raw=p).snapshot.session_id)
    def test_start_requires_hero(self):
        p=payload(); p['hero']['name']=''; self.assertIsNone(receive(raw=p).snapshot.session_id)
    def test_start_requires_local(self): self.assertIsNone(receive(raw=payload('nonlocal')).snapshot.session_id)
    def test_empty_id_not_authoritative(self):
        r=receive(raw=payload('match_id_empty')); self.assertEqual(r.next_state.session_ordinal,1)
        self.assertIsNone(r.next_state.known_match_id)
    def test_zero_id_not_authoritative(self): self.assertIsNone(receive(raw=payload('match_id_zero')).next_state.known_match_id)
    def test_first_usable_id_binds(self):
        s=receive(raw=payload('match_id_empty')).next_state
        r=receive(s,tick=11); self.assertEqual(r.next_state.session_id,s.session_id)
    def test_known_id_change_new_session(self):
        r=receive(receive().next_state,payload('match_id_changed'),11)
        self.assertEqual(r.snapshot.session_id,'run/session/2')
    def test_hero_change_new_session(self):
        r=receive(receive().next_state,payload('hero_changed'),11)
        self.assertEqual(r.snapshot.session_id,'run/session/2')
    def test_explicit_exit_ends_session(self):
        r=receive(receive().next_state,payload('menu'),11)
        self.assertIsNone(r.snapshot.session_id); self.assertIn(live.RuntimeUpdateReason.SESSION_END,r.reason_codes)
    def test_optional_absence_does_not_end(self):
        s=receive().next_state; r=receive(s,payload('missing_scope'),11)
        self.assertEqual(r.snapshot.session_id,s.session_id)
    def test_no_value_fill_forward(self):
        r=receive(receive().next_state,payload('optional_absent'),11)
        self.assertIsNone(json.loads(r.snapshot.normalized_state_json)['gold'])
        self.assertNotIn('gold',r.observation_event.refs)
    def test_identical_payload_distinct_occurrences(self):
        a=receive(); b=receive(a.next_state,tick=11)
        self.assertEqual(a.snapshot.payload_id,b.snapshot.payload_id)
        self.assertNotEqual(a.snapshot.snapshot_id,b.snapshot.snapshot_id)
        self.assertNotEqual(a.observation_event.event_id,b.observation_event.event_id)
    def test_same_game_time_distinct(self):
        a=receive(); b=receive(a.next_state,payload('item_change'),11)
        self.assertEqual(a.snapshot.source_match_time,b.snapshot.source_match_time)
        self.assertNotEqual(a.snapshot.normalized_state_json,b.snapshot.normalized_state_json)
    def test_pause_retains_timeline(self):
        a=receive(); b=receive(a.next_state,payload('pause'),11)
        self.assertEqual(a.snapshot.timeline_id,b.snapshot.timeline_id)
        self.assertIn(live.RuntimeUpdateReason.PAUSE,b.reason_codes)
    def test_resume_explicit(self):
        a=receive(raw=payload('pause')); b=receive(a.next_state,tick=11)
        self.assertIn(live.RuntimeUpdateReason.RESUME,b.reason_codes)
    def test_absent_pause_not_resume(self):
        a=receive(raw=payload('pause')); p=payload(); p['map'].pop('paused')
        b=receive(a.next_state,p,11); self.assertTrue(b.next_state.paused)
        self.assertNotIn(live.RuntimeUpdateReason.RESUME,b.reason_codes)
    def test_rewind_new_timeline_same_session(self):
        a=receive(); b=receive(a.next_state,payload('rewind'),11)
        self.assertEqual(a.snapshot.session_id,b.snapshot.session_id)
        self.assertNotEqual(a.snapshot.timeline_id,b.snapshot.timeline_id)
        self.assertIn(live.RuntimeUpdateReason.REWIND,b.reason_codes)
    def test_gap_boundary_not_crossed(self):
        a=receive(); b=control(a.next_state,110)
        self.assertFalse(b.next_state.gap_open)
    def test_gap_crossed_once(self):
        a=receive(); b=control(a.next_state,111); c=control(b.next_state,112)
        self.assertTrue(b.next_state.gap_open); self.assertEqual(b.next_state.timeline_id,c.next_state.timeline_id)
        self.assertEqual(b.next_state.temporal_state.marks,())
    def test_gap_prior_freshness_retained(self):
        a=receive(); b=control(a.next_state,111)
        self.assertEqual(b.temporal_snapshot.timeline_id,a.snapshot.timeline_id)
        self.assertEqual(next(e for e in b.temporal_snapshot.entries if e.ref=='gold').status.value,'stale')
    def test_return_after_gap_no_second_reset(self):
        gap=control(receive().next_state,111); r=receive(gap.next_state,tick=112)
        self.assertEqual(gap.next_state.timeline_id,r.snapshot.timeline_id)
    def test_ordinary_reconnect_continuity(self):
        a=receive(); b=receive(a.next_state,tick=90)
        self.assertEqual(a.snapshot.timeline_id,b.snapshot.timeline_id)
    def test_reset_empties_tracker(self):
        r=control(receive().next_state,11,live.RuntimeInputKind.RESET)
        self.assertEqual(r.next_state.temporal_state.marks,()); self.assertIsNone(r.snapshot)
    def test_controls_do_not_increment_sequence(self):
        a=receive(); b=control(a.next_state,11)
        self.assertEqual(b.next_state.receive_sequence,1); self.assertIsNone(b.observation_event)
    def test_control_ages_without_refresh(self):
        a=receive(); b=control(a.next_state,31)
        entry=next(e for e in b.temporal_snapshot.entries if e.ref=='gold')
        self.assertEqual(entry.age_ticks,21); self.assertEqual(entry.status.value,'stale')
    def test_age_boundary_inclusive(self):
        b=control(receive().next_state,30)
        self.assertEqual(next(e for e in b.temporal_snapshot.entries if e.ref=='gold').status.value,'fresh')
    def test_clock_is_receipt_only(self):
        r=receive(); self.assertIsNone(r.observation_event.source_stamp)
        self.assertEqual(r.temporal_projection.timestamp_basis.value,'receipt')
        self.assertEqual(r.snapshot.evaluated_at_tick,10)
    def test_provider_timestamp_metadata_only(self):
        p=payload(); p['provider']['timestamp']=-100
        r=receive(raw=p); self.assertEqual(r.snapshot.provider_timestamp,-100)
        self.assertEqual(r.temporal_projection.selected_tick,10)
    def test_tick_tie_breaker(self):
        a=receive(); b=receive(a.next_state,tick=10)
        self.assertEqual(b.snapshot.evaluated_at_tick,11); self.assertEqual(b.next_state.last_receipt_elapsed_ns,10)
    def test_out_of_order_time(self):
        a=receive(); b=receive(a.next_state,tick=9)
        self.assertEqual(b.next_state,a.next_state); self.assertEqual(b.status.value,'REJECTED')
    def test_out_of_order_sequence(self):
        a=receive(); b=receive(a.next_state,tick=11,seq=3)
        self.assertEqual(b.next_state,a.next_state); self.assertIsNone(b.snapshot)
    def test_rejection_no_refresh(self):
        a=receive(); inp=live.RuntimeInputV1(live.RuntimeInputKind.REJECTED,11,2,rejection_reason=live.RuntimeUpdateReason.INVALID_AUTH)
        b=live.advance_live_runtime_v1(previous_state=a.next_state,runtime_input=inp,policy=policy())
        self.assertEqual(b.next_state.temporal_state,a.next_state.temporal_state)
        self.assertIsNone(b.snapshot); self.assertEqual(b.next_state.receive_sequence,2)
    def test_shutdown_terminal(self):
        r=control(initial(),10,live.RuntimeInputKind.SHUTDOWN)
        with self.assertRaises(ValueError): control(r.next_state,11)
    def test_foreign_policy_rejected(self):
        with self.assertRaises(ValueError): live.advance_live_runtime_v1(previous_state=initial(),runtime_input=live.RuntimeInputV1(live.RuntimeInputKind.TIME_ADVANCE,1),policy=policy(policy_id='other'))
    def test_frozen_snapshot(self):
        with self.assertRaises(FrozenInstanceError): receive().snapshot.run_id='other'
    def test_mutation_of_input_cannot_change_snapshot(self):
        p=payload(); r=receive(raw=p); before=r.snapshot.snapshot_id; p['items']['slot0']['name']='changed'
        self.assertEqual(r.snapshot.snapshot_id,before)
    def test_capability_catalog_bounded(self):
        self.assertEqual(tuple(c.field_id for c in receive().snapshot.capabilities),live.FIELD_IDS)
        self.assertLessEqual(len(receive().next_state.temporal_state.marks),len(live.FIELD_IDS))
    def test_unsupported_not_observed(self):
        r=receive(raw=payload('unsupported_health')); c=cap(r,'health')
        self.assertEqual(c.support.value,'UNSUPPORTED'); self.assertEqual(c.presence.value,'PRESENT')
        self.assertNotIn('health',r.observation_event.refs)
    def test_empty_collection_present(self): self.assertEqual(cap(receive(raw=payload('empty_items')),'items').presence.value,'PRESENT')
    def test_cooldown_absent_not_zero(self):
        r=receive(raw=payload('cooldown_absent')); self.assertEqual(cap(r,'abilities.cooldown').presence.value,'ABSENT')
        self.assertNotIn('cooldown',json.loads(r.snapshot.normalized_state_json)['abilities']['ability0'])
    def test_nested_source_paths(self): self.assertEqual(cap(receive(),'abilities.cooldown').source_paths,('abilities.ability0.cooldown',))
    def test_credentials_removed(self):
        value=live.canonical_json(live.sanitize_gsi_payload_v1(payload=payload('auth_and_pii')))
        self.assertNotIn('SYNTHETIC_TOKEN',value); self.assertNotIn('SYNTHETIC_PRIVATE',value); self.assertNotIn('Synthetic Player',value)
    def test_nonfinite_dropped_field_rejected(self):
        p=payload(); p['unused']=float('nan')
        with self.assertRaises(ValueError): live.sanitize_gsi_payload_v1(payload=p)
    def test_unsanitized_input_rejected(self):
        with self.assertRaises(ValueError): live.RuntimeInputV1(live.RuntimeInputKind.RECEIVED,1,1,live.canonical_json(payload('auth_and_pii')))
    def test_invalid_appid_runtime_rejected(self):
        p=payload(); p['provider']['appid']=440
        self.assertEqual(receive(raw=p).status.value,'REJECTED')
    def test_no_domain_events(self):
        self.assertEqual(set(live.RuntimeUpdateResultV1.__dataclass_fields__),{'status','reason_codes','next_state','snapshot','observation_event','temporal_projection','temporal_snapshot'})
    def test_pure_import_boundary(self):
        tree=ast.parse(inspect.getsource(live)); imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertEqual(imports-{'dataclasses','enum'}, {'coach.state','observation_event','temporal_evidence'})
        calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls & {'open','time.monotonic_ns','time.time','uuid.uuid4','eval','exec','__import__','getattr'})
    def test_all_synthetic_sanitization_parity(self):
        self.assertEqual(FIXTURES['origin'],'SYNTHETIC')
        for name,p in FIXTURES['scenarios'].items():
            with self.subTest(name=name): self.assertEqual(normalize(p),normalize(live.sanitize_gsi_payload_v1(payload=p)))
    def test_field_level_zero(self):
        p=payload(); p['hero']['level']=0; r=receive(raw=p); c=cap(r,'level')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('level' in r.observation_event.refs,True)
    def test_field_level_absent(self):
        p=payload(); p['hero'].pop('level'); r=receive(raw=p); c=cap(r,'level')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('level' in r.observation_event.refs,False)
    def test_field_level_invalid(self):
        p=payload(); p['hero']['level']=True; r=receive(raw=p); c=cap(r,'level')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('level' in r.observation_event.refs,False)
    def test_field_kills_zero(self):
        p=payload(); p['player']['kills']=0; r=receive(raw=p); c=cap(r,'kills')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('kills' in r.observation_event.refs,True)
    def test_field_kills_absent(self):
        p=payload(); p['player'].pop('kills'); r=receive(raw=p); c=cap(r,'kills')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('kills' in r.observation_event.refs,False)
    def test_field_kills_invalid(self):
        p=payload(); p['player']['kills']=True; r=receive(raw=p); c=cap(r,'kills')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('kills' in r.observation_event.refs,False)
    def test_field_deaths_zero(self):
        p=payload(); p['player']['deaths']=0; r=receive(raw=p); c=cap(r,'deaths')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('deaths' in r.observation_event.refs,True)
    def test_field_deaths_absent(self):
        p=payload(); p['player'].pop('deaths'); r=receive(raw=p); c=cap(r,'deaths')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('deaths' in r.observation_event.refs,False)
    def test_field_deaths_invalid(self):
        p=payload(); p['player']['deaths']=True; r=receive(raw=p); c=cap(r,'deaths')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('deaths' in r.observation_event.refs,False)
    def test_field_assists_zero(self):
        p=payload(); p['player']['assists']=0; r=receive(raw=p); c=cap(r,'assists')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('assists' in r.observation_event.refs,True)
    def test_field_assists_absent(self):
        p=payload(); p['player'].pop('assists'); r=receive(raw=p); c=cap(r,'assists')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('assists' in r.observation_event.refs,False)
    def test_field_assists_invalid(self):
        p=payload(); p['player']['assists']=True; r=receive(raw=p); c=cap(r,'assists')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('assists' in r.observation_event.refs,False)
    def test_field_lh_zero(self):
        p=payload(); p['player']['last_hits']=0; r=receive(raw=p); c=cap(r,'lh')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('lh' in r.observation_event.refs,True)
    def test_field_lh_absent(self):
        p=payload(); p['player'].pop('last_hits'); r=receive(raw=p); c=cap(r,'lh')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('lh' in r.observation_event.refs,False)
    def test_field_lh_invalid(self):
        p=payload(); p['player']['last_hits']=True; r=receive(raw=p); c=cap(r,'lh')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('lh' in r.observation_event.refs,False)
    def test_field_denies_zero(self):
        p=payload(); p['player']['denies']=0; r=receive(raw=p); c=cap(r,'denies')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('denies' in r.observation_event.refs,True)
    def test_field_denies_absent(self):
        p=payload(); p['player'].pop('denies'); r=receive(raw=p); c=cap(r,'denies')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('denies' in r.observation_event.refs,False)
    def test_field_denies_invalid(self):
        p=payload(); p['player']['denies']=True; r=receive(raw=p); c=cap(r,'denies')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('denies' in r.observation_event.refs,False)
    def test_field_gold_zero(self):
        p=payload(); p['player']['gold']=0; r=receive(raw=p); c=cap(r,'gold')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('gold' in r.observation_event.refs,True)
    def test_field_gold_absent(self):
        p=payload(); p['player'].pop('gold'); r=receive(raw=p); c=cap(r,'gold')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('gold' in r.observation_event.refs,False)
    def test_field_gold_invalid(self):
        p=payload(); p['player']['gold']=True; r=receive(raw=p); c=cap(r,'gold')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('gold' in r.observation_event.refs,False)
    def test_field_gpm_zero(self):
        p=payload(); p['player']['gpm']=0; r=receive(raw=p); c=cap(r,'gpm')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('gpm' in r.observation_event.refs,True)
    def test_field_gpm_absent(self):
        p=payload(); p['player'].pop('gpm'); r=receive(raw=p); c=cap(r,'gpm')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('gpm' in r.observation_event.refs,False)
    def test_field_gpm_invalid(self):
        p=payload(); p['player']['gpm']=True; r=receive(raw=p); c=cap(r,'gpm')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('gpm' in r.observation_event.refs,False)
    def test_field_xpm_zero(self):
        p=payload(); p['player']['xpm']=0; r=receive(raw=p); c=cap(r,'xpm')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('xpm' in r.observation_event.refs,True)
    def test_field_xpm_absent(self):
        p=payload(); p['player'].pop('xpm'); r=receive(raw=p); c=cap(r,'xpm')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('xpm' in r.observation_event.refs,False)
    def test_field_xpm_invalid(self):
        p=payload(); p['player']['xpm']=True; r=receive(raw=p); c=cap(r,'xpm')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('xpm' in r.observation_event.refs,False)
    def test_field_buyback_cost_zero(self):
        p=payload(); p['hero']['buyback_cost']=0; r=receive(raw=p); c=cap(r,'buyback_cost')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('buyback_cost' in r.observation_event.refs,True)
    def test_field_buyback_cost_absent(self):
        p=payload(); p['hero'].pop('buyback_cost'); r=receive(raw=p); c=cap(r,'buyback_cost')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('buyback_cost' in r.observation_event.refs,False)
    def test_field_buyback_cost_invalid(self):
        p=payload(); p['hero']['buyback_cost']=True; r=receive(raw=p); c=cap(r,'buyback_cost')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('buyback_cost' in r.observation_event.refs,False)
    def test_field_buyback_cooldown_zero(self):
        p=payload(); p['hero']['buyback_cooldown']=0; r=receive(raw=p); c=cap(r,'buyback_cooldown')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','VALID'))
        self.assertEqual('buyback_cooldown' in r.observation_event.refs,True)
    def test_field_buyback_cooldown_absent(self):
        p=payload(); p['hero'].pop('buyback_cooldown'); r=receive(raw=p); c=cap(r,'buyback_cooldown')
        self.assertEqual((c.presence.value,c.validity.value),('ABSENT','NOT_ASSESSED'))
        self.assertEqual('buyback_cooldown' in r.observation_event.refs,False)
    def test_field_buyback_cooldown_invalid(self):
        p=payload(); p['hero']['buyback_cooldown']=True; r=receive(raw=p); c=cap(r,'buyback_cooldown')
        self.assertEqual((c.presence.value,c.validity.value),('PRESENT','INVALID'))
        self.assertEqual('buyback_cooldown' in r.observation_event.refs,False)
    def test_invalid_policy_blank(self):
        with self.assertRaises((ValueError,TypeError)): policy(policy_id=' ')
    def test_invalid_gap_bool(self):
        with self.assertRaises((ValueError,TypeError)): policy(gap_after_ns=True)
    def test_invalid_gap_negative(self):
        with self.assertRaises((ValueError,TypeError)): policy(gap_after_ns=-1)
    def test_invalid_age_float(self):
        with self.assertRaises((ValueError,TypeError)): policy(max_age_ns=1.0)
    def test_invalid_age_negative(self):
        with self.assertRaises((ValueError,TypeError)): policy(max_age_ns=-1)
    def test_invalid_fresh_blank(self):
        with self.assertRaises((ValueError,TypeError)): policy(freshness_policy_id='')
    def test_invalid_schema(self):
        with self.assertRaises((ValueError,TypeError)): policy(schema_id='future')
    def test_invalid_sanitization(self):
        with self.assertRaises((ValueError,TypeError)): policy(sanitization_version='future')
