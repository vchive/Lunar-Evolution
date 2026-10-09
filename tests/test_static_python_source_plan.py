"""The offline plan retains source assets without presenting them as a runtime."""

import hashlib
import json
import re

import pytest

from tools.static_python_fixture import recipe
from tools.static_python_fixture.recipe import emit_build_plan


def test_plan_records_exact_source_assets_and_pending_runtime(tmp_path):
    plan = emit_build_plan(tmp_path / "plan")
    manifest = json.loads((plan / "manifest.json").read_bytes())
    records = manifest["generated_source_assets"]
    assert {item["path"] for item in records} == {
        "Python/frozen.c", "Modules/config.c", "Modules/lunar-static-sources.mk",
        "Python/stdlib_module_names.h",
    }
    for item in records:
        raw = (plan / "generated-sources" / item["path"]).read_bytes()
        assert item["sha256"] == hashlib.sha256(raw).hexdigest()
        assert item["size"] == len(raw) > 0
    inputs_record = manifest["build_inputs"]
    input_bytes = (plan / inputs_record["path"]).read_bytes()
    assert inputs_record["sha256"] == hashlib.sha256(input_bytes).hexdigest()
    assert inputs_record["size"] == len(input_bytes)
    assert inputs_record["state"] == "source-reviewed-candidate-only"
    assert inputs_record["configured_closure_verified"] is False
    assert inputs_record["execution_enabled"] is False
    inputs = json.loads(input_bytes)
    frozen_source = (plan / "generated-sources/Python/frozen.c").read_text()
    headers = re.findall(r'#include "(frozen_modules/[^"]+)"', frozen_source)
    assert len(headers) == 9
    assert [item["output"] for item in inputs["freeze_tasks"]] == [
        "generated-sources/Python/" + header for header in headers
    ]
    assert not any((plan / item["output"]).exists() for item in inputs["freeze_tasks"])
    assert manifest["source_preparation_applied"] is False
    assert manifest["frozen_header_state"] == "requires-pinned-freezer"
    assert manifest["link_state"] == "not-executed"
    assert manifest["artifact_state"] == "pending-builder"
    assert manifest["startup_state"] == "not-executed"
    assert manifest["production_admission"] is False
    assert manifest["runtime_load_protection"] is False
    assert manifest["general_code_origin_protection"] is False
    assert not list(plan.rglob("*.o"))
    assert not list(plan.rglob("*.pyc"))
    assert not list(plan.rglob("importlib._bootstrap.h"))


@pytest.mark.parametrize("asset", ["pipe.c", "frozen_main.py", "lunar_fixture_profile.h", "Python/frozen.c"])
def test_plan_rejects_emitted_asset_drift_before_recording_success(tmp_path, monkeypatch, asset):
    if asset.startswith("Python/"):
        original = recipe.emit_static_python_tables

        def changed_tables():
            values = original()
            values[asset] += b"/* unreviewed table change */\n"
            return values

        monkeypatch.setattr(recipe, "emit_static_python_tables", changed_tables)
    else:
        original = recipe._assets

        def changed_assets():
            values = original()
            values[asset] += "\n# unreviewed asset change\n"
            return values

        monkeypatch.setattr(recipe, "_assets", changed_assets)
    plan = tmp_path / "plan"
    with pytest.raises(recipe.RecipeError, match="emitted source asset drift"):
        emit_build_plan(plan)
    assert not (plan / "manifest.json").exists()
    assert not (plan / "build.sh").exists()
