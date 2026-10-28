"""Isolated loopback Shadow capture/replay CLI. No Service, decisions or output.

Example: python -B -m coach02.shadow_runtime_v01 capture --settings <existing>
  --journal <new external.jsonl> --run-id <opaque> --policy-id <opaque>
  --gap-after-ns <integer> --freshness-policy-id <opaque> --max-age-ns <integer>
  --control-interval-ms <integer> --duration-seconds <integer>
"""
import argparse
from dataclasses import asdict
import json
import os
import threading
import time

from coach.gsi import start_receiver
from coach.state import normalize
from .live_runtime_v01 import (LiveRuntimePolicyV1, RuntimeInputKind, RuntimeInputV1,
                              RuntimeUpdateReason, RuntimeUpdateStatus, canonical_json,
                              sanitize_gsi_payload_v1, new_live_runtime_state_v1,
                              advance_live_runtime_v1)
from .shadow_journal_v01 import (ShadowRecordType, ShadowJournalWriterV1, make_record_v1,
                                result_content_v1, read_shadow_records_v1,
                                replay_shadow_records_v1)

HTTP_REASONS = (('auth', RuntimeUpdateReason.INVALID_AUTH),
                ('size', RuntimeUpdateReason.INVALID_SIZE),
                ('path', RuntimeUpdateReason.INVALID_PATH),
                ('json', RuntimeUpdateReason.INVALID_JSON),
                ('shape', RuntimeUpdateReason.INVALID_SHAPE),
                ('transport', RuntimeUpdateReason.INVALID_TRANSPORT),
                ('internal', RuntimeUpdateReason.INVALID_TRANSPORT))


class ShadowCaptureV1:
    """Single serialization point. Journal durability precedes state publication."""
    def __init__(self, *, run_id, policy, writer, clock=time.monotonic_ns,
                 origin='REAL_GSI', scope_label=''):
        self.lock = threading.Lock()
        self.clock = clock
        self.origin_ns = clock()
        self.state = new_live_runtime_state_v1(run_id=run_id, policy=policy)
        self.policy = policy
        self.writer = writer
        self.failed = threading.Event()
        self.failure_reason = None
        self.parity_checks = 0
        self.accepted_count = 0
        self.first_valid_elapsed_ns = None
        self.last_valid_elapsed_ns = None
        self.closed = False
        self._append((make_record_v1(ShadowRecordType.HEADER, 1,
                     dict(run_id=run_id, policy=asdict(policy), origin=origin, scope_label=scope_label)),))

    def _append(self, records):
        try:
            self.writer.append(records)
        except Exception as error:
            self.failure_reason = type(error).__name__
            self.failed.set()
            raise

    def _transition(self, inp, diagnostics=None):
        if self.failed.is_set() or self.closed:
            raise RuntimeError('shadow_capture_fail_stop')
        started = self.clock()
        result = advance_live_runtime_v1(previous_state=self.state, runtime_input=inp, policy=self.policy)
        if result.status is RuntimeUpdateStatus.ERROR:
            raise RuntimeError('runtime_internal_error')
        compose_ns = self.clock() - started
        seq = self.writer.record_sequence
        kind = ShadowRecordType.INPUT if inp.kind in (RuntimeInputKind.RECEIVED, RuntimeInputKind.REJECTED) else ShadowRecordType.CONTROL
        diagnostic = dict(diagnostics or {}, compose_ns=compose_ns)
        self._append((make_record_v1(kind, seq + 1, asdict(inp)),
                      make_record_v1(ShadowRecordType.RESULT, seq + 2, result_content_v1(result), diagnostic)))
        journal_ns = self.clock() - started - compose_ns
        # Timings are a separate diagnostic record, excluded from content IDs.
        self._append((make_record_v1(ShadowRecordType.DIAGNOSTIC, seq + 3, {},
                      dict(compose_ns=compose_ns, journal_ns=journal_ns, **(diagnostics or {}))),))
        self.state = result.next_state
        if result.status is RuntimeUpdateStatus.ACCEPTED:
            self.accepted_count += 1
            if self.first_valid_elapsed_ns is None:
                self.first_valid_elapsed_ns = inp.receipt_elapsed_ns
            self.last_valid_elapsed_ns = inp.receipt_elapsed_ns
        return result

    def request_hook(self, outcome):
        with self.lock:
            try:
                if self.failed.is_set() or self.closed:
                    raise RuntimeError('shadow_capture_fail_stop')
                elapsed = self.clock() - self.origin_ns
                last = self.state.last_valid_receipt_elapsed_ns
                if last is not None and not self.state.gap_open and elapsed - last > self.policy.gap_after_ns:
                    self._transition(RuntimeInputV1(RuntimeInputKind.TIME_ADVANCE, elapsed))
                sequence = self.state.receive_sequence + 1
                diagnostics = {key: outcome[key] for key in ('http_status', 'read_ns', 'parse_ns', 'normalize_ns', 'parse_normalize_ns', 'after_body_start_ns') if key in outcome}
                after_body = diagnostics.pop('after_body_start_ns', None)
                sanitize_start = self.clock()
                if outcome['classification'] == 'accepted':
                    try:
                        original = outcome['payload']
                        sanitized = sanitize_gsi_payload_v1(payload=original)
                        projected = normalize(sanitized)
                        if canonical_json(projected.to_dict()) != canonical_json(outcome['state'].to_dict()):
                            raise RuntimeError('sanitization_normalization_parity_failure')
                        self.parity_checks += 1
                        inp = RuntimeInputV1(RuntimeInputKind.RECEIVED, elapsed, sequence, canonical_json(sanitized))
                    except (ValueError, TypeError, RecursionError):
                        inp = RuntimeInputV1(RuntimeInputKind.REJECTED, elapsed, sequence,
                                             rejection_reason=RuntimeUpdateReason.INVALID_SHAPE)
                else:
                    reason = dict(HTTP_REASONS).get(outcome['classification'])
                    if reason is None:
                        raise ValueError('unknown_http_classification')
                    inp = RuntimeInputV1(RuntimeInputKind.REJECTED, elapsed, sequence, rejection_reason=reason)
                diagnostics['sanitize_ns'] = self.clock() - sanitize_start
                result = self._transition(inp, diagnostics)
                if after_body is not None:
                    self._append((make_record_v1(ShadowRecordType.DIAGNOSTIC,
                                  self.writer.record_sequence + 1, {},
                                  dict(total_after_body_ns=self.clock() - after_body)),))
                return result
            except Exception as error:
                self.failure_reason = str(error)
                self.failed.set()
                raise

    def control(self, kind=RuntimeInputKind.TIME_ADVANCE):
        with self.lock:
            try:
                return self._transition(RuntimeInputV1(kind, self.clock() - self.origin_ns))
            except Exception as error:
                self.failure_reason = str(error)
                self.failed.set()
                raise

    def finish(self):
        with self.lock:
            if self.failed.is_set() or self.closed:
                raise RuntimeError('cannot_complete_failed_capture')
            self._transition(RuntimeInputV1(RuntimeInputKind.SHUTDOWN, self.clock() - self.origin_ns))
            self._append((make_record_v1(ShadowRecordType.FOOTER, self.writer.record_sequence + 1,
                          dict(final_state_id=self.state.state_id, complete=True)),))
            self.closed = True
        self.writer.close()


