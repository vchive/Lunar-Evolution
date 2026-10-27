"""Explicit trusted installed wrapper-to-native composition, with pre-gate custody.

No factory or public request creates authorization here. Installation code must
provide previously authorized originals and establish its candidate isolation.
Default/public worker execution and production readiness remain unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionControl
from .external_worker_guardian_vault import retain_installed_guardian_reference
from .external_worker_native_lifecycle import (
    WorkerNativeLifecycleResolver,
    WorkerNativeTaskMapping,
    native_lifecycle_lookup,
)
from .external_worker_native_restart import WorkerNativeRestartWriter
from .external_worker_native_vault import (
    InstalledWorkerNativeVault,
    check_installed_vault_separation,
    retain_installed_native_anchor,
)
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey
from .external_worker_wrapper import WorkerWrapperConfig, validate_worker_request, worker_json
from .native_bootstrap import NativeBootstrapArtifact
from .native_guardian_registration import NativeGuardianCustodyRequest
from .native_trusted_attempt import run_native_trusted_attempt
from .producer_bootstrap import build_trusted_bootstrap_launch
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    verify_producer_launch_attestation,
)
from .rsi_gateway import SolverRequest


class WorkerNativeBridgeError(ValueError):
    """Fixed trusted-bridge errors, without original authorization or private paths."""


def _check_deadline(control: SolveExecutionControl, value: dict, stage: str) -> None:
    control.check(stage)
    # Compare the original absolute wire expiry; never remap it to a fresh
    # relative timeout. A wall-clock forward jump also refuses the native gate.
    if time.time() >= value["deadline_unix"]:
        raise WorkerNativeBridgeError("worker_native_bridge_original_deadline_expired")


@dataclass(frozen=True, slots=True)
class InstalledWorkerNativeLaunch:
    """Previously authorized original installation inputs; never a channel DTO."""

    context: WorkerOriginContext = field(repr=False)
    request: SolverRequest = field(repr=False)
    mapping: WorkerNativeTaskMapping = field(repr=False)
    intent: ProducerLaunchIntent = field(repr=False)
    attestation: ProducerLaunchAttestation = field(repr=False)
    artifact: NativeBootstrapArtifact = field(repr=False)
    workspace: Path = field(repr=False)
    producer_root: Path = field(repr=False)

    def snapshot(self) -> bytes:
        return worker_json({
            "context": self.context.to_dict(), "request": self.request.to_dict(),
            "mapping": self.mapping.to_dict(), "intent": self.intent.to_dict(),
            "attestation": self.attestation.to_dict(), "workspace": str(self.workspace),
            "producer_root": str(self.producer_root), "artifact": {
                "path": str(self.artifact.path), "source_sha256": self.artifact.source_sha256,
                "artifact_sha256": self.artifact.artifact_sha256, "compiler": self.artifact.compiler,
                "allowlist_id": self.artifact.allowlist_id,
                "platform_execution_mode": self.artifact.platform_execution_mode,
                "descriptor": self.artifact.descriptor.to_dict(),
            },
        })


class WorkerInstalledNativeBridge:
    """One trusted original native attempt, invoked only for a newly written intent.

    This explicit API is not a claim that an installation/build/account is
    accepted. A host must install that boundary independently before supplying
    untrusted candidates. Local regression uses a fixed trusted inert target.
    """

    def __init__(self, launch: InstalledWorkerNativeLaunch, *, installation: InstalledWorkerNativeVault,
                 key: WorkerOriginKey, profile_sha256: str,
                 guardian_custody: NativeGuardianCustodyRequest | None = None) -> None:
        types = (("context", WorkerOriginContext), ("request", SolverRequest),
                 ("mapping", WorkerNativeTaskMapping), ("intent", ProducerLaunchIntent),
                 ("attestation", ProducerLaunchAttestation), ("artifact", NativeBootstrapArtifact))
        if (type(launch) is not InstalledWorkerNativeLaunch
                or any(type(getattr(launch, name)) is not expected for name, expected in types)
                or type(installation) is not InstalledWorkerNativeVault or type(key) is not WorkerOriginKey
                or not all(isinstance(path, Path) for path in (launch.workspace, launch.producer_root))
                or (guardian_custody is not None
                    and type(guardian_custody) is not NativeGuardianCustodyRequest)):
            raise WorkerNativeBridgeError("worker_native_bridge_originals_required")
        verify_producer_launch_attestation(launch.intent, launch.attestation)
        self._launch = launch
        self._installation = installation
        self._key = key
        self._profile = profile_sha256
        self._guardian_custody = guardian_custody
        self._baseline = launch.snapshot()
        self._installation_baseline = installation.canonical_bytes
        self._attempted = False
        self._check()

    def _check(self) -> None:
        launch = self._launch
        if (launch.snapshot() != self._baseline
                or self._installation.canonical_bytes != self._installation_baseline):
            raise WorkerNativeBridgeError("worker_native_bridge_originals_drift")
        verify_producer_launch_attestation(launch.intent, launch.attestation)
        check_installed_vault_separation(
            self._installation, key=self._key, profile_sha256=self._profile,
            private_roots=(launch.workspace, launch.producer_root, launch.artifact.path.parent),
        )
        if self._guardian_custody is not None:
            native_launch = build_trusted_bootstrap_launch(
                launch.intent, launch.attestation, launch.artifact.descriptor,
            )
            directory = self._guardian_custody.check_installed_assignment(
                original_context_sha256=hashlib.sha256(worker_json(launch.context.to_dict())).hexdigest(),
                original_launch_sha256=native_launch.launch_sha256,
                original_profile_sha256=self._profile,
            )
            check_installed_vault_separation(
                self._installation, key=self._key, profile_sha256=self._profile,
                private_roots=(directory,),
            )

    def check_wrapper(self, config: WorkerWrapperConfig) -> None:
        self._check()
        if (type(config) is not WorkerWrapperConfig or config.profile_sha256 != self._profile
                or any(getattr(config.key, name) != getattr(self._key, name)
                       for name in ("worker_id", "host_id", "host_boot_id", "key_id"))
                or not hmac.compare_digest(config.key.secret_key, self._key.secret_key)):
            raise WorkerNativeBridgeError("worker_native_bridge_installation_mismatch")

    def run_original(
        self, raw: bytes, *, original_episode_chain: DirectoryChain,
        original_worker_intent: bytes, original_worker_intent_identity: tuple[str | int, ...],
        episode_directory: Path, control: SolveExecutionControl,
    ):
        self._check()
        if self._attempted:
            raise WorkerNativeBridgeError("worker_native_bridge_replayed")
        self._attempted = True
        value = validate_worker_request(raw)
        launch = self._launch
        if (value["action"] != "run" or value["context"] != launch.context.to_dict()
                or value["request"] != launch.request.to_dict()
                or value["request_sha256"] != launch.request.digest()
                or value["profile_sha256"] != self._profile
                or any(value[name] != getattr(self._key, name)
                       for name in ("worker_id", "host_id", "host_boot_id", "key_id"))):
            raise WorkerNativeBridgeError("worker_native_bridge_assignment_mismatch")
        check_installed_vault_separation(
            self._installation, key=self._key, profile_sha256=self._profile,
            private_roots=(episode_directory,),
        )
        _check_deadline(control, value, "installed_worker_native_prepare")
        resolver = WorkerNativeLifecycleResolver()
        try:
            writer = WorkerNativeRestartWriter(key=self._key, profile_sha256=self._profile)
            registered = resolver.prepare_observer(
                context=launch.context, request=launch.request, profile_sha256=self._profile,
                mapping=launch.mapping, intent=launch.intent, attestation=launch.attestation,
                artifact=launch.artifact, workspace=launch.workspace, producer_root=launch.producer_root,
                episode_directory=episode_directory, original_episode_chain=original_episode_chain,
                original_worker_intent=original_worker_intent,
                original_worker_intent_identity=original_worker_intent_identity, restart_writer=writer,
            )
            lookup = native_lifecycle_lookup(context=launch.context, request_sha256=launch.request.digest(),
                                             profile_sha256=self._profile)

            def durable_registered(context) -> None:
                _check_deadline(control, value, "installed_worker_native_before_custody")
                self._check()
                registered(context)
                retain_installed_native_anchor(
                    self._installation, writer.anchor, lookup, key=self._key,
                    expected_context=launch.context, expected_mapping=launch.mapping,
                    expected_profile_sha256=self._profile,
                )
                if self._guardian_custody is not None:
                    retain_installed_guardian_reference(
                        self._installation, self._guardian_custody.reference,
                        writer.anchor, lookup, native_context=context, key=self._key,
                        expected_context=launch.context, expected_mapping=launch.mapping,
                        expected_profile_sha256=self._profile,
                        check=lambda: _check_deadline(
                            control, value, "installed_worker_guardian_custody",
                        ),
                    )
                self._check()
                _check_deadline(control, value, "installed_worker_native_after_custody")

            _check_deadline(control, value, "installed_worker_native_start")
            return run_native_trusted_attempt(
                launch.workspace, producer_root=launch.producer_root, intent=launch.intent,
                attestation=launch.attestation, artifact=launch.artifact,
                parent_deadline=control.deadline, cancelled=control.is_cancelled,
                registered_observer=durable_registered,
                **({"guardian_custody": self._guardian_custody}
                   if self._guardian_custody is not None else {}),
            )
        finally:
            resolver.close()
