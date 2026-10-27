# Fixed Linux real socket module source profile

## Trigger and scope

The real-source traversal for both fixed solver profiles refused the unguarded `_socket` dependency in official CPython 3.13.12 `Lib/types.py:340`. This is a function-local import in `types.__getattr__`, executed when the public lazy attribute `CapsuleType` is requested. Plain `import types` does not itself execute that branch. `types.__all__` also publishes `CapsuleType`. The conservative closure resolver retains functional function bodies and must preserve this dependency rather than inventing an eager-import claim, deleting it or returning a substitute capsule type.

Retain the unchanged official `types.py`, the real static `_socket` builtin and its real `_socket.CAPI`. CPython's `socket_exec` constructs this C API with `PyCapsule_New`, then publishes `PySocket_CAPI_NAME`. No fake `_socket`, Python shim, host import, CapsuleType constant substitution or new branch-pruning exception is allowed.

## Capability boundary

The original producer isolation still refuses `socket`, `connect`, `bind`, `listen`, `accept`/`accept4` and multiplexed `socketcall`. Existing narrowly allowed AF_UNIX `socketpair`, ordinary local pipe/file/fork/thread, broker and descriptor policies remain controlled by the original native gates. This source-profile extension changes none of those rules or grants. Static availability of a Python module does not confer a syscall permission, host network route or process lifecycle acceptance.

Official Linux `_socket` initialization selects its non-Windows `os_init`, which returns success without creating a network connection. This is source inspection only. It does not constitute target-runtime execution, complete egress proof or native-isolation acceptance. `_ssl` remains absent; no SSL, crypto, DNS library, host header or host library grant is added. Original sealed startup, ownership, deadline and guardian gates remain mandatory.

## Finite native input contract

Pin the complete official `Modules/socketmodule.c` translation unit and every directly quoted CPython/clinic input in that unit and its generated clinic header. This includes `socketmodule.h`, `addrinfo.h`, direct internal headers and both conditional embedded fallback C files `getaddrinfo.c` and `getnameinfo.c`; their presence does not assert that either preprocessor branch is active. All pins derive from the independently pinned official archive, not a caller-generated source substitution.

The runtime closure checks each exact size and SHA-256 before resolution and checks the real module initializer, execution slot, clinic constructor relationship and C API capsule publication. It emits the real `PyInit__socket` finite builtin. The concrete recipe independently checks the original source inventory for every pin and requires exactly one unchanged socket C unit/object/size/digest with no extra flags. A re-signed closure wire cannot substitute a different unit, extra flags or duplicate socket unit. The recipe retains its existing static musl compiler/link contract.

This is a finite direct-input check. It does not prove complete transitive headers, C preprocessing, external symbols, configuration or source closure. The actual independently reviewed CPython/Zig/musl `pyconfig.h`, bundled musl/Linux headers and native static link must still be verified with original evidence. Do not fabricate `HAVE_*` settings, use host headers/libc or add `-lnsl`, `-lresolv`, `-lssl` or `-lcrypto` to evade a real build refusal. If actual configuration or link dependencies cannot be met, retain the failure as an open blocker.

## Validation and claims

Candidate tests cover the actual lazy CapsuleType import shape; retained real C API unit and unchanged Python source; complete direct quoted/clinic input inventory; missing/drifted inputs; module/capsule/clinic anchor substitution; independently re-signed recipe input/unit drift; unchanged configuration input and false build/runtime/admission claims. Existing unknown-source, `_ssl` absence, configuration and isolated-runtime negatives remain required.

This candidate package is prepared without importing product or upstream modules, invoking source closure, pytest, build, SSH, solver, model or evaluator. Root owns integration review and actual focused/static acceptance. Source and build/runtime acceptance remain distinct; no CI, production, successful solver or merge claim is made here.
