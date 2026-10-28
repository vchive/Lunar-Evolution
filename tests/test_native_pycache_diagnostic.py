"""Finite configuration checks and real inert native-attempt diagnostics.

Linux cases compile a static C fixture and run the original bootstrap/grants/
guardian path. No CPython, solver, evaluator or accepted runtime is exercised.
"""

from __future__ import annotations

import hashlib
import json
import sys

import pytest
from _native_target_fixture import compile_native_target

from lunar_evolution import native_pycache_diagnostic as diagnostic
from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.static_python_pycache_grants import GrantBoundPycacheMonitor


@pytest.mark.parametrize("changes", (
    {"observer": None}, {"diagnostic_profile": None}, {"diagnostic_profile": "enabled"},
    {"working_directories": ["."]}, {"working_directories": ("child",)},
    {"working_directories": (".", "../escape")},
    {"output_directories": (".", "missing/child")},
    {"output_directories": (".", ".")}, {"output_directories": (".", 1)},
))
def test_invalid_configuration_is_not_original_evidence(changes):
    options = {"observer": lambda *_args: None, **changes}
    request = diagnostic.NativePycacheDiagnosticRequest(**options)
    with pytest.raises(diagnostic.NativePycacheDiagnosticError):
        request.validate()


def test_explicit_configuration_contains_layout_only():
    observer = lambda *_args: None
    request = diagnostic.NativePycacheDiagnosticRequest(
        observer, working_directories=(".", "precreated", "precreated/nested"),
    )
    request.validate()
    assert request.observer is observer
    assert not hasattr(request, "original_grants_sha256")
    assert not hasattr(request, "quiescence")


def test_default_none_scope_does_not_acquire_grants_or_monitor():
    with diagnostic.original_native_pycache_diagnostic_scope(
        None, held_grants=None, working=None, output=None, deadline_ns=0,
    ) as scope:
        assert scope is None


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="actual native Linux diagnostics")


def _attempt(tmp_path, *, cache=True, delay=0, target_exit=0, timeout=8):
    workspace, producer_root = tmp_path / "workspace", tmp_path / "producer"
    workspace.mkdir()
    producer_root.mkdir()
    batch = workspace / "evolution" / "producer-batches" / "journal-001"
    work, output = batch / "work", batch / "output"
    candidate = b"candidate = 1\n"
    envelope = {"schema_version": "1", "producer_id": "fixture", "producer_fingerprint": "a" * 64,
                "status": "completed", "contract_sha256": "a" * 64, "budget": {"requests": 0},
                "materials": [{"kind": "candidate_source", "path": "candidate.py",
                               "size": len(candidate), "sha256": hashlib.sha256(candidate).hexdigest()}]}
    envelope_text = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    cache_path = json.dumps(str(work / "transient.pyc.314"))
    cache_code = (f'if(put({cache_path},"cache"))return 3; '
                  f'if(unlink({cache_path}))return 4; ') if cache else ""
    source, target = producer_root / "target.c", producer_root / "target"
    source.write_text(
        '#include <fcntl.h>\n#include <string.h>\n#include <unistd.h>\n'
        'static int put(const char*p,const char*s){int f=open(p,O_CREAT|O_WRONLY,0600); '
        'if(f<0)return 1; size_t n=strlen(s); if(write(f,s,n)!=(ssize_t)n){close(f);return 2;} '
        'return close(f);}\nint main(void){'
        f'if(put({json.dumps(str(work / "target.marker"))},"started"))return 2; '
        f'{cache_code}'
        f'if(put({json.dumps(str(output / "candidate.py"))},{json.dumps(candidate.decode())}))return 5; '
        f'if(put({json.dumps(str(output / "producer-result.json"))},{json.dumps(envelope_text)}))return 6; '
        f'sleep({delay}); return {target_exit};}}\n', encoding="utf-8",
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
        executable_relative="target", argv=("target",), working_directory="work",
        output_directory="output", request_timeout_seconds=1, max_requests=1,
        output_max_bytes=4096, wall_timeout_seconds=timeout,
    )
    return workspace, producer_root, intent, build_producer_launch_attestation(intent, "nonce-001"), artifact, batch


def _run(fixture, **options):
    workspace, producer_root, intent, attestation, artifact, _batch = fixture
    return runner.run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, **options,
    )


