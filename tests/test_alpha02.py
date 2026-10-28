"""Alpha 0.2 unit/integration tests. Vision and speech stimuli are SYNTHETIC."""
from contextlib import closing
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request,urlopen
from coach.state import normalize
from coach.demo import payload
from coach02 import config
from coach02.rules import Engine,Candidate
from coach02.policy import Policy
from coach02.service import Service
from coach02.voice import Voice,Job,choose_voice
from coach02.storage import Store,utc
from coach02.vision import Temporal,Matcher,ROLES,Vision

def cfg():
    c=copy.deepcopy(config.DEFAULTS); c['token']='a'*64; return c
def state(t=300,lh=30,**kw): return normalize(payload(t,lh,**kw))
def wait_for(fn,seconds=3):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if fn(): return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for condition')
def candidate(rid='farm_low_v1',priority=2,key='farm:low'):
    return Candidate(rid,key,'Teste sintético',{'fixture':True},priority)

class ConfigTests(unittest.TestCase):
    def test_modes_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); c=config.load(p); c['test_mode']=True; c['vision_enabled']=True
            config.save(p,c)
            restored=config.load(p)
            self.assertNotIn('test_mode',restored); self.assertNotIn('vision_enabled',restored)
            self.assertGreater(config.profile(c,False)['global_cooldown'],config.profile(c,True)['global_cooldown'])
    def test_invalid_config(self):
        for key,value in [('lh_per_minute',float('nan')),('volume',True),('port',80)]:
            c=cfg(); c[key]=value
            with self.assertRaises(ValueError): config.validate(c)
    def test_gsi_preserves_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); path=root/'game/dota/cfg/gamestate_integration'; path.mkdir(parents=True)
            old=path/'gamestate_integration_dota_ai_coach.cfg'; old.write_text('baseline')
            new=config.install_gsi(root,cfg())
            self.assertEqual(old.read_text(),'baseline'); self.assertIn('32124',new.read_text())
            self.assertNotEqual(new.name,old.name)

