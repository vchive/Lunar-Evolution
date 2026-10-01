"""Command-line interface for the standalone local controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import time
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

from .agent_evolution import (
    AgentCandidateEvaluator,
    AgentCandidateGenerator,
    AgentEvaluatorEnsemble,
    AgentPortfolioGenerator,
)
from .agent_loop import AgentLoopRuntime, HermesSessionRuntime
from .agents import (
    DEFAULT_RUNTIME_CAPABILITIES,
    MAX_CANDIDATE_TOOL_STEPS,
    AgentError,
    AgentRegistry,
    AgentRequest,
    CandidateGenerationBudget,
    CommandAgentAdapter,
    RuntimeAgentAdapter,
)
from .algorithm import (
    ACTIVE_EVOLUTION_STRATEGIES,
    LOOP_STRATEGY_RETIRED,
    LOOP_STRATEGY_RETIRED_MESSAGE,
    LOOP_STRATEGY_RETIREMENT_HINT,
    MAX_CONTRACT_BYTES,
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILES,
    AlgorithmProblemContract,
)
from .artifacts import ArtifactStore
from .automatic_solve_lifecycle import (
    AutomaticSolveAlreadyRunning,
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
    SolveExecutionObservation,
    own_automatic_solve,
    solve_execution_status,
)
from .benchmark import BenchmarkConfig, BenchmarkRunner
from .budget import BudgetSpec
from .config import Config
from .controller import LocalController, WorkerObservationTimeout
from .conversational import RuntimeContractCompiler, build_algorithm_role_plan
from .deep_effect_trial import DeepEffectTrialConfig, DeepEffectTrialRunner
from .effect_adapters import (
    EffectAdapterError,
    convert_fm_eval_baseline,
    run_harness_adapter,
    run_subject_adapter,
)
from .effect_kit import EffectKitError, build_effect_kit
from .effect_preflight import run_effect_preflight
from .effect_trial import EffectTrialConfig, EffectTrialError, EffectTrialRunner
from .evaluator_bundle import SolverScoringContract, compile_evaluator_bundle
from .evolution import (
    CandidateInputArtifact,
    CommandCandidateEvaluator,
    CommandCandidateGenerator,
    CommandCandidateRunner,
    ContractCandidateRunner,
    EvolutionConfig,
    EvolutionError,
    ExecutionAwareCandidateEvaluator,
    _read_bounded_regular_file,
    _strict_json_loads,
    contract_candidate_runner_fingerprint,
)
from .memory import MemoryStore
from .models import Run
from .policy import MasterPolicy, PlanDocument, PlanPatch
from .producer_handoff import ProducerHandoffError
from .profiles import ModelProfile
from .rsi_adapters import fixture_solver_gateway
from .rsi_callbacks import DurableCallbackJournal
from .rsi_controller import DeterministicCurriculum, RSILearningController
from .rsi_store import RSILedger
from .runtime import OpenAICompatibleRuntime, build_runtime
from .seed_handoff import SeedAdmissionError
from .staged_workflow import StagedWorkflowConfig
from .store import Store
from .tools import LocalToolRegistry


def _add_home(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--home",
        default=None,
        help="local state directory (default: LUNAR_EVOLUTION_HOME or .lunar-evolution)",
    )


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON value on stdout",
    )


def _evolution_strategy_request(value: str) -> str:
    """Parse active names while retaining ``loop`` solely for fixed-code retirement handling."""
    if value == "loop" or value in ACTIVE_EVOLUTION_STRATEGIES:
        return value
    raise argparse.ArgumentTypeError("strategy must be population or openevolve")


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        default="mock",
    )
    parser.add_argument("--command", dest="runtime_command", help="explicit subprocess command")
    parser.add_argument("--endpoint", help="OpenAI-compatible chat endpoint URL")
    parser.add_argument("--model", help="model name for the OpenAI-compatible runtime")
    parser.add_argument(
        "--model-profile",
        type=Path,
        help="bounded JSON ModelProfile for an agent loop (requires --agent-loop)",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        help="optional model API key (prefer LUNAR_EVOLUTION_API_KEY to avoid shell history)",
    )
    parser.add_argument(
        "--agent-loop",
        "--hermes-session",
        action="store_true",
        help="run a continuous Hermes-inspired tool session (requires openai-compatible runtime)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=40,
        help="maximum tool calls in an agent loop (default: 40)",
    )
    parser.add_argument(
        "--allow-exec",
        action="store_true",
        help="expose the no-shell run_command tool to an agent loop",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="opt in to durable memory tools for this model session",
    )
    parser.add_argument(
        "--session-history",
        action="store_true",
        help="persist and replay a bounded local transcript across retries/resume",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="maximum local task workers (default: 1)",
    )


def _add_input_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--input",
        dest="input_files",
        action="append",
        default=[],
        metavar="SOURCE[=DEST]",
        help=(
            "stage a local data file under data/raw (destination defaults to its basename; "
            "repeat for multiple files)"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lunar-evolution",
        description="Standalone local Lunar Evolution agent controller",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a local state directory")
    _add_home(init_parser)
    _add_json(init_parser)

    run_parser = subparsers.add_parser("run", help="start and execute a goal")
    run_parser.add_argument("goal", nargs="?", help="user goal, or '-' to read it from stdin")
    run_parser.add_argument("--plan", type=Path, help="JSON plan file containing goal and tasks")
    _add_runtime_options(run_parser)
    _add_input_options(run_parser)
    run_parser.add_argument(
        "--detach",
        action="store_true",
        help="return a run ID immediately and execute it in a local background process",
    )
    _add_home(run_parser)
    _add_json(run_parser)

    solve_parser = subparsers.add_parser(
        "solve", help="compile a conversational algorithm mission and execute its plan"
    )
    solve_parser.add_argument("goal", nargs="?", help="algorithm objective, or '-' to read stdin")
    solve_parser.add_argument("--workspace", type=Path, help="run workspace (default: a new local run)")
    solve_parser.add_argument("--resume", action="store_true", help="resume a conversational run")
    solve_parser.add_argument("--run-id", help="existing run ID (required with --resume)")
    solve_parser.add_argument(
        "--detach", action="store_true", help="return a run ID and compile/execute in the background"
    )
    solve_parser.add_argument(
        "--role-dag",
        action="store_true",
        help="use the five-stage DataDiscovery/Formulator/Solver/Evaluator/Reviewer workflow",
    )
    solve_parser.add_argument(
        "--evolve",
        action="store_true",
        help="handoff the compiled contract to a linked local evolution run",
    )
    solve_parser.add_argument(
        "--strategy",
        type=_evolution_strategy_request,
        metavar="{population,openevolve}",
        help=(
            "evolution strategy when --evolve is enabled "
            "(default: contract strategy; new contracts default to population)"
        ),
    )
    solve_parser.add_argument(
        "--openevolve-command",
        help="explicit OpenEvolve executable for --evolve --strategy openevolve",
    )
    solve_parser.add_argument(
        "--evaluator-command",
        help="explicit local objective harness for native --evolve candidates",
    )
    solve_parser.add_argument(
        "--compile-evaluator",
        action="store_true",
        help="compile, preflight, and freeze a local evaluator before native evolution",
    )
    solve_parser.add_argument("--bundle-profile", type=Path, help="explicit multi-file execution and exact evaluator profile for --evolve")
    solve_parser.add_argument("--multi-file", action="store_true", help="generate complete source bundles with an automatically compiled and frozen evaluator")
    solve_parser.add_argument("--max-rounds", type=int)
    solve_parser.add_argument("--stagnation-rounds", type=int)
    solve_parser.add_argument("--population-size", type=int)
    solve_parser.add_argument("--offspring-per-iteration", type=int)
    solve_parser.add_argument("--islands", type=int)
    solve_parser.add_argument("--migration-interval", type=int)
    solve_parser.add_argument("--migration-rate", type=float)
    solve_parser.add_argument("--seed", type=int)
    solve_parser.add_argument("--timeout", type=float)
    solve_parser.add_argument(
        "--evaluator-preparation-timeout",
        type=float,
        help="per-request deadline for the automatic multi-file evaluator compiler and auditor",
    )
    solve_parser.add_argument(
        "--evaluator-preparation-wall-timeout",
        type=float,
        help="total deadline for one automatic multi-file evaluator preparation attempt",
    )
    solve_parser.add_argument(
        "--solve-wall-timeout",
        type=float,
        help="active execution deadline for one automatic multi-file solve continuation",
    )
    solve_parser.add_argument(
        "--candidate-generation-max-steps",
        type=int,
        help="candidate-generation tool-step ceiling for native automatic multi-file evolution",
    )
    _add_runtime_options(solve_parser)
    _add_input_options(solve_parser)
    _add_home(solve_parser)
    _add_json(solve_parser)

    delegate_parser = subparsers.add_parser(
        "delegate", help="delegate one durable task to an explicit local Agent command"
    )
    delegate_parser.add_argument("prompt", nargs="?", help="task prompt; omit when using --run-id")
    delegate_parser.add_argument(
        "--run-id", help="delegate the next ready task in an existing run"
    )
    delegate_parser.add_argument("--task-id", help="specific task ID in an existing run")
    delegate_parser.add_argument(
        "--agent-command",
        required=True,
        help="explicit command (first token must be an absolute executable path)",
    )
    delegate_parser.add_argument("--agent-name", default="command")
    delegate_parser.add_argument("--agent-role", default="solver")
    delegate_parser.add_argument(
        "--capability",
        dest="capabilities",
        action="append",
        default=[],
        help="required worker capability; may be supplied more than once",
    )
    delegate_parser.add_argument("--preferred-agent")
    delegate_parser.add_argument("--timeout", type=float, default=None)
    delegate_parser.add_argument(
        "--wait-timeout", type=float, default=None,
        help="maximum seconds to wait for the worker; does not stop active execution",
    )
    delegate_parser.add_argument(
        "--detach",
        action="store_true",
        help="return a run ID immediately and execute delegation in a local child process",
    )
    _add_home(delegate_parser)
    _add_json(delegate_parser)

    resume_parser = subparsers.add_parser("resume", help="recover and continue a run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument(
        "--detach", action="store_true", help="continue an automatic multi-file solve in the background"
    )
    resume_parser.add_argument("--bundle-profile", type=Path, help="matching profile for a conversational multi-file evolution run")
    resume_parser.add_argument("--multi-file", action="store_true", help="continue an automatically prepared multi-file solve")
    resume_parser.add_argument(
        "--evaluator-preparation-timeout",
        type=float,
        help="matching automatic multi-file evaluator compiler/auditor request deadline",
    )
    resume_parser.add_argument(
        "--evaluator-preparation-wall-timeout",
        type=float,
        help="matching total deadline for one automatic evaluator preparation attempt",
    )
    resume_parser.add_argument(
        "--solve-wall-timeout",
        type=float,
        help="matching active execution deadline for an automatic multi-file solve",
    )
    resume_parser.add_argument(
        "--candidate-generation-max-steps",
        type=int,
        help="matching candidate-generation tool-step ceiling for an automatic multi-file handoff",
    )
    _add_runtime_options(resume_parser)
    _add_home(resume_parser)
    _add_json(resume_parser)

    evolve_parser = subparsers.add_parser("evolve", help="run a local algorithm evolution strategy")
    evolve_parser.add_argument("contract", type=Path, help="algorithm problem contract JSON")
    evolve_parser.add_argument("--workspace", type=Path, help="run workspace (default: a new local run)")
    evolve_parser.add_argument("--resume", action="store_true", help="resume an existing strategy run")
    evolve_parser.add_argument("--run-id", help="existing evolution run ID (required with --resume)")
    evolve_parser.add_argument("--detach", action="store_true", help="return an evolution run ID and execute in the background")
    seed_source = evolve_parser.add_mutually_exclusive_group()
    seed_source.add_argument(
        "--seed-manifest",
        type=Path,
        help="optional verified-seed manifest for population initialization",
    )
    seed_source.add_argument(
        "--producer-result", type=Path,
        help="completed local producer export directory for population initialization",
    )
    evolve_parser.add_argument(
        "--producer-fingerprint", help="pinned producer version/config digest required with --producer-result",
    )
    evolve_parser.add_argument("--producer-id", help="optional expected producer name with --producer-result")
    evolve_parser.add_argument(
        "--seed-dependency-sha256",
        help="current dependency identity required with --seed-manifest",
    )
    evolve_parser.add_argument(
        "--seed-environment-sha256",
        help="current execution-environment identity required with --seed-manifest",
    )
    evolve_parser.add_argument(
        "--strategy",
        type=_evolution_strategy_request,
        metavar="{population,openevolve}",
        help="override the contract strategy (new contracts default to population)",
    )
    evolve_parser.add_argument(
        "--generator-command",
        help="explicit population generator command; receives a request JSON path",
    )
    evolve_parser.add_argument("--agent-command", help="explicit Agent command used as candidate generator")
    evolve_parser.add_argument(
        "--agent-portfolio-command",
        dest="agent_portfolio_commands",
        action="append",
        default=[],
        help="repeatable explicit solver Agent command for a deterministic portfolio",
    )
    evolve_parser.add_argument(
        "--agent-runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        help="use a repository-owned runtime for any unbound solver/evaluator seam",
    )
    evolve_parser.add_argument(
        "--agent-runtime-command",
        help="runtime subprocess command (used with --agent-runtime subprocess)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-endpoint",
        help="OpenAI-compatible endpoint (used with --agent-runtime openai-compatible)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-model",
        help="OpenAI-compatible model name (used with --agent-runtime openai-compatible)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-api-key",
        help="optional runtime API key; detached runs pass it via LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY",
    )
    evolve_parser.add_argument(
        "--agent-runtime-loop",
        action="store_true",
        help="wrap an OpenAI-compatible evolution runtime in the bounded tool-capable Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-max-steps",
        type=int,
        default=40,
        help="maximum model tool calls per evolution Agent invocation (default: 40)",
    )
    evolve_parser.add_argument(
        "--agent-runtime-allow-exec",
        action="store_true",
        help="allow no-shell command execution inside the evolution Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-memory",
        action="store_true",
        help="enable explicit durable memory tools inside the evolution Agent loop",
    )
    evolve_parser.add_argument(
        "--agent-runtime-session-history",
        action="store_true",
        help="persist a bounded transcript in each evolution Agent workspace",
    )
    evolve_parser.add_argument(
        "--candidate-runner-command",
        help="explicit command that runs each candidate before evaluator-command",
    )
    evolve_parser.add_argument("--agent-name", default="evolution-agent")
    evolve_parser.add_argument("--agent-role", default="solver")
    evolve_parser.add_argument(
        "--agent-capability",
        dest="agent_capabilities",
        action="append",
        default=[],
        help="required Agent capability; may be supplied more than once",
    )
    evolve_parser.add_argument("--evaluator-command", help="explicit evaluator command; receives a candidate path")
    evolve_parser.add_argument(
        "--evaluator-agent-command",
        help="explicit evaluator Agent command returning an EvaluationReport JSON object",
    )
    evolve_parser.add_argument(
        "--evaluator-portfolio-command",
        dest="evaluator_portfolio_commands",
        action="append",
        default=[],
        help="repeatable explicit evaluator Agent command for a consensus portfolio",
    )
    evolve_parser.add_argument("--evaluator-agent-name", default="evolution-evaluator")
    evolve_parser.add_argument("--evaluator-agent-role", default="evaluator")
    evolve_parser.add_argument(
        "--evaluator-agent-capability",
        dest="evaluator_agent_capabilities",
        action="append",
        default=[],
        help="required evaluator Agent capability; may be supplied more than once",
    )
    evolve_parser.add_argument("--openevolve-command", help="explicit OpenEvolve command; receives a generated config path")
    evolve_parser.add_argument("--max-rounds", type=int)
    evolve_parser.add_argument("--stagnation-rounds", type=int)
    evolve_parser.add_argument("--population-size", type=int, default=8)
    evolve_parser.add_argument("--offspring-per-iteration", type=int, default=1)
    evolve_parser.add_argument("--islands", type=int, default=1)
    evolve_parser.add_argument("--migration-interval", type=int, default=0)
    evolve_parser.add_argument("--migration-rate", type=float, default=0.1)
    evolve_parser.add_argument("--seed", type=int)
    evolve_parser.add_argument("--timeout", type=float, default=900.0)
    _add_home(evolve_parser)
    _add_json(evolve_parser)

    bundle_evolve_parser = subparsers.add_parser(
        "evolve-bundle", help="evolve complete source bundles with a pinned local evaluator",
    )
    bundle_evolve_parser.add_argument("contract", type=Path, help="algorithm contract JSON")
    bundle_evolve_parser.add_argument("--profile", type=Path, required=True, help="bundle pipeline profile JSON")
    bundle_generator = bundle_evolve_parser.add_mutually_exclusive_group(required=True)
    bundle_generator.add_argument("--generator-command", help="explicit generator command receiving a request JSON path")
    bundle_generator.add_argument("--agent-command", help="explicit solver Agent command receiving an Agent request on stdin")
    bundle_generator.add_argument("--agent-runtime", choices=("mock", "subprocess", "openai-compatible"), help="repository runtime used only to generate candidate source")
    bundle_evolve_parser.add_argument("--agent-name", help="solver Agent name (default: bundle-agent)")
    bundle_evolve_parser.add_argument("--agent-role", help="solver Agent role (default: solver)")
    bundle_evolve_parser.add_argument("--agent-capability", dest="agent_capabilities", action="append", default=[])
    bundle_evolve_parser.add_argument("--agent-runtime-command", help="explicit command for the subprocess runtime")
    bundle_evolve_parser.add_argument("--agent-runtime-endpoint", help="OpenAI-compatible model endpoint")
    bundle_evolve_parser.add_argument("--agent-runtime-model", help="OpenAI-compatible model name")
    bundle_evolve_parser.add_argument("--agent-runtime-api-key", help="optional model API key")
    bundle_evolve_parser.add_argument("--agent-runtime-loop", action="store_true", help="enable the bounded model tool loop")
    bundle_evolve_parser.add_argument("--agent-runtime-max-steps", type=int, help="model tool-loop step limit (default: 40, maximum: 200)")
    bundle_evolve_parser.add_argument("--agent-runtime-allow-exec", action="store_true", help="allow command execution within the model tool loop")
    bundle_evolve_parser.add_argument("--agent-runtime-memory", action="store_true", help="enable durable memory within the model tool loop")
    bundle_evolve_parser.add_argument("--agent-runtime-session-history", action="store_true", help="retain a bounded model tool-loop transcript")
    bundle_evolve_parser.add_argument("--workspace", type=Path, required=True, help="evolution workspace")
    bundle_evolve_parser.add_argument("--resume", action="store_true", help="validate and resume the existing run")
    bundle_evolve_parser.add_argument("--run-id", help="existing run ID required with --resume")
    bundle_evolve_parser.add_argument("--destination-root", type=Path, help="existing directory for the selected source and scored outputs")
    bundle_evolve_parser.add_argument("--max-rounds", type=int)
    bundle_evolve_parser.add_argument("--stagnation-rounds", type=int)
    bundle_evolve_parser.add_argument("--population-size", type=int, default=8)
    bundle_evolve_parser.add_argument("--offspring-per-iteration", type=int, default=1)
    bundle_evolve_parser.add_argument("--islands", type=int, default=1)
    bundle_evolve_parser.add_argument("--migration-interval", type=int, default=0)
    bundle_evolve_parser.add_argument("--migration-rate", type=float, default=0.1)
    bundle_evolve_parser.add_argument("--seed", type=int)
    bundle_evolve_parser.add_argument("--timeout", type=float, default=900.0, help="generator timeout in seconds")
    _add_home(bundle_evolve_parser)
    _add_json(bundle_evolve_parser)

    benchmark_parser = subparsers.add_parser(
        "benchmark", help="compare native evolution strategies on one local contract"
    )
    benchmark_parser.add_argument("contract", type=Path, help="algorithm problem contract JSON")
    benchmark_parser.add_argument(
        "--strategy",
        dest="strategies",
        action="append",
        type=_evolution_strategy_request,
        metavar="{population,openevolve}",
        help="strategy to compare; repeat for order (default: population)",
    )
    benchmark_parser.add_argument("--workspace", type=Path, help="new benchmark workspace")
    benchmark_parser.add_argument(
        "--generator-command", help="explicit generator command for population"
    )
    benchmark_parser.add_argument(
        "--evaluator-command", help="explicit evaluator command"
    )
    benchmark_parser.add_argument(
        "--openevolve-command", help="explicit OpenEvolve command for the openevolve strategy"
    )
    benchmark_parser.add_argument(
        "--agent-runtime",
        choices=("mock", "subprocess", "openai-compatible"),
        help="use a repository-owned runtime for native solver/evaluator roles",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-command",
        help="runtime subprocess command (used with --agent-runtime subprocess)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-endpoint",
        help="OpenAI-compatible endpoint (used with --agent-runtime openai-compatible)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-model",
        help="OpenAI-compatible model name (used with --agent-runtime openai-compatible)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-api-key",
        help="optional runtime API key; prefer LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-loop",
        action="store_true",
        help="wrap an OpenAI-compatible runtime in the bounded tool-capable loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-max-steps",
        type=int,
        default=40,
        help="maximum model tool calls per runtime invocation (default: 40)",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-allow-exec",
        action="store_true",
        help="allow no-shell command execution inside the runtime loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-memory",
        action="store_true",
        help="enable explicit durable memory tools inside the runtime loop",
    )
    benchmark_parser.add_argument(
        "--agent-runtime-session-history",
        action="store_true",
        help="persist a bounded transcript in each runtime workspace",
    )
    benchmark_parser.add_argument("--max-rounds", type=int)
    benchmark_parser.add_argument("--stagnation-rounds", type=int)
    benchmark_parser.add_argument("--population-size", type=int, default=8)
    benchmark_parser.add_argument("--offspring-per-iteration", type=int, default=1)
    benchmark_parser.add_argument("--islands", type=int, default=1)
    benchmark_parser.add_argument("--migration-interval", type=int, default=0)
    benchmark_parser.add_argument("--migration-rate", type=float, default=0.1)
    benchmark_parser.add_argument("--seed", type=int)
    benchmark_parser.add_argument("--timeout", type=float, default=900.0)
    _add_home(benchmark_parser)
    _add_json(benchmark_parser)

    effect_parser = subparsers.add_parser(
        "effect-trial",
        help="run a small frozen normal-Agent trial against exported reference-benchmark history",
    )
    effect_parser.add_argument("suite", type=Path, help="frozen one/two-case suite JSON")
    effect_parser.add_argument("baseline", type=Path, help="FM-Eval per-run baseline export JSON")
    effect_parser.add_argument(
        "--case-source",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="map one selected case key to its local public source root; repeat per case",
    )
    effect_parser.add_argument("--subject-command", required=True, help="explicit normal-Agent command")
    effect_parser.add_argument("--harness-command", required=True, help="explicit exact-harness command")
    effect_parser.add_argument("--requested-model", required=True, help="requested model identity")
    effect_parser.add_argument(
        "--model-profile", type=Path,
        help="bounded JSON ModelProfile for the isolated subject runtime",
    )
    effect_parser.add_argument("--runs-per-case", type=int, default=3)
    effect_parser.add_argument("--timeout", type=float, default=3600.0)
    effect_parser.add_argument("--workspace", type=Path, required=True, help="trial workspace")
    effect_parser.add_argument(
        "--keep-awake-report", type=Path,
        help="require macOS idle-sleep protection; fresh JSONL outside workspace and case sources",
    )
    effect_parser.add_argument(
        "--subject-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the subject",
    )
    effect_parser.add_argument(
        "--harness-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the harness",
    )
    effect_parser.add_argument("--resume", action="store_true", help="resume the frozen trial")
    _add_json(effect_parser)

    preflight_parser = subparsers.add_parser(
        "effect-preflight",
        help="validate a frozen effect trial and exact harness without running either process",
    )
    preflight_parser.add_argument("suite", type=Path, help="frozen one/two-case suite JSON")
    preflight_parser.add_argument("baseline", type=Path, help="FM-Eval per-run baseline export JSON")
    preflight_parser.add_argument(
        "--case-source",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="map one selected case key to its local public source root; repeat per case",
    )
    preflight_parser.add_argument("--subject-command", required=True, help="explicit normal-Agent command")
    preflight_parser.add_argument("--harness-command", required=True, help="explicit exact-harness command")
    preflight_parser.add_argument("--requested-model", required=True, help="requested model identity")
    preflight_parser.add_argument(
        "--model-profile", type=Path, help="bounded JSON ModelProfile for the isolated subject runtime"
    )
    preflight_parser.add_argument("--harness-python", required=True, help="exact extractor Python interpreter")
    preflight_parser.add_argument(
        "--harness-import",
        action="append",
        default=[],
        metavar="MODULE",
        help="module to probe with the exact harness Python; repeat as needed",
    )
    preflight_parser.add_argument(
        "--harness-package",
        action="append",
        default=[],
        metavar="DIST[==VERSION]",
        help="distribution to probe with the exact harness Python; repeat as needed",
    )
    preflight_parser.add_argument("--runs-per-case", type=int, default=1)
    preflight_parser.add_argument("--timeout", type=float, default=3600.0)
    preflight_parser.add_argument(
        "--subject-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the subject",
    )
    preflight_parser.add_argument(
        "--harness-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the harness",
    )
    preflight_parser.add_argument("--output", type=Path, help="optional atomic JSON report destination")
    _add_json(preflight_parser)

    deep_effect_parser = subparsers.add_parser(
        "effect-deep-trial",
        help="run a bounded five-round deep-evolution trial against exported reference-benchmark history",
    )
    deep_effect_parser.add_argument("suite", type=Path, help="frozen one/two-case suite JSON")
    deep_effect_parser.add_argument("baseline", type=Path, help="FM-Eval per-run baseline export JSON")
    deep_effect_parser.add_argument(
        "--case-source",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="map one selected case key to its local public source root; repeat per case",
    )
    deep_effect_parser.add_argument("--subject-command", required=True, help="explicit deep subject command")
    deep_effect_parser.add_argument("--harness-command", required=True, help="explicit exact-harness command")
    deep_effect_parser.add_argument("--requested-model", required=True, help="requested model identity")
    deep_effect_parser.add_argument(
        "--model-profile", type=Path,
        help="bounded JSON ModelProfile for the isolated subject runtime",
    )
    deep_effect_parser.add_argument("--runs-per-case", type=int, default=2)
    deep_effect_parser.add_argument(
        "--outer-rounds",
        type=int,
        default=5,
        help="outer evolution rounds (default: 5, matching WebAgent no-argument /evolve)",
    )
    deep_effect_parser.add_argument(
        "--stagnation-rounds",
        type=int,
        default=2,
        help="non-improving rounds before a strategy-change directive (default: 2)",
    )
    deep_effect_parser.add_argument("--timeout", type=float, default=3600.0)
    deep_effect_parser.add_argument("--workspace", type=Path, required=True, help="trial workspace")
    deep_effect_parser.add_argument(
        "--keep-awake-report", type=Path,
        help="require macOS idle-sleep protection; fresh JSONL outside workspace and case sources",
    )
    deep_effect_parser.add_argument(
        "--subject-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the subject",
    )
    deep_effect_parser.add_argument(
        "--harness-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing environment variable to the harness",
    )
    deep_effect_parser.add_argument("--resume", action="store_true", help="resume the deep trial")
    _add_json(deep_effect_parser)

    kit_parser = subparsers.add_parser(
        "effect-kit", help="build a content-addressed public reference-benchmark trial kit"
    )
    kit_parser.add_argument("output", type=Path, help="new local kit directory")
    kit_parser.add_argument(
        "--case",
        action="append",
        default=[],
        required=True,
        metavar="KEY=PATH",
        help="map a selected key to an absolute private case root; repeat for at most two cases",
    )
    kit_parser.add_argument("--benchmark-name", default="reference-benchmark")
    kit_parser.add_argument("--profile-name", default="lunar-evolution-reference-default")
    kit_parser.add_argument("--profile-revision", type=int, default=1)
    kit_parser.add_argument(
        "--owner-attested-content-equivalence",
        action="store_true",
        help="record that the owner established cross-release selected-case content equivalence",
    )
    _add_json(kit_parser)

    subject_parser = subparsers.add_parser(
        "effect-subject", help="run Lunar Evolution as a fresh reference-benchmark subject"
    )
    subject_parser.add_argument("request", type=Path, help="generated subject request JSON")
    subject_parser.add_argument("--endpoint", help="OpenAI-compatible chat endpoint URL")
    subject_parser.add_argument("--model", help="model name (must match the generated request)")
    subject_parser.add_argument(
        "--model-profile",
        type=Path,
        help="bounded JSON ModelProfile for the isolated subject runtime",
    )
    subject_parser.add_argument(
        "--api-key", help="optional model API key (prefer LUNAR_EVOLUTION_API_KEY)"
    )
    subject_parser.add_argument("--max-steps", type=int, default=100)
    subject_parser.add_argument("--timeout", type=float)
    subject_parser.add_argument(
        "--workflow-config", type=Path,
        help="opt-in frozen staged manifest and reservations JSON (normal mode only)",
    )
    subject_parser.add_argument(
        "--no-exec", action="store_true", help="disable the no-shell command tool"
    )
    _add_json(subject_parser)

    harness_parser = subparsers.add_parser(
        "effect-harness", help="run an exact frozen reference-benchmark extractor/evaluator pair"
    )
    harness_parser.add_argument("request", type=Path, help="generated harness request JSON")
    harness_parser.add_argument("--case-root", type=Path, required=True)
    harness_parser.add_argument("--python", default=sys.executable, help="extractor Python")
    harness_parser.add_argument("--timeout", type=float, default=600.0)
    harness_parser.add_argument(
        "--extractor-env",
        action="append",
        default=[],
        metavar="NAME",
        help="pass one explicitly named existing variable to the extractor; repeat as needed",
    )
    _add_json(harness_parser)

    baseline_parser = subparsers.add_parser(
        "effect-baseline", help="convert a local evaluation results export to a strict baseline"
    )
    baseline_parser.add_argument("results", type=Path)
    baseline_parser.add_argument("suite", type=Path)
    baseline_parser.add_argument("output", type=Path)
    baseline_parser.add_argument("--experiment-id", required=True)
    baseline_parser.add_argument("--requested-model", required=True)
    baseline_parser.add_argument("--effective-model", required=True)
    baseline_parser.add_argument(
        "--model-evidence",
        choices=("not_observable", "owner_attested", "runtime_observed", "provider_observed"),
        required=True,
    )
    baseline_parser.add_argument("--authority", default="descriptive")
    baseline_parser.add_argument(
        "--conclusion-eligibility", choices=("eligible", "ineligible"), default="ineligible"
    )
    baseline_parser.add_argument(
        "--owner-attested-content-equivalence",
        action="store_true",
        help="label historical/local content equivalence as owner-attested and formally ineligible",
    )
    baseline_parser.add_argument(
        "--adapter-kind",
        choices=("webagent", "agentserver", "company-platform"),
        default="webagent",
        help="source adapter identity carried by the export (default: webagent)",
    )
    baseline_parser.add_argument(
        "--baseline-source",
        default="fm-eval",
        help="safe baseline source identifier recorded in provenance (default: fm-eval)",
    )
    _add_json(baseline_parser)

    answer_parser = subparsers.add_parser("answer", help="answer a pending agent question and resume")
    answer_parser.add_argument("run_id")
    answer_parser.add_argument("answer", nargs="?", help="answer text, or '-' to read stdin")
    answer_parser.add_argument(
        "--detach", action="store_true", help="accept the answer and continue an automatic multi-file solve in the background"
    )
    answer_parser.add_argument("--bundle-profile", type=Path, help="matching profile for a pending multi-file evolution handoff")
    answer_parser.add_argument("--multi-file", action="store_true", help="continue an automatically prepared multi-file solve")
    answer_parser.add_argument(
        "--evaluator-preparation-timeout",
        type=float,
        help="matching automatic multi-file evaluator compiler/auditor request deadline",
    )
    answer_parser.add_argument(
        "--evaluator-preparation-wall-timeout",
        type=float,
        help="matching total deadline for one automatic evaluator preparation attempt",
    )
    answer_parser.add_argument(
        "--solve-wall-timeout",
        type=float,
        help="matching active execution deadline for an automatic multi-file solve",
    )
    answer_parser.add_argument(
        "--candidate-generation-max-steps",
        type=int,
        help="matching candidate-generation tool-step ceiling for an automatic multi-file handoff",
    )
    answer_parser.add_argument(
        "--evaluator-command",
        help="explicit local objective harness for a pending native evolution handoff",
    )
    answer_parser.add_argument(
        "--compile-evaluator",
        action="store_true",
        help="enable a pending compiled evaluator handoff",
    )
    _add_runtime_options(answer_parser)
    _add_home(answer_parser)
    _add_json(answer_parser)

    for name, help_text in (
        ("status", "inspect a run"),
        ("events", "inspect run events"),
        ("cancel", "cancel a run"),
        ("recover", "propose an evidence-guided recovery action"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("run_id")
        _add_home(command_parser)
        _add_json(command_parser)
    diagnostic_parser = subparsers.add_parser(
        "diagnose-materialization", help="inspect retained delivery evidence without changing the run",
    )
    diagnostic_parser.add_argument("parent_run_id")
    diagnostic_parser.add_argument("evolution_run_id")
    _add_home(diagnostic_parser)
    _add_json(diagnostic_parser)
    export_parser = subparsers.add_parser(
        "export-materialization-evidence", help="export a sanitized materialization evidence bundle",
    )
    export_parser.add_argument("parent_run_id")
    export_parser.add_argument("evolution_run_id")
    export_parser.add_argument("--output", required=True)
    _add_home(export_parser)
    _add_json(export_parser)
    attest_parser = subparsers.add_parser(
        "attest-materialization-execution", help="register an explicitly attested retained execution",
    )
    attest_parser.add_argument("parent_run_id")
    attest_parser.add_argument("evolution_run_id")
    attest_parser.add_argument("--receipt", required=True, type=Path)
    _add_home(attest_parser)
    _add_json(attest_parser)
    shinka_parser = subparsers.add_parser(
        "export-shinka-result", help="export completed Shinka material for local population warm start",
    )
    shinka_parser.add_argument("results_root", type=Path)
    shinka_parser.add_argument("--output", type=Path, required=True, help="new export directory")
    shinka_parser.add_argument("--contract", type=Path, required=True, help="algorithm contract JSON")
    shinka_parser.add_argument("--producer-fingerprint", required=True, help="pinned Shinka version/config SHA-256")
    shinka_parser.add_argument("--producer-run-id", help="optional producer run label")
    selection = shinka_parser.add_mutually_exclusive_group()
    selection.add_argument("--program-id", action="append", dest="program_ids", help="select ordered IDs; repeat for more")
    selection.add_argument("--top-k", type=int, help="select top correct rows by producer score (default: 1)")
    _add_json(shinka_parser)
    benchmark_task_parser = subparsers.add_parser(
        "benchmark-task", help="validate a benchmark task envelope without initialization",
    )
    benchmark_task_commands = benchmark_task_parser.add_subparsers(
        dest="benchmark_task_command", required=True,
    )
    validate_task_parser = benchmark_task_commands.add_parser(
        "validate", help="validate task identity and input bytes",
    )
    validate_task_parser.add_argument("task", type=Path, help="benchmark task envelope JSON")
    validate_task_parser.add_argument("--contract", type=Path, required=True, help="algorithm contract JSON")
    validate_task_parser.add_argument("--input-root", type=Path, required=True, help="root containing declared input files")
    validate_task_parser.add_argument("--model-profile-sha256", required=True, help="caller-pinned model profile digest")
    validate_task_parser.add_argument("--evaluator-fingerprint", required=True, help="caller-pinned exact evaluator digest")
    _add_home(validate_task_parser)
    _add_json(validate_task_parser)
    comparison_parser = subparsers.add_parser(
        "benchmark-comparison", help="validate a frozen benchmark comparison without initialization",
    )
    comparison_commands = comparison_parser.add_subparsers(
        dest="benchmark_comparison_command", required=True,
    )
    validate_comparison_parser = comparison_commands.add_parser(
        "validate-result", help="validate a comparison plan and its result receipt",
    )
    validate_comparison_parser.add_argument("plan", type=Path, help="comparison plan JSON")
    validate_comparison_parser.add_argument("result", type=Path, help="comparison result JSON")
    validate_comparison_parser.add_argument("--contract", type=Path, required=True, help="algorithm contract JSON")
    validate_comparison_parser.add_argument("--input-root", type=Path, required=True, help="root containing declared input files")
    validate_comparison_parser.add_argument("--model-profile-sha256", required=True, help="caller-pinned model profile digest")
    validate_comparison_parser.add_argument("--evaluator-fingerprint", required=True, help="caller-pinned exact evaluator digest")
    validate_comparison_parser.add_argument(
        "--plan-sha256", help="caller-pinned canonical plan digest; requires a pinned result receipt",
    )
    validate_comparison_parser.add_argument(
        "--evidence-root", type=Path,
        help="optional root containing the declared per-arm evidence files",
    )
    _add_home(validate_comparison_parser)
    _add_json(validate_comparison_parser)
    candidate_bundle_parser = subparsers.add_parser(
        "candidate-bundle", help="verify declared candidate source files without initialization",
    )
    candidate_bundle_commands = candidate_bundle_parser.add_subparsers(
        dest="candidate_bundle_command", required=True,
    )
    validate_bundle_parser = candidate_bundle_commands.add_parser(
        "validate", help="validate a source manifest and its declared file bytes",
    )
    validate_bundle_parser.add_argument("manifest", type=Path, help="candidate source bundle JSON")
    validate_bundle_parser.add_argument("--source-root", type=Path, required=True, help="root containing declared source files")
    validate_bundle_parser.add_argument("--contract", type=Path, required=True, help="algorithm contract JSON")
    validate_bundle_parser.add_argument("--bundle-sha256", help="optional caller-pinned canonical bundle digest")
    _add_home(validate_bundle_parser)
    _add_json(validate_bundle_parser)
    materialize_bundle_parser = candidate_bundle_commands.add_parser(
        "materialize", help="copy declared source files into a private workspace without execution",
    )
    materialize_bundle_parser.add_argument("manifest", type=Path, help="candidate source bundle JSON")
    materialize_bundle_parser.add_argument("--source-root", type=Path, required=True, help="root containing declared source files")
    materialize_bundle_parser.add_argument("--contract", type=Path, required=True, help="algorithm contract JSON")
    materialize_bundle_parser.add_argument("--workspace-root", type=Path, required=True, help="existing directory for private workspaces")
    materialize_bundle_parser.add_argument("--bundle-sha256", help="optional caller-pinned canonical bundle digest")
    materialize_bundle_parser.add_argument("--command", dest="planned_command", nargs="+", required=True, help="planned absolute runner command; never started")
    materialize_bundle_parser.add_argument("--timeout-seconds", type=float, default=300.0)
    materialize_bundle_parser.add_argument("--max-output-bytes", type=int, default=1024 * 1024)
    materialize_bundle_parser.add_argument("--environment-json", type=Path, help="optional explicit environment object JSON")
    _add_home(materialize_bundle_parser)
    _add_json(materialize_bundle_parser)
    admit_execution_parser = candidate_bundle_commands.add_parser(
        "admit-execution", help="admit a static execution declaration without initialization",
    )
    admit_execution_parser.add_argument("plan", type=Path, help="candidate workspace plan JSON")
    admit_execution_parser.add_argument(
        "--inputs", type=Path, required=True,
        help="JSON file containing the logical input descriptor array",
    )
    admit_execution_parser.add_argument(
        "--input-root", type=Path,
        help="optional root containing the declared input bytes",
    )
    admit_execution_parser.add_argument("--dependency-sha256", required=True)
    admit_execution_parser.add_argument("--environment-sha256", required=True)
    admit_execution_parser.add_argument("--evaluator-kind", required=True)
    admit_execution_parser.add_argument("--evaluator-sha256", required=True)
    admit_execution_parser.add_argument("--output-contract-sha256")
    admit_execution_parser.add_argument("--timeout-seconds", type=float)
    admit_execution_parser.add_argument("--max-output-bytes", type=int)
    admit_execution_parser.add_argument("--max-input-bytes", type=int)
    admit_execution_parser.add_argument("--max-processes", type=int)
    admit_execution_parser.add_argument("--plan-sha256", dest="expected_plan_sha256")
    admit_execution_parser.add_argument("--bundle-sha256", dest="expected_bundle_sha256")
    admit_execution_parser.add_argument("--contract-sha256", dest="expected_contract_sha256")
    admit_execution_parser.add_argument("--admission-sha256", dest="expected_admission_sha256")
    _add_home(admit_execution_parser)
    _add_json(admit_execution_parser)
    stage_inputs_parser = candidate_bundle_commands.add_parser(
        "stage-inputs", help="copy admitted inputs to a private directory without execution",
    )
    stage_inputs_parser.add_argument("admission", type=Path, help="execution admission JSON")
    stage_inputs_parser.add_argument("--plan", type=Path, required=True, help="workspace plan JSON")
    stage_inputs_parser.add_argument("--input-root", type=Path, required=True)
    stage_inputs_parser.add_argument("--staging-root", type=Path, required=True)
    stage_inputs_parser.add_argument("--plan-sha256", dest="expected_plan_sha256")
    stage_inputs_parser.add_argument("--bundle-sha256", dest="expected_bundle_sha256")
    stage_inputs_parser.add_argument("--contract-sha256", dest="expected_contract_sha256")
    stage_inputs_parser.add_argument("--admission-sha256", dest="expected_admission_sha256")
    _add_home(stage_inputs_parser)
    _add_json(stage_inputs_parser)
    run_bundle_parser = candidate_bundle_commands.add_parser(
        "run", help="run an admitted candidate without Store or evaluator initialization",
    )
    run_bundle_parser.add_argument("admission", type=Path, help="execution admission JSON")
    run_bundle_parser.add_argument("--plan", type=Path, required=True)
    run_bundle_parser.add_argument("--workspace", type=Path, required=True)
    run_bundle_parser.add_argument("--input-root", type=Path, required=True)
    run_bundle_parser.add_argument("--plan-sha256", dest="expected_plan_sha256")
    run_bundle_parser.add_argument("--bundle-sha256", dest="expected_bundle_sha256")
    run_bundle_parser.add_argument("--contract-sha256", dest="expected_contract_sha256")
    run_bundle_parser.add_argument("--admission-sha256", dest="expected_admission_sha256")
    _add_home(run_bundle_parser)
    _add_json(run_bundle_parser)
    for command, help_text in (
        ("run-recorded", "retain launch intent and process evidence in a new attempt directory"),
        ("inspect-execution", "inspect retained execution evidence without launching or repairing"),
    ):
        record_parser = candidate_bundle_commands.add_parser(command, help=help_text)
        record_parser.add_argument("admission", type=Path, help="execution admission JSON")
        record_parser.add_argument("--plan", type=Path, required=True)
        record_parser.add_argument("--attempt", type=Path, required=True)
        if command == "run-recorded":
            record_parser.add_argument("--workspace", type=Path, required=True)
            record_parser.add_argument("--input-root", type=Path, required=True)
        else:
            record_parser.add_argument("--completion-sha256", dest="expected_completion_sha256")
        record_parser.add_argument("--plan-sha256", dest="expected_plan_sha256")
        record_parser.add_argument("--bundle-sha256", dest="expected_bundle_sha256")
        record_parser.add_argument("--contract-sha256", dest="expected_contract_sha256")
        record_parser.add_argument("--admission-sha256", dest="expected_admission_sha256")
        _add_home(record_parser)
        _add_json(record_parser)
    evaluate_bundle_parser = candidate_bundle_commands.add_parser(
        "evaluate", help="independently score retained candidate outputs without rerunning the candidate",
    )
    evaluate_bundle_parser.add_argument("admission", type=Path, help="execution admission JSON")
    evaluate_bundle_parser.add_argument("--plan", type=Path, required=True)
    evaluate_bundle_parser.add_argument("--contract", type=Path, required=True)
    evaluate_bundle_parser.add_argument("--evaluator", type=Path, required=True, help="pinned evaluator specification JSON")
    evaluate_bundle_parser.add_argument("--harness", type=Path, required=True, help="evaluator implementation file")
    evaluate_bundle_parser.add_argument("--workspace", type=Path, required=True)
    evaluate_bundle_parser.add_argument("--input-root", type=Path, required=True)
    evaluate_bundle_parser.add_argument("--attempt", type=Path, required=True)
    evaluate_bundle_parser.add_argument("--evaluation-root", type=Path, required=True, help="existing root for a new private evaluation directory")
    evaluate_bundle_parser.add_argument("--plan-sha256", dest="expected_plan_sha256")
    evaluate_bundle_parser.add_argument("--bundle-sha256", dest="expected_bundle_sha256")
    evaluate_bundle_parser.add_argument("--contract-sha256", dest="expected_contract_sha256")
    evaluate_bundle_parser.add_argument("--admission-sha256", dest="expected_admission_sha256")
    evaluate_bundle_parser.add_argument("--completion-sha256", dest="expected_completion_sha256")
    _add_home(evaluate_bundle_parser)
    _add_json(evaluate_bundle_parser)
    inspect_evaluation_parser = candidate_bundle_commands.add_parser(
        "inspect-evaluation", help="verify retained evaluation evidence without execution or initialization",
    )
    inspect_evaluation_parser.add_argument("evaluation", type=Path, help="retained evaluation directory")
    inspect_evaluation_parser.add_argument("--evaluation-sha256", dest="expected_evaluation_sha256")
    _add_home(inspect_evaluation_parser)
    _add_json(inspect_evaluation_parser)
    inspect_delivery_parser = candidate_bundle_commands.add_parser(
        "inspect-delivery", help="verify a portable bundle delivery without execution or initialization",
    )
    inspect_delivery_parser.add_argument("delivery", type=Path, help="retained delivery directory")
    inspect_delivery_parser.add_argument("--delivery-sha256", dest="expected_delivery_sha256")
    _add_home(inspect_delivery_parser)
    _add_json(inspect_delivery_parser)
    memory_parser = subparsers.add_parser("memory", help="inspect explicit local memory")
    memory_parser.add_argument("query", nargs="?", help="optional lexical recall query")
    memory_parser.add_argument("--scope", help="limit results to global or run:<run-id>")
    memory_parser.add_argument("--limit", type=int, default=20)
    _add_home(memory_parser)
    _add_json(memory_parser)

    rsi_parser = subparsers.add_parser("rsi", help="run or inspect local RSI learning mode")
    rsi_commands = rsi_parser.add_subparsers(dest="rsi_command", required=True)
    rsi_run_parser = rsi_commands.add_parser(
        "run", help="run the provider-free RSI fixture and persist its ledger"
    )
    rsi_run_parser.add_argument("contract", type=Path, help="contract file used to pin the run")
    rsi_run_parser.add_argument("--mode", choices=("drs", "brs"), default="drs")
    rsi_run_parser.add_argument("--solver", choices=("mock", "native_population", "openevolve", "shinka"), default="mock")
    rsi_run_parser.add_argument("--run-id", help="explicit durable RSI run ID")
    rsi_run_parser.add_argument("--reconcile-callback", help="record an explicit result for one uncertain callback")
    rsi_run_parser.add_argument("--expected-checkpoint-sha256", help="observed started callback checkpoint")
    rsi_run_parser.add_argument("--callback-result", type=Path, help="strict JSON object containing the callback result")
    rsi_run_parser.add_argument("--callback-evidence", type=Path, help="strict JSON object binding local recovery evidence")
    rsi_run_parser.add_argument("--contract-sha256", help="explicit contract pin; defaults to file bytes")
    rsi_run_parser.add_argument("--evaluator-sha256", help="evaluator pin; defaults to local exact fixture")
    rsi_run_parser.add_argument("--environment-sha256", help="environment pin; defaults to local fixture")
    rsi_run_parser.add_argument("--max-practice-rounds", type=int, default=3)
    rsi_run_parser.add_argument("--max-target-attempts", type=int, default=4)
    rsi_run_parser.add_argument("--practice-count", type=int, default=2, help="BRS practice decisions")
    rsi_run_parser.add_argument(
        "--worker-status",
        choices=("completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"),
        default="completed",
        help="terminal status for the local fixture worker",
    )
    _add_home(rsi_run_parser)
    _add_json(rsi_run_parser)

    rsi_inspect_parser = rsi_commands.add_parser("inspect", help="inspect one RSI run or episode ledger")
    rsi_inspect_parser.add_argument("logical_id")
    rsi_inspect_parser.add_argument("--callback-id", help="inspect a callback checkpoint in this run")
    _add_home(rsi_inspect_parser)
    _add_json(rsi_inspect_parser)

    rsi_usage_parser = rsi_commands.add_parser("usage", help="read an existing RSI usage ledger without initializing local state")
    rsi_usage_parser.add_argument("ledger", type=Path, help="existing local usage JSON ledger")
    rsi_usage_parser.add_argument("--run-id", help="limit receipts to one run")
    rsi_usage_parser.add_argument("--episode-id", help="limit receipts to one episode")
    rsi_usage_parser.add_argument("--adapter-stage", help="limit receipts to one adapter stage")
    _add_json(rsi_usage_parser)

    rsi_reconcile_parser = rsi_commands.add_parser("reconcile", help="reconcile an RSI worker state explicitly")
    rsi_reconcile_parser.add_argument("episode_id")
    rsi_reconcile_parser.add_argument(
        "--worker-state", choices=("running", "idle", "completed", "failed", "cancelled", "unknown"), required=True,
    )
    rsi_reconcile_parser.add_argument("--launched", action="store_true", help="treat an idle worker as launched")
    rsi_reconcile_parser.add_argument("--expected-record-sha256", required=True)
    _add_home(rsi_reconcile_parser)
    _add_json(rsi_reconcile_parser)

    decide_parser = subparsers.add_parser("decide", help="classify a goal with Master policy")
    decide_parser.add_argument("goal", nargs="?", help="goal, or '-' to read stdin")
    _add_home(decide_parser)
    _add_json(decide_parser)

    plan_parser = subparsers.add_parser("plan", help="create or inspect a versioned plan")
    plan_parser.add_argument("target", help="plan JSON path to create, or run ID to inspect")
    plan_parser.add_argument("plan_file", nargs="?", help="optional plan JSON path")
    _add_runtime_options(plan_parser)
    _add_home(plan_parser)
    _add_json(plan_parser)

    for name, help_text in (("patch", "patch the current plan"), ("replan", "create a new plan revision")):
        revision_parser = subparsers.add_parser(name, help=help_text)
        revision_parser.add_argument("run_id")
        revision_parser.add_argument("plan_file", type=Path)
        _add_home(revision_parser)
        _add_json(revision_parser)

    deliver_parser = subparsers.add_parser("deliver", help="return verified run artifacts")
    deliver_parser.add_argument("run_id")
    _add_home(deliver_parser)
    _add_json(deliver_parser)
    return parser


def _config(args: argparse.Namespace) -> Config:
    config = Config.from_env(args.home)
    config.ensure()
    Store(config.database).initialize()
    return config


def _reject_retired_cli_strategy(args: argparse.Namespace) -> None:
    """Reject an explicitly named historical strategy before local state is initialized."""
    requested: tuple[str, ...]
    if args.command == "benchmark":
        requested = tuple(args.strategies or ())
    elif args.command in {"solve", "evolve"}:
        requested = (args.strategy,) if args.strategy is not None else ()
    else:
        return
    if "loop" in requested:
        raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)


_MAX_MODEL_PROFILE_BYTES = 64 * 1024


def _load_model_profile(path: Path | None) -> ModelProfile | None:
    """Load one bounded, regular JSON model profile without following a symlink."""
    if path is None:
        return None
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("model profile must be a regular file")
    try:
        with candidate.open("rb") as stream:
            content = stream.read(_MAX_MODEL_PROFILE_BYTES + 1)
        if len(content) > _MAX_MODEL_PROFILE_BYTES:
            raise ValueError("model profile exceeds 65536 bytes")
        payload = json.loads(content.decode("utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read model profile: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("model profile must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"model profile is not valid JSON: {exc.msg}") from exc
    try:
        return ModelProfile.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid model profile: {exc}") from exc


def _model_profile_digest(profile: ModelProfile | None) -> str | None:
    if profile is None:
        return None
    encoded = json.dumps(
        profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _controller(args: argparse.Namespace, config: Config) -> LocalController:
    profile = _load_model_profile(getattr(args, "model_profile", None))
    requested_model = getattr(args, "model", None)
    if profile is not None and requested_model is not None and requested_model != profile.model:
        raise ValueError("--model does not match model profile model")
    if profile is not None and not getattr(args, "agent_loop", False):
        raise ValueError("--model-profile requires --agent-loop")
    runtime_model = requested_model or (profile.model if profile is not None else None)
    if profile is not None:
        config = replace(config, runtime_timeout=min(config.runtime_timeout, profile.timeout_seconds))

    def make_runtime():
        runtime = build_runtime(
            args.runtime,
            getattr(args, "runtime_command", None),
            getattr(args, "endpoint", None),
            runtime_model,
            getattr(args, "api_key", None),
        )
        if getattr(args, "agent_loop", False):
            if not isinstance(runtime, OpenAICompatibleRuntime):
                raise ValueError("--agent-loop requires --runtime openai-compatible")
            memory = MemoryStore(config.database) if getattr(args, "memory", False) else None
            tools = LocalToolRegistry(
                allow_exec=getattr(args, "allow_exec", False),
                memory=memory,
                redactions=(runtime.api_key,) if runtime.api_key else (),
            )
            runtime = HermesSessionRuntime(
                runtime,
                tools=tools,
                max_steps=getattr(args, "max_steps", 40),
                memory=memory,
                session_history=getattr(args, "session_history", False),
                profile=profile,
            )
        return runtime

    workers = getattr(args, "workers", 1)
    runtime = make_runtime()
    return LocalController(
        config,
        runtime,
        runtime_factory=make_runtime,
        max_workers=workers,
    )


def _load_plan(path: Path, goal_override: str | None) -> tuple[str, list[dict[str, object]]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise TypeError("plan must be a JSON object")
    plan_goal = goal_override or payload.get("goal")
    if not isinstance(plan_goal, str) or not plan_goal.strip():
        raise ValueError("plan requires a non-empty goal (or a positional goal override)")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        raise TypeError("plan requires a tasks array")
    return plan_goal, tasks


def _load_plan_document(path: Path, goal_override: str | None = None) -> PlanDocument:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
    if goal_override and isinstance(payload, dict):
        payload = {**payload, "goal": goal_override}
    return PlanDocument.from_dict(payload)


def _detach(
    config: Config,
    args: argparse.Namespace,
    goal: str,
    plan_tasks: list[dict[str, object]] | None = None,
) -> object:
    controller = _controller(args, config)
    run = controller.create(goal, plan_tasks)
    staged_inputs = _stage_input_files(
        run, controller.store, getattr(args, "input_files", None)
    )
    log_path = Path(run.workspace) / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "lunar_evolution",
        "resume",
        run.id,
        "--runtime",
        args.runtime,
        "--home",
        str(config.home),
        "--json",
        "--workers",
        str(args.workers),
    ]
    if args.runtime_command:
        command.extend(("--command", args.runtime_command))
    if args.endpoint:
        command.extend(("--endpoint", args.endpoint))
    if args.model:
        command.extend(("--model", args.model))
    if getattr(args, "model_profile", None):
        command.extend(("--model-profile", str(args.model_profile)))
    if args.agent_loop:
        command.append("--agent-loop")
        command.extend(("--max-steps", str(args.max_steps)))
    if args.allow_exec:
        command.append("--allow-exec")
    if args.memory:
        command.append("--memory")
    if args.session_history:
        command.append("--session-history")
    child_env = None
    if args.api_key is not None:
        child_env = os.environ.copy()
        child_env["LUNAR_EVOLUTION_API_KEY"] = args.api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            controller.store.set_runner_process(run.id, pid, pgid)
            latest = controller.store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                controller.store.clear_runner_process(run.id)
    except OSError:
        controller.cancel(run.id)
        raise
    return {
        "run_id": run.id,
        "status": "pending",
        "workspace": str(run.workspace),
        "plan": bool(plan_tasks),
        "workers": args.workers,
        "input_data": list(staged_inputs),
    }


def _print_status(config: Config, run_id: str) -> int:
    store = Store(config.database)
    run = store.get_run(run_id)
    if run is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    projection = _status_payload(config, run.id)
    if projection is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    preparation = _bundle_preparation_payload(store, run.id)
    print(f"run_id: {run.id}")
    print(f"status: {projection['status']}")
    print(f"run_status: {projection['run_status']}")
    print(f"preparation_status: {projection['preparation_status']}")
    print(f"preparation_recoverable: {projection['preparation_recoverable']}")
    print(f"status_reason: {projection['reason_code']}")
    print(f"goal: {run.goal}")
    print(f"workspace: {run.workspace}")
    preparation_budgets = _preparation_budgets_payload(store, run.id)
    if preparation_budgets is not None:
        for name, budget in preparation_budgets.items():
            value = budget["seconds"]
            print(f"{name}: {value if value is not None else 'unbounded'} ({budget['source']})")
    if preparation is not None:
        print(f"evaluator_preparation: {preparation['status']}")
        if preparation.get("error_category"):
            print(f"preparation_error: {preparation['stage']}: {preparation['error_category']}")
        if preparation.get("wall_failure"):
            detail = preparation["wall_failure"]
            print(f"preparation_wall_failure: {detail['reason']} elapsed_ms={detail['elapsed_ms']}"
                  f" wall_timeout_ms={detail['wall_timeout_ms']}")
        if preparation.get("local_failure"):
            detail = preparation["local_failure"]
            positions = " ".join(f"{key}={detail[key]}" for key in
                                 ("probe_index", "input_index", "order_index") if detail[key] is not None)
            print(f"preparation_local_failure: {detail['reason']}" + (f" {positions}" if positions else ""))
        if preparation.get("request_failure"):
            detail = preparation["request_failure"]
            status = detail["response_status"]
            print(f"preparation_request_failure: {detail['reason']}"
                  + (f" response_status={status}" if status is not None else ""))
            request = detail["request_observation"]
            if request is not None:
                print(f"preparation_request_observation: {request['phase']} elapsed_ms={request['elapsed_ms']}"
                      + (f" request_timeout_ms={request['request_timeout_ms']}"
                         if request["request_timeout_ms"] is not None else ""))
            transport = detail["transport_observation"]
            if transport is not None:
                print(f"preparation_transport_observation: {transport['last_milestone']}"
                      f" http_exchange_index={transport['http_exchange_index']} elapsed_ms={transport['elapsed_ms']}")
        if preparation.get("request_failure_hint"):
            print(preparation["request_failure_hint"])
        if preparation.get("resume_hint"):
            print(preparation["resume_hint"])
        if preparation.get("capability_hint"):
            print(preparation["capability_hint"])
            for constraint in preparation["unsupported_constraints"]:
                print(f"unsupported_constraint: {constraint['id']} ({constraint['verification_scope']})")
    if run.runner_pid:
        print(f"runner: pid={run.runner_pid} pgid={run.runner_pgid}")
    pending_input = store.pending_input(run.id)
    if pending_input:
        print(f"awaiting_input: task={pending_input['task_id']}")
        print(f"question: {pending_input['question']}")
        if pending_input["options"]:
            print(f"options: {', '.join(pending_input['options'])}")
    for task in store.list_tasks(run.id):
        print(
            f"task: {task.id} state={task.state.value} attempts={task.attempts}"
            + (f" error={task.last_error}" if task.last_error else "")
            + (f" depends_on={','.join(task.dependencies)}" if task.dependencies else "")
        )
    artifacts = store.list_artifacts(run.id)
    for artifact in artifacts:
        print(
            f"artifact: {artifact['path']} kind={artifact['kind']} size={artifact['size']} sha256={artifact['sha256']}"
        )
    return 0


def _status_projection(
    run: Run,
    *,
    preparation: dict[str, object] | None = None,
    evolution_status: str | None = None,
    materialization_status: str | None = None,
) -> dict[str, object]:
    """Project stable public status without changing the persisted parent state."""
    persisted = run.status.value
    preparation_status = preparation.get("status") if isinstance(preparation, dict) else None
    recoverable = bool(
        isinstance(preparation, dict) and preparation.get("recoverable") is True
    )

    # Cancellation wins.  Composite delivery failures may override a succeeded intake;
    # preparation alone cannot rewrite a terminal parent's effective or persisted state.
    if persisted == "cancelled":
        effective, reason = "cancelled", "cancelled"
    elif materialization_status == "failed":
        effective, reason = "failed", "materialization_failed"
    elif evolution_status == "failed":
        effective, reason = "failed", "evolution_failed"
    elif persisted in {"failed", "succeeded"}:
        effective, reason = persisted, f"terminal_{persisted}"
    elif preparation_status in {"failed", "unknown"}:
        category = preparation.get("error_category") if isinstance(preparation, dict) else None
        reason_by_category = {
            "cancelled": "cancelled",
            "preparation_timeout": "preparation_timeout",
            "runtime_error": "preparation_runtime_error",
            "validation_error": "preparation_validation_error",
            "unsupported_verification": "preparation_unsupported",
            "interrupted": "preparation_unknown",
        }
        effective = "failed"
        reason = reason_by_category.get(category, "preparation_failed" if preparation_status == "failed"
                                        else "preparation_unknown")
    else:
        effective, reason = persisted, f"run_{persisted}"

    return {
        "status": effective,
        "run_status": persisted,
        "preparation_status": preparation_status,
        "preparation_recoverable": recoverable,
        "reason_code": reason,
    }


def _status_payload(config: Config, run_id: str) -> dict[str, object] | None:
    store = Store(config.database)
    run = store.get_run(run_id)
    if run is None:
        return None
    tasks = store.list_tasks(run.id)
    current_plan = store.get_current_plan(run.id)
    events = store.list_events(run.id)
    latest_evaluations = {
        event["task_id"]: {
            "event_id": event["id"],
            "created_at": event["created_at"],
            **event["payload"],
        }
        for event in events
        if event["type"] == "task_evaluated" and event["task_id"] is not None
    }
    latest_agents = {
        event["task_id"]: {
            "event_id": event["id"],
            "created_at": event["created_at"],
            **event["payload"],
        }
        for event in events
        if event["type"] in {"agent_finished", "agent_failed"} and event["task_id"] is not None
    }
    latest_recovery = next(
        (
            event["payload"].get("proposal")
            for event in reversed(events)
            if event["type"] == "recovery_proposed"
            and isinstance(event["payload"].get("proposal"), dict)
        ),
        None,
    )
    algorithm_manifest = None
    if current_plan is not None and current_plan.algorithm_problem is not None:
        algorithm_manifest = next(
            (item for item in reversed(store.list_artifacts(run.id)) if item["kind"] == "algorithm_manifest"),
            None,
        )
    conversation_manifest = _conversation_manifest(run)
    evolution_finished = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_finished" and isinstance(event["payload"], dict)
        ),
        None,
    )
    evolution_configured = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_configured" and isinstance(event["payload"], dict)
        ),
        None,
    )
    evolution_iterations = (
        evolution_finished.get("iterations")
        if isinstance(evolution_finished, dict) and isinstance(evolution_finished.get("iterations"), int)
        else sum(1 for event in events if event["type"] == "evolution_iteration")
    )
    evolution_candidates = (
        evolution_finished.get("evaluated_candidates")
        if isinstance(evolution_finished, dict) and isinstance(evolution_finished.get("evaluated_candidates"), int)
        else sum(1 for event in events if event["type"] == "evolution_candidate_archived")
    )
    evolution_link = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_linked" and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    evolution_materialization = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] in {"evolved_candidate_materialized", "bundle_candidate_delivered"}
            and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    linked_evolution = None
    if evolution_link is not None:
        child_id = evolution_link.get("evolution_run_id")
        if isinstance(child_id, str):
            child = store.get_run(child_id)
            if child is not None:
                child_events = store.list_events(child.id)
                child_result = next(
                    (
                        event["payload"]
                        for event in reversed(child_events)
                        if event["type"] == "evolution_finished"
                        and isinstance(event.get("payload"), dict)
                    ),
                    None,
                )
                linked_evolution = {
                    "run_id": child.id,
                    "status": child.status.value,
                    "workspace": str(child.workspace),
                    "strategy": evolution_link.get("strategy"),
                    "result": child_result,
                    "materialization": evolution_materialization,
                }
            else:
                linked_evolution = {"run_id": child_id, "status": "missing"}
    artifacts = store.list_artifacts(run.id)
    algorithm_outputs = [item for item in artifacts if item["kind"] == "output"]
    role_evidence = [item for item in artifacts if item["kind"] == "role_evidence"]
    preparation = _bundle_preparation_payload(store, run.id)
    preparation_budgets = _preparation_budgets_payload(store, run.id)
    projection = _status_projection(
        run,
        preparation=preparation,
        evolution_status=(linked_evolution.get("status") if linked_evolution else None),
        materialization_status=(
            evolution_materialization.get("status")
            if isinstance(evolution_materialization, dict) else None
        ),
    )
    return {
        **projection,
        **({"solve_execution": execution_status} if (execution_status := solve_execution_status(store, run)) is not None else {}),
        "run": {
            "id": run.id,
            "goal": run.goal,
            "status": run.status.value,
            "workspace": str(run.workspace),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "runner_pid": run.runner_pid,
            "runner_pgid": run.runner_pgid,
            "current_plan_id": run.current_plan_id,
            "current_plan_version": run.current_plan_version,
            "route_domain": run.route_domain,
            "route_reason": run.route_reason,
            "route_confidence": run.route_confidence,
            "solver_profile": run.solver_profile,
            "evaluator_profile": run.evaluator_profile,
            "required_capabilities": list(run.route_required_capabilities),
            "route_evidence": list(run.route_evidence),
            "budget": (run.budget or BudgetSpec()).to_dict(),
        },
        "route": {
            "domain": run.route_domain,
            "reason": run.route_reason,
            "confidence": run.route_confidence,
            "solver_profile": run.solver_profile,
            "evaluator_profile": run.evaluator_profile,
            "required_capabilities": list(run.route_required_capabilities),
            "evidence": list(run.route_evidence),
        } if run.route_domain else None,
        "budget": (run.budget or BudgetSpec()).to_dict(),
        "tasks": [
            {
                "id": task.id,
                "plan_task_id": task.plan_task_id,
                "run_id": task.run_id,
                "title": task.title,
                "state": task.state.value,
                "attempts": task.attempts,
                "result_path": str(task.result_path) if task.result_path else None,
                "last_error": task.last_error,
                "dependencies": list(task.dependencies),
                "acceptance": task.acceptance,
                "evaluation": latest_evaluations.get(task.id),
                "agent": latest_agents.get(task.id),
            }
            for task in tasks
        ],
        "artifacts": artifacts,
        # Keep structured data discoverable without requiring callers to filter the complete
        # audit ledger.  The rows remain the same hashed, run-relative artifact metadata.
        "algorithm_outputs": algorithm_outputs,
        "role_evidence": role_evidence,
        "input_request": store.pending_input(run.id),
        "recovery": latest_recovery,
        "plan": current_plan.to_dict() if current_plan else None,
        "algorithm_problem": current_plan.algorithm_problem if current_plan else None,
        "algorithm_workspace": algorithm_manifest,
        "conversation": conversation_manifest,
        "evolution": {
            "configured": evolution_configured,
            "result": evolution_finished,
            "iterations": evolution_iterations,
            "candidates": evolution_candidates,
            "linked": linked_evolution,
            **({"preparation": preparation} if preparation is not None else {}),
            **({"preparation_budgets": preparation_budgets} if preparation_budgets is not None else {}),
        } if (evolution_configured or evolution_finished or linked_evolution or preparation
              or preparation_budgets) else None,
        "decisions": store.list_decisions(run.id),
        "agents": [
            {"task_id": task_id, **payload}
            for task_id, payload in latest_agents.items()
        ],
    }


def _print_events(config: Config, run_id: str) -> int:
    store = Store(config.database)
    if store.get_run(run_id) is None:
        print(f"unknown run: {run_id}", file=sys.stderr)
        return 2
    for event in store.list_events(run_id):
        task = f" task={event['task_id']}" if event["task_id"] else ""
        print(f"{event['created_at']} {event['type']}{task} {event['payload']}")
    return 0


def _emit(payload: object, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
        return
    print(payload)


def _loop_retirement_payload() -> dict[str, str]:
    return {
        "error": LOOP_STRATEGY_RETIRED,
        "message": LOOP_STRATEGY_RETIREMENT_HINT,
    }


def _emit_error(message: str, json_mode: bool) -> None:
    if json_mode:
        payload = {"error": message}
        if message in {LOOP_STRATEGY_RETIRED, LOOP_STRATEGY_RETIRED_MESSAGE}:
            payload = _loop_retirement_payload()
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)


def _parse_command(value: str | None, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        command = tuple(shlex.split(value))
    except ValueError as exc:
        raise ValueError(f"{label} is not valid shell-like argument text: {exc}") from exc
    if not command:
        raise ValueError(f"{label} must not be empty")
    return command


def _effect_mapping(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise ValueError(f"{label} must use KEY=PATH")
        key, raw_path = value.split("=", 1)
        if not key or not raw_path or key in result:
            raise ValueError(f"{label} must contain unique non-empty KEY=PATH entries")
        result[key] = Path(raw_path)
    return result


def _effect_environment(names: list[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        if name in result:
            raise ValueError(f"{label} environment names must be unique")
        value = os.environ.get(name)
        if value is None:
            raise ValueError(f"{label} environment variable is not set: {name}")
        result[name] = value
    return result


def _adapter_fingerprint(
    command: tuple[str, ...],
    *,
    kind: str,
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
) -> str | None:
    """Return a credential-safe identity for one explicit evolution adapter."""
    if not command:
        return None
    payload = {
        "command": list(command),
        "kind": kind,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _portfolio_fingerprint(
    commands: tuple[tuple[str, ...], ...],
    *,
    kind: str = "portfolio-generator",
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
) -> str | None:
    """Return a digest for an ordered portfolio without persisting raw command arguments."""
    if not commands:
        return None
    payload = {
        "commands": [list(command) for command in commands],
        "kind": kind,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _runtime_fingerprint(
    runtime_name: str,
    *,
    command: tuple[str, ...] = (),
    endpoint: str | None = None,
    model: str | None = None,
    name: str,
    role: str,
    required_capabilities: tuple[str, ...] = (),
    agent_loop: bool = False,
    loop_max_steps: int = 40,
    loop_allow_exec: bool = False,
    loop_memory: bool = False,
    loop_session_history: bool = False,
    model_profile: ModelProfile | None = None,
) -> str:
    """Return a credential-safe identity for one repository-owned runtime Agent."""
    payload = {
        "command": list(command),
        "endpoint": endpoint,
        "kind": "runtime",
        "model": model,
        "name": name,
        "required_capabilities": sorted(set(required_capabilities)),
        "role": role,
        "runtime": runtime_name,
    }
    if model_profile is not None:
        payload["model_profile_sha256"] = _model_profile_digest(model_profile)
    if agent_loop:
        payload["agent_loop"] = {
            "allow_exec": loop_allow_exec,
            "max_steps": loop_max_steps,
            "memory": loop_memory,
            "session_history": loop_session_history,
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_evolution_runtime(
    config: Config,
    args: argparse.Namespace,
    runtime_name: str,
    command: tuple[str, ...],
    endpoint: str | None,
    model: str | None,
    api_key: str | None,
) -> object:
    """Construct one fresh repository runtime for an evolution role."""
    runtime = build_runtime(runtime_name, command or None, endpoint, model, api_key)
    if not args.agent_runtime_loop:
        return runtime
    if not isinstance(runtime, OpenAICompatibleRuntime):
        raise ValueError(  # noqa: TRY004 - this is a user-facing option conflict
            "--agent-runtime-loop requires --agent-runtime openai-compatible"
        )
    memory = MemoryStore(config.database) if args.agent_runtime_memory else None
    if memory is not None:
        memory.initialize()
    tools = LocalToolRegistry(
        allow_exec=args.agent_runtime_allow_exec,
        memory=memory,
        redactions=(runtime.api_key,) if runtime.api_key else (),
    )
    return AgentLoopRuntime(
        runtime,
        tools=tools,
        max_steps=args.agent_runtime_max_steps,
        memory=memory,
        session_history=args.agent_runtime_session_history,
    )


def _runner_fingerprint(command: tuple[str, ...], timeout: float) -> str | None:
    """Return a credential-safe identity for an explicit candidate runner."""
    if not command:
        return None
    payload = {
        "command": list(command),
        "kind": "candidate-runner",
        "timeout": timeout,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _candidate_input_artifacts(store: Store, run_id: str) -> tuple[CandidateInputArtifact, ...]:
    """Project the durable input ledger into path-free execution descriptors."""
    by_path: dict[str, CandidateInputArtifact] = {}
    for item in store.list_artifacts(run_id):
        if item.get("kind") != "input_data":
            continue
        try:
            descriptor = CandidateInputArtifact(
                path=item.get("path"),  # type: ignore[arg-type]
                size=item.get("size"),  # type: ignore[arg-type]
                sha256=item.get("sha256"),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise EvolutionError("run input artifact metadata is malformed") from exc
        existing = by_path.get(descriptor.path)
        if existing is not None and existing != descriptor:
            raise EvolutionError(
                f"run input ledger contains conflicting evidence: {descriptor.path}"
            )
        by_path[descriptor.path] = descriptor
    return tuple(by_path[path] for path in sorted(by_path))


def _compiler_fingerprint(runtime: object) -> str:
    """Return a credential-safe identity for the solve contract compiler runtime."""
    candidate = getattr(runtime, "model", None)
    provider = runtime if isinstance(candidate, str) else (candidate or runtime)
    profile = getattr(runtime, "profile", None)
    payload = {
        "kind": "contract-compiler",
        "runtime": getattr(runtime, "name", type(runtime).__name__),
        "command": list(getattr(provider, "command", ()) or ()),
        "endpoint": getattr(provider, "endpoint", None),
        "model": getattr(provider, "model", None),
        "mode": getattr(runtime, "name", "runtime"),
    }
    if isinstance(profile, ModelProfile):
        payload["model_profile_sha256"] = _model_profile_digest(profile)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _conversation_manifest(run: Run) -> dict[str, object] | None:
    path = Path(run.workspace) / "solve" / "compiler-manifest.json"
    try:
        path.resolve(strict=False).relative_to(Path(run.workspace).resolve())
    except ValueError:
        return None
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _conversation_plan_factory(
    args: argparse.Namespace, manifest: dict[str, object] | None = None
) -> object | None:
    """Resolve role-plan mode, preferring the persisted mode during answer/resume."""
    if getattr(args, "role_dag", False) or (
        manifest is not None and manifest.get("plan_kind") == "role_dag"
    ):
        return build_algorithm_role_plan
    return None


def _read_conversation_goal(args: argparse.Namespace) -> str:
    if args.goal == "-":
        goal = sys.stdin.read()
    elif isinstance(args.goal, str):
        goal = args.goal
    else:
        goal = ""
    if not goal.strip():
        raise ValueError("solve requires a goal or --run-id with --resume")
    if len(goal.encode("utf-8")) > 8_000:
        raise ValueError("solve goal exceeds 8 KiB")
    return goal.strip()


def _safe_input_destination(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("input destination must be non-empty")
    value = value.strip()
    if "\\" in value or "\x00" in value:
        raise ValueError("input destination must be a portable relative path")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("input destination must be a portable relative path")
    return "/".join(candidate.parts)


def _input_source_and_destination(raw: object) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("--input requires SOURCE or SOURCE=DEST")
    source_text, separator, destination = raw.partition("=")
    source = Path(source_text if separator else raw).expanduser()
    if not source_text.strip():
        raise ValueError("--input source must be non-empty")
    if source.is_symlink():
        raise ValueError(f"input source must not be a symlink: {source}")
    source_path = source.resolve(strict=False)
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError(f"input source is not a regular file: {source}")
    target = destination.strip() if separator else source_path.name
    return source_path, _safe_input_destination(target)


def _path_has_symlink(root: Path, path: Path) -> bool:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            return True
        if current == root:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _stage_input_files(
    run: Run, store: Store, raw_inputs: list[str] | tuple[str, ...] | None
) -> tuple[str, ...]:
    """Copy explicit user data into a run-relative, hashed ``data/raw`` directory.

    Staging is idempotent for the same path and bytes, which lets a parent Agent safely retry a
    detached ``solve`` invocation. A different file at an existing destination is rejected rather
    than silently changing the problem underneath an immutable run.
    """
    values = tuple(raw_inputs or ())
    if len(values) > MAX_INPUT_FILES:
        raise ValueError(f"at most {MAX_INPUT_FILES} input files may be staged")
    if not values:
        return ()
    root = Path(run.workspace).expanduser().resolve(strict=False)
    raw_root = root / "data" / "raw"
    if _path_has_symlink(root, raw_root):
        raise ValueError("run data/raw directory must not be a symlink")
    raw_root.mkdir(parents=True, exist_ok=True)
    tasks = store.list_tasks(run.id)
    if not tasks:
        raise ValueError("run has no task to own staged input artifacts")
    owner_task = tasks[0].id
    artifact_store = ArtifactStore(root, store, run.id)
    staged: list[str] = []
    for raw in values:
        source, destination = _input_source_and_destination(raw)
        size = source.stat().st_size
        if size > MAX_INPUT_FILE_BYTES:
            raise ValueError(
                f"input source exceeds {MAX_INPUT_FILE_BYTES} bytes: {source}"
            )
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        target = root / "data" / "raw" / destination
        if _path_has_symlink(root, target):
            raise ValueError(f"input destination is symlinked: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"input destination already contains different data: {destination}")
        else:
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(content)
            temporary.replace(target)
        relative = f"data/raw/{destination}"
        if not any(
            item["path"] == relative
            and item["kind"] == "input_data"
            and item["sha256"] == digest
            for item in store.list_artifacts(run.id)
        ):
            artifact_store.record(target, owner_task, kind="input_data")
        store.append_event(
            run.id,
            "algorithm_input_staged",
            {"path": relative, "size": size, "sha256": digest},
            task_id=owner_task,
            event_id=f"event-algorithm-input-{run.id}-{hashlib.sha256(relative.encode()).hexdigest()}",
        )
        staged.append(relative)
    return tuple(staged)


def _prepare_conversational_bundle(args: argparse.Namespace) -> None:
    """Load explicit bundle authority without retaining local profile paths in run events."""
    if getattr(args, "multi_file", False):
        _validate_automatic_bundle_options(args)
        return
    path = getattr(args, "bundle_profile", None)
    if path is None:
        return
    if args.command == "solve" and not (args.evolve or args.resume):
        raise ValueError("--bundle-profile requires --evolve")
    if getattr(args, "detach", False):
        raise ValueError("--bundle-profile does not support --detach")
    if (
        getattr(args, "compile_evaluator", False)
        or getattr(args, "evaluator_command", None)
        or getattr(args, "openevolve_command", None)
        or getattr(args, "strategy", None) not in {None, "population"}
    ):
        raise ValueError("--bundle-profile requires native population and its own exact evaluator")
    from .bundle_evolution import load_bundle_pipeline
    from .solve_bundle import bundle_pipeline_sha256

    pipeline = load_bundle_pipeline(path)
    args._bundle_pipeline = pipeline
    args._bundle_profile_sha256 = bundle_pipeline_sha256(pipeline)


def _validate_automatic_bundle_options(args) -> None:
    if args.command == "solve" and not (args.evolve or args.resume):
        raise ValueError("--multi-file requires --evolve")
    if (getattr(args, "bundle_profile", None) is not None
            or getattr(args, "evaluator_command", None)
            or getattr(args, "openevolve_command", None)
            or getattr(args, "strategy", None) not in {None, "population"}):
        raise ValueError("--multi-file requires native population and its automatically compiled evaluator")


def _validate_automatic_detach(args, request: dict | None) -> None:
    """Admit background continuation only for the explicitly versioned automatic lifecycle."""
    worker = getattr(args, "_automatic_owner", None) is not None
    if not getattr(args, "detach", False) and not worker:
        return
    if (not worker and args.command == "solve" and not getattr(args, "resume", False)):
        # Existing ordinary fresh solves retain their separate launcher.
        return
    if not (
        isinstance(request, dict)
        and request.get("bundle_mode") == "compiled"
        and type(request.get("automatic_lifecycle_version")) is int
        and request["automatic_lifecycle_version"] == _AUTOMATIC_LIFECYCLE_VERSION
    ):
        raise ValueError("--detach requires a lifecycle-enabled automatic multi-file solve")


def _validate_candidate_generation_value(value: object, *, error_type=ValueError) -> None:
    """Validate the explicit native automatic candidate-generation ceiling."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_CANDIDATE_TOOL_STEPS
    ):
        raise error_type(
            "--candidate-generation-max-steps must be an integer between "
            f"1 and {MAX_CANDIDATE_TOOL_STEPS}"
        )


