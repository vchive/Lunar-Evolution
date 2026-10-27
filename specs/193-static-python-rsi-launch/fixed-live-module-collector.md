# Fixed live-module callable and detached comparison

This slice provides an explicit source-preparation opt-in,
`live_modules_profile="fixed-live-modules-v1"`, for the two fixed expanded
solver profiles. The default frozen main remains byte-for-byte unchanged.
The selected main retains the existing `_rsi_launch` implementation and embeds
`_lunar_collect_live_modules(manifest_sha256)`. Selection changes the source
closure digest and therefore requires a separately built image.

The callable returns bounded canonical ASCII JSON plus LF. It does not write
stdout, files, a broker request, the solver reply, or an inherited descriptor.
The existing launcher does not automatically call it. A separately reviewed
in-image caller and trusted observation sink are still needed before this
becomes a launch-time collection path. No C launcher or old nine-module API
changes are included.

The callable imports only `_imp`, `_sha2`, `posix`, and `sys`, then captures the
entire bounded `sys.modules` table, retaining the original module references.
It refuses unknown names, `None` or foreign values, unreviewed aliases, source
or extension origins, unexpected loader identities, altered isolated flags,
nonempty path loaders, dynamic loader entry points, and available-module roster
drift. It checks the original table keys and object identities again before
returning. Available frozen/builtin inventories remain separate from modules
actually present in the table.

CPython 3.13.12's `FrozenImporter._fix_up_module`, `find_spec`, and
`create_module` synthesize `__file__` while `ModuleSpec._set_fileattr` remains
false. These paths are metadata, not evidence of a filesystem source import.
This fixed profile requires `/lunar-static-fixture` as `sys._stdlib_dir`, the
exact original name supplied by the generated C frozen table, the exact
`SimpleNamespace(filename, origname)` loader state, and the exact package paths.
Bootstrap originals are `importlib._bootstrap` and
`importlib._bootstrap_external`; other frozen originals are their canonical
names. Runtime aliases share the canonical module object. Arbitrary `.py`
paths, mismatched state, or extension/source loaders still refuse. Builtin and
interpreter entries must retain no file or package path.

The core `_frozen_importlib` bootstrap runs before `_PySys_UpdateConfig` adds
`sys._stdlib_dir`, so its loader-state filename remains `None`. Before the
public `importlib._bootstrap` alias is published, its `__file__` is also absent;
after that alias is published, official `importlib.__init__` sets the exact
synthetic bootstrap file without changing loader state. The collector handles
these two precise stages separately. `_frozen_importlib_external` and subsequent
frozen imports run after configuration and retain their synthetic filenames.

The metadata rule follows the pinned source in
`tests/fixtures/static_python_source/Lib/importlib/_bootstrap.py.source`,
`Python/import.c.source:find_frozen`, and the fixed `ALIASES`/frozen tables.
Official `Lib/importlib/__init__.py` changes bootstrap aliases' `__name__` and
`__file__` to these same fixed synthetic paths. `_setup`, `_spec_from_module`,
`_init_module_attrs`, and the `ModuleSpec` constructor establish the builtin
loader, origin, false file-attribute flag and empty loader state. No supplied
upstream source is imported or executed to prepare the collector.

On Linux the image observer opens the fixed kernel magic link
`/proc/self/exe`, hashes the actual held executable FD in bounded chunks, and
checks its identity and metadata before/after, plus the final named identity.
It neither uses `argv[0]` nor accepts a caller-supplied image path. This detects
observation-window drift; it does not establish immutable custody.

`compare_fixed_python_live_modules` reparses the independently pinned expanded
installation description, verifies supplied actual image bytes, and binds the
observation to the exact composed frozen main, startup pins, manifest and image
identity. Synthetic tests exercise whole-table observation, official-shaped
frozen metadata, identity/read failures, expanded 93/103-module descriptions,
and unchanged default launch behavior. These are local fixture tests, not
executions of either expanded static interpreter.

The detached comparison cannot prove that supplied JSON came from the running
callable or that a producer did not omit an optional entry. Its
`live_runtime_authenticated`, `immutable_custody_verified`, and
`production_admission` fields remain false. Accepted build/source consumption,
immutable custody, a trusted launch/sink, and actual static runtime/lifecycle
validation remain separate unfinished boundaries. This slice grants none of
that authority and runs no solver, evaluator, model, or upstream code.
