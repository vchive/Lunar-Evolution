"""Named solver and evaluator profiles, independent from Runtime adapters."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .budget import BudgetSpec
from .evaluator import Evaluator, NonEmptyEvaluator

_SECRET_RE = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)")


def _profile_text(value: str, name: str) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if not value or len(value.encode("utf-8")) > 8_000 or _SECRET_RE.search(value):
        raise ValueError(f"{name} must be bounded and contain no credential-like content")
    return value


@dataclass(frozen=True)
class SolverProfile:
    name: str
    description: str
    required_capabilities: tuple[str, ...]
    budget: BudgetSpec = field(default_factory=BudgetSpec)

    def __post_init__(self) -> None:
        _profile_text(self.name, "solver profile name")
        _profile_text(self.description, "solver profile description")
        if len(self.required_capabilities) > 16:
            raise ValueError("solver profile has too many capabilities")
        for capability in self.required_capabilities:
            _profile_text(capability, "solver capability")


@dataclass(frozen=True)
class EvaluatorProfile:
    name: str
    description: str
    factory: Callable[[], Evaluator]

    def __post_init__(self) -> None:
        _profile_text(self.name, "evaluator profile name")
        _profile_text(self.description, "evaluator profile description")
        if not callable(self.factory):
            raise TypeError("evaluator profile factory must be callable")

    def create(self) -> Evaluator:
        return self.factory()


@dataclass(frozen=True)
class ModelProfile:
    """Bounded model execution and spend policy.

    The profile is deliberately provider-neutral: ``model`` is an opaque endpoint model id and
    prices are optional micro-USD per 1,000 tokens.  A profile can therefore be used with a local
    endpoint (without prices) while still enforcing a hard token ceiling.
    """

    name: str
    model: str
    thinking_budget: int = 0
    max_steps: int = 40
    timeout_seconds: float = 900.0
    max_total_tokens: int | None = None
    max_cost_micros: int | None = None
    input_cost_per_1k_micros: int | None = None
    output_cost_per_1k_micros: int | None = None
    max_completion_tokens: int | None = None

    def __post_init__(self) -> None:
        _profile_text(self.name, "model profile name")
        _profile_text(self.model, "model profile model")
        if (
            isinstance(self.thinking_budget, bool)
            or not isinstance(self.thinking_budget, int)
            or not 0 <= self.thinking_budget <= 1_000_000
        ):
            raise ValueError("thinking_budget must be an integer between 0 and 1000000")
        if (
            isinstance(self.max_steps, bool)
            or not isinstance(self.max_steps, int)
            or not 1 <= self.max_steps <= 200
        ):
            raise ValueError("max_steps must be between 1 and 200")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0 < self.timeout_seconds <= 86_400
        ):
            raise ValueError("timeout_seconds must be finite and between 0 and 86400")
        for field_name in (
            "max_total_tokens",
            "max_cost_micros",
            "input_cost_per_1k_micros",
            "output_cost_per_1k_micros",
        ):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{field_name} must be a non-negative integer or null")
        if (self.input_cost_per_1k_micros is None) != (self.output_cost_per_1k_micros is None):
            raise ValueError("input and output token prices must be supplied together")
        if self.max_cost_micros is not None and self.input_cost_per_1k_micros is None:
            raise ValueError("max_cost_micros requires input and output token prices")
        if self.max_total_tokens == 0 or self.max_cost_micros == 0:
            raise ValueError("token and cost ceilings must be positive when supplied")
        if self.max_completion_tokens is not None and (
            isinstance(self.max_completion_tokens, bool)
            or not isinstance(self.max_completion_tokens, int)
            or not 1 <= self.max_completion_tokens <= 1_000_000
        ):
            raise ValueError("max_completion_tokens must be an integer between 1 and 1000000 or null")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "name": self.name,
            "model": self.model,
            "thinking_budget": self.thinking_budget,
            "max_steps": self.max_steps,
            "timeout_seconds": float(self.timeout_seconds),
            "max_total_tokens": self.max_total_tokens,
            "max_cost_micros": self.max_cost_micros,
            "input_cost_per_1k_micros": self.input_cost_per_1k_micros,
            "output_cost_per_1k_micros": self.output_cost_per_1k_micros,
        }
        # Omit an unset limit to preserve canonical identities of existing profiles.
        if self.max_completion_tokens is not None:
            value["max_completion_tokens"] = self.max_completion_tokens
        return value

    @classmethod
    def from_dict(cls, value: object) -> ModelProfile:
        if not isinstance(value, dict):
            raise TypeError("model profile must be an object")
        required = {"name", "model"}
        missing = required - set(value)
        if missing:
            raise ValueError(
                f"model profile is missing required fields: {', '.join(sorted(missing))}"
            )
        allowed = {
            "name",
            "model",
            "thinking_budget",
            "max_steps",
            "timeout_seconds",
            "max_total_tokens",
            "max_cost_micros",
            "input_cost_per_1k_micros",
            "output_cost_per_1k_micros",
            "max_completion_tokens",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown model profile fields: {', '.join(sorted(unknown))}")
        defaults = cls("default", "local").to_dict()
        defaults.update(value)
        return cls(**defaults)


class ProfileRegistry:
    def __init__(self, solvers: tuple[SolverProfile, ...] | None = None, evaluators: tuple[EvaluatorProfile, ...] | None = None) -> None:
        solver_items = solvers or self._default_solvers()
        evaluator_items = evaluators or self._default_evaluators()
        if len({item.name for item in solver_items}) != len(solver_items):
            raise ValueError("solver profile names must be unique")
        if len({item.name for item in evaluator_items}) != len(evaluator_items):
            raise ValueError("evaluator profile names must be unique")
        self.solvers = {item.name: item for item in solver_items}
        self.evaluators = {item.name: item for item in evaluator_items}

    @staticmethod
    def _default_solvers() -> tuple[SolverProfile, ...]:
        return tuple(
            SolverProfile(name, f"{name} local solver", capabilities)
            for name, capabilities in {
                "general": ("read_files", "write_artifacts"),
                "data": ("read_files", "write_files", "analyze_data", "write_artifacts"),
                "research": ("read_files", "gather_sources", "write_artifacts"),
                "coding": ("read_files", "write_files", "run_tests", "write_artifacts"),
            }.items()
        )

    @staticmethod
    def _default_evaluators() -> tuple[EvaluatorProfile, ...]:
        return tuple(EvaluatorProfile(name, f"{name} structured evaluator", NonEmptyEvaluator) for name in ("general", "data", "research", "coding"))

    def solver(self, name: str) -> SolverProfile:
        try:
            return self.solvers[name]
        except KeyError as exc:
            raise ValueError(f"unknown solver profile: {name}") from exc

    def evaluator(self, name: str) -> Evaluator:
        try:
            return self.evaluators[name].create()
        except KeyError as exc:
            raise ValueError(f"unknown evaluator profile: {name}") from exc
