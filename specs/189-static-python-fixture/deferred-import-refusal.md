# Fixed candidate deferred-import refusal

## Problem and boundary

The existing pinned `_bootstrap_external.py` postimage still contains deferred
imports of `importlib.readers`, `importlib.metadata` and `tokenize`. These names
are outside the finite candidate inventory. Ordinary startup does not register
the file/path finders, but direct calls to the retained functions are a separate
source-level route. The 2026-10-22 importlib audit explicitly leaves it open.

Continue Feature189 source preparation with five fixed whole-function
replacements using the existing `lunar_static_external_loader_refused`
`ImportError`. Do not discover or admit extra modules, add a new descriptor,
change the observation wire, or enable configure/build/target execution.

| Fixed function | Required disposition |
| --- | --- |
| `FileLoader.get_resource_reader(self, module)` | Remove its `_check_name` decorator and replace the complete function with immediate refusal, before accessing/comparing/formatting caller-owned names. |
| `NamespaceLoader.get_resource_reader(self, module)` | Refuse before importing a reader or accessing `self._path`. |
| `PathFinder.invalidate_caches()` | Keep `staticmethod`, replace the complete function, and refuse before cache deletion, finder callbacks, namespace epoch mutation or metadata import. |
| `PathFinder.find_distributions(*args, **kwargs)` | Keep `staticmethod` and refuse before metadata import or argument inspection. |
| `decode_source(source_bytes)` | Refuse before `tokenize` import, stream construction or byte decoding. |

These five entry points must refuse for arbitrary supplied objects without
calling their attribute, comparison, representation or decoding hooks. They do
not make every loader function safe: `SourceLoader.get_source` still performs
`get_filename`/`get_data` before calling `decode_source`. Direct file/data APIs,
C/runtime enforcement, target consumption and a complete import closure remain
separate open obligations. Do not claim a general Python sandbox.

## Fixed identity transition

Keep the official raw preimage unchanged: 73,219 bytes, SHA-256
`a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae`.
Retain the old prepared 64,722-byte source with SHA-256
`2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab`
as an inert historical fixture. Its old observations and v1 graph continue to
refer to those exact bytes.

Append the five fixed snippet operations in the table order above. The
independent read-only projection expects a 63,208-byte candidate postimage,
SHA-256 `3269c01134c03bf8196306ce6aa89e24da41430ccf3bef7eb43afe362ec1bf1e`.
The complete 18-operation patch vector is expected to have SHA-256
`8ccdc0541b2e0c6e9c2bf251d9dd502d51bdaf27543ceaccccf59df41e10348e`.
Implementation must reproduce these bytes and retain exact occurrence,
whole-preimage and postimage checks. These are candidate source identities,
never evidence of compiler/freezer consumption.

Refresh every active base/RSI build-input, source-plan, overlay/preparation and
detached installation comparison pin affected by that source change. Preserve
historical source/staging receipts, previous codec observation JSON and v1
graph exactly; use retained old bytes when replaying them. Record the current
nine-source scan in a separate observation using the existing observer. It is
expected to have 25 unique edges after removing the three deferred targets;
all unsupported sites remain explicit. Do not rewrite old evidence to appear
to describe the new candidate.

## Implementation and verification tasks

- [x] Add the five exact source replacements and validate independently
  projected whole-file and operation-vector identities.
- [x] Preserve the old prepared source and historical audit replay inputs.
- [x] Refresh the complete active pin chain and current source audit.
- [x] Add meaningful provider-free tests of all five refusals, inherited file
  reader access, removal of the name decorator, unchanged cache/epoch/module
  state and absence of caller callbacks. Execute only isolated repository-owned
  replacement bodies in synthetic contexts, never a complete archived module.
- [x] Retain existing finite profile, original tests and fixed CI groups, with
  an additional zero-skip focused gate for this slice.
- [x] Run affected focused tests, Ruff, compileall and diff-check; independently
  review source/pin/history changes before commit/push.
- [ ] Complete the final commit's Linux focused/source-invariance verification
  and full branch CI before main merge. PR186's current CI failure must be
  resolved separately; this source slice does not replace its acceptance.

Full configured source closure, immutable build custody, generated configuration,
freezing/compilation/linking, ELF, sealed target and production admission remain
open. No real solver, WebAgent, evaluator or company platform is involved.

## Candidate source and dependent identity records

The implementation produces the projected 63,208-byte external source and
18-operation vector above. The PathFinder decorators stay in the original
source outside their body-replacement snippets; actual prepared AST inspection
must still verify both `staticmethod` decorators. FileLoader's name-checking
decorator is part of its removed snippet. Internal snippet boundaries do not
alter the required prepared source behavior.

| Current candidate record | Bytes | SHA-256 |
| --- | ---: | --- |
| Complete source-preparation policy | — | `b8f97a81f60d84ea07b7a008b000229e9221492d88ce6ebc099eb63ff232ff4b` |
| Base reviewed build inputs | 80,050 | `7d1660a9166208c412626fcd8f60cb60124060595643064b353926381565171d` |
| RSI source-plan manifest | 6,706 | `6018846ffcfdaf1d578516043e690cdd01da413d5b885d16d18d537219d79058` |
| RSI profile overlay | 2,456 | `831d9e4625f5e9f6d7b662505bbd811d9ce23b6804a7e9c4172ddbafb77888e6` |
| RSI profile preparation | 73,802 | `cb82e14008c30b3f95c7769f52b7a4005f46d897d93397fc2ae4320fab30a62d` |
| Separate current nine-source AST observation | 3,379 | `50bd394683a86dc0e0421d1e9ab592d153650456c54a23606e166db0c625e7ff` |

These records must be independently checked against the final emitted bytes
before the slice is marked complete. Historical source/staging/graph records
continue to describe their original candidate; the new source identity does
not update any historical staging tree in place.
