"""Bounded priority queue. System.Speech events measure synthesis, not acoustic output."""
import base64
from dataclasses import dataclass, field
import json
import os
import queue
import subprocess
import threading
import time
from .storage import utc

# Event handlers are C#, not PowerShell scriptblocks on a background thread.
SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[System.Text.Encoding]::UTF8
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
$d=[Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$src=@'
using System;
using System.Speech.Synthesis;
using System.Threading;
public static class CoachSpeaker {
  static void Mark(string type) { Console.WriteLine(type+"|"+DateTimeOffset.UtcNow.ToString("o")); Console.Out.Flush(); }
  public static void Run(string text, int volume) {
    using (SpeechSynthesizer s=new SpeechSynthesizer()) {
      foreach (InstalledVoice v in s.GetInstalledVoices()) {
        if(v.Enabled && v.VoiceInfo.Culture.Name=="pt-BR") { s.SelectVoice(v.VoiceInfo.Name); break; }
      }
      Console.WriteLine("VOICE|"+s.Voice.Culture.Name+"|"+s.Voice.Name); Console.Out.Flush();
      s.Volume=volume; s.SetOutputToDefaultAudioDevice();
      using (ManualResetEvent done=new ManualResetEvent(false)) {
        s.SpeakStarted += (o,e)=>Mark("START");
        s.SpeakCompleted += (o,e)=>{ Mark(e.Error==null && !e.Cancelled ? "END" : "ERROR"); done.Set(); };
        s.SpeakAsync(text);
        if (!done.WaitOne(30000)) { s.SpeakAsyncCancelAll(); Mark("ERROR"); }
      }
    }
  }
}
'@
Add-Type -TypeDefinition $src -ReferencedAssemblies System.Speech
[CoachSpeaker]::Run([string]$d.text,[int]$d.volume)
'''

def choose_voice(voices,default):
    """Selection contract, mirrored by the small Windows adapter above."""
    return next((v for v in voices if v.get('enabled',True) and v.get('culture')=='pt-BR'),default)

class WindowsBackend:
    def play(self,job,emit):
        if os.name!='nt': emit('failed',{'reason':'windows_tts_unavailable'}); return
        encoded=base64.b64encode(SCRIPT.encode('utf-16le')).decode()
        process=subprocess.Popen(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        events=queue.Queue(); complete=False; started=False
        def read():
            for line in process.stdout: events.put(line.decode('utf-8',errors='replace').strip())
            events.put(None)
        reader=threading.Thread(target=read,daemon=True); reader.start()
        try:
            process.stdin.write(json.dumps({'text':job.text,'volume':job.volume},ensure_ascii=False).encode('utf-8'))
            process.stdin.close()
            deadline=time.monotonic()+35
            while True:
                if job.cancel.is_set():
                    process.terminate(); emit('cancelled',{'reason':job.cancel_reason}); return
                if time.monotonic()>deadline:
                    process.kill(); emit('failed',{'reason':'tts_timeout'}); return
                try: line=events.get(timeout=.05)
                except queue.Empty: continue
                if line is None: break
                parts=line.split('|',2)
                if parts[0]=='VOICE' and len(parts)==3:
                    emit('voice_selected',{'culture':parts[1],'name':parts[2],'fallback':parts[1]!='pt-BR'})
                elif parts[0]=='START' and len(parts)>=2:
                    started=True; emit('started',{'at':parts[1]})
                elif parts[0]=='END' and len(parts)>=2:
                    complete=True; emit('spoken',{'at':parts[1]})
                elif parts[0]=='ERROR': emit('failed',{'reason':'synthesis_error'}); return
            if not complete: emit('failed',{'reason':'no_completion_event','start_seen':started})
        finally:
            if process.poll() is None:
                try: process.wait(timeout=1)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
            reader.join(timeout=1)
            process.stdout.close()

@dataclass
class Job:
    rid: int | None
    text: str
    volume: int
    priority: int
    created_mono: float
    key: str
    queued_mono: float=field(default_factory=time.monotonic)
    started: bool=False
    cancel: threading.Event=field(default_factory=threading.Event)
    cancel_reason: str=''

class Voice:
    def __init__(self,report,backend=None,capacity=3,ttl=15):
        self.report=report; self.backend=backend or WindowsBackend()
        self.capacity=capacity; self.ttl=ttl; self.pending=[]; self.current=None
        self.cv=threading.Condition(); self.stopping=False
        self.thread=threading.Thread(target=self.run,daemon=True,name='voice02'); self.thread.start()
    def event(self,job,event,details=None):
        d={'at':utc(),**(details or {})}
        if event=='started':
            with self.cv: job.started=True
            d['latency_ms']=round((time.monotonic()-job.created_mono)*1000,3)
        self.report(job.rid,event,d)
    def submit(self,job):
        with self.cv:
            if self.stopping: self.event(job,'cancelled',{'reason':'shutdown'}); return
            if any(x.key==job.key for x in self.pending) or (self.current and self.current.key==job.key and not self.current.cancel.is_set()):
                self.event(job,'skipped_duplicate',{'reason':'voice_queue_semantic_duplicate'}); return
            for old in list(self.pending):
                if old.priority<job.priority:
                    self.pending.remove(old); self.event(old,'skipped_priority',{'reason':'higher_priority_pending'})
            if self.current and not self.current.started and self.current.priority<job.priority:
                self.current.cancel_reason='higher_priority_before_start'; self.current.cancel.set()
            if len(self.pending)>=self.capacity:
                self.event(job,'skipped_queue_full',{'reason':'bounded_queue'}); return
            job.queued_mono=time.monotonic()
            self.pending.append(job); self.event(job,'queued'); self.cv.notify()
    def cancel(self,reason='user_disabled',interrupt=False):
        with self.cv:
            for job in self.pending: self.event(job,'cancelled',{'reason':reason})
            self.pending.clear()
            if self.current and (interrupt or not self.current.started):
                self.current.cancel_reason=reason; self.current.cancel.set()
    def run(self):
        while True:
            with self.cv:
                self.cv.wait_for(lambda:self.pending or self.stopping)
                if self.stopping: return
                self.pending.sort(key=lambda j:(-j.priority,j.queued_mono))
                job=self.pending.pop(0); self.current=job
            try:
                if time.monotonic()-job.queued_mono>self.ttl: self.event(job,'expired',{'reason':'queue_ttl'})
                else: self.backend.play(job,lambda e,d=None:self.event(job,e,d))
            except Exception as exc: self.event(job,'failed',{'reason':type(exc).__name__})
            finally:
                with self.cv: self.current=None
    def close(self):
        self.cancel('shutdown',interrupt=True)
        with self.cv: self.stopping=True; self.cv.notify_all()
        self.thread.join(timeout=5)
