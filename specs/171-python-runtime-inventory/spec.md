# Feature 171 — Declared Python runtime inventory

This P1 slice follows Feature170. A Python producer needs explicit interpreter, library,
dependency, project and resource identities before any native runtime access is widened.
Existing worker trust profiles contain declarations; they do not inspect these host files.

## Contract

- The caller declares bounded, nonoverlapping absolute roots and relative regular files.
  No discovery, user-home scan, module import, interpreter invocation or package manager runs.
- Immutable DTOs freeze the declared CPython target, import directories, entrypoint, launcher
  policy and each file's bytes, SHA-256, size, device, inode, permissions and timestamps.
  All used ancestor, root and parent/import directories retain device/inode/mode pins.
- Require one executable interpreter, stdlib material, project entrypoint and dependency lock.
  A declared venv tree additionally requires one regular `pyvenv.cfg`. Reject links, special
  files, path traversal, aliases, duplicate declarations and listed customization hooks.
- Canonical parsing is strict, bounded and read-only. Separate runtime, dependency, project,
  resource and metadata digests cover actual file observations. The manifest itself is pinned.
- Builder and verifier independently read two complete declared-file snapshots. The verifier
  additionally requires the caller's original manifest digest and declared target. Any byte,
  file identity or directory identity drift refuses with a fixed error code.
- Observations explicitly state `scope=declared-files-only`, `execution_performed=false` and
  `runtime_load_protection=false`. Repeated verification performs no writes or scheduling.

## Boundary

Target ABI/version are declarations, not binary inspection. Fixed `-I -S -B` and no Python
environment, user site, `.pth`, customization, cwd imports or bytecode writes describe a future
launcher policy; this API does not enforce it. Import directory contents are not enumerated.
Unlisted files do not become verified, and adding one does not change this declared-file inventory.
Writable observed files are not sealed. No isolation grants, native argv, RSI/producer marker,
attestation, deadline, worker admission or campaign behavior changes.

Next work requires a separately designed immutable runtime layout and complete import inventory,
then native launch binding and a local Python/broker fixture. No real model, WebAgent, remote or
company evaluator, upstream campaign, `.env` or credentials are used for validation.
