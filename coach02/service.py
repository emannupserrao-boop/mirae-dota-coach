"""GSI callback queues bounded work. One engine worker owns rules and SQLite writes."""
import copy
from collections import deque
import json
import logging
import platform
import queue
import threading
import time
import uuid
from coach.gsi import start_receiver
from coach.state import State
from . import config
from .rules import Engine
from .policy import Policy
from .storage import Store,utc
from .voice import Voice,Job
from .vision import Vision
from .performance import Performance

class Service:
    def __init__(self,directory,settings,test_mode=False,backend=None):
        self.directory=directory; self.settings=copy.deepcopy(settings); self.test_mode=test_mode
        self.mode='TEST' if test_mode else 'NORMAL'; self.source='live'; self.closed=False
        self.run_id=str(uuid.uuid4()); self.session=str(uuid.uuid4())
        self.lock=threading.RLock(); self.messages=queue.Queue(maxsize=256); self.voice_messages=queue.SimpleQueue()
        self.state=State(); self.last_received=None; self.packets=0; self.rejected=0; self.dropped=0
        self.error=''; self.errors=deque(maxlen=100); self.latest=None; self.rows=[]; self.voice_status='pronta'
        self.engine=Engine(); self.policy=Policy(); self.engine_debug={}; self.server=None
        self.store=Store(directory/('coach02-test.sqlite3' if test_mode else 'coach02.sqlite3'))
        self.stop=threading.Event(); self.work_done=threading.Event(); self.stale_handled=False
        self.voice=Voice(self.voice_report,backend=backend)
        self.vision=Vision(directory,self.vision_context,self.vision_result,self.issue)
        self.performance=Performance(); self.pending_reset=False
        self.worker=threading.Thread(target=self.run,daemon=True,name='coach-engine'); self.worker.start()
    def start(self):
        self.server,self.http_thread=start_receiver(self.settings['port'],self.settings['token'],self.ingest,self.reject)
    def ingest(self,state):
        observed=utc(); received=time.monotonic()
        with self.lock:
            self.packets+=1
        try: self.messages.put_nowait(('state',state,observed,received))
        except queue.Full:
            with self.lock: self.dropped+=1; self.pending_reset=True
            self.issue('gsi_backpressure','Fila de processamento cheia; baseline será reiniciado.')
    def reject(self,reason):
        with self.lock: self.rejected+=1
        self.issue('gsi_rejected',reason)
    def issue(self,kind,message):
        row=dict(at=utc(),kind=kind,message=message)
        with self.lock: self.error=message; self.errors.append(row)
        self.voice_messages.put(('diagnostic',None,kind,row))
    def voice_report(self,rid,event,details):
        self.voice_messages.put(('voice',rid,event,details))
    def vision_context(self):
        with self.lock:
            age=time.monotonic()-self.last_received if self.last_received is not None else 1e9
            return dict(eligible=self.state.active and self.state.alive is True and age<3 and self.test_mode,
                        session=self.session,priority=self.settings['priorities']['enemy_missing_v1'],game_time=self.state.time)
    def vision_result(self,events,debug,session,epoch):
        if events:
            try: self.messages.put_nowait(('vision',events,debug,session,epoch,utc(),time.monotonic()))
            except queue.Full: self.issue('vision_backpressure','Evento visual descartado por fila cheia.')
    def command(self,kind,*args):
        try: self.messages.put_nowait((kind,*args)); return True
        except queue.Full: self.issue('control_backpressure','Controle não aplicado; tente novamente.'); return False
    def update_settings(self,c):
        config.validate(c)
        if c['port']!=self.settings['port'] or c['token']!=self.settings['token']: raise ValueError('Porta/token exigem reinício; não altere durante execução.')
        return self.command('settings',copy.deepcopy(c))
    def rate(self,rid,rating): return self.command('rate',rid,rating)
    def test_voice(self):
        with self.lock:
            if not self.settings['voice']: return False
            volume=self.settings['volume']
        self.voice.submit(Job(None,'Dota AI Coach pronto. Este é um teste de voz.',volume,1,time.monotonic(),'voice_test'))
        return True
    def reset(self,reason,new_session=True):
        self.engine.reset(); self.policy.reset(); self.voice.cancel(reason,interrupt=True)
        if new_session:
            self.session=str(uuid.uuid4()); self.vision.disable('Nova sessão: confira e recalibre os ícones antes de ativar.')
        with self.lock: self.latest=None
        self.store.diagnostic(self.run_id,'engine_reset',{'reason':reason,'session_id':self.session})
    def decisions(self,events,observed,received):
        c=self.settings; p=config.profile(c,self.test_mode)
        for candidate,reason in self.policy.decide(events,self.state.time,p,c['coach']):
            mono=time.monotonic()
            rid=self.store.record(self.run_id,self.session,self.mode,'live',candidate,self.state,c,observed,(mono-received)*1000,reason)
            if reason is None:
                with self.lock: self.latest=dict(id=rid,text=candidate.text,rule_id=candidate.rule_id,priority=candidate.priority)
                if c['voice']: self.voice.submit(Job(rid,candidate.text,c['volume'],candidate.priority,mono,candidate.semantic_key))
                else: self.store.voice(rid,'muted',{'at':utc(),'reason':'voice_disabled'})
    def process(self,message):
        kind=message[0]
        if kind=='state':
            _,s,observed,received=message
            if time.monotonic()-received>2:
                self.pending_reset=True; self.dropped+=1; return
            old=self.state
            new_session=old.local and (old.match_id!=s.match_id or old.hero!=s.hero or not s.local or
                        (old.time is not None and s.time is not None and s.time<old.time) or
                        (old.phase=='DOTA_GAMERULES_STATE_GAME_IN_PROGRESS' and s.phase!='DOTA_GAMERULES_STATE_GAME_IN_PROGRESS'))
            gap=self.last_received is not None and received-self.last_received>15
            if new_session or gap or self.pending_reset:
                self.reset('new_match_or_rewind' if new_session else 'gsi_gap_or_overload',new_session=new_session)
                self.pending_reset=False
            with self.lock: self.state=s; self.last_received=received; self.stale_handled=False
            if not s.active: self.voice.cancel('paused_or_inactive',interrupt=False)
            events=self.engine.evaluate(s,self.settings,config.profile(self.settings,self.test_mode))
            if events: self.decisions(events,observed,received)
            with self.lock: self.engine_debug=copy.deepcopy(self.engine.debug)
        elif kind=='vision':
            _,events,debug,session,epoch,observed,received=message
            if session!=self.session or epoch!=self.vision.epoch or not self.vision.enabled or not self.vision_context()['eligible'] or time.monotonic()-received>2:
                self.store.diagnostic(self.run_id,'vision_event_discarded',{'reason':'context_changed_or_stale'})
            else: self.decisions(events,observed,received)
        elif kind=='settings':
            new=message[1]; old=self.settings
            rules_changed=any(new[k]!=old[k] for k in ('normal','test','lh_per_minute','important_items','priorities'))
            vision_changed=new['vision']!=old['vision']
            config.save(self.directory,new)
            with self.lock: self.settings=new
            if rules_changed: self.reset('rule_settings_changed',new_session=False)
            if vision_changed: self.vision.disable('Configuração visual alterada; reative após calibrar.')
            if not new['voice'] or not new['coach']: self.voice.cancel('user_disabled',interrupt=True)
        elif kind=='rate': self.store.rate(message[1],message[2])
        elif kind=='mark_vision': self.store.diagnostic(self.run_id,'vision_manual_label',message[1])
    def drain_voice(self):
        while True:
            try: kind,rid,event,details=self.voice_messages.get_nowait()
            except queue.Empty: break
            if kind=='voice':
                self.store.voice(rid,event,details)
                if rid is None: self.store.diagnostic(self.run_id,'voice_test_event',dict(event=event,**details))
                with self.lock: self.voice_status=event
                if event=='failed': self.store.diagnostic(self.run_id,'tts_failure',details)
            else: self.store.diagnostic(self.run_id,event,details)
    def run(self):
        last_refresh=0
        try:
            while not self.stop.is_set() or not self.messages.empty():
                try:
                    message=self.messages.get(timeout=.1)
                    try: self.process(message)
                    finally: self.messages.task_done()
                except queue.Empty: pass
                except Exception as exc:
                    logging.exception('Erro no worker do coach')
                    self.issue('engine_error',type(exc).__name__+': '+str(exc))
                try:
                    self.drain_voice()
                    if self.last_received is not None and time.monotonic()-self.last_received>15 and not self.stale_handled:
                        self.voice.cancel('gsi_stale',interrupt=False); self.stale_handled=True
                    if time.monotonic()-last_refresh>.5:
                        rows=self.store.recent()
                        with self.lock: self.rows=rows
                        last_refresh=time.monotonic()
                except Exception as exc:
                    logging.exception('Erro de persistência')
                    with self.lock: self.error='Falha SQLite: '+type(exc).__name__
        finally:
            try: self.drain_voice()
            finally: self.work_done.set()
    def snapshot(self):
        with self.lock:
            age=None if self.last_received is None else time.monotonic()-self.last_received
            return dict(state=self.state,age=age,connected=age is not None and age<=15,packets=self.packets,
                        rejected=self.rejected,dropped=self.dropped,error=self.error,latest=copy.deepcopy(self.latest),
                        voice_status=self.voice_status,rows=copy.deepcopy(self.rows),engine_debug=copy.deepcopy(self.engine_debug),
                        mode=self.mode,run_id=self.run_id,session_id=self.session)
    def export(self,path):
        # Called by a separate UI worker so disk serialization never freezes the UI.
        deadline=time.monotonic()+3
        while (self.messages.unfinished_tasks or not self.voice_messages.empty()) and time.monotonic()<deadline: time.sleep(.02)
        snap=self.snapshot(); snap['state']=snap['state'].to_dict(); snap.pop('rows',None)
        report=self.store.report(self.run_id)
        with self.lock: errors=list(self.errors)
        report.update(app_version='0.2.0',platform=platform.platform(),python=platform.python_version(),
                      runtime=snap,errors=errors,vision=self.vision.report(),performance=self.performance.report(),
                      latency_definition='Received GSI event -> decision -> System.Speech SpeakStarted; not acoustic latency.',
                      teamfight_detection='UNSUPPORTED: no reliable combat classifier',
                      scope='current application run; multiple match sessions identified separately')
        with open(path,'w',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,indent=2)
    def close(self):
        if self.closed: return
        self.closed=True
        if self.server:
            self.server.shutdown(); self.server.server_close(); self.http_thread.join(timeout=3)
        self.vision.close(); self.voice.close(); self.performance.close()
        self.stop.set(); self.worker.join()
        self.store.close()
