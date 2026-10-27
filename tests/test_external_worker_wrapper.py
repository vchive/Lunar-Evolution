"""Preinstalled wrapper state/real process fixtures, with no remote worker."""

import hashlib
import os
import subprocess

import pytest
from external_worker_fixtures import (
    PROFILE,
    RECEIPT,
    SECRET,
    invocation,
    lines,
    worker_harness,
    write_private,
)

from lunar_evolution.external_worker_origin import WorkerOriginContext, verify_worker_origin
from lunar_evolution.external_worker_wrapper import (
    WorkerWrapperError,
    handle_worker_request,
    load_worker_wrapper_config,
    parse_worker_response,
    worker_json,
)


def test_real_wrapper_producer_exact_receipt_and_existing_run_never_restarts(tmp_path):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    request = invocation(h)
    raw = worker_json(request)
    result = handle_worker_request(raw, config)
    status, origin, receipt = parse_worker_response(result)
    assert status == "receipt" and receipt == RECEIPT
    verified = verify_worker_origin(origin, registry=h.book.registry,
        expected_context=WorkerOriginContext.from_dict(h.assignment["context"]),
        expected_profile_sha256=PROFILE, receipt=receipt)
    assert verified.worker_id == "worker-local"
    assert handle_worker_request(raw, config) == result
    assert handle_worker_request(worker_json({**request, "action": "inspect"}), config) == result
    assert len(lines(h.marker)) == 1
    assert SECRET.decode() not in repr(config) + repr(lines(h.marker)) + result.decode()


def test_actual_competing_wrapper_processes_start_only_one_producer(tmp_path):
    h = worker_harness(tmp_path)
    raw = worker_json(invocation(h))
    children = [subprocess.Popen(h.wrapper_argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE) for _ in range(2)]
    try:
        for child in children:
            child.stdin.write(raw)
            child.stdin.close()
            child.stdin = None
        outputs = [child.communicate(timeout=20) for child in children]
        statuses = [parse_worker_response(output)[0] for output, _error in outputs]
        assert "receipt" in statuses
        assert set(statuses) <= {"receipt", "unknown"}
        assert len(lines(h.marker)) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_interrupted_remote_intent_and_foreign_intent_never_admit_producer(tmp_path):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    request = invocation(h)
    job = h.state / hashlib.sha256(h.request.episode_id.encode()).hexdigest()
    job.mkdir(mode=0o700)
    assert parse_worker_response(handle_worker_request(worker_json(request), config))[0] == "unknown"
    intent = {name: item for name, item in request.items() if name != "action"}
    write_private(job / "intent.json", worker_json(intent))
    assert parse_worker_response(handle_worker_request(worker_json(request), config))[0] == "unknown"
    assert parse_worker_response(handle_worker_request(worker_json({**request, "action": "inspect"}), config))[0] == "unknown"
    with pytest.raises(WorkerWrapperError, match="intent_drift"):
        handle_worker_request(worker_json({**request, "deadline_unix": request["deadline_unix"] + 1}), config)
    assert not h.marker.exists()


@pytest.mark.parametrize("field,value", [("host_id", "other"), ("profile_sha256", "f" * 64)])
def test_identity_profile_drift_rejected_before_intent(tmp_path, field, value):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    with pytest.raises(WorkerWrapperError, match="identity_mismatch"):
        handle_worker_request(worker_json({**invocation(h), field: value}), config)
    assert list(h.state.iterdir()) == [] and not h.marker.exists()


def test_private_config_key_and_ancestor_symlinks_are_refused_without_path_disclosure(tmp_path):
    h = worker_harness(tmp_path)
    h.key_file.chmod(0o644)
    with pytest.raises(WorkerWrapperError, match="private_file_invalid") as caught:
        load_worker_wrapper_config(h.config_file)
    assert str(h.key_file) not in str(caught.value)
    h.key_file.chmod(0o600)
    link = h.root / "key-link"
    link.symlink_to(h.key_file)
    write_private(h.config_file, worker_json({**h.config_value, "key_file": str(link)}))
    with pytest.raises(WorkerWrapperError, match="private_file_invalid"):
        load_worker_wrapper_config(h.config_file)
    write_private(h.config_file, worker_json(h.config_value))
    ancestor = h.root / "ancestor"
    ancestor.symlink_to(h.root, target_is_directory=True)
    with pytest.raises(WorkerWrapperError, match="private_file_invalid"):
        load_worker_wrapper_config(ancestor / h.config_file.name)