def _validate_candidate_generation_option(
    args: argparse.Namespace,
    request: dict[str, object] | None = None,
    *,
    allow_unresolved_handoff: bool = True,
) -> None:
    """Validate candidate-generation policy before preparation or continuation side effects."""
    supplied = getattr(args, "candidate_generation_max_steps", None)
    if supplied is not None:
        _validate_candidate_generation_value(supplied)

    if request is not None:
        stored = request.get("candidate_generation_max_steps")
        source = request.get("candidate_generation_max_steps_source")
        if (stored is not None or source is not None) and request.get("bundle_mode") != "compiled":
            raise EvolutionError("solve evolution candidate generation setting is invalid")
        if stored is None:
            if (
                "candidate_generation_max_steps" in request
                or "candidate_generation_max_steps_source" in request
            ):
                raise EvolutionError("solve evolution candidate generation setting is invalid")
            if supplied is not None:
                raise EvolutionError(
                    "solve evolution candidate generation setting does not match the existing handoff"
                )
            return
        try:
            _validate_candidate_generation_value(stored, error_type=EvolutionError)
        except EvolutionError:
            raise EvolutionError("solve evolution candidate generation setting is invalid") from None
        if source != "explicit":
            raise EvolutionError("solve evolution candidate generation source is invalid")
        if supplied is not None and supplied != stored:
            raise EvolutionError(
                "solve evolution candidate generation setting does not match the existing handoff"
            )
        _validate_automatic_bundle_options(args)
        return

    if supplied is None:
        return
    command = getattr(args, "command", None)
    if allow_unresolved_handoff and command == "solve" and getattr(args, "resume", False):
        # A resumed solve may discover its persisted automatic handoff below.
        return
    if allow_unresolved_handoff and command in {"resume", "answer"}:
        # These commands resolve the persisted handoff after local state is opened.
        return
    if command != "solve" or not getattr(args, "evolve", False) or not getattr(args, "multi_file", False):
        raise ValueError(
            "--candidate-generation-max-steps requires --evolve --multi-file"
        )
    if (
        getattr(args, "bundle_profile", None) is not None
        or getattr(args, "evaluator_command", None)
        or getattr(args, "openevolve_command", None)
        or getattr(args, "strategy", None) not in {None, "population"}
    ):
        raise ValueError(
            "--candidate-generation-max-steps requires native automatic multi-file evolution"
        )


