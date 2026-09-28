"""The acceptance process executes registered source bytes, never installed/pyc bytes."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.acceptance_pinned_loader import PinnedSourceError, read_pinned_sources


def _tree(tmp_path: Path):
    root = tmp_path / "src/lunar_evolution"
    root.mkdir(parents=True)
    files = {"__init__.py": b"", "runner.py": b"VALUE = 3\n"}
    pins = []
    for name, raw in files.items():
        p = root / name
        p.write_bytes(raw)
        pins.append({"path": str(p.relative_to(tmp_path)), "size": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    return root, {"product_files": pins}


def test_loads_exact_registered_source_bytes(tmp_path):
    _root, registration = _tree(tmp_path)
    sources = read_pinned_sources(tmp_path, registration)
    assert sources["lunar_evolution.runner"][1] == b"VALUE = 3\n"


@pytest.mark.parametrize("drift", ["changed", "missing_pin", "extra", "symlink", "hardlink"])
def test_rejects_source_inventory_or_byte_drift(tmp_path, drift):
    root, registration = _tree(tmp_path)
    path = root / "runner.py"
    if drift == "changed":
        path.write_bytes(b"VALUE = 4\n")
    elif drift == "missing_pin":
        registration["product_files"].pop()
    elif drift == "extra":
        (root / "unregistered.py").write_text("pass\n")
    else:
        path.rename(root / "outside.txt")
        if drift == "symlink":
            path.symlink_to(root / "outside.txt")
        else:
            path.hardlink_to(root / "outside.txt")
    with pytest.raises(PinnedSourceError):
        read_pinned_sources(tmp_path, registration)
