# Actual consumer: finite explicit command/input graph

## Problem and scope

The existing dependency capture plan identifies C compilations and two static
links. It previously ignored other executable commands and did not classify
every compiler option. The actual dependency consumer could therefore dispatch
an additional pinned helper or an unreviewed driver/configuration option before
eventually comparing the recognized depfiles.

The consumer now performs a finite command/input preflight after the existing
recipe/capture/manifest validation and before the execution runner, workspace
creation or tool dispatch. This is executable refusal behavior on the actual
consumer path, not a separate report parser or a new acceptance claim. The
generic v1/v2/v3 runners and original recipe generators are unchanged.

## Allowed command graph

Every command must be one of these forms, in its original stage:

- Pinned Zig `cc` compilation in configure/freeze/compile, with one original
  source, one object, the exact compiler depfile suffix, and its two declared
  non-executable outputs.
- The existing reviewed Zig static-link grammar in freeze/link, consuming prior
  object/archive outputs and declaring exactly its executable and linker depfile.
- One Zig `ar rcsD` command in link, consuming prior non-executable objects and
  declaring one non-executable archive under `libraries/`.
- The prior observed `bin/lunar-freeze-module` executable in freeze, with exactly
  a module identity, original source and matching frozen-header output.

Compiler flags are the finite options emitted by the concrete and fixed-runtime
generators, including their existing SQLite/hash module defines. New macros or
flags require a reviewed software change. Each compilation must explicitly keep
the fixed target and pinned Zig resource-directory options; omission cannot fall
back to the host's defaults. Directory inputs must have actual
source/toolchain records or prior work outputs underneath them; a current command
cannot grant itself an input through its output declaration. Command argv values
that introduce unreviewed helpers, response files, config files, plugins, joined
or pass-through flags, or literal external paths refuse. The optional recipe
environment is limited to the existing fixed locale/time/reproducibility values.

All input references retain their declared executable role. The consumer neither
adopts current filesystem digests as new inventory nor discovers approvals from a
driver's output. The original runner still observes the actual generated output
group before granting a later generated executable, compares original and copied
inputs, retains actual reports/depfiles, and keeps the original absolute deadline
and interruption path.

## Limits and verification

This closes the explicit command grammar and declared dependency graph only.
Compiler driver implicit configuration/resources/helpers, inherited FDs, complete
descendant drain and immutable contents/namespace custody remain separate open
requirements. `driver_inputs_verified`, `implicit_link_inputs_verified`,
`immutable_custody_verified`, installation, production and publication claims all
remain false. A manifest pin is an integrity comparison, not authorization of an
untrusted tool or an accepted runtime.

Focused tests cover the real concrete generator's full command graph, actual inert
compile/link/archive/generated-freezer processes and output readback, existing
SQLite/hash defines, and refusals before runner/workspace for unknown helpers,
driver input routes, environment, output groups, archive mode and current-output
directory inputs. These tests use the local C compiler and inert fixture only;
they do not run CPython, a solver, a model, an evaluator, or an old mixed case.

Run the new focused tests with existing actual build-consumer, compiler/linker
capture, concrete-recipe and v3 executor compatibility suites. AST checks alone
are not regression or production acceptance.
