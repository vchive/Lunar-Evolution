"""Original, read-only physical custody and scalar deadlines for staged ready.

Capture runs once after the complete empty-channel semantic observation.  The
last reader uses held native I/O and original primitive pins, never reconstructs
authority from DTOs, and does not refresh the pre-arm snapshot.  It grants no ACK.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import sys
import time
import types

from . import rsi_brs_rejection_ready_ack as ack_graph
from . import rsi_brs_rejection_ready_ledger as ledger
from . import rsi_brs_rejection_ready_locks as locks
from . import rsi_brs_rejection_ready_state as transport_state
from . import rsi_brs_rejection_ready_sync as sync
from . import rsi_learning as learning


def _build_readers():
    kind, length, namespace_of, identity = type, len, vars, id
    plain_tuple, plain_dict, plain_str, plain_int = tuple, dict, str, int
    plain_bytes, plain_list, plain_bool, plain_float = bytes, list, bool, float
    some, pairs, ordering = any, zip, sorted
    object_get, type_get = object.__getattribute__, type.__getattribute__
    member_get = types.MemberDescriptorType.__get__
    dict_get = types.GetSetDescriptorType.__get__
    member_type, getset_type = types.MemberDescriptorType, types.GetSetDescriptorType
    mapping_type = types.MappingProxyType
    error_type, error_new = learning.RSILearningError, BaseException.__new__
    error_dict, dict_set = namespace_of(BaseException)["__dict__"], dict.__setitem__
    open_file, read_file, close_file = os.open, os.read, os.close
    named_stat, fd_stat, list_names = os.stat, os.fstat, os.listdir
    is_regular, is_directory, mode_of = stat.S_ISREG, stat.S_ISDIR, stat.S_IMODE
    absent_error = FileNotFoundError
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    sha256, finite, unix_now, monotonic_now = hashlib.sha256, math.isfinite, time.time, time.monotonic
    raw_assert = ledger.assert_rejection_ready_rows
    lock_assert, condition_assert = locks.assert_rejection_ready_locks, sync.assert_ready_condition
    inflight_assert = transport_state.assert_selected_ready_inflight
    ack_assert = ack_graph.assert_rejection_ready_ack
    decode = json.loads  # Capture only; no JSON path is reachable in the final tail.
    prefix, missing = "rsi_brs_rejection_ready_final_", object()
    max_material, max_runtime = 16 * 1024 * 1024, 256 * 1024 * 1024

    def fail(reason):
        message = prefix + reason
        error = error_new(error_type, message)
        dict_set(dict_get(error_dict, error, error_type), "code", message)
        raise error

    def path_parts(path):
        if (kind(path) is not plain_str or not path.startswith("/")
                or "\x00" in path or length(path.encode("utf-8")) > 4096):
            fail("path_invalid")
        parts = plain_tuple(path.split("/")[1:])
        # The source may spell an absolute POSIX root with two leading slashes.
        if parts and parts[0] == "":
            parts = parts[1:]
        if (not parts or length(parts) > 128
                or some(part in ("", ".", "..") for part in parts)):
            fail("path_invalid")
        return parts

    def metadata(info):
        return (info.st_dev, info.st_ino, mode_of(info.st_mode), info.st_nlink,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def open_parent(path):
        parts = path_parts(path)
        fds, links = [], []
        try:
            fds.append(open_file("/", directory_flags))
            for name in parts[:-1]:
                parent = fds[-1]
                before = named_stat(name, dir_fd=parent, follow_symlinks=False)
                if not is_directory(before.st_mode):
                    fail("directory_invalid")
                child = open_file(name, directory_flags, dir_fd=parent)
                fds.append(child)
                after = fd_stat(child)
                if ((before.st_dev, before.st_ino, before.st_mode)
                        != (after.st_dev, after.st_ino, after.st_mode)):
                    fail("directory_changed")
                links.append((parent, name, child))
            check_chain(fds, links)
            return parts[-1], fds, links
        except BaseException:
            close_all(fds)
            raise

    def check_chain(fds, links):
        result = []
        root = fd_stat(fds[0])
        if not is_directory(root.st_mode):
            fail("directory_invalid")
        result.append((root.st_dev, root.st_ino, mode_of(root.st_mode)))
        for parent, name, child in links:
            current, opened = named_stat(name, dir_fd=parent, follow_symlinks=False), fd_stat(child)
            if (not is_directory(current.st_mode) or not is_directory(opened.st_mode)
                    or (current.st_dev, current.st_ino, current.st_mode)
                    != (opened.st_dev, opened.st_ino, opened.st_mode)):
                fail("directory_changed")
            result.append((opened.st_dev, opened.st_ino, mode_of(opened.st_mode)))
        return plain_tuple(result)

    def close_all(fds):
        failure = None
        while fds:
            descriptor = fds.pop()
            try:
                close_file(descriptor)
            except BaseException as error:  # noqa: BLE001 - finish releasing owned descriptors.
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def observe_absence(path):
        parts = path_parts(path)
        fds, links = [open_file("/", directory_flags)], []
        try:
            for index, name in enumerate(parts):
                try:
                    before = named_stat(name, dir_fd=fds[-1], follow_symlinks=False)
                except absent_error:
                    return check_chain(fds, links)
                if index == length(parts) - 1:
                    fail("absence_drift")
                if not is_directory(before.st_mode):
                    fail("directory_invalid")
                parent = fds[-1]
                child = open_file(name, directory_flags, dir_fd=parent)
                fds.append(child)
                links.append((parent, name, child))
                if ((before.st_dev, before.st_ino, before.st_mode)
                        != (fd_stat(child).st_dev, fd_stat(child).st_ino, fd_stat(child).st_mode)):
                    fail("directory_changed")
            fail("absence_drift")
        finally:
            close_all(fds)

    def observe_file(path, maximum, retain=False, absent=False, inode_only=False):
        if kind(maximum) is not plain_int or not 0 <= maximum <= max_runtime:
            fail("limit_invalid")
        if absent:
            return path, observe_absence(path), None, None, None, maximum, retain, absent, inode_only
        name, fds, links = open_parent(path)
        descriptor = None
        try:
            directories = check_chain(fds, links)
            try:
                before = named_stat(name, dir_fd=fds[-1], follow_symlinks=False)
            except absent_error:
                if absent:
                    check_chain(fds, links)
                    return path, directories, None, None, None, maximum, retain, absent, inode_only
                raise
            if absent:
                fail("absence_drift")
            if (not is_regular(before.st_mode) or before.st_nlink != 1
                    or before.st_mode & 0o6000 or (not inode_only and before.st_size > maximum)):
                fail("file_invalid")
            descriptor = open_file(name, file_flags, dir_fd=fds[-1])
            opened = fd_stat(descriptor)
            if ((before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                    or not is_regular(opened.st_mode) or opened.st_nlink != 1):
                fail("file_changed")
            if not inode_only and metadata(before) != metadata(opened):
                fail("file_changed")
            raw, count, digest = [], 0, sha256()
            if not inode_only:
                while count <= maximum:
                    chunk = read_file(descriptor, min(65536, maximum + 1 - count))
                    if not chunk:
                        break
                    count += length(chunk)
                    if count > maximum:
                        fail("capacity_exceeded")
                    digest.update(chunk)
                    if retain:
                        raw.append(chunk)
            after = fd_stat(descriptor)
            named = named_stat(name, dir_fd=fds[-1], follow_symlinks=False)
            if inode_only:
                if (some(not is_regular(item.st_mode) or item.st_nlink != 1 for item in (after, named))
                        or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)
                        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
                    fail("ledger_inode_drift")
                info = (opened.st_dev, opened.st_ino)
            else:
                if (metadata(opened) != metadata(after) or metadata(after) != metadata(named)
                        or count != after.st_size):
                    fail("file_changed")
                info = metadata(after)
            if check_chain(fds, links) != directories:
                fail("directory_changed")
            return (path, directories, info, None if inode_only else digest.hexdigest(),
                    b"".join(raw) if retain else None, maximum, retain, absent, inode_only)
        finally:
            try:
                if descriptor is not None:
                    close_file(descriptor)
            finally:
                close_all(fds)

    def assert_file(pin):
        if kind(pin) is not plain_tuple or length(pin) != 9:
            fail("file_pin_invalid")
        path, _directories, _metadata, _sha, _raw, maximum, retain, absent, inode_only = pin
        if (kind(retain) is not plain_bool or kind(absent) is not plain_bool
                or kind(inode_only) is not plain_bool):
            fail("file_pin_invalid")
        if observe_file(path, maximum, retain, absent, inode_only) != pin:
            fail("physical_drift")

    def observe_directory(path):
        # Reuse the same lexical and descriptor-relative chain reader, including
        # the terminal directory; listdir receives the held FD, never a Path.
        _name, fds, links = open_parent(path + "/.ready-custody-unused")
        try:
            chain = check_chain(fds, links)
            before = metadata(fd_stat(fds[-1]))
            names = plain_tuple(ordering(list_names(fds[-1])))
            if some(kind(name) is not plain_str or "/" in name or "\x00" in name for name in names):
                fail("directory_invalid")
            if metadata(fd_stat(fds[-1])) != before or check_chain(fds, links) != chain:
                fail("directory_changed")
            return path, chain, before, names
        finally:
            close_all(fds)

    def frozen(value, depth=0, remaining=None, seen=None):
        """Closed primitive/declared DTO observation without serializers or callbacks."""
        if remaining is None:
            remaining, seen = [100_000, 64 * 1024 * 1024], {}
        remaining[0] -= 1
        if depth > 48 or remaining[0] < 0:
            fail("shape_invalid")
        declared = kind(value)
        if value is None or some(declared is scalar for scalar in (
                plain_str, plain_bytes, plain_int, plain_bool, plain_float)):
            if declared is plain_str or declared is plain_bytes:
                remaining[1] -= length(value)
                if remaining[1] < 0:
                    fail("shape_invalid")
            if declared is plain_float and not finite(value):
                fail("numeric_invalid")
            return identity(declared), value
        marker = identity(value)
        if marker in seen:
            return "reference", marker
        seen[marker] = True
        if declared is plain_list or declared is plain_tuple:
            return identity(declared), marker, plain_tuple(
                frozen(item, depth + 1, remaining, seen) for item in value)
        if declared is plain_dict or declared is mapping_type:
            if length(value) > 100_000 or some(kind(key) is not plain_str for key in value):
                fail("shape_invalid")
            return identity(declared), marker, plain_tuple(
                (key, frozen(value[key], depth + 1, remaining, seen)) for key in ordering(value))
        if kind(declared) is not type:
            fail("shape_invalid")
        members = type_get(declared, "__dict__")
        # Functions/locks/paths and other opaque leaves are held by identity;
        # source, locks and file paths have independent physical/live gates.
        fields = members.get("__dataclass_fields__")
        if kind(fields) is not plain_dict:
            return "opaque", marker, identity(declared)
        if some(kind(name) is not plain_str for name in fields):
            fail("shape_invalid")
        hierarchy = type_get(declared, "__mro__")
        hierarchy_domain = plain_tuple((identity(base), plain_tuple(
            (name, identity(item)) for name, item in type_get(base, "__dict__").items()))
                                       for base in hierarchy)
        values = []
        dictionary_descriptor = members.get("__dict__")
        if kind(dictionary_descriptor) is not getset_type:
            for base in hierarchy:
                candidate = type_get(base, "__dict__").get("__dict__")
                if kind(candidate) is getset_type:
                    dictionary_descriptor = candidate
                    break
        namespace = (dict_get(dictionary_descriptor, value, declared)
                     if kind(dictionary_descriptor) is getset_type else None)
        if namespace is not None and (kind(namespace) is not plain_dict
                                      or some(kind(key) is not plain_str for key in namespace)):
            fail("shape_invalid")
        namespace_domain = (None if namespace is None else
                            (identity(namespace), plain_tuple(ordering(namespace))))
        for name in ordering(fields):
            descriptor = members.get(name)
            if kind(descriptor) is member_type:
                item = member_get(descriptor, value, declared)
            elif kind(namespace) is plain_dict and name in namespace:
                item = namespace[name]
            else:
                fail("shape_invalid")
            values.append((name, frozen(item, depth + 1, remaining, seen)))
        return ("dto", marker, identity(declared),
                plain_tuple((name, identity(item)) for name, item in members.items()),
                identity(hierarchy), hierarchy_domain, namespace_domain, plain_tuple(values))

    def binding(instance, name, deep=False):
        declared = kind(instance)
        if kind(declared) is not type or kind(name) is not plain_str:
            fail("instance_invalid")
        members = type_get(declared, "__dict__")
        hierarchy = type_get(declared, "__mro__")
        hierarchy_pins = plain_tuple((base, plain_tuple(type_get(base, "__dict__").items()))
                                     for base in hierarchy)
        descriptor = members.get(name)
        dictionary_descriptor = members.get("__dict__")
        if kind(dictionary_descriptor) is not getset_type:
            for base in hierarchy:
                candidate = type_get(base, "__dict__").get("__dict__")
                if kind(candidate) is getset_type:
                    dictionary_descriptor = candidate
                    break
        if kind(descriptor) is member_type:
            namespace, value = None, member_get(descriptor, instance, declared)
        elif kind(dictionary_descriptor) is getset_type:
            namespace = dict_get(dictionary_descriptor, instance, declared)
            if (kind(namespace) is not plain_dict or name not in namespace
                    or some(kind(key) is not plain_str for key in namespace)):
                fail("instance_invalid")
            value = namespace[name]
        else:
            fail("instance_invalid")
        return (instance, declared, plain_tuple(members.items()), name, descriptor,
                dictionary_descriptor, namespace, value, frozen(value) if deep else None, deep,
                None if namespace is None else plain_tuple(ordering(namespace)), hierarchy, hierarchy_pins)

    def assert_binding(pin):
        (instance, declared, members, name, descriptor, dictionary_descriptor,
         namespace, original, content, deep, namespace_domain, hierarchy, hierarchy_pins) = pin
        if kind(instance) is not declared or type_get(declared, "__mro__") is not hierarchy:
            fail("custody_drift")
        for base, base_members in hierarchy_pins:
            current_base = type_get(base, "__dict__")
            if (length(current_base) != length(base_members)
                    or some(current_base.get(key, missing) is not item for key, item in base_members)):
                fail("declaration_drift")
        current_members = type_get(declared, "__dict__")
        if (length(current_members) != length(members)
                or some(current_members.get(key, missing) is not value for key, value in members)):
            fail("declaration_drift")
        if namespace is None:
            current = member_get(descriptor, instance, declared)
        else:
            current_namespace = dict_get(dictionary_descriptor, instance, declared)
            if (current_namespace is not namespace
                    or some(kind(key) is not plain_str for key in namespace)
                    or length(namespace) != length(namespace_domain)
                    or plain_tuple(ordering(namespace)) != namespace_domain):
                fail("custody_drift")
            current = namespace.get(name, missing)
        if current is not original or (deep and frozen(current) != content):
            fail("custody_drift")

    def pin_matches_file(pin, expected):
        info = pin[2]
        if (kind(expected) is not plain_dict or info is None
                or info != (expected["device"], expected["inode"], expected["mode"], expected["nlink"],
                            expected["size"], expected["mtime_ns"], expected["ctime_ns"])
                or pin[3] != expected["sha256"]
                or pin[1][-1][:2] != (expected["parent_device"], expected["parent_inode"])):
            fail("original_file_pin_drift")

    def scalar_deadline(value, optional=False):
        if value is None and optional:
            return None
        if kind(value) is not plain_int and kind(value) is not plain_float:
            fail("numeric_invalid")
        try:
            valid = finite(value) and value > 0
        except OverflowError:
            valid = False
        if not valid:
            fail("numeric_invalid")
        return value

    def scalar_tail(owner, capsule):
        for pin in capsule[1]:
            assert_binding(pin)
        if (owner is not capsule[0] or owner._rejection_ready_final_capture is not capsule
                or owner._poisoned is not False or owner._phase != "rejected-provenance"
                or owner._retaining_before is not False or owner._retaining_rejection is not False
                or owner._retaining_rejection_provenance is not False
                or owner._retaining_success is not None or owner._rejection_deadline is not None
                or owner._rejection_provenance_deadline is not None or owner._success_deadline is not None):
            fail("custody_drift")
        control = capsule[2]
        if control is not None:
            namespace = capsule[3]
            if namespace.get("_cancelled") is not False:
                fail("cancelled")
        unix, mono = capsule[8]
        now_unix, now_mono = unix_now(), monotonic_now()
        if (kind(now_unix) is not plain_float or kind(now_mono) is not plain_float
                or not finite(now_unix) or not finite(now_mono)
                or some(now_unix >= value for value in unix)
                or some(now_mono >= value for value in mono)):
            fail("deadline_exhausted")

    def capture_impl(owner):
        if owner._rejection_ready_final_capture is not None:
            fail("capture_consumed")
        original = owner._rejection_ready_capture
        if kind(original) is not plain_tuple or length(original) != 6:
            fail("prearm_capture_required")
        c1 = decode(owner._rejection_c1_capture[1])
        entry = c1["producer_publication_lineage"]["batches"][owner._ordinal]
        workspace = str(owner._workspace)
        batch = workspace + "/evolution/producer-batches/" + owner._plan.journal_id
        lineage_path = batch + "/lineage/"
        files, directories = {}, {}

        def add(path, maximum=max_material, retain=False, absent=False, inode_only=False):
            observed = observe_file(path, maximum, retain, absent, inode_only)
            if path in files and files[path] != observed:
                fail("capture_drift")
            files[path] = observed
            return observed

        for key in ("before_file_pin", "rejected_file_pin"):
            name = entry[key]["name"]
            if (kind(name) is not plain_str
                    or (key == "before_file_pin" and name not in ("before.json", "before-v2.json"))
                    or (key == "rejected_file_pin" and name != "rejected.json")):
                fail("original_file_pin_drift")
            pin_matches_file(add(lineage_path + name), entry[key])
        for pin in entry["snapshots"].values():
            pin_matches_file(add(lineage_path + pin["name"]), pin)
        for name, pin in entry["evidence_pins"].items():
            observed = add(batch + "/" + name, retain=name.startswith("rejections/"))
            pin_matches_file(observed, pin)
            if name.startswith("rejections/"):
                retained = decode(observed[4])["retained_evidence"]["entries"]
                for item in retained:
                    path = workspace + "/" + item["path"]
                    if item["kind"] == "directory":
                        observed_directory = observe_directory(path)
                        info = observed_directory[2]
                        if ((info[0], info[1], info[5], info[6])
                                != (item["device"], item["inode"], item["mtime_ns"], item["ctime_ns"])):
                            fail("retained_directory_drift")
                        directories[path] = observed_directory
                    else:
                        observed_file = add(path)
                        info = observed_file[2]
                        if ((info[0], info[1], info[4], info[5], info[6], observed_file[3])
                                != (item["device"], item["inode"], item["size"], item["mtime_ns"],
                                    item["ctime_ns"], item["sha256"])):
                            fail("retained_file_drift")
        if owner._reserved_prefix is not None:
            from .rsi_brs_rejection_owner import _reserved_material_tables

            rejection_tables, published_tables = _reserved_material_tables(
                owner, c1["producer_publication_lineage"])
            for historical in c1["producer_publication_lineage"]["batches"][:owner._ordinal]:
                historical_batch = workspace + "/evolution/producer-batches/" + historical["journal_id"] + "/"
                for descriptor_kind in ("before", "staged", "terminal", "rejected"):
                    field = descriptor_kind + "_file_pin"
                    if field in historical:
                        pin = historical[field]
                        pin_matches_file(add(historical_batch + "lineage/" + pin["name"]), pin)
                for pin in historical["snapshots"].values():
                    pin_matches_file(add(historical_batch + "lineage/" + pin["name"]), pin)
                for name, pin in historical["evidence_pins"].items():
                    pin_matches_file(add(historical_batch + name), pin)
                historical_p = historical.get("rejection_provenance")
                if historical_p is not None:
                    pin = historical_p["file_pin"]
                    pin_matches_file(add(historical_batch + pin["name"], 1024 * 1024), pin)
            native_observations = []
            for tables in rejection_tables.values():
                for table in tables.values():
                    native_observations.extend(table["entries"])
            for table in published_tables.values():
                native_observations.extend({"path": path, **record} for path, record in table.items())
            for item in native_observations:
                path = workspace + "/" + item["path"]
                if item["kind"] == "directory":
                    observed = observe_directory(path)
                    info = observed[2]
                    if ((info[0], info[1], info[5], info[6])
                            != (item["device"], item["inode"], item["mtime_ns"], item["ctime_ns"])):
                        fail("retained_directory_drift")
                    directories[path] = observed
                else:
                    observed = add(path)
                    info = observed[2]
                    if ((info[0], info[1], info[4], info[5], info[6], observed[3])
                            != (item["device"], item["inode"], item["size"], item["mtime_ns"],
                                item["ctime_ns"], item["sha256"])):
                        fail("retained_file_drift")
        for name, pin in entry["before_sources"].items():
            path = workspace + "/evolution/" + name + (".jsonl" if name == "archive" else ".json")
            if pin.get("missing") is True:
                add(path, absent=True)
            else:
                pin_matches_file(add(path), pin)
        provenance_entry = entry.get("rejection_provenance")
        p_pin = provenance_entry.get("file_pin") if kind(provenance_entry) is plain_dict else None
        # C1 predates P, so the original writer pin lives in the confirmed C2.
        if p_pin is None:
            c2 = decode(owner._rejection_provenance_c2_capture[1])
            p_pin = c2["producer_publication_lineage"]["batches"][owner._ordinal]["rejection_provenance"]["file_pin"]
        p = add(batch + "/native-rsi.rejection-provenance.json", 1024 * 1024, retain=True)
        pin_matches_file(p, p_pin)
        p_body = decode(p[4])
        if p_body["provenance_sha256"] != owner._rejection_provenance_sha256:
            fail("provenance_drift")
        for name in ("native-rsi.provenance.json", "native-rsi.failure-provenance.json",
                     "stage", "manifest.json", "journal.staged.json", "journal.published.json", "terminal.json"):
            add(batch + "/" + name, absent=True)
        add(workspace + "/evolution/producer-publication.json", absent=True)
        directories[batch + "/rejections"] = observe_directory(batch + "/rejections")
        for candidate in entry["rejected"]["candidate_ids"]:
            add(workspace + "/evolution/candidates/" + candidate, absent=True)
        # All original runtime files and closed directory membership are finite
        # tables retained independently by the original producer binding.
        producer_binding = owner._sidecar.binding
        roots = {root.label: root.path for root in producer_binding.runtime_manifest.roots}
        for item in producer_binding.runtime_manifest.files:
            observed = add(roots[item.root_label] + "/" + item.relative_path, max_runtime)
            info = observed[2]
            if ((info[0], info[1], info[2], info[4], info[5], info[6], observed[3])
                    != (item.device, item.inode, item.mode, item.size, item.mtime_ns, item.ctime_ns, item.sha256)):
                fail("runtime_file_drift")
        for item in producer_binding.runtime_tree.directories:
            relative = item.relative_path
            path = roots[item.root_label] + ("/" + relative if relative not in ("", ".") else "")
            observed = observe_directory(path)
            info = observed[2]
            if ((info[0], info[1], info[2], info[5], info[6], observed[3])
                    != (item.device, item.inode, item.mode, item.mtime_ns, item.ctime_ns, item.children)):
                fail("runtime_directory_drift")
            directories[path] = observed
        # Explicit stable native sidecar roots; no recursive arbitrary scan or
        # discovery/adoption of a different attempt is performed.
        native_names = (
            "python-producer-binding.json", "python-producer-admission-handoff.json",
            "native-rsi-launch.json", ".rsi-input/request.json", ".rsi-input/memory.json",
            ".rsi-input/manifest.json", "attestation-consumption.json", "process-registration.json",
            "execution-receipt.json", "native-trusted-process-terminal.json",
            "native-trusted-process-recovery.json", "native-trusted-attempt-deadline.json",
            "native-trusted-execution-audit.json", "native-trusted-output-capture.json",
            "native-trusted-cleanup.json", "native-trusted-stream-capture.json",
            "native-deadline-binding.json", "trusted-bootstrap-evidence.json",
        )
        for name in native_names:
            path = batch + "/" + name
            # Some platform-specific optional sidecars are absent in a valid
            # attempt. Pin absence itself, never choose a replacement later.
            try:
                add(path, 128 * 1024 * 1024)
            except absent_error:
                add(path, absent=True)
        add(batch + "/" + owner._native.intent.envelope_path, 128 * 1024 * 1024)
        for name, field in (("process-registration.json", "target_execution_snapshot_relative_path"),
                            ("native-trusted-output-capture.json", "broker_evidence")):
            path = batch + "/" + name
            observed = files[path]
            if observed[2] is not None:
                raw = observe_file(path, max_material, retain=True)
                if raw[:4] != observed[:4]:
                    fail("capture_drift")
                document = decode(raw[4])
                value = document.get(field)
                relative = value.get("journal_relative_path") if kind(value) is plain_dict else value
                if relative is not None:
                    if (kind(relative) is not plain_str or relative.startswith("/")
                            or some(part in ("", ".", "..") for part in relative.split("/"))):
                        fail("path_invalid")
                    retained = add(batch + "/" + relative, 128 * 1024 * 1024)
                    info = retained[2]
                    if field == "broker_evidence":
                        if ((info[0], info[1], info[4], retained[3])
                                != (*value["journal_file_identity"], value["journal_bytes"],
                                    value["journal_sha256"])):
                            fail("native_broker_journal_drift")
                    elif ((info[4], retained[3])
                            != (document["target_execution_snapshot_size"],
                                document["target_execution_snapshot_sha256"])):
                        fail("native_target_snapshot_drift")
        output_capture = observe_file(batch + "/native-trusted-output-capture.json", max_material, retain=True)
        for material in decode(output_capture[4])["materials"]:
            relative = material["path"]
            if (kind(relative) is not plain_str or relative.startswith("/")
                    or some(part in ("", ".", "..") for part in relative.split("/"))):
                fail("path_invalid")
            observed = add(batch + "/" + owner._native.intent.output_directory + "/" + relative,
                           128 * 1024 * 1024)
            info = observed[2]
            if ((info[0], info[1], info[4], info[5], info[6], observed[3])
                    != (material["device"], material["inode"], material["bytes"], material["mtime_ns"],
                        material["ctime_ns"], material["sha256"])):
                fail("native_output_material_drift")
        nonce = sha256(owner._native.attestation.nonce.encode("utf-8")).hexdigest()
        nonce_path = workspace + "/evolution/producer-nonces/" + nonce + ".json"
        try:
            add(nonce_path, max_material)
        except absent_error:
            add(nonce_path, absent=True)
        add(str(owner._native.artifact.path), max_runtime)
        # Retain each concrete loaded Lunar source once. The existing policy
        # has already checked canonical source fingerprints before this call.
        source_root = __file__.rsplit("/", 1)[0] + "/"
        for module_name, module in plain_tuple(sys.modules.items()):
            if (kind(module_name) is plain_str and module_name.startswith("lunar_evolution.")
                    and kind(module) is types.ModuleType):
                namespace = namespace_of(module)
                path = namespace.get("__file__")
                if kind(path) is plain_str and path.startswith(source_root) and path.endswith(".py"):
                    add(path, 1024 * 1024)
        ledger_identity = decode(owner._rejection_ledger_identity)
        database = ledger_identity["database"]
        ledger_pin = add(database, inode_only=True)
        if ledger_pin[2] != (ledger_identity["device"], ledger_identity["inode"]):
            fail("ledger_inode_drift")
        pins = []
        owner_names = ("_rejection_ready_capture", "_rejection_c1_capture", "_rejection_provenance_c2_capture",
                       "_rejection_file_pin", "_rejection_provenance_file_pin", "_rejection_ledger_identity",
                       "_rejection_provenance_evidence", "_rejection_provenance_sha256", "_budget_bytes",
                       "_handoff_bytes", "_selected_context_bytes", "_head", "_payload", "_policy_bytes",
                       "_controller", "_ledger", "_wave", "_channel", "_plan", "_request", "_memory",
                       "_before_control", "_before_control_pin", "_before_cancelled", "_native_inputs",
                       "_native", "_sidecar", "_workspace", "_thread", "_rejection_ready_locks_capture",
                       "_rejection_ready_sync_capture", "_ordinal", "_reserved_prefix",
                       "_reserved_lineage_bytes", "_reserved_original_checkpoint", "_reserved_capture_bytes",
                       "_reserved_scope", "_reserved_gateway", "_root_sidecar")
        pins.extend(binding(owner, name) for name in owner_names)
        if owner._reserved_prefix is not None:
            for name in ("domain_bytes", "batch_bytes", "canonical_bytes"):
                pins.append(binding(owner._reserved_prefix, name, True))
            pins.append(binding(owner, "_reserved_scope", True))
            pins.append(binding(owner._reserved_gateway, "config", True))
            pins.append(binding(owner._reserved_gateway, "producer_config", True))
        for name in ("_state", "_plan", "_request", "_memory", "_native", "_native_inputs", "_sidecar", "_root_sidecar"):
            pins.append(binding(owner, name, True))
        for name in ("_native_config", "_strategy_config", "_strategy_context", "_strategy_bytes",
                     "_strategy_authority", "_strategy_archive", "_strategy_contract"):
            pins.append(binding(owner, name, True))
        for name in ("context", "config", "integrity_authority", "archive"):
            pins.append(binding(owner._strategy, name, True))
        pins.append(binding(owner._strategy_archive, "workspace", True))
        for name in ("state", "budget_state", "checkpoint_sha256", "payload", "active", "selected_return",
                     "selected_settlement_started", "channel", "selected_handoff", "selected_context"):
            pins.append(binding(owner._wave, name, True))
        control, control_namespace = owner._before_control, None
        mono = ()
        if control is not None:
            control_namespace = object_get(control, "__dict__")
            for name in ("started_at", "deadline", "timeout_seconds", "_clock", "_observe_stage", "_lock",
                         "_cancellation_callbacks"):
                pins.append(binding(control, name, True))
            mono = (scalar_deadline(control_namespace["deadline"]),)
        planned = owner._wave.budget_state["planned"]
        unix = plain_tuple(value for value in (
            scalar_deadline(owner._plan.deadline_unix), scalar_deadline(producer_binding.deadline_unix),
            scalar_deadline(planned["deadline_unix"], True)) if value is not None)
        capsule = (owner, plain_tuple(pins), control, control_namespace,
                   plain_tuple(files[path] for path in ordering(files)),
                   plain_tuple(directories[path] for path in ordering(directories)),
                   original[1], ledger_pin, (unix, mono))
        # The caller installs this exact capsule only after this entire capture
        # succeeds. Final assertion never allocates or installs a new baseline.
        return capsule

    def staged_tail(owner, capture, stage, ack, fields):
        if (owner._rejection_ready_stage is not stage or owner._rejection_ready_ack is not ack
                or owner._rejection_ready_ack_fields is not fields
                or kind(owner._rejection_ready_state) is not plain_str
                or owner._rejection_ready_state != "inflight"
                or owner._rejection_ready_commit_started is not False
                or kind(stage) is not plain_tuple or length(stage) != 4
                or stage[0] is not capture[3] or stage[1] is not capture[2]
                or kind(stage[3]) is not plain_tuple or length(stage[3]) != 4
                or stage[3][2] != capture[5]
                or kind(fields) is not plain_tuple or length(fields) != 4
                or some(kind(value) is not plain_str for value in fields)
                or fields != (capture[3][0], capture[3][1], stage[3][3], capture[4][2])):
            fail("staged_identity_drift")
        inflight_assert(owner._channel, stage)
        namespace = object_get(owner._channel, "__dict__")
        if kind(namespace) is not plain_dict or namespace.get("_rejection_ready_worker_guarded") is not True:
            fail("worker_unguarded")
        ack_assert(ack, fields)

    def assert_impl(owner, capsule):
        if kind(capsule) is not plain_tuple or length(capsule) != 9 or owner is not capsule[0]:
            fail("capsule_invalid")
        scalar_tail(owner, capsule)
        stage, ack, fields = (owner._rejection_ready_stage, owner._rejection_ready_ack,
                              owner._rejection_ready_ack_fields)
        capture = owner._rejection_ready_capture
        staged_tail(owner, capture, stage, ack, fields)
        lock_assert(owner._controller, owner._ledger, owner._before_control, owner._rejection_ready_locks_capture)
        condition_assert(owner._before_channel_condition, owner._rejection_ready_sync_capture)
        for pin in capsule[4]:
            assert_file(pin)
        for pin in capsule[5]:
            if observe_directory(pin[0]) != pin:
                fail("directory_drift")
        raw_assert(capsule[7][0], capsule[6])
        # A matching replacement database cannot acquire the original authority.
        assert_file(capsule[7])
        condition_assert(owner._before_channel_condition, owner._rejection_ready_sync_capture)
        staged_tail(owner, capture, stage, ack, fields)
        scalar_tail(owner, capsule)

    def deadlines_impl(capsule):
        if kind(capsule) is not plain_tuple or length(capsule) != 9:
            fail("capsule_invalid")
        result = capsule[8]
        if (kind(result) is not plain_tuple or length(result) != 2
                or some(kind(group) is not plain_tuple for group in result)):
            fail("capsule_invalid")
        for group in result:
            for value in group:
                scalar_deadline(value)
        return result

    def capture(owner):
        if (bootstrap.__code__ is not bootstrap_pin[0]
                or some(cell.cell_contents is not original
                        for cell, original in pairs(bootstrap.__closure__ or (), bootstrap_pin[1]))):
            message = prefix + "guard_drift"
            error = error_new(error_type, message)
            dict_set(dict_get(error_dict, error, error_type), "code", message)
            raise error
        bootstrap()
        guard()
        return capture_impl(owner)

    def compare(owner, capsule):
        if (bootstrap.__code__ is not bootstrap_pin[0]
                or some(cell.cell_contents is not original
                        for cell, original in pairs(bootstrap.__closure__ or (), bootstrap_pin[1]))):
            message = prefix + "guard_drift"
            error = error_new(error_type, message)
            dict_set(dict_get(error_dict, error, error_type), "code", message)
            raise error
        bootstrap()
        guard()
        return assert_impl(owner, capsule)

    def deadlines(capsule):
        if (bootstrap.__code__ is not bootstrap_pin[0]
                or some(cell.cell_contents is not original
                        for cell, original in pairs(bootstrap.__closure__ or (), bootstrap_pin[1]))):
            message = prefix + "guard_drift"
            error = error_new(error_type, message)
            dict_set(dict_get(error_dict, error, error_type), "code", message)
            raise error
        bootstrap()
        guard()
        return deadlines_impl(capsule)

    # Guard code/closures are independently held before their first invocation;
    # outer owner policy additionally holds all three public entry closures.
    def bootstrap():
        for function, code, captures, attributes, labels in guard_pins:
            if (function.__code__ is not code
                    or some(cell.cell_contents is not original
                            for cell, original in pairs(function.__closure__ or (), captures))):
                message = prefix + "guard_drift"
                error = error_new(error_type, message)
                dict_set(dict_get(error_dict, error, error_type), "code", message)
                raise error
            for current, expected in ((function.__dict__, attributes), (function.__annotations__, labels)):
                if (kind(current) is not plain_dict or length(current) != length(expected)
                        or some(kind(name) is not plain_str for name in current)
                        or some(current.get(name, missing) is not value for name, value in expected.items())):
                    message = prefix + "guard_drift"
                    error = error_new(error_type, message)
                    dict_set(dict_get(error_dict, error, error_type), "code", message)
                    raise error

    functions = (fail, path_parts, metadata, open_parent, check_chain, close_all, observe_absence, observe_file,
                 assert_file, observe_directory, frozen, binding, assert_binding, pin_matches_file,
                 scalar_deadline, scalar_tail, capture_impl, staged_tail, assert_impl, deadlines_impl)
    from .rsi_brs_rejection_ready_final_policy import build_rejection_ready_final_guard

    guard = build_rejection_ready_final_guard(functions, globals())
    guard_functions = (guard, *guard.__dict__["_fixed_helpers"])
    guard_pins = plain_tuple((function, function.__code__,
                              plain_tuple(cell.cell_contents for cell in function.__closure__ or ()),
                              plain_dict(function.__dict__), plain_dict(function.__annotations__))
                             for function in guard_functions)
    bootstrap_pin = (bootstrap.__code__, plain_tuple(cell.cell_contents
                                                     for cell in bootstrap.__closure__ or ()))
    return capture, compare, deadlines, (*functions, bootstrap, *guard_functions)


(capture_rejection_ready_final, assert_rejection_ready_final,
 rejection_ready_deadlines, _FINAL_FUNCTIONS) = _build_readers()
