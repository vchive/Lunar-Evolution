# Feature 189 — pinned Python AST import observations

Status: bounded provider-free scanner contract and synthetic implementation.
This is a tool for observing a caller-selected set of source bytes. It is not
the independent CPython source audit, a complete import graph, or evidence that
any source bytes came from the declared installation.

## Purpose and boundary

The startup-closure DTO in `startup-closure-contract.md` compares a supplied
module graph with a fixed installation profile. This scanner fills a narrower
gap: it reads no path and observes Python import syntax directly from exact
caller-supplied source bytes, each bound by an independently supplied digest.
It does not compare to or extend the Feature 189 profile.

The scanner accepts only a mapping from module labels to exact built-in `bytes`
and a second mapping with one externally supplied SHA-256 pin for every exact
source key. It parses a bounded UTF-8 Python subset with `ast.parse`; it never
executes source, imports a target, calls a codec registry, reads or writes a
file, accesses the environment, starts a process, or uses the network. A passing
digest check means only that the supplied bytes match the supplied pin. It does
not authenticate the source or the person who supplied either value.

This scanner's output is explicitly an **AST import observation**. A static
import target can be recorded even when no bytes for that target were supplied.
That behavior is intentional: this API does not require a source closure and
does not say that the target is part of the current installation. For
`from package import member`, the base package/module edge is observed; an
additional possible submodule edge is emitted only if the exact corresponding
source key was supplied. It does not decide whether the member is instead an
attribute at runtime.

Package context for relative imports is explicit. A package initializer is
represented by a source key ending in `.__init__`, such as
`pkg.sub.__init__`. The canonical import name for that source is `pkg.sub`.
The scanner does not infer package status merely because another dotted source
name exists. Relative imports that lack an explicit package initializer context
are retained as unresolved observations.

## API and result wire

The API is:

```python
audit_static_python_imports(
    sources: dict[str, bytes],
    *,
    expected_source_sha256: dict[str, str],
) -> StaticPythonImportAudit
```

Both mappings must be exact built-in dictionaries. Their keys must be the same
bounded module-name strings, and every source value must be exact built-in
bytes. Digest pins are lowercase SHA-256 strings and reject all-zero/all-`f`
sentinels. The scanner checks all mapping shapes and source bounds before
hashing or parsing. A changed source byte, missing/extra digest key, custom
mapping, malformed name or invalid pin has a fixed context-free refusal code.

The immutable result holds only canonical wire bytes and count metadata; its
`to_dict()` method returns a detached copy. The wire schema is
`lunar-static-python-import-audit-v1`, with exact fields `schema`,
`evidence_scope`, `sources`, `imports`, `unresolved_imports`,
`unsupported_import_sites`, and `claims`. It contains source names and their
verified-against-caller-pin digests, but never source text. The wire uses sorted
keys, compact JSON, ASCII output and sorted/deduplicated observations. All claim
fields are fixed false, including source-graph verification, configured closure,
build, runtime startup, installation acceptance and production admission.

Each import observation is `{source, target, kind}`. Kinds are `import`,
`from-import` and `literal-import`. `source` is the canonical import name of
the source bytes. `target` is the statically named target, regardless of whether
its bytes were supplied. Repeated identical AST edges collapse to one edge.

Unresolved and unsupported observations have exact fields `{source, line,
column, reason}`. Locations use one-based source line and zero-based AST column.
Reason values come from fixed enums in the implementation; source text,
exception strings, paths, credentials and caller-controlled error context are
never retained.

## Static resolution and unsupported syntax

Ordinary `import` statements produce one edge for each named import. Absolute
`from-import` statements produce an edge to the base module. Relative
`from-import` names are resolved only from the source module's explicit package
initializer context. A supplied source key for a possible `package.member`
module adds a second `from-import` edge; no unprovided member name is guessed to
be a module.

Simple literal calls to `__import__("absolute.name")` and
`importlib.import_module("absolute.name")` produce `literal-import` edges.
`importlib.import_module` also supports a literal relative name when its package
argument is a literal string whose package initializer source was supplied.
Other call shapes or non-literal names are retained as `dynamic-import`
unsupported sites. Invalid literal module names and relative imports without a
resolved package context are retained in `unresolved_imports`. Star imports
retain their base edge and an unsupported `star-import` site. Calls to `eval`,
`exec` or `compile` are retained as `dynamic-code-execution` unsupported sites.

This is a bounded syntax observer, not a Python name-binding or execution
analysis. It does not resolve arbitrary aliases, `getattr`/`sys.modules`
manipulation, custom import hooks, C-created imports, extension loaders, or
runtime-built code. The unsupported records cover the fixed syntactic forms
listed above; an empty unsupported list does not prove that no other dynamic
import mechanism exists. The independent source review required by `tasks.md`
must separately audit C import sites, bootstrap aliases, literal imports and
dynamic-import refusal sites against the selected CPython release.

## Fixed bounds and refusals

V1 bounds are 1–256 source modules, 256 KiB per source, 4 MiB aggregate source
bytes, 20,000 AST nodes per source, 100,000 total AST nodes, depth 128, 2,048
import/call sites and 256 KiB output. Exceeding a bound refuses the whole call
with a fixed `budget` code; it never returns a partial graph. Syntax errors,
unsupported source encodings, malformed input shapes, pin drift and output
serialization failures also refuse with fixed codes. Dynamic and relative
resolution gaps that can be represented as observations are returned in the
wire rather than silently omitted.

Only UTF-8 (including an optional UTF-8 BOM and an explicit UTF-8 coding cookie)
is accepted. Other Python source encodings refuse before AST parsing. This
deliberately bounded subset avoids consulting process-global codec search hooks.

## Focused validation

Tests use only synthetic in-memory sources and independently computed source
pins. Cover ordinary, from-, relative- and literal-import observations; explicit
`pkg.__init__` package context; possible submodule edges only when pinned bytes
are supplied; dynamic/star/code-execution unsupported records; unresolved
relative and malformed literal names; digest/key/type/canonical-wire behavior;
fixed refusal reasons; every size/depth/node/site/output bound; detached DTO
results; and no execution, file, process or network activity.

The scanner's test oracle checks only the syntax observer contract. It must not
label synthetic sources as CPython source, claim that import enumeration is
complete, infer profile compatibility, or mark source graph/installation/runtime
verification true. Independent CPython source review and actual build/startup
remain separate Feature 189 gates.
