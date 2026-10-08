"""Actual native delivery of canonical producer configuration through an exact read grant."""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_trusted_attempt import _attempt
from test_producer_bundle_handoff import _contract

from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution import producer_launch_inputs as inputs
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_receipt import (
    NativeTrustedReceiptError,
    persist_native_trusted_execution_receipt,
    recover_native_trusted_execution_receipt,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")


def _inventory(root: Path) -> dict[str, tuple[object, ...]]:
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        result[path.relative_to(root).as_posix()] = (
            path.read_bytes() if stat.S_ISREG(info.st_mode) else None,
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
    return result


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    return build_native_bootstrap_artifact(tmp_path_factory.mktemp("producer-input-bootstrap"))


def _prepared(tmp_path: Path, artifact, *, marker: bool = True):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    producer = tmp_path / "producer"
    producer.mkdir()
    contract = _contract()
    config = {"contract": contract.to_dict(), "search": {"width": 2}, "fixture": "canonical-config"}
    descriptor = inputs.prepare_producer_launch_inputs(
        workspace, journal_id="config-journal", config=config,
    )
    host = workspace / "host-only.json"
    host.write_bytes(b"host fixture must remain inaccessible")
    candidate = b"candidate = 1\n"
    envelope = json.dumps({
        "schema_version": "1", "producer_id": "local-config-fixture",
        "producer_fingerprint": "a" * 64, "status": "completed",
        "contract_sha256": contract.digest(), "budget": {"requests": 0},
        "materials": [{"kind": "candidate_source", "path": "candidate.py",
                       "size": len(candidate), "sha256": hashlib.sha256(candidate).hexdigest()}],
    }, sort_keys=True, separators=(",", ":"))
    program = (
        '#include <errno.h>\n#include <fcntl.h>\n#include <stdio.h>\n#include <string.h>\n'
        '#include <sys/stat.h>\n#include <unistd.h>\n'
        'static int denied(void){return errno==EACCES||errno==EPERM||errno==EXDEV;}\n'
        'static int exact(const char *path,const char *expected){char data[32768];'
        'int fd=open(path,O_RDONLY);if(fd<0)return 0;ssize_t n=read(fd,data,sizeof(data)-1);'
        'if(close(fd)!=0||n<0)return 0;data[n]=0;return strcmp(data,expected)==0;}\n'
        'static int immutable(const char *path){int fd=open(path,O_WRONLY|O_APPEND);'
        'if(fd>=0){close(fd);return 0;}if(!denied())return 0;'
        'if(chmod(path,0600)==0||!denied())return 0;'
        'if(unlink(path)==0||!denied())return 0;'
        'if(rename(path,"../output/stolen-config.json")==0||!denied())return 0;'
        'if(link(path,"../output/config-link.json")==0||!denied())return 0;return 1;}\n'
        'int main(int argc,char **argv){'
        'if(argc!=4||strcmp(argv[1],"../.producer-input/config.json")!=0)return 10;'
        f'if(strcmp(argv[2],{json.dumps(inputs.PRODUCER_LAUNCH_INPUT_MARKER)})!=0)return 11;'
        f'if(strcmp(argv[3],{json.dumps(descriptor.manifest_sha256)})!=0)return 12;'
        f'if(!exact(argv[1],{json.dumps(descriptor.config_json.decode())}))return 13;'
        'if(!immutable(argv[1]))return 14;'
        'int fd=open("../.producer-input/manifest.json",O_RDONLY);'
        'if(fd>=0){close(fd);return 15;}if(!denied())return 16;'
        'fd=open("../native-producer-launch.json",O_RDONLY);'
        'if(fd>=0){close(fd);return 17;}if(!denied())return 18;'
        f'fd=open({json.dumps(str(host))},O_RDONLY);'
        'if(fd>=0){close(fd);return 19;}if(!denied())return 20;'
        'FILE *f=fopen("config-read-marker","wb");'
        'if(!f||fputs("config-readonly",f)<0||fclose(f)!=0)return 21;'
        'f=fopen("../output/candidate.py","wb");'
        f'if(!f||fputs({json.dumps(candidate.decode())},f)<0||fclose(f)!=0)return 22;'
        'f=fopen("../output/producer-result.json","wb");'
        f'if(!f||fputs({json.dumps(envelope)},f)<0||fclose(f)!=0)return 23;return 0;}}\n'
    )
    source = producer / "target.c"
    source.write_text(program)
    compile_native_target(source, producer / "target")
    argv = ("target", "../.producer-input/config.json", *descriptor.argv_fragment) if marker else ("target",)
    intent = build_producer_launch_intent(
        producer_root=producer, launch_id="config-launch", journal_id="config-journal",
        run_id="config-run", parent_task_id="config-parent", task_id="config-task",
        contract_sha256=contract.digest(), evaluator_kind="local", evaluator_fingerprint="a" * 64,
        runner_fingerprint="a" * 64, generator_fingerprint="a" * 64, dependency_sha256="a" * 64,
        environment_sha256="a" * 64, producer_id="local-config-fixture", producer_fingerprint="a" * 64,
        executable_relative="target", argv=argv, working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=4096, wall_timeout_seconds=8,
    )
    attestation = build_producer_launch_attestation(intent, "config-fixture-once")
    if marker:
        descriptor = inputs.bind_producer_launch_inputs(
            workspace, intent=intent, attestation=attestation, artifact=artifact, inputs=descriptor,
        )
    return SimpleNamespace(workspace=workspace, producer=producer, intent=intent,
                           attestation=attestation, artifact=artifact, descriptor=descriptor,
                           batch=workspace / "evolution" / "producer-batches" / intent.journal_id)


def _run(prepared):
    return runner.run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )


def _recover(prepared):
    return runner.recover_native_trusted_attempt(
        prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
        artifact=prepared.artifact,
    )


def _tamper(path: Path, kind: str):
    if kind == "bytes":
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
    elif kind == "inode":
        parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
        path.parent.chmod(0o700)
        try:
            replacement = path.with_name("replacement.json")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o400)
            replacement.replace(path)
        finally:
            path.parent.chmod(parent_mode)
    else:
        path.chmod(0o600)


