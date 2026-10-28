"""SYNTHETIC journal durability and deterministic replay tests."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from coach02 import shadow_journal_v01 as journal
from coach02 import live_runtime_v01 as live
from test_live_runtime_v01 import initial, payload, policy, receive

def records(rejected=False,control=False):
    state=initial()
    kind=live.RuntimeInputKind.REJECTED if rejected else live.RuntimeInputKind.TIME_ADVANCE if control else live.RuntimeInputKind.RECEIVED
    inp=live.RuntimeInputV1(kind,10,None if control else 1,None if rejected or control else live.canonical_json(payload()),live.RuntimeUpdateReason.INVALID_AUTH if rejected else None)
    result=live.advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=policy())
    return (journal.make_record_v1(journal.ShadowRecordType.HEADER,1,dict(run_id='run',policy=asdict(policy()),origin='SYNTHETIC',scope_label='')),
            journal.make_record_v1(journal.ShadowRecordType.CONTROL if control else journal.ShadowRecordType.INPUT,2,asdict(inp)),
            journal.make_record_v1(journal.ShadowRecordType.RESULT,3,journal.result_content_v1(result)),
            journal.make_record_v1(journal.ShadowRecordType.FOOTER,4,dict(final_state_id=result.next_state.state_id,complete=True)))

class JournalTests(unittest.TestCase):
    def test_complete_roundtrip(self):
        r=journal.replay_shadow_records_v1(records=records()); self.assertEqual(r.completeness.value,'COMPLETE'); self.assertEqual(r.divergence_count,0); self.assertEqual(r.accepted_count,1)
    def test_rejection_replays_classification(self): self.assertEqual(journal.replay_shadow_records_v1(records=records(rejected=True)).rejected_count,1)
    def test_control_replays(self): self.assertEqual(journal.replay_shadow_records_v1(records=records(control=True)).control_count,1)
    def test_empty_incomplete(self): self.assertEqual(journal.replay_shadow_records_v1(records=()).completeness.value,'INCOMPLETE')
    def test_no_footer_incomplete(self): self.assertEqual(journal.replay_shadow_records_v1(records=records()[:-1]).completeness.value,'INCOMPLETE')
    def test_pending_input_incomplete(self): self.assertEqual(journal.replay_shadow_records_v1(records=records()[:2]).completeness.value,'INCOMPLETE')
    def test_result_not_truth(self):
        rs=records(); value=json.loads(rs[2].content_json); value['status']='CONTROL'
        changed=replace(rs[2],content_json=live.canonical_json(value))
        r=journal.replay_shadow_records_v1(records=rs[:2]+(changed,rs[3]))
        self.assertEqual(r.divergence_count,1); self.assertEqual(r.accepted_count,1)
    def test_wrong_footer_lineage(self):
        rs=records(); bad=replace(rs[3],content_json=live.canonical_json(dict(final_state_id='wrong',complete=True)))
        self.assertEqual(journal.replay_shadow_records_v1(records=rs[:3]+(bad,)).completeness.value,'CORRUPT')
    def test_record_after_footer(self):
        rs=records(); extra=journal.make_record_v1(journal.ShadowRecordType.DIAGNOSTIC,5,{})
        self.assertGreater(journal.replay_shadow_records_v1(records=rs+(extra,)).divergence_count,0)
    def test_input_without_result(self):
        rs=records(); extra=replace(rs[1],record_sequence=3)
        self.assertGreater(journal.replay_shadow_records_v1(records=rs[:2]+(extra,)).divergence_count,0)
    def test_result_without_input(self):
        rs=records(); extra=replace(rs[2],record_sequence=2)
        self.assertGreater(journal.replay_shadow_records_v1(records=(rs[0],extra)).divergence_count,0)
    def test_header_required(self): self.assertGreater(journal.replay_shadow_records_v1(records=(replace(records()[1],record_sequence=1),)).divergence_count,0)
    def test_header_not_repeated(self):
        rs=records(); self.assertGreater(journal.replay_shadow_records_v1(records=(rs[0],replace(rs[0],record_sequence=2))).divergence_count,0)
    def test_diagnostics_do_not_change_id(self):
        r=records()[2]; self.assertEqual(r.record_id,replace(r,diagnostics_json='{"seconds":99}').record_id)
    def test_content_changes_id(self):
        r=records()[2]; self.assertNotEqual(r.record_id,replace(r,content_json='{}').record_id)
    def test_sequence_changes_id(self):
        r=records()[2]; self.assertNotEqual(r.record_id,replace(r,record_sequence=9).record_id)
    def test_jsonl_roundtrip(self):
        for record in records(): self.assertEqual(journal.parse_record_line_v1(journal.record_line_v1(record)),record)
    def test_tampered_hash_rejected(self):
        value=json.loads(journal.record_line_v1(records()[0])); value['record_id']='wrong'
        with self.assertRaises(ValueError): journal.parse_record_line_v1(json.dumps(value))
    def test_unknown_record_key_rejected(self):
        value=json.loads(journal.record_line_v1(records()[0])); value['extra']=1
        with self.assertRaises(ValueError): journal.parse_record_line_v1(json.dumps(value))
    def test_writer_durability(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.jsonl'; w=journal.ShadowJournalWriterV1(path)
            with patch.object(journal.os,'fsync',wraps=journal.os.fsync) as fsync:
                w.append(records()); self.assertEqual(fsync.call_count,1)
            w.close(); self.assertEqual(journal.read_shadow_records_v1(path),records())
    def test_writer_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.jsonl'; path.write_text('existing')
            with self.assertRaises(FileExistsError): journal.ShadowJournalWriterV1(path)
            self.assertEqual(path.read_text(),'existing')
    def test_writer_failure_poisoned(self):
        with tempfile.TemporaryDirectory() as folder:
            w=journal.ShadowJournalWriterV1(Path(folder)/'j')
            try:
                with patch.object(journal.os,'fsync',side_effect=OSError('disk')):
                    with self.assertRaises(OSError): w.append(records())
                self.assertTrue(w.failed)
                with self.assertRaises(OSError): w.append(records())
                self.assertEqual(w.record_sequence,0)
            finally: w.close()
    def test_writer_rejects_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            w=journal.ShadowJournalWriterV1(Path(folder)/'j')
            try:
                with self.assertRaises(ValueError): w.append((records()[1],))
                self.assertFalse(w.failed)
            finally: w.close()
    def test_truncated_suffix_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'j'; path.write_bytes(''.join(journal.record_line_v1(r) for r in records()[:-1]).encode()+b'{"partial')
            r=journal.replay_shadow_records_v1(records=journal.read_shadow_records_v1(path)); self.assertEqual(r.completeness.value,'INCOMPLETE')
    def test_corrupt_complete_line_not_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'j'; path.write_bytes(journal.record_line_v1(records()[0]).encode()+b'{bad}\n')
            with self.assertRaises(ValueError): journal.read_shadow_records_v1(path)
    def test_non_tuple_rejected(self):
        with self.assertRaises(TypeError): journal.replay_shadow_records_v1(records=list(records()))
    def test_foreign_record_rejected(self):
        with self.assertRaises(TypeError): journal.replay_shadow_records_v1(records=(object(),))
    def test_invalid_type(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],record_type='HEADER')
    def test_invalid_sequence_bool(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],record_sequence=True)
    def test_invalid_sequence_zero(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],record_sequence=0)
    def test_invalid_sequence_float(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],record_sequence=1.0)
    def test_invalid_ruleset(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],ruleset='future')
    def test_invalid_content_list(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],content_json='[]')
    def test_invalid_content_noncanonical(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],content_json='{ "x": 1}')
    def test_invalid_diagnostic_list(self):
        with self.assertRaises((ValueError,TypeError)): replace(records()[0],diagnostics_json='[]')
