"""Request and frozen-memory delivery is admitted before one actual native launch."""

from __future__ import annotations

import hashlib
import json
import stat
import sys
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target

from lunar_evolution import rsi_native_inputs as inputs
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    recover_native_trusted_attempt,
    run_native_trusted_attempt,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemoryItem, MemorySnapshot

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")

HEX = "a" * 64


def _memory() -> MemorySnapshot:
    return MemorySnapshot("native-frozen", HEX, (MemoryItem(
        memory_id="retained-strategy", problem_family="local-fixture", trigger="small input",
        strategy="choose a bounded exact candidate", expected_result="pass",
        failure_boundary="local frozen fixture only", compatible_contracts=(HEX,),
        compatible_solvers=("native_population",), verifier_outcome="pass",
        receipt_sha256="b" * 64, episode_id="prior-practice",
    ),))


def _request(memory: MemorySnapshot, *, deadline: float | None = None) -> SolverRequest:
    budget = RSIRunBudget.create({
        "max_target_attempts": 2, "max_solver_invocations": 2,
        "max_evaluator_invocations": 2, "max_verifier_invocations": 2,
        "deadline_unix": time.time() + 120 if deadline is None else deadline,
    }).to_dict()["planned"]
    return SolverRequest.build(
        episode_id="native-episode", contract_sha256=HEX, evaluator_sha256=HEX,
        environment_sha256=HEX, memory_snapshot_sha256=memory.digest(),
        solver_id="native_population", solver_settings={"search": {"width": 2}},
        budget=budget, practice_charter={"trigger": "small input", "failure_boundary": "fixture"},
    )


def _inventory(root: Path) -> dict[str, tuple[object, ...]]:
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        content = path.read_bytes() if stat.S_ISREG(info.st_mode) else None
        result[path.relative_to(root).as_posix()] = (
            content, info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        )
    return result


@pytest.fixture(scope="module")
def native_artifact(tmp_path_factory):
    return build_native_bootstrap_artifact(tmp_path_factory.mktemp("native-rsi-bootstrap"))


def _prepared(tmp_path: Path, native_artifact, *, argv: tuple[str, ...] | None = None,
              working_directory: str = "work", request: SolverRequest | None = None,
              stage_inputs: bool = True):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = _memory()
    request = request or _request(memory)
    descriptor = (inputs.prepare_native_rsi_inputs(
        workspace, journal_id="native-journal", request=request, memory=memory,
    ) if stage_inputs else None)
    producer = tmp_path / "producer"
    producer.mkdir()
    (producer / "target").write_bytes(b"local inert fixture executable\n")
    (producer / "target").chmod(0o700)
    intent = build_producer_launch_intent(
        producer_root=producer, launch_id="native-launch", journal_id="native-journal",
        run_id="native-run", parent_task_id="native-parent", task_id="native-task",
        contract_sha256=HEX, evaluator_kind="local", evaluator_fingerprint=HEX,
        runner_fingerprint=HEX, generator_fingerprint=HEX, dependency_sha256=HEX,
        environment_sha256=HEX, producer_id="local-rsi-fixture", producer_fingerprint=HEX,
        executable_relative="target", argv=argv or (
            ("target", *descriptor.argv_fragment) if descriptor is not None else ("target",)
        ),
        working_directory=working_directory, output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=4096, wall_timeout_seconds=8,
    )
    attestation = build_producer_launch_attestation(intent, "native-rsi-fixture-once")
    batch = workspace / "evolution" / "producer-batches" / intent.journal_id
    return SimpleNamespace(workspace=workspace, memory=memory, request=request, descriptor=descriptor,
                           producer=producer, intent=intent, attestation=attestation,
                           artifact=native_artifact, batch=batch)


def _bind(prepared):
    return inputs.bind_native_rsi_launch(
        prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
        artifact=prepared.artifact, inputs=prepared.descriptor,
    )


