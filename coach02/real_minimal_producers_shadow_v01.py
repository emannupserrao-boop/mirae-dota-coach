"""Offline semantic Shadow over immutable Foundation inputs; no listener/output."""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import os

from .live_runtime_v01 import (LiveRuntimePolicyV1, RuntimeInputV1, RuntimeInputKind,
                              RuntimeUpdateReason, RuntimeUpdateStatus,
                              new_live_runtime_state_v1, advance_live_runtime_v1)
from .shadow_journal_v01 import (ShadowJournalRecordV1, ShadowRecordType,
                                result_content_v1, record_line_v1,
                                read_shadow_records_v1)
from .farm_cadence_evidence_v01 import (FarmCadencePolicyV1, FarmCadenceStatus,
    new_farm_cadence_state_v1, advance_farm_cadence_v1, RULESET as FARM_RULESET)
from .local_readiness_evidence_v01 import (LocalReadinessPolicyV1,
    new_local_readiness_state_v1, advance_local_readiness_v1, RULESET as READINESS_RULESET)

RULESET = 'runtime.real_minimal_producers_shadow.v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _hash(data): return hashlib.sha256(data).hexdigest().upper()


class SemanticShadowRecordType(str, Enum):
    HEADER = 'HEADER'
    PRODUCER_RESULT = 'PRODUCER_RESULT'
    DIAGNOSTIC = 'DIAGNOSTIC'
    FOOTER = 'FOOTER'


class SemanticReplayCompleteness(str, Enum):
    COMPLETE = 'COMPLETE'
    INCOMPLETE = 'INCOMPLETE'
    CORRUPT = 'CORRUPT'


@dataclass(frozen=True)
class SemanticShadowRecordV1:
    record_type: SemanticShadowRecordType
    record_sequence: int
    content_json: str
    diagnostics_json: str = '{}'
    ruleset: str = RULESET

    def __post_init__(self):
        if type(self.record_type) is not SemanticShadowRecordType or self.ruleset != RULESET:
            raise ValueError('exact_semantic_record_ruleset_required')
        if type(self.record_sequence) is not int or self.record_sequence < 1:
            raise ValueError('positive_semantic_record_sequence_required')
        for value in (self.content_json,self.diagnostics_json):
            if type(value) is not str or type(json.loads(value)) is not dict or _json(json.loads(value)) != value:
                raise ValueError('canonical_semantic_record_object_required')

    @property
    def record_id(self):
        value=dict(ruleset=self.ruleset,record_type=self.record_type.value,
                   record_sequence=self.record_sequence,content=json.loads(self.content_json))
        return RULESET + ':record:' + hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class SemanticShadowBuildV1:
    records: tuple[SemanticShadowRecordV1, ...]
    proof_json: str
    timings_ns: tuple[tuple[int, int, int, int], ...]


@dataclass(frozen=True)
class SemanticReplayResultV1:
    completeness: SemanticReplayCompleteness
    record_count: int
    divergence_details: tuple[str, ...]
    final_farm_state_id: str | None
    final_readiness_state_id: str | None
    proof_json: str | None

    @property
    def divergence_count(self): return len(self.divergence_details)


def semantic_record_line_v1(record):
    if type(record) is not SemanticShadowRecordV1: raise TypeError('exact_semantic_record_required')
    value=asdict(record);value['record_id']=record.record_id
    return _json(value)+'\n'


def parse_semantic_record_line_v1(line):
    value=json.loads(line)
    if type(value) is not dict or set(value) != {'record_type','record_sequence','content_json','diagnostics_json','ruleset','record_id'}:
        raise ValueError('invalid_semantic_record_shape')
    record=SemanticShadowRecordV1(SemanticShadowRecordType(value['record_type']),
        value['record_sequence'],value['content_json'],value['diagnostics_json'],value['ruleset'])
    if record.record_id != value['record_id']: raise ValueError('semantic_record_hash_mismatch')
    return record


