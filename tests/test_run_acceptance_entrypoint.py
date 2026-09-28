from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "tools" / "run_acceptance.py"


def test_help_is_available_without_importing_product_package():
    result = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--registration" in result.stdout
    assert "--campaign-parent" in result.stdout


def test_missing_pinned_loader_fails_before_child_start(tmp_path):
    result = subprocess.run(
        [
            sys.executable, str(ENTRYPOINT),
            "--registration", str(tmp_path / "registration.json"),
            "--seal", str(tmp_path / "seal.json"),
            "--checkout-root", str(tmp_path),
            "--campaign-parent", str(tmp_path / "campaigns"),
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "status": "failed", "error": "acceptance_loader_missing",
    }


def test_entrypoint_starts_fresh_pinned_loader(tmp_path):
    checkout = tmp_path / "checkout"
    loader = checkout / "src/lunar_evolution"
    loader.mkdir(parents=True)
    # A tiny stand-in makes this test independent of provider credentials and product
    # registration material while still checking argv order and fresh-process launch.
    (loader / "acceptance_pinned_loader.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'status':'completed','argv':sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    campaign_parent = tmp_path / "campaigns"
    campaign_parent.mkdir()
    result = subprocess.run(
        [
            sys.executable, str(ENTRYPOINT),
            "--registration", str(tmp_path / "registration.json"),
            "--seal", str(tmp_path / "seal.json"),
            "--checkout-root", str(checkout),
            "--campaign-parent", str(campaign_parent),
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["argv"] == [
        str(checkout), str(tmp_path / "registration.json"),
        str(tmp_path / "seal.json"), str(campaign_parent),
    ]


def test_private_env_file_reaches_isolated_child_without_entering_argv(tmp_path):
    checkout = tmp_path / "checkout"
    loader = checkout / "src/lunar_evolution"
    loader.mkdir(parents=True)
    (loader / "acceptance_pinned_loader.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'endpoint': os.environ.get('LUNAR_EVOLUTION_MODEL_ENDPOINT'), "
        "'model': os.environ.get('LUNAR_EVOLUTION_MODEL'), "
        "'key_present': os.environ.get('LUNAR_EVOLUTION_API_KEY') == 'fixture-key', "
        "'key_in_argv': any('fixture-key' in value for value in sys.argv)}))\n",
        encoding="utf-8",
    )
    config = checkout / ".env"
    config.write_text(
        "LUNAR_EVOLUTION_MODEL_ENDPOINT=https://example.invalid/v1/chat/completions\n"
        "LUNAR_EVOLUTION_MODEL=glm-5.2\n"
        "LUNAR_EVOLUTION_API_KEY=fixture-key\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    result = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--registration", str(tmp_path / "reg.json"),
         "--seal", str(tmp_path / "seal.json"), "--checkout-root", str(checkout),
         "--campaign-parent", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "endpoint": "https://example.invalid/v1/chat/completions",
        "model": "glm-5.2", "key_present": True, "key_in_argv": False,
    }


def test_env_file_rejects_insecure_or_ambiguous_credentials(tmp_path):
    checkout = tmp_path / "checkout"
    loader = checkout / "src/lunar_evolution"
    loader.mkdir(parents=True)
    (loader / "acceptance_pinned_loader.py").write_text("raise AssertionError('started')\n")
    config = checkout / ".env"
    command = [
        sys.executable, str(ENTRYPOINT), "--registration", str(tmp_path / "reg.json"),
        "--seal", str(tmp_path / "seal.json"), "--checkout-root", str(checkout),
        "--campaign-parent", str(tmp_path),
    ]
    config.write_text("LUNAR_EVOLUTION_API_KEY=fixture-key\n")
    config.chmod(0o644)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert json.loads(result.stdout) == {"status": "failed", "error": "acceptance_env_invalid"}
    assert "fixture-key" not in result.stdout + result.stderr

    config.chmod(0o600)
    config.write_text("LUNAR_EVOLUTION_API_KEY=one\nLUNAR_EVOLUTION_API_KEY=two\n")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert json.loads(result.stdout) == {"status": "failed", "error": "acceptance_env_invalid"}

    config.unlink()
    os.symlink(tmp_path / "key", config)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert json.loads(result.stdout) == {"status": "failed", "error": "acceptance_env_invalid"}
