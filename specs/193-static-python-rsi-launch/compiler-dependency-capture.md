# Actual compiler dependency capture

This continuation implements an explicit opt-in recipe and retained-byte
comparison. It does not provide an immutable source-custody boundary or an
accepted configured build. The original concrete recipe remains unchanged.

`prepare_cpython_dependency_recipe` generates the original pinned CPython/Zig
recipe, then adds `-MD -MF <fixed-output> -MQ <original-object>` to every C
compilation, including the configuration probe, same-source freezer units and
target units. Each command declares its own bounded create-only depfile output.
The existing v3 executor observes and pins that output with the object before
allowing later commands to consume either. `-MD` includes system headers;
`-MMD` would silently omit part of the actual preprocessor input set. `-MQ`
quotes targets whose attempt directory contains spaces. No compiler, configure
script or target is executed during recipe generation.

The dependency-recipe manifest binds the original recipe and manifest hashes,
new recipe hash and complete command/source/object/depfile mapping. It keeps
build, immutable custody, configured closure and production claims false.

`compare_compiler_dependencies` takes independently pinned recipe and retained
output-inventory bytes, exact source/toolchain/work roots from the original
attempt and every retained depfile's actual bytes. It does not read current
paths or acquire trust from a caller digest. Each depfile must match the
retained output size/digest and its original command's fixed capture arguments.
Every original command output must be present; missing or additional records
refuse. The single target must equal the original object, and the original
translation unit must occur among the prerequisites.

The parser handles clang/GCC make escaping, dollar escaping, spaces and line
continuations. Variables, extra/phony rules, comments, malformed escapes,
duplicates, oversized content and ambiguous paths refuse with fixed codes.
Every dependency must resolve under the original disjoint roots to a declared
source/toolchain input or an output of an earlier command. Ambient system
headers, undeclared Zig cache products, future/self outputs, traversal and
prefix-lookalike paths refuse. Observation of an undeclared compiler-generated
input is a real closure gap; it is not automatically added to the inventory.

The result contains bounded relative references and independent input/output
pins, never private absolute roots or raw compiler prose. It describes retained
compiler bytes only. A depfile is a compiler assertion; it cannot prove that
input bytes stayed immutable during reads, enumerate implicit CRT/linker
libraries, establish build consumption, validate the compiler or grant
installation/production authority. Those existing acceptance tasks remain open.

Validation is centralized after the parallel development freeze: an actual
small local C compile verifies parser compatibility with real depfile escaping;
synthetic prospective recipes exercise the binding and refusal gates. No
upstream CPython, solver, model, remote evaluator or privileged build is run.
