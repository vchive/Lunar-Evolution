"""Opt-in socket ownership with real local AF_UNIX names and proc doubles.

The listener is a real local socket. Kernel table rows, the named service and
its FD links are explicit inert doubles; no Podman ownership is established.
"""

from __future__ import annotations

import copy
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import test_static_python_podman_vfs_root as original_tests
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

HEADER = "Num RefCount Protocol Flags Type St Inode Path\n"
PID = 1234
service_root_double = original_tests.service_root_double


def row(endpoint, *, inode="12345", flags="00010000", state="01", kind="0001",
        number="0000000000000000:", refs="00000002", protocol="00000000"):
    return f"{number} {refs} {protocol} {flags} {kind} {state} {inode} {endpoint}\n"


def accepted(endpoint, *, inode="12346", **changes):
    return row(endpoint, inode=inode, flags="00000000", state="03", refs="00000003", **changes)


@pytest.fixture
def socket_vector(monkeypatch):
    # Keep a short real pathname within macOS's AF_UNIX sun_path ceiling.
    with (tempfile.TemporaryDirectory(prefix="lvsc-", dir="/tmp") as directory,
          socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener):
        endpoint = Path(directory).resolve() / "podman.sock"
        listener.bind(str(endpoint))
        listener.listen(1)
        state = SimpleNamespace(endpoint=endpoint, rows=[row(endpoint)],
                                links={"4": "socket:[12345]"}, link_reads={},
                                scans=0, proc_reads=0, hook=None, extra_sockets=[])

        def proc_bytes(path, maximum=1024**2):
            assert path == f"/proc/{PID}/net/unix" and maximum == 1024**2
            state.proc_reads += 1
            return (HEADER + "".join(state.rows)).encode("ascii")

        @contextmanager
        def entries(path):
            assert path == f"/proc/{PID}/fd"
            state.scans += 1
            yield iter(SimpleNamespace(path="/inert-service-fd/" + name) for name in state.links)

        def readlink(path):
            name = str(path).rsplit("/", 1)[-1]
            state.link_reads[name] = state.link_reads.get(name, 0) + 1
            original = state.links[name]
            if state.hook is not None:
                return state.hook(name, state.link_reads[name], original)
            return original

        # Restore process APIs before TemporaryDirectory removes real entries.
        with monkeypatch.context() as proc:
            proc.setattr(vfs, "_proc_bytes", proc_bytes)
            proc.setattr(vfs.os, "scandir", entries)
            proc.setattr(vfs.os, "readlink", readlink)
            try:
                yield state
            finally:
                for extra in state.extra_sockets:
                    extra.close()


def observe(vector, *, connected_streams=True, checkpoint=lambda: None):
    return vfs._socket_owner(PID, vector.endpoint, checkpoint, connected_streams=connected_streams)


@pytest.mark.parametrize("order", ["accepted-first", "accepted-last", "multiple-accepted"])
def test_opt_in_profile_accepts_unique_listener_among_connected_stream_rows(socket_vector, order):
    vector = socket_vector
    listening, connected = row(vector.endpoint), accepted(vector.endpoint)
    vector.rows = ([connected, listening] if order == "accepted-first" else
                   [listening, connected, accepted(vector.endpoint, inode="12347")]
                   if order == "multiple-accepted" else [listening, connected])
    vector.links["8"] = "socket:[12346]"
    proof = observe(vector)
    assert proof == {"path": str(vector.endpoint), "identity": vfs.identity(vector.endpoint.lstat()),
                     "kernel_inode": 12345}
    assert vector.link_reads["4"] >= 2 and vector.scans == 1


def test_listener_only_proof_bytes_are_unchanged_from_original_profile(socket_vector):
    vector = socket_vector
    legacy = vfs._socket_owner(PID, vector.endpoint, lambda: None)
    assert observe(vector) == legacy


@pytest.mark.parametrize("order", ["first", "last"])
def test_legacy_profile_keeps_refusing_same_path_connected_stream_rows(socket_vector, order):
    vector = socket_vector
    listener, stream = row(vector.endpoint), accepted(vector.endpoint)
    vector.rows = [stream, listener] if order == "first" else [listener, stream]
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        vfs._socket_owner(PID, vector.endpoint, lambda: None)
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector, connected_streams=False)