def _validate_conversational_bundle_request(args, request) -> None:
    mode = request.get("bundle_mode") if request is not None else None
    if request is not None and "bundle_mode" in request:
        if (mode != "compiled" or request.get("compile_evaluator") is not True
                or "bundle_profile_sha256" in request
                or request.get("evaluator_command_configured") is not False
                or request.get("openevolve_command_configured") is not False
                or request.get("strategy") not in {None, "population"}):
            raise EvolutionError("solve_bundle_mode_invalid")
        _validate_automatic_bundle_options(args)
        _validate_preparation_request(request)
        _validate_solve_wall_timeout_option(args, request)
        args.multi_file = True
        args.compile_evaluator = True
        return
    if getattr(args, "multi_file", False) and (
        request is not None or args.command in {"answer", "resume"} or getattr(args, "resume", False)
    ):
        raise EvolutionError("solve_bundle_mode_mismatch")
    expected = request.get("bundle_profile_sha256") if request is not None else None
    supplied = getattr(args, "_bundle_profile_sha256", None)
    if request is not None and "bundle_profile_sha256" in request and (
        not isinstance(expected, str) or len(expected) != 64
        or any(char not in "0123456789abcdef" for char in expected)
    ):
        raise EvolutionError("solve_bundle_profile_marker_invalid")
    if expected is not None and supplied is None:
        raise EvolutionError("solve_bundle_profile_required")
    if expected != supplied:
        raise EvolutionError("solve_bundle_profile_mismatch")


def _bind_conversational_bundle_inputs(args, store, parent) -> None:
    if getattr(args, "_bundle_pipeline", None) is not None:
        from .solve_bundle import prepare_solve_bundle_pipeline

        args._bundle_pipeline = prepare_solve_bundle_pipeline(
            store, parent.id, args._bundle_pipeline,
        )