def test_private_reads_handle_short_reads_and_reject_inplace_mutation(tmp_path, monkeypatch):
    from lunar_evolution import external_worker_wrapper as module

    h = worker_harness(tmp_path)
    original = os.read

    def short(fd, count):
        return original(fd, min(count, 3))

    monkeypatch.setattr(module.os, "read", short)
    assert load_worker_wrapper_config(h.config_file).key.secret_key == SECRET
    changed = False

    def mutate(fd, count):
        nonlocal changed
        result = original(fd, count)
        if not changed:
            changed = True
            h.config_file.write_bytes(h.config_file.read_bytes() + b" ")
        return result

    monkeypatch.setattr(module.os, "read", mutate)
    with pytest.raises(WorkerWrapperError, match="private_file_invalid"):
        load_worker_wrapper_config(h.config_file)


@pytest.mark.parametrize("code", ["import sys;sys.exit(8)", "print('x'*140000)", "import sys;sys.stderr.write('x'*5000)"])
def test_nonzero_or_unbounded_producer_never_seals_a_signed_receipt(tmp_path, code):
    h = worker_harness(tmp_path, producer_code=code)
    config = load_worker_wrapper_config(h.config_file)
    request = invocation(h)
    try:
        raw = handle_worker_request(worker_json(request), config)
    except ValueError:
        raw = None
    if raw is not None:
        assert parse_worker_response(raw)[0] == "unknown"
    job = next(h.state.iterdir())
    assert (job / "intent.json").is_file() and not (job / "response.json").exists()
    assert parse_worker_response(handle_worker_request(worker_json(request), config))[0] == "unknown"


def test_expired_original_deadline_does_not_start_producer(tmp_path):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    request = {**invocation(h), "deadline_unix": 1.0}
    assert parse_worker_response(handle_worker_request(worker_json(request), config))[0] == "unknown"
    assert not h.marker.exists()
    assert parse_worker_response(handle_worker_request(worker_json(request), config))[0] == "unknown"


def test_public_request_cannot_supply_argv_environment_or_key(tmp_path):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    for name in ("producer_argv", "key", "environment"):
        with pytest.raises(WorkerWrapperError, match="request_fields_invalid"):
            handle_worker_request(worker_json({**invocation(h), name: "untrusted"}), config)
    assert list(h.state.iterdir()) == []


def test_missing_read_only_remote_inspect_creates_no_intent_or_producer(tmp_path):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    response = handle_worker_request(worker_json(invocation(h, action="inspect")), config)
    assert parse_worker_response(response)[0] == "missing"
    assert list(h.state.iterdir()) == [] and not h.marker.exists()


@pytest.mark.parametrize("field", ["timeout_seconds", "deadline_unix"])
def test_wrapper_independently_refuses_wire_budget_above_original_request(tmp_path, field):
    h = worker_harness(tmp_path)
    config = load_worker_wrapper_config(h.config_file)
    raw = invocation(h)
    limits = dict(h.request.budget)
    raw[field] = limits["wall_timeout_seconds" if field == "timeout_seconds" else "deadline_unix"] + 1
    with pytest.raises(WorkerWrapperError, match="budget_invalid"):
        handle_worker_request(worker_json(raw), config)
    assert list(h.state.iterdir()) == [] and not h.marker.exists()


def test_expired_original_request_is_still_inspectable_without_launch(tmp_path):
    h = worker_harness(tmp_path, budget={"wall_timeout_seconds": 10, "deadline_unix": 1.0})
    config = load_worker_wrapper_config(h.config_file)
    assert parse_worker_response(handle_worker_request(worker_json(invocation(h, action="inspect")), config))[0] == "missing"
    assert list(h.state.iterdir()) == [] and not h.marker.exists()


def test_existing_fifo_is_rejected_before_wrapper_leaf_open(tmp_path, monkeypatch):
    from lunar_evolution import external_worker_wrapper as module

    fifo = tmp_path / "private-key.fifo"
    os.mkfifo(fifo, 0o600)
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = os.open

    def checked_open(path, flags, *args, **kwargs):
        if path == fifo.name and kwargs.get("dir_fd") == directory:
            pytest.fail("an existing nonregular leaf must not reach open")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked_open)
    try:
        with pytest.raises(WorkerWrapperError, match="state_file_invalid"):
            module._read_at(directory, fifo.name, 4096)
    finally:
        os.close(directory)


def test_wrapper_regular_to_fifo_race_opens_nonblocking_and_refuses(tmp_path, monkeypatch):
    from lunar_evolution import external_worker_wrapper as module

    leaf = tmp_path / "private-key"
    write_private(leaf, b"inert original bytes")
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = os.open
    seen = []

    def replace_before_open(path, flags, *args, **kwargs):
        if path == leaf.name and kwargs.get("dir_fd") == directory:
            # Assert before the real FIFO open, so a regression cannot hang pytest.
            assert flags & os.O_NONBLOCK
            assert flags & os.O_NOFOLLOW
            seen.append(True)
            leaf.unlink()
            os.mkfifo(leaf, 0o600)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    try:
        with pytest.raises(WorkerWrapperError, match="state_file_invalid"):
            module._read_at(directory, leaf.name, 4096)
        assert seen == [True]
    finally:
        os.close(directory)
