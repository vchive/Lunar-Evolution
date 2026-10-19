"""CLI coverage for detached static-Python build probe inspection."""

from __future__ import annotations

import hashlib
import json

from lunar_evolution.cli import main
from lunar_evolution.static_python_build_probe import BUILD_PROBE_SCHEMA


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _receipt() -> dict[str, object]:
    return {
        "schema": BUILD_PROBE_SCHEMA,
        "probe_id": "cp313-core-static-20261019",
        "source_archive_sha256": _sha("archive"),
        "source_tree_sha256": _sha("tree"),
        "toolchain_manifest_sha256": _sha("toolchain"),
        "recipe_sha256": _sha("recipe"),
        "build": {
            "configure_status": "succeeded",
            "target_status": "succeeded",
            "target": "python",
            "optional_module_closure": "open",
            "blocker": None,
        },
        "artifact": {
            "present": True,
            "sha256": _sha("image"),
            "size": 26673400,
            "elf": {
                "class": 64,
                "byte_order": "little",
                "type": "ET_EXEC",
                "machine": "x86_64",
                "program_headers": 9,
                "section_headers": 26,
                "pt_interp": False,
                "dt_needed": False,
                "dynamic_section": False,
            },
        },
        "runtime": {
            "attempted": True,
            "status": "failed",
            "exit_code": 1,
            "failure": "encodings_not_found",
        },
        "claims": {
            "build_acceptance": False,
            "runtime_execution": False,
            "sealed_runtime": False,
            "production_admission": False,
        },
    }


def test_inspect_build_probe_emits_detached_observation(tmp_path, capsys):
    receipt_path = tmp_path / "probe.json"
    raw = json.dumps(_receipt(), sort_keys=True, separators=(",", ":")).encode()
    receipt_path.write_bytes(raw)

    assert main(["inspect-static-python-build-probe", str(receipt_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "observed"
    assert payload["probe_id"] == "cp313-core-static-20261019"
    assert payload["runtime_status"] == "failed"
    assert payload["production_admission"] is False
    assert payload["receipt_sha256"] == hashlib.sha256(raw).hexdigest()


def test_inspect_build_probe_rejects_malformed_receipt_without_initializing_home(tmp_path, capsys):
    receipt_path = tmp_path / "probe.json"
    receipt_path.write_text("{}", encoding="utf-8")

    assert main(["inspect-static-python-build-probe", str(receipt_path), "--json"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "static_python_build_probe_schema"}
    assert not (tmp_path / ".lunar-evolution").exists()
