from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import run_native_trusted_attempt
from lunar_evolution.native_trusted_output import (
    NativeTrustedOutputError,
    prepare_native_trusted_output,
)
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
    assert result.publication_eligible is False
    assert not (output.parent / "journal.json").exists()


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


@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
def test_prepares_output_from_actual_native_trusted_attempt(tmp_path: Path) -> None:
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
        "budget": {"requests": 0}, "materials": materials,
    }
    body = json.dumps(envelope)
    source = producer_root / "target.c"
    source.write_text(
        '#include <stdio.h>\n#include <sys/stat.h>\n'
        'int main(void) {\n'
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
    process = run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact,
    )
    assert process.exit_code == 0
    result = prepare_native_trusted_output(
        workspace, intent=intent, attestation=attestation, artifact=artifact,
        contract=contract,
        groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN,
    )
    assert result.process_terminal_sha256 == process.terminal_sha256
    assert len(result.drafts) == 1
    assert result.publication_eligible is False
