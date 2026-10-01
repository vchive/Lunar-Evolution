from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target
from test_http_transport_deadline import clear_proxy_environment, local_http

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    audit_native_trusted_lifecycle,
    persist_native_trusted_lifecycle_audit,
    recover_native_trusted_attempt,
    recover_native_trusted_lifecycle_audit,
    run_native_trusted_attempt,
)
from lunar_evolution.native_trusted_capture import capture_native_trusted_output
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
             broker_request: bool = False, mark_started_before_sleep: bool = False):
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
        pre_sleep = (
            f'int fd0 = open("{marker}", O_CREAT | O_WRONLY, 0600); '
            'if (fd0 < 0) return 2; '
            'if (write(fd0, "started", 7) != 7) return 3; '
            'if (close(fd0) != 0) return 4; '
        ) if mark_started_before_sleep else ""
        source.write_text(
            '#include <fcntl.h>\n#include <unistd.h>\n'
            'int main(void) { '
            f'{pre_sleep}'
            f'sleep({target_sleep}); '
            f'int fd = open("{marker}", O_CREAT | O_WRONLY, 0600); '
            'if (fd < 0) return 2; '
            'if (write(fd, "started", 7) != 7) return 3; '
            f'return close(fd) == 0 ? {target_exit} : 4; }}\n',
            encoding="utf-8",
        )
    compile_native_target(source, target)
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


