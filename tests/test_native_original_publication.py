"""Actual publication-FD retention, without cgroup or credential acceptance."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pickle
from pathlib import Path

import pytest

from lunar_evolution.native_deadline_binding import persist_native_deadline_binding
from lunar_evolution.native_original_publication import (
    NativeOriginalPublicationError,
    NativeOriginalPublications,
    hold_native_original_publications,
)
from lunar_evolution.producer_process import _atomic_json

_NAMES = {"registration": "process-registration.json", "handoff": "trusted-bootstrap-handoff.json",
          "deadline": "native-trusted-attempt-deadline.json"}


def _deadline():
    record = {"schema_version": "1", "deadline_monotonic": 456.0}
    record["deadline_sha256"] = hashlib.sha256(json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return record


def _publish(owner, directory):
    for role in ("registration", "handoff"):
        _atomic_json(directory / _NAMES[role], {"role": role}, exclusive=True,
                     retain_creation_owner=owner._slot(role))
    persist_native_deadline_binding(directory, record=_deadline(),
                                    retain_creation_owner=owner._slot("deadline"))


def test_original_creator_descriptors_remain_readable_and_close_with_owner(tmp_path):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, pins = owner._borrow_for_native_transfer()
        assert len(descriptors) == len(set(descriptors)) == 3
        for descriptor, pin in zip(descriptors, pins, strict=True):
            assert os.pread(descriptor, 65537, 0)
            assert hashlib.sha256(os.pread(descriptor, 65537, 0)).hexdigest() == pin[0]
            assert (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) == pin[2:4]
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_retention_does_not_reopen_published_name(tmp_path, monkeypatch):
    original_open = os.open

    def open_created_only(name, flags, *args, **kwargs):
        if Path(name).name in {"process-registration.json", "trusted-bootstrap-handoff.json"}:
            pytest.fail("retention reopened a publication instead of duplicating its creator FD")
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_created_only)
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        assert len(owner._borrow_for_native_transfer()[0]) == 3


@pytest.mark.parametrize("role", ["registration", "handoff", "deadline"])
def test_same_bytes_in_replaced_inode_refuse_original_consumption(tmp_path, role):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        path = tmp_path / _NAMES[role]
        raw = path.read_bytes()
        replacement = tmp_path / "replacement"
        replacement.write_bytes(raw)
        replacement.chmod(0o600)
        replacement.replace(path)
        with pytest.raises(NativeOriginalPublicationError):
            owner._borrow_for_native_transfer()


def test_missing_original_role_cannot_be_reconstructed_from_existing_path(tmp_path):
    _atomic_json(tmp_path / "process-registration.json", {"role": "registration"})
    with hold_native_original_publications() as owner, pytest.raises(NativeOriginalPublicationError):
        owner._borrow_for_native_transfer()


def test_publication_slot_is_one_shot(tmp_path):
    with hold_native_original_publications() as owner:
        slot = owner._slot("registration")
        _atomic_json(tmp_path / "process-registration.json", {"value": 1}, retain_creation_owner=slot)
        with pytest.raises(NativeOriginalPublicationError):
            _atomic_json(tmp_path / "second", {"value": 1}, retain_creation_owner=slot)
        assert not (tmp_path / "second").exists()


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy, pickle.dumps])
@pytest.mark.parametrize("slot", [False, True])
def test_live_owner_and_slots_cannot_be_copied_or_serialized(clone, slot):
    with hold_native_original_publications() as owner, pytest.raises(NativeOriginalPublicationError):
        clone(owner._slot("deadline") if slot else owner)


def test_owner_cannot_be_constructed_from_caller_fds_or_saved_pins():
    with pytest.raises(NativeOriginalPublicationError):
        NativeOriginalPublications(object())


@pytest.mark.parametrize("publisher", ["json", "deadline"])
def test_invalid_creation_owner_refuses_before_publication(tmp_path, publisher):
    with pytest.raises(NativeOriginalPublicationError):
        if publisher == "json":
            _atomic_json(tmp_path / "invalid", {"value": 1}, retain_creation_owner=object())
        else:
            persist_native_deadline_binding(tmp_path, record=_deadline(), retain_creation_owner=object())
    assert list(tmp_path.iterdir()) == []


def test_default_publication_return_and_optional_identity_remain_unchanged(tmp_path):
    assert _atomic_json(tmp_path / "old", {"value": 1}) is None
    pin = _atomic_json(tmp_path / "pin", {"value": 2}, capture_identity=True)
    assert len(pin) == 6
    with hold_native_original_publications() as owner:
        pin = _atomic_json(tmp_path / "process-registration.json", {"value": 3}, capture_identity=True,
                           retain_creation_owner=owner._slot("registration"))
        assert len(pin) == 6


def test_pread_consumer_does_not_change_creator_stream_offset(tmp_path):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, _ = owner._borrow_for_native_transfer()
        before = [os.lseek(fd, 0, os.SEEK_CUR) for fd in descriptors]
        owner._borrow_for_native_transfer()
        assert [os.lseek(fd, 0, os.SEEK_CUR) for fd in descriptors] == before


@pytest.mark.parametrize("role,wrong", [
    ("registration", "handoff"), ("handoff", "registration"), ("deadline", "registration"),
])
def test_wrong_role_refuses_before_real_publisher_creates_any_file(tmp_path, role, wrong):
    with hold_native_original_publications() as owner:
        with pytest.raises(NativeOriginalPublicationError):
            if role == "deadline":
                persist_native_deadline_binding(tmp_path, record=_deadline(),
                                                retain_creation_owner=owner._slot(wrong))
            else:
                _atomic_json(tmp_path / _NAMES[role], {"role": role},
                             retain_creation_owner=owner._slot(wrong))
        assert list(tmp_path.iterdir()) == []


def test_in_place_mutation_of_original_inode_refuses(tmp_path):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        (tmp_path / _NAMES["registration"]).write_bytes(b'{"role":"mutated"}')
        with pytest.raises(NativeOriginalPublicationError):
            owner._borrow_for_native_transfer()


def test_close_failure_retires_numbers_and_still_closes_other_originals(tmp_path, monkeypatch):
    original_close = os.close
    owner = None
    attempted = []
    with pytest.raises(OSError, match="injected close uncertainty"):  # noqa: SIM117
        with hold_native_original_publications() as owner:
            _publish(owner, tmp_path)
            descriptors, _ = owner._borrow_for_native_transfer()
            all_fds = [fd for entry in owner._entries.values() for fd in entry[:2]]
            selected = descriptors[0]

            def close_once(fd):
                if fd in all_fds:
                    attempted.append(fd)
                original_close(fd)
                if fd == selected:
                    raise OSError("injected close uncertainty")

            monkeypatch.setattr(os, "close", close_once)
    assert sorted(attempted) == sorted(all_fds)
    owner.close()
    assert sorted(attempted) == sorted(all_fds)


def test_cleanup_close_uncertainty_preserves_original_operation_failure(tmp_path, monkeypatch):
    original_close = os.close
    with pytest.raises(RuntimeError, match="original operation failure"):  # noqa: SIM117
        with hold_native_original_publications() as owner:
            _publish(owner, tmp_path)
            descriptors, _ = owner._borrow_for_native_transfer()

            def close_with_failure(fd):
                original_close(fd)
                if fd == descriptors[0]:
                    raise OSError("later cleanup failure")

            monkeypatch.setattr(os, "close", close_with_failure)
            raise RuntimeError("original operation failure")


def test_close_does_not_close_a_known_reused_descriptor(tmp_path, monkeypatch):
    original_close = os.close
    selected = replacement = -1
    closed = []
    try:
        with pytest.raises(NativeOriginalPublicationError):  # noqa: SIM117
            with hold_native_original_publications() as owner:
                _publish(owner, tmp_path)
                selected = owner._borrow_for_native_transfer()[0][0]
                foreign = tmp_path / "foreign"
                foreign.write_bytes(b"not an original publication")
                replacement = os.open(foreign, os.O_RDONLY)
                original_close(selected)
                os.dup2(replacement, selected)

                def close_recorded(fd):
                    closed.append(fd)
                    original_close(fd)

                monkeypatch.setattr(os, "close", close_recorded)
        assert selected not in closed
        assert os.pread(selected, 100, 0) == b"not an original publication"
    finally:
        if selected >= 0:
            original_close(selected)
        if replacement >= 0:
            original_close(replacement)
