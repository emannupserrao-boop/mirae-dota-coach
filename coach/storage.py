"""Durable recommendation + snapshot + feedback, without Steam ID or GSI token."""
import json
import sqlite3
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS advice (
          id INTEGER PRIMARY KEY, created TEXT NOT NULL, session TEXT NOT NULL,
          source TEXT NOT NULL, rule_version TEXT NOT NULL, rule TEXT NOT NULL,
          text TEXT NOT NULL, state_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
          settings_json TEXT NOT NULL, rating TEXT,
          voice_status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS feedback (
          id INTEGER PRIMARY KEY, advice_id INTEGER NOT NULL,
          created TEXT NOT NULL, rating TEXT NOT NULL);
        ''')

    def record(self, session, source, advice, state, settings, version):
        public = {k:v for k,v in settings.items() if k != 'token'}
        with self.lock, self.db:
            c = self.db.execute('INSERT INTO advice(created,session,source,rule_version,rule,text,state_json,evidence_json,settings_json) VALUES(?,?,?,?,?,?,?,?,?)',
                (datetime.now(timezone.utc).isoformat(), session, source, version, advice.rule, advice.text,
                 json.dumps(state.to_dict(), ensure_ascii=False), json.dumps(advice.evidence), json.dumps(public)))
            return c.lastrowid

    def rate(self, advice_id, rating):
        if rating not in ('boa', 'ruim', 'irrelevante'):
            raise ValueError('Avaliação inválida')
        with self.lock, self.db:
            c = self.db.execute('UPDATE advice SET rating=? WHERE id=?', (rating, advice_id))
            if c.rowcount != 1:
                raise ValueError('Recomendação não encontrada')
            self.db.execute('INSERT INTO feedback(advice_id,created,rating) VALUES(?,?,?)',
                            (advice_id, datetime.now(timezone.utc).isoformat(), rating))

    def voice_status(self, advice_id, status):
        with self.lock, self.db:
            self.db.execute('UPDATE advice SET voice_status=? WHERE id=?', (status, advice_id))

    def recent(self, limit=100):
        with self.lock:
            rows = self.db.execute('SELECT id,created,source,text,rating,voice_status FROM advice ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            return rows

    def export(self, path):
        with self.lock:
            c = self.db.execute('SELECT * FROM advice ORDER BY id')
            keys = [d[0] for d in c.description]
            rows = [dict(zip(keys,row)) for row in c.fetchall()]
            c = self.db.execute('SELECT * FROM feedback ORDER BY id')
            keys = [d[0] for d in c.description]
            feedback = [dict(zip(keys,row)) for row in c.fetchall()]
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'schema_version':1,'recommendations':rows,'feedback_history':feedback}, f, ensure_ascii=False, indent=2)

    def close(self):
        with self.lock:
            self.db.close()