def _retain_real_acquisitions(monkeypatch, batch):
    original = GrantBoundPycacheMonitor.arm_before_target
    captures, deadlines = [], []

    def arm(**options):
        assert not (batch / "work" / "target.marker").exists()
        capture = original(**options)
        captures.append(capture)
        deadlines.append(options["deadline_monotonic_ns"])
        return capture

    monkeypatch.setattr(GrantBoundPycacheMonitor, "arm_before_target", arm)
    return captures, deadlines


@linux_only
@pytest.mark.parametrize("cache", (True, False))
def test_original_native_gate_grants_events_cleanup_and_delivery(tmp_path, monkeypatch, cache):
    fixture = _attempt(tmp_path, cache=cache)
    batch = fixture[-1]
    captures, deadlines = _retain_real_acquisitions(monkeypatch, batch)
    original_publish = runner.publish_trusted_bootstrap_registration
    publications = []
    delivered = []

    def publish(*args, **options):
        assert options.get("retain_creation_identity") is True
        published = original_publish(*args, **options)
        assert published.registration_file_identity is not None
        assert published.handoff_file_identity is not None
        publications.append(published)
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", publish)

    def observer(context, observed):
        assert context.run_id == "run-001" and context.journal_id == "journal-001"
        assert json.loads(context.registration_json)["registration_sha256"]
        assert context.registration_file_identity == publications[0].registration_file_identity
        assert context.handoff_file_identity == publications[0].handoff_file_identity
        assert (batch / "native-trusted-process-terminal.json").is_file()
        assert captures[0]._original_capture._closed
        assert not captures[0]._owner._closed
        assert observed.original_grants_authenticated
        assert not any((observed.original_quiescence_observed, observed.writer_enclosure_verified,
                        observed.coverage_complete, observed.strict_view_accepted, observed.production_admission))
        assert "original_quiescence_unavailable" in observed.failures
        assert ("python_cache_observed" in observed.failures) is cache
        assert any(item.event.name == b"transient.pyc.314" for item in observed.events) is cache
        delivered.append((context, observed))

    result = _run(fixture, pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(observer))
    assert result.reason == "native_trusted_attempt_request_and_output_unverified"
    assert result.gate_released and result.target_started and result.exit_code == 0
    assert len(publications) == len(captures) == len(delivered) == 1
    assert captures[0]._owner._closed and captures[0]._original_capture._closed
    assert captures[0]._original_capture._deadline == deadlines[0]
    assert {item.path for item in delivered[0][1].directories} == {
        str(batch / "work"), str(batch / "output"),
    }


@linux_only
def test_default_none_native_attempt_does_not_arm(tmp_path, monkeypatch):
    fixture = _attempt(tmp_path)
    monkeypatch.setattr(GrantBoundPycacheMonitor, "arm_before_target",
                        lambda **_options: pytest.fail("default native attempt must not monitor"))
    result = _run(fixture)
    assert result.reason == "native_trusted_attempt_request_and_output_unverified"


@linux_only
def test_original_pre_gate_cache_contamination_never_releases_target(tmp_path):
    fixture = _attempt(tmp_path)
    batch = fixture[-1]
    delivered = []

    def contaminate(_context):
        (batch / "work" / "existing.pyc").write_bytes(b"original contamination")

    result = _run(
        fixture, registered_observer=contaminate,
        pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(lambda *_args: delivered.append(True)),
    )
    assert result.reason == "native_trusted_attempt_pycache_diagnostic_arm_failed"
    assert not result.gate_released and not result.target_started
    assert not (batch / "work" / "target.marker").exists()
    assert delivered == []


@linux_only
@pytest.mark.parametrize("fault", ("exit", "cancel", "timeout"))
def test_native_failure_cleanup_precedes_reader_release_and_keeps_primary(tmp_path, monkeypatch, fault):
    fixture = _attempt(tmp_path, delay=30 if fault in {"cancel", "timeout"} else 0,
                       target_exit=7 if fault == "exit" else 0, timeout=1 if fault == "timeout" else 8)
    batch = fixture[-1]
    captures, _deadlines = _retain_real_acquisitions(monkeypatch, batch)
    original_cleanup = runner._cleanup
    order = []

    def cleanup(*args, **options):
        assert captures and not captures[0]._original_capture._closed
        order.append("native_cleanup")
        return original_cleanup(*args, **options)

    monkeypatch.setattr(runner, "_cleanup", cleanup)
    options = ({"cancelled": lambda: (batch / "work" / "target.marker").exists()}
               if fault == "cancel" else {})
    delivered = []
    result = _run(fixture, pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(
        lambda *_args: delivered.append(True),
    ), **options)
    assert "pycache_diagnostic" not in result.reason
    assert result.reason != "native_trusted_attempt_request_and_output_unverified"
    assert order and delivered == []
    assert captures[0]._original_capture._closed


