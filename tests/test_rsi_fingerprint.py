from __future__ import annotations

import hashlib

import pytest

from lunar_evolution.rsi_fingerprint import (
    FingerprintContract,
    RSIFingerprintContract,
    RSIFingerprintError,
    RunFingerprint,
    canonical_fingerprint_digest,
    compare_fingerprint_contracts,
    ensure_fingerprint_compatible,
)

HEX = "a" * 64
OTHER = "b" * 64


def make_contract(**changes):
    values = {
        "contract_sha256": HEX,
        "evaluator_sha256": HEX,
        "environment_sha256": HEX,
        "memory_snapshot_sha256": HEX,
        "solver_id": "native",
        "solver_settings": {"iterations": 3, "seed": 7, "nested": {"enabled": True}},
        "actor_fingerprint": HEX,
        "verifier_fingerprint": HEX,
        "curriculum_fingerprint": HEX,
        "target_judge_fingerprint": HEX,
    }
    values.update(changes)
    return RSIFingerprintContract.build(**values)


def test_contract_is_canonical_and_round_trips() -> None:
    contract = make_contract()
    assert isinstance(contract, RunFingerprint)
    assert isinstance(contract, FingerprintContract)
    assert len(contract.digest()) == 64
    assert contract.digest() == hashlib.sha256(
        __import__("lunar_evolution.candidate_evaluation_spec", fromlist=["canonical_json"]).canonical_json(
            contract.to_dict(), maximum=128 * 1024
        )
    ).hexdigest()
    assert RSIFingerprintContract.from_dict(contract.to_dict()) == contract
    assert canonical_fingerprint_digest(contract) == contract.digest()
    assert canonical_fingerprint_digest(contract.to_dict()) == contract.digest()
    assert len(contract.solver_fingerprint) == 64


def test_mapping_order_does_not_change_digest() -> None:
    left = make_contract(solver_settings={"z": 1, "a": {"y": 2, "x": 3}})
    right = make_contract(solver_settings={"a": {"x": 3, "y": 2}, "z": 1})
    assert left == right
    assert left.digest() == right.digest()


@pytest.mark.parametrize(
    "field",
    [
        "contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256",
        "actor_fingerprint", "verifier_fingerprint", "curriculum_fingerprint",
        "target_judge_fingerprint",
    ],
)
def test_changed_identity_is_drift_with_reason(field: str) -> None:
    expected = make_contract()
    actual = make_contract(**{field: OTHER})
    result = compare_fingerprint_contracts(expected, actual)
    assert not result.compatible
    assert result.reason_codes == (f"{field}_changed",)
    assert result.drift_reason == f"{field}_changed"
    with pytest.raises(RSIFingerprintError, match="rsi_fingerprint_drift"):
        ensure_fingerprint_compatible(expected, actual)


def test_solver_id_and_settings_are_drifted() -> None:
    expected = make_contract()
    assert compare_fingerprint_contracts(expected, make_contract(solver_id="openevolve")).reason_codes == (
        "solver_id_changed",
    )
    result = compare_fingerprint_contracts(expected, make_contract(solver_settings={"iterations": 4}))
    assert result.reason_codes == ("solver_settings_changed",)


def test_multiple_drift_reasons_are_stable_and_fail_closed() -> None:
    result = compare_fingerprint_contracts(
        make_contract(), make_contract(evaluator_sha256=OTHER, actor_fingerprint=OTHER)
    )
    assert result.reason_codes == ("evaluator_sha256_changed", "actor_fingerprint_changed")
    assert result.to_dict()["compatible"] is False


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"contract_sha256": "missing"}, "digest_invalid"),
        ({"solver_id": "bad\nsolver"}, "solver_id_invalid"),
        ({"solver_settings": {"x": float("nan")}}, "solver_settings_invalid"),
        ({"solver_settings": {1: "bad"}}, "solver_settings_invalid"),
    ],
)
def test_malformed_contract_fails_closed(kwargs, code: str) -> None:
    with pytest.raises(RSIFingerprintError) as exc:
        make_contract(**kwargs)
    assert exc.value.code == f"rsi_fingerprint_{code}"


def test_record_parser_rejects_unknown_or_missing_fields() -> None:
    payload = make_contract().to_dict()
    payload["unexpected"] = 1
    with pytest.raises(RSIFingerprintError):
        RSIFingerprintContract.from_dict(payload)
    del payload["unexpected"]
    del payload["target_judge_fingerprint"]
    with pytest.raises(RSIFingerprintError):
        RSIFingerprintContract.from_dict(payload)


def test_alias_target_judge_sha256_requires_exact_match() -> None:
    contract = make_contract()
    values = contract.to_dict()
    values.pop("schema_version")
    values.pop("kind")
    values["target_judge_fingerprint"] = HEX
    values.pop("target_judge_fingerprint")
    built = RSIFingerprintContract.build(**values, target_judge_sha256=HEX)
    assert built == contract
    mismatch = dict(values, target_judge_fingerprint=HEX)
    with pytest.raises(RSIFingerprintError):
        RSIFingerprintContract.build(**mismatch, target_judge_sha256=OTHER)


def test_invalid_comparison_inputs_fail_closed() -> None:
    with pytest.raises(RSIFingerprintError) as exc:
        compare_fingerprint_contracts({}, make_contract())
    assert exc.value.code == "rsi_fingerprint_expected_invalid"
    with pytest.raises(RSIFingerprintError) as exc:
        compare_fingerprint_contracts(make_contract(), {})
    assert exc.value.code == "rsi_fingerprint_actual_invalid"