@pytest.mark.parametrize("change", ["no-listener", "duplicate-listener", "duplicate-accepted",
                                     "listener-accepted-collision"])
def test_listener_and_connected_stream_inode_identity_is_unique(socket_vector, change):
    vector = socket_vector
    listener, stream = row(vector.endpoint), accepted(vector.endpoint)
    vector.rows = {
        "no-listener": [stream],
        "duplicate-listener": [listener, row(vector.endpoint, inode="12347")],
        "duplicate-accepted": [listener, stream, stream],
        "listener-accepted-collision": [listener, accepted(vector.endpoint, inode="12345")],
    }[change]
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)


@pytest.mark.parametrize("field,value", [
    ("number", "0000000:"), ("number", "00000000000000000:"),
    ("number", "0000000000000000"), ("number", "000000000000000g:"),
    ("refs", "0000002"), ("refs", "0000000x"), ("protocol", "00000001"),
    ("flags", "00000010"), ("kind", "0002"), ("state", "02"),
    ("inode", "0"), ("inode", "-1"), ("inode", "012345"),
    ("inode", "12x"), ("inode", str(2**64)), ("inode", "1" * 21),
], ids=["short-num", "long-num", "missing-colon", "nonhex-num", "short-ref", "nonhex-ref",
        "protocol", "flags", "nonstream", "unknown-state", "zero-inode", "negative-inode",
        "noncanonical-inode", "nondecimal-inode", "overflow-inode", "long-inode"])
def test_every_matching_listener_row_has_the_exact_bounded_kernel_shape(socket_vector, field, value):
    vector = socket_vector
    vector.rows = [row(vector.endpoint, **{field: value})]
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)


@pytest.mark.parametrize("change", ["flags", "type", "state", "inode", "extra-column",
                                     "missing-inode", "misplaced-path"])
def test_malformed_connected_rows_cannot_hide_beside_valid_listener(socket_vector, change):
    vector = socket_vector
    fields = accepted(vector.endpoint).split()
    if change == "flags":
        fields[3] = "00010000"
    elif change == "type":
        fields[4] = "0002"
    elif change == "state":
        fields[5] = "01"
    elif change == "inode":
        fields[6] = "0"
    elif change == "extra-column":
        fields.append("extra")
    elif change == "missing-inode":
        fields.pop(6)
    else:
        fields[6], fields[7] = fields[7], fields[6]
    vector.rows = [row(vector.endpoint), " ".join(fields) + "\n"]
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)


def test_unrelated_path_rows_and_prefix_siblings_do_not_replace_matching_listener(socket_vector):
    vector = socket_vector
    vector.rows = [f"malformed unrelated row {vector.endpoint}-sibling\n", row(vector.endpoint)]
    assert observe(vector)["kernel_inode"] == 12345


def test_service_must_own_listener_instead_of_only_an_accepted_stream(socket_vector):
    vector = socket_vector
    vector.rows.append(accepted(vector.endpoint))
    vector.links = {"4": "socket:[12346]"}
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)


def test_duplicate_owned_descriptors_for_same_unique_listener_remain_supported(socket_vector):
    vector = socket_vector
    vector.links["5"] = "socket:[12345]"
    assert observe(vector)["kernel_inode"] == 12345
    assert max(vector.link_reads.values()) >= 2


@pytest.mark.parametrize("change", ["different-inode", "disappeared"])
def test_original_winning_listener_fd_link_is_rechecked(socket_vector, change):
    vector = socket_vector

    def drift(_name, count, original):
        if count == 1:
            return original
        if change == "disappeared":
            raise FileNotFoundError("inert original FD disappeared")
        return "socket:[99999]"

    vector.hook = drift
    with pytest.raises((BuildExecutionError, FileNotFoundError)):
        observe(vector)
    assert vector.link_reads["4"] >= 2


