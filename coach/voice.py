"""Windows System.Speech in a cancellable worker; input is data, never code."""
import base64
import json
import os
import queue
import subprocess
import threading
import time

SCRIPT = '''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$d = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'pt-BR' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Volume = [int]$d.volume
$s.Speak([string]$d.text)
$s.Dispose()
'''


class Voice:
    def __init__(self, report):
        self.report = report
        self.pending = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.generation = 0
        self.thread = threading.Thread(target=self.run, daemon=True, name='voice')
        self.thread.start()

    def say(self, advice_id, text, volume):
        if os.name != 'nt':
            self.report(advice_id, 'unsupported_platform')
            return
        try:
            self.pending.put_nowait((advice_id, text, int(volume), time.monotonic(), self.generation))
        except queue.Full:
            self.report(advice_id, 'skipped_busy')

    def cancel(self):
        with self.lock:
            self.generation += 1
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def run(self):
        while not self.stop_event.is_set():
            try:
                advice_id, text, volume, created, generation = self.pending.get(timeout=.2)
            except queue.Empty:
                continue
            if time.monotonic()-created > 10 or generation != self.generation:
                self.report(advice_id, 'cancelled_or_expired')
                continue
            try:
                encoded = base64.b64encode(SCRIPT.encode('utf-16le')).decode('ascii')
                with self.lock:
                    if generation != self.generation or self.stop_event.is_set():
                        process = None
                    else:
                        self.process = subprocess.Popen(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        process = self.process
                if process is None:
                    self.report(advice_id, 'cancelled')
                    continue
                try:
                    process.communicate(json.dumps({'text':text, 'volume':volume}, ensure_ascii=False).encode('utf-8'), timeout=25)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RuntimeError('voice timeout')
                self.report(advice_id, 'spoken' if process.returncode == 0 else 'cancelled_or_failed')
            except Exception:
                self.report(advice_id, 'failed')
            finally:
                with self.lock:
                    self.process = None

    def close(self):
        self.stop_event.set()
        self.cancel()
        self.thread.join(timeout=4)