def _materialize_valid_capture(
    batch: Path, intent, terminal: dict[str, object], *, broker=None,
) -> dict[str, object]:
    output = batch / intent.output_directory
    output.mkdir(parents=True, exist_ok=True)
    content = b"candidate = 1\n"
    material = output / "candidate.py"
    material.write_bytes(content)
    envelope = {
        "schema_version": "1", "producer_id": intent.producer_id,
        "producer_fingerprint": intent.producer_fingerprint, "status": "completed",
        "contract_sha256": intent.contract_sha256, "budget": {"requests": 0},
        "materials": [{
            "kind": "candidate_source", "path": "candidate.py", "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }],
    }
    (output / "producer-result.json").write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    deadline = json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
    return capture_native_trusted_output(
        batch, intent=intent, terminal_sha256=terminal["terminal_sha256"], broker=broker,
        deadline=deadline["deadline_monotonic"],
    )


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
    deadline_record = json.loads(
        (batch / "native-trusted-attempt-deadline.json").read_bytes()
    )
    assert deadline_record["launch_id"] == intent.launch_id
    assert deadline_record["journal_id"] == intent.journal_id
    assert deadline_record["launch_sha256"] == terminal["launch_sha256"]
    assert deadline_record["intent_sha256"] == intent.intent_sha256
    assert deadline_record["attestation_sha256"] == attestation.attestation_sha256
    assert terminal["deadline_sha256"] == deadline_record["deadline_sha256"]
    assert deadline_record["deadline_monotonic"] == deadline_record["started_monotonic"] + intent.wall_timeout_seconds
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
def test_audit_native_lifecycle_reports_process_only_when_capture_missing(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, _ = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert audit["status"] == "process_only"
    assert audit["reason"] == "native_trusted_lifecycle_capture_missing"
    assert audit["output_capture_sha256"] is None
    assert audit["broker_coverage"] == "not_observed"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_audit_native_lifecycle_reports_verified_capture(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    capture = _materialize_valid_capture(batch, intent, terminal)
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert audit["status"] == "process_only"
    assert audit["reason"] == "native_trusted_lifecycle_capture_verified"
    assert audit["output_capture_sha256"] == capture["capture_sha256"]
    assert audit["broker_coverage"] == "producer_declaration_only"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_audit_native_lifecycle_rejects_tampered_capture(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    _materialize_valid_capture(batch, intent, terminal)
    capture_path = batch / "native-trusted-output-capture.json"
    capture = json.loads(capture_path.read_bytes())
    capture["publication_eligible"] = True
    capture_path.write_text(json.dumps(capture, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert audit["status"] == "recovery_required"
    assert audit["reason"] == "native_trusted_capture_receipt_invalid"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_audit_native_lifecycle_rejects_tampered_broker_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    clear_proxy_environment(monkeypatch)
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, broker_request=True,
    )
    with local_http() as (endpoint, _calls):
        result = run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=ProducerBrokerConfig(endpoint, {}),
        )
    assert result.broker_observation is not None
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    _materialize_valid_capture(
        batch, intent, terminal, broker=result.broker_observation,
    )
    with (batch / ".host-request-journal" / "requests").open("ab") as journal:
        journal.write(b"tampered\n")
    audit = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert audit["status"] == "recovery_required"
    assert audit["reason"] == "native_trusted_capture_broker_invalid"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_persist_native_lifecycle_audit_is_create_only_and_chain_bound(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    capture = _materialize_valid_capture(batch, intent, terminal)
    audit = persist_native_trusted_lifecycle_audit(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert audit["protocol"] == "lunar-native-trusted-execution-audit-v1"
    assert audit["terminal_sha256"] == terminal["terminal_sha256"]
    assert audit["capture_sha256"] == capture["capture_sha256"]
    assert audit["deadline_sha256"]
    assert audit["publication_eligible"] is False
    with pytest.raises(NativeTrustedAttemptError) as conflict:
        persist_native_trusted_lifecycle_audit(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert conflict.value.code == "native_trusted_lifecycle_audit_write_unknown"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_persist_native_lifecycle_audit_requires_verified_capture(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    with pytest.raises(NativeTrustedAttemptError) as failure:
        persist_native_trusted_lifecycle_audit(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_lifecycle_audit_not_verified"
    assert not (batch / "native-trusted-execution-audit.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_recover_native_lifecycle_audit_revalidates_underlying_chain(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    persisted = _materialize_valid_capture(batch, intent, terminal)
    expected = persist_native_trusted_lifecycle_audit(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    recovered = recover_native_trusted_lifecycle_audit(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert recovered == expected
    assert recovered["capture_sha256"] == persisted["capture_sha256"]

    path = batch / "native-trusted-execution-audit.json"
    tampered = json.loads(path.read_bytes())
    tampered["capture_sha256"] = "f" * 64
    from lunar_evolution import producer_process

    tampered["audit_sha256"] = producer_process._digest_without(tampered, "audit_sha256")
    path.write_text(json.dumps(tampered, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NativeTrustedAttemptError) as failure:
        recover_native_trusted_lifecycle_audit(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_lifecycle_audit_invalid"


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
def test_broker_keeps_pipe_ownership_through_parent_cleanup(tmp_path: Path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    clear_proxy_environment(monkeypatch)
    workspace, producer_root, intent, attestation, artifact, _ = _attempt(
        tmp_path, broker_request=True,
    )
    parent_cleanup = threading.Event()
    serve = runner.serve_producer_broker
    cleanup = runner._cleanup
    thread_type = runner.threading.Thread
    joins = []
    ticks = []

    def observed_clock():
        current = time.monotonic()
        ticks.append(current)
        return current

    def delayed_serve(request_fd, response_fd, **kwargs):
        observation = serve(request_fd, response_fd, **kwargs)
        identities = [os.fstat(fd) for fd in (request_fd, response_fd)]
        assert parent_cleanup.wait(2)
        # The broker thread is the sole owner even when the parent finishes its target cleanup.
        for fd, expected in zip((request_fd, response_fd), identities, strict=True):
            current = os.fstat(fd)
            assert (current.st_dev, current.st_ino) == (expected.st_dev, expected.st_ino)
        return observation

    def signal_cleanup(*args, **kwargs):
        parent_cleanup.set()
        return cleanup(*args, **kwargs)

    class ObservedThread(thread_type):
        def __init__(self, *args, **kwargs):
            self.producer_broker = getattr(kwargs.get("target"), "__name__", None) == "serve"
            super().__init__(*args, **kwargs)

        def join(self, timeout=None):
            if self.producer_broker:
                joins.append((timeout, max(0.0, ticks[0] + intent.wall_timeout_seconds - ticks[-1])))
            return super().join(timeout)

    monkeypatch.setattr(runner, "serve_producer_broker", delayed_serve)
    monkeypatch.setattr(runner, "_cleanup", signal_cleanup)
    monkeypatch.setattr(runner.threading, "Thread", ObservedThread)
    with local_http() as (endpoint, _):
        result = run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=ProducerBrokerConfig(endpoint, {}),
            monotonic=observed_clock,
        )
    assert result.broker_observation is not None and result.broker_observation.complete
    assert result.reason == "native_trusted_attempt_output_capture_unknown"
    assert len(joins) == 1
    timeout, remaining = joins[0]
    assert timeout == remaining


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
    cleanup_deadlines: list[float | None] = []
    original_recovery_cleanup = runner.cleanup_registered_process

    def observed_recovery_cleanup(*args, **kwargs):
        cleanup_deadlines.append(kwargs.get("deadline"))
        return original_recovery_cleanup(*args, **kwargs)

    monkeypatch.setattr(runner, "cleanup_registered_process", observed_recovery_cleanup)
    recovered = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
    )
    assert recovered["execution_outcome"] == "unknown"
    assert recovered["term_sent"] is True
    assert recovered["cleanup_status"] in {"cleaned", "cleanup_unverified", "ownership_lost"}
    assert recovered["pid"] == recovered["pgid"]
    assert cleanup_deadlines and cleanup_deadlines[0] is not None
    deadline_record = json.loads(
        (batch / "native-trusted-attempt-deadline.json").read_bytes()
    )
    assert cleanup_deadlines[0] == deadline_record["deadline_monotonic"]
    try:
        os.waitpid(recovered["pid"], 0)
    except ChildProcessError:
        pass


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_recovery_rejects_tampered_native_attempt_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=0,
    )

    original_atomic_json = runner._atomic_json

    def reject_terminal(path, value, *, exclusive=False):
        if path.name == "native-trusted-process-terminal.json":
            raise ProducerProcessError("producer_process_receipt_write_unknown")
        return original_atomic_json(path, value, exclusive=exclusive)

    # Leave a registered attempt that requires explicit recovery.
    monkeypatch.setattr(runner, "_atomic_json", reject_terminal)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.reason == "native_trusted_attempt_terminal_write_unknown"
    deadline_path = batch / "native-trusted-attempt-deadline.json"
    deadline = json.loads(deadline_path.read_bytes())
    deadline["deadline_monotonic"] = deadline["started_monotonic"]
    deadline["deadline_sha256"] = runner._digest_without(deadline, "deadline_sha256")
    deadline_path.write_text(json.dumps(deadline, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(NativeTrustedAttemptError) as failure:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    with pytest.raises(NativeTrustedAttemptError) as failure:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
        )
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"
    registration = json.loads((batch / "process-registration.json").read_bytes())
    try:
        os.killpg(registration["pid"], 9)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(registration["pid"], 0)
    except ChildProcessError:
        pass


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_recovery_requires_native_attempt_deadline_sidecar(tmp_path: Path):
    """A terminal receipt cannot be recovered without its retained budget."""
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert result.terminal_sha256 is not None
    (batch / "native-trusted-attempt-deadline.json").unlink()
    with pytest.raises(NativeTrustedAttemptError) as failure:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_recovery_deadline_invalid"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_recovery_rejects_valid_but_rebound_native_attempt_deadline(tmp_path: Path):
    """A self-digested replacement budget cannot detach the terminal chain."""
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    deadline_path = batch / "native-trusted-attempt-deadline.json"
    deadline = json.loads(deadline_path.read_bytes())
    deadline["deadline_monotonic"] = deadline["started_monotonic"] + 1.0
    from lunar_evolution import producer_process

    deadline["deadline_sha256"] = producer_process._digest_without(deadline, "deadline_sha256")
    deadline_path.write_text(
        json.dumps(deadline, sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    with pytest.raises(NativeTrustedAttemptError) as failure:
        recover_native_trusted_attempt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
    assert failure.value.code == "native_trusted_recovery_terminal_invalid"


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_lifecycle_audit_keeps_missing_attempt_recovery_required(tmp_path: Path):
    """A missing claim is not reported as a process-only terminal."""
    workspace, _producer_root, intent, attestation, artifact, _ = _attempt(tmp_path)
    result = audit_native_trusted_lifecycle(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert result["status"] == "recovery_required"
    assert result["reason"] == "native_trusted_lifecycle_process_terminal_unverified"
    assert result["terminal_sha256"] is None
    assert result["publication_eligible"] is False


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
def test_recovery_rejects_tampered_native_cancelled_receipt(tmp_path: Path):
    """A self-digested receipt cannot change cancellation into a known exit."""
    from lunar_evolution import producer_process

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=10, mark_started_before_sleep=True,
    )
    marker_seen_at: float | None = None

    def cancelled() -> bool:
        nonlocal marker_seen_at
        if (batch / "work" / "marker").is_file():
            marker_seen_at = marker_seen_at or time.monotonic()
        return marker_seen_at is not None and time.monotonic() - marker_seen_at >= 0.2

    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, cancelled=cancelled,
    )
    assert result.reason == "native_trusted_attempt_cancelled"
    path = batch / "native-trusted-process-terminal.json"
    receipt = json.loads(path.read_bytes())
    assert receipt["process_status"] == "cancelled"
    receipt["process_status"] = "exited_zero"
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


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_cancellation_before_host_accepts_start_frame_cannot_claim_known_terminal(tmp_path, monkeypatch):
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=10, mark_started_before_sleep=True,
    )
    marker = batch / "work" / "marker"
    read_frame = runner._read_attempt_frame
    reads = 0

    def interleaved_read(fd, deadline, monotonic, cancelled):
        nonlocal reads
        reads += 1
        if reads == 2:
            # The target really runs, but cancellation wins before the host consumes its
            # start frame. A target-written file does not replace verified handshake evidence.
            while not marker.exists() or marker.read_bytes() != b"started":
                assert monotonic() < deadline
                time.sleep(0.005)
        return read_frame(fd, deadline, monotonic, cancelled)

    monkeypatch.setattr(runner, "_read_attempt_frame", interleaved_read)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, cancelled=marker.exists,
    )
    assert reads == 2 and marker.read_bytes() == b"started"
    assert result.gate_released and not result.target_started
    assert result.reason == "native_trusted_attempt_cancelled"
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert result.terminal_sha256 is None
    assert not (batch / "native-trusted-process-terminal.json").exists()
    evidence = parse_trusted_bootstrap_evidence((batch / "trusted-bootstrap-evidence.json").read_bytes())
    assert evidence.status == "unknown"
    recovered = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    assert recovered["status"] == "recovery_required"
    assert recovered["reason"] == "native_trusted_attempt_terminal_receipt_missing"
    assert "process_status" not in recovered


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_active_cancellation_terminates_owned_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """An active cancellation must stop a registered target before terminal evidence."""
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=10, mark_started_before_sleep=True,
    )
    started = time.monotonic()
    marker_seen_at: float | None = None

    def cancelled() -> bool:
        # Wait until the target has left the gate and created its marker so this exercises
        # cancellation of a live, owned process rather than the pre-gate admission path.
        nonlocal marker_seen_at
        if (batch / "work" / "marker").is_file():
            marker_seen_at = marker_seen_at or time.monotonic()
        return marker_seen_at is not None and time.monotonic() - marker_seen_at >= 0.2

    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, cancelled=cancelled,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_cancelled"
    assert result.gate_released and result.target_started
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert result.exit_code is None
    assert (batch / "work" / "marker").read_text(encoding="utf-8") == "started"
    assert time.monotonic() - started < intent.wall_timeout_seconds

    # Verified cancellation is a durable process-only terminal variant. Recovery is
    # read-only by default and idempotent; explicit cleanup must also avoid signalling a
    # process a second time once the terminal receipt exists.
    terminal_path = batch / "native-trusted-process-terminal.json"
    assert terminal_path.is_file()
    terminal = json.loads(terminal_path.read_bytes())
    assert terminal["process_status"] == "cancelled"
    assert terminal["exit_code"] is None
    assert terminal["receipt_scope"] == "process_only"
    assert terminal["publication_eligible"] is False
    assert result.terminal_sha256 == terminal["terminal_sha256"]
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    ) == terminal
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    ) == terminal

    import lunar_evolution.native_trusted_attempt as runner

    def must_not_signal(*args, **kwargs):
        pytest.fail("read-only recovery of a terminal cancellation must not signal")

    # The terminal branch must not enter _cleanup_recovered_attempt, even when the caller
    # explicitly asks for cleanup. Patch the low-level signal helper to make that contract
    # deterministic and visible.
    monkeypatch.setattr(runner, "cleanup_registered_process", must_not_signal)
    assert recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact, cleanup=True,
    ) == terminal


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_cancellation_cleanup_uncertainty_is_unknown(tmp_path: Path, monkeypatch):
    """Cancellation cannot claim success when process-group cleanup is unverified."""
    import lunar_evolution.native_trusted_attempt as runner

    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=1, target_sleep=10, mark_started_before_sleep=True,
    )
    marker_seen_at: float | None = None

    def cancelled() -> bool:
        nonlocal marker_seen_at
        if (batch / "work" / "marker").is_file():
            marker_seen_at = marker_seen_at or time.monotonic()
        return marker_seen_at is not None and time.monotonic() - marker_seen_at >= 0.2

    def uncertain_cleanup(owner, process, **kwargs):
        return ProcessCleanupResult(
            label=owner.label, pid=owner.pid, pgid=owner.pgid,
            status=ProcessCleanupStatus.KILL_FAILED, alive_after=True,
        )

    monkeypatch.setattr(runner, "_cleanup", uncertain_cleanup)
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, cancelled=cancelled,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_cleanup_unknown"
    assert result.cleanup_status == "kill_failed"
    assert result.exit_code is None
    assert not (batch / "native-trusted-process-terminal.json").exists()

    # The test deliberately replaced lifecycle cleanup; remove the sleeping fixture
    # after assertions so no child survives the test process.
    registration = json.loads((batch / "process-registration.json").read_bytes())
    pid = registration["pid"]
    try:
        os.killpg(pid, 9)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_active_cancellation_callback_error_has_no_cancelled_receipt(
    tmp_path: Path,
):
    """A callback error after registration remains unknown and cannot publish cancelled."""
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=10, mark_started_before_sleep=True,
    )

    def cancelled() -> bool:
        if (batch / "work" / "marker").is_file():
            raise RuntimeError("callback failed")
        return False

    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, cancelled=cancelled,
    )
    assert result.status == "recovery_required"
    assert result.reason == "native_trusted_attempt_cancellation_unknown"
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert result.exit_code is None
    assert not (batch / "native-trusted-process-terminal.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_parent_deadline_narrows_intent_wall_budget(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(
        tmp_path, timeout=5, target_sleep=10,
    )
    started = time.monotonic()
    result = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
        # Leave enough headroom for Darwin immutable-snapshot setup while still
        # proving the parent budget cuts the five-second intent deadline short.
        parent_deadline=started + 1.5,
    )
    assert result.status == "recovery_required"
    assert result.reason in {
        "native_trusted_attempt_wall_timeout",
        "native_trusted_attempt_cleanup_unknown",
    }
    assert result.gate_released
    assert time.monotonic() - started < intent.wall_timeout_seconds
    assert not (batch / "work" / "marker").exists()
    assert not (batch / "native-trusted-process-terminal.json").exists()


@pytest.mark.parametrize(
    ("cancelled", "code"),
    [
        (lambda: 1, "native_trusted_attempt_cancellation_invalid"),
        (lambda: (_ for _ in ()).throw(RuntimeError("callback failed")),
         "native_trusted_attempt_cancellation_unknown"),
    ],
)
def test_native_attempt_invalid_cancellation_callback_fails_closed(
    tmp_path: Path, cancelled, code: str,
):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact, cancelled=cancelled,
        )
    assert failure.value.code == code
    assert not (batch / "attestation-consumption.json").exists()
    assert not (batch / "process-registration.json").exists()


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_native_attempt_invalid_parent_deadline_fails_closed(tmp_path: Path):
    workspace, producer_root, intent, attestation, artifact, batch = _attempt(tmp_path)
    with pytest.raises(NativeTrustedAttemptError) as failure:
        run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            parent_deadline=float("nan"),
        )
    assert failure.value.code == "native_trusted_attempt_parent_deadline_invalid"
    assert not (batch / "attestation-consumption.json").exists()
    assert not (batch / "process-registration.json").exists()
