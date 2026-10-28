"""Experimental player-visible ROI matching. No game process access or gameplay inputs."""
import copy
import ctypes
from dataclasses import dataclass
import math
import os
import threading
import time
from collections import deque
from .rules import Candidate
from .storage import utc

ROLES=('enemy_mid','enemy_support_opposite','allied_support','local_player')

def visible_dota_roi(roi):
    """Check foreground window title/rectangle only; never open a process handle."""
    if os.name!='nt': return False
    from ctypes import wintypes
    u=ctypes.windll.user32
    u.GetForegroundWindow.restype=wintypes.HWND
    u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    u.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    u.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    hwnd=u.GetForegroundWindow(); title=ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd,title,256)
    if title.value.strip()!='Dota 2': return False
    rect=wintypes.RECT(); point=wintypes.POINT(0,0)
    if not u.GetClientRect(hwnd,ctypes.byref(rect)) or not u.ClientToScreen(hwnd,ctypes.byref(point)): return False
    x,y,w,h=roi
    return point.x<=x and point.y<=y and x+w<=point.x+rect.right and y+h<=point.y+rect.bottom

def capture_roi(roi):
    if not visible_dota_roi(roi): raise RuntimeError('Dota deve estar em primeiro plano e o ROI dentro da janela.')
    import mss
    import numpy as np
    x,y,w,h=roi
    start=time.perf_counter()
    with mss.mss() as screen:
        frame=np.array(screen.grab(dict(left=x,top=y,width=w,height=h)))[:,:,:3].copy()
    return frame,(time.perf_counter()-start)*1000

class Matcher:
    def __init__(self,templates,config):
        import cv2
        cv2.setNumThreads(1)
        self.templates=templates; self.config=config
    def detect(self,frame):
        import cv2
        import numpy as np
        result={}
        if frame.ndim!=3 or frame.shape[2]!=3 or frame.std()<8:
            return {role:dict(score=0,position=None,valid=False) for role in ROLES}
        for role in ROLES:
            template=self.templates.get(role)
            if template is None:
                result[role]=dict(score=0,position=None,valid=False); continue
            h,w=template.shape[:2]
            if h>frame.shape[0] or w>frame.shape[1] or template.std()<10:
                result[role]=dict(score=0,position=None,valid=False); continue
            scores=cv2.matchTemplate(frame,template,cv2.TM_CCOEFF_NORMED)
            _,best,_,position=cv2.minMaxLoc(scores)
            x,y=position
            masked=scores.copy()
            masked[max(0,y-h):y+h+1,max(0,x-w):x+w+1]=-1
            second=float(masked.max())
            ambiguous=best>=self.config['visible_threshold'] and best-second<self.config['ambiguity_margin']
            result[role]=dict(score=float(best) if math.isfinite(best) else 0,
                position=[(x+w/2)/frame.shape[1],(y+h/2)/frame.shape[0]],valid=not ambiguous,
                second_score=second,box=[x,y,w,h])
        # A patch matching multiple role templates is not proof of two heroes.
        for i,a in enumerate(ROLES):
            for b in ROLES[i+1:]:
                da,db=result[a],result[b]
                if da['score']>=self.config['visible_threshold'] and db['score']>=self.config['visible_threshold'] and da['position'] and db['position']:
                    if math.dist(da['position'],db['position'])<.04:
                        da['valid']=db['valid']=False
        return result

