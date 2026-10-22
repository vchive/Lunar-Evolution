# Feature 189 — bounded startup import-closure comparison contract

Status: provider-free DTO parser and synthetic focused tests implemented. The
independent source audit that would establish a real import graph remains open.
This does not establish a complete CPython import closure, a build, startup,
loader refusal, ownership, runtime acceptance, or production admission.

## Purpose and existing contracts

The current contracts cover adjacent but different facts:

- `static_python_installation.py` validates the fixed installation profile,
  the complete frozen/builtin/alias inventories, initialization fields, and
  expected startup module names.
- Feature 193 F02 in `build-closure-contract.md` compares the nine reviewed
  frozen headers, static-link projection, and declared ELF projection against
  the installation contract. It does not encode module-to-module import edges.
- `python_fixture_observation.py` and
  `python_runtime_observation_policy.py` validate the fixed module names and
  origins in a runtime observation. `static_python_runtime_startup.py` validates
  a separate launch/lifecycle DTO. This contract does not replace or widen
  those wires.

The remaining bounded comparison gap is a canonical representation of the
expected startup-module inventory, separately source-audited graph roots, each
root's transitive import edges, and the permitted static route for every
reached module. Version 2 separates those concepts because treating every
expected module as a root makes reachability vacuous. A successful parse can
say only that this supplied graph is bounded, internally consistent, matches
its independent pins, and fits the already pinned installation inventory. It
cannot prove the graph or root list is complete or truthful; source review and
later actual startup remain separate gates.

Do not modify the current profile to make a graph pass. The frozen inventory
remains exactly these nine names: `_frozen_importlib`,
`_frozen_importlib_external`, `_lunar_static_main`, `abc`, `codecs`,
`encodings`, `encodings.aliases`, `encodings.utf_8`, and `io`. The builtin
inventory remains exactly the 19 names fixed by `static_python_installation.py`
(`_abc`, `_ast`, `_codecs`, `_imp`, `_io`, `_lunar_fixture_pipe`, `_signal`,
`_string`, `_thread`, `_tokenize`, `_warnings`, `_weakref`, `atexit`,
`builtins`, `faulthandler`, `gc`, `marshal`, `posix`, and `sys`). The two
aliases remain `importlib._bootstrap` → `_frozen_importlib` and
`importlib._bootstrap_external` → `_frozen_importlib_external`.

In particular, `operator` is not added because a separate diagnostic image
failed to import it. The retained 5090gpu probes describe different artifacts
and are diagnostic only. Any later candidate that needs a different module set
requires an explicit profile/version revision and new independent pins; this
DTO must refuse the drift.

## API and independent pins

Implement a pure parser with this interface:

```python
parse_static_python_startup_closure(
    raw: bytes,
    *,
    installation_descriptor_raw: bytes,
    expected_closure_sha256: str,
    expected_startup_roots_sha256: str,
    expected_installation_descriptor_sha256: str,
    expected_installation_version: str,
    expected_artifact_sha256: str,
    expected_source_tree_sha256: str,
    expected_patch_set_sha256: str,
    expected_initialization_profile_sha256: str,
    expected_frozen_inventory_sha256: str,
    expected_builtin_inventory_sha256: str,
    expected_alias_inventory_sha256: str,
) -> StaticPythonStartupClosure
```

The API requires ten independent SHA-256 pins: closure, source-audited startup
roots, installation descriptor, artifact, source tree, patch set,
initialization profile, frozen inventory, builtin inventory, and alias
inventory. Each is an exact built-in
`str`, lowercase SHA-256, and rejects all-zero/all-`f` sentinels. The separate
installation version is a bounded ASCII label. The parser
reparses `installation_descriptor_raw` through the unchanged
`parse_static_python_installation_descriptor` using its independent descriptor,
version, and artifact pins. It then checks that the explicit source, patch,
initialization, frozen, builtin, and alias pins equal the corresponding fields
in that validated descriptor. No expected value may be selected from the graph
wire or derived from its self-digest.
`expected_closure_sha256` is the independently supplied SHA-256 of the exact
canonical `raw` bytes; it is not a field that the wire may use to self-pin.
`expected_startup_roots_sha256` hashes the canonical JSON array of the separately
reviewed graph-root names. The digest must come from the source-audit process;
computing it from an unreviewed graph does not establish root correctness.

