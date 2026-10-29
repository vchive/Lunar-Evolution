"""Detached replay checks real original OCI structure, beyond self-consistent pins."""

from __future__ import annotations

import copy

import pytest

from tests.test_static_python_source_data_backend import observed, source_data_vector
from tools.static_python_rsi_fixture import podman_custody as custody


@pytest.fixture
def original(tmp_path, monkeypatch):
    vector = source_data_vector(tmp_path, monkeypatch)
    policy = observed(vector)
    spec = copy.deepcopy(vector[5])
    policy["root_acquisition"] = {"ancillary_mounts": [{
        "destination": row["path"], "source": next(
            mount["source"] for mount in spec["mounts"] if mount["destination"] == row["path"]),
        "size": row["size"], "sha256": row["sha256"],
    } for row in policy["runtime_metadata"]]}
    value = {"runtime_policy": policy, "executed_argv": copy.deepcopy(spec["process"]["args"]),
             "executed_environment": {"LANG": "C"}, "container_id": "b" * 64}
    return spec, value, vector[0].destination


def replay(original):
    spec, value, workspace = original
    custody._retained_runtime_spec(spec, value, workspace, "configure", 0)


def test_detached_replay_accepts_original_finite_policy_without_reacquiring_service(original, monkeypatch):
    monkeypatch.setattr(custody.PodmanCustody, "_control", lambda *_args: pytest.fail("live query"))
    replay(original)


@pytest.mark.parametrize("change", [
    "root-writable", "root-substitution", "capability", "privilege", "args", "environment", "cwd",
    "namespace-path", "namespace-duplicate", "seccomp", "memory", "pids", "cpu", "boolean-resource",
    "core", "fsize", "duplicate-rlimit", "source-path", "source-executable", "toolchain-options",
    "current-readonly", "resolver-source", "resolver-writable", "shm-writable", "tmp-size",
    "unknown-mount", "duplicate-mount", "conflicting-options", "duplicate-option-key", "missing-source",
])
def test_detached_replay_rejects_weakened_oci_even_with_recomputed_digest(original, change):
    spec, value, _workspace = original
    process, linux = spec["process"], spec["linux"]
    mounts = {row["destination"]: row for row in spec["mounts"]}
    if change == "root-writable":
        spec["root"]["readonly"] = False
    elif change == "root-substitution":
        spec["root"]["path"] = "/different/root"
    elif change == "capability":
        process["capabilities"]["effective"] = ["CAP_SYS_ADMIN"]
    elif change == "privilege":
        process["noNewPrivileges"] = False
    elif change == "args":
        process["args"] = ["/different/helper"]
    elif change == "environment":
        process["env"].append("LD_PRELOAD=/host/override")
    elif change == "cwd":
        process["cwd"] = "/host"
    elif change == "namespace-path":
        linux["namespaces"][0]["path"] = "/proc/1/ns/pid"
    elif change == "namespace-duplicate":
        linux["namespaces"].append(copy.deepcopy(linux["namespaces"][0]))
    elif change == "seccomp":
        linux["seccomp"]["syscalls"] = []
    elif change == "memory":
        linux["resources"]["memory"]["limit"] *= 2
    elif change == "pids":
        linux["resources"]["pids"]["limit"] = 257
    elif change == "cpu":
        linux["resources"]["cpu"]["quota"] = 200001
    elif change == "boolean-resource":
        linux["resources"]["pids"]["limit"] = True
    elif change == "core":
        process["rlimits"][0]["soft"] = 1
    elif change == "fsize":
        process["rlimits"][1]["hard"] *= 2
    elif change == "duplicate-rlimit":
        process["rlimits"].append(copy.deepcopy(process["rlimits"][0]))
    elif change == "source-path":
        mounts["/source"]["source"] = "/host/source"
    elif change == "source-executable":
        mounts["/source"]["options"].remove("noexec")
    elif change == "toolchain-options":
        mounts["/toolchain"]["options"].append("noexec")
    elif change == "current-readonly":
        mounts["/out"]["options"][0] = "ro"
    elif change == "resolver-source":
        mounts["/etc/resolv.conf"]["source"] = "/etc/resolv.conf"
    elif change == "resolver-writable":
        mounts["/etc/resolv.conf"]["options"][0] = "rw"
    elif change == "shm-writable":
        mounts["/dev/shm"]["options"][0] = "rw"
    elif change == "tmp-size":
        mounts["/tmp"]["options"][-1] = "size=1073741824"
    elif change == "unknown-mount":
        spec["mounts"].append({"source": "/host", "destination": "/alias", "type": "bind", "options": []})
    elif change == "duplicate-mount":
        spec["mounts"].append(copy.deepcopy(mounts["/source"]))
    elif change == "conflicting-options":
        mounts["/tmp"]["options"].append("exec")
    elif change == "duplicate-option-key":
        mounts["/tmp"]["options"].append("size=1")
    else:
        spec["mounts"].remove(mounts["/source"])
    value["runtime_policy"]["oci_sha256"] = custody._pin(custody._json(spec))
    with pytest.raises(ValueError, match="retained_runtime_spec"):
        replay(original)


@pytest.mark.parametrize("target,data", [("/etc/passwd", custody._PASSWD), ("/etc/group", custody._GROUP)])
def test_replay_checks_fixed_account_bytes_after_coordinated_pin_changes(original, target, data):
    spec, value, workspace = original
    source = str(workspace / "metadata" / value["container_id"] / "userdata" / target.rsplit("/", 1)[-1])
    spec["mounts"].append({"source": source, "destination": target, "type": "bind",
                           "options": ["ro", "noexec", "nosuid", "nodev"]})
    row = {"destination": target, "source": source, "size": len(data), "sha256": custody._pin(data)}
    value["runtime_policy"]["root_acquisition"]["ancillary_mounts"].append(row)
    replay(original)
    row["sha256"] = custody._pin(b"substituted account data")
    with pytest.raises(ValueError, match="retained_runtime_spec"):
        replay(original)
