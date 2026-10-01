"""Compose generation holdout with durable child trials and the original learning budget."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .rsi_callbacks import DurableCallbackJournal
from .rsi_governance_coordinator import GenerationRegressionRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import RSILearningError
from .rsi_parent_budget import ParentRunBudget
from .rsi_regression_campaign import DurableRegressionCampaign
from .rsi_store import RSILedger
from .rsi_transfer_regression import TransferRegressionReport, TransferTask


class GenerationCampaignRunner:
    """Explicit local composition; governance transitions remain owned by the coordinator."""

    def __init__(self, ledger: RSILedger, run_id: str, *, tasks: Sequence[TransferTask],
                 runner: Callable[..., Any], component_pins: Callable[[], Mapping[str, str]]) -> None:
        self.ledger = ledger
        self.parent = ParentRunBudget(ledger, run_id)
        self.tasks = tuple(TransferTask(**task.to_dict()) for task in tasks)
        self.runner = runner
        self.component_pins = component_pins
        self.campaign = DurableRegressionCampaign(ledger)
        self._config = self.rsi_fingerprint_config()

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        return {"protocol": "rsi-generation-campaign-v1", "parent": self.parent.identity(),
                "manifest": [task.to_dict() for task in self.tasks],
                "runner": component_fingerprint(self.runner),
                "components": dict(self.component_pins())}

    @staticmethod
    def admission_id(request: GenerationRegressionRequest) -> str:
        # Hash rather than joining unescaped caller IDs, which could alias a validation scope.
        return "generation:" + DurableCallbackJournal.digest({
            "intent_sha256": request.intent_sha256, "validation_id": request.validation_id,
        })

    def __call__(self, request: GenerationRegressionRequest) -> TransferRegressionReport:
        def check() -> None:
            if self.rsi_fingerprint_config() != self._config:
                raise RSILearningError("rsi_generation_campaign_fingerprint_drift")

        check()
        return self.campaign.run(
            admission_id=self.admission_id(request), initial_record_sha256=request.intent_sha256,
            tasks=self.tasks, old_memory=request.parent_memory, current_memory=request.current_memory,
            policy=request.policy, runner=self.runner,
            controller_pins={**self._config, "generation_intent_sha256": request.intent_sha256,
                             "validation_id": request.validation_id},
            check_components=check, parent_budget=self.parent,
        )


__all__ = ["GenerationCampaignRunner"]
