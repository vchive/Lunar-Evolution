The focused fixture compiles `native_producer_isolation.h` directly, installs
the same Landlock/seccomp profile as the producer target, and invokes each
route with zero arguments. Every call must return `-1/EPERM`, demonstrating the
rule runs before kernel argument validation. The same filtered process writes a
small declared file and exchanges bytes through an anonymous pipe to prove the
new rules do not remove ordinary local I/O.

The fixture is provider-free and disposable. It does not use a model, remote
evaluator, WebAgent, external worker, or pre-existing kernel object.
