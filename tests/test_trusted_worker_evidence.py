from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_producer_bootstrap import _attempt_records

from lunar_evolution import TrustedWorkerEvidenceResult
from lunar_evolution import verify_trusted_worker_evidence as public_verify
from lunar_evolution.native_trusted_attempt import _terminal_receipt
from lunar_evolution.native_trusted_cleanup import _record as _cleanup_record
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import (
    TrustedBootstrapEvidence,
    build_trusted_bootstrap_launch,
)
from lunar_evolution.producer_process import _digest_without
from lunar_evolution.trusted_bootstrap_handoff import (
    build_trusted_bootstrap_process_registration_handoff,
)
from lunar_evolution.trusted_worker_evidence import verify_trusted_worker_evidence


def _chain(tmp_path):
    launch, descriptor, intent, attestation, claim, registration, evidence = _attempt_records(tmp_path)
    handoff = build_trusted_bootstrap_process_registration_handoff(
        launch=launch, descriptor=descriptor, intent=intent, attestation=attestation,
        consumption=claim, registration=registration,
    )
    return {
        'launch': launch, 'descriptor': descriptor, 'intent': intent, 'attestation': attestation,
        'consumption': claim, 'registration': registration, 'handoff': handoff, 'evidence': evidence,
    }


def _rehash(record, field):
    record[field] = _digest_without(record, field)
    return record


def _terminal_chain(tmp_path, *, exit_code=0, cancelled=False):
    chain = _chain(tmp_path)
    launch = chain['launch']
    deadline = _rehash({
        'schema_version': '1', 'protocol': 'lunar-native-trusted-attempt-deadline-v1',
        'launch_id': launch.launch_id, 'journal_id': launch.journal_id,
        'launch_sha256': launch.launch_sha256, 'intent_sha256': launch.intent_sha256,
        'attestation_sha256': launch.attestation_sha256,
        'started_monotonic': 10.0, 'deadline_monotonic': 11.0, 'boot_id': 'fixture-boot',
    }, 'deadline_sha256')
    registration = chain['registration']
    cleanup = _cleanup_record(
        chain['intent'], registration['registration_sha256'], deadline['deadline_sha256'],
        ProcessCleanupResult(
            label='fixture', pid=registration['pid'], pgid=registration['pgid'],
            status=ProcessCleanupStatus.ALREADY_EXITED, alive_after=False,
        ),
    )
    terminal = _terminal_receipt(
        registration, handoff_sha256=chain['handoff']['handoff_sha256'],
        evidence_sha256=chain['evidence'].evidence_sha256,
        gate_released=True, target_started=True, exit_code=None if cancelled else exit_code,
        cleanup_status=cleanup['cleanup_status'], deadline_sha256=deadline['deadline_sha256'],
        cleanup_sha256=cleanup['cleanup_sha256'], cancelled=cancelled,
    )
    return {**chain, 'terminal': terminal, 'deadline': deadline, 'cleanup': cleanup}


def test_handshake_pass_alone_cannot_establish_completion(tmp_path):
    result = verify_trusted_worker_evidence(**_chain(tmp_path))
    assert result.status == 'unknown_recovery_required'
    assert result.reason_code == 'process_terminal_missing'
    assert result.terminal_sha256 is None


@pytest.mark.parametrize(('exit_code', 'cancelled', 'status'), [
    (0, False, 'trusted_completed'), (7, False, 'trusted_failed'),
    (-9, False, 'trusted_failed'), (None, True, 'trusted_failed'),
])
def test_terminal_classification_requires_complete_matching_evidence(
    tmp_path, exit_code, cancelled, status,
):
    chain = _terminal_chain(tmp_path, exit_code=exit_code, cancelled=cancelled)
    result = verify_trusted_worker_evidence(**chain)
    assert result.status == status, result.reason_code
    assert result.reason_code == 'verified'
    for field in ('registration_sha256', 'terminal_sha256', 'deadline_sha256', 'cleanup_sha256'):
        assert result.to_dict()[field] == chain['terminal'][field]
    assert public_verify is verify_trusted_worker_evidence
    assert isinstance(result, TrustedWorkerEvidenceResult)


