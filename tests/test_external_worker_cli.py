"""Explicit commands join real local claim/HMAC journals without any SSH launch."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess

import pytest
from test_external_worker_assignment import _PLAN, _PROFILE, _SECRET, _setup

from lunar_evolution import cli
from lunar_evolution import external_worker_cli as worker_cli
from lunar_evolution.external_worker_origin import WorkerOriginContext, sign_worker_origin
from lunar_evolution.external_worker_wrapper import worker_json
from lunar_evolution.rsi_store import RSILedger


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("CLI fixture must not execute SSH, a model, or a producer")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(cli, "_config", forbidden)


def _json(path, value):
    path.write_bytes(worker_json(value))
    path.chmod(0o600)
    return path.resolve()


def _files(root):
    root = root.resolve()
    key = root / "worker.key"
    key.write_bytes(_SECRET)
    key.chmod(0o600)
    registry = _json(root / "registry.json", {
        "schema_version": "lunar-external-worker-registry-v1", "workers": [{
            "worker_id": "worker-1", "host_id": "host-1", "host_boot_id": "boot-1",
            "key_id": "key-1", "key_file": str(key), "revoked": False,
        }],
    })
    config = _json(root / "ssh.json", {
        "schema_version": "lunar-external-worker-ssh-v1", "ssh_executable": "/usr/bin/ssh",
        "host": "5090gpu", "remote_argv": [
            "/usr/bin/python3", "-m", "lunar_evolution.external_worker_wrapper",
            "--config", "/srv/lunar/private-wrapper.json",
        ], "worker_id": "worker-1",
    })
    return key, registry, config


def _arguments(h, tmp_path, action):
    _key, registry, config = _files(tmp_path)
    request = _json(tmp_path / "request.json", h.request.to_dict())
    arguments = [
        "external-worker", action, "--ledger", str(h.store.database),
        "--registry", str(registry), "--ssh-config", str(config),
        "--controller-id", "controller-1", "--run-id", "run-1", "--task-id", "task-1", "--json",
    ]
    if action == "inspect":
        return arguments + ["--episode-id", h.request.episode_id]
    arguments += [
        "--request", str(request), "--request-sha256", hashlib.sha256(request.read_bytes()).hexdigest(),
        "--plan-sha256", _PLAN, "--checkpoint-sha256", h.original_checkpoint,
    ]
    if action == "reserve":
        arguments += ["--claim-sha256", h.claim.claim_sha256, "--profile-sha256", _PROFILE]
    return arguments


def test_reserve_and_inspect_use_existing_claim_without_native_publication(tmp_path, capsys):
    h = _setup(tmp_path)
    assert cli.main(_arguments(h, tmp_path, "reserve")) == 0
    reserved = json.loads(capsys.readouterr().out)
    assert reserved["status"] == "assigned"
    original = h.book.inspect(h.request.episode_id)
    assert cli.main(_arguments(h, tmp_path, "inspect")) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert reserved == inspected
    assert h.book.inspect(h.request.episode_id) == original
    assert h.store.episode_result(h.request.episode_id) is None
    assert h.store.inspect_native_episode_claim(h.request, plan_sha256=_PLAN) == h.claim
    assert all(inspected[name] is False for name in (
        "production_admission", "online_publication", "native_result_published", "remote_cleanup_verified",
    ))
    visible = json.dumps(inspected)
    assert _SECRET.decode() not in visible
    assert "controller_challenge" not in visible
    assert str(tmp_path) not in visible


def test_dispatch_uses_original_lock_and_real_once_only_hmac_consumption(tmp_path, monkeypatch, capsys):
    from lunar_evolution.external_worker_transport import SSHWorkerTransport

    h = _setup(tmp_path)
    assert cli.main(_arguments(h, tmp_path, "reserve")) == 0
    capsys.readouterr()
    seen = []

    def dispatch(self, request, *, plan_sha256, expected_controller_checkpoint_sha256, control):
        assert self.assignments.ledger.controller_lock_held("run-1")
        assert request == h.request and plan_sha256 == _PLAN
        assert expected_controller_checkpoint_sha256 == h.original_checkpoint
        assert 0 < control.remaining() <= 30
        assignment = self.assignments.inspect(request.episode_id)
        context = WorkerOriginContext.from_dict(assignment["context"])
        receipt = b"original inert worker receipt"
        raw = sign_worker_origin(key=h.key, context=context, profile_sha256=_PROFILE, receipt=receipt)
        self.assignments.record_origin_receipt(
            request, plan_sha256=plan_sha256,
            expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
            raw=raw, receipt=receipt,
        )
        seen.append(True)
        return {"status": "receipt_authenticated", "assignment": self.assignments.inspect(request.episode_id)}

    monkeypatch.setattr(SSHWorkerTransport, "dispatch", dispatch)
    assert cli.main(_arguments(h, tmp_path, "dispatch")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "receipt_authenticated" and seen == [True]
    assert h.store.episode_result(h.request.episode_id) is None
    assert h.store.inspect_native_episode_claim(h.request, plan_sha256=_PLAN) == h.claim


def test_unknown_reconcile_is_explicit_and_uses_inspection_operation(tmp_path, monkeypatch, capsys):
    from lunar_evolution.external_worker_transport import SSHWorkerTransport

    h = _setup(tmp_path)
    assert cli.main(_arguments(h, tmp_path, "reserve")) == 0
    capsys.readouterr()
    with h.store.controller_lock("run-1"):
        h.book.mark_unknown(h.request, plan_sha256=_PLAN,
            expected_controller_checkpoint_sha256=h.original_checkpoint, reason_code="disconnected")
    seen = []

    def reconcile(self, request, **_kwargs):
        assert self.assignments.ledger.controller_lock_held("run-1")
        seen.append(request.episode_id)
        return {"status": "unknown", "assignment": self.assignments.inspect(request.episode_id)}

    monkeypatch.setattr(SSHWorkerTransport, "reconcile", reconcile)
    assert cli.main(_arguments(h, tmp_path, "reconcile")) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unknown"
    assert seen == [h.request.episode_id]
    assert h.book.inspect(h.request.episode_id)["status"] == "unknown"


@pytest.mark.parametrize("field", ["--request-sha256", "--claim-sha256", "--checkpoint-sha256"])
def test_drift_refuses_without_assignment_or_native_result(tmp_path, capsys, field):
    h = _setup(tmp_path)
    args = _arguments(h, tmp_path, "reserve")
    args[args.index(field) + 1] = "f" * 64
    assert cli.main(args) == 2
    assert "error" in json.loads(capsys.readouterr().err)
    assert h.book.inspect(h.request.episode_id) is None
    assert h.store.episode_result(h.request.episode_id) is None


def test_missing_ledger_refuses_instead_of_creating_it(tmp_path, capsys):
    h = _setup(tmp_path)
    args = _arguments(h, tmp_path, "inspect")
    path = tmp_path.resolve() / "missing.sqlite3"
    args[args.index("--ledger") + 1] = str(path)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "worker_cli_ledger_missing"}
    assert not path.exists()


@pytest.mark.parametrize("change", ["symlink", "hardlink", "parent_symlink"])
def test_ledger_aliases_refuse_before_assignment(tmp_path, capsys, change):
    h = _setup(tmp_path)
    args = _arguments(h, tmp_path, "reserve")
    database = h.store.database
    if change == "symlink":
        alias = database.with_suffix(".alias")
        alias.symlink_to(database)
    elif change == "hardlink":
        alias = database.with_suffix(".alias")
        os.link(database, alias)
    else:
        directory = tmp_path.resolve() / "ledger-alias"
        directory.symlink_to(database.parent, target_is_directory=True)
        alias = directory / database.name
    args[args.index("--ledger") + 1] = str(alias)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "worker_cli_ledger_invalid"}
    assert h.book.inspect(h.request.episode_id) is None


def test_malformed_ledger_returns_fixed_json_error(tmp_path, capsys):
    h = _setup(tmp_path)
    args = _arguments(h, tmp_path, "inspect")
    malformed = tmp_path.resolve() / "malformed.sqlite3"
    malformed.write_bytes(b"private non-SQLite bytes")
    args[args.index("--ledger") + 1] = str(malformed)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "worker_cli_ledger_invalid"}
    assert malformed.read_bytes() == b"private non-SQLite bytes"


def test_removed_ledger_is_not_recreated_during_constructor_connection(tmp_path, monkeypatch, capsys):
    h = _setup(tmp_path)
    args = _arguments(h, tmp_path, "inspect")
    original_connect = sqlite3.connect
    calls = []

    def connect(path, *positional, **kwargs):
        calls.append(str(path))
        if len(calls) == 1:
            h.store.database.unlink()
        return original_connect(path, *positional, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "worker_cli_ledger_invalid"}
    assert calls == [h.store.database.as_uri() + "?mode=rw"]
    assert not h.store.database.exists()


def test_existing_only_ledger_connections_never_recreate_a_removed_database(tmp_path):
    path = tmp_path / "existing.sqlite3"
    RSILedger(path)
    ledger = RSILedger(path, create=False)
    path.unlink()
    with pytest.raises(sqlite3.OperationalError):
        ledger.controller_checkpoint("original-run")
    assert not path.exists()


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o666])
@pytest.mark.parametrize("file", ["key", "registry"])
def test_private_registry_and_key_permissions_refuse(tmp_path, file, mode):
    key, registry, _ = _files(tmp_path)
    (key if file == "key" else registry).chmod(mode)
    with pytest.raises(ValueError, match="worker_cli_file_invalid"):
        worker_cli.load_worker_registry(registry)


@pytest.mark.parametrize("change", ["symlink", "hardlink", "parent_symlink"])
def test_key_aliases_refuse_without_disclosing_path_or_key(tmp_path, change):
    key, registry, _ = _files(tmp_path)
    if change == "symlink":
        original = key.with_suffix(".original")
        key.rename(original)
        key.symlink_to(original)
    elif change == "hardlink":
        os.link(key, key.with_suffix(".other"))
    else:
        directory = tmp_path / "alias"
        directory.symlink_to(tmp_path, target_is_directory=True)
        payload = json.loads(registry.read_bytes())
        payload["workers"][0]["key_file"] = str(directory / key.name)
        registry = _json(registry, payload)
    with pytest.raises(ValueError) as failure:
        worker_cli.load_worker_registry(registry)
    assert _SECRET.decode() not in str(failure.value)
    assert str(tmp_path) not in str(failure.value)


def test_private_reader_completes_short_reads_and_rechecks_metadata(tmp_path, monkeypatch):
    key, registry, _ = _files(tmp_path)
    original = os.read
    monkeypatch.setattr(os, "read", lambda fd, count: original(fd, min(count, 7)))
    _registry, keys = worker_cli.load_worker_registry(registry)
    assert keys["worker-1"].secret_key == key.read_bytes()


def test_duplicate_registry_keys_and_inline_secrets_are_refused(tmp_path):
    _key, registry, _ = _files(tmp_path)
    raw = registry.read_bytes()
    registry.write_bytes(raw[:-1] + b',"workers":[]}')
    with pytest.raises(ValueError):
        worker_cli.load_worker_registry(registry)
    payload = json.loads(raw)
    payload["workers"][0]["secret_key"] = _SECRET.decode()
    _json(registry, payload)
    with pytest.raises(ValueError, match="registry_invalid"):
        worker_cli.load_worker_registry(registry)


@pytest.mark.parametrize("operation", ["read", "ledger"])
def test_existing_fifo_is_rejected_before_cli_leaf_open(tmp_path, monkeypatch, operation):
    leaf = tmp_path.resolve() / "original.fifo"
    os.mkfifo(leaf, 0o600)
    original = os.open

    def checked_open(path, flags, *args, **kwargs):
        if path == leaf.name and kwargs.get("dir_fd") is not None:
            pytest.fail("an existing nonregular leaf must not reach open")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", checked_open)
    with pytest.raises(ValueError, match="worker_cli_(file|ledger)_invalid"):
        if operation == "read":
            worker_cli._read(leaf, 4096, private=True)
        else:
            with worker_cli._existing_ledger(leaf):
                pytest.fail("a FIFO cannot grant ledger access")


@pytest.mark.parametrize("operation", ["read", "ledger"])
def test_cli_regular_to_fifo_race_is_nonblocking_and_refused(tmp_path, monkeypatch, operation):
    leaf = tmp_path.resolve() / "original"
    leaf.write_bytes(b"original inert bytes")
    leaf.chmod(0o600)
    original = os.open
    seen = []

    def replace_before_open(path, flags, *args, **kwargs):
        if path == leaf.name and kwargs.get("dir_fd") is not None:
            # No real FIFO open happens unless the nonblocking flag is present.
            assert flags & os.O_NONBLOCK
            assert flags & os.O_NOFOLLOW
            seen.append(True)
            leaf.unlink()
            os.mkfifo(leaf, 0o600)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    with pytest.raises(ValueError, match="worker_cli_(file|ledger)_changed"):
        if operation == "read":
            worker_cli._read(leaf, 4096, private=True)
        else:
            with worker_cli._existing_ledger(leaf):
                pytest.fail("a replaced FIFO cannot grant ledger access")
    assert seen == [True]
