"""Process presence only, via Windows tasklist. Never opens the game process."""
import os
import subprocess
import threading


class Detector:
    def __init__(self):
        self.detected = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='process-detector')
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            if os.name == 'nt':
                try:
                    result = subprocess.run(['tasklist.exe', '/FI', 'IMAGENAME eq dota2.exe', '/FO', 'CSV', '/NH'],
                        capture_output=True, timeout=4, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.detected = b'"dota2.exe"' in result.stdout.lower() if result.returncode == 0 else None
                except (OSError, subprocess.TimeoutExpired):
                    self.detected = None
            self.stop.wait(5)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