class Rules02Tests(unittest.TestCase):
    def setUp(self): self.c=cfg(); self.p=config.profile(self.c,True); self.e=Engine()
    def events(self,t,lh=30,**kw): return self.e.evaluate(state(t,lh,**kw),self.c,self.p)
    def test_farm_hold_hysteresis_and_no_repeat(self):
        out=[]
        for t in range(300,340): out+=self.events(t,30)
        self.assertEqual([e.rule_id for e in out],['farm_low_v1'])
        # Rapid LH recovery remains high for the full hold.
        out=[]
        for t in range(340,360): out+=self.events(t,35)
        self.assertEqual([e.rule_id for e in out],['farm_recovered_v1'])
    def test_trend_without_universal_goal(self):
        self.c['lh_per_minute']=0; out=[]
        for t in range(300,381):
            lh=(t-300)//3 if t<340 else 13
            out+=self.events(t,lh)
        self.assertTrue(any(x.rule_id=='farm_low_v1' for x in out))
        low=next(x for x in out if x.rule_id=='farm_low_v1')
        self.assertEqual(low.evidence['reference_source'],'previous_window')
    def test_no_farm_without_lh_or_alive(self):
        for t in range(300,350):
            s=replace(state(t),alive=False)
            self.assertEqual(self.e.evaluate(s,self.c,self.p),[])
        for t in range(350,400): self.assertEqual(self.events(t,None),[])
    def test_trend_recovery_after_flat_previous_window(self):
        self.c['lh_per_minute']=0
        self.e.low=True; self.e.low_reference=5
        out=[]
        for t in range(300,360): out+=self.events(t,30 if t<345 else 35)
        self.assertTrue(any(x.rule_id=='farm_recovered_v1' for x in out))
    def test_initial_item_and_item_transition(self):
        s=state(); self.e.evaluate(s,self.c,self.p)
        item=replace(state(301),items={'slot0':{'name':'item_maelstrom'}})
        e=self.e.evaluate(item,self.c,self.p)
        self.assertEqual(e[0].rule_id,'item_power_spike_v1'); self.assertEqual(e[0].version,1)
        moved=replace(item,time=302,items={'slot2':{'name':'item_maelstrom'}})
        self.assertEqual(self.e.evaluate(moved,self.c,self.p),[])
        self.e=Engine(); self.assertEqual(self.e.evaluate(item,self.c,self.p),[])
    def test_stash_then_delivery_not_initial(self):
        self.events(300)
        s=replace(state(301),items={'stash0':{'name':'item_manta'}})
        self.assertEqual(self.e.evaluate(s,self.c,self.p),[])
        s=replace(s,time=302,items={'slot0':{'name':'item_manta'}})
        self.assertEqual(self.e.evaluate(s,self.c,self.p)[0].rule_id,'item_power_spike_v1')
    def test_death_pattern_not_each_death(self):
        self.c['lh_per_minute']=0
        self.events(300,deaths=0); self.events(310,deaths=1)
        self.assertEqual(self.events(320,deaths=2)[0].rule_id,'death_pattern_v1')
        self.assertEqual(self.events(330,deaths=3),[])
    def test_no_fabrication_from_death_jump(self):
        self.events(300,deaths=0)
        self.assertEqual(self.events(301,deaths=4),[])
    def test_buyback_gate_hold_and_unknown(self):
        p=config.profile(self.c,False)
        self.assertEqual(self.e.evaluate(state(300),self.c,p),[])
        self.assertEqual(self.e.evaluate(state(310,gold=0),self.c,p),[])
        self.e=Engine(); self.events(300,gold=1000)
        self.assertEqual(self.events(301,gold=0),[])
        self.assertEqual(self.events(303,gold=0),[])
        self.assertEqual(self.events(304,gold=0)[0].rule_id,'buyback_warning_v1')
        s=replace(state(310,gold=1000),buyback_cost=None)
        self.assertEqual(self.e.evaluate(s,self.c,self.p),[])
        self.assertEqual(self.events(320,gold=1000),[])
    def test_pause_new_match_rewind(self):
        for t in range(300,330): self.events(t)
        self.assertTrue(self.e.low)
        self.e.evaluate(replace(state(330),paused=True),self.c,self.p)
        self.assertTrue(self.e.low)
        self.events(1); self.assertFalse(self.e.low)
        self.e.evaluate(replace(state(350),match_id='new'),self.c,self.p)
        self.assertFalse(self.e.low)

class PolicyTests(unittest.TestCase):
    def setUp(self): self.p=Policy(); self.c=config.profile(cfg(),True)
    def test_priority_wins_batch(self):
        low=candidate(); high=candidate('buyback_warning_v1',4,'buyback:false')
        result=self.p.decide([low,high],300,self.c)
        self.assertEqual(result[0],(high,None)); self.assertEqual(result[1][1],'global_cooldown')
    def test_global_cooldown(self):
        self.p.decide([candidate()],300,self.c)
        result=self.p.decide([candidate('item_power_spike_v1',3,'item:x')],301,self.c)
        self.assertEqual(result[0][1],'global_cooldown')
    def test_critical_override(self):
        self.p.decide([candidate()],300,self.c)
        self.assertIsNone(self.p.decide([candidate('buyback_warning_v1',4,'bb')],301,self.c)[0][1])
    def test_rule_and_semantic_cooldown(self):
        self.p.decide([candidate()],300,self.c)
        self.assertEqual(self.p.decide([candidate()],301,self.c)[0][1],'semantic_cooldown')
        self.assertEqual(self.p.decide([candidate(key='different')],306,self.c)[0][1],'rule_cooldown')
    def test_duplicate_batch_and_reset(self):
        events=self.p.decide([candidate(),candidate()],300,self.c)
        self.assertEqual(events[1][1],'duplicate_batch')
        self.p.reset(); self.assertIsNone(self.p.decide([candidate()],300,self.c)[0][1])
    def test_disabled_logged(self): self.assertEqual(self.p.decide([candidate()],300,self.c,False)[0][1],'coach_disabled')

