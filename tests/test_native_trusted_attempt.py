from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_http_transport_deadline import clear_proxy_environment, local_http

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    recover_native_trusted_attempt,
    run_native_trusted_attempt,
)
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import (
    ProducerBootstrapError,
    build_trusted_bootstrap_launch,
    observe_trusted_bootstrap_attempt,
    parse_trusted_bootstrap_evidence,
)
from lunar_evolution.producer_broker_ipc import (
    ProducerBrokerConfig,
    ProducerBrokerIpcError,
    brokered_producer_post,
    serve_producer_broker,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.producer_process import ProducerProcessError
from lunar_evolution.producer_request_transport import (
    HostRequestJournalIdentity,
    read_host_request_journal,
)
from lunar_evolution.trusted_bootstrap_registration import TrustedBootstrapRegistrationError


def _attempt(tmp_path: Path, *, timeout: int = 8, target_sleep: int = 0, target_exit: int = 0,
             broker_request: bool = False):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    producer_root = tmp_path / "producer"
    producer_root.mkdir()
    target = producer_root / "target"
    source = producer_root / "target.c"
    marker = workspace / "evolution" / "producer-batches" / "journal-001" / "work" / "marker"
    if broker_request:
        source.write_text(
            '#include <fcntl.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n'
            'int main(void) { '
            'const char *w=getenv("LUNAR_PRODUCER_REQUEST_FD"); '
            'const char *r=getenv("LUNAR_PRODUCER_RESPONSE_FD"); '
            'if(!w||!r)return 10; '
            'const char *q="{\\"protocol\\":\\"lunar-producer-broker-ipc-v1\\",\\"request_id\\":\\"req-1\\",\\"body_base64\\":\\"aGVsbG8=\\"}\\n"; '
            'if(write(atoi(w),q,strlen(q))!=(ssize_t)strlen(q))return 11; '
            'char reply[4096]; int n=0; char c; '
            'while(n<4095 && read(atoi(r),&c,1)==1){reply[n++]=c;if(c==10)break;} '
            'reply[n]=0; if(!strstr(reply,"\\"status\\":\\"completed\\""))return 12; '
            f'int fd=open("{marker}",O_CREAT|O_WRONLY,0600); '
            'if(fd<0)return 13; if(write(fd,reply,n)!=n)return 14; '
            'return close(fd); }\n', encoding="utf-8",
        )
    else:
        source.write_text(
            '#include <fcntl.h>\n#include <unistd.h>\n'
            'int main(void) { '
            f'sleep({target_sleep}); '
            f'int fd = open("{marker}", O_CREAT | O_WRONLY, 0600); '
            'if (fd < 0) return 2; '
            'if (write(fd, "started", 7) != 7) return 3; '
            f'return close(fd) == 0 ? {target_exit} : 4; }}\n',
            encoding="utf-8",
        )
    subprocess.run(["/usr/bin/clang", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True)
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    digest = "a" * 64
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001",
        run_id="run-001", parent_task_id="parent-001", task_id="task-001",
        contract_sha256=digest, evaluator_kind="local", evaluator_fingerprint=digest,
        runner_fingerprint=digest, generator_fingerprint=digest,
        dependency_sha256=digest, environment_sha256=digest,
        producer_id="fixture", producer_fingerprint=digest,
        executable_relative="target", argv=("target",),
        working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024,
        wall_timeout_seconds=timeout,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    batch = workspace / "evolution" / "producer-batches" / intent.journal_id
    return workspace, producer_root, intent, attestation, artifact, batch


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_registers_before_release_but_remains_unpublishable(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    marker = batch / "work" / "marker"
    publish = runner.publish_trusted_bootstrap_registration

    def checked_publish(*args, **kwargs):
        assert not marker.exists()
        result = publish(*args, **kwargs)
        assert (batch / "process-registration.json").is_file()
        assert (batch / "trusted-bootstrap-handoff.json").is_file()
        assert not marker.exists()
        return result

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", checked_publish)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_output_capture_unknown"
    assert result.registration_sha256 is not None
    assert result.gate_released and result.target_started
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "started"
    assert not (batch / "execution-receipt.json").exists()
    terminal = json.loads((batch / "native-trusted-process-terminal.json").read_bytes())
    assert result.terminal_sha256 == terminal["terminal_sha256"]
    assert result.output_capture_sha256 is None
    assert terminal["process_status"] == "exited_zero"
    assert terminal["receipt_scope"] == "process_only"
    assert terminal["publication_eligible"] is False
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    ) == terminal
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
    ) == terminal
    evidence = parse_trusted_bootstrap_evidence(
        (batch / "trusted-bootstrap-evidence.json").read_bytes()
    )
    assert evidence.status == "passed"
    assert evidence.target_pgid is not None
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    observed = observe_trusted_bootstrap_attempt(
        workspace, launch=launch, descriptor=artifact.descriptor,
        intent=intent, attestation=attestation, require_handoff=True,
    )
    assert observed["status"] == "evidence_available"
    assert observed["bootstrap_status"] == "passed"
    assert observed["evidence_sha256"] == evidence.evidence_sha256
    assert isinstance(observed["handoff_sha256"], str)
    with pytest.raises(ProducerBootstrapError) as expired:
        observe_trusted_bootstrap_attempt(
            workspace, launch=launch, descriptor=artifact.descriptor,
            intent=intent, attestation=attestation, require_handoff=True,
            deadline=0.0, monotonic=lambda: 0.0,
        )
    assert expired.value.code == "producer_bootstrap_attempt_wall_timeout"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_routes_isolated_target_request_through_host_broker(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, broker_request=True,
    )
    secret = "host-only-secret"
    with local_http() as (endpoint, calls):
        result = run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=ProducerBrokerConfig(endpoint, {"Authorization": secret}),
        )
    assert result.exit_code == 0 and result.target_started
    assert result.broker_observation is not None
    assert result.broker_observation.complete
    assert result.broker_observation.snapshot.admitted_count == 1
    assert result.broker_observation.snapshot.events[0].status == "completed"
    assert len(calls) == 1 and calls[0][1] == b"hello"
    assert calls[0][2]["Authorization"] == secret
    assert secret not in (batch / "work" / "marker").read_text()
    journal = result.broker_observation.journal_path
    assert journal.parent.name == ".host-request-journal"
    assert journal.stat().st_mode & 0o777 == 0o600
    assert journal.parent.stat().st_mode & 0o777 == 0o700
    header = json.loads(journal.read_bytes().splitlines()[0])
    recovery = read_host_request_journal(
        journal, expected_identity=HostRequestJournalIdentity(**header["identity"]),
    )
    assert recovery.uncertain_request_ids == ()
    assert recovery.snapshot.events[0].status == "completed"
    assert result.status == "recovery_required"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_broker_journal_initialization_failure_keeps_native_gate_closed(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    batch.mkdir(parents=True)
    (batch / ".host-request-journal").symlink_to(tmp_path, target_is_directory=True)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
        broker_config=ProducerBrokerConfig("http://127.0.0.1:1", {}),
    )
    assert result.reason == "native_trusted_attempt_broker_unknown"
    assert not result.gate_released and not result.target_started
    assert not (batch / "work" / "marker").exists()