def foundation_records_sha256_v1(records):
    """Hash the canonical serialized input in memory; never exports the source."""
    if type(records) is not tuple or any(type(r) is not ShadowJournalRecordV1 for r in records):
        raise TypeError('exact_foundation_records_required')
    value=hashlib.sha256()
    for record in records: value.update(record_line_v1(record).encode('utf-8'))
    return value.hexdigest().upper()


def _record(kind, sequence, value):
    return SemanticShadowRecordV1(kind,sequence,_json(value))


def build_semantic_shadow_v1(*, foundation_records, foundation_sha256,
                             farm_policy, readiness_policy, timer=None):
    """Recompute Foundation, then producers. Optional external profiler is not identity.

    This is a batch journal operation. Producer states retain no event history;
    the caller-owned input/output record tuples are the offline replay material.
    """
    if type(farm_policy) is not FarmCadencePolicyV1 or type(readiness_policy) is not LocalReadinessPolicyV1:
        raise TypeError('exact_semantic_policies_required')
    farm_policy.__post_init__();readiness_policy.__post_init__()
    if foundation_records_sha256_v1(foundation_records) != foundation_sha256:
        raise ValueError('foundation_journal_sha256_mismatch')
    state=pending=policy=None
    pending_record_id=None
    completed=False
    farm=new_farm_cadence_state_v1(policy=farm_policy)
    readiness=new_local_readiness_state_v1(policy=readiness_policy)
    records=[];timings=[]
    proof=dict(accepted=0,controls=0,rejected=0,producer_results=0,farm_intervals=0,
        ability_ready=0,ability_not_ready=0,ability_indeterminate=0,
        item_present=0,item_not_reported=0,item_indeterminate=0,transitions=0,
        ability_availability_transitions=0,heroes=[])
    for sequence,record in enumerate(foundation_records,1):
        record.__post_init__()
        if record.record_sequence != sequence or completed: raise ValueError('foundation_sequence_or_footer_order')
        content=json.loads(record.content_json)
        if record.record_type is ShadowRecordType.HEADER:
            if sequence != 1 or state is not None or set(content) != {'run_id','policy','origin','scope_label'} or content['origin'] not in ('REAL_GSI','SYNTHETIC'):
                raise ValueError('foundation_header_shape')
            policy=LiveRuntimePolicyV1(**content['policy'])
            state=new_live_runtime_state_v1(run_id=content['run_id'],policy=policy)
            header=dict(foundation_sha256=foundation_sha256,origin=content['origin'],
                ruleset=RULESET,farm_ruleset=FARM_RULESET,readiness_ruleset=READINESS_RULESET,
                farm_policy=asdict(farm_policy),readiness_policy=asdict(readiness_policy))
            records.append(_record(SemanticShadowRecordType.HEADER,1,header))
        elif state is None: raise ValueError('foundation_header_required')
        elif record.record_type in (ShadowRecordType.INPUT,ShadowRecordType.CONTROL):
            if pending is not None: raise ValueError('foundation_input_without_result')
            value=dict(content);value['kind']=RuntimeInputKind(value['kind'])
            if value.get('rejection_reason') is not None: value['rejection_reason']=RuntimeUpdateReason(value['rejection_reason'])
            inp=RuntimeInputV1(**value)
            if (inp.kind in (RuntimeInputKind.RECEIVED,RuntimeInputKind.REJECTED)) != (record.record_type is ShadowRecordType.INPUT):
                raise ValueError('foundation_input_kind_mismatch')
            pending=advance_live_runtime_v1(previous_state=state,runtime_input=inp,policy=policy)
            pending_record_id=record.record_id
        elif record.record_type is ShadowRecordType.RESULT:
            if pending is None: raise ValueError('foundation_result_without_input')
            actual=result_content_v1(pending)
            if _json(actual) != record.content_json: raise ValueError('foundation_result_divergence')
            start=timer() if timer is not None else 0
            f=advance_farm_cadence_v1(previous_state=farm,runtime_result=pending,policy=farm_policy)
            after_farm=timer() if timer is not None else 0
            q=advance_local_readiness_v1(previous_state=readiness,runtime_result=pending,policy=readiness_policy)
            after_readiness=timer() if timer is not None else 0
            value=dict(foundation_input_record_id=pending_record_id,
                foundation_result_record_id=record.record_id,
                foundation_state_id=pending.next_state.state_id,
                runtime_snapshot_id=None if pending.snapshot is None else pending.snapshot.snapshot_id,
                run_id=pending.next_state.run_id,session_id=pending.next_state.session_id,
                timeline_id=pending.next_state.timeline_id,selected_clock_id=pending.next_state.selected_clock_id,
                evaluated_at_tick=pending.next_state.evaluated_at_tick,
                receive_sequence=pending.next_state.receive_sequence,
                payload_id=None if pending.snapshot is None else pending.snapshot.payload_id,
                farm=asdict(f),readiness=asdict(q),farm_evidence_id=f.evidence.evidence_id,
                farm_state_id=f.next_state.state_id,readiness_snapshot_id=q.snapshot.snapshot_id,
                readiness_state_id=q.next_state.state_id,
                ability_evidence_ids=[a.evidence_id for a in q.snapshot.abilities],
                item_evidence_ids=[a.evidence_id for a in q.snapshot.items],
                transition_ids=[t.transition_id for t in q.transitions])
            semantic=_record(SemanticShadowRecordType.PRODUCER_RESULT,len(records)+1,value)
            semantic.record_id  # include complete content hashing in the measured processing
            end=timer() if timer is not None else 0
            records.append(semantic)
            if timer is not None and pending.status is RuntimeUpdateStatus.ACCEPTED:
                timings.append((after_farm-start,after_readiness-after_farm,end-after_readiness,end-start))
            proof['producer_results']+=1
            counter={RuntimeUpdateStatus.ACCEPTED:'accepted',RuntimeUpdateStatus.CONTROL:'controls',RuntimeUpdateStatus.REJECTED:'rejected'}.get(pending.status)
            if counter is None: raise ValueError('foundation_internal_error')
            proof[counter]+=1
            proof['farm_intervals']+=f.evidence.status is FarmCadenceStatus.OBSERVED_INTERVAL
            for a in q.snapshot.abilities: proof['ability_'+a.status.value.lower()]+=1
            for a in q.snapshot.items: proof['item_'+a.status.value.lower()]+=1
            proof['transitions']+=len(q.transitions)
            proof['ability_availability_transitions']+=sum(t.resource_kind=='ability' and {t.previous_status.value,t.current_status.value}=={'READY','NOT_READY'} for t in q.transitions)
            if q.snapshot.input_presence.value=='PRESENT' and q.snapshot.hero and q.snapshot.hero not in proof['heroes']: proof['heroes'].append(q.snapshot.hero)
            farm,readiness,state=f.next_state,q.next_state,pending.next_state
            pending=pending_record_id=None
        elif record.record_type is ShadowRecordType.DIAGNOSTIC:
            if pending is not None or content: raise ValueError('foundation_diagnostic_order_or_content')
        elif record.record_type is ShadowRecordType.FOOTER:
            if pending is not None or content != {'final_state_id':state.state_id,'complete':True}:
                raise ValueError('foundation_footer_lineage')
            completed=True
    if not completed: raise ValueError('foundation_incomplete')
    footer=dict(complete=True,final_foundation_state_id=state.state_id,
        final_farm_state_id=farm.state_id,final_readiness_state_id=readiness.state_id,proof=proof)
    records.append(_record(SemanticShadowRecordType.FOOTER,len(records)+1,footer))
    return SemanticShadowBuildV1(tuple(records),_json(proof),tuple(timings))


