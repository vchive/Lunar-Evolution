"""The offline plan retains source assets without presenting them as a runtime."""

import hashlib
import json

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
