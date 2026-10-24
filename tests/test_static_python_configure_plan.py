"""Fixed configure planning assets; never configure, compile or freeze CPython."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tools.static_python_fixture import recipe
from tools.static_python_fixture.configure_plan import emit_configure_plan_assets

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "tests/fixtures/static_python_source/Modules"
_TEMPLATES = {
    "Setup.bootstrap.in": (971, "bb401f9494c2f896aa40af6a8077ff9f22b99a9d4126ce38daef759427c8df88"),
    "Setup.stdlib.in": (8606, "700424110da7f19053e02642da6853035490726b1cec9c9ed99b1261e447caa7"),
}
_ENABLED = {
    "_abc": ["_abc.c"],
    "_codecs": ["_codecsmodule.c"],
    "_io": [
        "_io/_iomodule.c", "_io/iobase.c", "_io/fileio.c", "_io/bytesio.c",
        "_io/bufferedio.c", "_io/textio.c", "_io/stringio.c",
    ],
    "_signal": ["signalmodule.c"],
    "_thread": ["_threadmodule.c"],
    "_weakref": ["_weakref.c"],
    "atexit": ["atexitmodule.c"],
    "faulthandler": ["faulthandler.c"],
    "posix": ["posixmodule.c"],
}
_CORE = {"marshal", "_imp", "_ast", "_tokenize", "builtins", "sys", "gc", "_warnings", "_string"}
_ASSET_NAMES = {"configure-plan.json", "config.site", "Modules/Setup.local"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _template_rows(raw: bytes) -> dict[str, list[str]]:
    """Read module/source rows independently from the retained inert templates."""
    rows = {}
    for line in raw.decode("utf-8").splitlines():
        line = re.sub(r"^@[^@]+@", "", line).strip()
        if not line or line.startswith(("#", "*")):
            continue
        name, *fields = line.split()
        rows[name] = fields
    return rows


def _setup_sections(raw: bytes) -> tuple[dict[str, list[str]], list[str]]:
    enabled = {}
    disabled = []
    section = None
    for line in raw.decode("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("*"):
            assert line in {"*static*", "*disabled*"}
            section = line
            continue
        name, *sources = line.split()
        if section == "*static*":
            assert name not in enabled
            enabled[name] = sources
        else:
            assert section == "*disabled*"
            assert not sources
            disabled.append(name)
    return enabled, disabled


def test_candidate_assets_are_fresh_deterministic_planning_data() -> None:
    assets = emit_configure_plan_assets()
    assert type(assets) is dict
    assert set(assets) == _ASSET_NAMES
    assert all(type(name) is str and type(raw) is bytes and raw for name, raw in assets.items())
    assert emit_configure_plan_assets() == assets
    expected = dict(assets)
    assets["configure-plan.json"] = b"changed by caller"
    assets.clear()
    assert emit_configure_plan_assets() == expected

    plan = json.loads(expected["configure-plan.json"])
    assert plan["schema"] == "lunar-static-python-configure-candidate-v1"
    assert plan["state"] == "fixed-candidate-not-configured"
    assert plan["claims"]
    assert all(type(value) is bool and value is False for value in plan["claims"].values())
    assert plan["configure"]["build"] == "x86_64-linux-gnu"
    assert plan["configure"]["host"] == "x86_64-linux-musl"
    argv = plan["configure"]["argv"]
    assert "--without-ensurepip" in argv
    assert "--disable-shared" in argv
    assert "--disable-ipv6" in argv
    assert "--with-system-ffi=no" not in argv
    assert plan["configure"]["build_python_binding"] == "unresolved"
    assert plan["freezer"]["route"] == "same-source-direct-c-freezer"
    assert plan["environment"]["inherit"] is False


def test_setup_candidate_covers_exact_pinned_template_union_without_duplicate_core() -> None:
    assets = emit_configure_plan_assets()
    plan = json.loads(assets["configure-plan.json"])
    template_rows = {}
    expected_records = []
    for name, (size, digest) in _TEMPLATES.items():
        raw = (_FIXTURES / (name + ".source")).read_bytes()
        assert (len(raw), _sha256(raw)) == (size, digest)
        template_rows.update(_template_rows(raw))
        expected_records.append({"path": "Modules/" + name, "size": size, "sha256": digest})
    assert len(template_rows) == 103
    assert plan["module_selection"]["template_inputs"] == expected_records

    enabled, disabled = _setup_sections(assets["Modules/Setup.local"])
    assert enabled == _ENABLED
    assert {name: template_rows[name] for name in enabled} == _ENABLED
    assert len(disabled) == len(set(disabled)) == 94
    assert set(enabled).isdisjoint(disabled)
    assert set(enabled) | set(disabled) == set(template_rows)
    assert not (set(enabled) | set(disabled)) & _CORE
    assert "_lunar_fixture_pipe" not in enabled
    assert "_lunar_fixture_pipe" not in disabled
    selection = plan["module_selection"]
    assert len(selection["enabled_upstream"]) == 9
    assert {item["name"]: item["sources"] for item in selection["enabled_upstream"]} == _ENABLED
    assert selection["disabled"] == sorted(disabled)


def test_candidate_cache_contains_only_explicit_feature_disable_policies() -> None:
    assets = emit_configure_plan_assets()
    site = assets["config.site"].decode("utf-8")
    assignments = {}
    for line in site.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, value = line.split("=", 1)
            assert name not in assignments
            assignments[name] = value
    assert assignments == {
        "ac_cv_func_dlopen": "no",
        "ac_cv_file__dev_ptmx": "no",
        "ac_cv_file__dev_ptc": "no",
    }
    assert json.loads(assets["configure-plan.json"])["cache"]["policies"] == assignments


def test_ambient_build_variables_cannot_change_candidate_assets(monkeypatch) -> None:
    expected = emit_configure_plan_assets()
    for name in (
        "PATH", "CC", "CXX", "AR", "RANLIB", "CFLAGS", "CPPFLAGS", "LDFLAGS",
        "CONFIG_SITE", "PKG_CONFIG", "PKG_CONFIG_PATH", "PYTHONPATH", "PYTHONHOME",
        "ac_cv_func_dlopen", "ac_cv_file__dev_ptmx", "ac_cv_file__dev_ptc",
        "ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR", "LUNAR_STATIC_EXECUTE",
    ):
        monkeypatch.setenv(name, "host-selected-unreviewed-value")
    assert emit_configure_plan_assets() == expected


def test_build_plan_records_actual_candidate_asset_hashes_and_keeps_execution_disabled(tmp_path) -> None:
    destination = recipe.emit_build_plan(tmp_path / "plan")
    manifest = json.loads((destination / "manifest.json").read_bytes())
    candidate = manifest["configuration_candidate"]
    assert candidate["state"] == "fixed-candidate-not-configured"
    assert candidate["execution_enabled"] is False
    assert {item["path"] for item in candidate["assets"]} == {
        "configure-plan/" + name for name in _ASSET_NAMES
    }
    assert len(candidate["assets"]) == 3
    for record in candidate["assets"]:
        raw = (destination / record["path"]).read_bytes()
        assert record["size"] == len(raw) > 0
        assert record["sha256"] == _sha256(raw)
        assert raw == emit_configure_plan_assets()[record["path"].removeprefix("configure-plan/")]
    plan = json.loads((destination / "configure-plan/configure-plan.json").read_bytes())
    assert manifest["build_environment"]["CONFIG_SITE"] == plan["environment"]["values"]["CONFIG_SITE"]
    assert manifest["build_environment"]["CONFIG_SITE"] == "configure-plan/config.site"
    assert manifest["artifact_state"] == "pending-builder"
    assert manifest["startup_state"] == "not-executed"
    assert manifest["production_admission"] is False


@pytest.mark.parametrize("asset", sorted(_ASSET_NAMES))
def test_written_candidate_drift_refuses_before_publishing_manifest_or_entry_points(
    tmp_path, monkeypatch, asset,
) -> None:
    destination = tmp_path / "plan"
    target = destination / "configure-plan" / asset
    original = Path.write_bytes

    def changed_write(path, raw):
        if path == target:
            raw += b"\n# unreviewed write drift\n"
        return original(path, raw)

    monkeypatch.setattr(Path, "write_bytes", changed_write)
    with pytest.raises(recipe.RecipeError):
        recipe.emit_build_plan(destination)
    assert target.is_file()
    for name in ("manifest.json", "build.sh", "linux-build-commands.sh"):
        assert not (destination / name).exists()


@pytest.mark.parametrize("explicit_opt_in", [False, True])
def test_candidate_assets_do_not_enable_either_build_entry_point(tmp_path, explicit_opt_in) -> None:
    destination = recipe.emit_build_plan(tmp_path / "plan")
    environment = {"PATH": os.defpath}
    if explicit_opt_in:
        environment["LUNAR_STATIC_EXECUTE"] = "1"
    for entry_point in ("build.sh", "linux-build-commands.sh"):
        result = subprocess.run(
            ["/bin/sh", str(destination / entry_point)], cwd=tmp_path, env=environment,
            capture_output=True, timeout=5, check=False,
        )
        assert result.returncode == 78
        assert b"PLAN ONLY" in result.stderr
    assert sorted(path.name for path in tmp_path.iterdir()) == ["plan"]
