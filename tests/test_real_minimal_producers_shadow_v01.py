"""Foundation recomputation, semantic lineage, persistence/replay and frozen scope."""
import ast
from dataclasses import asdict, replace
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coach02 import real_minimal_producers_shadow_v01 as shadow
from coach02 import farm_cadence_evidence_v01 as farm
from coach02 import local_readiness_evidence_v01 as readiness
from coach02.live_runtime_v01 import (RuntimeInputV1, RuntimeInputKind, canonical_json,
    sanitize_gsi_payload_v1, new_live_runtime_state_v1, advance_live_runtime_v1)
from coach02.shadow_journal_v01 import (ShadowRecordType, make_record_v1,
    result_content_v1, record_line_v1)
from test_farm_cadence_evidence_v01 import FOUNDATION, payload, policy as farm_policy
from test_local_readiness_evidence_v01 import policy as readiness_policy


def foundation(updates=None,origin='SYNTHETIC'):
    updates=[(0,0,0,{}),(1,1,1,{'abilities.ability0.can_cast':False}),(2,2,2,{})] if updates is None else updates
    state=new_live_runtime_state_v1(run_id='synthetic-run',policy=FOUNDATION)
    records=[make_record_v1(ShadowRecordType.HEADER,1,dict(run_id='synthetic-run',policy=asdict(FOUNDATION),origin=origin,scope_label='synthetic test'))]
    for source,lh,receipt,changes in updates:
        inp=RuntimeInputV1(RuntimeInputKind.RECEIVED,receipt,state.receive_sequence+1,
            canonical_json(sanitize_gsi_payload_v1(payload=payload(source_time=source,lh=lh,changes=changes))))
        result=advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=FOUNDATION)
        records.extend((make_record_v1(ShadowRecordType.INPUT,len(records)+1,asdict(inp)),
            make_record_v1(ShadowRecordType.RESULT,len(records)+2,result_content_v1(result))))
        state=result.next_state
    receipt=0 if not updates else updates[-1][2]+1
    inp=RuntimeInputV1(RuntimeInputKind.SHUTDOWN,receipt)
    result=advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=FOUNDATION)
    records.extend((make_record_v1(ShadowRecordType.CONTROL,len(records)+1,asdict(inp)),
        make_record_v1(ShadowRecordType.RESULT,len(records)+2,result_content_v1(result)),
        make_record_v1(ShadowRecordType.FOOTER,len(records)+3,dict(complete=True,final_state_id=result.next_state.state_id))))
    return tuple(records)


def build(records=None,**changes):
    records=foundation() if records is None else records
    values=dict(foundation_records=records,foundation_sha256=shadow.foundation_records_sha256_v1(records),farm_policy=farm_policy(),readiness_policy=readiness_policy())
    values.update(changes);return shadow.build_semantic_shadow_v1(**values)


def replay(records,semantic):
    return shadow.replay_semantic_shadow_v1(foundation_records=records,foundation_sha256=shadow.foundation_records_sha256_v1(records),semantic_records=semantic)