@pytest.mark.parametrize(('missing', 'reason'), [
    ('evidence', 'bootstrap_evidence_missing'), ('terminal', 'process_terminal_missing'),
    ('deadline', 'original_deadline_missing'), ('cleanup', 'cleanup_evidence_missing'),
])
def test_missing_evidence_remains_unknown(tmp_path, missing, reason):
    chain = _terminal_chain(tmp_path)
    chain[missing] = None
    result = verify_trusted_worker_evidence(**chain)
    assert result.status == 'unknown_recovery_required'
    assert result.reason_code == reason
    assert result.terminal_sha256 is None


def test_failed_handshake_without_process_terminal_is_unknown(tmp_path):
    chain = _chain(tmp_path)
    chain['evidence'] = TrustedBootstrapEvidence(
        launch_sha256=chain['launch'].launch_sha256,
        registration_sha256=chain['registration']['registration_sha256'],
        bootstrap_ready_observed=True, release_observed=True,
        target_started_observed=False, target_start_count=0,
        target_group_identity=None, target_pid=None, target_pgid=None,
        pre_gate_target_work_observed=False, status='failed', failure_code='target_start_failed',
    )
    assert verify_trusted_worker_evidence(**chain).status == 'unknown_recovery_required'


@pytest.mark.parametrize('cancelled', [False, True])
def test_unknown_handshake_only_supports_verified_cancellation(tmp_path, cancelled):
    chain = _terminal_chain(tmp_path, cancelled=cancelled)
    chain['evidence'] = replace(chain['evidence'], status='unknown', evidence_sha256=None)
    chain['terminal']['bootstrap_evidence_sha256'] = chain['evidence'].evidence_sha256
    _rehash(chain['terminal'], 'terminal_sha256')
    result = verify_trusted_worker_evidence(**chain)
    assert result.status == ('trusted_failed' if cancelled else 'identity_drift')


@pytest.mark.parametrize(('record', 'field', 'value'), [
    ('handoff', 'registration_sha256', 'f' * 64),
    ('terminal', 'owner_identity_sha256', 'f' * 64),
    ('terminal', 'registration_sha256', 'f' * 64),
    ('terminal', 'launch_id', 'another-launch'),
    ('terminal', 'parent_task_id', 'another-parent'),
    ('terminal', 'task_id', 'another-task'),
    ('terminal', 'consumption_sha256', 'f' * 64),
    ('terminal', 'bootstrap_descriptor_sha256', 'f' * 64),
    ('terminal', 'pid', 1235), ('terminal', 'pgid', 1235),
    ('terminal', 'handoff_sha256', 'f' * 64),
    ('terminal', 'bootstrap_evidence_sha256', 'f' * 64),
    ('terminal', 'deadline_sha256', 'f' * 64),
    ('terminal', 'cleanup_sha256', 'f' * 64),
    ('terminal', 'cleanup_status', 'uncertain'),
    ('terminal', 'gate_released', False), ('terminal', 'target_started', False),
    ('terminal', 'exit_code', True), ('terminal', 'exit_code', None),
    ('terminal', 'exit_code', 256), ('terminal', 'exit_code', 7),
    ('terminal', 'publication_eligible', 0),
    ('terminal', 'stream_capture_sha256', 'x' * 64),
    ('deadline', 'intent_sha256', 'f' * 64),
    ('deadline', 'attestation_sha256', 'f' * 64),
    ('deadline', 'deadline_monotonic', 12.0),
    ('deadline', 'deadline_monotonic', 10**400),
    ('deadline', 'started_monotonic', 10**400),
    ('deadline', 'started_monotonic', 11.0), ('deadline', 'boot_id', ''),
    ('cleanup', 'registration_sha256', 'f' * 64),
    ('cleanup', 'deadline_sha256', 'f' * 64),
    ('cleanup', 'task_id', 'another-task'),
    ('cleanup', 'pid', 1235), ('cleanup', 'pgid', 1235),
    ('cleanup', 'cleanup_status', 'cleaned'), ('cleanup', 'alive_after', True),
])
def test_rehashed_drift_cannot_establish_terminal_authority(tmp_path, record, field, value):
    chain = _terminal_chain(tmp_path)
    chain[record][field] = value
    _rehash(chain[record], {'handoff': 'handoff_sha256', 'terminal': 'terminal_sha256',
                          'deadline': 'deadline_sha256', 'cleanup': 'cleanup_sha256'}[record])
    result = verify_trusted_worker_evidence(**chain)
    assert result.status == 'identity_drift', result.to_dict()
    assert result.terminal_sha256 is None


