"""New directory-reader dependencies stay in the original finite owner policy."""
from types import FunctionType

import pytest

from lunar_evolution import _candidate_workspace_io as directories
from lunar_evolution import rsi_brs_publication_lineage as owner
from lunar_evolution.rsi_fingerprint import RSIFingerprintContract
from lunar_evolution.rsi_learning import RSILearningError


@pytest.mark.parametrize("name", ("fail", "identity"))
def test_directory_helper_foreign_globals_refuse_before_owner_capture(monkeypatch, name):
    function = getattr(directories, name)
    clone = FunctionType(function.__code__, dict(function.__globals__), function.__name__)
    monkeypatch.setattr(directories, name, clone)
    with pytest.raises(RSILearningError, match="globals"):
        owner._policy()


def test_directory_flags_drift_is_refused_and_original_contract_still_roundtrips(monkeypatch):
    original = owner._policy()
    monkeypatch.setattr(directories, "_FLAGS", directories._FLAGS & ~directories.os.O_NOFOLLOW)
    # The retained native provenance reader independently holds its original
    # nofollow flags. A new descriptive digest cannot authorize weaker I/O.
    with pytest.raises(RSILearningError, match="rejection_provenance_policy_drift"):
        owner._policy()
    contract = RSIFingerprintContract.build(
        contract_sha256="a" * 64, evaluator_sha256="b" * 64,
        environment_sha256="c" * 64, memory_snapshot_sha256="d" * 64,
        solver_id="fixture", solver_settings={"producer_brs_checkpoint_policy": original},
        actor_fingerprint="e" * 64, verifier_fingerprint="f" * 64,
        curriculum_fingerprint="1" * 64, target_judge_fingerprint="2" * 64,
    )
    assert RSIFingerprintContract.from_dict(contract.to_dict()).digest() == contract.digest()
