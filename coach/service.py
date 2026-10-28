import threading
import time
import uuid
from .state import State
from .rules import Engine
from .storage import Store
from .voice import Voice
from .gsi import start_receiver


class Service:
    def __init__(self, directory, settings, source='live'):
        self.directory, self.settings, self.source = directory, dict(settings), source
        self.lock = threading.RLock()
        self.state, self.engine = State(), Engine()
        self.store = Store(directory / ('demo.sqlite3' if source == 'demo' else 'coach.sqlite3'))
        self.session = str(uuid.uuid4())
        self.last_received = None
        self.packets = 0
        self.rejected = 0
        self.error = ''
        self.last_advice = ''
        self.voice_error = ''
        self.stale_voice_cancelled = False
        self.voice = Voice(self.voice_report)
        self.server = None

    def voice_report(self, advice_id, status):
        if advice_id is not None:
            self.store.voice_status(advice_id, status)
        with self.lock:
            self.voice_error = status

    def reject(self, reason):
        with self.lock:
            self.rejected += 1
            self.error = reason

    def start(self):
        if self.source == 'live':
            self.server, self.thread = start_receiver(self.settings['port'], self.settings['token'], self.ingest, self.reject)

    def ingest(self, state):
        with self.lock:
            now = time.monotonic()
            if self.last_received is not None and now-self.last_received > 15:
                self.engine.reset()
                self.voice.cancel()
            if (self.state.hero != state.hero or self.state.match_id != state.match_id or
                (self.state.time is not None and state.time is not None and state.time < self.state.time)):
                self.session = str(uuid.uuid4())
                self.voice.cancel()
            if not state.active:
                self.voice.cancel()
            self.state = state
            self.last_received = now
            self.stale_voice_cancelled = False
            self.packets += 1
            self.error = ''
            for advice in self.engine.evaluate(state, self.settings):
                record_id = self.store.record(self.session, self.source, advice, state, self.settings, self.engine.VERSION)
                self.last_advice = advice.text
                if self.settings['voice']:
                    self.voice.say(record_id, advice.text, self.settings['volume'])
                else:
                    self.store.voice_status(record_id, 'muted')

    def snapshot(self):
        with self.lock:
            age = None if self.last_received is None else time.monotonic()-self.last_received
            if age is not None and age > 15 and not self.stale_voice_cancelled:
                self.voice.cancel()
                self.stale_voice_cancelled = True
            return dict(state=self.state, age=age, connected=age is not None and age <= 15,
                        packets=self.packets, rejected=self.rejected, error=self.error,
                        last_advice=self.last_advice, voice_status=self.voice_error)

    def export_diagnostic(self, path):
        import json
        import platform
        snap = self.snapshot()
        snap['state'] = snap['state'].to_dict()
        snap.update(app_version='0.1.0', platform=platform.platform(), source=self.source,
                    python=platform.python_version(), rule_version=self.engine.VERSION)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

    def update_settings(self, settings):
        with self.lock:
            self.settings = dict(settings)
            if not settings['voice'] or not settings['coach']:
                self.voice.cancel()

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
        self.voice.close()
        self.store.close()