def _solve(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Compile and execute one conversational algorithm mission."""
    if args.compile_evaluator and not (args.evolve or args.resume):
        raise ValueError("--compile-evaluator requires --evolve")
    if not args.evolve and any(
        getattr(args, name, None) is not None
        for name in (
            "strategy",
            "openevolve_command",
            "evaluator_command",
            "max_rounds",
            "stagnation_rounds",
            "population_size",
            "offspring_per_iteration",
            "islands",
            "migration_interval",
            "migration_rate",
            "seed",
            "timeout",
        )
    ):
        raise ValueError("evolution options require --evolve")
    if (
        not args.evolve
        and not args.resume
        and _has_preparation_timeout(args)
    ):
        raise ValueError("evolution options require --evolve")
    preparation_request = None
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        preparation_request = _latest_evolution_request(Store(config.database), args.run_id)
        _validate_automatic_detach(args, preparation_request)
        if preparation_request is not None:
            _validate_solve_wall_timeout_option(args, preparation_request)
        elif getattr(args, "solve_wall_timeout", None) is not None:
            _validate_solve_wall_timeout_option(
                args, None, allow_unresolved_handoff=False,
            )
        if preparation_request is None and getattr(args, "candidate_generation_max_steps", None) is not None and not args.evolve:
            raise ValueError(
                "--candidate-generation-max-steps requires an automatic multi-file evolution handoff"
            )
        if preparation_request is not None:
            _validate_candidate_generation_option(args, preparation_request)
        if preparation_request is not None and preparation_request.get("bundle_mode") == "compiled":
            _validate_preparation_request(preparation_request)
            _validate_evolution_override(args, preparation_request)
        if _has_preparation_timeout(args) and not (args.evolve and preparation_request is None):
            _validate_preparation_timeout_override(args, preparation_request)
    if args.evolve:
        _validate_candidate_generation_option(
            args, preparation_request, allow_unresolved_handoff=False,
        )
        persisted_compiled = (
            preparation_request is not None and preparation_request.get("bundle_mode") == "compiled"
        )
        _validate_evolution_cli_bounds(
            _evolution_args(args, preparation_request) if persisted_compiled else args,
        )
        if args.compile_evaluator and args.evaluator_command:
            raise ValueError("--compile-evaluator and --evaluator-command are mutually exclusive")
        if args.strategy == "openevolve" and args.compile_evaluator:
            raise ValueError("--compile-evaluator is supported only by native evolution strategies")
    controller = _controller(args, config)
    runtime = controller.runtime
    fingerprint = _compiler_fingerprint(runtime)
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        run = controller.store.get_run(args.run_id)
        if run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        current_plan = controller.store.get_current_plan(run.id)
        if current_plan is not None and current_plan.algorithm_problem is not None:
            current_contract = AlgorithmProblemContract.from_dict(current_plan.algorithm_problem)
            if current_contract.evolution.strategy == "loop":
                raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
        if args.workspace is not None and args.workspace.expanduser().resolve() != run.workspace:
            raise ValueError("--workspace does not match the existing conversational run")
        manifest = _conversation_manifest(run)
        if manifest is not None and manifest.get("runtime_fingerprint") not in {None, fingerprint}:
            raise ValueError("solve resume compiler runtime does not match the existing run")
        evolution_request = _latest_evolution_request(controller.store, run.id)
        if args.compile_evaluator and not args.evolve and evolution_request is None:
            raise ValueError("--compile-evaluator requires an existing evolution handoff")
        if args.evolve and evolution_request is None:
            controller.store.append_event(
                run.id,
                "evolution_requested",
                _evolution_request_payload(args),
                event_id="event-evolution-request-" + hashlib.sha256(run.id.encode()).hexdigest(),
            )
            evolution_request = _evolution_request_payload(args)
        if (
            args.evolve
            or args.compile_evaluator
            or _has_preparation_timeout(args)
        ) and evolution_request is not None:
            _validate_evolution_override(args, evolution_request)
        _validate_conversational_bundle_request(args, evolution_request)
        if evolution_request is not None and (
            "bundle_profile_sha256" in evolution_request or "bundle_mode" in evolution_request
        ):
            _validate_evolution_override(args, evolution_request)
        if _lifecycle_enabled(evolution_request) and run.status.value in {"failed", "cancelled"}:
            return _solve_payload(controller, run)
        _validate_conversational_bundle_link(args, controller.store, run)
        if _lifecycle_enabled(evolution_request):
            return _continue_automatic_solve(
                config, _evolution_args(args, evolution_request), controller, run, manifest,
            )
        _stage_input_files(run, controller.store, args.input_files)
        _bind_conversational_bundle_inputs(args, controller.store, run)
        settled = controller.resume_conversational(
            run.id,
            RuntimeContractCompiler(runtime),
            compiler_fingerprint=fingerprint,
            plan_factory=_conversation_plan_factory(args, manifest),
            execute_plan=not args.evolve and evolution_request is None,
        )
        effective_args = _evolution_args(args, evolution_request)
        if effective_args.evolve and settled.current_plan_id is not None:
            _bind_solve_execution_control(effective_args, controller, settled)
            _solve_evolution(config, effective_args, controller, settled)
            settled = controller.store.get_run(settled.id) or settled
        return _solve_payload(controller, settled)
    goal = _read_conversation_goal(args)
    run = controller.create_conversational_run(
        goal, workspace=args.workspace, compiler_fingerprint=fingerprint
    )
    evolution_request = None
    if args.evolve:
        evolution_request = _evolution_request_payload(args)
        controller.store.append_event(
            run.id,
            "evolution_requested",
            evolution_request,
            event_id="event-evolution-request-" + hashlib.sha256(run.id.encode()).hexdigest(),
        )
    if _lifecycle_enabled(evolution_request):
        run.workspace.mkdir(parents=True, exist_ok=True)
        return _continue_automatic_solve(
            config, _evolution_args(args, evolution_request), controller, run,
        )
    _stage_input_files(run, controller.store, args.input_files)
    _bind_conversational_bundle_inputs(args, controller.store, run)
    if args.detach:
        return _detach_solve(config, args, run)
    settled = controller.resume_conversational(
        run.id,
        RuntimeContractCompiler(runtime),
        compiler_fingerprint=fingerprint,
        plan_factory=_conversation_plan_factory(args),
        execute_plan=not args.evolve,
    )
    effective_args = _evolution_args(args, evolution_request)
    if effective_args.evolve and settled.current_plan_id is not None:
        _bind_solve_execution_control(effective_args, controller, settled)
        _solve_evolution(config, effective_args, controller, settled)
        settled = controller.store.get_run(settled.id) or settled
    return _solve_payload(controller, settled)


def _bind_solve_execution_control(
    args: argparse.Namespace, controller: LocalController, run: Run,
    *, observe_stage=None,
) -> None:
    """Attach one process-local solve deadline to an automatic multi-file execution."""
    timeout = getattr(args, "solve_wall_timeout", None)
    if not getattr(args, "multi_file", False) or timeout is None:
        return
    args._solve_execution_control = SolveExecutionControl(
        timeout,
        observe_stage=observe_stage,
        cancellation_callbacks=(
            lambda: (
                (current := controller.store.get_run(run.id)) is None
                or current.status.value == "cancelled"
            ),
        ),
    )


def _lifecycle_enabled(request: dict | None) -> bool:
    return (isinstance(request, dict) and request.get("bundle_mode") == "compiled"
            and request.get("automatic_lifecycle_version") == _AUTOMATIC_LIFECYCLE_VERSION)


def _automatic_solve_child(controller: LocalController, parent: Run) -> Run | None:
    """Select only the reciprocally bound child for this exact accepted contract."""
    scope = controller._automatic_cancel_targets(parent.id)
    if scope is None or not scope.verified or scope.child_id is None:
        return None
    return controller.store.get_run(scope.child_id)


def _continue_automatic_solve(config, args, controller, run, manifest=None) -> dict[str, object]:
    """Reserve one execution before staging inputs or starting a foreground/background owner."""
    if run.status.value in {"succeeded", "failed", "cancelled"} or controller.store.pending_input(run.id) is not None:
        return _solve_payload(controller, run)
    from .automatic_solve_worker import launch_automatic_solve, prepare_automatic_continuation

    inherited_owner = getattr(args, "_automatic_owner", None)
    ownership = (
        nullcontext(inherited_owner) if inherited_owner is not None
        else own_automatic_solve(run.id, Path(run.workspace))
    )
    with ownership as owner:
        run = controller.store.get_run(run.id) or run
        if run.status.value in {"succeeded", "failed", "cancelled"} or controller.store.pending_input(run.id) is not None:
            return _solve_payload(controller, run)
        prepare_automatic_continuation(controller, run)
        run = controller.store.get_run(run.id) or run
        if run.status.value in {"succeeded", "failed", "cancelled"} or controller.store.pending_input(run.id) is not None:
            return _solve_payload(controller, run)
        _stage_input_files(run, controller.store, getattr(args, "input_files", []))
        _bind_conversational_bundle_inputs(args, controller.store, run)
        if getattr(args, "detach", False):
            launch_automatic_solve(config, args, controller, run, owner)
            payload = _solve_payload(controller, controller.store.get_run(run.id) or run)
            return {**payload, "detached": True, "launch_status": "accepted"}
        settled = _resume_automatic_solve(
            config, args, controller, run, manifest, owner_held=True,
        )
        return _solve_payload(controller, settled)


def _resume_automatic_solve(config, args, controller, run, manifest=None, *, owner_held=False) -> Run:
    """One admitted foreground execution spans intake, preparation, evolution and delivery."""
    if run.status.value in {"succeeded", "failed", "cancelled"} or controller.store.pending_input(run.id) is not None:
        return run
    from .automatic_solve_bundle import validate_automatic_preparation_recovery

    validate_automatic_preparation_recovery(controller.store, run.id)
    with (nullcontext() if owner_held else own_automatic_solve(run.id, Path(run.workspace))):
        run = controller.store.get_run(run.id) or run
        if run.status.value in {"succeeded", "failed", "cancelled"}:
            return run
        observation = SolveExecutionObservation(controller.store, run.id, getattr(args, "solve_wall_timeout", None))
        _bind_solve_execution_control(args, controller, run, observe_stage=observation.observe)
        args._solve_owner_held = True
        args._solve_observation = observation
        try:
            settled = controller.resume_conversational(
                run.id, RuntimeContractCompiler(controller.runtime),
                compiler_fingerprint=_compiler_fingerprint(controller.runtime),
                plan_factory=_conversation_plan_factory(args, manifest), execute_plan=False,
                solve_control=getattr(args, "_solve_execution_control", None),
            )
            if settled.current_plan_id is not None and settled.status.value not in {"failed", "cancelled"}:
                _solve_evolution(config, args, controller, settled)
        except SolveExecutionBudgetExceeded as exc:
            controller.store.fail_budget(run.id, exc.limit, exc.actual, exc.maximum, str(exc))
            child = _automatic_solve_child(controller, run)
            if child is not None:
                if controller.store.get_run(run.id).status.value == "cancelled":
                    controller.store.cancel_run(child.id)
                else:
                    controller.store.fail_budget(child.id, exc.limit, exc.actual, exc.maximum, str(exc))
            controller.cleanup_automatic_solve(run.id)
        except SolveExecutionCancelled:
            controller.cancel(run.id)
            controller.cleanup_automatic_solve(run.id)
        except Exception:
            for task in controller.store.list_tasks(run.id):
                if task.orchestration and (attempt := controller.store.active_attempt(task.id)) is not None:
                    controller.store.finish_task(task.id, attempt.id, False, error="automatic solve failed")
            controller.store.settle_run(run.id)
            raise
        finally:
            args._solve_owner_held = False
            current = controller.store.get_run(run.id) or run
            state, reason = "inactive", "interrupted"
            if current.status.value in {"succeeded", "failed", "cancelled"}:
                state = "terminal"
                reason = {"succeeded": "completed", "failed": "failed", "cancelled": "cancelled"}[current.status.value]
                if current.status.value == "failed" and any(
                    e["type"] == "budget_exceeded" and e["payload"].get("limit") == "solve_wall_timeout"
                    for e in controller.store.list_events(run.id)
                ):
                    reason = "solve_wall_timeout"
            elif current.status.value == "awaiting_input":
                state, reason = "awaiting_input", "awaiting_input"
            else:
                preparation = _bundle_preparation_payload(controller.store, run.id)
                if preparation and preparation.get("recoverable"):
                    reason = "preparation_recoverable"
            observation.observe(observation.stage, state=state, reason=reason)
        return controller.store.get_run(run.id) or run


def _evolution_request_payload(args: argparse.Namespace) -> dict[str, object]:
    """Return only bounded, non-secret settings needed to continue a solve handoff."""
    _validate_candidate_generation_option(args, allow_unresolved_handoff=False)
    payload = {
        "strategy": args.strategy,
        "max_rounds": args.max_rounds,
        "stagnation_rounds": args.stagnation_rounds,
        "population_size": args.population_size if args.population_size is not None else 8,
        "offspring_per_iteration": (
            args.offspring_per_iteration if args.offspring_per_iteration is not None else 1
        ),
        "islands": args.islands if args.islands is not None else 1,
        "migration_interval": (
            args.migration_interval if args.migration_interval is not None else 0
        ),
        "migration_rate": args.migration_rate if args.migration_rate is not None else 0.1,
        "seed": args.seed,
        "timeout": args.timeout if args.timeout is not None else 900.0,
        "openevolve_command_configured": bool(args.openevolve_command),
        "evaluator_command_configured": bool(args.evaluator_command),
        "compile_evaluator": bool(getattr(args, "compile_evaluator", False) or getattr(args, "multi_file", False)),
    }
    if getattr(args, "_bundle_profile_sha256", None) is not None:
        payload["bundle_profile_sha256"] = args._bundle_profile_sha256
    if getattr(args, "multi_file", False):
        payload["automatic_lifecycle_version"] = _AUTOMATIC_LIFECYCLE_VERSION
        candidate_steps = getattr(args, "candidate_generation_max_steps", None)
        if candidate_steps is not None:
            _validate_candidate_generation_value(candidate_steps)
        payload["bundle_mode"] = "compiled"
        if candidate_steps is not None:
            payload["candidate_generation_max_steps"] = candidate_steps
            payload["candidate_generation_max_steps_source"] = "explicit"
        payload["timeout_source"] = "explicit" if args.timeout is not None else "default"
        payload["evaluator_preparation_timeout"] = (
            args.evaluator_preparation_timeout
            if args.evaluator_preparation_timeout is not None
            else payload["timeout"]
        )
        payload["evaluator_preparation_wall_timeout"] = (
            args.evaluator_preparation_wall_timeout
            if args.evaluator_preparation_wall_timeout is not None
            else min(86400.0, 2 * payload["evaluator_preparation_timeout"] + 60.0)
        )
        for name in _PREPARATION_TIMEOUT_OPTIONS:
            payload[name + "_source"] = "explicit" if getattr(args, name, None) is not None else "default"
        solve_wall_timeout = getattr(args, "solve_wall_timeout", None)
        if solve_wall_timeout is not None:
            _validate_solve_wall_timeout_value(solve_wall_timeout)
            payload["solve_wall_timeout"] = solve_wall_timeout
            payload["solve_wall_timeout_source"] = "explicit"
    return payload


def _validate_evolution_cli_bounds(args: argparse.Namespace) -> None:
    """Validate option bounds before a handoff request is persisted in the intake ledger."""
    _validate_candidate_generation_option(args)
    _validate_solve_wall_timeout_option(args, allow_unresolved_handoff=False)
    try:
        EvolutionConfig(
            strategy="population",
            max_rounds=args.max_rounds if args.max_rounds is not None else 1,
            stagnation_rounds=(
                args.stagnation_rounds if args.stagnation_rounds is not None else 1
            ),
            population_size=args.population_size if args.population_size is not None else 8,
            offspring_per_iteration=(
                args.offspring_per_iteration if args.offspring_per_iteration is not None else 1
            ),
            num_islands=args.islands if args.islands is not None else 1,
            migration_interval=(
                args.migration_interval if args.migration_interval is not None else 0
            ),
            migration_rate=args.migration_rate if args.migration_rate is not None else 0.1,
            rng_seed=args.seed,
            timeout_seconds=args.timeout if args.timeout is not None else 900.0,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid solve evolution options: {exc}") from exc
    _validate_preparation_cli_timeouts(args)
    for name in _PREPARATION_TIMEOUT_OPTIONS:
        if getattr(args, name, None) is not None and not getattr(args, "multi_file", False):
            raise ValueError(f"--{name.replace('_', '-')} requires --multi-file")
    wall_timeout = getattr(args, "evaluator_preparation_wall_timeout", None)
    request_timeout = getattr(args, "evaluator_preparation_timeout", None)
    if request_timeout is None:
        request_timeout = args.timeout if args.timeout is not None else 900.0
    if wall_timeout is not None and wall_timeout < request_timeout:
        raise ValueError(
            "--evaluator-preparation-wall-timeout must be at least the resolved "
            "--evaluator-preparation-timeout"
        )
    evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
    if evaluator_command:
        executable = Path(evaluator_command[0])
        if (
            not executable.is_absolute()
            or not executable.is_file()
            or not os.access(executable, os.X_OK)
        ):
            raise ValueError(
                "--evaluator-command must start with an existing absolute executable path"
            )


_PREPARATION_TIMEOUT_OPTIONS = (
    "evaluator_preparation_timeout",
    "evaluator_preparation_wall_timeout",
)
_AUTOMATIC_LIFECYCLE_VERSION = 1


def _has_preparation_timeout(args: argparse.Namespace) -> bool:
    return any(getattr(args, name, None) is not None for name in _PREPARATION_TIMEOUT_OPTIONS)


def _validate_preparation_cli_timeouts(args: argparse.Namespace) -> None:
    for name in _PREPARATION_TIMEOUT_OPTIONS:
        value = getattr(args, name, None)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 < value <= 86400
            or not math.isfinite(float(value))
        ):
            raise ValueError(
                f"invalid --{name.replace('_', '-')}: "
                "must be finite and between 0 and 86400 seconds"
            )


def _validate_solve_wall_timeout_value(value: object, *, error_type=ValueError) -> None:
    """Validate the active execution policy independently from stage ceilings."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= 86400
        or not math.isfinite(float(value))
    ):
        raise error_type(
            "--solve-wall-timeout must be finite and between 0 and 86400 seconds"
        )


def _validate_solve_wall_timeout_option(
    args: argparse.Namespace,
    request: dict[str, object] | None = None,
    *,
    allow_unresolved_handoff: bool = True,
) -> None:
    """Validate a solve policy before runtime, Store, or answer-artifact side effects."""
    supplied = getattr(args, "solve_wall_timeout", None)
    if supplied is not None:
        _validate_solve_wall_timeout_value(supplied)

    if request is not None:
        mode = request.get("bundle_mode")
        if mode != "compiled":
            if supplied is not None:
                raise EvolutionError(
                    "solve-wall-timeout requires an automatic multi-file evolution handoff"
                )
            return
        marker = request.get("automatic_lifecycle_version")
        if marker is not None and marker != _AUTOMATIC_LIFECYCLE_VERSION:
            raise EvolutionError("solve evolution lifecycle marker is invalid")
        stored = request.get("solve_wall_timeout")
        source = request.get("solve_wall_timeout_source")
        has_policy_fields = "solve_wall_timeout" in request or "solve_wall_timeout_source" in request
        if has_policy_fields:
            if marker is None:
                raise EvolutionError(
                    "solve evolution solve_wall_timeout requires the lifecycle marker"
                )
            if stored is None or source != "explicit":
                raise EvolutionError("solve evolution solve_wall_timeout setting is invalid")
            try:
                _validate_solve_wall_timeout_value(stored, error_type=EvolutionError)
            except EvolutionError:
                raise EvolutionError("solve evolution solve_wall_timeout setting is invalid") from None
        elif marker is not None and supplied is not None:
            raise EvolutionError(
                "solve evolution solve_wall_timeout cannot be added to an existing handoff"
            )
        elif marker is None and supplied is not None:
            raise EvolutionError(
                "solve evolution solve_wall_timeout cannot be added to a legacy handoff"
            )
        if supplied is not None and stored is not None and supplied != stored:
            raise EvolutionError(
                "solve evolution setting solve_wall_timeout does not match the existing handoff"
            )
        return

    if supplied is None:
        return
    command = getattr(args, "command", None)
    if allow_unresolved_handoff and command == "solve" and getattr(args, "resume", False):
        return
    if allow_unresolved_handoff and command in {"resume", "answer"}:
        return
    if command != "solve" or not getattr(args, "evolve", False) or not getattr(args, "multi_file", False):
        raise ValueError("--solve-wall-timeout requires --evolve --multi-file")


def _validate_preparation_request(request: dict[str, object]) -> None:
    """Validate persisted values without adding a wall deadline to legacy handoffs."""
    for name in ("timeout", *_PREPARATION_TIMEOUT_OPTIONS):
        source_name = name + "_source"
        if source_name in request and (
            name not in request or request[source_name] not in ("explicit", "default")
        ):
            raise EvolutionError(f"solve evolution setting {source_name} is invalid")
    for name in ("timeout", *_PREPARATION_TIMEOUT_OPTIONS):
        if name == "evaluator_preparation_wall_timeout" and name not in request:
            continue
        value = request.get(name)
        if name == "evaluator_preparation_timeout" and name not in request:
            value = request.get("timeout")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 < value <= 86400
            or not math.isfinite(float(value))
        ):
            raise EvolutionError(f"solve evolution setting {name} is invalid")
    wall_timeout = request.get("evaluator_preparation_wall_timeout")
    request_timeout = request.get("evaluator_preparation_timeout", request.get("timeout"))
    if wall_timeout is not None and wall_timeout < request_timeout:
        raise EvolutionError(
            "solve evolution setting evaluator_preparation_wall_timeout "
            "must be at least evaluator_preparation_timeout"
        )


def _validate_preparation_timeout_override(args, request) -> None:
    """Keep request and total budgets fixed across explicit continuation."""
    _validate_preparation_cli_timeouts(args)
    if request is not None and request.get("bundle_mode") == "compiled":
        _validate_preparation_request(request)
    for name in _PREPARATION_TIMEOUT_OPTIONS:
        supplied = getattr(args, name, None)
        if supplied is None:
            continue
        if request is None or request.get("bundle_mode") != "compiled":
            raise EvolutionError(f"--{name.replace('_', '-')} requires --multi-file")
        stored = request.get(name)
        if name == "evaluator_preparation_timeout" and stored is None:
            stored = request.get("timeout")
        # A legacy handoff has no total wall deadline. An explicit value would
        # change that persisted policy, even if it matches the current default.
        if supplied != stored:
            raise EvolutionError(f"solve evolution setting {name} does not match the existing handoff")


def _latest_evolution_request(store: Store, run_id: str) -> dict[str, object] | None:
    for event in reversed(store.list_events(run_id)):
        if event["type"] == "evolution_requested" and isinstance(event.get("payload"), dict):
            return event["payload"]
    return None


def _validate_evolution_override(args: argparse.Namespace, request: dict[str, object]) -> None:
    """Reject explicit resume settings that differ from the persisted handoff request."""
    _validate_candidate_generation_option(args, request)
    _validate_solve_wall_timeout_option(args, request)
    _validate_preparation_timeout_override(args, request)
    for name in (
        "strategy",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
    ):
        supplied = getattr(args, name, None)
        stored = request.get(name)
        if supplied is not None and stored is not None and supplied != stored:
            raise EvolutionError(f"solve evolution setting {name} does not match the existing handoff")
    configured = request.get("evaluator_command_configured", False)
    if not isinstance(configured, bool):
        raise EvolutionError("solve evolution evaluator command marker is invalid")
    if configured != bool(getattr(args, "evaluator_command", None)):
        if configured:
            raise EvolutionError("solve evolution requires the configured evaluator command")
        raise EvolutionError("solve evolution did not configure an evaluator command")
    compiled = request.get("compile_evaluator", False)
    if not isinstance(compiled, bool):
        raise EvolutionError("solve evolution compiled evaluator marker is invalid")
    if getattr(args, "compile_evaluator", False) and not compiled:
        raise EvolutionError("solve evolution did not configure a compiled evaluator")


def _evolution_args(
    args: argparse.Namespace, request: dict[str, object] | None
) -> argparse.Namespace:
    """Overlay persisted handoff settings onto a CLI namespace during answer/resume."""
    if request is None:
        return args
    values = vars(args).copy()
    values["evolve"] = True
    for name in (
        "strategy",
        "openevolve_command",
        "evaluator_command",
        "compile_evaluator",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
        "evaluator_preparation_timeout",
        "evaluator_preparation_wall_timeout",
        "candidate_generation_max_steps",
        "solve_wall_timeout",
    ):
        values.setdefault(name, None)
    for name in (
        "strategy",
        "max_rounds",
        "stagnation_rounds",
        "population_size",
        "offspring_per_iteration",
        "islands",
        "migration_interval",
        "migration_rate",
        "seed",
        "timeout",
        "evaluator_preparation_timeout",
        "evaluator_preparation_wall_timeout",
        "candidate_generation_max_steps",
    ):
        if name in request and request[name] is not None:
            values[name] = request[name]
    if request.get("bundle_mode") == "compiled":
        # Preserve legacy automatic handoffs that never recorded a candidate budget.
        values["candidate_generation_max_steps"] = request.get(
            "candidate_generation_max_steps"
        )
        values["evaluator_preparation_timeout"] = request.get(
            "evaluator_preparation_timeout", request.get("timeout")
        )
        values["evaluator_preparation_wall_timeout"] = request.get(
            "evaluator_preparation_wall_timeout"
        )
    values["compile_evaluator"] = bool(request.get("compile_evaluator", False))
    values["multi_file"] = request.get("bundle_mode") == "compiled"
    values["solve_wall_timeout"] = request.get("solve_wall_timeout")
    return argparse.Namespace(**values)


def _index_evaluator_bundle(
    controller: LocalController,
    parent: Run,
    bundle_root: Path,
    fingerprint: str,
) -> None:
    """Index one verified frozen bundle without copying source or probes into events."""
    tasks = controller.store.list_tasks(parent.id)
    if not tasks:
        raise EvolutionError("compiled evaluator parent run has no artifact owner")
    owner = tasks[0].id
    artifacts = ArtifactStore(parent.workspace, controller.store, parent.id)
    existing = {
        (item["path"], item["sha256"])
        for item in controller.store.list_artifacts(parent.id)
        if item["kind"] == "evaluator_bundle"
    }
    indexed: list[dict[str, object]] = []
    for path in sorted(bundle_root.iterdir(), key=lambda item: item.name):
        relative = path.relative_to(parent.workspace).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if (relative, digest) not in existing:
            artifact_id = artifacts.record(path, owner, kind="evaluator_bundle")
        else:
            artifact_id = next(
                item["id"]
                for item in controller.store.list_artifacts(parent.id)
                if item["kind"] == "evaluator_bundle"
                and item["path"] == relative
                and item["sha256"] == digest
            )
        indexed.append(
            {
                "artifact_id": artifact_id,
                "path": relative,
                "size": path.stat().st_size,
                "sha256": digest,
            }
        )
    controller.store.append_event(
        parent.id,
        "evaluator_bundle_frozen",
        {"bundle_sha256": fingerprint, "artifacts": indexed},
        task_id=owner,
        event_id="event-evaluator-bundle-" + fingerprint,
    )


def _validate_solve_bundle_child(store, parent, child, contract, *, linked_required):
    from ._benchmark_files import absolute_path, read_regular_file
    from ._candidate_workspace_io import DirectoryChain

    expected = absolute_path(Path(parent.workspace) / "evolution-run")
    if absolute_path(child.workspace) != expected:
        raise EvolutionError("solve_bundle_link_invalid")
    held = DirectoryChain(expected, "destination_changed")
    try:
        canonical = AlgorithmProblemContract.from_dict(_strict_json_loads(read_regular_file(
            expected / "evolution/contract.json", MAX_CONTRACT_BYTES,
        )))
        if canonical.digest() != contract.digest():
            raise EvolutionError("solve_bundle_link_invalid")
        held.check()
    finally:
        held.close()
    links = [event.get("payload") for event in store.list_events(child.id)
             if event["type"] == "evolution_parent_linked"]
    if (linked_required and not links) or any(
        not isinstance(link, dict) or link.get("parent_run_id") != parent.id
        or link.get("contract_sha256") != contract.digest() for link in links
    ):
        raise EvolutionError("solve_bundle_link_invalid")


def _validate_conversational_bundle_link(args, store, parent):
    if getattr(args, "_bundle_pipeline", None) is None and not getattr(args, "multi_file", False):
        return
    if getattr(args, "multi_file", False):
        from .automatic_solve_bundle import validate_automatic_solve_bundle

        validate_automatic_solve_bundle(store, parent.id)
    from ._benchmark_files import absolute_path
    from ._candidate_workspace_io import DirectoryChain

    expected = absolute_path(Path(parent.workspace) / "evolution-run")
    # Validate the existing path before any resolution, input staging, compiler or child work.
    existing_path = expected
    while not existing_path.exists() and not existing_path.is_symlink():
        existing_path = existing_path.parent
    held = DirectoryChain(existing_path, "destination_changed")
    held.close()
    links = [event.get("payload") for event in store.list_events(parent.id)
             if event["type"] == "evolution_linked"]
    plan = store.get_current_plan(parent.id)
    if not links:
        child = store.get_run_by_workspace(expected)
        if child is not None:
            if plan is None or plan.algorithm_problem is None:
                raise EvolutionError("solve_bundle_link_invalid")
            _validate_solve_bundle_child(
                store, parent, child, AlgorithmProblemContract.from_dict(plan.algorithm_problem),
                linked_required=False,
            )
        return
    if plan is None or plan.algorithm_problem is None or not isinstance(links[0], dict):
        raise EvolutionError("solve_bundle_link_invalid")
    contract = AlgorithmProblemContract.from_dict(plan.algorithm_problem)
    child_id = links[0].get("evolution_run_id")
    if not isinstance(child_id, str) or not child_id or any(
        not isinstance(link, dict) or link.get("evolution_run_id") != child_id
        or link.get("contract_sha256") != contract.digest() or link.get("strategy") != "population"
        for link in links
    ):
        raise EvolutionError("solve_bundle_link_invalid")
    child = store.get_run(child_id)
    if child is None:
        raise EvolutionError("solve_bundle_link_invalid")
    _validate_solve_bundle_child(store, parent, child, contract, linked_required=True)


def _solve_evolution(
    config: Config, args: argparse.Namespace, controller: LocalController, parent: Run
) -> dict[str, object]:
    """Run one automatic evolution under a process-local exclusive owner."""
    if getattr(args, "multi_file", False) and not getattr(args, "_solve_owner_held", False):
        with own_automatic_solve(parent.id):
            return _solve_evolution_impl(config, args, controller, parent)
    return _solve_evolution_impl(config, args, controller, parent)


