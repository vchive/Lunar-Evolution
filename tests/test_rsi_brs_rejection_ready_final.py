"""Pure final-reader components: real local files, no owner/ACK authority."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from lunar_evolution import rsi_brs_rejection_ready_final as final
from lunar_evolution.rsi_learning import RSILearningError

_CORE = {function.__name__: function for function in final._FINAL_FUNCTIONS}


def _file(tmp_path, raw=b"original\x00full bytes"):
    path = tmp_path / "proof ?#%月球.json"
    path.write_bytes(raw)
    path.chmod(0o400)
    return path


def test_original_bytes_and_complete_file_metadata_are_retained_readonly(tmp_path):
    path = _file(tmp_path)
    before = path.stat()
    pin = _CORE["observe_file"](str(path), 1024, True)
    assert pin[2] == (before.st_dev, before.st_ino, 0o400, 1, before.st_size,
                      before.st_mtime_ns, before.st_ctime_ns)
    assert pin[3] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert pin[4] == path.read_bytes()
    assert _CORE["assert_file"](pin) is None
    assert path.stat() == before


@pytest.mark.parametrize("fault", ["bytes", "equal-inode", "mode", "hardlink", "symlink", "missing"])
def test_original_file_never_refreshes_after_physical_drift(tmp_path, fault):
    path = _file(tmp_path)
    pin = _CORE["observe_file"](str(path), 1024, True)
    raw = path.read_bytes()
    if fault == "bytes":
        path.chmod(0o600)
        path.write_bytes(b"different bytes")
    elif fault == "equal-inode":
        path.rename(path.with_suffix(".old"))
        path.write_bytes(raw)
        path.chmod(0o400)
    elif fault == "mode":
        path.chmod(0o600)
    elif fault == "hardlink":
        os.link(path, tmp_path / "other")
    elif fault == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    else:
        path.unlink()
    with pytest.raises((RSILearningError, OSError)):
        _CORE["assert_file"](pin)


def test_original_ancestor_identity_and_nofollow_are_retained(tmp_path):
    directory = tmp_path / "parent"
    directory.mkdir()
    path = _file(directory)
    pin = _CORE["observe_file"](str(path), 1024)
    renamed = tmp_path / "renamed"
    directory.rename(renamed)
    directory.symlink_to(renamed, target_is_directory=True)
    with pytest.raises((RSILearningError, OSError)):
        _CORE["assert_file"](pin)


def test_ledger_only_pin_keeps_inode_without_freezing_mutable_sqlite_bytes(tmp_path):
    path = _file(tmp_path)
    path.chmod(0o600)
    pin = _CORE["observe_file"](str(path), 0, False, False, True)
    assert pin[2] == (path.stat().st_dev, path.stat().st_ino)
    assert pin[3:5] == (None, None)
    path.write_bytes(b"SQLite/WAL updates remain mutable; raw six-table comparison is separate")
    _CORE["assert_file"](pin)
    original = path.with_suffix(".old")
    path.rename(original)
    path.write_bytes(original.read_bytes())
    with pytest.raises(RSILearningError, match="physical_drift"):
        _CORE["assert_file"](pin)


@pytest.mark.parametrize("intermediate", [False, True])
def test_original_absence_including_missing_parent_is_held(tmp_path, intermediate):
    path = tmp_path / "absent" / "candidate" if intermediate else tmp_path / "absent"
    pin = _CORE["observe_file"](str(path), 1024, False, True)
    _CORE["assert_file"](pin)
    if intermediate:
        path.parent.mkdir()
        # Merely replacing the missing boundary with an empty directory already
        # changes the original absent-domain custody; no file adoption occurs.
    else:
        path.write_bytes(b"orphan")
    with pytest.raises(RSILearningError):
        _CORE["assert_file"](pin)


def test_directory_membership_refuses_unlisted_children(tmp_path):
    directory = tmp_path / "original"
    directory.mkdir()
    (directory / "file").write_bytes(b"x")
    pin = _CORE["observe_directory"](str(directory))
    assert pin[3] == ("file",)
    assert _CORE["observe_directory"](str(directory)) == pin
    (directory / "foreign").write_bytes(b"x")
    assert _CORE["observe_directory"](str(directory)) != pin


@pytest.mark.parametrize("limit", [True, -1, 1.0, 256 * 1024 * 1024 + 1])
def test_read_limits_require_exact_original_integer_domain(tmp_path, limit):
    with pytest.raises(RSILearningError, match="limit_invalid"):
        _CORE["observe_file"](str(_file(tmp_path)), limit)


def test_exact_limit_accepts_and_over_limit_refuses_without_truncation(tmp_path):
    path = _file(tmp_path, b"abcd")
    assert _CORE["observe_file"](str(path), 4, True)[4] == b"abcd"
    with pytest.raises(RSILearningError):
        _CORE["observe_file"](str(path), 3, True)


@pytest.mark.parametrize("path", ["relative", "/bad\x00name", "/a/../b", "/a/./b", "/a//b", "/"])
def test_lexical_refusal_precedes_io(path):
    with pytest.raises(RSILearningError, match="path_invalid"):
        _CORE["observe_file"](path, 0)


def test_file_subclasses_cannot_run_callbacks(tmp_path):
    calls = []

    class Foreign(str):
        def startswith(self, *_args):
            calls.append("startswith")
            raise AssertionError

    with pytest.raises(RSILearningError, match="path_invalid"):
        _CORE["observe_file"](Foreign(str(_file(tmp_path))), 1024)
    assert not calls


@dataclass(frozen=True, slots=True)
class _DTO:
    payload: dict


def test_nested_dto_and_primitive_changes_cannot_match_original_frozen_observation():
    value = _DTO({"values": [1, "x", b"raw"]})
    original = _CORE["frozen"](value)
    assert _CORE["frozen"](value) == original
    value.payload["values"].append(2)
    assert _CORE["frozen"](value) != original


def test_native_binding_refuses_property_replacement_before_callback(monkeypatch):
    @dataclass
    class Holder:
        payload: object

    value = Holder({"fixed": 1})
    pin = _CORE["binding"](value, "payload", True)
    calls = []

    def foreign(_self):
        calls.append("property")
        return value.__dict__["payload"]

    monkeypatch.setattr(Holder, "payload", property(foreign), raising=False)
    with pytest.raises(RSILearningError, match="declaration_drift"):
        _CORE["assert_binding"](pin)
    assert not calls


def test_native_binding_refuses_added_shadow_key():
    @dataclass
    class Holder:
        payload: object

    value = Holder({"fixed": 1})
    pin = _CORE["binding"](value, "payload", True)
    value.reader = lambda: None
    with pytest.raises(RSILearningError, match="custody_drift"):
        _CORE["assert_binding"](pin)


def test_nested_dto_instance_namespace_domain_is_frozen():
    @dataclass
    class Holder:
        payload: object

    value = Holder({"fixed": 1})
    original = _CORE["frozen"](value)
    value.shadow = True
    assert _CORE["frozen"](value) != original


@pytest.mark.parametrize("function", ["frozen", "scalar_deadline"])
def test_foreign_metaclass_equality_cannot_run_during_exact_type_checks(function):
    calls = []

    class Meta(type):
        def __eq__(cls, _other):
            calls.append("foreign equality")
            raise AssertionError("metaclass callback")

    class Foreign(metaclass=Meta):
        pass

    with pytest.raises(RSILearningError):
        _CORE[function](Foreign())
    assert not calls


def _tail(deadline):
    owner = SimpleNamespace(
        _poisoned=False, _phase="rejected-provenance", _retaining_before=False,
        _retaining_rejection=False, _retaining_rejection_provenance=False, _retaining_success=None,
        _rejection_deadline=None, _rejection_provenance_deadline=None, _success_deadline=None)
    capsule = (owner, (), None, None, (), (), (), (), ((deadline,), ()))
    owner._rejection_ready_final_capture = capsule
    return owner, capsule


def test_deadline_uses_original_absolute_value_after_delayed_read():
    owner, capsule = _tail(time.time() + 0.05)
    _CORE["scalar_tail"](owner, capsule)
    time.sleep(0.07)
    with pytest.raises(RSILearningError, match="deadline_exhausted"):
        _CORE["scalar_tail"](owner, capsule)
    assert owner._rejection_ready_final_capture is capsule


@pytest.mark.parametrize("deadline", [True, None, float("inf"), float("nan"), 0, -1, 10**1000])
def test_deadline_primitive_domain_never_accepts_nonfinite_or_bool(deadline):
    with pytest.raises(RSILearningError, match="numeric_invalid"):
        _CORE["scalar_deadline"](deadline)


def test_deadline_accessor_returns_original_tuple_without_new_allowance():
    deadlines = ((time.time() + 1,), (time.monotonic() + 1,))
    capsule = (None,) * 8 + (deadlines,)
    assert final.rejection_ready_deadlines(capsule) is deadlines


def test_raw_capture_must_not_repair_malformed_capsule():
    with pytest.raises(RSILearningError, match="capsule_invalid"):
        final.assert_rejection_ready_final(object(), ())


@pytest.mark.parametrize("field", ["_rejection_ready_stage", "_rejection_ready_ack_fields"])
def test_staged_tail_refuses_equal_reconstructed_identity_before_transport_dispatch(field):
    scope, condition = ("run", "episode"), object()
    stage = (scope, condition, (), ("run", "episode", b"payload", "d" * 64))
    fields = ("run", "episode", "d" * 64, "a" * 64)
    ack = object()
    owner = SimpleNamespace(_rejection_ready_stage=stage, _rejection_ready_ack=ack,
                            _rejection_ready_ack_fields=fields, _rejection_ready_state="inflight",
                            _rejection_ready_commit_started=False)
    original = getattr(owner, field)
    replacement = tuple(value for value in original)
    assert replacement == original and replacement is not original
    setattr(owner, field, replacement)
    capture = (None, None, condition, scope, (None, None, "a" * 64), b"payload")
    with pytest.raises(RSILearningError, match="staged_identity_drift"):
        _CORE["staged_tail"](owner, capture, stage, ack, fields)
