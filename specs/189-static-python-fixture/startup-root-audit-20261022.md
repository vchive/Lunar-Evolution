# Feature 189 — CPython 3.13.12 startup-root audit (2026-10-22)

## Result and scope

The source-level primary startup roots for the fixed Linux x86_64 GIL profile
are retained as the canonical JSON array in
[`startup-roots-cpython-3.13.12.json`](startup-roots-cpython-3.13.12.json):

```text
["__main__","_frozen_importlib","_imp","_lunar_static_main","builtins","encodings","io","sys"]
```

The exact 94-byte UTF-8 canonical array has SHA-256
`d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313`.
This matches the v2 comparator's independent `expected_startup_roots_sha256`
input. All eight names occur in the fixed 22-name
`expected_startup_modules` inventory. They are direct C-created/imported
modules or the Lunar launcher's explicit application import. The inventory is
the expected final startup set; it is not interchangeable with this root vector.

This is a source-derived root list, not an observed successful startup and not
a complete source import graph. The evidence binds callsites to the pinned
CPython 3.13.12 release-archive members recorded in
[`c-startup-source-audit-20261021.md`](c-startup-source-audit-20261021.md),
plus the checked-in Lunar launcher and the separately pinned expanded frozen
main. The archive/signature custody limits from
[`release-input-audit-20261021.md`](release-input-audit-20261021.md) still
apply; this review did not re-run signature verification or establish that a
configured build consumed the sources.

## Root callsites

| Root | Source and pinned SHA-256 | Source-level entry |
| --- | --- | --- |
| `sys` | CPython `Python/sysmodule.c`, `9767ec9be310810126ae10eb4441ca9f0b40f9f7ab64cd26a036da4867790ca1` | `_PySys_Create()` creates and registers `sys` (lines 3893–3938). |
| `builtins` | CPython `Python/pylifecycle.c`, `21296f86275077e4f19234a2c32691ee087fea961c28745770373a6c4ef70789` | `pycore_init_builtins()` calls `_PyBuiltin_Init()` and registers it (lines 803–823). |
| `__main__` | Same pinned `Python/pylifecycle.c` member | `add_main_module()` creates it (lines 2556–2575). |
| `_frozen_importlib` | CPython `Python/import.c`, `4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61` | `init_importlib()` directly requests this frozen module (lines 3173–3192). |
| `_imp` | Same pinned `Python/import.c` member | `bootstrap_imp()` initializes the builtin, then `init_importlib()` inserts it (lines 3114–3154, 3194–3205). |
| `encodings` | CPython `Python/codecs.c`, `910a58613c8332b1afa6c006595c536ca5ffa56845e65b3cf78b9e32219d511b` | `_PyCodec_InitRegistry()` directly imports it (lines 1501–1509), called by `_PyUnicode_InitEncodings()` in `Objects/unicodeobject.c` (`77ffa6c7c7407207a531890f95e474c812fa1066bb0f22cd92887cf5717e83c7`, lines 15865–15878). |
| `io` | CPython `Python/pylifecycle.c`, same digest above | `init_sys_streams()` directly imports it (lines 2802–2828); `init_set_builtins_open()` also requests `io.open` (lines 2769–2799). |
| `_lunar_static_main` | Lunar `tools/static_python_fixture/assets/launcher.c`, `79a4462386f54dfe36ea87838523fe652bbc59e72db4505175fd3b6870837735` | The launcher calls `PyImport_ImportModule("_lunar_static_main")` (lines 21–30). The expanded source is separately pinned at 6,794 bytes and SHA-256 `6e6a9e661f50dc1baf5b1e6e1f2a717468f1351d7fc6d534ecae125717e0695d`. |

The importlib external bootstrap is deliberately not a primary caller root:
`_frozen_importlib` requests `_frozen_importlib_external` while installing the
external importers. Likewise, builtin modules fetched by frozen importlib are
transitive edges. This keeps the root definition tied to C/launcher entry
requests rather than promoting every expected module into a root.

The upstream archive's unpatched `Python/import.c` also attempts the optional
`zipimport.zipimporter` lookup in `init_zipimport()`. The fixed source policy
removes the `init_zipimport()` call from `_PyImport_InitExternal`; its observed
candidate postimage is 146,559 bytes with SHA-256
`58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1`, as
recorded in `prepared-source-import-observation-20261021.md` and specified by
`source-preparation.md`. Thus `zipimport` is absent from this target-candidate
root vector because of a planned patched-source disposition, not because the
upstream source has no such request. The postimage has not been bound to a
configured build or runtime; until then this remains a candidate root vector,
not a proven target root set.

## Remaining graph and build gates

The root vector does not close the graph. The prepared-source observer still
reports four unsupported sites: dynamic `exec` in `_frozen_importlib`,
dynamic `compile` in `_frozen_importlib_external`, the `from _codecs import *`
site in `codecs`, and the computed `__import__(name)` in the frozen-main
loader-negative probe. The first two are code-object operations; the `_codecs`
star import needs an explicit reviewed builtin-edge disposition; the frozen
main dynamic import is a bounded negative test, not an admitted source route.
See [`prepared-source-import-observation-20261021.md`](prepared-source-import-observation-20261021.md).

Conditional `warnings`/`site` branches, Windows-only imports, frozen-importer
overrides, the configured builtin table, optional-module discovery, generated
headers, resolved objects/link inputs, and actual module origins remain open.
Consequently this pin may be supplied to the v2 DTO comparator only after a
complete graph has been independently audited; a successful synthetic graph
test still proves only parser consistency. Build, sealed startup, owner and
lifecycle acceptance remain open, and production admission/publication stay
false.
