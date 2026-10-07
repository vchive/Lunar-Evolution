# Validation

Use provider-free C fixtures with the actual production isolation header. Assert exact refusal
codes, unchanged session/group, surviving fixture supervisor and ordinary fork/vfork/thread
success. Signal probes use signal zero; no real controller or arbitrary host PID is attacked.

Linux enforcement must be demonstrated by Linux CI; on Darwin these execution cases skip with
an explicit platform reason. Static/source checks are supporting evidence only. Retain separate
focused XML and existing native-cleanup/full runner results.

Local Darwin: new Linux module26 platform skips (`/tmp/lunar-feature172-control-local.xml`),
isolation/bootstrap joint11 passed/34 skips (`/tmp/lunar-feature172-native-local.xml`), existing
native attempt/broker/controller/deadline85 passed (`/tmp/lunar-feature172-native-broker-local.xml`).
The85-case invocation exited0 with old immutable pytest temporary-fixture cleanup warnings.
Root final joint suite351 passed/34 skips,0 failure/error, no warnings
(`/tmp/lunar-local-runtime-final-oct8.xml`); counts overlap. Ruff/compileall/diff checks passed.
Independent BPF/fixture review found and fixed an unsupported-architecture branch that could
skip KILL with modern headers; unsupported ABIs now return ENOTSUP before Landlock.

Final source adds queued-signal and pidfd_getfd refusals: the Linux module is now29 cases.
After this Linux-only refinement, targeted architecture/control verification is1 passed/29 Darwin
skips (`/tmp/lunar-control-final-v2-oct8.xml`), with0 failure/error and no warnings. The one passed
case compiles the real unsupported-ABI header branch even with modern syscall names and confirms
ENOTSUP; it does not execute Linux seccomp. Earlier joint counts above retain their actual revision.

No local result claims actual Linux syscall enforcement. Final-head Ubuntu CI must run the C
fixtures and full regression before merge; checks and merge records supply later status.
