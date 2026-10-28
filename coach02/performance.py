import os
import threading
import time
from collections import deque
from .storage import utc

class Performance:
    """Metrics for our own PID + its TTS child only, never Dota."""
    def __init__(self):
        self.samples=deque(maxlen=720); self.lock=threading.Lock(); self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True,name='coach-performance'); self.thread.start()
    def run(self):
        try:
            import psutil
            process=psutil.Process(os.getpid()); known={process.pid:process}
            process.cpu_percent(None)
            while not self.stop.wait(2):
                children=process.children(recursive=True); live={process.pid}|{x.pid for x in children}
                for child in children:
                    if child.pid not in known: known[child.pid]=child; child.cpu_percent(None)
                total_cpu=0; rss=0; threads=0
                for pid,p in list(known.items()):
                    if pid not in live: del known[pid]; continue
                    try:
                        total_cpu+=p.cpu_percent(None); rss+=p.memory_info().rss; threads+=p.num_threads()
                    except psutil.Error: continue
                row=dict(at=utc(),cpu_percent_one_core=total_cpu,cpu_percent_machine=total_cpu/(os.cpu_count() or 1),
                         ram_mb=rss/1024/1024,threads=threads,includes_tts_child=True,
                         note='Amostragem a cada 2s; processos TTS muito curtos podem escapar.')
                with self.lock: self.samples.append(row)
        except Exception as exc:
            with self.lock: self.samples.append({'at':utc(),'error':type(exc).__name__,'status':'unavailable'})
    def report(self):
        with self.lock: rows=list(self.samples)
        valid=[r for r in rows if 'ram_mb' in r]
        return dict(samples=rows,latest=rows[-1] if rows else {},
                    peak_ram_mb=max((r['ram_mb'] for r in valid),default=None),
                    average_cpu_percent_machine=sum(r['cpu_percent_machine'] for r in valid)/len(valid) if valid else None,
                    peak_cpu_percent_machine=max((r['cpu_percent_machine'] for r in valid),default=None),
                    scope='app + sampled TTS child; not Dota; last 24 min')
    def close(self): self.stop.set(); self.thread.join(timeout=3)