class FakeSpeech:
    """Synthetic adapter; never evidence that Windows audio actually played."""
    def play(self,job,emit):
        emit('voice_selected',{'name':'Synthetic','culture':'en-US','fallback':True})
        emit('started'); emit('spoken')

class BlockingSpeech:
    def __init__(self,started=False): self.entered=threading.Event(); self.release=threading.Event(); self.start=started
    def play(self,job,emit):
        if self.start: emit('started')
        self.entered.set()
        while not self.release.wait(.01):
            if job.cancel.is_set(): emit('cancelled',{'reason':job.cancel_reason}); return
        if not self.start: emit('started')
        emit('spoken')

class VoiceTests(unittest.TestCase):
    def test_voice_selection_fallback(self):
        default=dict(culture='en-US',name='English')
        pt=dict(culture='pt-BR',name='Portuguese')
        self.assertEqual(choose_voice([default,pt],default),pt)
        self.assertEqual(choose_voice([default],default),default)
    def test_priority_cancels_not_started(self):
        backend=BlockingSpeech(); records=[]
        v=Voice(lambda rid,e,d:records.append((rid,e,d)),backend)
        try:
            v.submit(Job(1,'low',50,1,time.monotonic(),'low')); self.assertTrue(backend.entered.wait(1))
            v.submit(Job(2,'high',50,4,time.monotonic(),'high'))
            wait_for(lambda:any(rid==1 and e=='cancelled' for rid,e,d in records))
            backend.release.set(); wait_for(lambda:any(rid==2 and e=='spoken' for rid,e,d in records))
        finally: backend.release.set(); v.close()
    def test_no_priority_interrupt_after_start_and_pending_evicted(self):
        backend=BlockingSpeech(started=True); records=[]
        v=Voice(lambda rid,e,d:records.append((rid,e,d)),backend)
        try:
            v.submit(Job(1,'speaking',50,1,time.monotonic(),'one')); backend.entered.wait(1)
            v.submit(Job(2,'pending',50,1,time.monotonic(),'two'))
            v.submit(Job(3,'critical',50,4,time.monotonic(),'three'))
            self.assertFalse(v.current.cancel.is_set())
            self.assertTrue(any(rid==2 and e=='skipped_priority' for rid,e,d in records))
            backend.release.set(); wait_for(lambda:any(rid==3 and e=='spoken' for rid,e,d in records))
        finally: backend.release.set(); v.close()
    def test_bounded_duplicate_queue(self):
        backend=BlockingSpeech(True); records=[]
        v=Voice(lambda rid,e,d:records.append((rid,e)),backend,capacity=1)
        try:
            v.submit(Job(1,'one',50,2,time.monotonic(),'one')); backend.entered.wait(1)
            v.submit(Job(2,'two',50,2,time.monotonic(),'two'))
            v.submit(Job(3,'two',50,2,time.monotonic(),'two'))
            v.submit(Job(4,'four',50,2,time.monotonic(),'four'))
            self.assertIn((3,'skipped_duplicate'),records); self.assertIn((4,'skipped_queue_full'),records)
        finally: backend.release.set(); v.close()
    def test_expiry(self):
        backend=BlockingSpeech(True); records=[]
        v=Voice(lambda rid,e,d:records.append((rid,e)),backend,ttl=.01)
        try:
            v.submit(Job(1,'one',50,2,time.monotonic(),'one')); backend.entered.wait(1)
            v.submit(Job(2,'two',50,2,time.monotonic(),'two'))
            time.sleep(.03); backend.release.set(); wait_for(lambda:(2,'expired') in records)
        finally: backend.release.set(); v.close()

def detection(visible=True,position=(.5,.5),valid=True):
    return dict(score=.99 if visible else .2,position=list(position),valid=valid)
def detections(mid=True,support=True,ally=True):
    return dict(enemy_mid=detection(mid,(.2,.2)),enemy_support_opposite=detection(support,(.3,.3)),
                allied_support=detection(ally,(.9,.9)),local_player=detection(True,(.5,.5)))

