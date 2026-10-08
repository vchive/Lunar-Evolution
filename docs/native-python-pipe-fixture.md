# Native Python pipe compatibility fixture

This P1 fixture exercises a real installed CPython child through the existing native
bootstrap and private original-grant control v2. A sealed inert C launcher execs the
explicit fixture interpreter with `-I -S -B`; the Python child imports the existing
producer pipe SDK and exchanges inert framed bytes with a private parent responder.
The workflow retains dedicated `python-pipe.xml` alongside all earlier native and
full regression phases.

The test explicitly grants its trusted installed runtime layout and fixture SDK source.
Those test declarations do not enter production launch APIs. Evidence is scoped to
`trusted-host-fixture-only`; `runtime_load_protection=false`. The launcher is sealed,
while CPython, its native loader, stdlib and SDK import bytes are trusted installed host
files. Actual flags/version/cache tag and pipe behavior are observed compatibility facts.

The acceptance checks cover the original ready/release/start/terminal lifecycle, useful
output, inherited pipe endpoints, actual SDK response refusals and isolated import/no-pyc
behavior. Fixture parents own their fresh processes and descriptors and clean them up.
There is no model, provider request, solver campaign or remote evaluator.

Existing runtime171/177 APIs remain declared/closed-filesystem preflight. Complete
archive/loader/import closure, immutable runtime loading, versioned recipient delivery
and formal Python worker admission remain separate production work. This fixture gives
concrete startup/load evidence for those next decisions; it does not complete them.
