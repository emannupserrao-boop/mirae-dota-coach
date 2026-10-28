import json
import sqlite3
import threading
from datetime import datetime, timezone

def utc(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

class Store:
    def __init__(self,path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS recommendations(
          id INTEGER PRIMARY KEY, run_id TEXT, session_id TEXT, mode TEXT, source TEXT,
          rule_id TEXT, rule_version INTEGER, engine_version TEXT, priority INTEGER,
          semantic_key TEXT, text TEXT, event_observed_at TEXT, recommendation_created_at TEXT,
          event_to_decision_ms REAL, game_time REAL, state_json TEXT, evidence_json TEXT, settings_json TEXT,
          status TEXT, suppression_reason TEXT, voice_status TEXT, voice_queued_at TEXT,
          voice_started_at TEXT, voice_finished_at TEXT, voice_terminal_at TEXT,
          recommendation_to_voice_latency_ms REAL, voice_name TEXT, voice_fallback INTEGER,
          rating TEXT);
        CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, recommendation_id INTEGER REFERENCES recommendations(id),
          created_at TEXT, rating TEXT);
        CREATE TABLE IF NOT EXISTS voice_events(id INTEGER PRIMARY KEY, recommendation_id INTEGER REFERENCES recommendations(id),
          created_at TEXT, event TEXT, details_json TEXT);
        CREATE TABLE IF NOT EXISTS diagnostics(id INTEGER PRIMARY KEY, run_id TEXT, created_at TEXT, kind TEXT, details_json TEXT);
        CREATE INDEX IF NOT EXISTS rec_run ON recommendations(run_id);
        ''')

    def record(self,run_id,session,mode,source,event,state,settings,observed,decision_ms,reason):
        safe={k:v for k,v in settings.items() if k!='token'}
        with self.lock,self.db:
            c=self.db.execute('''INSERT INTO recommendations(run_id,session_id,mode,source,rule_id,rule_version,
              engine_version,priority,semantic_key,text,event_observed_at,recommendation_created_at,event_to_decision_ms,
              game_time,state_json,evidence_json,settings_json,status,suppression_reason,voice_status)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (run_id,session,mode,source,event.rule_id,event.version,'alpha-0.2.0',event.priority,event.semantic_key,event.text,
               observed,utc(),decision_ms,state.time,json.dumps(state.to_dict()),json.dumps(event.evidence),json.dumps(safe),
               'suppressed' if reason else 'accepted',reason,'not_scheduled' if reason else 'pending'))
            return c.lastrowid

    def voice(self,rid,event,details):
        with self.lock,self.db:
            self.db.execute('INSERT INTO voice_events(recommendation_id,created_at,event,details_json) VALUES(?,?,?,?)',
                            (rid,details.get('at',utc()),event,json.dumps(details)))
            values={'voice_status':event}
            if event=='queued': values['voice_queued_at']=details['at']
            elif event=='started':
                values.update(voice_started_at=details['at'],recommendation_to_voice_latency_ms=details['latency_ms'])
            elif event=='spoken': values['voice_finished_at']=details['at']
            elif event=='voice_selected':
                values={'voice_name':details.get('name'), 'voice_fallback':int(details.get('fallback',False))}
            else: values['voice_terminal_at']=details.get('at',utc())
            if rid is not None:
                assignments=','.join(k+'=?' for k in values)
                self.db.execute(f'UPDATE recommendations SET {assignments} WHERE id=?',(*values.values(),rid))

    def rate(self,rid,rating):
        if rating not in ('boa','ruim','irrelevante'): raise ValueError('Avaliação inválida')
        with self.lock,self.db:
            c=self.db.execute("UPDATE recommendations SET rating=? WHERE id=? AND status='accepted'",(rating,rid))
            if c.rowcount!=1: raise ValueError('Recomendação não encontrada')
            self.db.execute('INSERT INTO feedback(recommendation_id,created_at,rating) VALUES(?,?,?)',(rid,utc(),rating))

    def diagnostic(self,run_id,kind,details):
        with self.lock,self.db:
            self.db.execute('INSERT INTO diagnostics(run_id,created_at,kind,details_json) VALUES(?,?,?,?)',
                            (run_id,utc(),kind,json.dumps(details)))

    def recent(self,limit=100):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM recommendations WHERE status='accepted' ORDER BY id DESC LIMIT ?",(limit,))]

    def report(self,run_id=None):
        with self.lock:
            where=' WHERE run_id=?' if run_id else ''
            params=(run_id,) if run_id else ()
            rows=[dict(r) for r in self.db.execute('SELECT * FROM recommendations'+where+' ORDER BY id',params)]
            ids=[r['id'] for r in rows]
            # SQL join avoids variable count limits in long sessions.
            suffix=' WHERE r.run_id=?' if run_id else ''
            fb=[dict(r) for r in self.db.execute('SELECT f.* FROM feedback f JOIN recommendations r ON r.id=f.recommendation_id'+suffix,params)]
            voices=[dict(r) for r in self.db.execute('SELECT v.* FROM voice_events v JOIN recommendations r ON r.id=v.recommendation_id'+suffix,params)]
            diagnostics=[dict(r) for r in self.db.execute('SELECT * FROM diagnostics'+where,params)]
        from collections import Counter
        latency=[r['recommendation_to_voice_latency_ms'] for r in rows if r['recommendation_to_voice_latency_ms'] is not None]
        suppressed=Counter(r['suppression_reason'] for r in rows if r['status']=='suppressed')
        return dict(schema_version=2,recommendations=rows,feedback_history=fb,voice_events=voices,diagnostics=diagnostics,
                    summary=dict(detected=len(rows),accepted=sum(r['status']=='accepted' for r in rows),
                      spoken=sum(r['voice_status']=='spoken' for r in rows),suppressed=sum(suppressed.values()),
                      suppression_reasons=dict(suppressed),voice_status_counts=dict(Counter(r['voice_status'] for r in rows)),
                      feedback=dict(Counter(r['rating'] for r in rows if r['rating'])),
                      voice_latency_average_ms=sum(latency)/len(latency) if latency else None,
                      voice_latency_max_ms=max(latency) if latency else None,
                      voice_latency_samples=len(latency),voice_fallback_count=sum(r['voice_fallback']==1 for r in rows)))

    def close(self):
        with self.lock: self.db.close()
