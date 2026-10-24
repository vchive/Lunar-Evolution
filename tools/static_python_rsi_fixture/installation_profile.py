"""Pure, fixed source-input overlay preparation; never installation acceptance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from tools.static_python_fixture.build_inputs import emit_static_python_build_inputs

PROFILE = "rsi-marker-launch-v1"
_BASE_SIZE = 80050
_BASE_SHA256 = "6e2d35188aadc5e00f2d6eb98e90b2f9e34f3a425c8f3575b759f52c3e38ba5c"
_OVERLAY_SIZE = 2456
_OVERLAY_SHA256 = "91d808742d567a79b2deca48e977fd696771904e0c6c059a94ffa4274ea599e8"
_SOURCE_PLAN_SIZE = 6706
_SOURCE_PLAN_SHA256 = "bd95a2c120821d5ff4b72cae740e3abc85ee747881c13aa43ffddd9bd4197175"
_ASSETS = frozenset({
    "launcher.c", "pipe.c", "profile.c", "getpath.c", "lunar_fixture_profile.h", "frozen_main.py",
})
_FALSE_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
)


class RSIProfilePreparationError(ValueError):
    """Fixed refusal without caller metadata or callback exception disclosure."""

    def __init__(self, reason: str) -> None:
        super().__init__("static_python_rsi_profile_" + reason)


@dataclass(frozen=True, slots=True)
class RSIProfilePreparation:
    """Immutable preparation wire; no production consumer accepts this schema."""

    wire_bytes: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.wire_bytes).hexdigest()


def _pin(raw: bytes, size: int, digest: str) -> None:
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise RSIProfilePreparationError("source_pin_mismatch")


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RSIProfilePreparationError("json_invalid")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise RSIProfilePreparationError("json_invalid")


def _load(raw: bytes) -> dict:
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if type(value) is not dict:
        raise RSIProfilePreparationError("json_invalid")
    return value


def prepare_rsi_installation_profile(
    *,
    reviewed_build_inputs: bytes,
    reviewed_overlay: bytes,
    source_plan: bytes,
    expected_source_plan_sha256: str,
    source_assets: dict[str, bytes],
) -> RSIProfilePreparation:
    """Prepare exactly two reviewed source substitutions, without any side effects.

    Digests identify source bytes only. No generated headers, object/link/ELF
    closure, runtime/input evidence or accepted installation is produced.
    """
    try:
        # Validate exact built-ins before length, iteration, hashing or comparisons
        # can dispatch caller-defined callbacks. Sizes bound all later JSON work.
        for raw, maximum in (
            (reviewed_build_inputs, 128 * 1024), (reviewed_overlay, 8 * 1024),
            (source_plan, 16 * 1024),
        ):
            if type(raw) is not bytes or not 0 < len(raw) <= maximum:
                raise RSIProfilePreparationError("input_shape_invalid")
        if (type(expected_source_plan_sha256) is not str
                or len(expected_source_plan_sha256) != 64
                or any(c not in "0123456789abcdef" for c in expected_source_plan_sha256)):
            raise RSIProfilePreparationError("caller_pin_invalid")
        if type(source_assets) is not dict or len(source_assets) != 6:
            raise RSIProfilePreparationError("asset_shape_invalid")
        # Retain our own map so a caller cannot replace values after validation.
        assets = source_assets.copy()
        for name, raw in assets.items():
            if (type(name) is not str or len(name) > 64 or type(raw) is not bytes
                    or not 0 < len(raw) <= 16 * 1024):
                raise RSIProfilePreparationError("asset_shape_invalid")
        if set(assets) != _ASSETS:
            raise RSIProfilePreparationError("asset_shape_invalid")

        _pin(reviewed_build_inputs, _BASE_SIZE, _BASE_SHA256)
        _pin(reviewed_overlay, _OVERLAY_SIZE, _OVERLAY_SHA256)
        if expected_source_plan_sha256 != _SOURCE_PLAN_SHA256:
            raise RSIProfilePreparationError("caller_pin_mismatch")
        _pin(source_plan, _SOURCE_PLAN_SIZE, _SOURCE_PLAN_SHA256)
        overlay, plan = _load(reviewed_overlay), _load(source_plan)
        if (overlay["schema"] != "lunar-static-python-rsi-profile-overlay-v1"
                or overlay["profile"] != PROFILE
                or overlay["base"] != {"size": _BASE_SIZE, "sha256": _BASE_SHA256}
                or overlay["source_plan"] != {
                    "size": _SOURCE_PLAN_SIZE, "sha256": _SOURCE_PLAN_SHA256,
                }
                or plan["schema"] != "lunar-static-python-rsi-launch-source-plan-v1"
                or plan["profile"] != PROFILE
                or set(plan["claims"]) != set(_FALSE_CLAIMS)
                or any(value is not False for value in plan["claims"].values())):
            raise RSIProfilePreparationError("profile_mismatch")
        # This fixed, independently pinned manifest commits to all eleven inputs,
        # six payloads and both argument domains. A re-signed mutant is not accepted.
        if len(plan["source_inputs"]) != 11 or len(plan["emitted_sources"]) != 6:
            raise RSIProfilePreparationError("profile_mismatch")
        for record in plan["emitted_sources"]:
            name = record["path"].removeprefix("assets/")
            _pin(assets[name], record["size"], record["sha256"])

        candidate = emit_static_python_build_inputs(reviewed_build_inputs)
        changes = overlay["substitutions"]
        expected = (
            ("target_units", "object", "installation-owned-launcher.o"),
            ("freeze_tasks", "name", "_lunar_static_main"),
        )
        if len(changes) != 2:
            raise RSIProfilePreparationError("substitution_invalid")
        for change, identity in zip(changes, expected, strict=True):
            section, key, value = identity
            if (change["section"], change["key"], change["value"]) != identity:
                raise RSIProfilePreparationError("substitution_invalid")
            matches = [i for i, record in enumerate(candidate[section]) if record[key] == value]
            if len(matches) != 1 or candidate[section][matches[0]] != change["before"]:
                raise RSIProfilePreparationError("substitution_preimage_mismatch")
            candidate[section][matches[0]] = change["after"]
        # The separate schema prevents routing this partial candidate through the
        # old fixed build-input validator or accepted installation descriptor path.
        candidate["schema"] = "lunar-static-python-rsi-build-input-candidate-v1"
        wire = {
            "schema": "lunar-static-python-rsi-installation-profile-preparation-v1",
            "profile": PROFILE,
            "base_reviewed_inputs": overlay["base"],
            "reviewed_overlay": {"size": _OVERLAY_SIZE, "sha256": _OVERLAY_SHA256},
            "source_plan": overlay["source_plan"],
            "launch_policy": plan["launch_policy"],
            "initialization_profile": plan["initialization_profile"],
            "substitutions": changes,
            "candidate_build_inputs": candidate,
            "pending_frozen_headers": [
                {"name": task["name"], "output": task["output"],
                 "source_sha256": task["source_sha256"], "state": "pending-freezer"}
                for task in candidate["freeze_tasks"]
            ],
            "claims": dict.fromkeys(_FALSE_CLAIMS, False),
            "artifact_state": "pending-builder", "startup_state": "not-executed",
        }
        raw = (json.dumps(wire, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
        return RSIProfilePreparation(raw)
    except RSIProfilePreparationError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise RSIProfilePreparationError("preparation_invalid") from exc
