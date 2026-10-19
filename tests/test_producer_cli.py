"""CLI options and detached forwarding for external producer warm starts."""

import json
import shlex
import sys
from pathlib import Path

import pytest
from test_cli import _write_evolution_commands, _write_evolution_contract
from test_producer_handoff import _envelope, _material

from lunar_evolution import cli
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.producer_handoff import ProducerResultEnvelope

PRODUCER_SHA = "b" * 64


def _inputs(tmp_path):
    contract_path = tmp_path / "contract.json"
    _write_evolution_contract(contract_path, max_rounds=1)
    contract = AlgorithmProblemContract.from_dict(json.loads(contract_path.read_bytes()))
    root = tmp_path / "producer result"
    root.mkdir()
    material = _material(root, "best/main.py", "def solve():\n    return 9\n")
    _envelope(root, contract, [material], producer_fingerprint=PRODUCER_SHA)
    generator, evaluator = _write_evolution_commands(tmp_path)
    return contract_path, root, [
        "--generator-command", shlex.join((sys.executable, str(generator))),
        "--evaluator-command", shlex.join((sys.executable, str(evaluator))),
        "--population-size", "1", "--home", str(tmp_path / "home"), "--json",
    ]


def test_export_dispatches_without_initializing_or_running_anything(tmp_path, monkeypatch, capsys):
    from lunar_evolution import shinka_handoff

    contract_path, root, _ = _inputs(tmp_path)
    envelope = ProducerResultEnvelope.from_dict(json.loads((root / "producer-result.json").read_bytes()))
    calls = []
    def export(*args, **kwargs):
        calls.append((args, kwargs))
        return envelope
    def forbidden(*args, **kwargs):
        pytest.fail("export initialized storage or called a process")
    monkeypatch.setattr(shinka_handoff, "export_shinka_result", export)
    monkeypatch.setattr(cli, "_config", forbidden)
    monkeypatch.setattr(cli.subprocess, "Popen", forbidden)
    assert cli.main([
        "export-shinka-result", str(root), "--output", str(tmp_path / "export"),
        "--contract", str(contract_path), "--producer-fingerprint", PRODUCER_SHA,
        "--program-id", "first", "--program-id", "second", "--producer-run-id", "run-1", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "exported"
    assert payload["evidence_scope"] == "retained_local_material"
    assert payload["solver_execution"] == "retained_result_export"
    assert payload["production_admission"] is False
    assert payload["material_count"] == 1
    assert payload["envelope_sha256"] == envelope.envelope_sha256
    assert "score" not in payload and "admitted" not in payload
    assert calls[0][1]["program_ids"] == ["first", "second"]
    assert calls[0][1]["top_k"] is None
    assert calls[0][1]["producer_run_id"] == "run-1"
    assert calls[0][1]["contract_sha256"] == envelope.contract_sha256
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("options", [[], ["--top-k", "2"]])
def test_export_preserves_convenience_selection_default(tmp_path, monkeypatch, capsys, options):
    from lunar_evolution import shinka_handoff

    contract_path, root, _ = _inputs(tmp_path)
    envelope = ProducerResultEnvelope.from_dict(json.loads((root / "producer-result.json").read_bytes()))
    calls = []
    def export(*args, **kwargs):
        calls.append(kwargs)
        return envelope
    monkeypatch.setattr(shinka_handoff, "export_shinka_result", export)
    assert cli.main(["export-shinka-result", str(root), "--output", str(tmp_path / "export"),
                     "--contract", str(contract_path), "--producer-fingerprint", PRODUCER_SHA, "--json", *options]) == 0
    assert calls[0]["program_ids"] is None
    assert calls[0]["top_k"] == (2 if options else None)
    capsys.readouterr()


@pytest.mark.parametrize("kind", ["duplicate", "invalid", "oversized", "symlink"])
def test_export_bad_contract_has_fixed_error_and_no_output(tmp_path, monkeypatch, capsys, kind):
    path = tmp_path / "contract.json"
    if kind == "duplicate":
        path.write_bytes(b'{"secret":"sk-private", "secret":"other"}')
    elif kind == "oversized":
        path.write_bytes(b" " * (64 * 1024 + 1))
    elif kind == "symlink":
        target = tmp_path / "original.json"
        _write_evolution_contract(target)
        path.symlink_to(target)
    else:
        path.write_bytes(b'{"secret":"sk-private"}')
    def forbidden(*args):
        pytest.fail("export initialized normal storage")
    monkeypatch.setattr(cli, "_config", forbidden)
    output = tmp_path / "export"
    assert cli.main(["export-shinka-result", str(tmp_path), "--output", str(output), "--contract", str(path),
                     "--producer-fingerprint", PRODUCER_SHA, "--json"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "producer_export_contract_invalid"}
    assert not output.exists()


def test_exporter_fixed_failure_is_returned_as_json(tmp_path, capsys):
    path = tmp_path / "contract.json"
    _write_evolution_contract(path)
    output = tmp_path / "export"
    assert cli.main(["export-shinka-result", str(tmp_path), "--output", str(output), "--contract", str(path),
                     "--producer-fingerprint", PRODUCER_SHA, "--json"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "shinka_database_missing"}
    assert not output.exists()


@pytest.mark.parametrize("arguments", [
    ["evolve", "contract.json", "--producer-result", "root", "--seed-manifest", "seeds.json"],
    ["export-shinka-result", "root", "--output", "export", "--contract", "contract.json",
     "--producer-fingerprint", PRODUCER_SHA, "--program-id", "first", "--top-k", "1"],
])
def test_mutually_exclusive_sources_and_selection_are_rejected(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(arguments)
    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("options,match", [
    (["--producer-fingerprint", PRODUCER_SHA], "require --producer-result"),
    (["--producer-id", "shinka"], "require --producer-result"),
    (["--producer-result", "unused"], "requires --producer-fingerprint"),
    (["--producer-result", "unused", "--producer-fingerprint", PRODUCER_SHA, "--strategy", "openevolve"], "only by the population"),
    (["--producer-result", "unused", "--producer-fingerprint", PRODUCER_SHA, "--seed-dependency-sha256", "d" * 64], "cannot be combined"),
    (["--producer-result", "unused", "--producer-fingerprint", PRODUCER_SHA, "--seed-environment-sha256", "e" * 64], "cannot be combined"),
])
def test_producer_options_reject_ambiguous_pins(tmp_path, capsys, options, match):
    path = tmp_path / "contract.json"
    _write_evolution_contract(path)
    workspace = tmp_path / "workspace"
    assert cli.main(["evolve", str(path), "--workspace", str(workspace), "--home", str(tmp_path / "home"), "--json", *options]) == 2
    assert match in json.loads(capsys.readouterr().err)["error"]
    assert not workspace.exists()


def test_producer_requires_command_backed_exact_evaluator(tmp_path, capsys):
    path = tmp_path / "contract.json"
    _write_evolution_contract(path)
    assert cli.main(["evolve", str(path), "--producer-result", str(tmp_path), "--producer-fingerprint", PRODUCER_SHA,
                     "--agent-runtime", "mock", "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "requires --evaluator-command" in json.loads(capsys.readouterr().err)["error"]


def test_duplicate_producer_identity_has_fixed_error_before_run_or_commands(tmp_path, monkeypatch, capsys):
    contract_path, root, options = _inputs(tmp_path)
    envelope_path = root / "producer-result.json"
    envelope = json.loads(envelope_path.read_bytes())
    source = (root / envelope["materials"][0]["path"]).read_text(encoding="utf-8")
    envelope["materials"].append(_material(root, "duplicate/main.py", source))
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("duplicate producer identity created a run or executed a command")

    monkeypatch.setattr(cli.LocalController, "create_evolution_run", forbidden)
    monkeypatch.setattr(cli.subprocess, "Popen", forbidden)
    assert cli.main([
        "evolve", str(contract_path), "--producer-result", str(root),
        "--producer-fingerprint", PRODUCER_SHA, *options,
    ]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "duplicate_identity"}


def test_detach_forwards_producer_options_without_synthetic_seed_flags(tmp_path, monkeypatch, capsys):
    contract_path, root, options = _inputs(tmp_path)
    calls = []
    class Process:
        pid = None
    def spawn(command, **kwargs):
        calls.append(command)
        return Process()
    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    assert cli.main(["evolve", str(contract_path), "--producer-result", str(root), "--producer-fingerprint", PRODUCER_SHA,
                     "--producer-id", "shinka", "--detach", *options]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["detached"] is True
    command = calls[0]
    parsed = cli.build_parser().parse_args(command[3:])
    assert parsed.producer_result == root.absolute()
    assert parsed.producer_fingerprint == PRODUCER_SHA
    assert parsed.producer_id == "shinka"
    assert parsed.resume and parsed.run_id == payload["run_id"]
    assert parsed.seed_manifest is None and parsed.seed_dependency_sha256 is None
    assert parsed.seed_environment_sha256 is None
    assert not (Path(payload["workspace"]) / "evolution/seed-commit.json").exists()
    # A normal child resume must be able to reconstruct the same seed manifest.
    monkeypatch.undo()
    assert cli.main(command[3:]) == 0
    finished = json.loads(capsys.readouterr().out)
    assert finished["run_id"] == payload["run_id"]
    assert finished["best_score"] == 9.0
