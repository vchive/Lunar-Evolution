# Plan

This directory specifies Feature188 only. Implement no code until Feature187's
final-head Linux acceptance. Preserve other work and keep the new API independent
of native admission, selectors and all existing 171/177 wire formats.

## Proposed implementation

`producer_python_runtime_material.py` owns the strict framed format, immutable
detached descriptor, factory-owned live context, materializer and live verifier.
API names are proposed until implementation review:

- `materialize_sealed_python_runtime_material(...)`: consume original tree/pins,
  explicit version and absolute deadline; yield one live sealed bundle.
- `parse_python_runtime_material_descriptor(...)`: pure bounded canonical parsing;
  produce detached evidence without a live FD or filesystem effects.
- `verify_sealed_python_runtime_material(...)`: revalidate original live ownership,
  independent descriptor/frame/version/tree/declared/target pins, seals and bytes.

Reuse Feature177's external-pin and exact-shape boundary, Feature171's file pins
and `DirectoryChain` no-follow reads. Reuse the sealing pattern and negative
fixtures from `linux_executable_binding.py`; do not reuse its executable-only
DTO or its source/mode/size contract for ordinary data.

1. Validate cheap scalar/count bounds and canonical graph semantics before any
   serialization, hash-set work, source read or source path parsing.
2. Reverify the original Feature177 tree with the caller's original pins.
3. Create exactly one owned MFD_CLOEXEC | MFD_ALLOW_SEALING data memfd. Serialize a
   bounded canonical logical table, then copy payloads in canonical file order.
   Stream bytes and digests; do not buffer the complete payload in Python memory.
4. For every source retain a held no-follow parent chain and compare original
   before/opened/after/named stat and digest pins. Refuse links, special files,
   aliases and drift. Reverify the original tree after copying.
5. Reread the complete owned frame and independently validate table, payload
   lengths/digests, total size and all externally retained bindings.
6. Add F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL, check F_GET_SEALS,
   original regular-file identity and size, then verify the sealed frame again.
   Only then yield the live object and detached descriptor.
7. Keep original ownership in the context rather than received JSON. Document
   borrowed-FD use: callers must not close, replace or rebind it. Recheck identity
   before verification and cleanup. Unexpected FD reuse is cleanup_unknown and
   must not cause the factory to close a foreign object.
8. On partial copy/seal, OSError, deadline, KeyboardInterrupt or SystemExit,
   close all still-owned descriptors. Preserve the primary error, report uncertain
   cleanup and never repair source permissions or delete source objects.

A final source recheck remains an observation. If the source changes after it,
the already sealed bytes still retain their original digest; this is the
materialization increment over Feature177's documented tail boundary.

## Local CLI and delivery

An optional local CLI must avoid global home/Store/RSI initialization. It may
materialize, verify, output a detached descriptor/receipt and close its live object
before exit. Its output must state that no live FD survives CLI termination.

A provider-free local static reader fixture may receive a deliberately duplicated
reader FD within the fixture parent's ownership and verify the frame/seals.
This is a separate inert delivery proof, not production native admission.
Do not add that FD to control v2, existing grants or target environment.

## Feature189 dependency, not Feature188 work

A first real Python fixture can freeze its complete minimal main/module/resource
closure into a single fully static CPython target image and use the existing
sealed target FD. A reusable project runtime can instead use static CPython plus
one framed sealed bundle and a native sealed importer. The second shape needs a
new explicit versioned native handoff with original image/bundle ownership,
C seal/frame/pin checks and complete FD census; no silent v2 extension.

The installation must supply a pinned artifact and build descriptor. It must bind
CPython source/patches, compiler/libc/link recipe, frozen generator and tables,
builtin extensions, resources, ELF/ABI and exact image SHA/size. Inspecting static
ELF alone does not prove CPython identity or absence of runtime dlopen.

Freeze initialization encodings, aliases, UTF-8 codec and importlib/bootstrap
before path discovery can run. Use fixed isolated PyConfig and finite builtin/
frozen modules; reject dynamic extensions, ctypes, file/zip imports, venv/site/pth,
unsupported modules and loader fallback. Static libpython with dynamic libc, or
static glibc's unclosed NSS/gconv/dlopen behavior, does not qualify.
The first supported architecture/version is explicit; other platforms refuse.

Actual CPython version/cache_tag/flags, frozen execution, readable import decoys,
source replacement, pipe behavior and native ownership/deadline/cleanup require
separate real Linux acceptance. Feature188 does not perform or claim that work.
