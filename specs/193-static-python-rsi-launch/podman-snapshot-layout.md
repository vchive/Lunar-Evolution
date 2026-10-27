# Bounded Podman snapshot layout

The explicit `custody_backend="podman-snapshots-v1"` uses the original v3 runner
and dependency consumer. The default and the separately copied `podman` image
layout remain available. A fixed empty scratch image is imported once per
attempt and addressed by its actual image ID. Before every original start, OCI
inspection verifies that same image and the effective mounts, argv, environment,
resource restrictions, namespaces, capabilities and seccomp policy.

The runner creates the complete pinned source/toolchain snapshots itself, with
no-follow reads, byte verification and ordinary private copies before any build
command. The new layout mounts only those snapshots at `/source` and `/toolchain`
read-only, with nosuid/nodev. It does not mount caller-selected source directories.
For every command, it makes a new private `/work` view by copying and verifying
only earlier declared output groups. This is a separate copy, without hardlinks,
not a bind of the live host work directory. Generated executables remain available
only after the original entire output group passes. The current output is a
different fresh `/out` bind. No previous header/object/archive is writable by the
next command. Explicit executable mounts and an omitted default `exec` OCI option
have equivalent semantics; an effective `noexec` input mount is refused.

This removes the requirement to import the complete 358 MB Zig tree once per
command. The new profile permits at most 512 commands, within the existing v3
graph limit, rather than the copied-image profile's 32-command limit. The original
4 GiB input bound remains; cumulative retained prior-output copies and the empty
image are bounded by the original 8 GiB retained-copy budget. The bound is checked
before each copy. The base image archive is reverified before reuse. All original
fresh input/output drift observations and deadlines remain. No test result claims
that a whole CPython build actually fits its budget merely because its command
count fits. Copy/hash cost still requires actual full-build acceptance.

The trusted host, pinned tools and existing local Podman/crun daemon remain the
TCB. Read-only guest mounts prevent a build command from changing these inputs;
they do not prevent a malicious host from modifying its ordinary copied files.
This layout does not claim independently immutable consumed bytes or aggregate
hard output quota. It preserves all false custody/driver/installation/production
claims and the original unknown-cleanup gate. There is no arbitrary container
image, Dockerfile, shell helper, ambient bind, network, fallback, automatic retry,
new admission route or changed original deadline.

Focused coverage exercises real prior copying and readback, byte/symlink refusal,
copy/command limits, base archive drift, actual OCI mount mutation and the original
runner's selection boundary. An actual Linux original-consumer inert smoke must
also confirm this layout before claiming daemon-backed execution. Configuration,
real Zig support, complete CPython build and solver lifecycle are separate gates.