def test_actual_target_reads_only_config_and_cannot_modify_or_read_host_files(tmp_path, artifact, monkeypatch):
    prepared = _prepared(tmp_path, artifact)
    before = _inventory(prepared.descriptor.inputs_path)
    observed_grants = []
    _observe_control_reads(monkeypatch, lambda _argv, reads: observed_grants.append(reads))
    result = _run(prepared)
    assert result.exit_code == 0 and result.target_started and result.gate_released
    assert result.terminal_sha256 and result.output_capture_sha256
    assert (prepared.batch / "work" / "config-read-marker").read_bytes() == b"config-readonly"
    assert _inventory(prepared.descriptor.inputs_path) == before
    assert len(observed_grants) == 1
    declared = set(observed_grants[0])
    assert str(prepared.descriptor.config_path) in declared
    assert not any(Path(path).is_dir() for path in declared)
    if sys.platform == "linux":
        assert declared == {str(prepared.descriptor.config_path)}
    else:
        assert len(declared) == 2
    assert not (prepared.batch / "output" / "stolen-config.json").exists()
    assert not (prepared.batch / "output" / "config-link.json").exists()


@pytest.mark.parametrize("material", ["config", "manifest", "binding"])
@pytest.mark.parametrize("drift", ["bytes", "inode", "mode"])
def test_drift_refused_before_consumption_or_process_start(tmp_path, artifact, material, drift):
    prepared = _prepared(tmp_path, artifact)
    path = {"config": prepared.descriptor.config_path,
            "manifest": prepared.descriptor.inputs_path / "manifest.json",
            "binding": prepared.batch / "native-producer-launch.json"}[material]
    _tamper(path, drift)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _run(prepared)
    assert not (prepared.batch / "attestation-consumption.json").exists()
    assert not (prepared.batch / "process-registration.json").exists()
    assert not (prepared.batch / "native-trusted-attempt-deadline.json").exists()
    assert not (prepared.batch / "work" / "config-read-marker").exists()


def test_config_changed_after_registration_cannot_release_gate(tmp_path, artifact, monkeypatch):
    prepared = _prepared(tmp_path, artifact)
    publish = runner.publish_trusted_bootstrap_registration

    def change_after_registration(*args, **kwargs):
        published = publish(*args, **kwargs)
        _tamper(prepared.descriptor.config_path, "bytes")
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", change_after_registration)
    result = _run(prepared)
    assert not result.gate_released and not result.target_started
    assert result.reason.startswith("producer_launch_inputs_")
    assert not (prepared.batch / "work" / "config-read-marker").exists()
    assert not (prepared.batch / "native-trusted-process-terminal.json").exists()


