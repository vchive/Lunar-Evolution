"""Private local subprocess fixtures, never an SSH host or evaluator."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from lunar_evolution.external_worker_assignment import ExternalWorkerAssignments
from lunar_evolution.external_worker_origin import WorkerOriginKey, WorkerOriginRegistry
from lunar_evolution.external_worker_transport import SSHWorkerConfig, SSHWorkerTransport
from lunar_evolution.external_worker_wrapper import worker_json
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_store import RSILedger

PLAN = "a" * 64
PROFILE = "e" * 64
SECRET = b"local-worker-fixture-private-secret-123456789"
RECEIPT = b'{"trusted_launcher":"local fixture receipt"}\n'


def write_private(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def worker_harness(tmp_path, *, producer_code=None, drop=False, budget=None):
    root = tmp_path.resolve()
    state = root / "private-state"
    state.mkdir(mode=0o700)
    key_file = root / "worker.key"
    write_private(key_file, SECRET)
    marker = root / "producer-calls.jsonl"
    producer = root / "trusted producer.py"
    producer.write_text(producer_code if producer_code is not None else (
        "import json,os,sys,time\n"
        "raw=sys.stdin.buffer.read()\n"
        f"with open({str(marker)!r},'a') as stream:\n"
        " stream.write(json.dumps({'stdin':raw.decode(),'environment':dict(os.environ),'argv':sys.argv})+'\\n')\n"
        " stream.flush()\n"
        "time.sleep(0.05)\n"
        f"sys.stdout.buffer.write({RECEIPT!r})\n"
    ))
    wrapper_config = root / "worker config ; safe.json"
    config_value = {
        "schema_version": "lunar-external-worker-wrapper-v1", "worker_id": "worker-local",
        "host_id": "host-local", "host_boot_id": "boot-local", "key_id": "key-local",
        "profile_sha256": PROFILE, "key_file": str(key_file), "state_directory": str(state),
        "producer_argv": [sys.executable, str(producer)], "allowed_controllers": ["controller-local"],
        "maximum_runtime_seconds": 30,
    }
    write_private(wrapper_config, worker_json(config_value))
    source = Path(__file__).resolve().parents[1] / "src"
    wrapper_argv = (sys.executable, "-c",
                    (f"import runpy,sys;sys.path.insert(0,{str(source)!r});"
                     "runpy.run_module('lunar_evolution.external_worker_wrapper',run_name='__main__')"),
                    "--config", str(wrapper_config))
    ssh_marker = root / "ssh-calls.jsonl"
    ssh = root / "local-ssh-fixture"
    ssh.write_text(
        f"#!{sys.executable}\n"
        "import json,os,shlex,subprocess,sys\n"
        "raw=sys.stdin.buffer.read()\n"
        f"with open({str(ssh_marker)!r},'a') as stream:\n"
        " stream.write(json.dumps({'argv':sys.argv,'wire':raw.decode(),'environment':dict(os.environ)})+'\\n')\n"
        "result=subprocess.run(shlex.split(sys.argv[-1]),input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE)\n"
        f"if {drop!r} and json.loads(raw)['action']=='run':\n"
        " sys.exit(17)\n"
        "sys.stdout.buffer.write(result.stdout)\n"
        "sys.exit(result.returncode)\n"
    )
    ssh.chmod(0o700)
    request = SolverRequest.build(
        episode_id="external-worker-local-episode", contract_sha256="1" * 64,
        evaluator_sha256="2" * 64, environment_sha256="3" * 64,
        memory_snapshot_sha256="4" * 64, solver_id="local-fixture",
        solver_settings={"iterations": 1},
        budget={"wall_timeout_seconds": 30, "deadline_unix": time.time() + 30} if budget is None else budget,
        practice_charter={"goal": "local trusted launcher fixture"},
    )
    ledger = RSILedger(root / "rsi.sqlite3")
    key = WorkerOriginKey("worker-local", "host-local", "boot-local", "key-local", SECRET)
    registry = WorkerOriginRegistry([key])
    book = ExternalWorkerAssignments(ledger, controller_id="controller-local", run_id="run-local",
                                     task_id="task-local", registry=registry)
    with ledger.controller_lock("run-local"):
        checkpoint = ledger.write_controller_checkpoint("run-local", {"fixture": "original"},
                                                        expected_sha256=None)
        claim = ledger.claim_native_episode(request, plan_sha256=PLAN, controller_run_id="run-local",
                                             expected_controller_checkpoint_sha256=checkpoint)
        assignment = book.reserve_assignment(request, plan_sha256=PLAN, profile_sha256=PROFILE,
                    worker=key, expected_native_claim=claim,
                    expected_controller_checkpoint_sha256=checkpoint)
    config = SSHWorkerConfig(str(ssh), "fixture-host", wrapper_argv, key.worker_id)
    return SimpleNamespace(root=root, state=state, key_file=key_file, config_file=wrapper_config,
        config_value=config_value, producer=producer, marker=marker, ssh_marker=ssh_marker,
        wrapper_argv=wrapper_argv, request=request, ledger=ledger, book=book, key=key,
        checkpoint=checkpoint, claim=claim, assignment=assignment, config=config,
        transport=SSHWorkerTransport(book, config))


def invocation(h, *, action="run"):
    original = dict(h.request.budget)
    return {"schema_version": "lunar-external-worker-channel-v1", "action": action,
            "context": h.assignment["context"], "request": h.request.to_dict(),
            "request_sha256": h.request.digest(), "profile_sha256": PROFILE,
            "timeout_seconds": min(20, original["wall_timeout_seconds"]),
            "deadline_unix": min(time.time() + 20, original["deadline_unix"]),
            **{name: getattr(h.key, name) for name in ("worker_id", "host_id", "host_boot_id", "key_id")}}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_no_native_authority(h, result=None):
    assert h.ledger.episode_result(h.request.episode_id) is None
    assert h.ledger.inspect_native_episode_claim(h.request, plan_sha256=PLAN) == h.claim
    if result is not None:
        assert result["native_success"] is False
        assert result["remote_cleanup_verified"] is False
        assert result["publication_authority"] is False