def read_receiver_settings_v1(path):
    with open(path, encoding='utf-8') as stream:
        settings = json.load(stream)
    port, token = settings.get('port'), settings.get('token')
    if type(port) is not int or not 1 <= port <= 65535 or type(token) is not str or not token.strip():
        raise ValueError('invalid_existing_receiver_settings')
    return port, token


def main(argv=None):
    parser = argparse.ArgumentParser(description='Isolated no-output Shadow foundation')
    commands = parser.add_subparsers(dest='command', required=True)
    replay = commands.add_parser('replay')
    replay.add_argument('--journal', required=True)
    capture = commands.add_parser('capture')
    capture.add_argument('--settings', default=os.path.join(os.environ.get('LOCALAPPDATA', ''), 'DotaAICoach02', 'settings02.json'))
    capture.add_argument('--journal', required=True)
    capture.add_argument('--run-id', required=True)
    capture.add_argument('--policy-id', required=True)
    capture.add_argument('--gap-after-ns', required=True, type=int)
    capture.add_argument('--freshness-policy-id', required=True)
    capture.add_argument('--max-age-ns', required=True, type=int)
    capture.add_argument('--control-interval-ms', required=True, type=int)
    capture.add_argument('--duration-seconds', required=True, type=int)
    capture.add_argument('--scope-label', default='')
    args = parser.parse_args(argv)
    if args.command == 'replay':
        result = replay_shadow_records_v1(records=read_shadow_records_v1(args.journal))
        print(canonical_json(asdict(result)))
        return 0 if result.completeness.value == 'COMPLETE' and result.divergence_count == 0 else 1
    if args.control_interval_ms <= 0 or args.duration_seconds <= 0:
        parser.error('positive control interval and duration required')
    policy = LiveRuntimePolicyV1(args.policy_id, args.gap_after_ns, args.freshness_policy_id, args.max_age_ns)
    port, token = read_receiver_settings_v1(args.settings)
    # Bind first: collision fails without creating a journal or changing settings.
    holder = {}
    ready = threading.Event()
    def receiver_hook(outcome):
        ready.wait()
        if 'capture' not in holder:
            raise RuntimeError('shadow_capture_initialization_failed')
        return holder['capture'].request_hook(outcome)
    server, thread = start_receiver(port, token, lambda state: None, lambda reason: None,
                                    on_request_result=receiver_hook)
    writer = None
    try:
        writer = ShadowJournalWriterV1(args.journal)
        capture_state = ShadowCaptureV1(run_id=args.run_id, policy=policy, writer=writer, scope_label=args.scope_label)
        holder['capture'] = capture_state
        ready.set()
        print(canonical_json(dict(status='LISTENING', port=port, run_id=args.run_id)), flush=True)
        started = time.monotonic_ns()
        while time.monotonic_ns() - started < args.duration_seconds * 1_000_000_000:
            if capture_state.failed.wait(args.control_interval_ms / 1000):
                raise RuntimeError('shadow_capture_failed:' + str(capture_state.failure_reason))
            capture_state.control()
        server.shutdown()
        thread.join(timeout=5)
        capture_state.finish()
        print(canonical_json(dict(status='COMPLETE', accepted=capture_state.accepted_count,
              parity_checks=capture_state.parity_checks,
              first_valid_elapsed_ns=capture_state.first_valid_elapsed_ns,
              last_valid_elapsed_ns=capture_state.last_valid_elapsed_ns)), flush=True)
        return 0
    finally:
        ready.set()
        server.shutdown()
        server.server_close()
        if writer is not None and not writer.stream.closed:
            writer.close()


if __name__ == '__main__':
    raise SystemExit(main())
