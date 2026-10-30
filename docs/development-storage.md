# Development storage and retained results

Remote development should use one project directory below
`/home/qinzhiqing/vchive/lunar-evolution-dev/`, with separate `envs/`, `work/`,
`runs/` and `artifacts/` children. This is a convention for new work; it does not
move existing runs, change their recorded paths or grant runtime authority.

Reuse a development environment for the same Python version and dependency lock.
Separate test processes still provide the required fresh-interpreter isolation;
each role does not need another full dependency installation. Keep build-tool
versions and installation profiles explicit. Do not modify an accepted runtime
or a running environment to recover space.

After collecting a completed run, distinguish reproducible work from evidence:

| Material | Retention |
| --- | --- |
| Current environment, active checkout, toolchain and uncommitted work | Keep while referenced. |
| Original run configuration, source commit/tree and archive pins, reservations, logs, XML, exit statuses and audits | Preserve successful and failed originals, with a checked local copy. |
| Old clean role checkouts whose complete source and results are archived | Remove after checking their current Git identity, changes, process references and mount boundaries. |
| Old virtual environments, bytecode and pytest caches | Rebuild when needed; remove after checking that current work does not depend on them. |
| Podman images/containers, shared caches and unrelated account files | Manage separately; never use a broad prune as part of source-workspace cleanup. |

Record exact cleanup paths, identities, refusals and account quota before/after.
Do not sum per-directory sizes as space recovered: environments can share hard
links. Use the account's quota change for the measured reduction. Filesystem free
space does not override the account's soft or hard quota.

Cleanup does not rerun an old acceptance attempt, change a failure to success,
extend its deadline or establish immutable build/runtime custody. Keep the
original evidence and admission boundaries even after disposable work is removed.
