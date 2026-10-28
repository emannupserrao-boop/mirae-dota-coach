"""SYNTHETIC isolated capture, hook compatibility and failure tests."""
import ast
from dataclasses import asdict
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from coach import gsi
from coach.state import normalize
from coach02 import shadow_runtime_v01 as runtime
from coach02 import shadow_journal_v01 as journal
from coach02 import live_runtime_v01 as live
from test_live_runtime_v01 import payload,policy

class Clock:
    def __init__(self): self.value=0
    def __call__(self): return self.value
class MemoryWriter:
    def __init__(self): self.records=[]; self.record_sequence=0; self.fail=False; self.closed=False
    def append(self,records):
        if self.fail: raise OSError('disk')
        self.records.extend(records); self.record_sequence=records[-1].record_sequence
    def close(self): self.closed=True
def capture():
    clock=Clock(); writer=MemoryWriter()
    state=runtime.ShadowCaptureV1(run_id='run',policy=policy(),writer=writer,clock=clock,origin='SYNTHETIC')
    clock.value=10
    return state,writer,clock
def outcome(raw=None):
    raw=payload() if raw is None else raw
    return dict(classification='accepted',payload=raw,state=normalize(raw),http_status=200)

class ShadowRuntimeTests(unittest.TestCase):
    def test_capture_commits_after_journal(self):
        c,w,clock=capture(); c.request_hook(outcome()); self.assertEqual(c.state.receive_sequence,1)
        self.assertEqual(len(w.records),4); self.assertEqual(c.parity_checks,1)
    def test_failed_write_not_published(self):
        c,w,clock=capture(); old=c.state; w.fail=True
        with self.assertRaises(OSError): c.request_hook(outcome())
        self.assertEqual(c.state,old); self.assertTrue(c.failed.is_set())
    def test_failed_capture_cannot_continue(self):
        c,w,clock=capture(); w.fail=True
        with self.assertRaises(OSError): c.request_hook(outcome())
        w.fail=False
        with self.assertRaises(RuntimeError): c.request_hook(outcome())
    def test_failed_capture_cannot_finish(self):
        c,w,clock=capture(); c.failed.set()
        with self.assertRaises(RuntimeError): c.finish()
    def test_normalization_parity_failure_blocks(self):
        c,w,clock=capture(); value=outcome(); value['state']=normalize(payload('optional_absent'))
        with self.assertRaises(RuntimeError): c.request_hook(value)
        self.assertTrue(c.failed.is_set()); self.assertEqual(c.state.receive_sequence,0)
    def test_no_unsafe_rejected_payload_in_journal(self):
        c,w,clock=capture(); c.request_hook(dict(classification='auth',payload='secret',http_status=403))
        self.assertNotIn('secret',''.join(r.content_json for r in w.records))
        self.assertEqual(c.state.receive_sequence,1)
    def test_nonfinite_http_accepted_runtime_rejected(self):
        c,w,clock=capture(); value=outcome(); value['payload']['unused']=float('nan')
        r=c.request_hook(value); self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.snapshot)
    def test_control_sequence_unchanged(self):
        c,w,clock=capture(); c.control(); self.assertEqual(c.state.receive_sequence,0)
    def test_runner_opens_gap_before_returning_post(self):
        c,w,clock=capture(); a=c.request_hook(outcome()); clock.value=111; b=c.request_hook(outcome())
        self.assertEqual(b.next_state.timeline_ordinal,a.next_state.timeline_ordinal+1)
        self.assertEqual(b.next_state.receive_sequence,2)
        self.assertTrue(any(r.record_type is journal.ShadowRecordType.CONTROL for r in w.records))
    def test_capture_finish_replay(self):
        c,w,clock=capture(); c.request_hook(outcome()); clock.value=11; c.finish()
        result=journal.replay_shadow_records_v1(records=tuple(w.records))
        self.assertEqual(result.completeness.value,'COMPLETE'); self.assertEqual(result.divergence_count,0)
    def test_technical_diagnostics_excluded_from_ids(self):
        c,w,clock=capture(); c.request_hook(outcome()); ds=[r for r in w.records if r.record_type is journal.ShadowRecordType.DIAGNOSTIC]
        self.assertTrue(ds); self.assertEqual(ds[0].content_json,'{}')
    def test_capture_rejected_then_valid(self):
        c,w,clock=capture(); c.request_hook(dict(classification='json',http_status=400)); clock.value=11
        r=c.request_hook(outcome()); self.assertEqual(r.next_state.receive_sequence,2)
    def test_port_collision_fails(self):
        server,thread=gsi.start_receiver(0,'token',lambda state:None)
        try:
            with self.assertRaises(OSError): gsi.start_receiver(server.server_address[1],'token',lambda state:None)
        finally: server.shutdown(); server.server_close(); thread.join()
    def test_hook_keyword_only(self): self.assertEqual(inspect.signature(gsi.start_receiver).parameters['on_request_result'].kind,inspect.Parameter.KEYWORD_ONLY)
    def test_no_output_imports(self):
        tree=ast.parse(inspect.getsource(runtime)); imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
        self.assertEqual(imports-{'dataclasses'}, {'coach.gsi','coach.state','live_runtime_v01','shadow_journal_v01'})
        source=inspect.getsource(runtime)
        for forbidden in ('Service(', 'Store(', 'Policy(', 'Voice(', 'Engine(', 'CoachCall(', 'subprocess.', 'pyautogui.'):
            self.assertNotIn(forbidden,source)
    def test_settings_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'; body=json.dumps(dict(port=32124,token='private',voice=True)); path.write_text(body)
            self.assertEqual(runtime.read_receiver_settings_v1(path),(32124,'private')); self.assertEqual(path.read_text(),body)
    def test_replay_cli_no_receiver(self):
        from test_shadow_journal_v01 import records
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'j'; path.write_text(''.join(journal.record_line_v1(r) for r in records()))
            with patch.object(runtime,'start_receiver',side_effect=AssertionError('HTTP forbidden')),patch.object(runtime.time,'monotonic_ns',side_effect=AssertionError('clock forbidden')),patch('builtins.print'):
                self.assertEqual(runtime.main(['replay','--journal',str(path)]),0)
    def test_closed_capture_rejects_posts(self):
        c,w,clock=capture(); c.finish()
        with self.assertRaises(RuntimeError): c.request_hook(outcome())
    def test_explicit_reset_is_control(self):
        c,w,clock=capture(); c.request_hook(outcome()); clock.value=11; r=c.control(live.RuntimeInputKind.RESET)
        self.assertEqual(r.status.value,'CONTROL'); self.assertEqual(r.next_state.receive_sequence,1)
    def test_multiple_posts_never_deduplicated(self):
        c,w,clock=capture()
        for i in range(5): clock.value=10+i; c.request_hook(outcome())
        self.assertEqual(c.accepted_count,5)
        self.assertEqual(len([r for r in w.records if r.record_type is journal.ShadowRecordType.INPUT]),5)
    def http_request(self,body,path='/gsi',token='token',hook=True,headers=None):
        seen=[]; states=[]; rejected=[]
        server,thread=gsi.start_receiver(0,token,states.append,rejected.append,**({'on_request_result':seen.append} if hook else {}))
        try:
            request=urllib.request.Request('http://127.0.0.1:'+str(server.server_address[1])+path,body,headers or {'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request,timeout=5) as reply: status=reply.status; reply.read()
            except urllib.error.HTTPError as error: status=error.code; error.read()
        finally: server.shutdown(); server.server_close(); thread.join()
        return status,seen,states,rejected
    def test_legacy_success_without_hook(self):
        p=payload(); p['auth']={'token':'token'}; status,seen,states,rejected=self.http_request(json.dumps(p).encode(),hook=False)
        self.assertEqual(status,200); self.assertEqual(seen,[]); self.assertEqual(states,[normalize(p)]); self.assertEqual(rejected,[])
    def test_hook_success_normalized_state(self):
        p=payload(); p['auth']={'token':'token'}; status,seen,states,rejected=self.http_request(json.dumps(p).encode())
        self.assertEqual(status,200); self.assertEqual(seen[0]['state'],normalize(p)); self.assertEqual(seen[0]['classification'],'accepted')
    def test_hook_bad_auth_no_payload(self):
        p=payload(); p['auth']={'token':'wrong'}; status,seen,states,rejected=self.http_request(json.dumps(p).encode())
        self.assertEqual(status,403); self.assertIsNone(seen[0]['payload']); self.assertEqual(states,[])
    def test_hook_invalid_json_no_payload(self):
        status,seen,states,rejected=self.http_request(b'{broken')
        self.assertEqual(status,400); self.assertEqual(seen[0]['classification'],'json'); self.assertIsNone(seen[0]['payload'])
    def test_hook_invalid_shape_no_payload(self):
        status,seen,states,rejected=self.http_request(b'[]')
        self.assertEqual(status,400); self.assertEqual(seen[0]['classification'],'shape'); self.assertIsNone(seen[0]['payload'])
    def test_hook_wrong_path(self):
        status,seen,states,rejected=self.http_request(b'{}',path='/other')
        self.assertEqual(status,404); self.assertEqual(seen[0]['classification'],'path'); self.assertEqual(rejected,[])
    def test_hook_origin_rejected(self):
        status,seen,states,rejected=self.http_request(b'{}',headers={'Origin':'https://example.test'})
        self.assertEqual(status,400); self.assertEqual(seen[0]['classification'],'transport')
    def test_legacy_bad_json_unchanged(self):
        status,seen,states,rejected=self.http_request(b'{broken',hook=False)
        self.assertEqual(status,400); self.assertEqual(rejected,['Pacote GSI inválido'])
    def test_classification_auth(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='auth',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_classification_size(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='size',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_classification_path(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='path',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_classification_json(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='json',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_classification_shape(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='shape',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_classification_transport(self):
        c,w,clock=capture(); r=c.request_hook(dict(classification='transport',http_status=400))
        self.assertEqual(r.status.value,'REJECTED'); self.assertIsNone(r.observation_event)
    def test_invalid_settings_port_bool(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port=True,token='token')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
    def test_invalid_settings_port_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port=0,token='token')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
    def test_invalid_settings_port_large(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port=65536,token='token')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
    def test_invalid_settings_port_str(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port='32124',token='token')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
    def test_invalid_settings_token_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port=32124,token='')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
    def test_invalid_settings_token_space(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings'; path.write_text(json.dumps(dict(port=32124,token=' ')))
            with self.assertRaises(ValueError): runtime.read_receiver_settings_v1(path)