def test_even_linked_cleanup_with_alive_process_cannot_complete(tmp_path):
    chain = _terminal_chain(tmp_path)
    chain['cleanup']['alive_after'] = True
    _rehash(chain['cleanup'], 'cleanup_sha256')
    chain['terminal']['cleanup_sha256'] = chain['cleanup']['cleanup_sha256']
    _rehash(chain['terminal'], 'terminal_sha256')
    assert verify_trusted_worker_evidence(**chain).status == 'identity_drift'


@pytest.mark.parametrize('field', ['terminal', 'deadline', 'cleanup'])
@pytest.mark.parametrize('value', [[], 'untrusted', 1, {}])
def test_malformed_records_fail_closed(tmp_path, field, value):
    chain = _terminal_chain(tmp_path)
    chain[field] = value
    assert verify_trusted_worker_evidence(**chain).status == 'identity_drift'


def test_pure_verifier_has_no_filesystem_process_or_clock_effects(tmp_path, monkeypatch):
    import builtins
    import os
    import time

    import lunar_evolution.native_trusted_attempt as native

    chain = _terminal_chain(tmp_path)
    before = repr(chain)

    def forbidden(*args, **kwargs):
        pytest.fail('pure evidence verifier performed I/O, clock or process observation')

    with monkeypatch.context() as patch:
        for obj, names in ((builtins, ['open']), (os, ['stat', 'lstat', 'kill']),
                           (time, ['time', 'monotonic']), (Path, ['open', 'read_bytes']),
                           (native, ['_producer_boot_id', '_read_durable_json'])):
            for name in names:
                patch.setattr(obj, name, forbidden)
        first = verify_trusted_worker_evidence(**chain)
        assert first.status == 'trusted_completed', first.reason_code
        assert verify_trusted_worker_evidence(**chain) == first
    assert repr(chain) == before


@pytest.mark.skipif(sys.platform not in {'darwin', 'linux'}, reason='native bootstrap platform')
@pytest.mark.parametrize('exit_code', [0, 7])
def test_actual_native_terminal_agrees_with_readonly_recovery(tmp_path, exit_code):
    from test_native_trusted_attempt import _attempt

    from lunar_evolution.native_trusted_attempt import (
        recover_native_trusted_attempt,
        run_native_trusted_attempt,
    )

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, target_exit=exit_code,
    )
    run_native_trusted_attempt(workspace, producer_root=producer_root, intent=intent,
                               attestation=attestation, artifact=artifact)
    files = {
        'consumption': 'attestation-consumption.json', 'registration': 'process-registration.json',
        'handoff': 'trusted-bootstrap-handoff.json', 'evidence': 'trusted-bootstrap-evidence.json',
        'terminal': 'native-trusted-process-terminal.json',
        'deadline': 'native-trusted-attempt-deadline.json', 'cleanup': 'native-trusted-cleanup.json',
    }
    retained = {key: (batch / name).read_bytes() for key, name in files.items()}
    identities = {key: (batch / name).stat().st_ino for key, name in files.items()}
    chain = {key: json.loads(raw) for key, raw in retained.items()}
    chain.update(launch=build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor),
                 descriptor=artifact.descriptor, intent=intent, attestation=attestation)
    result = verify_trusted_worker_evidence(**chain)
    assert result.status == ('trusted_completed' if exit_code == 0 else 'trusted_failed'), result
    assert verify_trusted_worker_evidence(**chain) == result
    recovered = recover_native_trusted_attempt(workspace, intent=intent, attestation=attestation,
                                               artifact=artifact)
    assert recovered['terminal_sha256'] == result.terminal_sha256
    assert all((batch / name).read_bytes() == retained[key] for key, name in files.items())
    assert all((batch / name).stat().st_ino == identities[key] for key, name in files.items())