class SemanticShadowTests(unittest.TestCase):
    def test_01_record_domain(self):
        self.assertEqual([s.value for s in shadow.SemanticShadowRecordType],['HEADER','PRODUCER_RESULT','DIAGNOSTIC','FOOTER'])
    def test_02_semantic_record_validation(self):
        for seq in (0,-1,True):
            with self.assertRaises(ValueError):shadow.SemanticShadowRecordV1(shadow.SemanticShadowRecordType.HEADER,seq,'{}')
        with self.assertRaises(ValueError):shadow.SemanticShadowRecordV1(shadow.SemanticShadowRecordType.HEADER,1,'[]')
    def test_03_record_roundtrip(self):
        record=build().records[0];self.assertEqual(shadow.parse_semantic_record_line_v1(shadow.semantic_record_line_v1(record)),record)
    def test_04_record_hash_tamper(self):
        value=json.loads(shadow.semantic_record_line_v1(build().records[0]));value['record_id']='wrong'
        with self.assertRaises(ValueError):shadow.parse_semantic_record_line_v1(json.dumps(value))
    def test_05_diagnostics_excluded_from_identity(self):
        record=build().records[0];self.assertEqual(record.record_id,replace(record,diagnostics_json='{"ns":1}').record_id)
    def test_06_foundation_hash_binding(self):
        with self.assertRaises(ValueError):build(foundation_sha256='0'*64)
    def test_07_foundation_recomputed(self):
        with patch.object(shadow,'advance_live_runtime_v1',wraps=shadow.advance_live_runtime_v1) as call:
            build();self.assertEqual(call.call_count,4)
    def test_08_stored_result_not_trusted(self):
        records=list(foundation());c=json.loads(records[2].content_json);c['status']='REJECTED';records[2]=replace(records[2],content_json=canonical_json(c))
        with self.assertRaisesRegex(ValueError,'divergence'):build(tuple(records))
    def test_09_foundation_incomplete(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):build(foundation()[:-1])
    def test_10_foundation_footer_wrong(self):
        records=list(foundation());records[-1]=replace(records[-1],content_json='{"complete":true,"final_state_id":"wrong"}')
        with self.assertRaises(ValueError):build(tuple(records))
    def test_11_foundation_record_order(self):
        records=list(foundation());records[1]=replace(records[1],record_sequence=999)
        with self.assertRaises(ValueError):build(tuple(records))
    def test_12_header_policy_origin(self):
        head=json.loads(build().records[0].content_json);self.assertEqual(head['origin'],'SYNTHETIC');self.assertEqual(head['farm_policy']['policy_id'],'farm.v1');self.assertEqual(head['ruleset'],shadow.RULESET)
    def test_13_semantic_result_lineage(self):
        records=foundation();out=build(records);c=json.loads(out.records[1].content_json)
        self.assertEqual(c['foundation_input_record_id'],records[1].record_id);self.assertEqual(c['foundation_result_record_id'],records[2].record_id);self.assertEqual(c['payload_id'],c['farm']['evidence']['payload_id'])
    def test_14_synthetic_positive_proof(self):
        proof=json.loads(build().proof_json);self.assertEqual(proof['farm_intervals'],1);self.assertGreater(proof['ability_ready'],0);self.assertGreater(proof['item_present'],0);self.assertEqual(proof['ability_availability_transitions'],2)
    def test_15_replay_complete_zero(self):
        records=foundation();out=replay(records,build(records).records);self.assertIs(out.completeness,shadow.SemanticReplayCompleteness.COMPLETE);self.assertEqual(out.divergence_count,0)
    def test_16_replay_missing_footer(self):
        records=foundation();out=replay(records,build(records).records[:-1]);self.assertIs(out.completeness,shadow.SemanticReplayCompleteness.INCOMPLETE)
    def test_17_replay_empty(self):
        self.assertIs(replay(foundation(),()).completeness,shadow.SemanticReplayCompleteness.INCOMPLETE)
    def test_18_semantic_result_tamper(self):
        records=foundation();rows=list(build(records).records);c=json.loads(rows[1].content_json);c['payload_id']='foreign';rows[1]=replace(rows[1],content_json=canonical_json(c))
        self.assertGreater(replay(records,tuple(rows)).divergence_count,0)
    def test_19_semantic_policy_tamper(self):
        records=foundation();rows=list(build(records).records);c=json.loads(rows[0].content_json);c['farm_policy']['minimum_gameplay_interval_seconds']=99;rows[0]=replace(rows[0],content_json=canonical_json(c))
        self.assertGreater(replay(records,tuple(rows)).divergence_count,0)
    def test_20_semantic_sequence_and_extra_footer(self):
        records=foundation();rows=list(build(records).records);rows[1]=replace(rows[1],record_sequence=999)
        self.assertIs(replay(records,tuple(rows)).completeness,shadow.SemanticReplayCompleteness.CORRUPT)
        rows=list(build(records).records);rows.append(replace(rows[-1],record_sequence=len(rows)+1));self.assertGreater(replay(records,tuple(rows)).divergence_count,0)
    def test_21_pure_replay_no_clock_or_network(self):
        import time,socket,builtins
        records=foundation();semantic=build(records).records
        with patch.object(time,'time',side_effect=AssertionError),patch.object(time,'monotonic_ns',side_effect=AssertionError),patch.object(time,'sleep',side_effect=AssertionError),patch.object(socket,'socket',side_effect=AssertionError),patch.object(builtins,'open',side_effect=AssertionError):
            self.assertEqual(replay(records,semantic).divergence_count,0)
    def test_22_write_read_exclusive(self):
        rows=build().records
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'semantic.jsonl';shadow.write_semantic_journal_v1(path=path,records=rows);self.assertEqual(shadow.read_semantic_journal_v1(path),rows)
            with self.assertRaises(FileExistsError):shadow.write_semantic_journal_v1(path=path,records=rows)
    def test_23_write_failure_propagates(self):
        with patch.object(shadow.os,'fsync',side_effect=OSError('durability')):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(OSError):shadow.write_semantic_journal_v1(path=Path(directory)/'new',records=build().records)
    def test_24_partial_final_line_incomplete(self):
        rows=build().records
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'partial';path.write_bytes(''.join(shadow.semantic_record_line_v1(r) for r in rows[:-1]).encode()+b'{')
            read=shadow.read_semantic_journal_v1(path);self.assertEqual(read,rows[:-1])
    def test_25_suffix_after_footer_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'extra';path.write_bytes(''.join(shadow.semantic_record_line_v1(r) for r in build().records).encode()+b'{')
            with self.assertRaises(ValueError):shadow.read_semantic_journal_v1(path)
    def test_26_corrupt_complete_prefix_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad';path.write_text('{}\n',encoding='utf-8')
            with self.assertRaises(ValueError):shadow.read_semantic_journal_v1(path)
    def test_27_read_foundation_preserves_bytes(self):
        source=foundation();encoded=''.join(record_line_v1(r) for r in source).encode()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'foundation';path.write_bytes(encoded);rows,digest=shadow.read_foundation_input_v1(path)
            self.assertEqual(path.read_bytes(),encoded);self.assertEqual(rows,source);self.assertEqual(digest,hashlib.sha256(encoded).hexdigest().upper())
    def test_28_optional_external_profiler_excluded(self):
        counter=iter(range(1000));records=foundation();plain=build(records);timed=build(records,timer=lambda:next(counter))
        self.assertEqual(plain.records,timed.records);self.assertEqual(len(timed.timings_ns),3);self.assertEqual(len(timed.timings_ns[0]),4)
    def test_29_dependency_and_authority_boundary(self):
        allowed={'live_runtime_v01','shadow_journal_v01','farm_cadence_evidence_v01','local_readiness_evidence_v01'}
        tree=ast.parse(inspect.getsource(shadow));self.assertEqual({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.level},allowed)
        for module in (farm,readiness,shadow):
            tree=ast.parse(inspect.getsource(module));imports={n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
            self.assertFalse(any(word in name for name in imports for word in ('risk','threat','feasibility','arbiter','option_outcome','execution','voice','gsi','service','observation_event','temporal_evidence')))
    def test_30_real_artifact_hash_only_no_execution(self):
        path=Path.home()/'Dota-AI-Coach-Data/live-runtime-shadow-v01-evidence/real_gsi_acceptance/REAL_GSI.jsonl'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest().upper(),'56C92CFC59E6CF8A73A035F4CA557B88AD678140155D77D0C91AF394394F9D61')
    def test_31_real_artifact_origin_and_hero_read_only(self):
        path=Path.home()/'Dota-AI-Coach-Data/live-runtime-shadow-v01-evidence/real_gsi_acceptance/REAL_GSI.jsonl'
        with path.open(encoding='utf-8') as stream:
            header=json.loads(next(stream));self.assertEqual(json.loads(header['content_json'])['origin'],'REAL_GSI')
            for line in stream:
                row=json.loads(line)
                if row['record_type']=='RESULT':
                    result=json.loads(row['content_json'])
                    if result['snapshot'] is not None:
                        self.assertEqual(json.loads(result['snapshot']['normalized_state_json'])['hero'],'npc_dota_hero_phantom_assassin');break
            else:self.fail('real snapshot absent')
    def test_32_documentation_scope(self):
        text=(Path(shadow.__file__).resolve().parent.parent/'REAL_MINIMAL_PRODUCERS_VERTICAL_ELIGIBILITY_V01.md').read_text(encoding='utf-8')
        for phrase in ('Phantom Assassin','not Juggernaut validation','retrospective','source_match_time','cooldown zero != can_cast','mana unsupported','item presence != power spike','no Option Outcome','no complete Feasibility','no Risk/Safety','no Arbiter','separate semantic journal'):
            self.assertIn(phrase,text)
