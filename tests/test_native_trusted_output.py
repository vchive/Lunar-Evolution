from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import pytest
from test_http_transport_deadline import clear_proxy_environment, local_http

from lunar_evolution import producer_process
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import (
    recover_native_trusted_attempt,
    run_native_trusted_attempt,
)
from lunar_evolution.native_trusted_capture import (
    NativeTrustedCaptureError,
    capture_native_trusted_output,
    recover_native_trusted_output_capture,
)
from lunar_evolution.native_trusted_output import (
    NativeTrustedOutputError,
    prepare_native_trusted_output,
)
from lunar_evolution.native_trusted_receipt import persist_native_trusted_execution_receipt
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)

PIN = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "native-trusted-output", "problem_type": "routing",
        "statement": "route", "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
        "decision_variables": ["route"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["valid"],
        "deliverables": ["program"],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    contract = _contract()
    producer_root = tmp_path / "producer"
    producer_root.mkdir()
    target = producer_root / "target"
    target.write_bytes(b"fixture executable\n")
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001",
        run_id="run-001", parent_task_id="parent-001", task_id="task-001",
        contract_sha256=contract.digest(), evaluator_kind="local", evaluator_fingerprint=PIN,
        runner_fingerprint=PIN, generator_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN,
        producer_id="fixture", producer_fingerprint=PIN,
        executable_relative="target", argv=("target",), working_directory="work",
        output_directory="output", request_timeout_seconds=1, max_requests=2,
        output_max_bytes=65536, wall_timeout_seconds=8,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    output = tmp_path / "evolution" / "producer-batches" / intent.journal_id / "output"
    (output / "pkg").mkdir(parents=True)
    materials = []
    for name, source in (("pkg/main.py", b"from helper import VALUE\n"), ("pkg/helper.py", b"VALUE = 1\n")):
        (output / name).write_bytes(source)
        materials.append({
            "kind": "candidate_source", "path": name,
            "size": len(source), "sha256": hashlib.sha256(source).hexdigest(),
        })
    envelope = {
        "schema_version": "1", "producer_id": "fixture", "producer_fingerprint": PIN,
        "status": "completed", "contract_sha256": contract.digest(),
        "budget": {"requests": 1}, "materials": materials,
    }
    (output / "producer-result.json").write_text(json.dumps(envelope), encoding="utf-8")
    import lunar_evolution.native_trusted_output as output_module

    monkeypatch.setattr(output_module, "recover_native_trusted_attempt", lambda *args, **kwargs: {
        "protocol": "lunar-native-trusted-process-terminal-v1", "process_status": "exited_zero",
        "cleanup_status": "cleaned", "gate_released": True, "target_started": True,
        "terminal_sha256": "c" * 64,
    })
    arguments = {
        "intent": intent, "attestation": attestation, "artifact": object(),
        "contract": contract,
        "groups": [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        "evaluator_kind": "local", "evaluator_fingerprint": PIN,
        "runner_fingerprint": PIN, "dependency_sha256": PIN, "environment_sha256": PIN,
    }
    return output, envelope, arguments


def test_prepares_verified_multifile_output_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, envelope, arguments = _fixture(tmp_path, monkeypatch)
    result = prepare_native_trusted_output(tmp_path, **arguments)
    assert result.process_terminal_sha256 == "c" * 64
    assert result.envelope_bytes_sha256 == hashlib.sha256(
        (output / "producer-result.json").read_bytes(),
    ).hexdigest()
    assert result.envelope.producer_id == envelope["producer_id"]
    assert len(result.bundles) == len(result.drafts) == len(result.admission_plan.bundles) == 1
    assert set(result.drafts[0].draft.source_files) == {"pkg/main.py", "pkg/helper.py"}
    assert result.request_coverage == "producer_declaration_only"
    assert result.output_capture_sha256 is None
    assert result.publication_eligible is False
    assert not (output.parent / "journal.json").exists()


def test_strict_preparation_requires_same_attempt_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _output, _, arguments = _fixture(tmp_path, monkeypatch)
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_capture_unverified"):
        prepare_native_trusted_output(
            tmp_path, **arguments, require_same_attempt_capture=True,
        )


def test_formal_preparation_requires_durable_execution_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _output, _, arguments = _fixture(tmp_path, monkeypatch)
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_receipt_unverified"):
        prepare_native_trusted_output(tmp_path, **arguments, require_execution_receipt=True)


@pytest.mark.parametrize("broker_evidence", [
    {"complete": False, "declared_count_matches": True},
    {"complete": True, "declared_count_matches": False},
])
def test_strict_preparation_rejects_incomplete_broker_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broker_evidence: dict[str, bool],
) -> None:
    _output, _, arguments = _fixture(tmp_path, monkeypatch)
    import lunar_evolution.native_trusted_output as output_module

    monkeypatch.setattr(
        output_module, "recover_native_trusted_output_capture",
        lambda *args, **kwargs: {"broker_evidence": broker_evidence},
    )
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_broker_incomplete"):
        prepare_native_trusted_output(
            tmp_path, **arguments, require_same_attempt_capture=True,
        )


def test_requires_successful_verified_process_before_reading_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, arguments = _fixture(tmp_path, monkeypatch)
    import lunar_evolution.native_trusted_output as output_module

    monkeypatch.setattr(output_module, "recover_native_trusted_attempt", lambda *args, **kwargs: {
        "status": "recovery_required", "reason": "native_trusted_attempt_terminal_receipt_missing",
    })
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_process_incomplete"):
        prepare_native_trusted_output(tmp_path, **arguments)
    assert (output / "producer-result.json").exists()


def test_rejects_duplicate_envelope_keys_and_over_budget_declarations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, envelope, arguments = _fixture(tmp_path, monkeypatch)
    path = output / "producer-result.json"
    path.write_text('{"budget":{},"budget":{}}', encoding="utf-8")
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_envelope_unverified"):
        prepare_native_trusted_output(tmp_path, **arguments)
    envelope["budget"] = {"requests": 3}
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_envelope_mismatch"):
        prepare_native_trusted_output(tmp_path, **arguments)


def test_rejects_envelope_symlink_and_raced_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, envelope, arguments = _fixture(tmp_path, monkeypatch)
    path = output / "producer-result.json"
    original = path.read_bytes()
    path.unlink()
    path.symlink_to("pkg/main.py")
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_envelope_unverified"):
        prepare_native_trusted_output(tmp_path, **arguments)
    path.unlink()
    path.write_bytes(original)
    import lunar_evolution.native_trusted_output as output_module

    read = output_module._files.read_regular_file

    def replace_after_first_read(file: Path, maximum: int) -> bytes:
        file.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return read(file, maximum)

    monkeypatch.setattr(output_module._files, "read_regular_file", replace_after_first_read)
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_envelope_changed"):
        prepare_native_trusted_output(tmp_path, **arguments)


def test_rejects_changed_bundle_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, arguments = _fixture(tmp_path, monkeypatch)
    (output / "pkg/helper.py").write_bytes(b"VALUE = 2\n")
    with pytest.raises(ValueError, match="candidate_bundle_.*mismatch|candidate_bundle_.*changed"):
        prepare_native_trusted_output(tmp_path, **arguments)


def test_capture_does_not_create_receipt_after_original_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, arguments = _fixture(tmp_path, monkeypatch)
    with pytest.raises(NativeTrustedCaptureError, match="native_trusted_capture_wall_timeout"):
        capture_native_trusted_output(
            output.parent, intent=arguments["intent"], terminal_sha256="c" * 64,
            broker=None, deadline=time.monotonic() - 1,
        )
    assert not (output.parent / "native-trusted-output-capture.json").exists()


def test_capture_recovery_requires_strict_envelope_identity_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, arguments = _fixture(tmp_path, monkeypatch)
    batch = output.parent
    capture = capture_native_trusted_output(
        batch, intent=arguments["intent"], terminal_sha256="c" * 64,
        broker=None, deadline=time.monotonic() + 5.0,
    )
    evidence = capture["envelope_evidence"]
    assert set(evidence) == {
        "relative_path", "sha256", "bytes", "device", "inode", "mtime_ns", "ctime_ns",
        "identity_before", "identity_after", "read_status",
    }
    assert evidence["identity_before"] == evidence["identity_after"]
    assert evidence["read_status"] == "stable"

    path = batch / "native-trusted-output-capture.json"
    tampered = json.loads(path.read_bytes())
    tampered["envelope_evidence"]["read_status"] = "unknown"
    tampered["capture_sha256"] = producer_process._digest_without(tampered, "capture_sha256")
    path.write_text(json.dumps(tampered, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    terminal = {
        "protocol": "lunar-native-trusted-process-terminal-v1",
        "process_status": "exited_zero", "gate_released": True,
        "target_started": True, "cleanup_status": "cleaned", "terminal_sha256": "c" * 64,
    }
    with pytest.raises(NativeTrustedCaptureError, match="native_trusted_capture_receipt_invalid"):
        recover_native_trusted_output_capture(
            batch, intent=arguments["intent"], terminal=terminal,
        )


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
@pytest.mark.parametrize("brokered", [False, True])
def test_prepares_output_from_actual_native_trusted_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, brokered: bool,
) -> None:
    contract = _contract()
    producer_root = tmp_path / "producer"
    producer_root.mkdir()
    target = producer_root / "target"
    main = "from helper import VALUE\n"
    helper = "VALUE = 1\n"
    materials = [
        {"kind": "candidate_source", "path": name, "size": len(content.encode()),
         "sha256": hashlib.sha256(content.encode()).hexdigest()}
        for name, content in (("pkg/main.py", main), ("pkg/helper.py", helper))
    ]
    envelope = {
        "schema_version": "1", "producer_id": "fixture", "producer_fingerprint": PIN,
        "status": "completed", "contract_sha256": contract.digest(),
        "budget": {"requests": int(brokered)}, "materials": materials,
    }
    body = json.dumps(envelope)
    broker_call = (
        ' const char *w=getenv("LUNAR_PRODUCER_REQUEST_FD");\n'
        ' const char *r=getenv("LUNAR_PRODUCER_RESPONSE_FD");\n'
        ' if (!w || !r) return 10;\n'
        ' const char *q="{\\"protocol\\":\\"lunar-producer-broker-ipc-v1\\",'
        '\\"request_id\\":\\"req-1\\",\\"body_base64\\":\\"aGVsbG8=\\"}\\n";\n'
        ' if (write(atoi(w), q, strlen(q)) != (ssize_t)strlen(q)) return 11;\n'
        ' char reply[4096]; int n=0; char c;\n'
        ' while (n<4095 && read(atoi(r), &c, 1)==1) {reply[n++]=c; if(c==10)break;}\n'
        ' reply[n]=0; if (!strstr(reply,"\\"status\\":\\"completed\\"")) return 12;\n'
    ) if brokered else ""
    source = producer_root / "target.c"
    source.write_text(
        '#include <stdio.h>\n#include <sys/stat.h>\n'
        '#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n'
        'int main(void) {\n'
        + broker_call +
        ' if (mkdir("../output/pkg", 0700) != 0) return 2;\n'
        ' FILE *f = fopen("../output/pkg/main.py", "wb");\n'
        f' if (!f || fputs({json.dumps(main)}, f) < 0 || fclose(f) != 0) return 3;\n'
        ' f = fopen("../output/pkg/helper.py", "wb");\n'
        f' if (!f || fputs({json.dumps(helper)}, f) < 0 || fclose(f) != 0) return 4;\n'
        ' f = fopen("../output/producer-result.json", "wb");\n'
        f' if (!f || fputs({json.dumps(body)}, f) < 0 || fclose(f) != 0) return 5;\n'
        ' return 0;\n}\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["/usr/bin/clang", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
        check=True, capture_output=True,
    )
    artifact = build_native_bootstrap_artifact(tmp_path / "install")
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001",
        run_id="run-001", parent_task_id="parent-001", task_id="task-001",
        contract_sha256=contract.digest(), evaluator_kind="local", evaluator_fingerprint=PIN,
        runner_fingerprint=PIN, generator_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN,
        producer_id="fixture", producer_fingerprint=PIN,
        executable_relative="target", argv=("target",), working_directory="work",
        output_directory="output", request_timeout_seconds=1, max_requests=1,
        output_max_bytes=65536, wall_timeout_seconds=8,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if brokered:
        clear_proxy_environment(monkeypatch)
    with (local_http() if brokered else nullcontext((None, []))) as (endpoint, calls):
        process = run_native_trusted_attempt(
            workspace, producer_root=producer_root, intent=intent,
            attestation=attestation, artifact=artifact,
            broker_config=(ProducerBrokerConfig(endpoint, {}) if endpoint else None),
        )
    assert process.exit_code == 0
    assert len(calls) == int(brokered)
    assert process.output_capture_sha256 is not None
    terminal = recover_native_trusted_attempt(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
    )
    batch = workspace / "evolution" / "producer-batches" / intent.journal_id
    capture = recover_native_trusted_output_capture(batch, intent=intent, terminal=terminal)
    assert capture["capture_sha256"] == process.output_capture_sha256
    assert len(capture["materials"]) == 2
    assert capture["publication_eligible"] is False
    broker_evidence = capture["broker_evidence"]
    if brokered:
        assert broker_evidence["admitted_count"] == 1
        assert broker_evidence["declared_count_matches"] is True
        assert broker_evidence["complete"] is True
        assert broker_evidence["coverage"] == "brokered_requests_only"
        assert set(broker_evidence) == {
            "journal_relative_path", "journal_identity", "journal_sha256", "journal_bytes",
            "admitted_count", "complete", "declared_count_matches", "coverage",
        }
        assert broker_evidence["journal_identity"]["launch_id"] == intent.launch_id
        assert broker_evidence["journal_identity"]["journal_id"] == intent.journal_id
    else:
        assert broker_evidence is None
    result = prepare_native_trusted_output(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
        contract=contract,
        groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN,
        require_same_attempt_capture=True,
    )
    assert result.process_terminal_sha256 == process.terminal_sha256
    assert result.output_capture_sha256 == process.output_capture_sha256
    assert result.request_coverage == (
        "brokered_requests_only" if brokered else "producer_declaration_only"
    )
    assert len(result.drafts) == 1
    assert result.publication_eligible is False
    assert result.execution_receipt_sha256 is None
    if brokered:
        formal = persist_native_trusted_execution_receipt(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
        )
        formal_preparation = prepare_native_trusted_output(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            contract=contract,
            groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
            require_execution_receipt=True,
        )
        assert formal_preparation.execution_receipt_sha256 == formal.receipt_sha256
        assert formal_preparation.request_coverage == "brokered_requests_only"
        assert formal_preparation.publication_eligible is False
    if brokered:
        capture_path = batch / "native-trusted-output-capture.json"
        tampered = json.loads(capture_path.read_bytes())
        tampered["broker_evidence"]["journal_identity"]["max_requests"] = intent.max_requests + 1
        tampered["capture_sha256"] = producer_process._digest_without(tampered, "capture_sha256")
        capture_path.write_text(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")), encoding="utf-8",
        )
        with pytest.raises(NativeTrustedCaptureError, match="native_trusted_capture_broker_invalid"):
            recover_native_trusted_output_capture(batch, intent=intent, terminal=terminal)
        # Restore the valid receipt before exercising independent journal tampering.
        capture_path.write_text(
            json.dumps(capture, sort_keys=True, separators=(",", ":")), encoding="utf-8",
        )
        with (batch / ".host-request-journal" / "requests").open("ab") as journal:
            journal.write(b"tampered\n")
    else:
        (batch / "output" / "pkg" / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(NativeTrustedCaptureError, match="native_trusted_capture_.*"):
        recover_native_trusted_output_capture(batch, intent=intent, terminal=terminal)
    with pytest.raises(NativeTrustedOutputError, match="native_trusted_output_capture_unverified"):
        prepare_native_trusted_output(
            workspace, intent=intent, attestation=attestation, artifact=artifact,
            contract=contract,
            groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
            require_same_attempt_capture=True,
        )