def test_recovery_and_formal_receipt_replay_are_readonly_and_revalidate_inputs(tmp_path, artifact, monkeypatch):
    prepared = _prepared(tmp_path, artifact)
    result = _run(prepared)
    assert result.exit_code == 0
    receipt = persist_native_trusted_execution_receipt(
        prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
        artifact=prepared.artifact, require_broker=False,
    )
    terminal = _recover(prepared)
    before = _inventory(prepared.workspace)

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only recovery must not spawn, write, stage or consume")

    for name in ("run_native_trusted_attempt", "_atomic_json", "_recovery_lock",
                 "consume_trusted_bootstrap_attestation"):
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    for _ in range(2):
        assert _recover(prepared) == terminal
        assert recover_native_trusted_execution_receipt(
            prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
            artifact=prepared.artifact, require_broker=False,
        ) == receipt
    assert _inventory(prepared.workspace) == before
    _tamper(prepared.descriptor.config_path, "inode")
    after = _inventory(prepared.workspace)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _recover(prepared)
    with pytest.raises(NativeTrustedReceiptError):
        recover_native_trusted_execution_receipt(
            prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
            artifact=prepared.artifact, require_broker=False,
        )
    assert _inventory(prepared.workspace) == after


def test_staged_config_cannot_downgrade_to_legacy_no_marker_launch(tmp_path, artifact):
    prepared = _prepared(tmp_path, artifact, marker=False)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _run(prepared)
    assert not (prepared.batch / "attestation-consumption.json").exists()


def test_recovery_rechecks_config_after_original_deadline_inspection(tmp_path, artifact, monkeypatch):
    prepared = _prepared(tmp_path, artifact)
    assert _run(prepared).exit_code == 0
    read_deadline = runner._read_deadline
    changed = []

    def mutate_after_deadline(*args, **kwargs):
        deadline = read_deadline(*args, **kwargs)
        _tamper(prepared.descriptor.config_path, "bytes")
        changed.append(_inventory(prepared.workspace))
        return deadline

    monkeypatch.setattr(runner, "_read_deadline", mutate_after_deadline)
    with pytest.raises(runner.NativeTrustedAttemptError):
        _recover(prepared)
    assert len(changed) == 1
    assert _inventory(prepared.workspace) == changed[0]


def test_dual_protocol_markers_refused_before_validation_or_launch(monkeypatch):
    intent = SimpleNamespace(argv=("target", "--lunar-rsi-input-v1", "a" * 64,
                                  inputs.PRODUCER_LAUNCH_INPUT_MARKER, "b" * 64))

    def forbidden(*_args, **_kwargs):
        pytest.fail("conflicting protocols must be refused before file validation")

    monkeypatch.setattr(runner, "validate_native_rsi_launch_inputs", forbidden)
    monkeypatch.setattr(runner, "validate_producer_launch_inputs", forbidden)
    with pytest.raises(runner.NativeTrustedAttemptError, match="launch_inputs_conflict"):
        runner._native_launch_inputs("unused", intent=intent, attestation=None,
                                     artifact=None, require_unexpired=True)


def test_legacy_launch_keeps_original_target_arguments_and_read_grants(tmp_path, monkeypatch):
    workspace, producer, intent, attestation, artifact, _batch = _attempt(tmp_path)
    seen = []
    _observe_control_reads(monkeypatch, lambda argv, reads: seen.append((argv, reads)))
    assert runner._native_launch_inputs(workspace, intent=intent, attestation=attestation,
                                       artifact=artifact, require_unexpired=True) is None
    result = runner.run_native_trusted_attempt(workspace, producer_root=producer, intent=intent,
                                               attestation=attestation, artifact=artifact)
    assert result.exit_code == 0
    assert len(seen) == 1
    argv, reads = seen[0]
    assert argv[1:] == intent.argv[1:]
    assert len(argv) == len(intent.argv)
    assert len(reads) == (1 if sys.platform == "darwin" else 0)


def _observe_control_reads(monkeypatch, observe):
    """Observe the real platform control boundary without changing its grants."""
    name = "encode_native_bootstrap_control_v2" if sys.platform == "linux" else "encode_native_bootstrap_control"
    encode = getattr(runner, name)

    def capture(launch, **kwargs):
        if sys.platform == "linux":
            reads = tuple(record.path for record in kwargs["held_grants"].manifest.records
                          if "protected-file" in record.roles or "readonly-directory" in record.roles)
        else:
            reads = tuple(map(str, kwargs["isolation_policy"].read_paths))
        observe(kwargs["target_argv"], reads)
        return encode(launch, **kwargs)

    monkeypatch.setattr(runner, name, capture)
