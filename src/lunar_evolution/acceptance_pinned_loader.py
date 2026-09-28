"""Standard-library-only import boundary for a fresh registered acceptance process."""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path


class PinnedSourceError(ValueError):
    """A fixed-code source binding failure."""


def _read(path: Path) -> bytes:
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise PinnedSourceError("acceptance_code_symlink")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > 8 * 1024 * 1024:
            raise PinnedSourceError("acceptance_code_file_invalid")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        after = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns,
                                 s.st_ctime_ns, s.st_nlink, s.st_mode)
        if fingerprint(before) != fingerprint(after) or fingerprint(after) != fingerprint(named):
            raise PinnedSourceError("acceptance_code_changed")
        return raw
    finally:
        os.close(fd)


def read_pinned_sources(checkout: Path, registration: dict) -> dict[str, tuple[Path, bytes, bool]]:
    """Snapshot all package source bytes; reject incomplete inventories and stale pyc."""
    checkout = checkout.absolute()
    package = checkout / "src/lunar_evolution"
    pins = {item["path"]: item for item in registration["product_files"]}
    paths = {p.relative_to(checkout).as_posix() for p in package.rglob("*.py")
             if "__pycache__" not in p.parts}
    registered = {p for p in pins if p.startswith("src/lunar_evolution/") and p.endswith(".py")}
    if not paths or paths != registered or "src/lunar_evolution/__init__.py" not in paths:
        raise PinnedSourceError("acceptance_code_inventory_mismatch")
    sources = {}
    for relative in sorted(paths):
        path = checkout / relative
        raw = _read(path)
        pin = pins[relative]
        if len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise PinnedSourceError("acceptance_code_digest_mismatch")
        pieces = Path(relative).with_suffix("").parts[1:]
        is_package = pieces[-1] == "__init__"
        name = ".".join(pieces[:-1] if is_package else pieces)
        sources[name] = (path, raw, is_package)
    return sources


class _PinnedLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, sources):
        self.sources = sources

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "lunar_evolution" and not fullname.startswith("lunar_evolution."):
            return None
        if fullname not in self.sources:
            raise PinnedSourceError("acceptance_import_not_registered")
        file, _raw, package = self.sources[fullname]
        return importlib.util.spec_from_file_location(
            fullname, file, loader=self,
            submodule_search_locations=[str(file.parent)] if package else None,
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw, _package = self.sources[module.__name__]
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)  # noqa: S102


def main() -> int:
    # The launcher passes only paths and a digest; credentials stay in the environment.
    checkout, registration_path, seal_path, campaign_parent = map(Path, sys.argv[1:5])
    try:
        registration = json.loads(_read(registration_path))
        sources = read_pinned_sources(checkout, registration)
        if any(name == "lunar_evolution" or name.startswith("lunar_evolution.") for name in sys.modules):
            raise PinnedSourceError("acceptance_package_already_loaded")
        sys.meta_path.insert(0, _PinnedLoader(sources))
        from lunar_evolution.acceptance_native_runner import _run_registered_acceptance

        result = _run_registered_acceptance(
            registration_path, seal_path, checkout_root=checkout, campaign_parent=campaign_parent,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "completed" else 1
    except Exception:  # noqa: BLE001 - redact all isolated-boundary failures
        # Provider/configuration exception text may contain credentials or private response data.
        print(json.dumps({"status": "failed", "error": "acceptance_isolated_runner_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