def _solve_evolution_impl(
    config: Config, args: argparse.Namespace, controller: LocalController, parent: Run
) -> dict[str, object]:
    """Create or resume the evolution child linked to one compiled conversational run."""
    solve_control = getattr(args, "_solve_execution_control", None)
    if solve_control is not None:
        solve_control.check("contract")
    if parent.status.value == "awaiting_input" and controller.store.pending_input(parent.id) is None:
        # Correct legacy dependency-only waits on explicit continuation, without rewriting
        # historical rows merely because a user inspected status.
        parent = controller.store.settle_run(parent.id) or parent
    events = controller.store.list_events(parent.id)
    linked = next(
        (
            event["payload"]
            for event in reversed(events)
            if event["type"] == "evolution_linked" and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    contract_payload = controller.store.get_current_plan(parent.id)
    if contract_payload is None or contract_payload.algorithm_problem is None:
        raise ValueError("solve --evolve requires a compiled algorithm contract")
    contract = AlgorithmProblemContract.from_dict(contract_payload.algorithm_problem)
    if contract.evolution.strategy == "loop":
        raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
    candidate_inputs = _candidate_input_artifacts(controller.store, parent.id)
    strategy_name = args.strategy or contract.evolution.strategy
    if strategy_name == "loop":
        raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
    orchestration_task = None
    orchestration_attempt = None
    lifecycle_request = _latest_evolution_request(controller.store, parent.id)
    lifecycle_enabled = (
        getattr(args, "multi_file", False)
        and lifecycle_request is not None
        and lifecycle_request.get("automatic_lifecycle_version") == _AUTOMATIC_LIFECYCLE_VERSION
    )
    if lifecycle_enabled:
        orchestration_task = controller.store.ensure_orchestration_task(
            parent.id,
            title="Automatic solve orchestration",
            prompt=f"Coordinate evolution and delivery for {contract.problem_id}",
        )
        if orchestration_task.state.value in {"succeeded", "failed", "cancelled"}:
            return {"run": controller.store.get_run(parent.id) or parent}
        orchestration_attempt = controller.store.claim_orchestration_task(
            orchestration_task.id, "automatic-solve",
        )
        if orchestration_attempt is None:
            raise EvolutionError("automatic solve orchestration task is not runnable")
        controller.store.append_event(
            parent.id,
            "automatic_solve_orchestration_started",
            {"task_id": orchestration_task.id, "attempt_id": orchestration_attempt.id},
            event_id="event-automatic-solve-orchestration-" + hashlib.sha256(parent.id.encode()).hexdigest(),
        )
        controller.store.supersede_pending_tasks(parent.id, "replaced by explicit evolution handoff")

    def delivery_guard() -> None:
        if solve_control is not None:
            solve_control.check("delivery")
        if lifecycle_enabled:
            current = controller.store.get_run(parent.id)
            if current is None or current.status.value in {"cancelled", "failed"}:
                raise SolveExecutionCancelled("delivery")

    def finish_orchestration(success: bool, error: str | None = None) -> None:
        if orchestration_task is None or orchestration_attempt is None:
            return
        controller.store.finish_task(
            orchestration_task.id,
            orchestration_attempt.id,
            success,
            error=error,
        )
        controller.store.settle_run(parent.id)

    def finish_child_orchestration(child: Run, delivery: dict[str, object] | None) -> None:
        delivery_guard()
        if child.status.value == "cancelled":
            controller.store.cancel_run(parent.id)
        elif child.status.value == "failed":
            finish_orchestration(False, "linked evolution failed")
        elif child.status.value == "succeeded":
            if lifecycle_enabled and (delivery is None or delivery.get("status") != "succeeded"):
                finish_orchestration(False, "automatic solve delivery did not succeed")
            else:
                finish_orchestration(True)

    if getattr(args, "multi_file", False):
        if strategy_name != "population":
            raise EvolutionError("solve_bundle_requires_population")
        if not contract.outputs:
            raise EvolutionError("solve_bundle_outputs_required")
        _validate_conversational_bundle_link(args, controller.store, parent)
        from .automatic_solve_bundle import (
            AutomaticBundlePreparationError,
            prepare_automatic_solve_bundle,
        )
        if (observation := getattr(args, "_solve_observation", None)) is not None:
            observation.observe("preparation")

        try:
            scope = (controller.observe_attempt_runtime(parent.id, orchestration_attempt.id)
                     if orchestration_attempt is not None else nullcontext((None, None)))
            with scope as (process_observer, process_released):
                args._bundle_pipeline = prepare_automatic_solve_bundle(
                    controller, parent.id, contract,
                    timeout_seconds=args.timeout if args.timeout is not None else 900.0,
                    evaluator_preparation_timeout_seconds=(
                        getattr(args, "evaluator_preparation_timeout", None)
                        if getattr(args, "evaluator_preparation_timeout", None) is not None
                        else args.timeout if args.timeout is not None else 900.0
                    ),
                    evaluator_preparation_wall_timeout_seconds=getattr(
                        args, "evaluator_preparation_wall_timeout", None,
                    ),
                    solve_control=solve_control,
                    **({"process_observer": process_observer, "process_released": process_released,
                        "process_guard": lambda: controller.ensure_attempt_process_released(
                            parent.id, orchestration_attempt.id,
                        )}
                       if process_observer is not None else {}),
                )
        except AutomaticBundlePreparationError:
            # The preparation ledger retains this failure; callers emit the ordinary parent
            # payload and a nonzero result without creating a child or discarding the contract.
            return {"run": controller.store.get_run(parent.id) or parent}
        if (acceptance_hook := getattr(args, "_acceptance_preparation_hook", None)) is not None:
            if solve_control is None:
                raise EvolutionError("acceptance_solve_control_required")
            acceptance_hook(controller.store, parent.id, contract, solve_control)
    bundle_pipeline = getattr(args, "_bundle_pipeline", None)
    if (observation := getattr(args, "_solve_observation", None)) is not None:
        observation.observe("candidate_generation")
    if solve_control is not None:
        solve_control.check("candidate_generation")
    if bundle_pipeline is not None:
        if strategy_name != "population":
            raise EvolutionError("solve_bundle_requires_population")
        if not contract.outputs:
            raise EvolutionError("solve_bundle_outputs_required")
        _validate_conversational_bundle_link(args, controller.store, parent)
        _bind_conversational_bundle_inputs(args, controller.store, parent)
        bundle_pipeline = args._bundle_pipeline
    evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
    compile_evaluator = bool(getattr(args, "compile_evaluator", False))

    # Validate all strategy/runtime settings before creating any child workspace or mutating the
    # intake plan. This keeps malformed opt-in requests side-effect free.
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = (
        args.stagnation_rounds
        if args.stagnation_rounds is not None
        else contract.evolution.stagnation_rounds
    )
    if strategy_name == "openevolve":
        if compile_evaluator:
            raise ValueError("--compile-evaluator is supported only by native evolution strategies")
        if not openevolve_command:
            raise ValueError("--evolve --strategy openevolve requires --openevolve-command")
        if not evaluator_command:
            raise ValueError(
                "--evolve --strategy openevolve requires --evaluator-command for local verification"
            )
        executable = Path(openevolve_command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("--openevolve-command must start with an existing absolute executable path")

        def generator(request):
            del request
            raise EvolutionError("openevolve does not use a native generator")

        evaluator = CommandCandidateEvaluator(
            evaluator_command,
            args.timeout,
            environment={
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONHASHSEED": "0",
                "PYTHONIOENCODING": "utf-8",
            },
        )
        generator_fingerprint = None
        evaluator_fingerprint = _adapter_fingerprint(
            evaluator_command,
            kind="objective-harness",
            name="command-evaluator",
            role="evaluator",
        )
    else:
        if openevolve_command:
            raise ValueError("--openevolve-command requires --evolve --strategy openevolve")
        if compile_evaluator and evaluator_command:
            raise ValueError("--compile-evaluator and --evaluator-command are mutually exclusive")
        runtime = controller.runtime
        solver_adapter = RuntimeAgentAdapter(
            runtime,
            name="solve-evolution-solver",
            roles=("solver",),
            capabilities=DEFAULT_RUNTIME_CAPABILITIES,
        )
        evaluator_adapter = RuntimeAgentAdapter(
            runtime,
            name="solve-evolution-evaluator",
            roles=("evaluator",),
            capabilities=DEFAULT_RUNTIME_CAPABILITIES,
        )
        runtime_fingerprint = _compiler_fingerprint(runtime)
        generator_fingerprint = hashlib.sha256(
            f"{runtime_fingerprint}:solver".encode()
        ).hexdigest()
        if bundle_pipeline is not None:
            scoring = None
            evaluator = bundle_pipeline
            evaluator_fingerprint = bundle_pipeline.evaluator.digest()
            generator_fingerprint = hashlib.sha256(
                f"{runtime_fingerprint}:bundle-solver-v1".encode()
            ).hexdigest()
        elif compile_evaluator:
            bundle = compile_evaluator_bundle(
                runtime,
                contract,
                Path(parent.workspace),
                inputs=candidate_inputs,
                timeout=args.timeout,
            )
            evaluator = bundle
            scoring = SolverScoringContract.from_bundle(bundle, contract)
            evaluator_fingerprint = bundle.fingerprint
            _index_evaluator_bundle(controller, parent, bundle.root, bundle.fingerprint)
        elif evaluator_command:
            scoring = None
            evaluator = CommandCandidateEvaluator(
                evaluator_command,
                args.timeout,
                environment={
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PYTHONHASHSEED": "0",
                    "PYTHONIOENCODING": "utf-8",
                },
            )
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_command,
                kind="objective-harness",
                name="command-evaluator",
                role="evaluator",
            )
        else:
            scoring = None
            evaluator = AgentCandidateEvaluator(
                evaluator_adapter, role="evaluator", timeout=args.timeout
            )
            evaluator_fingerprint = hashlib.sha256(
                f"{runtime_fingerprint}:evaluator".encode()
            ).hexdigest()
        candidate_budget = None
        candidate_steps = getattr(args, "candidate_generation_max_steps", None)
        if getattr(args, "multi_file", False) and candidate_steps is not None:
            candidate_budget = CandidateGenerationBudget(
                budget_id="candidate-generation",
                max_tool_steps=candidate_steps,
                timeout_seconds=args.timeout if args.timeout is not None else 900.0,
            )
        generator = AgentCandidateGenerator(
            solver_adapter,
            contract=contract,
            role="solver",
            timeout=args.timeout,
            inputs=() if bundle_pipeline is not None else candidate_inputs,
            scoring=scoring,
            bundle_pipeline=bundle_pipeline,
            candidate_budget=candidate_budget,
        )
    runner_fingerprint = (
        None
        if strategy_name == "openevolve" or bundle_pipeline is not None
        else contract_candidate_runner_fingerprint(contract, candidate_inputs)
    )
    evolution_config = EvolutionConfig(
        strategy=strategy_name,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        command=openevolve_command,
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint,
    )
    if bundle_pipeline is not None:
        evolution_config = bundle_pipeline.configure(evolution_config)

    def execution_grounded_evaluator(child: Run):
        if strategy_name == "openevolve" or bundle_pipeline is not None:
            return evaluator
        runner = ContractCandidateRunner(
            child.workspace,
            candidate_inputs,
            contract.outputs,
            timeout_seconds=args.timeout,
        )
        return ExecutionAwareCandidateEvaluator(runner, evaluator)

    if linked is not None:
        linked_contract = linked.get("contract_sha256")
        if not isinstance(linked_contract, str) or linked_contract != contract.digest():
            raise EvolutionError("evolution link has an invalid contract digest")
        child_id = linked.get("evolution_run_id")
        if not isinstance(child_id, str) or not child_id:
            raise EvolutionError("evolution link has an invalid child run ID")
        child = controller.store.get_run(child_id)
        if child is None:
            raise EvolutionError("linked evolution run no longer exists")
        if linked.get("strategy") != strategy_name:
            raise EvolutionError("solve evolution strategy does not match the existing handoff")
        if bundle_pipeline is not None:
            _validate_solve_bundle_child(controller.store, parent, child, contract, linked_required=True)
        state_path = child.workspace / "evolution" / "state.json"
        if state_path.is_file():
            try:
                state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvolutionError("linked evolution state is not valid JSON") from exc
            if (
                isinstance(state_payload, dict)
                and state_payload.get("config") is not None
                and state_payload.get("config") != evolution_config.to_dict()
            ):
                raise EvolutionError("solve evolution settings do not match the existing handoff")
        controller.copy_staged_inputs(parent.id, child.id)
        if solve_control is not None:
            solve_control.check("evolution")
        try:
            child, result = controller.run_evolution(
                child.id,
                contract,
                generator,
                execution_grounded_evaluator(child),
                evolution_config,
                resume=child.status.value not in {"succeeded", "failed", "cancelled"},
                bundle_pipeline=bundle_pipeline,
                **({"automatic_parent_id": parent.id} if lifecycle_enabled else {}),
                remaining_timeout=(
                    (lambda stage: solve_control.effective_timeout(stage=stage))
                    if solve_control is not None else None
                ),
            )
            delivery = None
            if child.status.value == "succeeded" and (bundle_pipeline is not None or contract.outputs):
                if (observation := getattr(args, "_solve_observation", None)) is not None:
                    observation.observe("delivery")
                if solve_control is not None:
                    solve_control.check("delivery")
                if bundle_pipeline is not None:
                    delivery = controller.deliver_bundle_to_parent(
                        parent.id, child.id, contract, result,
                        **({"continuation_guard": delivery_guard} if lifecycle_enabled or solve_control is not None else {}),
                    )
                else:
                    controller.materialize_evolved_outputs(
                        parent.id, child.id, contract, result,
                        timeout_seconds=evolution_config.timeout_seconds,
                    )
            finish_child_orchestration(child, delivery)
            return {"run": controller.store.get_run(parent.id) or parent, "child": child}
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            raise
        except Exception as exc:
            finish_orchestration(False, " ".join(str(exc).split())[-2_000:] or "automatic solve failed")
            raise

    child_workspace = Path(parent.workspace) / "evolution-run"
    if bundle_pipeline is None:
        child_workspace = child_workspace.resolve()
    existing = controller.store.get_run_by_workspace(child_workspace)
    if existing is not None:
        child = existing
        canonical_path = child.workspace / "evolution" / "contract.json"
        try:
            canonical = AlgorithmProblemContract.from_dict(
                json.loads(canonical_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("existing evolution handoff workspace has an invalid contract") from exc
        if canonical.digest() != contract.digest():
            raise EvolutionError("existing evolution handoff workspace belongs to another contract")
    else:
        child = controller.create_evolution_run(contract, workspace=child_workspace)
    if bundle_pipeline is not None:
        _validate_solve_bundle_child(controller.store, parent, child, contract, linked_required=False)
    # Re-run the copy after a crash between child creation and linking; identical bytes are
    # idempotent and conflicting bytes fail closed before strategy execution.
    controller.copy_staged_inputs(parent.id, child.id)
    if orchestration_task is None:
        # Preserve the legacy single-file handoff lifecycle.  Automatic multi-file solves use the
        # durable orchestration task above and remain running until child delivery settles them.
        controller.store.supersede_pending_tasks(parent.id, "replaced by explicit evolution handoff")
        controller.store.settle_run(parent.id)
    controller.store.append_event(
        parent.id,
        "evolution_linked",
        {
            "evolution_run_id": child.id,
            "contract_sha256": contract.digest(),
            "strategy": strategy_name,
        },
        event_id="event-evolution-link-" + hashlib.sha256(child.id.encode()).hexdigest(),
    )
    controller.store.append_event(
        child.id,
        "evolution_parent_linked",
        {"parent_run_id": parent.id, "contract_sha256": contract.digest()},
        event_id="event-evolution-parent-link-" + hashlib.sha256(parent.id.encode()).hexdigest(),
    )

    if solve_control is not None:
        solve_control.check("evolution")
    try:
        child, result = controller.run_evolution(
            child.id,
            contract,
            generator,
            execution_grounded_evaluator(child),
            evolution_config,
            bundle_pipeline=bundle_pipeline,
            **({"automatic_parent_id": parent.id} if lifecycle_enabled else {}),
            remaining_timeout=(
                (lambda stage: solve_control.effective_timeout(stage=stage))
                if solve_control is not None else None
            ),
        )
        delivery = None
        if child.status.value == "succeeded" and (bundle_pipeline is not None or contract.outputs):
            if (observation := getattr(args, "_solve_observation", None)) is not None:
                observation.observe("delivery")
            if solve_control is not None:
                solve_control.check("delivery")
            if bundle_pipeline is not None:
                delivery = controller.deliver_bundle_to_parent(
                    parent.id, child.id, contract, result,
                    **({"continuation_guard": delivery_guard} if lifecycle_enabled or solve_control is not None else {}),
                )
            else:
                controller.materialize_evolved_outputs(
                    parent.id, child.id, contract, result,
                    timeout_seconds=evolution_config.timeout_seconds,
                )
        finish_child_orchestration(child, delivery)
        return {"run": controller.store.get_run(parent.id) or parent, "child": controller.store.get_run(child.id) or child}
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        finish_orchestration(False, " ".join(str(exc).split())[-2_000:] or "automatic solve failed")
        raise


def _preparation_budgets_payload(store: Store, run_id: str) -> dict[str, object] | None:
    """Project bounded policy only; absent legacy fields never acquire a new deadline."""
    request = _latest_evolution_request(store, run_id)
    if request is None or request.get("bundle_mode") != "compiled":
        return None
    result = {}
    for field, name in (
        ("timeout", "candidate_timeout"),
        ("evaluator_preparation_timeout", "evaluator_preparation_timeout"),
        ("evaluator_preparation_wall_timeout", "evaluator_preparation_wall_timeout"),
    ):
        if field not in request:
            if field == "timeout":
                return None
            value = request["timeout"] if field == "evaluator_preparation_timeout" else None
            source = "legacy"
            if field + "_source" in request:
                return None
        else:
            value = request[field]
            source = request.get(field + "_source", "persisted")
            if (field + "_source" in request
                    and (not isinstance(source, str) or source not in {"explicit", "default"})):
                return None
            if value is None:
                return None
        if value is not None and (
            type(value) not in {int, float} or not 0 < value <= 86400
        ):
            return None
        result[name] = {"seconds": value, "source": source}
    wall = result["evaluator_preparation_wall_timeout"]["seconds"]
    if wall is not None and wall < result["evaluator_preparation_timeout"]["seconds"]:
        return None
    return result


def _bundle_preparation_payload(store: Store, run_id: str) -> dict[str, object] | None:
    from .automatic_solve_bundle import automatic_bundle_preparation_status

    preparation = automatic_bundle_preparation_status(store, run_id)
    if (preparation is not None and preparation.get("request_failure", {}).get("reason")
            == "transport_timeout"):
        preparation = {
            **preparation,
            "request_failure_hint": (
                "Evaluator generation model request timed out; remote completion and usage are unknown. "
                "The last transport milestone is a local observation, not a provider activity report. "
                "Explicit resume may issue new model requests."
            ),
        }
    if preparation is not None and preparation.get("recoverable"):
        preparation = {
            **preparation,
            "resume_hint": "Run resume with the same home and runtime settings to retry evaluator preparation.",
        }
    if preparation is not None and preparation.get("error_category") == "unsupported_verification":
        preparation = {
            **preparation,
            "capability_hint": (
                "Generated evaluators verify outputs only. Lunar Evolution separately checks declared minimum "
                "Python file counts. These requirements need independent "
                "source or execution checkers; retrying evaluator generation cannot verify them."
            ),
        }
    return preparation


def _solve_payload(controller: LocalController, run: Run) -> dict[str, object]:
    manifest = _conversation_manifest(run)
    input_data = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "input_data"
    ]
    algorithm_outputs = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "output"
    ]
    evolution_payload: dict[str, object] | None = None
    materialization = next(
        (
            event["payload"]
            for event in reversed(controller.store.list_events(run.id))
            if event["type"] in {"evolved_candidate_materialized", "bundle_candidate_delivered"}
            and isinstance(event.get("payload"), dict)
        ),
        None,
    )
    for event in reversed(controller.store.list_events(run.id)):
        if event["type"] != "evolution_linked" or not isinstance(event.get("payload"), dict):
            continue
        link = event["payload"]
        child_id = link.get("evolution_run_id")
        if not isinstance(child_id, str):
            break
        child = controller.store.get_run(child_id)
        if child is None:
            evolution_payload = {"run_id": child_id, "status": "missing"}
            break
        child_events = controller.store.list_events(child.id)
        result = next(
            (
                item["payload"]
                for item in reversed(child_events)
                if item["type"] == "evolution_finished" and isinstance(item.get("payload"), dict)
            ),
            None,
        )
        evolution_payload = {
            "run_id": child.id,
            "status": child.status.value,
            "workspace": str(child.workspace),
            "strategy": link.get("strategy"),
            "result": result,
            "materialization": materialization,
        }
        break
    preparation = _bundle_preparation_payload(controller.store, run.id)
    if preparation is not None:
        if evolution_payload is None:
            evolution_payload = {"status": preparation["status"], "preparation": preparation}
        else:
            evolution_payload["preparation"] = preparation
    preparation_budgets = _preparation_budgets_payload(controller.store, run.id)
    if preparation_budgets is not None:
        if evolution_payload is None:
            evolution_payload = {"status": run.status.value}
        evolution_payload["preparation_budgets"] = preparation_budgets
    evolution_status = None
    if (isinstance(evolution_payload, dict) and "run_id" in evolution_payload
            and evolution_payload.get("status") in {
        "pending", "running", "awaiting_input", "succeeded", "failed", "cancelled",
    }):
        evolution_status = evolution_payload["status"]
    projection = _status_projection(
        run,
        preparation=preparation,
        evolution_status=evolution_status,
        materialization_status=(
            materialization.get("status") if isinstance(materialization, dict) else None
        ),
    )
    payload = {
        "run_id": run.id,
        **projection,
        "workspace": str(run.workspace),
        "input_request": controller.store.pending_input(run.id),
        "input_data": input_data,
        "algorithm_outputs": algorithm_outputs,
        "compiler": manifest,
        "plan": (
            {"plan_id": run.current_plan_id, "version": run.current_plan_version}
            if run.current_plan_id
            else None
        ),
    }
    if (
        run.status.value == "failed"
        and run.current_plan_id is None
        and any(
            task.plan_task_id is None
            and task.state.value == "failed"
            and task.last_error == LOOP_STRATEGY_RETIRED_MESSAGE
            for task in controller.store.list_tasks(run.id)
        )
    ):
        payload.update(_loop_retirement_payload())
    if evolution_payload is not None:
        payload["evolution"] = evolution_payload
    if (execution_status := solve_execution_status(controller.store, run)) is not None:
        payload["solve_execution"] = execution_status
    return payload


def _automatic_runtime_command(config: Config, args: argparse.Namespace, run: Run) -> list[str]:
    """Resume one recorded automatic handoff; evolution policy is restored by the child."""
    command = [
        "solve", "--resume", "--run-id", run.id, "--runtime", args.runtime,
        "--home", str(config.home), "--json",
    ]
    for option, name in (
        ("--command", "runtime_command"), ("--endpoint", "endpoint"),
        ("--model", "model"), ("--model-profile", "model_profile"),
        ("--workers", "workers"),
    ):
        value = getattr(args, name, None)
        if value is not None:
            command.extend((option, str(value)))
    if getattr(args, "agent_loop", False):
        command.extend(("--agent-loop", "--max-steps", str(args.max_steps)))
    for option, name in (
        ("--allow-exec", "allow_exec"), ("--memory", "memory"),
        ("--session-history", "session_history"), ("--role-dag", "role_dag"),
    ):
        if getattr(args, name, False):
            command.append(option)
    return command


def _detach_solve(config: Config, args: argparse.Namespace, run: Run) -> dict[str, object]:
    """Spawn a child that resumes a conversational mission with identical runtime settings."""
    log_path = run.workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "lunar_evolution",
        "solve",
        "--resume",
        "--run-id",
        run.id,
        "--runtime",
        args.runtime,
        "--home",
        str(config.home),
        "--json",
    ]
    if args.workspace:
        command.extend(("--workspace", str(args.workspace)))
    if args.role_dag:
        command.append("--role-dag")
    if args.evolve:
        command.append("--evolve")
    if getattr(args, "compile_evaluator", False):
        command.append("--compile-evaluator")
    for option, value in (
        ("--strategy", args.strategy),
        ("--openevolve-command", args.openevolve_command),
        ("--evaluator-command", args.evaluator_command),
        ("--max-rounds", args.max_rounds),
        ("--stagnation-rounds", args.stagnation_rounds),
        ("--population-size", args.population_size),
        ("--offspring-per-iteration", args.offspring_per_iteration),
        ("--islands", args.islands),
        ("--migration-interval", args.migration_interval),
        ("--migration-rate", args.migration_rate),
        ("--seed", args.seed),
        ("--timeout", args.timeout),
    ):
        if value is not None:
            command.extend((option, str(value)))
    if args.runtime_command:
        command.extend(("--command", args.runtime_command))
    if args.endpoint:
        command.extend(("--endpoint", args.endpoint))
    if args.model:
        command.extend(("--model", args.model))
    if getattr(args, "model_profile", None):
        command.extend(("--model-profile", str(args.model_profile)))
    if args.agent_loop:
        command.append("--agent-loop")
        command.extend(("--max-steps", str(args.max_steps)))
    if args.allow_exec:
        command.append("--allow-exec")
    if args.memory:
        command.append("--memory")
    if args.session_history:
        command.append("--session-history")
    child_env = None
    if args.api_key is not None:
        child_env = os.environ.copy()
        child_env["LUNAR_EVOLUTION_API_KEY"] = args.api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run.id, pid, pgid)
            latest = store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run.id)
    except OSError as exc:
        Store(config.database).cancel_run(run.id)
        raise ValueError(f"could not start detached solve: {exc}") from exc
    input_data = [
        item for item in Store(config.database).list_artifacts(run.id)
        if item["kind"] == "input_data"
    ]
    return {
        "run_id": run.id,
        "status": "pending",
        "run_status": "pending",
        "workspace": str(run.workspace),
        "detached": True,
        "input_data": input_data,
    }