@linux_only
@pytest.mark.parametrize("failure", ("exception", "return_value", "diagnostic_mutation"))
def test_diagnostic_observer_cannot_change_native_or_accept_coverage(tmp_path, monkeypatch, failure):
    fixture = _attempt(tmp_path)
    captures, _deadlines = _retain_real_acquisitions(monkeypatch, fixture[-1])

    def observer(_context, observed):
        assert captures[0]._original_capture._closed
        if failure == "exception":
            raise RuntimeError("inert diagnostic sink failure")
        if failure == "return_value":
            return True
        object.__setattr__(observed, "coverage_complete", True)
        return None

    with pytest.raises(runner.NativeTrustedAttemptError, match="pycache_diagnostic_unknown"):
        _run(fixture, pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(observer))
    assert captures[0]._original_capture._closed
    terminal = json.loads((fixture[-1] / "native-trusted-process-terminal.json").read_bytes())
    assert terminal["exit_code"] == 0 and terminal["publication_eligible"] is False


@linux_only
@pytest.mark.parametrize("finish_fault", (None, "before_release", "after_release"))
def test_original_base_exception_survives_native_cleanup_and_monitor_finish(tmp_path, monkeypatch, finish_fault):
    fixture = _attempt(tmp_path, delay=30)
    captures, _deadlines = _retain_real_acquisitions(monkeypatch, fixture[-1])
    original_read = runner._read_attempt_frame
    original_finish = GrantBoundPycacheMonitor.finish
    primary = MemoryError("inert original native failure")
    delivered = []

    def read_then_interrupt(*args, **options):
        frame = original_read(*args, **options)
        if frame.kind == "target_started":
            raise primary
        return frame

    def finish_then_fail(self):
        if finish_fault == "after_release":
            original_finish(self)
        else:
            assert not self._original_capture._closed
        raise OSError("inert finish failure")

    monkeypatch.setattr(runner, "_read_attempt_frame", read_then_interrupt)
    if finish_fault:
        monkeypatch.setattr(GrantBoundPycacheMonitor, "finish", finish_then_fail)
    with pytest.raises(MemoryError) as caught:
        _run(fixture, pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(
            lambda *_args: delivered.append(True),
        ))
    assert caught.value is primary
    assert captures and captures[0]._original_capture._closed
    assert delivered == []
    assert (fixture[-1] / "native-trusted-cleanup.json").is_file()
    if finish_fault:
        assert "native_pycache_diagnostic_cleanup_or_delivery_unknown" in primary.__notes__


@linux_only
def test_normal_native_finish_failure_releases_original_reader_and_raises_fixed_error(tmp_path, monkeypatch):
    fixture = _attempt(tmp_path)
    captures, _deadlines = _retain_real_acquisitions(monkeypatch, fixture[-1])
    finish_error = OSError("inert supplied path must remain in cause only")
    delivered = []

    def fail_before_release(self):
        assert not self._original_capture._closed
        raise finish_error

    monkeypatch.setattr(GrantBoundPycacheMonitor, "finish", fail_before_release)
    with pytest.raises(runner.NativeTrustedAttemptError, match="^native_trusted_attempt_pycache_diagnostic_unknown$") as caught:
        _run(fixture, pycache_diagnostic=diagnostic.NativePycacheDiagnosticRequest(
            lambda *_args: delivered.append(True),
        ))
    assert isinstance(caught.value.__cause__, diagnostic.NativePycacheDiagnosticError)
    assert caught.value.__cause__.__cause__ is finish_error
    assert captures and captures[0]._original_capture._closed
    assert not captures[0]._original_capture._owned_directory_fds
    assert delivered == []
    terminal = json.loads((fixture[-1] / "native-trusted-process-terminal.json").read_bytes())
    assert terminal["exit_code"] == 0 and terminal["publication_eligible"] is False
