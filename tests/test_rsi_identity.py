from __future__ import annotations

import pytest

from lunar_evolution.rsi_identity import RSIIdentityError, component_fingerprint, component_identity


class ConfiguredVerifier:
    def __init__(self, threshold: float = 0.5, counter: int = 0) -> None:
        self.threshold = threshold
        self.counter = counter

    def rsi_fingerprint_config(self):
        return {"threshold": self.threshold}

    def verify(self, value):
        return value >= self.threshold


class AlternateVerifier(ConfiguredVerifier):
    def verify(self, value):
        return value > self.threshold


class GeneratedComponent:
    def __init__(self, label: str) -> None:
        self.label = label

    def rsi_fingerprint_config(self):
        return {"label": self.label}

    def rsi_fingerprint_code(self):
        return "generated-component-v1"


class NoConfig:
    def run(self):
        return None


def test_same_configured_instances_have_same_fingerprint_without_runtime_counters() -> None:
    left = ConfiguredVerifier(threshold=0.75, counter=1)
    right = ConfiguredVerifier(threshold=0.75, counter=999)
    assert component_fingerprint(left) == component_fingerprint(right)
    assert component_identity(left).to_dict()["config"] == {"threshold": 0.75}


def test_stable_config_and_code_changes_are_detected() -> None:
    baseline = component_fingerprint(ConfiguredVerifier(threshold=0.5))
    changed_config = component_fingerprint(ConfiguredVerifier(threshold=0.6))
    changed_code = component_fingerprint(AlternateVerifier(threshold=0.5))
    assert baseline != changed_config
    assert baseline != changed_code


def test_explicit_hooks_support_generated_code_and_configuration() -> None:
    first = GeneratedComponent("alpha")
    second = GeneratedComponent("alpha")
    assert component_fingerprint(first) == component_fingerprint(second)
    assert component_fingerprint(first) != component_fingerprint(GeneratedComponent("beta"))


def test_explicit_arguments_override_hooks() -> None:
    component = ConfiguredVerifier(threshold=0.5)
    left = component_fingerprint(component, config={"threshold": 0.5}, code="code-v1")
    right = component_fingerprint(component, config={"threshold": 0.6}, code="code-v1")
    changed_code = component_fingerprint(component, config={"threshold": 0.5}, code="code-v2")
    assert left != right
    assert left != changed_code


@pytest.mark.parametrize("value", [NoConfig(), object()])
def test_arbitrary_mutable_instances_require_explicit_config(value) -> None:
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_hook_required"):
        component_fingerprint(value)


def test_invalid_config_fails_closed() -> None:
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_invalid"):
        component_fingerprint(ConfiguredVerifier(), config={1: "bad"})
    with pytest.raises(RSIIdentityError, match="rsi_identity_config_invalid"):
        component_fingerprint(ConfiguredVerifier(), config={"nan": float("nan")})


def test_identity_payload_is_canonical_and_bounded() -> None:
    identity = component_identity(ConfiguredVerifier(), config={"b": 2, "a": 1})
    assert identity.to_bytes() == component_identity(
        ConfiguredVerifier(), config={"a": 1, "b": 2}
    ).to_bytes()
    assert len(identity.digest()) == 64