The API performs no filesystem, process, network, environment, compiler,
freezer, ELF, or runtime operation. It accepts no live owner or callback. A
frozen slots DTO retains only canonical wire bytes and fixed comparison
metadata; `to_dict()` must return a detached mutable copy.

## Canonical wire

Schema: `lunar-static-python-startup-closure-v2`. Accept only exact built-in
UTF-8 `bytes` in canonical JSON form: sorted object keys, compact separators,
no trailing newline, and no duplicate keys, floats, non-finite values, nulls,
custom collections, or unknown fields. Enforce byte/type limits before JSON
parsing, hashing, or descriptor parsing. Use fixed context-free refusal codes.

The exact top-level fields are:

```text
schema, evidence_scope, installation_version,
source_tree_sha256, patch_set_sha256,
initialization_profile_sha256, frozen_inventory_sha256,
builtin_inventory_sha256, alias_inventory_sha256,
expected_startup_modules, startup_roots, modules, import_edges, unresolved_imports,
unsupported_import_sites, claims
```

`evidence_scope` is exactly `synthetic-dto-comparison-only`. The wire's
`installation_version` and six digest fields equal their independent
arguments and corresponding validated installation descriptor fields. The
closure pin hashes the exact `raw` bytes; the descriptor pin hashes the exact
descriptor bytes; and the artifact pin is checked by the unchanged descriptor
parser. Those three pins are external arguments, not extra graph-wire fields.

`expected_startup_modules` is a sorted list exactly equal to the descriptor's
`initialization_profile.expected_startup_modules`. It preserves the fixed
expected module inventory. `startup_roots` is a separate sorted, unique list
of reviewed graph entry modules. Its canonical JSON SHA-256 must equal the
independent `expected_startup_roots_sha256` argument. Every root must occur in
the expected inventory, and roots must be a proper subset so the graph must
demonstrate at least one dependency edge. The list must be nonempty and contain
at most 64 names. This parser checks the supplied root digest; it does not audit
how the roots were selected.

`modules` is a sorted unique list of exact records `{name, route, target}`.
Records are sorted by `name`. Names are bounded ASCII dotted module labels.
`route` is one of `frozen`,
`builtin`, `alias`, or `interpreter-created`:

- `frozen` names must occur in the descriptor's existing frozen inventory.
- `builtin` names must occur in its existing builtin inventory.
- `alias` names and their nonempty `target` must exactly match its existing
  alias inventory; the target is the canonical module name and must itself
  resolve to a `frozen` module record.
- `interpreter-created` is permitted only for `__main__`, with `target=""`.
- Every non-alias route has `target=""`. File, zip, extension, host, ambient,
  or otherwise unrecognized routes are not representable and must refuse.

`modules` must contain exactly every expected startup module and every fixed
bootstrap alias from the descriptor. No module name may have more than one
route. Module references must resolve to exactly one listed module record;
unknown targets are refused even when they are familiar stdlib names. In
particular, parser code must not infer an inventory addition from a missing
target such as `operator`.

`import_edges` is a sorted unique list of exact records
`{source, target, kind}`. Both endpoints refer to listed modules. `kind` is one
of `import`, `from-import`, `literal-import`, or `bootstrap-alias`. For every
edge, `source` is the importing module. For a `bootstrap-alias` edge, `target`
is the alias module name; that alias's module record then names the canonical
frozen module in its own `target` field. The edge's `source` must equal that
canonical module name and resolve to a `frozen` module record. The source,
alias edge target, and alias record target must all agree with the descriptor's
fixed alias mapping. The edge target is not the canonical module name directly.
Every non-root module must be reachable from one or more separately pinned
startup roots through the directed edge list. Edges from unreachable sources
and unreferenced module records refuse. This is only a consistency check over
caller-supplied edges; it does not extract imports from source or prove that
the selected roots or edges are complete.