def _validate(prepared, **kwargs):
    return inputs.validate_native_rsi_launch_inputs(
        prepared.workspace, intent=prepared.intent, attestation=prepared.attestation,
        artifact=prepared.artifact, **kwargs,
    )


def _new_intent(intent, **changes):
    values = intent.to_dict() | changes | {"intent_sha256": None}
    values["argv"] = tuple(values["argv"])
    values["argv_sha256"] = hashlib.sha256(canonical_json(list(values["argv"]))).hexdigest()
    changed = type(intent)(**values)
    return replace(changed, intent_sha256=changed.digest())


def test_staged_inputs_preserve_the_full_canonical_request_and_approved_memory(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    descriptor = prepared.descriptor
    assert descriptor.argv_fragment == ("--lunar-rsi-input-v1", descriptor.manifest_sha256)
    assert tuple(Path(path).name for path in descriptor.read_paths) == ("request.json", "memory.json")
    assert all(Path(path).is_absolute() for path in descriptor.read_paths)
    assert Path(descriptor.read_paths[0]).read_bytes() == canonical_json(prepared.request.to_dict())
    assert Path(descriptor.read_paths[1]).read_bytes() == prepared.memory.to_bytes()
    assert descriptor.deadline_unix == dict(prepared.request.budget)["deadline_unix"]
    assert json.loads(Path(descriptor.read_paths[0]).read_bytes())["budget"] == dict(prepared.request.budget)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        descriptor.manifest_sha256 = "b" * 64


def test_bound_inputs_validate_read_only_and_do_not_infer_solver_completion(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    descriptor = _bind(prepared)
    assert descriptor.launch_binding_sha256
    before = _inventory(prepared.workspace)
    for _ in range(3):
        retained = _validate(prepared)
        assert retained == descriptor
        assert retained.read_paths == prepared.descriptor.read_paths
    assert _inventory(prepared.workspace) == before
    assert not (prepared.batch / "execution-receipt.json").exists()
    assert not (prepared.batch / "process-registration.json").exists()
    assert not hasattr(descriptor, "result")


def test_mismatched_memory_request_rejects_before_any_input_creation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = _memory()
    request = replace(_request(memory), memory_snapshot_sha256="c" * 64)
    before = _inventory(workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        inputs.prepare_native_rsi_inputs(workspace, journal_id="native-journal",
                                        request=request, memory=memory)
    assert _inventory(workspace) == before


def test_expired_original_deadline_cannot_prepare_new_inputs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = _memory()
    before = _inventory(workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        inputs.prepare_native_rsi_inputs(workspace, journal_id="native-journal",
                                        request=_request(memory, deadline=time.time() - 1), memory=memory)
    assert _inventory(workspace) == before


def test_staged_descriptor_copies_nested_inputs_and_exposes_fresh_request_values(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    original_wire = prepared.descriptor.request_json
    dict(prepared.request.solver_settings)["search"]["width"] = 99
    exposed = prepared.descriptor.request
    dict(exposed.solver_settings)["search"]["width"] = 101
    assert prepared.descriptor.request_json == original_wire
    assert dict(prepared.descriptor.request.solver_settings)["search"] == {"width": 2}
    assert Path(prepared.descriptor.read_paths[0]).read_bytes() == original_wire
    descriptor = _bind(prepared)
    assert descriptor.request_json == original_wire
    assert _validate(prepared).request_json == original_wire


def test_caller_fabricated_descriptor_cannot_change_retained_request_at_binding(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    forged_request = replace(prepared.request, episode_id="other-episode")
    prepared.descriptor = replace(
        prepared.descriptor, request_json=canonical_json(forged_request.to_dict()),
        request_sha256=forged_request.digest(),
    )
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


def test_original_deadline_expiration_also_blocks_the_launch_binding(tmp_path, native_artifact, monkeypatch):
    prepared = _prepared(tmp_path, native_artifact)
    before = _inventory(prepared.workspace)
    monkeypatch.setattr(inputs.time, "time", lambda: prepared.descriptor.deadline_unix + 1)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


def test_nullable_parent_deadline_is_preserved_without_inventing_a_new_run_budget(tmp_path, native_artifact):
    request = _request(_memory())
    budget = dict(request.budget) | {"deadline_unix": None}
    prepared = _prepared(tmp_path, native_artifact, request=replace(request, budget=tuple(sorted(budget.items()))))
    descriptor = _bind(prepared)
    assert descriptor.deadline_unix is None
    assert _validate(prepared, require_unexpired=True).deadline_unix is None
    assert _validate(prepared).request.to_dict()["budget"] == budget


@pytest.mark.parametrize("deadline", [True, False, 0, -1, "later", float("inf"), float("nan")])
def test_malformed_deadline_is_rejected_before_staging(tmp_path, deadline):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory = _memory()
    request = replace(_request(memory), budget=(("deadline_unix", deadline),))
    before = _inventory(workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        inputs.prepare_native_rsi_inputs(workspace, journal_id="native-journal",
                                        request=request, memory=memory)
    assert _inventory(workspace) == before


def test_preparation_cannot_replace_an_existing_input_identity(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        inputs.prepare_native_rsi_inputs(
            prepared.workspace, journal_id=prepared.intent.journal_id,
            request=prepared.request, memory=prepared.memory,
        )
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("field", ["contract_sha256", "evaluator_fingerprint", "environment_sha256"])
def test_launch_identity_pins_must_match_the_original_request(tmp_path, native_artifact, field):
    prepared = _prepared(tmp_path, native_artifact)
    prepared.intent = _new_intent(prepared.intent, **{field: "c" * 64})
    prepared.attestation = build_producer_launch_attestation(prepared.intent, "changed-pin-once")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


def test_launch_cannot_change_the_fixed_input_delivery_working_directory(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact, working_directory="other")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("argv_kind", ["missing", "wrong_digest", "duplicated", "not_tail"])
def test_reserved_input_marker_is_exact_unique_and_final(tmp_path, native_artifact, argv_kind):
    prepared = _prepared(tmp_path, native_artifact)
    marker = prepared.descriptor.argv_fragment
    argv = {
        "missing": ("target",),
        "wrong_digest": ("target", marker[0], "c" * 64),
        "duplicated": ("target", *marker, *marker),
        "not_tail": ("target", *marker, "other-argument"),
    }[argv_kind]
    prepared.intent = _new_intent(prepared.intent, argv=argv)
    prepared.attestation = build_producer_launch_attestation(prepared.intent, "changed-argv-once")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("existing", ["native-trusted-attempt-deadline.json", "process-registration.json",
                                      "execution-receipt.json"])
def test_preexisting_attempt_cannot_be_attributed_to_a_new_rsi_binding(tmp_path, native_artifact, existing):
    prepared = _prepared(tmp_path, native_artifact)
    (prepared.batch / existing).write_bytes(b"{}")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _bind(prepared)
    assert _inventory(prepared.workspace) == before


def test_bound_launch_cannot_remove_its_marker_or_claim_a_different_attestation(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    original_intent, original_attestation = prepared.intent, prepared.attestation
    prepared.intent = _new_intent(original_intent, argv=("target",))
    prepared.attestation = build_producer_launch_attestation(prepared.intent, "without-marker-once")
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    prepared.intent = original_intent
    prepared.attestation = build_producer_launch_attestation(original_intent, "other-attestation-once")
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    prepared.attestation = original_attestation
    assert _validate(prepared) is not None
    assert _inventory(prepared.workspace) == before


@pytest.mark.parametrize("material", ["request", "memory", "manifest", "binding"])
@pytest.mark.parametrize("change", ["bytes", "missing", "symlink", "inode"])
def test_input_material_drift_is_refused_without_repair(tmp_path, native_artifact, material, change):
    prepared = _prepared(tmp_path, native_artifact)
    staged = {path for path in prepared.batch.rglob("*.json")}
    _bind(prepared)
    bound = {path for path in prepared.batch.rglob("*.json")} - staged
    request_path, memory_path = map(Path, prepared.descriptor.read_paths)
    manifest, = staged - {request_path, memory_path}
    binding, = bound
    path = {"request": request_path, "memory": memory_path,
            "manifest": manifest, "binding": binding}[material]
    original = path.read_bytes()
    original_info = path.stat()
    original_mode = stat.S_IMODE(original_info.st_mode)
    if change == "bytes":
        path.chmod(0o600)
        path.write_bytes(original + b" ")
        path.chmod(original_mode)
    else:
        parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
        path.parent.chmod(0o700)
        if change == "inode":
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(original)
            replacement.chmod(original_mode)
            replacement.replace(path)
            assert (path.stat().st_dev, path.stat().st_ino) != (original_info.st_dev, original_info.st_ino)
        else:
            path.unlink()
            if change == "symlink":
                retained = tmp_path / "detached-original.json"
                retained.write_bytes(original)
                path.symlink_to(retained)
        path.parent.chmod(parent_mode)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert _inventory(prepared.workspace) == before


def test_historical_validation_keeps_original_deadline_but_live_admission_refuses_expiration(
    tmp_path, native_artifact, monkeypatch,
):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    deadline = prepared.descriptor.deadline_unix
    before = _inventory(prepared.workspace)
    monkeypatch.setattr(inputs.time, "time", lambda: deadline + 1)
    assert _validate(prepared).deadline_unix == deadline
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared, require_unexpired=True)
    assert _inventory(prepared.workspace) == before


def test_marker_without_binding_never_downgrades_to_an_unbound_native_launch(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert _inventory(prepared.workspace) == before


def test_input_replacement_during_launch_validation_is_rejected_after_the_final_read(
    tmp_path, native_artifact, monkeypatch,
):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    original = inputs._launch_payload

    def interleaved(*args, **kwargs):
        result = original(*args, **kwargs)
        path = Path(prepared.descriptor.read_paths[1])
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
        return result

    monkeypatch.setattr(inputs, "_launch_payload", interleaved)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert Path(prepared.descriptor.read_paths[1]).read_bytes().endswith(b" ")
    assert not (prepared.batch / "execution-receipt.json").exists()


def test_plain_native_launch_without_input_marker_or_binding_remains_unbound(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact, argv=("target",), stage_inputs=False)
    before = _inventory(prepared.workspace)
    assert _validate(prepared) is None
    assert _inventory(prepared.workspace) == before


def test_staged_inputs_cannot_be_downgraded_by_stripping_the_reserved_marker(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact, argv=("target",))
    before = _inventory(prepared.workspace)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert _inventory(prepared.workspace) == before


def _real_target(prepared, *, target_delay: int = 0) -> None:
    request_json = canonical_json(prepared.request.to_dict()).decode("utf-8")
    memory_json = prepared.memory.to_bytes().decode("utf-8")
    request_path, memory_path = map(Path, prepared.descriptor.read_paths)
    host_path = prepared.workspace / "host-only.json"
    host_path.write_bytes(b"host fixture must remain inaccessible")
    manifest, = set(prepared.batch.rglob("*.json")) - {request_path, memory_path, host_path}
    source = prepared.producer / "target.c"
    source.write_text(
        '#include <errno.h>\n#include <fcntl.h>\n#include <stdio.h>\n#include <string.h>\n'
        '#include <sys/stat.h>\n#include <unistd.h>\n'
        'static int denied(void){return errno==EACCES||errno==EPERM;}\n'
        'static int exact(const char *path,const char *expected){char data[32768];'
        'int fd=open(path,O_RDONLY);if(fd<0)return 0;ssize_t n=read(fd,data,sizeof(data)-1);'
        'if(close(fd)!=0||n<0)return 0;data[n]=0;return strcmp(data,expected)==0;}\n'
        'static int immutable(const char *path,const char *renamed,const char *linked){'
        'int fd=open(path,O_WRONLY|O_APPEND);if(fd>=0){close(fd);return 0;}if(!denied())return 0;'
        'if(chmod(path,0600)==0||!denied())return 0;'
        'if(unlink(path)==0||!denied())return 0;'
        'if(rename(path,renamed)==0||!denied())return 0;'
        'if(link(path,linked)==0||!denied())return 0;return 1;}\n'
        'int main(int argc,char **argv){'
        'if(argc!=3||strcmp(argv[1],"--lunar-rsi-input-v1")!=0)return 10;'
        f'if(strcmp(argv[2],{json.dumps(prepared.descriptor.manifest_sha256)})!=0)return 11;'
        f'if(!exact("../.rsi-input/request.json",{json.dumps(request_json)}))return 12;'
        f'if(!exact("../.rsi-input/memory.json",{json.dumps(memory_json)}))return 13;'
        'if(!immutable("../.rsi-input/request.json","../output/stolen-request.json","../output/request-link.json"))return 14;'
        'if(!immutable("../.rsi-input/memory.json","../output/stolen-memory.json","../output/memory-link.json"))return 15;'
        f'int fd=open({json.dumps(str(host_path))},O_RDONLY);'
        'if(fd>=0){close(fd);return 16;}if(!denied())return 17;'
        f'fd=open({json.dumps(str(manifest))},O_RDONLY);'
        'if(fd>=0){close(fd);return 18;}if(!denied())return 19;'
        f'sleep({target_delay});'
        'fd=open("input-read-marker",O_CREAT|O_WRONLY,0600);if(fd<0)return 20;'
        'if(write(fd,"request+memory-readonly",23)!=23)return 21;return close(fd)==0?0:22;}\n',
        encoding="utf-8",
    )
    compile_native_target(source, prepared.producer / "target")
    prepared.intent = build_producer_launch_intent(
        **{key: value for key, value in prepared.intent.to_dict().items() if key in {
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "contract_sha256",
            "evaluator_kind", "evaluator_fingerprint", "runner_fingerprint", "generator_fingerprint",
            "dependency_sha256", "environment_sha256", "producer_id", "producer_fingerprint",
            "executable_relative", "argv", "working_directory", "output_directory",
            "request_timeout_seconds", "max_requests", "output_max_bytes", "wall_timeout_seconds",
        }}, producer_root=prepared.producer,
    )
    prepared.attestation = build_producer_launch_attestation(prepared.intent, "compiled-input-once")


def test_actual_native_target_reads_exact_request_and_memory_with_no_write_or_directory_bypass(
    tmp_path, native_artifact,
):
    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    input_root = Path(prepared.descriptor.read_paths[0]).parent
    before = _inventory(input_root)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    assert result.target_started and result.gate_released
    assert result.exit_code == 0
    assert (prepared.batch / "work" / "input-read-marker").read_bytes() == b"request+memory-readonly"
    assert _inventory(input_root) == before
    assert _validate(prepared).read_paths == prepared.descriptor.read_paths
    assert not (prepared.batch / "execution-receipt.json").exists()
    assert not list((prepared.batch / "output").glob("*link.json"))
    assert not list((prepared.batch / "output").glob("stolen-*.json"))


def test_native_gate_rechecks_the_original_unix_deadline_after_registration(
    tmp_path, native_artifact, monkeypatch,
):
    from lunar_evolution import native_trusted_attempt as runner

    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    original = runner.publish_trusted_bootstrap_registration

    def jump_wall_clock(*args, **kwargs):
        published = original(*args, **kwargs)
        monkeypatch.setattr(inputs.time, "time", lambda: prepared.descriptor.deadline_unix + 1)
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", jump_wall_clock)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    assert not result.gate_released and not result.target_started
    assert not (prepared.batch / "work" / "input-read-marker").exists()
    assert not (prepared.batch / "execution-receipt.json").exists()
    assert _validate(prepared).deadline_unix == prepared.descriptor.deadline_unix


def test_original_unix_deadline_limits_one_native_attempt_without_renewal(
    tmp_path, native_artifact, monkeypatch,
):
    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared, target_delay=3)
    _bind(prepared)
    original_deadline = prepared.descriptor.deadline_unix
    monkeypatch.setattr(inputs.time, "time", lambda: original_deadline - 2)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    retained_deadline = json.loads((prepared.batch / "native-trusted-attempt-deadline.json").read_bytes())
    assert retained_deadline["deadline_monotonic"] < (
        retained_deadline["started_monotonic"] + prepared.intent.wall_timeout_seconds
    )
    assert result.reason == "native_trusted_attempt_wall_timeout"
    assert not (prepared.batch / "work" / "input-read-marker").exists()
    assert _validate(prepared).deadline_unix == original_deadline
    assert dict(_validate(prepared).request.budget)["deadline_unix"] == original_deadline
    assert not (prepared.batch / "execution-receipt.json").exists()


def test_tighter_caller_deadline_remains_exact_when_inputs_also_pin_a_run_deadline(
    tmp_path, native_artifact,
):
    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared, target_delay=3)
    _bind(prepared)
    caller_deadline = time.monotonic() + 1.5
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact, parent_deadline=caller_deadline,
    )
    retained = json.loads((prepared.batch / "native-trusted-attempt-deadline.json").read_bytes())
    assert retained["deadline_monotonic"] == caller_deadline
    assert result.reason == "native_trusted_attempt_wall_timeout"
    assert not (prepared.batch / "work" / "input-read-marker").exists()
    assert not (prepared.batch / "execution-receipt.json").exists()


@pytest.mark.parametrize("material", ["request", "memory"])
def test_actual_native_admission_refuses_changed_inputs_before_attestation_is_consumed(
    tmp_path, native_artifact, material,
):
    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    path = Path(prepared.descriptor.read_paths[0 if material == "request" else 1])
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((NativeTrustedAttemptError, inputs.NativeRSIInputError)):
        run_native_trusted_attempt(
            prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
    assert not (prepared.batch / "process-registration.json").exists()
    assert not (prepared.batch / "native-trusted-attempt-deadline.json").exists()
    assert not (prepared.batch / "work" / "input-read-marker").exists()
    assert not (prepared.batch / "execution-receipt.json").exists()


def test_native_gate_rechecks_input_bytes_changed_after_original_registration(
    tmp_path, native_artifact, monkeypatch,
):
    from lunar_evolution import native_trusted_attempt as runner

    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    original = runner.publish_trusted_bootstrap_registration
    original_binding = (prepared.batch / "native-rsi-launch.json").read_bytes()

    def mutate_input(*args, **kwargs):
        published = original(*args, **kwargs)
        path = prepared.descriptor.memory_path
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", mutate_input)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    assert not result.gate_released and not result.target_started
    assert not (prepared.batch / "work" / "input-read-marker").exists()
    assert prepared.descriptor.memory_path.read_bytes().endswith(b" ")
    assert (prepared.batch / "native-rsi-launch.json").read_bytes() == original_binding
    assert not (prepared.batch / "execution-receipt.json").exists()


def _executed(tmp_path, native_artifact):
    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    assert result.target_started and result.exit_code == 0
    assert result.terminal_sha256
    return prepared, result


def _forbid_recovery_side_effects(monkeypatch):
    from lunar_evolution import native_trusted_attempt as runner

    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only native recovery must not dispatch, clean up or send a signal")

    monkeypatch.setattr(runner, "run_native_trusted_attempt", forbidden)
    monkeypatch.setattr(runner, "_cleanup", forbidden)
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    monkeypatch.setattr(runner.os, "kill", forbidden)
    monkeypatch.setattr(runner.os, "killpg", forbidden)


@pytest.mark.parametrize("material", ["request", "memory", "manifest", "binding"])
def test_native_recovery_rejects_original_bound_material_drift_without_repair_or_relaunch(
    tmp_path, native_artifact, monkeypatch, material,
):
    prepared, _result = _executed(tmp_path, native_artifact)
    path = {
        "request": prepared.descriptor.request_path,
        "memory": prepared.descriptor.memory_path,
        "manifest": prepared.descriptor.inputs_path / "manifest.json",
        "binding": prepared.batch / "native-rsi-launch.json",
    }[material]
    mode = stat.S_IMODE(path.stat().st_mode)
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b" ")
    path.chmod(mode)
    before = _inventory(prepared.workspace)
    _forbid_recovery_side_effects(monkeypatch)
    with pytest.raises(NativeTrustedAttemptError):
        recover_native_trusted_attempt(
            prepared.workspace, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
    assert _inventory(prepared.workspace) == before


def test_completed_native_recovery_keeps_expired_original_input_deadline_read_only(
    tmp_path, native_artifact, monkeypatch,
):
    prepared, result = _executed(tmp_path, native_artifact)
    terminal = json.loads((prepared.batch / "native-trusted-process-terminal.json").read_bytes())
    assert terminal["terminal_sha256"] == result.terminal_sha256
    before = _inventory(prepared.workspace)
    monkeypatch.setattr(inputs.time, "time", lambda: prepared.descriptor.deadline_unix + 1)
    _forbid_recovery_side_effects(monkeypatch)
    for _ in range(2):
        recovered = recover_native_trusted_attempt(
            prepared.workspace, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
        assert recovered == terminal
        assert recovered["publication_eligible"] is False
        assert _validate(prepared).deadline_unix == prepared.descriptor.deadline_unix
    assert _inventory(prepared.workspace) == before


def test_native_recovery_revalidates_input_bytes_after_reading_original_deadline(
    tmp_path, native_artifact, monkeypatch,
):
    from lunar_evolution import native_trusted_attempt as runner

    prepared, _result = _executed(tmp_path, native_artifact)
    original = runner._read_deadline
    after_change = []

    def interleave(*args, **kwargs):
        deadline = original(*args, **kwargs)
        path = prepared.descriptor.request_path
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
        after_change.append(_inventory(prepared.workspace))
        return deadline

    monkeypatch.setattr(runner, "_read_deadline", interleave)
    _forbid_recovery_side_effects(monkeypatch)
    with pytest.raises(NativeTrustedAttemptError):
        recover_native_trusted_attempt(
            prepared.workspace, intent=prepared.intent,
            attestation=prepared.attestation, artifact=prepared.artifact,
        )
    assert len(after_change) == 1
    assert _inventory(prepared.workspace) == after_change[0]


def _replace_same_bytes_and_mode(path: Path, replacement: Path) -> None:
    original = path.stat()
    content = path.read_bytes()
    mode = stat.S_IMODE(original.st_mode)
    replacement.write_bytes(content)
    replacement.chmod(mode)
    assert (replacement.stat().st_dev, replacement.stat().st_ino) != (original.st_dev, original.st_ino)
    replacement.replace(path)
    assert path.read_bytes() == content
    assert stat.S_IMODE(path.stat().st_mode) == mode
    assert (path.stat().st_dev, path.stat().st_ino) != (original.st_dev, original.st_ino)


def _forbid_input_validation_mutations(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("input validation must not write, stage, bind or obtain a recovery lock")

    for name in ("_recovery_lock", "_write_file", "_write_open_file", "_open_new_file",
                 "_write_self_bound_file", "prepare_native_rsi_inputs", "bind_native_rsi_launch"):
        monkeypatch.setattr(inputs, name, forbidden)
    _forbid_recovery_side_effects(monkeypatch)


def test_binding_named_inode_replaced_before_held_fd_read_is_refused_without_repair(
    tmp_path, native_artifact, monkeypatch,
):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    path = prepared.batch / "native-rsi-launch.json"
    original_info = path.stat()
    identity = original_info.st_dev, original_info.st_ino
    read = inputs.os.read
    replacements = []

    def interleaved_read(descriptor, size):
        info = inputs.os.fstat(descriptor)
        if not replacements and (info.st_dev, info.st_ino) == identity:
            _replace_same_bytes_and_mode(path, tmp_path / "replacement-binding.json")
            replacements.append(_inventory(prepared.workspace))
        return read(descriptor, size)

    monkeypatch.setattr(inputs.os, "read", interleaved_read)
    _forbid_input_validation_mutations(monkeypatch)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert len(replacements) == 1
    assert _inventory(prepared.workspace) == replacements[0]


@pytest.mark.parametrize("replacement_stage", ["after_binding_read", "during_final_input_read"])
def test_binding_inode_replaced_during_validation_is_refused_by_the_final_reread(
    tmp_path, native_artifact, monkeypatch, replacement_stage,
):
    prepared = _prepared(tmp_path, native_artifact)
    _bind(prepared)
    path = prepared.batch / "native-rsi-launch.json"
    replacements = []

    def replace_binding():
        _replace_same_bytes_and_mode(path, tmp_path / "replacement-binding.json")
        replacements.append(_inventory(prepared.workspace))

    if replacement_stage == "after_binding_read":
        read_binding = inputs._read_bound_file

        def interleaved_binding_read(current):
            result = read_binding(current)
            if current == path and not replacements:
                replace_binding()
            return result

        monkeypatch.setattr(inputs, "_read_bound_file", interleaved_binding_read)
    else:
        read_inputs = inputs._read_inputs
        reads = []

        def interleaved_input_read(*args, **kwargs):
            result = read_inputs(*args, **kwargs)
            reads.append(result)
            if len(reads) == 2:
                replace_binding()
            return result

        monkeypatch.setattr(inputs, "_read_inputs", interleaved_input_read)
    _forbid_input_validation_mutations(monkeypatch)
    with pytest.raises(inputs.NativeRSIInputError):
        _validate(prepared)
    assert len(replacements) == 1
    assert _inventory(prepared.workspace) == replacements[0]


def test_native_terminal_projection_refuses_input_drift_after_stream_observation(
    tmp_path, native_artifact, monkeypatch,
):
    from lunar_evolution import native_trusted_attempt as runner

    prepared = _prepared(tmp_path, native_artifact)
    _real_target(prepared)
    _bind(prepared)
    persist_stream = runner.persist_native_trusted_stream_capture
    observations = []

    def interleaved_stream(*args, **kwargs):
        result = persist_stream(*args, **kwargs)
        path = prepared.descriptor.memory_path
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        path.chmod(0o400)
        observations.append(result)
        return result

    monkeypatch.setattr(runner, "persist_native_trusted_stream_capture", interleaved_stream)
    result = run_native_trusted_attempt(
        prepared.workspace, producer_root=prepared.producer, intent=prepared.intent,
        attestation=prepared.attestation, artifact=prepared.artifact,
    )
    assert len(observations) == 1
    assert result.gate_released and result.target_started and result.exit_code == 0
    assert result.reason.startswith("rsi_native_inputs_")
    assert result.status == "recovery_required"
    assert result.terminal_sha256 is None and result.output_capture_sha256 is None
    assert not (prepared.batch / "native-trusted-process-terminal.json").exists()
    assert not (prepared.batch / "execution-receipt.json").exists()
    assert prepared.descriptor.memory_path.read_bytes().endswith(b" ")