@dataclass
class Track:
    state: str='UNKNOWN'
    last_seen: float | None=None
    position: list | None=None
    score: float=0
    seen_frames: int=0
    absent_frames: int=0
    armed: bool=False
    episode: int=0
    def update(self,d,t,c):
        self.score=d['score']
        if not d['valid'] or c['absent_threshold']<self.score<c['visible_threshold']:
            self.state='UNKNOWN'; self.armed=False; self.seen_frames=0; self.absent_frames=0; self.position=None
        elif self.score>=c['visible_threshold']:
            self.absent_frames=0; self.seen_frames+=1
            if self.seen_frames>=c['confirm_frames']:
                if self.state!='VISIBLE': self.episode+=1
                self.state='VISIBLE'; self.armed=True; self.last_seen=t; self.position=d['position']
        else:
            self.seen_frames=0; self.absent_frames+=1; self.position=None
            if self.absent_frames>=c['confirm_frames']:
                self.state='MISSING' if self.armed else 'UNKNOWN'
        return dict(state=self.state,visible=True if self.state=='VISIBLE' else False if self.state=='MISSING' else None,
                    last_seen_monotonic=self.last_seen,missing_duration=max(0,t-self.last_seen) if self.state=='MISSING' and self.last_seen is not None else 0,
                    confidence=self.score,position=self.position,episode=self.episode)

class Temporal:
    def __init__(self,c): self.config=c; self.reset()
    def reset(self):
        self.tracks={r:Track() for r in ROLES}; self.last_frame=None
        self.alerted=set(); self.last_debug={}; self.missing_events=0; self.risk_events=0
    def update(self,detections,t,priority):
        if self.last_frame is not None and (t<=self.last_frame or t-self.last_frame>1):
            self.reset()
        self.last_frame=t; c=self.config
        # The local hero is an anchor: losing it suggests wrong/occluded capture.
        anchor=detections['local_player']
        if not anchor['valid'] or anchor['score']<c['visible_threshold']:
            detections={r:{'score':d['score'],'position':None,'valid':False} for r,d in detections.items()}
        before={r:x.state for r,x in self.tracks.items()}
        states={r:self.tracks[r].update(detections[r],t,c) for r in ROLES}
        self.missing_events+=sum(before[r]!='MISSING' and states[r]['state']=='MISSING' for r in ROLES[:2])
        ally,local=states['allied_support'],states['local_player']
        ally_state='UNKNOWN'
        if ally['state']=='VISIBLE' and local['state']=='VISIBLE' and ally['position'] and local['position']:
            distance=math.dist(ally['position'],local['position'])
            ally_state='WITH_US' if distance<=c['with_us_distance'] else 'NEARBY' if distance<=c['nearby_distance'] else 'FAR'
        missing=lambda r:states[r]['state']=='MISSING' and states[r]['missing_duration']>=c['missing_seconds']
        mid=missing('enemy_mid'); support=missing('enemy_support_opposite')
        risk='VERY_HIGH' if mid and support and ally_state=='FAR' else 'HIGH' if mid and support else 'MEDIUM' if mid else 'NONE'
        debug=dict(entities=states,ally_support_state=ally_state,gank_risk=risk,
                   missing_events=self.missing_events,gank_risk_events=self.risk_events,
                   confidence_mean=sum(x['confidence'] for x in states.values())/4,
                   source='visible_minimap_pixels',status='EXPERIMENTAL — BOT TEST ONLY')
        out=[]
        # One call per MID disappearance. Escalation is visible in debug, not repeated aloud.
        key=self.tracks['enemy_mid'].episode
        if mid and key not in self.alerted:
            self.alerted.add(key); self.risk_events+=1
            text='Mid e suporte sumiram do minimapa. Jogue mais recuado.' if support else 'Mid inimigo sumiu do minimapa. Cuidado com o gank.'
            out=[Candidate('enemy_missing_v1',f'enemy_missing:mid_episode:{key}',text,copy.deepcopy(debug),priority if support else min(priority,2))]
            debug['gank_risk_events']=self.risk_events
        self.last_debug=debug
        return debug,out