def test_broker_rejects_malformed_target_frame_before_provider_io(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    _, _, intent, _, _, batch = _attempt(tmp_path)
    batch.mkdir(parents=True)
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    try:
        os.write(request_write, b'{"protocol":"lunar-producer-broker-ipc-v1",'
                                b'"request_id":"req-1","request_id":"req-2",'
                                b'"body_base64":""}\n')
        os.close(request_write)
        request_write = -1
        with local_http() as (endpoint, calls):
            observed = serve_producer_broker(
                request_read, response_write, intent=intent,
                journal_dir=batch / ".host-request-journal",
                config=ProducerBrokerConfig(endpoint, {}),
                deadline_ns=time.monotonic_ns() + 2_000_000_000,
            )
        assert not observed.complete
        assert observed.reason == "request_boundary_unknown"
        assert observed.snapshot.admitted_count == 0
        assert calls == []
    finally:
        for fd in (request_read, request_write, response_read, response_write):
            if fd >= 0:
                os.close(fd)


def test_broker_denies_second_request_before_provider_io(tmp_path: Path, monkeypatch):
    clear_proxy_environment(monkeypatch)
    _, _, intent, _, _, batch = _attempt(tmp_path)
    batch.mkdir(parents=True)
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    monkeypatch.setenv("LUNAR_PRODUCER_REQUEST_FD", str(request_write))
    monkeypatch.setenv("LUNAR_PRODUCER_RESPONSE_FD", str(response_read))
    deadline_ns = time.monotonic_ns() + 4_000_000_000
    state = {}

    def run_server(endpoint: str) -> None:
        try:
            state["observed"] = serve_producer_broker(
                request_read, response_write, intent=intent,
                journal_dir=batch / ".host-request-journal",
                config=ProducerBrokerConfig(endpoint, {}), deadline_ns=deadline_ns,
            )
        finally:
            os.close(request_read)
            os.close(response_write)

    with local_http() as (endpoint, calls):
        server = threading.Thread(target=run_server, args=(endpoint,))
        server.start()
        try:
            status, _ = brokered_producer_post("req-1", b"first", deadline_ns=deadline_ns)
            assert status == 200
            with pytest.raises(ProducerBrokerIpcError) as failure:
                brokered_producer_post("req-2", b"second", deadline_ns=deadline_ns)
            assert failure.value.code == "producer_broker_response_missing"
        finally:
            os.close(request_write)
            os.close(response_read)
            server.join(timeout=5)
    assert not server.is_alive()
    assert len(calls) == 1 and calls[0][1] == b"first"
    observed = state["observed"]
    assert not observed.complete
    assert observed.snapshot.admitted_count == 1
    assert observed.snapshot.events[0].status == "completed"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "producer_bootstrap_attempt_handoff_missing"),
        ("tampered", "trusted_bootstrap_handoff_schema_invalid"),
    ],
)
def test_native_attempt_requires_stable_handoff_before_gate(
    tmp_path: Path, monkeypatch, mutation: str, reason: str,
):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    publish = runner.publish_trusted_bootstrap_registration

    def changed_publish(*args, **kwargs):
        result = publish(*args, **kwargs)
        handoff = batch / "trusted-bootstrap-handoff.json"
        if mutation == "missing":
            handoff.unlink()
        else:
            handoff.write_bytes(b"{}")
        return result

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", changed_publish)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == reason
    assert not result.gate_released and not result.target_started
    assert not (batch / "work" / "marker").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_nonzero_target_exit_has_failed_process_receipt_without_publication(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, target_exit=7,
    )
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.exit_code == 7
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_exit_failed"
    receipt = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert receipt["process_status"] == "exited_nonzero"
    assert receipt["exit_code"] == 7
    assert receipt["publication_eligible"] is False
    assert (batch / "native-trusted-process-terminal.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_registration_failure_keeps_gate_closed_and_target_unstarted(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)

    def fail_publish(*args, **kwargs):
        raise TrustedBootstrapRegistrationError("trusted_registration_publication_unknown")

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", fail_publish)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "trusted_registration_publication_unknown"
    assert not result.gate_released and not result.target_started
    assert not (batch / "work" / "marker").exists()
    assert (batch / "attestation-consumption.json").exists()
    assert not (batch / "process-registration.json").exists()
    assert not (batch / "trusted-bootstrap-evidence.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_consumed_nonce_cannot_start_second_native_attempt(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_attempt_claim_failed"
    assert (batch / "work" / "marker").read_text(encoding="utf-8") == "started"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_changed_bootstrap_artifact_is_rejected_before_nonce_consumption(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    artifact.path.write_bytes(artifact.path.read_bytes() + b"\x00")
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_attempt_preflight_invalid"
    assert not (batch / "attestation-consumption.json").exists()
    assert not (batch / "work" / "marker").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_timeout_keeps_unknown_and_cleans_owned_group(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=1, target_sleep=3,
    )
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_wall_timeout"
    assert result.gate_released and result.target_started
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert not (batch / "work" / "marker").exists()
    evidence = parse_trusted_bootstrap_evidence(
        (batch / "trusted-bootstrap-evidence.json").read_bytes()
    )
    assert evidence.status == "unknown"
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    observed = observe_trusted_bootstrap_attempt(
        workspace, launch=launch, descriptor=artifact.descriptor,
        intent=intent, attestation=attestation,
    )
    assert observed["status"] == "recovery_required"
    assert observed["reason"] == "trusted_bootstrap_evidence_unknown"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_evidence_write_failure_stays_recovery_required(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    atomic_json = runner._atomic_json

    def reject_evidence(path, value, *, exclusive=False):
        if path.name == "trusted-bootstrap-evidence.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return atomic_json(path, value, exclusive=exclusive)

    monkeypatch.setattr(runner, "_atomic_json", reject_evidence)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_evidence_write_unknown"
    assert not (batch / "trusted-bootstrap-evidence.json").exists()
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "native-trusted-process-terminal.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_terminal_write_failure_allows_explicit_unknown_recovery(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    atomic_json = runner._atomic_json

    def reject_terminal(path, value, *, exclusive=False):
        if path.name == "native-trusted-process-terminal.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return atomic_json(path, value, exclusive=exclusive)

    monkeypatch.setattr(runner, "_atomic_json", reject_terminal)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.reason == "native_trusted_attempt_terminal_write_unknown"
    assert result.terminal_sha256 is None
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )["reason"] == "native_trusted_attempt_terminal_receipt_missing"
    recovered = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
    )
    assert recovered["status"] == "recovery_required"
    assert recovered["execution_outcome"] == "unknown"
    assert recovered["term_sent"] is False
    assert (batch / "native-trusted-process-recovery.json").is_file()
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    ) == recovered
    with pytest.raises(NativeTrustedAttemptError) as duplicate:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
        )
    assert duplicate.value.code == "native_trusted_recovery_already_recorded"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_explicit_recovery_cleans_live_registered_native_group(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=1, target_sleep=10,
    )

    def interrupted_cleanup(owner, process, **kwargs):
        return ProcessCleanupResult(
            label=owner.label, pid=owner.pid, pgid=owner.pgid,
            status=ProcessCleanupStatus.CLEANUP_UNVERIFIED, alive_after=True,
        )

    monkeypatch.setattr(runner, "_cleanup", interrupted_cleanup)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.terminal_sha256 is None
    assert not (batch / "native-trusted-process-terminal.json").exists()
    recovered = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
    )
    assert recovered["execution_outcome"] == "unknown"
    assert recovered["term_sent"] is True
    assert recovered["cleanup_status"] in {"cleaned", "cleanup_unverified", "ownership_lost"}
    assert recovered["pid"] == recovered["pgid"]
    try:
        os.waitpid(recovered["pid"], 0)
    except ChildProcessError:
        pass


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_recovery_rejects_tampered_native_terminal_receipt(tmp_path: Path):
    from lunar_evolution import producer_process

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    path = batch / "native-trusted-process-terminal.json"
    receipt = json.loads(path.read_bytes())
    receipt["publication_eligible"] = True
    receipt["terminal_sha256"] = producer_process._digest_without(receipt, "terminal_sha256")
    path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NativeTrustedAttemptError) as tampered:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert tampered.value.code == "native_trusted_recovery_terminal_invalid"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_invalid_terminal_frame_persists_failed_evidence(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    read_frame = runner._read_frame
    seen = 0

    def wrong_terminal(fd, deadline, monotonic):
        nonlocal seen
        frame = read_frame(fd, deadline, monotonic)
        seen += 1
        if seen == 3:
            return replace(frame, sequence=2, frame_sha256=None)
        return frame

    monkeypatch.setattr(runner, "_read_frame", wrong_terminal)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.status == "recovery_required"
    assert result.reason == "producer_bootstrap_terminal_order_invalid"
    evidence = parse_trusted_bootstrap_evidence(
        (batch / "trusted-bootstrap-evidence.json").read_bytes()
    )
    assert evidence.status == "failed"
    assert evidence.failure_code == "producer_bootstrap_terminal_order_invalid"
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    observed = observe_trusted_bootstrap_attempt(
        workspace, launch=launch, descriptor=artifact.descriptor,
        intent=intent, attestation=attestation,
    )
    assert observed["status"] == "evidence_available"
    assert observed["bootstrap_status"] == "failed"
