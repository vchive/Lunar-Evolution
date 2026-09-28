"""Create the one-shot Feature 142 registration from the frozen case materials."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "specs/142-automatic-solve-lifecycle/measurement"))

from case import build_case_pins

from lunar_evolution.acceptance_observer import DEFAULT_ACCEPTANCE_BUDGETS
from lunar_evolution.acceptance_registration import (
    build_acceptance_registration,
    build_registration_seal,
    parse_acceptance_registration,
    parse_registration_seal,
)

OUTPUT = ROOT / "specs/142-automatic-solve-lifecycle/measurement"


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _pin(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration-id", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--product-commit", required=True)
    args = parser.parse_args()

    if _git("status", "--porcelain", "--untracked-files=all") != "?? tools/prepare_acceptance_registration.py":
        raise SystemExit("registration checkout must contain only this untracked generator")
    if _git("rev-parse", "HEAD") != args.product_commit:
        raise SystemExit("product commit must equal the prepared checkout")

    sources = sorted((ROOT / "src/lunar_evolution").glob("*.py"))
    product_files = [_pin(path) for path in sources]
    case = build_case_pins()
    for key in ("task_material", "input_material", "evaluator_material", "evaluator_profile_material"):
        pin = case[key]
        if _pin(ROOT / pin["path"]) != pin:
            raise SystemExit(f"case material changed: {key}")
    for holdout in case["holdout_pins"]:
        for key in ("input", "expected"):
            pin = holdout[key]
            if _pin(ROOT / pin["path"]) != pin:
                raise SystemExit(f"case holdout changed: {holdout['ordinal']} {key}")

    frozen = {
        "registration_id": ["registration-139-real-multifile-closure-50min"],
        "campaign_id": ["campaign-139-real-multifile-closure-20260920-50min"],
        "campaign_root": ["real-automatic-multifile-closure-20260920-50min"],
    }
    payload = {
        "schema_version": "1", "scope": "acceptance_registration",
        "registration_id": args.registration_id, "campaign_id": args.campaign_id,
        "campaign_root": args.campaign_root, "attempt_id": "attempt-001",
        "product_commit": args.product_commit, "product_files": product_files,
        **case,
        "task_sha256": case["task_material"]["sha256"],
        "input_sha256": case["input_material"]["sha256"],
        "evaluator_sha256": case["evaluator_material"]["sha256"],
        "evaluator_profile_sha256": case["evaluator_profile_material"]["sha256"],
        "provider": "openai-compatible", "model": "glm-5.2",
        "runtime": "openai-compatible", "api_mode": "chat_completions",
        "entrypoint": "src/main.py", "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS),
        "islands": 1, "population_size": 1, "offspring_count": 1,
        "rounds": 1, "candidate_tool_steps": 12,
        "frozen_identities": frozen,
        "frozen_identities_sha256": hashlib.sha256(_canonical(frozen)).hexdigest(),
    }
    registration = build_acceptance_registration(payload)
    seal = build_registration_seal(registration)
    parse_acceptance_registration(_canonical(registration).decode("utf-8"))
    parse_registration_seal(_canonical(seal).decode("utf-8"))
    with (OUTPUT / "registration.json").open("xb") as target:
        target.write(_canonical(registration))
    with (OUTPUT / "registration-seal.json").open("xb") as target:
        target.write(_canonical(seal))
    print(json.dumps({"registration_sha256": registration["registration_sha256"],
                      "product_files": len(product_files), "materials": 20}, sort_keys=True))


if __name__ == "__main__":
    main()
