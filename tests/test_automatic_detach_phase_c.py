"""Real automatic background workers against an offline loopback model fixture."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score
from test_conversational_automatic_bundle import SNAPSHOT_SOURCE, _suite

from lunar_evolution.automatic_solve_lifecycle import own_automatic_solve
from lunar_evolution.store import Store

FAKE_KEY = "phase-c-offline-fixture-key"
ROOT = Path(__file__).resolve().parents[1]


def _wait(predicate, *, seconds=30, diagnostic=lambda: "condition did not become true"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    pytest.fail(str(diagnostic()))


def _alive(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, timeout=3,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.lstrip().startswith("Z")


class OfflineAutomaticCase:
    def __init__(self, root, *, clarify=False, fail_preparation=False,
                 block_contract=False, block_candidate=False):
        self.root = root
        self.workspace = root / "conversation"
        self.home = root / "home"
        context = build_context(root)
        self.contract = context.contract.to_dict()
        self.contract["hard_constraints"] = [{
            "id": "out_of_bounds",
            "description": "The selected integer is between zero and the input limit.",
            "source": "user_confirmed", "verification": "independent",
        }]
        self.clarify = clarify
        self.fail_preparation = fail_preparation
        self.block_contract = block_contract
        self.block_candidate = block_candidate
        self.counts = Counter()
        self.authorizations = []
        self.errors = []
        self.lock = threading.Lock()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.processes = set()
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    prompt = request["messages"][-1]["content"]
                    stage = next((name for marker, name in (
                        ("contract compiler", "contract"),
                        ("frozen local evaluator bundle", "compiler"),
                        ("adversarial evaluator auditor", "auditor"),
                    ) if marker in prompt), "generation")
                    with case.lock:
                        case.counts[stage] += 1
                        index = case.counts[stage]
                        case.authorizations.append(self.headers.get("Authorization"))
                    if stage == "contract" and case.block_contract:
                        case.entered.set()
                        if not case.release.wait(30):
                            raise TimeoutError("test did not release the contract fixture")
                    if stage == "compiler" and case.fail_preparation and index == 1:
                        self.send_response(400)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if stage == "contract":
                        content = ({"status": "needs_input", "questions": [{
                            "question": "Which objective?", "options": ["maximize value"],
                        }]} if case.clarify and index == 1 else {
                            "status": "compiled", "contract": case.contract,
                        })
                    elif stage == "compiler":
                        content = {
                            **_suite(), "objective": "Maximize the integer within its input bound.",
                            "evaluator_source": SNAPSHOT_SOURCE,
                        }
                    elif stage == "auditor":
                        content = _suite(audit=True)
                    else:
                        draft = draft_for_score((1, 2, 999, 9)[index - 1])
                        files = dict(draft.source_files)
                        if case.block_candidate:
                            files["solve/main.py"] = files["solve/main.py"].replace(
                                "from helper import choose\n",
                                "from helper import choose\nimport time\n"
                                'Path("phase-c-candidate-ready").write_text(str(os.getpid()))\n'
                                "time.sleep(30)\n",
                            )
                        content = {"files": files, "entrypoint": draft.filename}
                    body = json.dumps({"choices": [{"message": {
                        "role": "assistant", "content": json.dumps(content),
                    }}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # Cancellation closes the in-flight fixture request.
                except Exception as exc:  # noqa: BLE001 - surface server failures in the test
                    case.errors.append(repr(exc))
                    self.close_connection = True

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def store(self):
        return Store(self.home / "state.db")

    @property
    def runtime_args(self):
        return [
            "--runtime", "openai-compatible", "--endpoint",
            f"http://127.0.0.1:{self.server.server_port}/v1", "--model", "offline-automatic",
            "--agent-loop", "--max-steps", "12",
        ]

    def cli(self, args, *, expected=0):
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("LUNAR_EVOLUTION_")
                       and key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
        environment["LUNAR_EVOLUTION_API_KEY"] = FAKE_KEY
        result = subprocess.run(
            [sys.executable, "-m", "lunar_evolution", *args,
             "--home", str(self.home), "--json"],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=40, check=False,
        )
        assert result.returncode == expected, result.stdout + result.stderr + self.log()
        output = result.stdout if expected != 2 else result.stderr
        payload = json.loads(output)
        self.observe_processes()
        return payload

    def solve(self, *, detach=True):
        return self.cli([
            "solve", "Choose a feasible integer and deliver its complete working project.",
            *self.runtime_args, "--workspace", str(self.workspace), "--evolve", "--multi-file",
            "--input", str(self.root / "inputs/value"), "--max-rounds", "1",
            "--stagnation-rounds", "3", "--population-size", "2",
            "--offspring-per-iteration", "2", "--islands", "2", "--seed", "7",
            "--timeout", "10", "--evaluator-preparation-timeout", "15",
            "--evaluator-preparation-wall-timeout", "25", "--solve-wall-timeout", "60",
            "--candidate-generation-max-steps", "7", *(["--detach"] if detach else []),
        ])

    def observe_processes(self):
        if not (self.home / "state.db").is_file():
            return None
        run = self.store.get_run_by_workspace(self.workspace)
        if run is not None and run.runner_pid is not None:
            self.processes.add((run.runner_pid, run.runner_pgid))
        with self.store._connect() as connection:
            self.processes.update((row["pid"], row["pgid"]) for row in connection.execute(
                "SELECT pid, pgid FROM attempts WHERE pid IS NOT NULL",
            ))
        return run

    def idle(self, run_id, *, status=None, reason=None):
        def done():
            run = self.observe_processes()
            if run is None or run.runner_pid is not None or run.runner_pgid is not None:
                return False
            if status is not None and run.status.value != status:
                return False
            if reason is not None:
                observed = [event["payload"] for event in self.store.list_events(run_id)
                            if event["type"] == "solve_execution"]
                if not observed or observed[-1].get("stopping_reason") != reason:
                    return False
            return run

        run = _wait(done, diagnostic=self.log)
        for pid, _ in self.processes:
            _wait(lambda pid=pid: not _alive(pid), seconds=5, diagnostic=self.log)
        with own_automatic_solve(run_id, self.workspace):
            pass
        assert self.errors == []
        return run

    def log(self):
        path = self.workspace / "controller.log"
        return (path.read_text() if path.is_file() else "no controller log") + repr(self.errors)

    def close(self):
        self.release.set()
        run = self.observe_processes()
        processes = sorted(self.processes, key=lambda item: run is not None and item[0] == run.runner_pid)
        for pid, pgid in processes:
            if _alive(pid):
                try:
                    os.killpg(pgid, signal.SIGKILL) if pgid == pid else os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


@pytest.fixture
def offline_case(tmp_path):
    cases = []

    def make(name="case", **kwargs):
        case = OfflineAutomaticCase(tmp_path / name, **kwargs)
        cases.append(case)
        return case

    yield make
    for case in reversed(cases):
        case.close()


def _request(case, run_id):
    return next(event["payload"] for event in case.store.list_events(run_id)
                if event["type"] == "evolution_requested")


def _assert_delivered(case, run_id):
    case.idle(run_id, status="succeeded")
    status = case.cli(["status", run_id])
    linked = status["evolution"]["linked"]
    assert linked["result"]["best_score"] == 9
    assert linked["result"]["valid_candidates"] == 3
    assert linked["materialization"]["status"] == "succeeded"
    assert json.loads((case.workspace / "output/result.json").read_text())["value"] == 9
    assert case.counts["generation"] == 4
    return status


def test_detached_automatic_matches_foreground_delivery_and_persisted_policies(offline_case):
    foreground = offline_case("foreground")
    first = foreground.solve(detach=False)
    foreground_status = _assert_delivered(foreground, first["run_id"])
    background = offline_case("background", block_contract=True)
    detached = background.solve()
    assert detached["detached"] is True
    assert detached["run_id"] == background.store.get_run_by_workspace(background.workspace).id
    assert background.entered.wait(5), background.log()
    assert background.counts == {"contract": 1}
    background.release.set()
    background_status = _assert_delivered(background, detached["run_id"])
    assert _request(foreground, first["run_id"]) == _request(background, detached["run_id"])
    request = _request(background, detached["run_id"])
    assert request["evaluator_preparation_timeout"] == 15
    assert request["evaluator_preparation_wall_timeout"] == 25
    assert request["candidate_generation_max_steps"] == 7
    assert request["solve_wall_timeout"] == 60
    assert foreground_status["solve_execution"]["policy_seconds"] == background_status["solve_execution"]["policy_seconds"] == 60
    assert (foreground.workspace / "output/result.json").read_bytes() == (background.workspace / "output/result.json").read_bytes()
    assert background.authorizations == [f"Bearer {FAKE_KEY}"] * 7
    assert FAKE_KEY not in json.dumps([
        detached, background_status, background.store.list_events(detached["run_id"]),
        background.store.list_artifacts(detached["run_id"]),
        background.store.list_events(background_status["evolution"]["linked"]["run_id"]),
    ])
    assert FAKE_KEY not in background.log()


def test_detached_waiting_worker_exits_and_answer_is_accepted_once(offline_case):
    case = offline_case(clarify=True)
    initial = case.solve()
    run_id = initial["run_id"]
    case.idle(run_id, status="awaiting_input")
    waiting = case.cli(["status", run_id])
    before = case.store.list_events(run_id)
    assert case.cli(["status", run_id])["solve_execution"] == waiting["solve_execution"]
    assert case.store.list_events(run_id) == before
    answer = case.cli(["answer", run_id, "maximize value", "--detach", *case.runtime_args])
    assert answer["run_id"] == run_id and answer["detached"] is True
    final = _assert_delivered(case, run_id)
    answer_files = {path: path.read_bytes() for path in case.workspace.rglob("input-answer.json")}
    assert len(answer_files) == 1
    before = case.store.list_events(run_id)
    error = case.cli(["answer", run_id, "a second answer", "--detach", *case.runtime_args], expected=2)
    assert "not awaiting input" in error["error"]
    assert case.store.list_events(run_id) == before
    assert all(path.read_bytes() == content for path, content in answer_files.items())
    assert len([event for event in before if event["type"] == "input_answered"]) == 1
    assert case.counts["contract"] == 2
    assert final["solve_execution"]["execution_id"] != waiting["solve_execution"]["execution_id"]
    assert final["solve_execution"]["policy_seconds"] == waiting["solve_execution"]["policy_seconds"] == 60


@pytest.mark.parametrize("command", ["solve", "resume"])
def test_detached_resume_reuses_parent_contract_and_restores_policies(offline_case, command):
    case = offline_case(fail_preparation=True)
    initial = case.solve()
    run_id = initial["run_id"]
    case.idle(run_id, reason="preparation_recoverable")
    failed = case.cli(["status", run_id])
    assert failed["evolution"]["preparation"]["recoverable"] is True
    contract = (case.workspace / "solve/contract.json").read_bytes()
    request = _request(case, run_id)
    args = ["solve", "--resume", "--run-id", run_id] if command == "solve" else ["resume", run_id]
    resumed = case.cli([*args, "--detach", *case.runtime_args])
    assert resumed["run_id"] == run_id and resumed["detached"] is True
    _assert_delivered(case, run_id)
    assert (case.workspace / "solve/contract.json").read_bytes() == contract
    assert _request(case, run_id) == request
    assert case.counts == {"contract": 1, "compiler": 2, "auditor": 1, "generation": 4}


def test_cancel_stops_real_detached_contract_worker_without_late_work(offline_case):
    case = offline_case(block_contract=True)
    initial = case.solve()
    run_id = initial["run_id"]
    assert case.entered.wait(5), case.log()
    run = case.observe_processes()
    assert run.runner_pid is not None and run.runner_pgid == run.runner_pid
    argv = subprocess.run(
        ["ps", "-p", str(run.runner_pid), "-o", "command="],
        capture_output=True, text=True, timeout=3, check=True,
    ).stdout
    assert FAKE_KEY not in argv and "--api-key" not in argv
    case.cli(["cancel", run_id])
    case.idle(run_id, status="cancelled")
    case.release.set()
    status = case.cli(["status", run_id])
    assert status["status"] == "cancelled"
    assert case.counts == {"contract": 1}
    assert not (case.workspace / "output/result.json").exists()
    assert not any(event["type"] == "bundle_candidate_delivered"
                   for event in case.store.list_events(run_id))
    with case.store._connect() as connection:
        rows = connection.execute(
            "SELECT pid, pgid FROM attempts WHERE task_id IN (SELECT id FROM tasks WHERE run_id = ?)",
            (run_id,),
        ).fetchall()
    assert all(row["pid"] is None and row["pgid"] is None for row in rows)


def test_live_background_owner_rejects_duplicate_detach_and_foreground_resume(offline_case):
    case = offline_case(block_contract=True)
    initial = case.solve()
    run_id = initial["run_id"]
    assert case.entered.wait(5), case.log()
    original = case.observe_processes()
    before = case.store.list_events(run_id)
    for args in (
        ["resume", run_id, "--detach"],
        ["solve", "--resume", "--run-id", run_id, "--detach"],
        ["resume", run_id],
    ):
        error = case.cli([*args, *case.runtime_args], expected=2)
        assert "active execution owner" in error["error"]
        current = case.store.get_run(run_id)
        assert (current.runner_pid, current.runner_pgid) == (original.runner_pid, original.runner_pgid)
        assert case.store.list_events(run_id) == before
        assert case.counts == {"contract": 1}
    case.cli(["cancel", run_id])
    case.idle(run_id, status="cancelled")


def test_detached_intake_recovers_after_worker_is_killed(offline_case):
    case = offline_case(block_contract=True)
    initial = case.solve()
    run_id = initial["run_id"]
    assert case.entered.wait(5), case.log()
    original = case.observe_processes()
    assert original.runner_pid is not None
    old_processes = case.processes.copy()
    request = _request(case, run_id)
    os.kill(original.runner_pid, signal.SIGKILL)
    _wait(lambda: not _alive(original.runner_pid), seconds=5, diagnostic=case.log)
    assert case.store.get_run(run_id).runner_pid == original.runner_pid
    case.block_contract = False
    resumed = case.cli(["resume", run_id, "--detach", *case.runtime_args])
    assert resumed["run_id"] == run_id and resumed["detached"] is True
    _assert_delivered(case, run_id)
    for pid, _ in old_processes:
        assert not _alive(pid)
    case.release.set()
    assert _request(case, run_id) == request
    assert case.counts["contract"] == 2
    events = case.store.list_events(run_id)
    assert len([event for event in events if event["type"] == "evolution_linked"]) == 1
    assert len([event for event in events if event["type"] == "bundle_candidate_delivered"]) == 1


def test_cancel_stops_real_detached_candidate_in_its_independent_group(offline_case):
    case = offline_case(block_candidate=True)
    initial = case.solve()
    run_id = initial["run_id"]

    def candidate_started():
        case.observe_processes()
        # Evaluator preparation publishes a temporary bundle directory and atomically
        # renames/removes it.  The detached candidate can start while that directory is
        # disappearing, so a recursive pathlib scan may observe a vanished entry on
        # Python 3.11.  Treat that observation as a transient poll miss and retry.
        try:
            paths = tuple(case.workspace.rglob("phase-c-candidate-ready"))
        except FileNotFoundError:
            return None
        for path in paths:
            try:
                value = path.read_text()
            except FileNotFoundError:
                continue
            if value:
                return int(value)
        return None

    candidate_pid = _wait(candidate_started, diagnostic=case.log)
    parent = case.observe_processes()
    assert os.getpgid(candidate_pid) == candidate_pid != parent.runner_pgid
    assert (candidate_pid, candidate_pid) in case.processes
    linked = next(event["payload"]["evolution_run_id"] for event in case.store.list_events(run_id)
                  if event["type"] == "evolution_linked")
    case.cli(["cancel", run_id])
    case.idle(run_id, status="cancelled")
    assert case.store.get_run(linked).status.value == "cancelled"
    assert not _alive(candidate_pid)
    with pytest.raises(ProcessLookupError):
        os.killpg(candidate_pid, 0)
    assert not (case.workspace / "output/result.json").exists()
    with case.store._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM attempts WHERE pid IS NOT NULL OR pgid IS NOT NULL",
        ).fetchone()[0] == 0


@pytest.mark.parametrize("command", ["solve", "resume"])
def test_terminal_detach_is_read_only_and_does_not_spawn_worker(offline_case, command):
    case = offline_case()
    initial = case.solve()
    run_id = initial["run_id"]
    _assert_delivered(case, run_id)
    events = case.store.list_events(run_id)
    artifacts = case.store.list_artifacts(run_id)
    files = {path: path.read_bytes() for path in case.workspace.rglob("*") if path.is_file()}
    calls = case.counts.copy()
    args = ["solve", "--resume", "--run-id", run_id] if command == "solve" else ["resume", run_id]
    repeated = case.cli([*args, "--detach", *case.runtime_args])
    assert repeated["status"] == "succeeded" and not repeated.get("detached", False)
    assert case.store.list_events(run_id) == events
    assert case.store.list_artifacts(run_id) == artifacts
    assert {path: path.read_bytes() for path in case.workspace.rglob("*") if path.is_file()} == files
    assert case.counts == calls
    case.idle(run_id, status="succeeded")