def replay_semantic_shadow_v1(*, foundation_records, foundation_sha256, semantic_records):
    """Pure comparison: stored semantic results are targets, never producer inputs."""
    if type(semantic_records) is not tuple or any(type(r) is not SemanticShadowRecordV1 for r in semantic_records):
        raise TypeError('exact_semantic_record_tuple_required')
    if not semantic_records: return SemanticReplayResultV1(SemanticReplayCompleteness.INCOMPLETE,0,(),None,None,None)
    try:
        first=semantic_records[0];first.__post_init__()
        if first.record_type is not SemanticShadowRecordType.HEADER: raise ValueError('semantic_header_required')
        header=json.loads(first.content_json)
        f=FarmCadencePolicyV1(**header['farm_policy'])
        p=dict(header['readiness_policy']);p['ability_selectors']=tuple(p['ability_selectors']);p['item_selectors']=tuple(p['item_selectors'])
        q=LocalReadinessPolicyV1(**p)
        if header['foundation_sha256'] != foundation_sha256: raise ValueError('semantic_foundation_binding_mismatch')
        expected=build_semantic_shadow_v1(foundation_records=foundation_records,foundation_sha256=foundation_sha256,farm_policy=f,readiness_policy=q)
        differences=[];comparable=[]
        for i,r in enumerate(semantic_records,1):
            r.__post_init__()
            if r.record_sequence != i: raise ValueError('semantic_sequence_mismatch')
            if r.record_type is SemanticShadowRecordType.DIAGNOSTIC:
                if json.loads(r.content_json): raise ValueError('diagnostic_has_deterministic_content')
                if comparable and comparable[-1].record_type is SemanticShadowRecordType.FOOTER: raise ValueError('data_after_semantic_footer')
                continue
            comparable.append(r)
        for i,r in enumerate(comparable):
            if i>=len(expected.records) or r.record_type is not expected.records[i].record_type or r.content_json != expected.records[i].content_json:
                differences.append('semantic_record_'+str(i+1)+':content_mismatch')
        has_footer=bool(comparable and comparable[-1].record_type is SemanticShadowRecordType.FOOTER)
        if has_footer and len(comparable)!=len(expected.records): differences.append('semantic_result_count_mismatch')
        completeness=SemanticReplayCompleteness.CORRUPT if differences else SemanticReplayCompleteness.COMPLETE if has_footer else SemanticReplayCompleteness.INCOMPLETE
        footer=json.loads(expected.records[-1].content_json)
        return SemanticReplayResultV1(completeness,len(semantic_records),tuple(differences),
            footer['final_farm_state_id'] if completeness is SemanticReplayCompleteness.COMPLETE else None,
            footer['final_readiness_state_id'] if completeness is SemanticReplayCompleteness.COMPLETE else None,
            expected.proof_json if completeness is SemanticReplayCompleteness.COMPLETE else None)
    except (ValueError,TypeError,KeyError,AttributeError) as error:
        return SemanticReplayResultV1(SemanticReplayCompleteness.CORRUPT,len(semantic_records),(str(error),),None,None,None)


def write_semantic_journal_v1(*, path, records):
    """Exclusive external output. Write failure propagates; no repair/fallback."""
    if type(records) is not tuple or not records: raise ValueError('nonempty_semantic_records_required')
    with open(path,'x',encoding='utf-8',newline='\n') as stream:
        for i,r in enumerate(records,1):
            if r.record_sequence != i: raise ValueError('semantic_write_sequence_mismatch')
            stream.write(semantic_record_line_v1(r))
        stream.flush();os.fsync(stream.fileno())


def read_semantic_journal_v1(path):
    records=[]
    with open(path,'rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                if records and records[-1].record_type is SemanticShadowRecordType.FOOTER: raise ValueError('data_after_complete_semantic_footer')
                break
            records.append(parse_semantic_record_line_v1(line.decode('utf-8')))
    return tuple(records)


def read_foundation_input_v1(path):
    """Read-only original input; hash actual bytes before canonical record validation."""
    with open(path,'rb') as stream: content=stream.read()
    digest=_hash(content)
    records=read_shadow_records_v1(path)
    if foundation_records_sha256_v1(records)!=digest: raise ValueError('incomplete_or_noncanonical_foundation_journal')
    return records,digest