class SyntheticVisionTests(unittest.TestCase):
    """SYNTHETIC ONLY: algorithmic tests, not a real-Dota validation."""
    def setUp(self): self.c=cfg()['vision']; self.t=Temporal(self.c)
    def seed(self):
        for t in (0,.2,.4): self.t.update(detections(),t,4)
    def test_never_seen_is_unknown(self):
        for i in range(30): debug,out=self.t.update(detections(False,False),i*.2,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'UNKNOWN'); self.assertEqual(out,[])
    def test_multi_frame_and_debounce(self):
        debug,_=self.t.update(detections(),0,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'UNKNOWN')
        self.seed()
        debug,_=self.t.update(detections(False),.6,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'VISIBLE')
        self.t.update(detections(False),.8,4)
        debug,_=self.t.update(detections(False),1,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'MISSING')
    def test_one_call_no_repeat_then_rearm(self):
        self.seed(); calls=[]
        for i in range(3,61):
            debug,out=self.t.update(detections(False,False),i*.2,4); calls+=out
        self.assertEqual(len(calls),1); self.assertEqual(debug['gank_risk'],'VERY_HIGH')
        for i in range(61,65): self.t.update(detections(),i*.2,4)
        for i in range(65,100):
            _,out=self.t.update(detections(False),i*.2,4); calls+=out
        self.assertEqual(len(calls),2)
    def test_low_confidence_unknown_never_far(self):
        self.seed(); d=detections(); d['allied_support']['score']=.8
        debug,_=self.t.update(d,.6,4)
        self.assertEqual(debug['ally_support_state'],'UNKNOWN')
    def test_support_distance(self):
        for pos,expected in [((.51,.51),'WITH_US'),((.6,.5),'NEARBY'),((.9,.9),'FAR')]:
            tracker=Temporal(self.c); d=detections(); d['allied_support']['position']=pos
            for i in range(3): debug,_=tracker.update(d,i*.2,4)
            self.assertEqual(debug['ally_support_state'],expected)
    def test_capture_gap_and_anchor_loss_do_not_mean_missing(self):
        self.seed(); debug,out=self.t.update(detections(False,False),5,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'UNKNOWN'); self.assertEqual(out,[])
        self.seed(); d=detections(False); d['local_player']=detection(False)
        debug,out=self.t.update(d,.6,4)
        self.assertEqual(debug['entities']['enemy_mid']['state'],'UNKNOWN'); self.assertEqual(out,[])
    def test_actual_matcher_synthetic_pixels(self):
        import numpy as np
        rng=np.random.default_rng(123); frame=rng.integers(0,100,(200,200,3),dtype=np.uint8)
        template=rng.integers(0,255,(16,16,3),dtype=np.uint8); frame[70:86,50:66]=template
        matcher=Matcher({'enemy_mid':template},self.c); result=matcher.detect(frame)
        self.assertGreater(result['enemy_mid']['score'],.99); self.assertTrue(result['enemy_mid']['valid'])
        frame[120:136,100:116]=template
        result=matcher.detect(frame); self.assertFalse(result['enemy_mid']['valid'])
    def test_normal_mode_cannot_activate(self):
        with tempfile.TemporaryDirectory() as d:
            v=Vision(Path(d),lambda:{},lambda *a:None,lambda *a:None)
            try:
                with self.assertRaises(ValueError): v.activate(self.c,False)
                self.assertEqual(v.snapshot()['status'],'DISABLED')
            finally: v.close()