class Vision:
    """Dedicated ROI worker; starts only after explicit per-run bot-test activation."""
    def __init__(self,directory,get_context,on_result,on_error):
        self.directory=directory; self.get_context=get_context; self.on_result=on_result; self.on_error=on_error
        self.stop=threading.Event(); self.lock=threading.RLock(); self.enabled=False
        self.debug={'status':'DISABLED','reason':'Ative explicitamente em TEST MODE, após calibrar.'}
        self.preview=None; self.recent_frames=deque(maxlen=150); self.latencies=deque(maxlen=300)
        self.trace=deque(maxlen=600); self.last_trace=0
        self.templates={}; self.matcher=None; self.tracker=None; self.epoch=0
        self.thread=threading.Thread(target=self.run,daemon=True,name='minimap-vision'); self.thread.start()
    def activate(self,c,test_mode):
        if not test_mode: raise ValueError('Vision só pode ser ativado em TEST MODE contra bots.')
        import cv2
        templates={}
        for role in ROLES:
            path=self.directory/(role+'.png')
            if role in c['roles'] and path.exists():
                import numpy as np
                templates[role]=cv2.imdecode(np.frombuffer(path.read_bytes(),dtype=np.uint8),cv2.IMREAD_COLOR)
        if any(templates.get(role) is None for role in ROLES): raise ValueError('Calibre os quatro ícones antes de ativar.')
        with self.lock:
            self.config=copy.deepcopy(c); self.templates=templates
            self.matcher=Matcher(templates,c); self.tracker=Temporal(c); self.enabled=True; self.epoch+=1
            self.recent_frames.clear(); self.latencies.clear()
            self.debug={'status':'EXPERIMENTAL','reason':'Aguardando Dota em primeiro plano e partida sem pausa.'}
    def disable(self,reason='Desligado pelo usuário'):
        with self.lock:
            self.enabled=False; self.epoch+=1; self.debug={'status':'DISABLED','reason':reason}
    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.debug)
    def report(self):
        with self.lock:
            return dict(current=copy.deepcopy(self.debug),tracking_samples=copy.deepcopy(list(self.trace)),
                        sample_scope='Até 600 amostras, máximo 2 Hz, somente metadados; sem frames gravados.')
    def run(self):
        while not self.stop.is_set():
            with self.lock:
                enabled=self.enabled; epoch=self.epoch
                if enabled: c=self.config; matcher=self.matcher; tracker=self.tracker
            if not enabled: self.stop.wait(.2); continue
            start=time.monotonic()
            try:
                context=self.get_context()
                if not context['eligible'] or not visible_dota_roi(c['roi']):
                    tracker.reset()
                    with self.lock:
                        if epoch==self.epoch: self.debug=dict(status='EXPERIMENTAL / SUSPENDED',reason='Pausa, GSI sem sinal ou Dota fora de primeiro plano; entidades UNKNOWN.')
                    self.stop.wait(.2); continue
                frame,capture_ms=capture_roi(c['roi'])
                vision_start=time.perf_counter(); detections=matcher.detect(frame)
                debug,events=tracker.update(detections,time.monotonic(),context['priority'])
                processing_ms=(time.perf_counter()-vision_start)*1000
                with self.lock:
                    if epoch!=self.epoch: continue
                    self.preview=frame; now=time.monotonic(); self.recent_frames.append(now)
                    self.latencies.append((capture_ms,processing_ms))
                    span=now-self.recent_frames[0]
                    debug.update(capture_fps=(len(self.recent_frames)-1)/span if span>0 else 0,
                        requested_fps=c['fps'],capture_latency_ms=capture_ms,vision_processing_ms=processing_ms,
                        capture_average_ms=sum(x[0] for x in self.latencies)/len(self.latencies),
                        processing_average_ms=sum(x[1] for x in self.latencies)/len(self.latencies),
                        captured_at=utc(),game_time=context['game_time'],active=True)
                    self.debug=debug
                    if now-self.last_trace>=.5:
                        self.trace.append(copy.deepcopy(debug)); self.last_trace=now
                self.on_result(events,debug,context['session'],epoch)
            except Exception as exc:
                self.on_error('vision',type(exc).__name__+': '+str(exc))
                self.disable('Erro de captura/detecção; confira o diagnóstico.')
            self.stop.wait(max(.001,1/c['fps']-(time.monotonic()-start)))
    def close(self):
        self.stop.set(); self.thread.join(timeout=3)
