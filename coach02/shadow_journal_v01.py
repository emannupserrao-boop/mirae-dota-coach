"""Shadow JSONL persistence and pure deterministic prefix replay.

Unsafe HTTP bodies are never retained; their classifications can be replayed,
not re-authenticated or re-parsed. Stored RESULT records are comparison targets,
never the source of reconstructed state.
"""
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import os

from .live_runtime_v01 import (LiveRuntimePolicyV1, RuntimeInputKind, RuntimeInputV1,
                              RuntimeUpdateReason, RuntimeUpdateStatus,
                              canonical_json, new_live_runtime_state_v1,
                              advance_live_runtime_v1)

RULESET = 'runtime.shadow_foundation.v1'


class ShadowRecordType(str, Enum):
    HEADER = 'HEADER'
    INPUT = 'INPUT'
    CONTROL = 'CONTROL'
    RESULT = 'RESULT'
    DIAGNOSTIC = 'DIAGNOSTIC'
    FOOTER = 'FOOTER'


class ShadowCompleteness(str, Enum):
    COMPLETE = 'COMPLETE'
    INCOMPLETE = 'INCOMPLETE'
    CORRUPT = 'CORRUPT'


@dataclass(frozen=True)
class ShadowJournalRecordV1:
    record_type: ShadowRecordType
    record_sequence: int
    content_json: str
    diagnostics_json: str = '{}'
    ruleset: str = RULESET

    def __post_init__(self):
        if type(self.record_type) is not ShadowRecordType:
            raise TypeError('explicit_record_type_required')
        if type(self.record_sequence) is not int or self.record_sequence < 1:
            raise ValueError('positive_concrete_record_sequence_required')
        if self.ruleset != RULESET:
            raise ValueError('journal_ruleset_mismatch')
        for value in (self.content_json, self.diagnostics_json):
            if type(value) is not str or type(json.loads(value)) is not dict or canonical_json(json.loads(value)) != value:
                raise ValueError('immutable_canonical_object_json_required')

    @property
    def record_id(self):
        content = dict(ruleset=self.ruleset, record_type=self.record_type.value,
                       record_sequence=self.record_sequence, content=json.loads(self.content_json))
        return RULESET + ':record:' + hashlib.sha256(canonical_json(content).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ShadowReplayResultV1:
    completeness: ShadowCompleteness
    record_count: int
    accepted_count: int
    rejected_count: int
    control_count: int
    divergence_details: tuple[str, ...]
    final_state_id: str | None
    final_result_json: str | None

    @property
    def divergence_count(self):
        return len(self.divergence_details)

    @property
    def first_divergence(self):
        return self.divergence_details[0] if self.divergence_details else None


def result_content_v1(result):
    """Complete deterministic subset, with accepted object IDs for lineage."""
    value = asdict(result)
    value['next_state_id'] = result.next_state.state_id
    for field, identifier in (('snapshot', 'snapshot_id'), ('observation_event', 'event_id'),
                              ('temporal_projection', 'projection_id'), ('temporal_snapshot', 'snapshot_id')):
        obj = getattr(result, field)
        if obj is not None:
            value[field][identifier] = getattr(obj, identifier)
    return value


def make_record_v1(kind, sequence, content, diagnostics=None):
    return ShadowJournalRecordV1(kind, sequence, canonical_json(content), canonical_json(diagnostics or {}))


def record_line_v1(record):
    value = asdict(record)
    value['record_id'] = record.record_id
    return canonical_json(value) + '\n'


def parse_record_line_v1(line):
    value = json.loads(line)
    if type(value) is not dict or set(value) != {'record_type', 'record_sequence', 'content_json', 'diagnostics_json', 'ruleset', 'record_id'}:
        raise ValueError('invalid_record_shape')
    record = ShadowJournalRecordV1(ShadowRecordType(value['record_type']), value['record_sequence'],
                                  value['content_json'], value['diagnostics_json'], value['ruleset'])
    if record.record_id != value['record_id']:
        raise ValueError('journal_record_hash_mismatch')
    return record


def read_shadow_records_v1(path):
    """Only an unfinished final line may be omitted. Prefix corruption raises.

    A complete journal requires a valid footer. A partial final line, including
    a partial footer, cannot establish completeness.
    """
    records = []
    with open(path, 'rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                if records and records[-1].record_type is ShadowRecordType.FOOTER:
                    raise ValueError('data_after_complete_footer')
                break
            records.append(parse_record_line_v1(line.decode('utf-8')))
    return tuple(records)


def replay_shadow_records_v1(*, records):
    if type(records) is not tuple or any(type(r) is not ShadowJournalRecordV1 for r in records):
        raise TypeError('exact_record_tuple_required')
    state = None
    policy = None
    pending = None
    final = None
    complete = False
    divergences = []
    counts = {RuntimeUpdateStatus.ACCEPTED: 0, RuntimeUpdateStatus.REJECTED: 0, RuntimeUpdateStatus.CONTROL: 0}
    for expected, record in enumerate(records, 1):
        try:
            record.__post_init__()
            if record.record_sequence != expected or complete:
                raise ValueError('record_sequence_or_footer_order')
            content = json.loads(record.content_json)
            if record.record_type is ShadowRecordType.HEADER:
                if expected != 1 or state is not None:
                    raise ValueError('header_order')
                if set(content) != {'run_id', 'policy', 'origin', 'scope_label'} or content['origin'] not in ('REAL_GSI', 'SYNTHETIC'):
                    raise ValueError('header_shape')
                policy = LiveRuntimePolicyV1(**content['policy'])
                state = new_live_runtime_state_v1(run_id=content['run_id'], policy=policy)
            elif state is None:
                raise ValueError('header_required')
            elif record.record_type in (ShadowRecordType.INPUT, ShadowRecordType.CONTROL):
                if pending is not None:
                    raise ValueError('input_without_result')
                value = dict(content)
                value['kind'] = RuntimeInputKind(value['kind'])
                if value.get('rejection_reason') is not None:
                    value['rejection_reason'] = RuntimeUpdateReason(value['rejection_reason'])
                inp = RuntimeInputV1(**value)
                post = inp.kind in (RuntimeInputKind.RECEIVED, RuntimeInputKind.REJECTED)
                if post != (record.record_type is ShadowRecordType.INPUT):
                    raise ValueError('input_record_kind_mismatch')
                pending = advance_live_runtime_v1(previous_state=state, runtime_input=inp, policy=policy)
            elif record.record_type is ShadowRecordType.RESULT:
                if pending is None:
                    raise ValueError('result_without_input')
                actual = canonical_json(result_content_v1(pending))
                if actual != record.content_json:
                    divergences.append('record_' + str(expected) + ':result_mismatch')
                state = pending.next_state
                final = actual
                if pending.status in counts:
                    counts[pending.status] += 1
                pending = None
            elif record.record_type is ShadowRecordType.DIAGNOSTIC:
                if pending is not None or content:
                    raise ValueError('diagnostic_order_or_deterministic_content')
            elif record.record_type is ShadowRecordType.FOOTER:
                if (pending is not None or content.get('complete') is not True or
                        content != {'final_state_id': state.state_id, 'complete': True}):
                    raise ValueError('footer_lineage_or_pending_input')
                complete = True
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            divergences.append('record_' + str(expected) + ':' + str(error))
            break
    completeness = (ShadowCompleteness.CORRUPT if divergences else
                    ShadowCompleteness.COMPLETE if complete else ShadowCompleteness.INCOMPLETE)
    return ShadowReplayResultV1(completeness, len(records), counts[RuntimeUpdateStatus.ACCEPTED],
           counts[RuntimeUpdateStatus.REJECTED], counts[RuntimeUpdateStatus.CONTROL], tuple(divergences),
           None if state is None else state.state_id, final)


class ShadowJournalWriterV1:
    """Exclusive, synchronous persistence. A failed write permanently poisons it."""
    def __init__(self, path):
        self.stream = open(path, 'x', encoding='utf-8', newline='\n')
        self.record_sequence = 0
        self.failed = False

    def append(self, records):
        if self.failed or self.stream.closed:
            raise OSError('journal_unavailable')
        if type(records) is not tuple or not records:
            raise ValueError('nonempty_record_transaction_required')
        expected = self.record_sequence
        lines = []
        for record in records:
            if type(record) is not ShadowJournalRecordV1 or record.record_sequence != expected + 1:
                raise ValueError('journal_sequence_mismatch')
            lines.append(record_line_v1(record))
            expected += 1
        try:
            self.stream.write(''.join(lines))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except Exception:
            self.failed = True
            raise
        self.record_sequence = expected

    def close(self):
        self.stream.close()