def test_original_socket_path_is_rechecked_after_fd_ownership_observation(socket_vector):
    vector = socket_vector
    replaced = []

    def replace_name(_name, _count, original):
        if not replaced:
            original_identity = vfs.identity(vector.endpoint.lstat())
            vector.endpoint.rename(vector.endpoint.with_name("original.sock"))
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            vector.extra_sockets.append(replacement)
            replacement.bind(str(vector.endpoint))
            replacement.listen(1)
            assert vfs.identity(vector.endpoint.lstat()) != original_identity
            replaced.append(True)
        return original

    vector.hook = replace_name
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)
    assert replaced == [True]


def test_connected_stream_table_and_original_fd_scan_remain_bounded(socket_vector, monkeypatch):
    vector = socket_vector
    monkeypatch.setattr(vfs, "MAX_RECORDS", 4)
    vector.rows.extend(accepted(vector.endpoint, inode=str(12346 + index)) for index in range(4))
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)


def test_second_bounded_table_must_keep_original_owned_listener_inode(socket_vector, monkeypatch):
    vector = socket_vector
    original_read = vfs._proc_bytes

    def replaced_table(path, maximum=1024**2):
        original = original_read(path, maximum)
        if vector.proc_reads == 2:
            return (HEADER + row(vector.endpoint, inode="54321")).encode("ascii")
        return original

    monkeypatch.setattr(vfs, "_proc_bytes", replaced_table)
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)
    assert vector.proc_reads == 2 and vector.scans == 1
    assert vector.link_reads["4"] >= 2


def test_original_fd_scan_has_independent_ceiling_with_valid_single_listener_table(socket_vector, monkeypatch):
    vector = socket_vector
    monkeypatch.setattr(vfs, "MAX_RECORDS", 4)
    vector.links = {str(index): "socket:[12345]" if index == 0 else "socket:[99999]"
                    for index in range(5)}
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector)
    assert vector.proc_reads == 1 and vector.scans == 1
    assert "4" not in vector.link_reads


def test_original_cancellation_cannot_continue_to_fd_ownership_scan(socket_vector):
    vector = socket_vector
    primary = BuildExecutionError("deadline_expired")

    def checkpoint():
        raise primary

    with pytest.raises(BuildExecutionError) as caught:
        observe(vector, checkpoint=checkpoint)
    assert caught.value is primary and vector.scans == 0


@pytest.mark.parametrize("value", [None, 1, "yes"], ids=["none", "integer", "string"])
def test_socket_profile_is_an_exact_boolean_before_proc_read(socket_vector, value):
    vector = socket_vector
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        observe(vector, connected_streams=value)
    assert vector.proc_reads == 0 and vector.scans == 0


@pytest.mark.parametrize("value", [None, 1, "yes"], ids=["none", "integer", "string"])
def test_service_profile_is_an_exact_boolean_before_pidfd_open(monkeypatch, value):
    monkeypatch.setattr(vfs.os, "pidfd_open", lambda *_args: pytest.fail("pidfd opened before mode gate"),
                        raising=False)
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        vfs.ServiceRoot(PID, lambda: None, _connected_streams=value)


@pytest.mark.parametrize("profile", ["legacy", "connected-streams"])
def test_constructor_and_each_verification_reuse_original_selected_socket_profile(
        service_root_double, monkeypatch, profile):
    vector = service_root_double
    calls = []

    def owner(pid, endpoint, checkpoint, **options):
        assert pid == vector.pid and str(endpoint) == vector.socket["path"]
        calls.append(options)
        return copy.deepcopy(vector.socket)

    poller = SimpleNamespace(register=lambda *_args: None, poll=lambda _timeout: [])
    monkeypatch.setattr(vfs, "_socket_owner", owner)
    monkeypatch.setattr(vfs, "select", SimpleNamespace(poll=lambda: poller, POLLIN=1))
    options = {"_release_all": True, "_connected_streams": True} if profile == "connected-streams" else {}
    service = vfs.ServiceRoot(vector.pid, lambda: None, **options)
    try:
        service.verify()
        expected = {"connected_streams": True} if profile == "connected-streams" else {}
        assert calls == [expected, expected, expected]
    finally:
        service.close()