`unresolved_imports` and `unsupported_import_sites` are required empty arrays.
Their presence makes incompleteness explicit rather than silently treating an
unknown import or runtime-selected module as absent. A source audit that finds
an unresolved dependency, non-literal dynamic import, external loader route, or
unreviewed module cannot produce an accepted v2 graph. A literal import is
allowed only when the source-review process independently fixes its module
name and represents it as a `literal-import` edge.

`claims` has exactly these boolean fields, all exactly `false`:

```text
source_graph_verified, configured_closure_verified, build_performed,
runtime_startup_performed, loader_policy_verified, owner_verified,
installation_accepted, runtime_load_protection,
general_code_origin_protection, production_admission
```

The parser reports comparison success, not any of these claims.

## Bounds and refusal behavior

Freeze these v2 parser limits:

- raw DTO: at most 256 KiB; installation descriptor: its existing 256 KiB
  bound;
- decoded object: at most 8,192 nodes, depth 12, and 192 KiB aggregate UTF-8
  text, including keys;
- expected startup modules: the exact descriptor list; startup roots: 1–64 and
  a proper subset of that list; module records: 1–256; import edges: 0–2,048;
- unresolved/unsupported-site arrays: 0–256 entries each, and accepted only
  when empty;
- module names: 1–128 ASCII bytes; route/kind labels use fixed enums;
- module records are sorted by name; edges are sorted by
  `(source, target, kind)`; duplicates refuse.

Reject booleans where integers are expected, subclasses/custom containers,
malformed UTF-8, surrogates, excess depth/nodes/text, unknown fields, duplicate
keys, noncanonical encodings, sentinel pins, descriptor mismatch, inventory
drift, missing roots, unknown route/edge endpoints, alias mismatch,
unreachable nodes, unresolved imports, unsupported import sites, or any true
claim. Errors use fixed reason codes only: no paths, source text, stderr,
credentials, or parser exception context are retained.

## Focused validation requirements

Use only synthetic in-memory vectors. A positive vector must be labelled
synthetic and demonstrate the exact expected-module inventory, a separate
proper-subset root vector with its independent hash, routes, aliases, graph
reachability, detached immutable output, and false claims. It must not present
the synthetic roots as the real CPython roots.
Negative cases must cover:

- every mandatory pin missing or mismatched, and installation descriptor
  canonical/profile/inventory mismatch;
- changed, missing, extra, unsorted, duplicate, all-module, or incorrectly
  pinned startup roots;
- a new module target such as `operator`, unknown builtin/frozen/alias routes,
  conflicting route assignments, alias-target drift, and external loader
  route attempts;
- missing roots, missing edge targets, unreachable nodes, duplicate/unsorted
  edges, invalid edge kinds, unresolved imports and unsupported dynamic sites;
- duplicate JSON keys, noncanonical bytes, unknown fields, invalid UTF-8,
  depth/node/text/wire limits, boolean/type substitution, and true claims;
- no filesystem/process/network/environment/compiler/freezer/ELF access and
  fixed errors without caller-controlled context.

The test oracle must not interpret the synthetic graph as proof that the
source's imports were exhaustively enumerated. Existing Feature 189/193 tests
remain unchanged and run as disjoint compatibility coverage.

## Acceptance boundary and sequencing

This DTO is useful only as a fail-closed *comparison* gate for a separately
reviewed import graph. It does not perform the source audit that establishes
the graph's completeness, validate the freezer's actual output bytes, inspect
the configured Makefile or link map, inspect an ELF, launch CPython, or verify
runtime module origins. The existing runtime-observation adapter and policy
remain distinct and unchanged.

Before a concrete graph is considered for this profile, retain a source-level
review that maps each fixed initialization and frozen-source import to a
finite route and explicitly accounts for C-created startup modules, aliases,
literal imports, package-relative imports, and unsupported dynamic imports.
Any discovered dependency outside the current pinned sets is a refusal and a
versioned profile-design decision; it is not automatically admitted. Later
real build/startup evidence still must independently bind the same descriptor,
generated headers, actual image, actual module origins, and original owner/
lifecycle. No SDD DTO or synthetic parser test changes
`production_admission=false`.
