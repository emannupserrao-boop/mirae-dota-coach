from contextlib import closing
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from coach.config import DEFAULTS, load, install_gsi, gsi_text
from coach.demo import payload
from coach.state import normalize
from coach.rules import Engine
from coach.service import Service
from coach.gsi import start_receiver


def settings(**kwargs):
    return dict(DEFAULTS, **{'voice':False, 'frequency':'frequente', **kwargs})


def state(t=300, lh=10, **player):
    return normalize(payload(t, lh, **player))


class StateTests(unittest.TestCase):
    def test_normal_snapshot(self):
        s = state()
        self.assertTrue(s.active)
        self.assertEqual((s.hero, s.lh, s.gpm, s.level), ('npc_dota_hero_juggernaut',10,400,5))
        self.assertTrue(s.buyback)
        self.assertEqual(s.abilities['ability0']['cooldown'], 0)

    def test_missing_is_not_zero(self):
        p = payload()
        p['player'].pop('gold')
        p['hero'].pop('buyback_cooldown')
        s = normalize(p)
        self.assertIsNone(s.gold)
        self.assertIsNone(s.buyback)

    def test_bad_numeric(self):
        p = payload(gpm=True, xpm='500', gold=float('nan'))
        s = normalize(p)
        self.assertEqual((s.gpm,s.xpm,s.gold), (None,None,None))

    def test_spectator_not_selected(self):
        p = payload()
        p['player'] = {'team2':{'player0':p['player']}}
        s = normalize(p)
        self.assertFalse(s.local)
        self.assertFalse(s.items)
        self.assertFalse(s.hero)

    def test_snapshot_removes_items(self):
        p = payload()
        self.assertTrue(normalize(p).items)
        p.pop('items')
        self.assertEqual(normalize(p).items, {})

    def test_explicit_nonplaying_activity_ignored(self):
        self.assertFalse(normalize(payload(activity='spectating')).local)

    def test_invalid_provider(self):
        with self.assertRaises(ValueError):
            normalize({'provider':{'appid':730}})


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.e, self.cfg = Engine(), settings()

    def test_farm_hysteresis_recovery(self):
        self.assertEqual(self.e.evaluate(state(), self.cfg), [])
        self.assertEqual(self.e.evaluate(state(329), self.cfg), [])
        self.assertEqual(self.e.evaluate(state(330), self.cfg)[0].rule, 'farm_low')
        self.assertEqual(self.e.evaluate(state(335), self.cfg), [])
        self.assertEqual(self.e.evaluate(state(350,30), self.cfg)[0].rule, 'farm_recovered')

    def test_pause_and_same_time(self):
        self.e.evaluate(state(), self.cfg)
        p = payload(400)
        p['map']['paused'] = True
        self.assertEqual(self.e.evaluate(normalize(p), self.cfg), [])
        self.assertEqual(self.e.evaluate(state(300), self.cfg), [])

    def test_item_baseline_and_new_item(self):
        p = payload(lh=100)
        p['items']['slot0']['name'] = 'item_bfury'
        self.assertEqual(self.e.evaluate(normalize(p), self.cfg), [])
        p['map']['clock_time'] = 320
        p['items']['slot1'] = {'name':'item_black_king_bar'}
        self.assertEqual(self.e.evaluate(normalize(p), self.cfg)[0].rule, 'item:item_black_king_bar')

    def test_item_moving_or_reappearing_no_repeat(self):
        p = payload(lh=100)
        self.e.evaluate(normalize(p), self.cfg)
        p['items']['slot0']['name'] = 'item_bfury'
        p['map']['clock_time'] = 320
        self.e.evaluate(normalize(p), self.cfg)
        p['map']['clock_time'] = 500
        p['items'] = {}
        self.e.evaluate(normalize(p), self.cfg)
        p['map']['clock_time'] = 510
        p['items']['stash0'] = {'name':'item_bfury'}
        self.assertFalse(any(a.rule.startswith('item:') for a in self.e.evaluate(normalize(p),self.cfg)))

    def test_death_spike_buyback(self):
        for change, rule in [('deaths','deaths'), ('level','power_spike'), ('gold','buyback')]:
            e = Engine()
            e.evaluate(state(300,100), self.cfg)
            p = payload(320,100)
            if change=='level': p['hero']['level']=6
            else: p['player'][change] = 4 if change=='deaths' else 100
            self.assertEqual(e.evaluate(normalize(p), self.cfg)[0].rule,rule)

    def test_next_item(self):
        cfg = settings(target_item='item_bfury', target_remaining_cost=1400)
        advice = self.e.evaluate(state(lh=100), cfg)
        self.assertEqual(advice[0].rule, 'near_item')

    def test_no_coach(self):
        cfg = settings(coach=False)
        for t in (300,340,400):
            self.assertEqual(self.e.evaluate(state(t),cfg),[])

    def test_missing_metrics_no_farm_warning(self):
        for t in (300,340,400):
            self.assertEqual(self.e.evaluate(state(t,None),self.cfg),[])

    def test_new_match_and_clock_reset(self):
        self.e.evaluate(state(),self.cfg)
        self.e.evaluate(state(330),self.cfg)
        self.assertTrue(self.e.farm_low)
        self.e.evaluate(state(10),self.cfg)
        self.assertFalse(self.e.farm_low)
        p = payload(400)
        p['map']['matchid']='new'
        self.assertEqual(self.e.evaluate(normalize(p),self.cfg),[])

    def test_gpm_and_xpm_sustained_drop(self):
        for metric in ('gpm','xpm'):
            e = Engine()
            out=[]
            for t in range(300, 546, 5):
                changes={metric:500 if t<460 else 300}
                out += e.evaluate(state(t,100,**changes),self.cfg)
            self.assertTrue(any(a.rule=='drop_'+metric.upper() for a in out))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory=Path(self.tmp.name)
        self.cfg=load(self.directory)
        self.cfg.update(voice=False, frequency='frequente')
        self.service=Service(self.directory,self.cfg)
        self.server, self.thread=start_receiver(0,self.cfg['token'],self.service.ingest,self.service.reject)
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.close()
        self.tmp.cleanup()

    def post(self,p, headers=None):
        req=Request(self.url+'/gsi',data=json.dumps(p).encode(),headers=headers or {'Content-Type':'application/json'})
        with urlopen(req,timeout=3) as r:
            return r.status

    def authenticated(self,t):
        p=payload(t)
        p['auth']={'token':self.cfg['token']}
        return p

    def test_http_to_advice_feedback_export_persistence(self):
        self.assertEqual(self.post(self.authenticated(300)),200)
        self.assertEqual(self.post(self.authenticated(335)),200)
        snap=self.service.snapshot()
        self.assertTrue(snap['connected'])
        self.assertEqual(snap['packets'],2)
        row=self.service.store.recent()[0]
        self.service.store.rate(row[0],'boa')
        self.service.store.rate(row[0],'irrelevante')
        path=self.directory/'export.json'
        self.service.store.export(path)
        data=json.loads(path.read_text())
        self.assertEqual(data['recommendations'][0]['rating'],'irrelevante')
        self.assertEqual(len(data['feedback_history']),2)
        self.assertEqual(json.loads(data['recommendations'][0]['state_json'])['time'],335)
        self.assertNotIn(self.cfg['token'],path.read_text())
        self.assertEqual(data['recommendations'][0]['voice_status'],'muted')
        import sqlite3
        with closing(sqlite3.connect(self.directory/'coach.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM advice').fetchone()[0],1)

    def test_wrong_token_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.post(payload())
        self.assertEqual(error.exception.code,403)
        self.assertEqual(self.service.snapshot()['packets'],0)

    def test_origin_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.post(self.authenticated(300),{'Origin':'https://example.test'})
        self.assertEqual(error.exception.code,400)

    def test_health_not_match_proof(self):
        with urlopen(self.url+'/health') as r:
            self.assertEqual(r.status,200)
        self.assertFalse(self.service.snapshot()['connected'])

    def test_malformed_and_oversized(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/gsi',data=b'{'),timeout=3)
        self.assertEqual(error.exception.code,400)

        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url+'/gsi',data=b'x'*262145),timeout=3)
        except ConnectionAbortedError as aborted:
            if os.name != 'nt' or getattr(aborted, 'winerror', None) != 10053:
                raise
        else:
            self.assertEqual(error.exception.code,413)

        self.assertEqual(self.service.snapshot()['packets'],0)
        self.assertEqual(self.post(self.authenticated(300)),200)
        snap = self.service.snapshot()
        # The serial receiver has finished both rejection callbacks before recovery.
        self.assertEqual(snap['rejected'],2)
        self.assertEqual(snap['packets'],1)
        self.assertTrue(snap['connected'])
        self.assertEqual(snap['state'].time,300)

    def test_stale_connection(self):
        self.post(self.authenticated(300))
        self.service.last_received -= 16
        self.assertFalse(self.service.snapshot()['connected'])
        self.post(self.authenticated(335))
        self.assertEqual(self.service.store.recent(),[])

    def test_diagnostic_without_advice_or_secrets(self):
        self.post(self.authenticated(300))
        path = self.directory/'diagnostic.json'
        self.service.export_diagnostic(path)
        data = json.loads(path.read_text())
        self.assertEqual(data['state']['lh'],10)
        self.assertEqual(data['packets'],1)
        self.assertNotIn(self.cfg['token'],path.read_text())

    def test_clock_rewind_starts_new_session(self):
        self.post(self.authenticated(300))
        session = self.service.session
        self.post(self.authenticated(1))
        self.assertNotEqual(self.service.session,session)

    def test_install_preserves_other_configs(self):
        root=self.directory/'dota 2 beta'
        folder=root/'game'/'dota'/'cfg'/'gamestate_integration'
        folder.mkdir(parents=True)
        other=folder/'gamestate_integration_other.cfg'
        other.write_text('keep')
        path=install_gsi(root,self.cfg)
        self.assertIn(self.cfg['token'],path.read_text())
        self.assertIn('127.0.0.1',path.read_text())
        self.assertEqual(other.read_text(),'keep')
        install_gsi(root,self.cfg)
        self.assertEqual(path.with_suffix('.cfg.bak').read_bytes(),path.read_bytes())


if __name__=='__main__':
    unittest.main()