def _prepare_bundle_generator(args: argparse.Namespace, contract, pipeline):
    """Validate one source producer before initialization; evaluation stays in the profile."""
    runtime_name = args.agent_runtime
    runtime_command = _parse_command(args.agent_runtime_command, "--agent-runtime-command")
    runtime_options = (
        args.agent_runtime_command, args.agent_runtime_endpoint,
        args.agent_runtime_model, args.agent_runtime_api_key,
    )
    step_option = args.agent_runtime_max_steps
    if step_option is not None and not 1 <= step_option <= 200:
        raise ValueError("--agent-runtime-max-steps must be between 1 and 200")
    loop_options = (
        args.agent_runtime_allow_exec, args.agent_runtime_memory,
        args.agent_runtime_session_history, step_option is not None,
    )
    if runtime_name is None and (
        any(value is not None for value in runtime_options)
        or args.agent_runtime_loop or any(loop_options)
    ):
        raise ValueError("bundle runtime options require --agent-runtime")
    if args.agent_runtime_loop and runtime_name != "openai-compatible":
        raise ValueError("--agent-runtime-loop requires --agent-runtime openai-compatible")
    if any(loop_options) and not args.agent_runtime_loop:
        raise ValueError("bundle runtime loop options require --agent-runtime-loop")
    args.agent_runtime_max_steps = 40 if step_option is None else step_option
    if runtime_name != "subprocess" and args.agent_runtime_command is not None:
        raise ValueError("--agent-runtime-command requires --agent-runtime subprocess")
    if runtime_name == "subprocess" and not runtime_command:
        raise ValueError("--agent-runtime subprocess requires --agent-runtime-command")
    if runtime_name != "openai-compatible" and any(
        value is not None for value in (
            args.agent_runtime_endpoint, args.agent_runtime_model, args.agent_runtime_api_key,
        )
    ):
        raise ValueError("endpoint/model/API-key options require --agent-runtime openai-compatible")

    if args.generator_command is not None:
        if args.agent_name is not None or args.agent_role is not None or args.agent_capabilities:
            raise ValueError("solver Agent options require --agent-command or --agent-runtime")
        command = _parse_command(args.generator_command, "--generator-command")
        generator = CommandCandidateGenerator(command, args.timeout)
        fingerprint = _adapter_fingerprint(
            command, kind="bundle-generator", name="command-generator", role="solver",
        )
        return generator, fingerprint, None

    name = "bundle-agent" if args.agent_name is None else args.agent_name
    role = "solver" if args.agent_role is None else args.agent_role
    if not name:
        raise ValueError("bundle solver Agent name must not be empty")
    required = tuple(args.agent_capabilities)
    declared = tuple(sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(required)))
    # Validate roles, duplicate capabilities and timeout before any state or Agent invocation.
    AgentRequest("bundle-preflight", "generator", role, "Validate source generation options.",
                 required_capabilities=required, workspace=args.workspace, timeout=args.timeout)

    def wrap(adapter):
        return AgentCandidateGenerator(
            adapter, contract=contract, role=role, required_capabilities=required,
            timeout=args.timeout, bundle_pipeline=pipeline,
        )

    if args.agent_command is not None:
        command = _parse_command(args.agent_command, "--agent-command")
        adapter = CommandAgentAdapter(command, name=name, roles=(role,), capabilities=declared)
        return wrap(adapter), _adapter_fingerprint(
            command, kind="bundle-agent-generator", name=name, role=role,
            required_capabilities=required,
        ), None

    if runtime_name == "subprocess":
        # The generic subprocess runtime accepts PATH lookups; this explicit local entry requires
        # the same existing absolute executable boundary as its other source producers.
        CommandAgentAdapter(runtime_command, name=name, roles=(role,), capabilities=declared)
    endpoint, model, api_key = (
        args.agent_runtime_endpoint, args.agent_runtime_model, args.agent_runtime_api_key,
    )
    if runtime_name == "openai-compatible":
        if any(value is not None and not value.strip() for value in (endpoint, model)):
            raise ValueError("bundle runtime endpoint and model must not be empty")
        endpoint = endpoint or os.environ.get("LUNAR_EVOLUTION_MODEL_ENDPOINT")
        model = model or os.environ.get("LUNAR_EVOLUTION_MODEL") or "local"
        if api_key is None:
            api_key = os.environ.get("LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY")
    runtime = build_runtime(runtime_name, runtime_command or None, endpoint, model, api_key)
    generator = wrap(RuntimeAgentAdapter(runtime, name=name, roles=(role,), capabilities=declared))
    runtime_fingerprint = _runtime_fingerprint(
        runtime_name, command=runtime_command, endpoint=endpoint, model=model, name=name,
        role=role, required_capabilities=required, agent_loop=args.agent_runtime_loop,
        loop_max_steps=args.agent_runtime_max_steps, loop_allow_exec=args.agent_runtime_allow_exec,
        loop_memory=args.agent_runtime_memory, loop_session_history=args.agent_runtime_session_history,
    )
    fingerprint = hashlib.sha256(json.dumps(
        {"protocol": "lunar-bundle-agent-generator-v1", "runtime_fingerprint": runtime_fingerprint},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    if not args.agent_runtime_loop:
        return generator, fingerprint, None

    def initialize_loop(config):
        # Memory initialization happens only after all profile, Agent and strategy checks pass.
        loop = _build_evolution_runtime(
            config, args, runtime_name, runtime_command, endpoint, model, api_key,
        )
        return wrap(RuntimeAgentAdapter(loop, name=name, roles=(role,), capabilities=declared))

    return generator, fingerprint, initialize_loop


def _evolve_bundle(args: argparse.Namespace) -> dict[str, object]:
    """Validate an explicit multi-file profile before creating its ledger-backed run."""
    from ._benchmark_files import absolute_path, read_regular_file
    from .bundle_evolution import load_bundle_pipeline
    from .candidate_evaluation_spec import candidate_output_contract_sha256

    if args.resume != bool(args.run_id):
        raise ValueError("bundle_evolution_resume_requires_run_id")
    try:
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(
            read_regular_file(absolute_path(args.contract), MAX_CONTRACT_BYTES),
        ))
    except (EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise ValueError("bundle_evolution_contract_invalid") from None
    if contract.evolution.strategy != "population":
        raise ValueError("bundle_evolution_requires_population")
    pipeline = load_bundle_pipeline(args.profile)
    candidate_output_contract_sha256(contract.outputs)
    args.workspace = absolute_path(args.workspace)
    generator, generator_fingerprint, initialize_loop = _prepare_bundle_generator(args, contract, pipeline)
    evolution_config = pipeline.configure(EvolutionConfig(
        strategy="population",
        max_rounds=(contract.evolution.max_rounds if args.max_rounds is None else args.max_rounds),
        stagnation_rounds=(contract.evolution.stagnation_rounds
                           if args.stagnation_rounds is None else args.stagnation_rounds),
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        generator_fingerprint=generator_fingerprint,
    ))
    workspace = args.workspace
    if args.destination_root is not None:
        from ._candidate_workspace_io import DirectoryChain

        # A misspelled delivery destination must not spend a generation/evaluation budget.
        destination = DirectoryChain(absolute_path(args.destination_root), "destination_changed")
        destination.close()
    config = _config(args)
    if initialize_loop is not None:
        generator = initialize_loop(config)
    controller = LocalController(config, build_runtime("mock", None, None, None, None))
    if args.resume:
        run = controller.store.get_run(args.run_id)
        if run is None:
            raise ValueError("bundle_evolution_run_missing")
        if workspace != absolute_path(run.workspace):
            raise ValueError("bundle_evolution_workspace_mismatch")
    else:
        run = controller.create_evolution_run(contract, workspace=workspace)
    settled, result = controller.run_evolution(
        run.id, contract, generator, pipeline, evolution_config,
        resume=args.resume, bundle_pipeline=pipeline,
    )
    payload = {
        **result.to_dict(), "run_id": run.id, "run_status": settled.status.value,
        "workspace": str(settled.workspace), "contract_sha256": contract.digest(),
    }
    if args.destination_root is not None and result.status in {"completed", "stagnated"}:
        delivery = controller.deliver_bundle_evolution(run.id, args.destination_root)
        payload["delivery"] = {**delivery.to_dict(), "delivery_path": str(delivery.delivery_path)}
    return payload


def _evolve(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Create/execute one ledger-backed local evolution run."""
    try:
        payload = json.loads(args.contract.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read contract {args.contract}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract is not valid JSON: {exc.msg}") from exc
    contract = AlgorithmProblemContract.from_dict(payload)
    if contract.evolution.strategy == "loop":
        raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
    if args.strategy and args.strategy != contract.evolution.strategy:
        contract = replace(contract, evolution=replace(contract.evolution, strategy=args.strategy))
    controller = LocalController(config, build_runtime("mock", None, None, None, None))
    existing_run = None
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        existing_run = controller.store.get_run(args.run_id)
        if existing_run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        if args.workspace is not None and args.workspace.expanduser().resolve() != existing_run.workspace:
            raise ValueError("--workspace does not match the existing evolution run")
        canonical_path = existing_run.workspace / "evolution" / "contract.json"
        try:
            canonical = AlgorithmProblemContract.from_dict(
                json.loads(canonical_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("existing evolution run has an invalid canonical contract") from exc
        if canonical.digest() != contract.digest():
            raise ValueError("supplied contract does not match the existing evolution run")
        contract = canonical
    strategy_name = args.strategy or contract.evolution.strategy
    if strategy_name == "loop":
        raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
    producer_result = args.producer_result
    if producer_result is None and (args.producer_fingerprint is not None or args.producer_id is not None):
        raise ValueError("--producer-fingerprint and --producer-id require --producer-result")
    if producer_result is not None:
        if strategy_name != "population":
            raise ValueError("--producer-result is supported only by the population strategy")
        if not args.producer_fingerprint:
            raise ValueError("--producer-result requires --producer-fingerprint")
        if args.seed_dependency_sha256 is not None or args.seed_environment_sha256 is not None:
            raise ValueError("--producer-result cannot be combined with seed dependency/environment overrides")
        if not args.evaluator_command:
            raise ValueError("--producer-result requires --evaluator-command as the local exact harness")
    seeded = args.seed_manifest is not None or producer_result is not None
    if args.generator_command and strategy_name != "population":
        raise ValueError("--generator-command requires --strategy population")
    if args.openevolve_command and strategy_name != "openevolve":
        raise ValueError("--openevolve-command requires --strategy openevolve")
    seed_identity_options = (
        args.seed_dependency_sha256,
        args.seed_environment_sha256,
    )
    if args.seed_manifest is None and any(seed_identity_options):
        raise ValueError(
            "--seed-dependency-sha256 and --seed-environment-sha256 require --seed-manifest"
        )
    if args.seed_manifest is not None:
        if strategy_name != "population":
            raise ValueError("--seed-manifest is supported only by the population strategy")
        if not all(seed_identity_options):
            raise ValueError(
                "--seed-manifest requires --seed-dependency-sha256 and "
                "--seed-environment-sha256"
            )
        if not args.evaluator_command:
            raise ValueError(
                "--seed-manifest requires --evaluator-command as the local exact harness"
            )
    workspace = (existing_run.workspace if existing_run is not None else args.workspace)
    if workspace is None:
        if args.resume:
            raise ValueError("--resume requires an existing run")
        workspace = config.runs / f"evolution-{uuid.uuid4().hex[:12]}"
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = args.stagnation_rounds if args.stagnation_rounds is not None else contract.evolution.stagnation_rounds
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    agent_command = _parse_command(args.agent_command, "--agent-command")
    agent_portfolio_commands = tuple(
        _parse_command(value, "--agent-portfolio-command")
        for value in args.agent_portfolio_commands
    )
    evaluator_agent_command = _parse_command(
        args.evaluator_agent_command, "--evaluator-agent-command"
    )
    evaluator_portfolio_commands = tuple(
        _parse_command(value, "--evaluator-portfolio-command")
        for value in args.evaluator_portfolio_commands
    )
    candidate_runner_command = _parse_command(
        args.candidate_runner_command, "--candidate-runner-command"
    )
    agent_runtime = args.agent_runtime
    agent_runtime_command = _parse_command(
        args.agent_runtime_command, "--agent-runtime-command"
    )
    runtime_profile_options = (
        agent_runtime_command,
        args.agent_runtime_endpoint,
        args.agent_runtime_model,
        args.agent_runtime_api_key,
    )
    if (
        not isinstance(args.agent_runtime_max_steps, int)
        or isinstance(args.agent_runtime_max_steps, bool)
        or not 1 <= args.agent_runtime_max_steps <= 200
    ):
        raise ValueError("--agent-runtime-max-steps must be between 1 and 200")
    loop_options_used = bool(
        args.agent_runtime_loop
        or args.agent_runtime_allow_exec
        or args.agent_runtime_memory
        or args.agent_runtime_session_history
        or args.agent_runtime_max_steps != 40
    )
    if loop_options_used and agent_runtime is None:
        raise ValueError("evolution runtime loop options require --agent-runtime")
    if args.agent_runtime_loop and agent_runtime != "openai-compatible":
        raise ValueError("--agent-runtime-loop requires --agent-runtime openai-compatible")
    if any(
        option
        for option in (
            args.agent_runtime_allow_exec,
            args.agent_runtime_memory,
            args.agent_runtime_session_history,
        )
    ) and not args.agent_runtime_loop:
        raise ValueError("evolution loop options require --agent-runtime-loop")
    if args.agent_runtime_max_steps != 40 and not args.agent_runtime_loop:
        raise ValueError("--agent-runtime-max-steps requires --agent-runtime-loop")
    if agent_runtime is None and any(value is not None and value != () for value in runtime_profile_options):
        raise ValueError("runtime profile options require --agent-runtime")
    if agent_runtime == "subprocess" and not agent_runtime_command:
        raise ValueError("--agent-runtime subprocess requires --agent-runtime-command")
    if agent_runtime == "subprocess" and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime == "openai-compatible" and agent_runtime_command:
        raise ValueError("--agent-runtime-command requires --agent-runtime subprocess")
    if agent_runtime in {"mock", None} and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    runtime_endpoint = args.agent_runtime_endpoint
    runtime_model = args.agent_runtime_model
    runtime_api_key = args.agent_runtime_api_key
    if agent_runtime == "openai-compatible":
        runtime_endpoint = runtime_endpoint or os.environ.get("LUNAR_EVOLUTION_MODEL_ENDPOINT")
        runtime_model = runtime_model or os.environ.get("LUNAR_EVOLUTION_MODEL") or "local"
        if runtime_api_key is None:
            runtime_api_key = os.environ.get("LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY")
    if agent_runtime != "openai-compatible" and args.agent_runtime_api_key is not None:
        raise ValueError("--agent-runtime-api-key requires --agent-runtime openai-compatible")
    generator_fingerprint: str | None = None
    evaluator_fingerprint: str | None = None
    runner_fingerprint: str | None = _runner_fingerprint(candidate_runner_command, args.timeout)
    if strategy_name == "openevolve":
        if (
            agent_command
            or agent_portfolio_commands
            or evaluator_agent_command
            or evaluator_portfolio_commands
            or agent_runtime
            or any(value is not None and value != () for value in runtime_profile_options)
            or candidate_runner_command
        ):
            raise ValueError(
                "native solver/evaluator and candidate runner commands are only supported by population"
            )
        command = openevolve_command
        if not command:
            raise ValueError("openevolve strategy requires --openevolve-command")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("--openevolve-command must start with an existing absolute executable path")
        evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
        if not evaluator_command:
            raise ValueError(
                "openevolve strategy requires --evaluator-command for local verification"
            )
        evaluator_fingerprint = _adapter_fingerprint(
            evaluator_command,
            kind="objective-harness",
            name="command-evaluator",
            role="evaluator",
        )
        evaluator = CommandCandidateEvaluator(evaluator_command, args.timeout)

        def generator(request):
            del request
            raise EvolutionError("openevolve does not use a native generator")
    else:
        generator_command = _parse_command(args.generator_command, "--generator-command")
        evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
        if generator_command and (agent_command or agent_portfolio_commands):
            raise ValueError("generator and Agent portfolio commands are mutually exclusive")
        if agent_command and agent_portfolio_commands:
            raise ValueError("--agent-command and --agent-portfolio-command are mutually exclusive")
        solver_explicit = bool(generator_command or agent_command or agent_portfolio_commands)
        evaluator_explicit = bool(
            evaluator_command or evaluator_agent_command or evaluator_portfolio_commands
        )
        if candidate_runner_command and not evaluator_command:
            raise ValueError("--candidate-runner-command requires --evaluator-command")
        if agent_runtime and solver_explicit and evaluator_explicit:
            raise ValueError(
                "--agent-runtime is unused when both solver and evaluator are explicitly configured"
            )
        if sum(
            bool(option)
            for option in (evaluator_command, evaluator_agent_command, evaluator_portfolio_commands)
        ) > 1:
            raise ValueError(
                "--evaluator-command, --evaluator-agent-command, and "
                "--evaluator-portfolio-command are mutually exclusive"
            )
        if not evaluator_explicit and not agent_runtime:
            raise ValueError(
                "population requires --evaluator-command or "
                "--evaluator-agent-command or --evaluator-portfolio-command plus "
                "--generator-command, --agent-command, or "
                "at least two --agent-portfolio-command options"
            )
        if agent_portfolio_commands and len(agent_portfolio_commands) < 2:
            raise ValueError("--agent-portfolio-command requires at least two commands")
        if evaluator_portfolio_commands and len(evaluator_portfolio_commands) < 2:
            raise ValueError("--evaluator-portfolio-command requires at least two commands")
        if agent_command:
            generator_fingerprint = _adapter_fingerprint(
                agent_command,
                kind="generator",
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
            )
        elif agent_portfolio_commands:
            generator_fingerprint = _portfolio_fingerprint(
                agent_portfolio_commands,
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
            )
        elif agent_runtime:
            generator_fingerprint = _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name=args.agent_name,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        else:
            generator_fingerprint = _adapter_fingerprint(
                generator_command,
                kind="generator",
                name="command-generator",
                role="generator",
            )
        if evaluator_agent_command:
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_agent_command,
                kind="evaluator",
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
            )
        elif evaluator_portfolio_commands:
            evaluator_fingerprint = _portfolio_fingerprint(
                evaluator_portfolio_commands,
                kind="portfolio-evaluator",
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
            )
        elif evaluator_command:
            evaluator_fingerprint = _adapter_fingerprint(
                evaluator_command,
                kind="objective-harness" if seeded else "evaluator",
                name="command-evaluator",
                role="evaluator",
            )
        elif agent_runtime:
            evaluator_fingerprint = _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name=args.evaluator_agent_name,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        if agent_command:
            declared = {*DEFAULT_RUNTIME_CAPABILITIES, *args.agent_capabilities}
            adapter = CommandAgentAdapter(
                agent_command,
                roles=(args.agent_role,),
                capabilities=tuple(sorted(declared)),
                name=args.agent_name,
            )
            generator = AgentCandidateGenerator(
                adapter,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif agent_portfolio_commands:
            declared = {*DEFAULT_RUNTIME_CAPABILITIES, *args.agent_capabilities}
            adapters = tuple(
                CommandAgentAdapter(
                    command,
                    roles=(args.agent_role,),
                    capabilities=tuple(sorted(declared)),
                    name=f"{args.agent_name}-{index:02d}",
                )
                for index, command in enumerate(agent_portfolio_commands, start=1)
            )
            generator = AgentPortfolioGenerator(
                adapters,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif agent_runtime:
            runtime = _build_evolution_runtime(
                config,
                args,
                agent_runtime,
                agent_runtime_command,
                runtime_endpoint,
                runtime_model,
                runtime_api_key,
            )
            generator_adapter = RuntimeAgentAdapter(
                runtime,
                name=args.agent_name,
                roles=(args.agent_role,),
                capabilities=tuple(sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.agent_capabilities))),
            )
            generator = AgentCandidateGenerator(
                generator_adapter,
                contract=contract,
                role=args.agent_role,
                required_capabilities=tuple(args.agent_capabilities),
                timeout=args.timeout,
            )
        elif generator_command:
            generator = CommandCandidateGenerator(generator_command, args.timeout)
        else:
            raise ValueError("population requires --generator-command or --agent-command")
        if evaluator_agent_command:
            evaluator_adapter = CommandAgentAdapter(
                evaluator_agent_command,
                roles=(args.evaluator_agent_role,),
                capabilities=tuple(
                    sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.evaluator_agent_capabilities))
                ),
                name=args.evaluator_agent_name,
            )
            evaluator = AgentCandidateEvaluator(
                evaluator_adapter,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        elif evaluator_portfolio_commands:
            evaluator_adapters = tuple(
                CommandAgentAdapter(
                    command,
                    roles=(args.evaluator_agent_role,),
                    capabilities=tuple(
                        sorted(set(DEFAULT_RUNTIME_CAPABILITIES) | set(args.evaluator_agent_capabilities))
                    ),
                    name=f"{args.evaluator_agent_name}-{index:02d}",
                )
                for index, command in enumerate(evaluator_portfolio_commands, start=1)
            )
            evaluator = AgentEvaluatorEnsemble(
                evaluator_adapters,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        elif evaluator_command:
            evaluator = CommandCandidateEvaluator(evaluator_command, args.timeout)
        elif agent_runtime:
            runtime = _build_evolution_runtime(
                config,
                args,
                agent_runtime,
                agent_runtime_command,
                runtime_endpoint,
                runtime_model,
                runtime_api_key,
            )
            evaluator_adapter = RuntimeAgentAdapter(
                runtime,
                name=args.evaluator_agent_name,
                roles=(args.evaluator_agent_role,),
                capabilities=tuple(
                    sorted(
                        set(DEFAULT_RUNTIME_CAPABILITIES)
                        | set(args.evaluator_agent_capabilities)
                    )
                ),
            )
            evaluator = AgentCandidateEvaluator(
                evaluator_adapter,
                role=args.evaluator_agent_role,
                required_capabilities=tuple(args.evaluator_agent_capabilities),
                timeout=args.timeout,
            )
        else:
            raise ValueError("population evolution has no evaluator")
        if candidate_runner_command:
            evaluator = ExecutionAwareCandidateEvaluator(
                CommandCandidateRunner(candidate_runner_command, args.timeout), evaluator
            )
        command = agent_command
    evolution_config = EvolutionConfig(
        strategy=strategy_name,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        command=command,
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
        runner_fingerprint=runner_fingerprint,
    )
    if args.resume:
        state_path = workspace / "evolution" / "state.json"
        if state_path.is_file():
            try:
                state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("existing evolution state is not valid JSON") from exc
            if (
                isinstance(state_payload, dict)
                and state_payload.get("config") is not None
                and state_payload.get("config") != evolution_config.to_dict()
            ):
                raise ValueError("evolution resume configuration does not match the existing run")
    seed_manifest = args.seed_manifest
    seed_dependency = args.seed_dependency_sha256
    seed_environment = args.seed_environment_sha256
    if producer_result is not None:
        from .producer_handoff import prepare_producer_seed_manifest

        seed_manifest = prepare_producer_seed_manifest(
            producer_result, contract, evaluator_fingerprint=evaluator_fingerprint,
            producer_fingerprint=args.producer_fingerprint, producer_id=args.producer_id,
        )
        seed_dependency = seed_manifest.dependency_sha256
        seed_environment = seed_manifest.environment_sha256
    if existing_run is None:
        run = controller.create_evolution_run(contract, workspace=workspace)
    else:
        run = existing_run
    if args.detach and not args.resume:
        return _detach_evolution(config, args, run, contract)
    settled, result = controller.run_evolution(
        run.id,
        contract,
        generator,
        evaluator,
        evolution_config,
        resume=args.resume,
        seed_manifest=seed_manifest,
        seed_dependency_sha256=seed_dependency,
        seed_environment_sha256=seed_environment,
    )
    return {
        **result.to_dict(),
        "run_id": run.id,
        "status": result.status,
        "run_status": settled.status.value,
        "workspace": str(settled.workspace),
        "contract_sha256": contract.digest(),
    }


def _benchmark(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Compare strategies with explicit commands or repository-owned runtime profiles."""
    try:
        payload = json.loads(args.contract.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read contract {args.contract}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract is not valid JSON: {exc.msg}") from exc
    contract = AlgorithmProblemContract.from_dict(payload)
    strategies = tuple(args.strategies or ("population",))
    generator_command = _parse_command(args.generator_command, "--generator-command")
    evaluator_command = _parse_command(args.evaluator_command, "--evaluator-command")
    openevolve_command = _parse_command(args.openevolve_command, "--openevolve-command")
    agent_runtime = args.agent_runtime
    agent_runtime_command = _parse_command(
        args.agent_runtime_command, "--agent-runtime-command"
    )
    runtime_profile_options = (
        agent_runtime_command,
        args.agent_runtime_endpoint,
        args.agent_runtime_model,
        args.agent_runtime_api_key,
    )
    if (
        not isinstance(args.agent_runtime_max_steps, int)
        or isinstance(args.agent_runtime_max_steps, bool)
        or not 1 <= args.agent_runtime_max_steps <= 200
    ):
        raise ValueError("--agent-runtime-max-steps must be between 1 and 200")
    loop_options_used = bool(
        args.agent_runtime_loop
        or args.agent_runtime_allow_exec
        or args.agent_runtime_memory
        or args.agent_runtime_session_history
        or args.agent_runtime_max_steps != 40
    )
    if loop_options_used and agent_runtime is None:
        raise ValueError("benchmark runtime loop options require --agent-runtime")
    if args.agent_runtime_loop and agent_runtime != "openai-compatible":
        raise ValueError("--agent-runtime-loop requires --agent-runtime openai-compatible")
    if any(
        option
        for option in (
            args.agent_runtime_allow_exec,
            args.agent_runtime_memory,
            args.agent_runtime_session_history,
        )
    ) and not args.agent_runtime_loop:
        raise ValueError("benchmark runtime loop options require --agent-runtime-loop")
    if args.agent_runtime_max_steps != 40 and not args.agent_runtime_loop:
        raise ValueError("--agent-runtime-max-steps requires --agent-runtime-loop")
    if agent_runtime is None and any(
        value is not None and value != () for value in runtime_profile_options
    ):
        raise ValueError("runtime profile options require --agent-runtime")
    if agent_runtime == "subprocess" and not agent_runtime_command:
        raise ValueError("--agent-runtime subprocess requires --agent-runtime-command")
    if agent_runtime == "subprocess" and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime == "openai-compatible" and agent_runtime_command:
        raise ValueError("--agent-runtime-command requires --agent-runtime subprocess")
    if agent_runtime in {"mock", None} and (
        args.agent_runtime_endpoint or args.agent_runtime_model
    ):
        raise ValueError("endpoint/model options require --agent-runtime openai-compatible")
    if agent_runtime != "openai-compatible" and args.agent_runtime_api_key is not None:
        raise ValueError("--agent-runtime-api-key requires --agent-runtime openai-compatible")
    runtime_endpoint = args.agent_runtime_endpoint
    runtime_model = args.agent_runtime_model
    runtime_api_key = args.agent_runtime_api_key
    if agent_runtime == "openai-compatible":
        runtime_endpoint = runtime_endpoint or os.environ.get("LUNAR_EVOLUTION_MODEL_ENDPOINT")
        runtime_model = runtime_model or os.environ.get("LUNAR_EVOLUTION_MODEL") or "local"
        if runtime_api_key is None:
            runtime_api_key = os.environ.get("LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY")
        if not runtime_endpoint:
            raise ValueError(
                "openai-compatible runtime requires --agent-runtime-endpoint or LUNAR_EVOLUTION_MODEL_ENDPOINT"
            )
    if agent_runtime and "openevolve" in strategies:
        raise ValueError("--agent-runtime cannot be combined with --strategy openevolve")
    if "openevolve" in strategies and not openevolve_command:
        raise ValueError("benchmark requires --openevolve-command for openevolve")
    if openevolve_command and "openevolve" not in strategies:
        raise ValueError("--openevolve-command requires --strategy openevolve")
    native_selected = any(strategy != "openevolve" for strategy in strategies)
    if generator_command and not native_selected:
        raise ValueError("--generator-command requires --strategy population")
    if native_selected and not agent_runtime and not generator_command:
        raise ValueError("benchmark requires --generator-command for population")
    if not evaluator_command and not agent_runtime:
        raise ValueError("benchmark requires --evaluator-command or --agent-runtime")
    if agent_runtime and generator_command and evaluator_command:
        raise ValueError("runtime profile is unused when generator and evaluator are explicit")
    max_rounds = args.max_rounds if args.max_rounds is not None else contract.evolution.max_rounds
    stagnation_rounds = (
        args.stagnation_rounds
        if args.stagnation_rounds is not None
        else contract.evolution.stagnation_rounds
    )
    benchmark_config = BenchmarkConfig(
        strategies=strategies,
        max_rounds=max_rounds,
        stagnation_rounds=stagnation_rounds,
        population_size=args.population_size,
        offspring_per_iteration=args.offspring_per_iteration,
        num_islands=args.islands,
        migration_interval=args.migration_interval,
        migration_rate=args.migration_rate,
        rng_seed=args.seed,
        timeout_seconds=args.timeout,
        generator_fingerprint=(
            _adapter_fingerprint(
                generator_command,
                kind="benchmark-generator",
                name="command-generator",
                role="solver",
            )
            if generator_command
            else _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name="benchmark-solver",
                role="solver",
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
            if native_selected
            else None
        ),
        evaluator_fingerprint=(
            _adapter_fingerprint(
                evaluator_command,
                kind="objective-harness",
                name="command-evaluator",
                role="evaluator",
            )
            if evaluator_command
            else _runtime_fingerprint(
                agent_runtime,
                command=agent_runtime_command,
                endpoint=runtime_endpoint,
                model=runtime_model,
                name="benchmark-evaluator",
                role="evaluator",
                agent_loop=args.agent_runtime_loop,
                loop_max_steps=args.agent_runtime_max_steps,
                loop_allow_exec=args.agent_runtime_allow_exec,
                loop_memory=args.agent_runtime_memory,
                loop_session_history=args.agent_runtime_session_history,
            )
        ),
        evaluator_kind="exact_harness" if evaluator_command else "native",
        strategy_commands={"openevolve": openevolve_command} if openevolve_command else {},
        runtime_profile=(
            {
                "kind": agent_runtime,
                "loop": args.agent_runtime_loop,
                "max_steps": args.agent_runtime_max_steps,
                "allow_exec": args.agent_runtime_allow_exec,
                "memory": args.agent_runtime_memory,
                "session_history": args.agent_runtime_session_history,
            }
            if agent_runtime
            else None
        ),
    )
    workspace = args.workspace
    if workspace is None:
        workspace = config.runs / f"benchmark-{uuid.uuid4().hex[:12]}"
    workspace = workspace.expanduser().resolve()

    def generator_factory(_strategy: str) -> CommandCandidateGenerator:
        if generator_command:
            return CommandCandidateGenerator(generator_command, args.timeout)
        runtime = _build_evolution_runtime(
            config,
            args,
            agent_runtime,
            agent_runtime_command,
            runtime_endpoint,
            runtime_model,
            runtime_api_key,
        )
        adapter = RuntimeAgentAdapter(runtime, name="benchmark-solver", roles=("solver",))
        return AgentCandidateGenerator(adapter, contract=contract, timeout=args.timeout)

    def evaluator_factory(_strategy: str) -> object:
        if evaluator_command:
            return CommandCandidateEvaluator(evaluator_command, args.timeout)
        runtime = _build_evolution_runtime(
            config,
            args,
            agent_runtime,
            agent_runtime_command,
            runtime_endpoint,
            runtime_model,
            runtime_api_key,
        )
        adapter = RuntimeAgentAdapter(runtime, name="benchmark-evaluator", roles=("evaluator",))
        return AgentCandidateEvaluator(adapter, timeout=args.timeout)

    report = BenchmarkRunner(
        contract,
        workspace,
        generator_factory=generator_factory if native_selected else None,
        evaluator_factory=evaluator_factory,
        config=benchmark_config,
    ).run()
    status = (
        "completed"
        if any(item.status in {"completed", "stagnated"} for item in report.runs)
        else "failed"
    )
    return {**report.to_dict(), "status": status, "workspace": str(workspace)}


def _effect_report_is_inside(report: Path, root: Path) -> bool:
    """Compare existing directory identities, including macOS name aliases.

    Missing root components have no identity yet. Compare their names conservatively across
    case and Unicode normalization so creating the workspace cannot absorb the sidecar later.
    """
    anchor = root
    while True:
        try:
            identity = anchor.stat()
            break
        except FileNotFoundError:
            if anchor == anchor.parent:
                raise ValueError("host execution report location could not be validated") from None
            anchor = anchor.parent
    missing = root.relative_to(anchor).parts
    for ancestor in (report, *report.parents):
        try:
            candidate = ancestor.stat()
        except FileNotFoundError:
            continue
        if (candidate.st_dev, candidate.st_ino) != (identity.st_dev, identity.st_ino):
            continue
        tail = report.relative_to(ancestor).parts
        normalize = lambda value: unicodedata.normalize("NFD", value).casefold()
        return len(tail) >= len(missing) and all(
            normalize(left) == normalize(right) for left, right in zip(missing, tail)
        )
    return False


def _effect_host_scope(
    args: argparse.Namespace,
    operation: Callable[[argparse.Namespace], dict[str, object]],
) -> dict[str, object]:
    report = getattr(args, "keep_awake_report", None)
    if report is None:
        return operation(args)

    sources = _effect_mapping(args.case_source, "--case-source")
    try:
        report = report.expanduser()
        resolved_report = report.resolve()
        workspace = args.workspace.expanduser().resolve()
        source_roots = [path.expanduser().resolve() for path in sources.values()]
        in_workspace = _effect_report_is_inside(resolved_report, workspace)
        in_source = any(_effect_report_is_inside(resolved_report, source) for source in source_roots)
    except (OSError, RuntimeError, ValueError):
        raise ValueError("host execution report location could not be validated") from None
    if in_workspace:
        raise ValueError("host execution report must be outside the trial workspace")
    if in_source:
        raise ValueError("host execution report must be outside case sources")

    from .host_session import host_execution

    # Preserve the supplied path so the scope can reject symlink components itself.
    with host_execution(report):
        return operation(args)


def _effect_trial(args: argparse.Namespace) -> dict[str, object]:
    profile = _load_model_profile(getattr(args, "model_profile", None))
    if profile is not None and profile.model != args.requested_model:
        raise ValueError("--requested-model does not match model profile model")
    trial_config = EffectTrialConfig(
        runs_per_case=args.runs_per_case,
        timeout_seconds=args.timeout,
        requested_model=args.requested_model,
        subject_command=_parse_command(args.subject_command, "--subject-command"),
        harness_command=_parse_command(args.harness_command, "--harness-command"),
        subject_environment=_effect_environment(args.subject_env, "subject"),
        harness_environment=_effect_environment(args.harness_env, "harness"),
        model_profile_sha256=_model_profile_digest(profile),
        subject_model_profile_path=(
            args.model_profile.expanduser().resolve() if profile is not None else None
        ),
    )
    return EffectTrialRunner(
        args.suite,
        args.baseline,
        args.workspace,
        case_sources=_effect_mapping(args.case_source, "--case-source"),
        config=trial_config,
        resume=args.resume,
    ).run().to_dict()


def _effect_preflight(args: argparse.Namespace) -> dict[str, object]:
    profile = _load_model_profile(getattr(args, "model_profile", None))
    if profile is not None and profile.model != args.requested_model:
        raise ValueError("--requested-model does not match model profile model")
    return run_effect_preflight(
        args.suite,
        args.baseline,
        case_sources=_effect_mapping(args.case_source, "--case-source"),
        subject_command=_parse_command(args.subject_command, "--subject-command"),
        harness_command=_parse_command(args.harness_command, "--harness-command"),
        requested_model=args.requested_model,
        harness_python=args.harness_python,
        harness_imports=args.harness_import,
        harness_packages=args.harness_package,
        subject_environment=_effect_environment(args.subject_env, "subject"),
        harness_environment=_effect_environment(args.harness_env, "harness"),
        model_profile_sha256=_model_profile_digest(profile),
        subject_model_profile_path=(
            args.model_profile.expanduser().resolve() if profile is not None else None
        ),
        runs_per_case=args.runs_per_case,
        timeout_seconds=args.timeout,
        output=args.output,
    )


def _effect_deep_trial(args: argparse.Namespace) -> dict[str, object]:
    profile = _load_model_profile(getattr(args, "model_profile", None))
    if profile is not None and profile.model != args.requested_model:
        raise ValueError("--requested-model does not match model profile model")
    base = EffectTrialConfig(
        runs_per_case=args.runs_per_case,
        timeout_seconds=args.timeout,
        requested_model=args.requested_model,
        subject_command=_parse_command(args.subject_command, "--subject-command"),
        harness_command=_parse_command(args.harness_command, "--harness-command"),
        subject_environment=_effect_environment(args.subject_env, "subject"),
        harness_environment=_effect_environment(args.harness_env, "harness"),
        model_profile_sha256=_model_profile_digest(profile),
        subject_model_profile_path=(
            args.model_profile.expanduser().resolve() if profile is not None else None
        ),
    )
    config = DeepEffectTrialConfig(
        base=base,
        outer_rounds=args.outer_rounds,
        stagnation_rounds=args.stagnation_rounds,
    )
    return DeepEffectTrialRunner(
        args.suite,
        args.baseline,
        args.workspace,
        case_sources=_effect_mapping(args.case_source, "--case-source"),
        config=config,
        resume=args.resume,
    ).run().to_dict()


def _effect_kit(args: argparse.Namespace) -> dict[str, object]:
    return build_effect_kit(
        args.output,
        _effect_mapping(args.case, "--case"),
        benchmark_name=args.benchmark_name,
        evaluation_profile_name=args.profile_name,
        evaluation_profile_revision=args.profile_revision,
        owner_attested_content_equivalence=args.owner_attested_content_equivalence,
    )


def _effect_subject(args: argparse.Namespace) -> dict[str, object]:
    profile = _load_model_profile(getattr(args, "model_profile", None))
    if profile is not None and args.model is not None and args.model != profile.model:
        raise ValueError("--model does not match model profile model")
    workflow_path = getattr(args, "workflow_config", None)
    return run_subject_adapter(
        args.request,
        endpoint=args.endpoint,
        model=args.model,
        api_key=args.api_key,
        max_steps=args.max_steps,
        allow_exec=not args.no_exec,
        timeout=args.timeout,
        model_profile=profile,
        workflow_config=StagedWorkflowConfig.load(workflow_path) if workflow_path else None,
    )


def _effect_harness(args: argparse.Namespace) -> dict[str, object]:
    return run_harness_adapter(
        args.request,
        args.case_root,
        python_bin=args.python,
        extractor_environment=_effect_environment(args.extractor_env, "extractor"),
        timeout=args.timeout,
    )


def _effect_baseline(args: argparse.Namespace) -> dict[str, object]:
    return convert_fm_eval_baseline(
        args.results,
        args.suite,
        args.output,
        experiment_id=args.experiment_id,
        requested_model=args.requested_model,
        effective_model=args.effective_model,
        model_evidence=args.model_evidence,
        authority=args.authority,
        conclusion_eligibility=args.conclusion_eligibility,
        content_equivalence_attested=args.owner_attested_content_equivalence,
        adapter_kind=args.adapter_kind,
        baseline_source=args.baseline_source,
    )


def _delegate(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Delegate one task through an explicitly supplied command adapter."""
    command = _parse_command(args.agent_command, "--agent-command")
    declared_capabilities = set(args.capabilities)
    initial_adapter = CommandAgentAdapter(
        command,
        roles=(args.agent_role,),
        capabilities=tuple(sorted(declared_capabilities)),
        name=args.agent_name,
    )
    # The command adapter is the worker; the mock runtime is retained only to satisfy the
    # controller's backwards-compatible Runtime constructor and is never invoked here. Pass the
    # selected registry at construction time so WorkerService cannot retain a stale registry.
    controller = LocalController(
        config,
        build_runtime("mock", None, None, None, None),
        agent_registry=AgentRegistry([initial_adapter]),
    )
    if args.run_id:
        run = controller.store.get_run(args.run_id)
        if run is None:
            raise ValueError(f"unknown run: {args.run_id}")
        if args.prompt is not None and not args.prompt.strip():
            raise ValueError("prompt must not be empty")
    else:
        if not isinstance(args.prompt, str) or not args.prompt.strip():
            raise ValueError("delegate requires a prompt unless --run-id is supplied")
        run = controller.create(args.prompt.strip())
    if args.detach:
        if args.run_id:
            raise ValueError("--detach is only valid when creating a new delegated run")
        return _detach_delegate(config, args, run)
    # ``WorkerService`` owns a non-daemon executor.  Running a bounded observation in
    # this process would therefore make the interpreter wait for the worker at shutdown,
    # defeating ``--wait-timeout``.  Move the durable execution to a child host and only
    # keep the short observation loop in the caller.
    if args.wait_timeout is not None:
        return _delegate_wait_timeout(config, args, run)
    declared_capabilities.update(run.route_required_capabilities)
    if declared_capabilities != set(args.capabilities):
        adapter = CommandAgentAdapter(
            command,
            roles=(args.agent_role,),
            capabilities=tuple(sorted(declared_capabilities)),
            name=args.agent_name,
        )
        registry = AgentRegistry([adapter])
        controller.agent_registry = registry
        controller.workers.registry = registry
    try:
        settled, result = controller.run_worker_agent(
            run.id,
            role=args.agent_role,
            prompt=args.prompt.strip() if isinstance(args.prompt, str) and args.prompt.strip() else None,
            required_capabilities=tuple(args.capabilities),
            preferred_adapter=args.preferred_agent,
            task_id=args.task_id,
            timeout=args.timeout,
            wait_timeout=args.wait_timeout,
        )
    except WorkerObservationTimeout as exc:
        current = controller.store.get_run(run.id)
        if current is None:
            raise ValueError(f"run disappeared while observing worker: {run.id}") from exc
        return {
            "run_id": current.id,
            "task_id": args.task_id or controller.store.list_tasks(current.id)[0].id,
            "worker_id": exc.worker_id,
            "status": "running",
            "run_status": current.status.value,
            "adapter": args.agent_name,
            "role": args.agent_role,
            "text": None,
            "artifacts": [],
            "metadata": {},
            "error": None,
            "workspace": str(current.workspace),
        }
    finally:
        controller.store.clear_runner_process(run.id, os.getpid())
    return {
        "run_id": settled.id,
        "task_id": args.task_id or controller.store.list_tasks(settled.id)[0].id,
        "status": result.status,
        "run_status": settled.status.value,
        "adapter": result.adapter_name,
        "role": result.role,
        "text": result.text,
        "artifacts": list(result.artifacts),
        "metadata": result.metadata,
        "error": result.error,
        "workspace": str(settled.workspace),
    }


def _detach_delegate(config: Config, args: argparse.Namespace, run: Run) -> dict[str, object]:
    """Spawn a child that re-enters the same explicit delegation request."""
    log_path = run.workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "lunar_evolution",
        "delegate",
    ]
    if isinstance(args.prompt, str) and args.prompt.strip():
        command.append(args.prompt)
    command.extend([
        "--run-id",
        run.id,
        "--agent-command",
        args.agent_command,
        "--agent-name",
        args.agent_name,
        "--agent-role",
        args.agent_role,
        "--home",
        str(config.home),
        "--json",
    ])
    delegated_capabilities = set(args.capabilities) | set(run.route_required_capabilities)
    for capability in sorted(delegated_capabilities):
        command.extend(("--capability", capability))
    if args.preferred_agent:
        command.extend(("--preferred-agent", args.preferred_agent))
    if args.task_id:
        command.extend(("--task-id", args.task_id))
    if args.timeout is not None:
        command.extend(("--timeout", str(args.timeout)))
    # The child is the durable worker host.  It must observe to completion so the
    # binding is eventually settled; a caller's wait budget only applies to the
    # parent observation window.
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run.id, pid, pgid)
            latest = store.get_run(run.id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run.id)
    except OSError as exc:
        Store(config.database).cancel_run(run.id)
        raise AgentError(f"could not start detached delegation: {exc}") from exc
    return {
        "run_id": run.id,
        "status": "pending",
        "run_status": "pending",
        "workspace": str(run.workspace),
        "detached": True,
    }


def _delegate_result_projection(
    store: Store, args: argparse.Namespace, run: Run,
) -> dict[str, object]:
    """Project the durable worker result into the delegate CLI response shape."""
    tasks = store.list_tasks(run.id)
    task = store.get_task(args.task_id) if args.task_id else None
    if task is None:
        bindings = store.list_worker_bindings(run.id)
        binding = next(
            (item for item in reversed(bindings) if item.status in {"active", "delivering", "settled", "discarded", "lost"}),
            None,
        )
        if binding is not None:
            task = store.get_task(binding.task_id)
    if task is None and tasks:
        task = tasks[0]
    binding = None
    if task is not None:
        bindings = store.list_worker_bindings(run.id)
        binding = next((item for item in reversed(bindings) if item.task_id == task.id), None)
    envelope = None
    if binding is not None:
        envelope = store.get_worker_result(
            binding.worker_id,
            binding.worker_attempt_id,
            owner_id=run.id,
        )
    result = envelope.to_agent_result() if envelope is not None else None
    status = result.status if result is not None else (
        "succeeded" if task is not None and task.state.value == "succeeded" else "failed"
        if task is not None and task.state.value == "failed" else run.status.value
    )
    return {
        "run_id": run.id,
        "task_id": task.id if task is not None else args.task_id,
        "worker_id": binding.worker_id if binding is not None else None,
        "status": status,
        "run_status": run.status.value,
        "adapter": result.adapter_name if result is not None else args.agent_name,
        "role": result.role if result is not None else args.agent_role,
        "text": result.text if result is not None else None,
        "artifacts": list(result.artifacts) if result is not None else [],
        "metadata": result.metadata if result is not None else {},
        "error": (result.error if result is not None else (task.last_error if task is not None else None)),
        "workspace": str(run.workspace),
    }


def _delegate_wait_timeout(config: Config, args: argparse.Namespace, run: Run) -> dict[str, object]:
    """Host a durable delegation in a child while observing it for a bounded period."""
    store = Store(config.database)
    # A later invocation with ``--run-id`` must attach to the existing durable runner.  The
    # runner PID is written immediately after spawn; the binding may appear a little later while
    # the child imports the application and claims its task.
    active = [
        item for item in store.list_worker_bindings(run.id)
        if item.status in {"active", "delivering"}
    ]
    runner_pid = run.runner_pid
    if not active and not (isinstance(runner_pid, int) and runner_pid > 1):
        _detach_delegate(config, args, run)
    wait_seconds = max(0.0, float(args.wait_timeout))
    started = time.monotonic()
    deadline = started + wait_seconds
    # Keep startup allowance short so a tiny caller wait budget remains a bounded foreground
    # observation.  Once a binding is visible, the normal deadline is authoritative.
    startup_deadline = started + min(0.08, max(0.02, wait_seconds * 2.0))
    terminal = {"succeeded", "failed", "cancelled"}
    while True:
        current = store.get_run(run.id)
        if current is None:
            raise ValueError(f"run disappeared while observing worker: {run.id}")
        if current.status.value in terminal:
            return _delegate_result_projection(store, args, current)
        active = [
            item for item in store.list_worker_bindings(run.id)
            if item.status in {"active", "delivering"}
        ]
        if not active and time.monotonic() < startup_deadline:
            time.sleep(0.01)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            binding = active[-1] if active else None
            tasks = store.list_tasks(run.id)
            task_id = binding.task_id if binding is not None else (args.task_id or (tasks[0].id if tasks else None))
            return {
                "run_id": current.id,
                "task_id": task_id,
                "worker_id": binding.worker_id if binding is not None else None,
                "status": "running",
                "run_status": current.status.value,
                "adapter": args.agent_name,
                "role": args.agent_role,
                "text": None,
                "artifacts": [],
                "metadata": {},
                "error": None,
                "workspace": str(current.workspace),
            }
        time.sleep(min(0.05, remaining))


def _detach_evolution(
    config: Config,
    args: argparse.Namespace,
    run: Run,
    contract: AlgorithmProblemContract,
) -> dict[str, object]:
    """Spawn a child process that resumes the already-created local evolution run."""
    run_id = run.id
    workspace = run.workspace
    log_path = workspace / "controller.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "lunar_evolution",
        "evolve",
        str(args.contract.expanduser().resolve()),
        "--resume",
        "--run-id",
        run_id,
        "--home",
        str(config.home),
        "--json",
    ]
    if args.strategy:
        command.extend(("--strategy", args.strategy))
    if args.seed_manifest is not None:
        command.extend(("--seed-manifest", str(args.seed_manifest.expanduser().absolute())))
    if args.producer_result is not None:
        command.extend(("--producer-result", str(args.producer_result.expanduser().absolute())))
        command.extend(("--producer-fingerprint", args.producer_fingerprint))
        if args.producer_id is not None:
            command.extend(("--producer-id", args.producer_id))
    if args.seed_dependency_sha256 is not None:
        command.extend(("--seed-dependency-sha256", args.seed_dependency_sha256))
    if args.seed_environment_sha256 is not None:
        command.extend(("--seed-environment-sha256", args.seed_environment_sha256))
    if args.generator_command:
        command.extend(("--generator-command", args.generator_command))
    if args.agent_command:
        command.extend(("--agent-command", args.agent_command))
    for portfolio_command in args.agent_portfolio_commands:
        command.extend(("--agent-portfolio-command", portfolio_command))
    if args.agent_runtime:
        command.extend(("--agent-runtime", args.agent_runtime))
    if args.agent_runtime_command:
        command.extend(("--agent-runtime-command", args.agent_runtime_command))
    if args.agent_runtime_endpoint:
        command.extend(("--agent-runtime-endpoint", args.agent_runtime_endpoint))
    if args.agent_runtime_model:
        command.extend(("--agent-runtime-model", args.agent_runtime_model))
    if args.agent_runtime_loop:
        command.append("--agent-runtime-loop")
    if args.agent_runtime_allow_exec:
        command.append("--agent-runtime-allow-exec")
    if args.agent_runtime_memory:
        command.append("--agent-runtime-memory")
    if args.agent_runtime_session_history:
        command.append("--agent-runtime-session-history")
    if args.agent_runtime_max_steps != 40:
        command.extend(("--agent-runtime-max-steps", str(args.agent_runtime_max_steps)))
    if args.candidate_runner_command:
        command.extend(("--candidate-runner-command", args.candidate_runner_command))
    if args.agent_name != "evolution-agent":
        command.extend(("--agent-name", args.agent_name))
    if args.agent_role != "solver":
        command.extend(("--agent-role", args.agent_role))
    for capability in args.agent_capabilities:
        command.extend(("--agent-capability", capability))
    if args.evaluator_command:
        command.extend(("--evaluator-command", args.evaluator_command))
    if args.evaluator_agent_command:
        command.extend(("--evaluator-agent-command", args.evaluator_agent_command))
    for portfolio_command in args.evaluator_portfolio_commands:
        command.extend(("--evaluator-portfolio-command", portfolio_command))
    if args.evaluator_agent_name != "evolution-evaluator":
        command.extend(("--evaluator-agent-name", args.evaluator_agent_name))
    if args.evaluator_agent_role != "evaluator":
        command.extend(("--evaluator-agent-role", args.evaluator_agent_role))
    for capability in args.evaluator_agent_capabilities:
        command.extend(("--evaluator-agent-capability", capability))
    if args.openevolve_command:
        command.extend(("--openevolve-command", args.openevolve_command))
    for option, value in (
        ("--max-rounds", args.max_rounds),
        ("--stagnation-rounds", args.stagnation_rounds),
        ("--population-size", args.population_size),
        ("--offspring-per-iteration", args.offspring_per_iteration),
        ("--islands", args.islands),
        ("--migration-interval", args.migration_interval),
        ("--migration-rate", args.migration_rate),
        ("--seed", args.seed),
        ("--timeout", args.timeout),
    ):
        if value is not None:
            command.extend((option, str(value)))
    child_env = None
    if args.agent_runtime_api_key is not None:
        child_env = os.environ.copy()
        child_env["LUNAR_EVOLUTION_AGENT_RUNTIME_API_KEY"] = args.agent_runtime_api_key
    try:
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                env=child_env,
            )
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 1:
            store = Store(config.database)
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid
            store.set_runner_process(run_id, pid, pgid)
            latest = store.get_run(run_id)
            if latest is not None and latest.status.value in {"succeeded", "failed", "cancelled"}:
                store.clear_runner_process(run_id)
    except OSError as exc:
        Store(config.database).cancel_run(run_id)
        raise EvolutionError(f"could not start detached evolution run: {exc}") from exc
    return {
        "run_id": run_id,
        "status": "pending",
        "strategy": contract.evolution.strategy,
        "workspace": str(workspace),
        "detached": True,
    }


def _rsi_record_payload(record) -> dict[str, object]:
    return {
        "logical_id": record.logical_id,
        "revision": record.revision,
        "kind": record.kind,
        "state": record.state,
        "request_sha256": record.request_sha256,
        "parent_record_sha256": record.parent_record_sha256,
        "payload": record.payload,
        "record_sha256": record.record_sha256,
        "created_at": record.created_at,
    }


def _rsi_callback_json(path: Path, *, maximum: int, name: str) -> dict[str, object]:
    error = f"rsi_callback_{name}_file_invalid"
    if path.name == ".env" or path.name.startswith(".env."):
        raise ValueError(error)
    content = _read_bounded_regular_file(path, maximum, error=error)
    try:
        value = _strict_json_loads(content)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(error) from exc
    if not isinstance(value, dict):
        raise TypeError(error)
    return value


def _rsi_run_payload(config: Config, args: argparse.Namespace) -> dict[str, object]:
    """Run only the deterministic local RSI fixture from the CLI.

    Real solver processes are deliberately not started by this diagnostic command.  They enter
    the same controller later through ``SolverGateway`` adapters after their receipt contract is
    implemented.
    """
    reconciliation_options = (
        args.reconcile_callback, args.expected_checkpoint_sha256,
        args.callback_result, args.callback_evidence,
    )
    reconcile_requested = any(value is not None for value in reconciliation_options)
    if reconcile_requested and (
        any(value is None for value in reconciliation_options) or not args.run_id or not args.run_id.strip()
    ):
        raise ValueError("rsi_callback_reconcile_options_required")
    try:
        contract_bytes = args.contract.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read RSI contract: {exc}") from exc
    contract_sha256 = args.contract_sha256 or hashlib.sha256(contract_bytes).hexdigest()
    evaluator_sha256 = args.evaluator_sha256 or hashlib.sha256(b"lunar-rsi-local-exact-v1").hexdigest()
    environment_sha256 = args.environment_sha256 or hashlib.sha256(b"lunar-rsi-local-fixture-v1").hexdigest()
    run_id = args.run_id or f"rsi-{uuid.uuid4().hex[:16]}"
    ledger = RSILedger(config.home / "rsi.sqlite3")
    gateway = fixture_solver_gateway(args.solver, terminal_status=args.worker_status)

    judge_mode = args.mode

    def target_judge(execution):
        # Make the successful local fixture exercise the learning gate once before transfer.
        if judge_mode == "drs" and execution.episode.episode_kind == "target" and execution.episode.wave == 0:
            return False, "local fixture capability gap"
        return execution.passed, "local fixture target accepted" if execution.passed else execution.verifier.diagnosis

    controller = RSILearningController(
        gateway,
        curriculum=DeterministicCurriculum(),
        target_judge=target_judge,
        ledger=ledger,
    )
    if reconcile_requested:
        record = ledger.get_run(run_id)
        if record is None:
            raise ValueError("rsi_callback_run_missing")
        for field, observed in (
            ("mode", args.mode), ("contract_sha256", contract_sha256),
            ("evaluator_sha256", evaluator_sha256), ("environment_sha256", environment_sha256),
            ("solver_id", args.solver),
        ):
            if record.payload.get(field) != observed:
                raise ValueError(f"rsi_resume_{field}_drift")
        result = controller.reconcile_callback(
            run_id, args.reconcile_callback,
            expected_checkpoint_sha256=args.expected_checkpoint_sha256,
            result=_rsi_callback_json(args.callback_result, maximum=1024 * 1024, name="result"),
            evidence=_rsi_callback_json(args.callback_evidence, maximum=128 * 1024, name="evidence"),
        )
        return {
            "run_id": run_id, "mode": args.mode, "status": "reconciled",
            "callback_id": args.reconcile_callback, "result": result,
            "ledger": str(config.home / "rsi.sqlite3"),
        }
    if args.mode == "drs":
        result = controller.run_drs(
            run_id=run_id,
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            solver_id=args.solver,
            max_practice_rounds=args.max_practice_rounds,
            max_target_attempts=args.max_target_attempts,
        )
    else:
        target = controller._target_episode(
            run_id,
            f"{run_id}-target-seed",
            {
                "contract_sha256": contract_sha256,
                "evaluator_sha256": evaluator_sha256,
                "environment_sha256": environment_sha256,
                "solver_id": args.solver,
            },
            0,
        )
        decisions = tuple(
            controller.curriculum.choose(target=target, diagnosis=f"fixture-gap-{index}", wave=0, ordinal=index)
            for index in range(args.practice_count)
        )
        result = controller.run_brs(
            run_id=run_id,
            contract_sha256=contract_sha256,
            evaluator_sha256=evaluator_sha256,
            environment_sha256=environment_sha256,
            solver_id=args.solver,
            practices=decisions,
        )
    return {
        "run_id": result.run_id,
        "mode": args.mode,
        "status": result.status,
        "target_attempts": len(result.target_attempts),
        "practice_episodes": len(result.practice_episodes),
        "memory_snapshot_sha256": result.memory_snapshot.digest(),
        "recovery_eligibility": "reconcile_required" if result.status == "unknown" else "terminal",
        "ledger": str(config.home / "rsi.sqlite3"),
    }


def _memory_payload(config: Config, query: str | None, scope: str | None, limit: int) -> list[dict[str, object]]:
    memory = MemoryStore(config.database)
    memory.initialize()
    if query:
        scopes = (scope,) if scope else ("global",)
        entries = memory.recall(query, scopes=scopes, limit=limit)
    else:
        entries = memory.list(scope=scope, limit=limit)
    return [
        {
            "id": entry.id,
            "scope": entry.scope,
            "kind": entry.kind,
            "content": entry.content,
            "tags": list(entry.tags),
            "source": entry.source,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "access_count": entry.access_count,
        }
        for entry in entries
    ]


def _answer(config: Config, args: argparse.Namespace) -> dict[str, object]:
    answer = args.answer
    if answer == "-":
        answer = sys.stdin.read()
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer requires non-empty text or '-' for stdin")
    api_key = args.api_key or os.environ.get("LUNAR_EVOLUTION_API_KEY")
    if api_key:
        answer = answer.replace(api_key, "[REDACTED]")
    if len(answer.encode("utf-8")) > 20_000:
        raise ValueError("answer exceeds 20 KiB")
    store = Store(config.database)
    run = store.get_run(args.run_id)
    if run is None:
        raise ValueError(f"unknown run: {args.run_id}")
    evolution_request = _latest_evolution_request(store, run.id)
    _validate_automatic_detach(args, evolution_request)
    if evolution_request is not None:
        _validate_solve_wall_timeout_option(args, evolution_request)
    elif getattr(args, "solve_wall_timeout", None) is not None:
        _validate_solve_wall_timeout_option(args, None, allow_unresolved_handoff=False)
    if evolution_request is None and getattr(args, "candidate_generation_max_steps", None) is not None:
        raise ValueError(
            "--candidate-generation-max-steps requires an automatic multi-file evolution handoff"
        )
    if evolution_request is not None:
        _validate_candidate_generation_option(args, evolution_request)
    if _has_preparation_timeout(args):
        _validate_preparation_timeout_override(args, evolution_request)
    _validate_conversational_bundle_request(args, evolution_request)
    _validate_conversational_bundle_link(args, store, run)
    if evolution_request is not None:
        compiled = bool(evolution_request.get("compile_evaluator", False))
        if getattr(args, "compile_evaluator", False) and not compiled:
            raise EvolutionError("solve evolution did not configure a compiled evaluator")
        if getattr(args, "evaluator_command", None) and compiled:
            raise EvolutionError("compiled evaluator and evaluator command are mutually exclusive")
    current_plan = store.get_current_plan(run.id)
    if current_plan is not None and current_plan.algorithm_problem is not None:
        current_contract = AlgorithmProblemContract.from_dict(current_plan.algorithm_problem)
        if current_contract.evolution.strategy == "loop":
            raise ValueError(LOOP_STRATEGY_RETIRED_MESSAGE)
    pending = store.pending_input(run.id)
    if pending is None:
        raise ValueError(f"run is not awaiting input: {args.run_id}")
    conversation = any(
        event["type"] == "conversation_started" for event in store.list_events(run.id)
    )
    manifest = _conversation_manifest(run) if conversation else None
    controller = _controller(args, config)
    if conversation:
        current_fingerprint = _compiler_fingerprint(controller.runtime)
        if manifest is not None and manifest.get("runtime_fingerprint") not in {
            None,
            current_fingerprint,
        }:
            raise ValueError("answer compiler runtime does not match the existing conversational run")
    automatic_answer = conversation and _lifecycle_enabled(evolution_request)
    ownership = own_automatic_solve(run.id, Path(run.workspace)) if automatic_answer else nullcontext()
    with ownership as owner:
        if automatic_answer:
            from .automatic_solve_worker import prepare_automatic_continuation

            prepare_automatic_continuation(controller, run)
        if store.pending_input(run.id) != pending:
            raise ValueError("input request changed concurrently; inspect status")
        _bind_conversational_bundle_inputs(args, store, run)
        artifacts = ArtifactStore(run.workspace, store, run.id)
        answer_path = artifacts.write_text(
            f"tasks/{pending['task_id']}/input-answer.json",
            json.dumps({"answer": answer.strip()}, ensure_ascii=False, indent=2) + "\n",
            pending["task_id"],
            kind="input",
        )
        relative_answer = str(answer_path.relative_to(run.workspace))
        task_id = store.answer_input(run.id, relative_answer)
        if task_id is None:
            raise ValueError("input request was answered concurrently; inspect status")
        evolution_request = _latest_evolution_request(store, run.id)
        automatic_continuation = conversation and _lifecycle_enabled(evolution_request)
        detached = False
        if automatic_continuation:
            effective_args = _evolution_args(args, evolution_request)
            resumed = controller.store.get_run(run.id) or run
            if getattr(args, "detach", False):
                from .automatic_solve_worker import launch_automatic_solve

                if resumed.status.value not in {"succeeded", "failed", "cancelled"} and store.pending_input(run.id) is None:
                    launch_automatic_solve(config, effective_args, controller, resumed, owner)
                    detached = True
                resumed = controller.store.get_run(run.id) or resumed
            else:
                resumed = _resume_automatic_solve(
                    config, effective_args, controller, resumed, manifest, owner_held=True,
                )
        elif conversation and (run.current_plan_id is None or evolution_request is not None):
            resumed = controller.resume_conversational(
                run.id,
                RuntimeContractCompiler(controller.runtime),
                compiler_fingerprint=_compiler_fingerprint(controller.runtime),
                plan_factory=_conversation_plan_factory(args, manifest),
                execute_plan=evolution_request is None,
            )
        else:
            resumed = controller.resume(run.id)
        evolution_request = _latest_evolution_request(controller.store, resumed.id)
        if not automatic_continuation and resumed.current_plan_id is not None and evolution_request is not None:
            evolution_args = _evolution_args(args, evolution_request)
            # An OpenEvolve executable is intentionally not persisted in the request event. The
            # same is true for an objective harness. The caller must continue either explicit path
            # with ``solve --resume`` and provide the command again; runtime-backed native handoffs
            # can resume automatically.
            harness_deferred = bool(evolution_request.get("evaluator_command_configured")) and not bool(
                getattr(args, "evaluator_command", None)
            )
            if (
                not evolution_request.get("evaluator_command_configured")
                and getattr(args, "evaluator_command", None)
            ):
                raise EvolutionError("solve evolution did not configure an evaluator command")
            if not (
                harness_deferred
                or (
                    getattr(evolution_args, "strategy", None) == "openevolve"
                    and not getattr(args, "openevolve_command", None)
                )
            ):
                _bind_solve_execution_control(evolution_args, controller, resumed)
                _solve_evolution(config, evolution_args, controller, resumed)
                resumed = controller.store.get_run(resumed.id) or resumed
        solved_payload = _solve_payload(controller, resumed)
        payload = {
            "run_id": resumed.id,
            "task_id": task_id,
            "status": solved_payload["status"],
            "run_status": resumed.status.value,
            "workspace": str(resumed.workspace),
            "answer_path": relative_answer,
            "workers": controller.max_workers,
            "input_request": solved_payload["input_request"],
            "algorithm_outputs": solved_payload.get("algorithm_outputs", []),
            "evolution": solved_payload.get("evolution"),
            **({"detached": True, "launch_status": "accepted"} if detached else {}),
            **({"solve_execution": solved_payload["solve_execution"]} if "solve_execution" in solved_payload else {}),
        }
        if solved_payload.get("error") == LOOP_STRATEGY_RETIRED:
            payload.update(_loop_retirement_payload())
        return payload


def _export_shinka(args: argparse.Namespace) -> dict[str, object]:
    from .shinka_handoff import export_shinka_result

    try:
        content = _read_bounded_regular_file(
            args.contract.expanduser(), MAX_CONTRACT_BYTES, error="producer_export_contract_invalid",
        )
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(content))
    except (EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise ValueError("producer_export_contract_invalid") from None
    envelope = export_shinka_result(
        args.results_root, args.output, contract_sha256=contract.digest(),
        producer_fingerprint=args.producer_fingerprint, producer_run_id=args.producer_run_id,
        program_ids=args.program_ids, top_k=args.top_k,
    )
    return {
        "status": "exported", "export_root": str(args.output.expanduser().absolute()),
        "producer_id": envelope.producer_id, "producer_run_id": envelope.producer_run_id,
        "material_count": len(envelope.materials), "contract_sha256": envelope.contract_sha256,
        "envelope_sha256": envelope.envelope_sha256,
    }


def _benchmark_task_validate(args: argparse.Namespace) -> dict[str, object]:
    from .benchmark_task import (
        BenchmarkTaskError,
        admit_benchmark_task_envelope,
        parse_benchmark_task_envelope,
    )

    try:
        content = _read_bounded_regular_file(
            args.contract.expanduser(), MAX_CONTRACT_BYTES, error="benchmark_task_envelope_invalid",
        )
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(content))
        envelope = parse_benchmark_task_envelope(args.task)
        admitted = admit_benchmark_task_envelope(
            envelope,
            contract_sha256=contract.digest(),
            input_root=args.input_root,
            model_profile_sha256=args.model_profile_sha256,
            evaluator_fingerprint=args.evaluator_fingerprint,
        )
    except BenchmarkTaskError:
        raise
    except (EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise ValueError("benchmark_task_envelope_invalid") from None
    return {
        "status": "validated",
        "task_key": envelope.task.key,
        "task_revision_id": envelope.task.revision_id,
        "envelope_sha256": admitted.envelope_sha256,
        "comparison_sha256": admitted.comparison_sha256,
        "contract_sha256": admitted.contract_sha256,
        "input_count": len(admitted.inputs),
    }


def _benchmark_comparison_validate_result(args: argparse.Namespace) -> dict[str, object]:
    from .benchmark_comparison import (
        BenchmarkComparisonError,
        admit_benchmark_comparison_plan,
        parse_benchmark_comparison_plan,
    )
    from .benchmark_result import (
        BenchmarkResultError,
        admit_benchmark_comparison_result,
        parse_benchmark_comparison_result,
    )

    try:
        content = _read_bounded_regular_file(
            args.contract.expanduser(), MAX_CONTRACT_BYTES, error="benchmark_comparison_invalid",
        )
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(content))
        plan = parse_benchmark_comparison_plan(args.plan)
        admitted_plan = admit_benchmark_comparison_plan(
            plan,
            contract_sha256=contract.digest(),
            input_root=args.input_root,
            model_profile_sha256=args.model_profile_sha256,
            evaluator_fingerprint=args.evaluator_fingerprint,
        )
        result = parse_benchmark_comparison_result(args.result)
        admitted_result = admit_benchmark_comparison_result(
            result, plan, evidence_root=args.evidence_root,
            expected_plan_sha256=args.plan_sha256,
        )
    except (BenchmarkComparisonError, BenchmarkResultError):
        raise
    except (EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise ValueError("benchmark_comparison_invalid") from None
    return {
        "status": "validated",
        "comparison_id": admitted_plan.comparison_id,
        "result_id": admitted_result.result_id,
        "arm_count": len(admitted_result.arms),
        "arm_ids": [arm.arm_id for arm in admitted_result.arms],
        "per_arm_attempts": admitted_plan.per_arm_attempts,
        "evidence_bound": args.evidence_root is not None,
        "plan_bound": admitted_result.plan_sha256 is not None,
        "plan_sha256": plan.digest(),
    }


def _candidate_bundle_validate(args: argparse.Namespace) -> dict[str, object]:
    from ._benchmark_files import absolute_path, read_regular_file
    from .candidate_bundle import (
        parse_candidate_source_bundle,
        verify_candidate_source_bundle,
    )

    try:
        content = read_regular_file(absolute_path(args.contract), MAX_CONTRACT_BYTES)
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(content))
        contract_sha256 = contract.digest()
    except (EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise ValueError("candidate_bundle_contract_invalid") from None
    verified = verify_candidate_source_bundle(
        parse_candidate_source_bundle(args.manifest),
        source_root=args.source_root,
        contract_sha256=contract_sha256,
        expected_bundle_sha256=args.bundle_sha256,
    )
    return {
        "status": "validated",
        "bundle_sha256": verified.bundle_sha256,
        "contract_sha256": verified.bundle.contract_sha256,
        "file_count": verified.file_count,
        "total_bytes": verified.total_bytes,
    }


def _candidate_bundle_materialize(args: argparse.Namespace) -> dict[str, object]:
    from ._benchmark_files import absolute_path, read_regular_file
    from .candidate_bundle import MAX_CANDIDATE_BUNDLE_BYTES, parse_candidate_source_bundle
    from .candidate_workspace import (
        build_candidate_workspace_plan,
        materialize_candidate_source_bundle,
    )

    try:
        content = read_regular_file(absolute_path(args.contract), MAX_CONTRACT_BYTES)
        contract = AlgorithmProblemContract.from_dict(_strict_json_loads(content))
        bundle = parse_candidate_source_bundle(args.manifest)
        environment: dict[str, str] = {}
        if args.environment_json is not None:
            raw = read_regular_file(absolute_path(args.environment_json), MAX_CANDIDATE_BUNDLE_BYTES)
            value = _strict_json_loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            environment = value
        plan = build_candidate_workspace_plan(
            bundle, command=args.planned_command, timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.max_output_bytes, environment=environment,
            contract_sha256=contract.digest(), expected_bundle_sha256=args.bundle_sha256,
        )
        result = materialize_candidate_source_bundle(
            bundle, source_root=args.source_root, workspace_root=args.workspace_root,
            contract_sha256=contract.digest(), expected_bundle_sha256=args.bundle_sha256,
        )
    except Exception as exc:
        from .candidate_workspace import CandidateWorkspaceError
        if isinstance(exc, CandidateWorkspaceError):
            raise
        raise ValueError("candidate_workspace_invalid") from None
    return {**result.to_dict(), "plan_sha256": plan.digest(), "workspace_path": str(result.workspace_path)}


def _candidate_bundle_admit_execution(args: argparse.Namespace) -> dict[str, object]:
    from . import _benchmark_files as files
    from .candidate_execution import (
        MAX_EXECUTION_ADMISSION_BYTES,
        MAX_EXECUTION_INPUT_BYTES,
        SOURCE_ONLY_EVALUATOR_KIND,
        CandidateEvaluatorPin,
        CandidateExecutionBudget,
        CandidateExecutionError,
        CandidateExecutionInput,
        admit_candidate_execution,
    )
    from .candidate_workspace_plan import (
        CandidateWorkspaceError,
        parse_candidate_workspace_plan,
    )

    def check_digest_pin(value: object, actual: str, code: str) -> None:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            or value != actual
        ):
            raise CandidateExecutionError(code)

    def check_digest(value: object, code: str, *, reject_zero: bool) -> None:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            or (reject_zero and value == "0" * 64)
        ):
            raise CandidateExecutionError(code)

    try:
        try:
            plan = parse_candidate_workspace_plan(args.plan)
        except CandidateWorkspaceError:
            raise CandidateExecutionError("plan_mismatch") from None

        # Validate all identity fields that can be checked from the plan and CLI arguments before
        # opening the separate input descriptor file. The admission API repeats these checks.
        if args.expected_plan_sha256 is not None:
            check_digest_pin(args.expected_plan_sha256, plan.digest(), "plan_mismatch")
        if args.expected_bundle_sha256 is not None:
            check_digest_pin(args.expected_bundle_sha256, plan.bundle_sha256, "bundle_mismatch")
        if args.expected_contract_sha256 is not None:
            check_digest_pin(args.expected_contract_sha256, plan.contract_sha256, "contract_mismatch")
        if args.expected_admission_sha256 is not None:
            check_digest(args.expected_admission_sha256, "identity_mismatch", reject_zero=False)
        check_digest(args.dependency_sha256, "dependency_mismatch", reject_zero=True)
        check_digest(args.environment_sha256, "environment_mismatch", reject_zero=True)
        evaluator = CandidateEvaluatorPin(args.evaluator_kind, args.evaluator_sha256)
        budget = CandidateExecutionBudget(
            plan.timeout_seconds if args.timeout_seconds is None else args.timeout_seconds,
            plan.max_output_bytes if args.max_output_bytes is None else args.max_output_bytes,
            MAX_EXECUTION_INPUT_BYTES if args.max_input_bytes is None else args.max_input_bytes,
            1 if args.max_processes is None else args.max_processes,
        )
        if plan.timeout_seconds > budget.timeout_seconds or plan.max_output_bytes > budget.max_output_bytes:
            raise CandidateExecutionError("budget_invalid")
        if args.output_contract_sha256 is None:
            if evaluator.kind != SOURCE_ONLY_EVALUATOR_KIND:
                raise CandidateExecutionError("output_contract_mismatch")
        else:
            check_digest(args.output_contract_sha256, "output_contract_mismatch", reject_zero=False)

        try:
            input_content = files.read_regular_file(
                files.absolute_path(args.inputs), MAX_EXECUTION_ADMISSION_BYTES,
            )
        except files.BenchmarkFileError as exc:
            raise CandidateExecutionError(
                "input_invalid" if exc.reason != "too_large" else "too_large",
            ) from None
        value = _strict_json_loads(input_content)
        if not isinstance(value, list):
            raise CandidateExecutionError("input_invalid")
        inputs = tuple(CandidateExecutionInput.from_dict(item) for item in value)
        admitted = admit_candidate_execution(
            plan,
            input_root=args.input_root,
            inputs=inputs,
            dependency_sha256=args.dependency_sha256,
            environment_sha256=args.environment_sha256,
            evaluator=evaluator,
            output_contract_sha256=args.output_contract_sha256,
            budget=budget,
            expected_plan_sha256=args.expected_plan_sha256,
            expected_bundle_sha256=args.expected_bundle_sha256,
            expected_contract_sha256=args.expected_contract_sha256,
            expected_admission_sha256=args.expected_admission_sha256,
        )
    except CandidateExecutionError:
        raise
    except (OSError, TypeError, ValueError, RecursionError):
        raise CandidateExecutionError("invalid") from None

    admission = admitted.admission
    return {
        "status": "admitted",
        "admission_sha256": admitted.admission_sha256,
        "plan_sha256": admission.workspace_plan_sha256,
        "bundle_sha256": admission.bundle_sha256,
        "contract_sha256": admission.contract_sha256,
        "evaluator_kind": admission.evaluator.kind,
        "input_count": admitted.input_count,
        "total_input_bytes": admitted.total_input_bytes,
        "inputs_verified": admitted.inputs_verified,
    }


def _candidate_bundle_stage_inputs(args: argparse.Namespace) -> dict[str, object]:
    from . import _benchmark_files as files
    from .candidate_execution import MAX_EXECUTION_ADMISSION_BYTES, CandidateExecutionError
    from .candidate_input_staging import stage_candidate_execution_inputs
    from .candidate_workspace_plan import CandidateWorkspaceError, parse_candidate_workspace_plan

    try:
        plan = parse_candidate_workspace_plan(args.plan)
    except CandidateWorkspaceError:
        raise CandidateExecutionError("plan_mismatch") from None
    try:
        content = files.read_regular_file(
            files.absolute_path(args.admission), MAX_EXECUTION_ADMISSION_BYTES,
        )
    except files.BenchmarkFileError as exc:
        raise CandidateExecutionError("too_large" if exc.reason == "too_large" else "invalid") from None
    except OSError:
        raise CandidateExecutionError("invalid") from None
    result = stage_candidate_execution_inputs(
        content, plan=plan, input_root=args.input_root, staging_root=args.staging_root,
        expected_plan_sha256=args.expected_plan_sha256,
        expected_bundle_sha256=args.expected_bundle_sha256,
        expected_contract_sha256=args.expected_contract_sha256,
        expected_admission_sha256=args.expected_admission_sha256,
    )
    return {**result.to_dict(), "input_path": str(result.input_path)}


def _candidate_bundle_run(args: argparse.Namespace) -> dict[str, object]:
    from . import _benchmark_files as files
    from .candidate_execution import MAX_EXECUTION_ADMISSION_BYTES
    from .candidate_execution_runner import CandidateExecutionRunnerError, run_candidate_execution
    from .candidate_workspace_plan import CandidateWorkspaceError, parse_candidate_workspace_plan

    try:
        plan = parse_candidate_workspace_plan(args.plan)
        content = files.read_regular_file(files.absolute_path(args.admission), MAX_EXECUTION_ADMISSION_BYTES)
    except (CandidateWorkspaceError, files.BenchmarkFileError, OSError):
        raise CandidateExecutionRunnerError("invalid") from None
    return run_candidate_execution(
        content, plan=plan, workspace_path=args.workspace, input_path=args.input_root,
        expected_admission_sha256=args.expected_admission_sha256,
        expected_plan_sha256=args.expected_plan_sha256,
        expected_bundle_sha256=args.expected_bundle_sha256,
        expected_contract_sha256=args.expected_contract_sha256,
    ).to_dict()


def _candidate_bundle_execution_record(args: argparse.Namespace) -> dict[str, object]:
    from . import _benchmark_files as files
    from .candidate_execution import MAX_EXECUTION_ADMISSION_BYTES
    from .candidate_execution_evidence import (
        CandidateExecutionEvidenceError,
        inspect_candidate_execution_record,
        run_candidate_execution_recorded,
    )
    from .candidate_workspace_plan import CandidateWorkspaceError, parse_candidate_workspace_plan

    try:
        plan = parse_candidate_workspace_plan(args.plan)
        admission = files.read_regular_file(files.absolute_path(args.admission), MAX_EXECUTION_ADMISSION_BYTES)
    except (CandidateWorkspaceError, files.BenchmarkFileError, OSError):
        raise CandidateExecutionEvidenceError("invalid") from None
    pins = {
        "expected_admission_sha256": args.expected_admission_sha256,
        "expected_plan_sha256": args.expected_plan_sha256,
        "expected_bundle_sha256": args.expected_bundle_sha256,
        "expected_contract_sha256": args.expected_contract_sha256,
    }
    if args.candidate_bundle_command == "run-recorded":
        result = run_candidate_execution_recorded(
            admission, plan=plan, workspace_path=args.workspace, input_path=args.input_root,
            attempt_path=args.attempt, **pins,
        )
    else:
        result = inspect_candidate_execution_record(
            args.attempt, plan=plan, admission=admission,
            expected_completion_sha256=args.expected_completion_sha256, **pins,
        )
    return result.to_dict()


def _candidate_bundle_evaluate(args: argparse.Namespace) -> dict[str, object]:
    from . import _benchmark_files as files
    from .candidate_evaluation import evaluate_candidate_execution
    from .candidate_evaluation_spec import (
        MAX_CANDIDATE_EVALUATION_SPEC_BYTES,
        CandidateEvaluationError,
        parse_candidate_evaluation_spec,
        strict_json,
    )
    from .candidate_execution import MAX_EXECUTION_ADMISSION_BYTES
    from .candidate_workspace_plan import CandidateWorkspaceError, parse_candidate_workspace_plan

    try:
        plan = parse_candidate_workspace_plan(args.plan)
        admission = files.read_regular_file(files.absolute_path(args.admission), MAX_EXECUTION_ADMISSION_BYTES)
        contract_content = files.read_regular_file(files.absolute_path(args.contract), MAX_CONTRACT_BYTES)
        contract = AlgorithmProblemContract.from_dict(strict_json(contract_content, MAX_CONTRACT_BYTES))
        evaluator_content = files.read_regular_file(
            files.absolute_path(args.evaluator), MAX_CANDIDATE_EVALUATION_SPEC_BYTES,
        )
        evaluator = parse_candidate_evaluation_spec(evaluator_content)
    except CandidateEvaluationError:
        raise
    except (CandidateWorkspaceError, files.BenchmarkFileError, EvolutionError, OSError, TypeError, ValueError, RecursionError):
        raise CandidateEvaluationError("invalid") from None
    result = evaluate_candidate_execution(
        admission, plan=plan, contract=contract, evaluator=evaluator, harness_path=args.harness,
        workspace_path=args.workspace, input_path=args.input_root, attempt_path=args.attempt,
        evaluation_root=args.evaluation_root,
        expected_admission_sha256=args.expected_admission_sha256,
        expected_plan_sha256=args.expected_plan_sha256,
        expected_bundle_sha256=args.expected_bundle_sha256,
        expected_contract_sha256=args.expected_contract_sha256,
        expected_completion_sha256=args.expected_completion_sha256,
    )
    return {**result.to_dict(), "evaluation_path": str(result.evaluation_path)}


def _candidate_bundle_inspect_evaluation(args: argparse.Namespace) -> dict[str, object]:
    from .candidate_evaluation import inspect_candidate_evaluation

    result = inspect_candidate_evaluation(
        args.evaluation, expected_evaluation_sha256=args.expected_evaluation_sha256,
    )
    return {**result.to_dict(), "evaluation_path": str(result.evaluation_path)}


def main(argv: list[str] | None = None, *, _automatic_owner=None,
         _acceptance_preparation_hook=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if _acceptance_preparation_hook is not None:
            if not callable(_acceptance_preparation_hook) or not (
                args.command == "solve" and args.evolve and args.multi_file
                and not args.resume and not args.detach
                and args.solve_wall_timeout is not None
            ):
                raise ValueError("invalid acceptance preparation hook")
            args._acceptance_preparation_hook = _acceptance_preparation_hook
        if _automatic_owner is not None:
            if not (
                args.command == "solve" and args.resume
                and args.run_id == _automatic_owner.parent_id
                and not args.detach
            ):
                raise ValueError("invalid automatic solve worker continuation")
            args._automatic_owner = _automatic_owner
            args._solve_owner_held = True
        _reject_retired_cli_strategy(args)
        if args.command in {"solve", "answer", "resume"}:
            _validate_preparation_cli_timeouts(args)
            _validate_solve_wall_timeout_option(args)
            _validate_candidate_generation_option(args)
            _prepare_conversational_bundle(args)
            if (args.command == "solve" and not args.resume
                    and _has_preparation_timeout(args) and not getattr(args, "multi_file", False)):
                raise ValueError("evaluator preparation timeouts require --evolve --multi-file")
        # Reject malformed automatic evolution budgets before creating the local state DB.
        if (args.command == "solve" and getattr(args, "evolve", False)
                and not getattr(args, "resume", False)):
            _validate_evolution_cli_bounds(args)
        if args.command == "effect-trial":
            payload = _effect_host_scope(args, _effect_trial)
            _emit(payload, args.json)
            return 0
        if args.command == "effect-preflight":
            payload = _effect_preflight(args)
            _emit(payload, args.json)
            return 0
        if args.command == "effect-deep-trial":
            payload = _effect_host_scope(args, _effect_deep_trial)
            _emit(payload, args.json)
            return 0
        if args.command == "effect-kit":
            _emit(_effect_kit(args), args.json)
            return 0
        if args.command == "effect-subject":
            _emit(_effect_subject(args), args.json)
            return 0
        if args.command == "effect-harness":
            _emit(_effect_harness(args), args.json)
            return 0
        if args.command == "effect-baseline":
            _emit(_effect_baseline(args), args.json)
            return 0
        if args.command == "diagnose-materialization":
            from .materialization_diagnostics import (
                diagnose_materialization,
                format_materialization_diagnostic,
            )

            # Avoid _config/Config.ensure/Store.initialize, including for a missing home.
            diagnostic_home = Path(args.home or os.environ.get("LUNAR_EVOLUTION_HOME", ".lunar-evolution")).expanduser()
            payload = diagnose_materialization(
                diagnostic_home / "state.db", args.parent_run_id, args.evolution_run_id,
            )
            if args.json:
                _emit(payload, True)
            else:
                print(format_materialization_diagnostic(payload))
            return 2 if payload["status"] in {"busy", "unavailable"} else 0
        if args.command == "export-materialization-evidence":
            from .materialization_evidence_bundle import export_materialization_evidence

            export_home = Path(args.home or os.environ.get("LUNAR_EVOLUTION_HOME", ".lunar-evolution")).expanduser()
            payload = export_materialization_evidence(
                export_home / "state.db", args.parent_run_id, args.evolution_run_id, Path(args.output),
            )
            _emit(payload, args.json)
            return 0
        if args.command == "attest-materialization-execution":
            from .materialization_attestation import attest_from_database

            attest_home = Path(args.home or os.environ.get("LUNAR_EVOLUTION_HOME", ".lunar-evolution")).expanduser()
            payload = attest_from_database(
                attest_home / "state.db", args.parent_run_id, args.evolution_run_id, args.receipt,
            )
            _emit(payload, args.json)
            return 0
        if args.command == "export-shinka-result":
            _emit(_export_shinka(args), args.json)
            return 0
        if args.command == "benchmark-task":
            if args.benchmark_task_command != "validate":
                raise ValueError("benchmark_task_envelope_invalid")
            _emit(_benchmark_task_validate(args), args.json)
            return 0
        if args.command == "benchmark-comparison":
            if args.benchmark_comparison_command != "validate-result":
                raise ValueError("benchmark_comparison_invalid")
            _emit(_benchmark_comparison_validate_result(args), args.json)
            return 0
        if args.command == "candidate-bundle":
            if args.candidate_bundle_command == "inspect-delivery":
                from .bundle_delivery import inspect_bundle_delivery

                delivery = inspect_bundle_delivery(
                    args.delivery, expected_delivery_sha256=args.expected_delivery_sha256,
                )
                _emit({**delivery.to_dict(), "delivery_path": str(delivery.delivery_path)}, args.json)
                return 0
            if args.candidate_bundle_command == "evaluate":
                result = _candidate_bundle_evaluate(args)
                _emit(result, args.json)
                return 0 if result["report"]["validity"] == 1 else 1
            if args.candidate_bundle_command == "inspect-evaluation":
                _emit(_candidate_bundle_inspect_evaluation(args), args.json)
                return 0
            if args.candidate_bundle_command in {"run-recorded", "inspect-execution"}:
                _emit(_candidate_bundle_execution_record(args), args.json)
                return 0
            if args.candidate_bundle_command == "validate":
                _emit(_candidate_bundle_validate(args), args.json)
                return 0
            if args.candidate_bundle_command == "materialize":
                _emit(_candidate_bundle_materialize(args), args.json)
                return 0
            if args.candidate_bundle_command == "admit-execution":
                _emit(_candidate_bundle_admit_execution(args), args.json)
                return 0
            if args.candidate_bundle_command == "stage-inputs":
                _emit(_candidate_bundle_stage_inputs(args), args.json)
                return 0
            if args.candidate_bundle_command == "run":
                result = _candidate_bundle_run(args)
                _emit(result, args.json)
                return 0 if result["status"] == "succeeded" else 1
            raise ValueError("candidate_bundle_invalid")
        if args.command == "evolve-bundle":
            payload = _evolve_bundle(args)
            _emit(payload, args.json)
            return 0 if payload["status"] in {"completed", "stagnated"} else 1
        if args.command == "rsi" and args.rsi_command == "usage":
            from .rsi_usage import inspect_usage_ledger

            # Read-only diagnostics must precede all home/SQLite initialization.
            _emit(inspect_usage_ledger(
                args.ledger, run_id=args.run_id, episode_id=args.episode_id,
                adapter_stage=args.adapter_stage,
            ), args.json)
            return 0
        config = _config(args)
        if args.command == "init":
            _emit({"home": str(config.home), "status": "initialized"}, args.json)
            return 0
        if args.command == "rsi":
            ledger = RSILedger(config.home / "rsi.sqlite3")
            if args.rsi_command == "run":
                payload = _rsi_run_payload(config, args)
                _emit(payload, args.json)
                return 0 if payload["status"] in {"completed", "reconciled"} else 1
            if args.rsi_command == "inspect":
                if args.callback_id is not None:
                    checkpoint = DurableCallbackJournal(ledger).inspect(args.logical_id, args.callback_id)
                    if checkpoint is None:
                        _emit_error("rsi_callback_missing", args.json)
                        return 2
                    _emit({"checkpoint_sha256": checkpoint[0], "state": checkpoint[1]}, args.json)
                    return 0
                record = ledger.get(args.logical_id)
                if record is None:
                    _emit_error(f"unknown RSI record: {args.logical_id}", args.json)
                    return 2
                payload = {
                    "head": _rsi_record_payload(record),
                    "history": [_rsi_record_payload(item) for item in ledger.history(args.logical_id)],
                }
                _emit(payload, args.json)
                return 0
            if args.rsi_command == "reconcile":
                record = ledger.reconcile_episode(
                    args.episode_id,
                    worker_state=args.worker_state,
                    launched=args.launched,
                    expected_record_sha256=args.expected_record_sha256,
                    evidence={
                        "reconciliation": {
                            "source": "explicit_cli",
                            "worker_state": args.worker_state,
                            "launched": args.launched,
                        },
                    },
                )
                _emit(_rsi_record_payload(record), args.json)
                return 0
            raise ValueError("rsi_command_invalid")
        if args.command == "solve":
            payload = _solve(config, args)
            _emit(payload, args.json)
            if payload.get("detached") is True and payload.get("run_status") in {"pending", "running", "awaiting_input"}:
                return 0
            success = payload["status"] in {"succeeded", "awaiting_input", "pending", "running"}
            evolution = payload.get("evolution")
            if isinstance(evolution, dict):
                success = success and evolution.get("status") in {
                    "succeeded",
                    "awaiting_input",
                    "pending",
                    "running",
                    "stagnated",
                }
            return 0 if success else 1
        if args.command == "run":
            plan_tasks = None
            if args.plan is not None:
                goal, plan_tasks = _load_plan(args.plan, args.goal)
            elif args.goal == "-":
                goal = sys.stdin.read()
            elif args.goal:
                goal = args.goal
            else:
                raise ValueError("run requires a goal or --plan PATH")
            if args.detach:
                _emit(_detach(config, args, goal, plan_tasks), args.json)
                return 0
            controller = _controller(args, config)
            run = controller.create(goal, plan_tasks)
            staged_inputs = _stage_input_files(run, controller.store, args.input_files)
            run = controller.resume(run.id)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                    "input_request": controller.store.pending_input(run.id),
                    "input_data": list(staged_inputs),
                    "workers": controller.max_workers,
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "delegate":
            payload = _delegate(config, args)
            _emit(payload, args.json)
            return 0 if payload["run_status"] in {"succeeded", "pending", "running"} else 1
        if args.command == "resume":
            evolution_request = _latest_evolution_request(Store(config.database), args.run_id)
            _validate_automatic_detach(args, evolution_request)
            _validate_solve_wall_timeout_option(
                args, evolution_request, allow_unresolved_handoff=False,
            )
            if evolution_request is not None:
                _validate_candidate_generation_option(args, evolution_request)
            if _has_preparation_timeout(args):
                _validate_preparation_timeout_override(args, evolution_request)
            if getattr(args, "bundle_profile", None) is not None or getattr(args, "multi_file", False) or getattr(args, "candidate_generation_max_steps", None) is not None or (
                evolution_request is not None and (
                    "bundle_profile_sha256" in evolution_request or "bundle_mode" in evolution_request
                )
            ):
                values = vars(build_parser().parse_args([
                    "solve", "--resume", "--run-id", args.run_id,
                ]))
                values.update(vars(args))
                values.update(command="solve", resume=True)
                payload = _solve(config, argparse.Namespace(**values))
                _emit(payload, args.json)
                if payload.get("detached") is True and payload.get("run_status") in {"pending", "running", "awaiting_input"}:
                    return 0
                success = payload["status"] in {"succeeded", "awaiting_input", "pending", "running"}
                evolution = payload.get("evolution")
                if isinstance(evolution, dict):
                    success = success and evolution.get("status") in {
                        "succeeded", "awaiting_input", "pending", "running", "stagnated",
                    }
                return 0 if success else 1
            controller = _controller(args, config)
            run = controller.resume(args.run_id)
            _emit(
                {
                    "run_id": run.id,
                    "status": run.status.value,
                    "workspace": str(run.workspace),
                    "input_request": controller.store.pending_input(run.id),
                    "workers": controller.max_workers,
                },
                args.json,
            )
            return 0 if run.status.value == "succeeded" else 1
        if args.command == "evolve":
            payload = _evolve(config, args)
            _emit(payload, args.json)
            return 0 if payload.get("status") in {"completed", "stagnated", "pending"} else 1
        if args.command == "benchmark":
            payload = _benchmark(config, args)
            _emit(payload, args.json)
            return 0 if payload.get("status") == "completed" else 1
        if args.command == "answer":
            payload = _answer(config, args)
            _emit(payload, args.json)
            if payload.get("detached") is True and payload.get("run_status") in {"pending", "running", "awaiting_input"}:
                return 0
            success = payload["status"] == "succeeded"
            evolution = payload.get("evolution")
            if isinstance(evolution, dict):
                success = success and evolution.get("status") in {
                    "succeeded",
                    "awaiting_input",
                    "pending",
                    "running",
                    "stagnated",
                }
            return 0 if success else 1
        if args.command == "status":
            if args.json:
                payload = _status_payload(config, args.run_id)
                if payload is None:
                    _emit_error(f"unknown run: {args.run_id}", True)
                    return 2
                _emit(payload, True)
                return 0
            return _print_status(config, args.run_id)
        if args.command == "events":
            if args.json:
                store = Store(config.database)
                if store.get_run(args.run_id) is None:
                    _emit_error(f"unknown run: {args.run_id}", True)
                    return 2
                _emit(store.list_events(args.run_id), True)
                return 0
            return _print_events(config, args.run_id)
        if args.command == "cancel":
            changed = _controller(argparse.Namespace(runtime="mock", runtime_command=None), config).cancel(
                args.run_id
            )
            if not changed:
                _emit_error(f"run not found or already terminal: {args.run_id}", args.json)
                return 2
            _emit({"run_id": args.run_id, "status": "cancelled"}, args.json)
            return 0
        if args.command == "recover":
            controller = LocalController(
                config,
                build_runtime("mock", None, None, None, None),
            )
            proposal = controller.recover(args.run_id)
            run = controller.store.get_run(args.run_id)
            assert run is not None
            _emit(
                {"run_id": run.id, "status": run.status.value, "proposal": proposal.to_dict()},
                args.json,
            )
            return 0
        if args.command == "memory":
            payload = _memory_payload(config, args.query, args.scope, args.limit)
            if args.json:
                _emit(payload, True)
            else:
                for entry in payload:
                    print(f"{entry['id']} [{entry['scope']}/{entry['kind']}] {entry['content']}")
            return 0
        if args.command == "decide":
            goal = sys.stdin.read() if args.goal == "-" else args.goal
            if not isinstance(goal, str) or not goal.strip():
                raise ValueError("decide requires a goal or '-' for stdin")
            _emit(MasterPolicy().decide(goal).to_dict(), args.json)
            return 0
        if args.command == "plan":
            candidate = Path(args.plan_file or args.target)
            if args.plan_file or candidate.is_file():
                document = _load_plan_document(candidate)
                controller = _controller(args, config)
                run = controller.start_plan(document)
                _emit({"run_id": run.id, "status": run.status.value, "plan_id": document.plan_id, "plan_version": document.version, "workspace": str(run.workspace), "workers": controller.max_workers}, args.json)
                return 0 if run.status.value == "succeeded" else 1
            payload = _status_payload(config, args.target)
            if payload is None:
                _emit_error(f"unknown run: {args.target}", args.json)
                return 2
            _emit(payload.get("plan"), args.json)
            return 0
        if args.command in {"patch", "replan"}:
            try:
                payload = json.loads(args.plan_file.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"could not read plan file {args.plan_file}: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise ValueError(f"plan is not valid JSON: {exc.msg}") from exc
            controller = _controller(argparse.Namespace(runtime="mock", runtime_command=None, endpoint=None, model=None, api_key=None, agent_loop=False, memory=False, allow_exec=False, max_steps=40, session_history=False), config)
            if args.command == "patch":
                document = controller.patch_plan(args.run_id, PlanPatch.from_dict(payload))
                reason = "patch applied"
            else:
                if args.command == "replan" and "plan_id" not in payload:
                    current = controller.store.get_current_plan(args.run_id)
                    if current is None:
                        raise ValueError("run has no current plan")
                    payload = {**payload, "plan_id": current.plan_id}
                incoming = PlanDocument.from_dict(payload)
                raw_reason = payload.get("reason", "explicit replan")
                raw_evidence = payload.get("evidence", [])
                if not isinstance(raw_reason, str):
                    raise TypeError("replan reason must be a string")
                if not isinstance(raw_evidence, list) or any(not isinstance(item, str) for item in raw_evidence):
                    raise TypeError("replan evidence must be a string array")
                document = controller.replan(args.run_id, incoming, raw_reason, tuple(raw_evidence))
                reason = "replan applied"
            _emit({"run_id": args.run_id, "plan_id": document.plan_id, "plan_version": document.version, "parent_version": document.parent_version, "status": reason}, args.json)
            return 0
        if args.command == "deliver":
            controller = _controller(argparse.Namespace(runtime="mock", runtime_command=None, endpoint=None, model=None, api_key=None, agent_loop=False, memory=False, allow_exec=False, max_steps=40, session_history=False), config)
            decision = controller.deliver(args.run_id)
            _emit(decision.to_dict(), args.json)
            return 0
    except (
        AgentError,
        AutomaticSolveAlreadyRunning,
        ValueError,
        TypeError,
        OSError,
        EvolutionError,
        EffectTrialError,
        EffectAdapterError,
        EffectKitError,
        ProducerHandoffError,
        SeedAdmissionError,
    ) as exc:
        _emit_error(str(exc), getattr(args, "json", False))
        return 2
    return 2