class Integration02Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name); self.c=config.load(self.path)
        self.s=Service(self.path,self.c,test_mode=True,backend=FakeSpeech())
    def tearDown(self): self.s.close(); self.tmp.cleanup()
    def send(self,s):
        self.s.ingest(s); self.s.messages.join()
    def test_event_voice_feedback_export(self):
        self.send(state(300)); self.send(replace(state(301),items={'slot0':{'name':'item_maelstrom'}}))
        wait_for(lambda:self.s.store.report()['summary']['spoken']==1)
        row=self.s.store.recent()[0]; rid=row['id']
        self.s.rate(rid,'boa'); self.s.messages.join()
        path=self.path/'report.json'; self.s.export(path); r=json.loads(path.read_text())
        record=r['recommendations'][0]
        for key in ('event_observed_at','recommendation_created_at','voice_queued_at','voice_started_at','voice_finished_at'):
            self.assertIsNotNone(record[key],key)
        self.assertGreaterEqual(record['recommendation_to_voice_latency_ms'],0)
        self.assertEqual(record['rating'],'boa'); self.assertEqual(record['mode'],'TEST')
        self.assertEqual(record['rule_version'],1); self.assertEqual(record['voice_fallback'],1)
        self.assertNotIn(self.c['token'],path.read_text())
        self.assertEqual(r['vision']['current']['status'],'DISABLED')
        import sqlite3
        with closing(sqlite3.connect(self.path/'coach02-test.sqlite3')) as db:
            self.assertEqual(db.execute('select rating from recommendations where id=?',(rid,)).fetchone()[0],'boa')
    def test_suppression_logged_with_snapshot(self):
        self.send(state(300))
        self.send(replace(state(301),items={'slot0':{'name':'item_maelstrom'},'slot1':{'name':'item_bfury'}}))
        report=self.s.store.report(); self.assertEqual(report['summary']['detected'],2)
        self.assertEqual(report['summary']['suppressed'],1)
        self.assertTrue(json.loads(report['recommendations'][1]['state_json'])['items'])
    def test_reset_new_match_and_rewind(self):
        self.send(state(300)); first=self.s.session
        self.send(state(1)); self.assertNotEqual(first,self.s.session)
        first=self.s.session; self.send(replace(state(2),match_id='another'))
        self.assertNotEqual(first,self.s.session)
    def test_http_real_receiver(self):
        from coach.gsi import start_receiver
        server,thread=start_receiver(0,self.c['token'],self.s.ingest,self.s.reject)
        try:
            p=payload(); p['auth']={'token':self.c['token']}
            with urlopen(Request(f'http://127.0.0.1:{server.server_port}/gsi',data=json.dumps(p).encode()),timeout=3) as response:
                self.assertEqual(response.status,200)
            self.s.messages.join(); self.assertEqual(self.s.snapshot()['state'].lh,10)
        finally: server.shutdown(); server.server_close(); thread.join()
    def test_settings_do_not_change_mode(self):
        c=copy.deepcopy(self.c); c['volume']=20; self.s.update_settings(c); self.s.messages.join()
        self.assertTrue(self.s.test_mode); self.assertFalse(self.s.vision.enabled)
    def test_vision_disabled_when_dead_or_alive_unknown(self):
        for alive in (False,None):
            self.send(replace(state(300),alive=alive))
            self.assertFalse(self.s.vision_context()['eligible'])
        self.send(replace(state(301),alive=True))
        self.assertTrue(self.s.vision_context()['eligible'])
    def test_shutdown_flushes_feedback(self):
        self.send(state(300)); self.send(replace(state(301),items={'slot0':{'name':'item_maelstrom'}}))
        rid=self.s.store.recent()[0]['id']
        self.s.rate(rid,'boa'); self.s.close()
        import sqlite3
        with closing(sqlite3.connect(self.path/'coach02-test.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT rating FROM recommendations WHERE id=?',(rid,)).fetchone()[0],'boa')
    def test_slow_voice_does_not_block_ingest(self):
        block=BlockingSpeech(True); self.s.voice.close(); self.s.voice=Voice(self.s.voice_report,block)
        try:
            self.send(state(300)); self.send(replace(state(301),items={'slot0':{'name':'item_maelstrom'}}))
            self.assertTrue(block.entered.wait(1))
            start=time.monotonic()
            self.send(state(302,99)); self.assertLess(time.monotonic()-start,.5)
            self.assertEqual(self.s.snapshot()['state'].lh,99)
        finally: block.release.set()

if __name__=='__main__': unittest.main()
