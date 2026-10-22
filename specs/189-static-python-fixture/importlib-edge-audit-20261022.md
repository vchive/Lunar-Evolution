# Feature 189 — importlib bootstrap and loader edge audit (2026-10-22)

## Scope and source identity

This bounded review follows the importlib bootstrap path through fixed CPython
3.13.12 archive members and the five-source preparation policy. It does not
claim that a configured build consumed any candidate postimage. The archive
identity is 22,926,488 bytes, SHA-256
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`. The
inspected members match the hashes in
`c-startup-source-audit-20261021.md`:

| Member | Bytes | SHA-256 |
| --- | ---: | --- |
| `Lib/importlib/_bootstrap.py` | 57,082 | `b84488f731914f6da30607e10f6f8d4c5c2ff7f4b0e913060aa66999c04f6252` |
| `Lib/importlib/_bootstrap_external.py` | 73,219 | `a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae` |
| `Python/import.c` | 146,770 | `4e18922dc31001c24fd9875746881ab407252bddc6bca544f22403d50e493a61` |
| prepared `Lib/importlib/_bootstrap_external.py` | 64,722 | `2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab` |
| prepared `Python/import.c` | 146,559 | `58a5fac8fac5916511f890f3fdd095d817e6f32ab709ebf0ed0becf9328226b1` |

The prepared postimages are exact outputs of the fixed source policy, not
evidence that a freezer or compiler consumed them. This review did not repeat
GPG verification or establish the archive-to-Git-commit relationship.

## Startup path and edge disposition

| Source edge or route | Source evidence | Candidate disposition | Remaining limit |
| --- | --- | --- | --- |
| C startup → `_frozen_importlib` | `Python/import.c:init_importlib()` imports it at line 3184, then calls `_install` at 3208–3209. | Primary source-level root, retained in the pinned root vector. | Configured import table and runtime origin are unverified. |
| `_frozen_importlib` → `_frozen_importlib_external` | `_install_external_importers()` in `_bootstrap.py` imports it at lines 1546–1551. C calls setup from `init_importlib_external()` (`Python/import.c:3222–3231`; `_PyImport_InitExternal():4162–4178`). | Transitive startup edge, not a separate primary C caller root. | Frozen bytes and actual target execution remain unbound. |
| `_frozen_importlib_external` → `_imp`, `_io`, `sys`, `_warnings`, `marshal` | Module-level builtin imports in `_bootstrap_external.py`; the prepared-source AST test records these exact edges. | Fixed startup imports for this profile. | Configured builtin table and runtime module origins remain open. |
| `_frozen_importlib_external` → `posix` | The source selects `posix` outside Windows; the fixed profile targets Linux x86_64. | Candidate Linux edge; `nt` and `winreg` are Windows-only branches and are not added to the target inventory. | Platform configuration and runtime remain unobserved. |
| C startup → `zipimport` | Upstream `init_zipimport()` looks up `zipimport.zipimporter` and tolerates absence (`Python/import.c:4125–4158`); `_PyImport_InitExternal()` calls it at line 4178. | The fixed source-preparation policy removes this call while retaining the helper definition. | Candidate postimage is not bound to a configured object or ELF. This remains a planned disposition, not proven target behavior. |
| `_frozen_importlib_external` → `tokenize` | Deferred import in `decode_source()` at line 818. The normal `SourceLoader.get_code()` route is replaced with immediate refusal by source preparation. | Not part of the ordinary startup route. | Other direct callers of `decode_source()` are not proven unreachable or refused. |
| `_frozen_importlib_external` → `importlib.readers` | Deferred `FileReader` and `NamespaceReader` imports at lines 1222 and 1452. | Outside ordinary startup; candidate `_install` does not register file/path importer hooks. | Direct resource-reader calls are not proven unreachable or refused. |
| `_frozen_importlib_external` → `importlib.metadata` | Deferred `MetadataPathFinder` imports at lines 1481 and 1582. | Candidate does not register `PathFinder`, which normally provides this path. | Direct calls and all callers remain unverified. |
| File/extension loaders and path finders | Upstream external `_install` adds `FileFinder.path_hook` and `PathFinder`. The prepared `_install` only sets the bootstrap module; `_get_supported_file_loaders()` returns `[]`; seven loader/finder entry points refuse before file or caller callbacks. | Fixed candidate refusal policy, covered by source-preparation tests. | Tests establish source transformation behavior only; target execution and configured table binding remain open. |

The prepared-source observer's 28 edges and four unsupported sites remain
recorded in `prepared-source-import-observation-20261021.md`. This review
classifies the bootstrap edge and loader dispositions but leaves direct
resource-reader and metadata routes unresolved. In particular,
`unresolved_imports=[]` in the AST result means only that syntax-level import
names were statically resolved; it does not establish that all targets are in
the finite profile or every deferred route is unreachable.

## Acceptance boundary

This closes only a bounded source-level importlib review. It does not complete
the full C/Python source graph, configuration gates, generated frozen tables,
toolchain/link closure, ELF, sealed startup, owner, or lifecycle acceptance.
No source was executed and no build, evaluator, solver, WebAgent, or company
platform was run. `production_admission=false` and `online_publication=false`
remain unchanged.
