# Fixed Linux subprocess source profile

Status: source-only implementation candidate, not runtime acceptance.

## Decision before code

The fixed Linux x86_64 CPython 3.13.12 solver source profile preserves standard POSIX process APIs already permitted by the original local producer contract. Feature192 explicitly keeps ordinary pipe/file/fork/thread/broker/grants unchanged. Adding the real finite `_posixsubprocess` translation unit resolves a Linux source dependency; it does not add a host/shell/entrypoint route, execute a process, widen native grants, authorize an arbitrary program, or claim subprocess isolation. The fixed launcher and all existing original process ownership/deadline/guardian gates remain required.

`os.popen` makes standard `subprocess` source reachable in the fixed solver source graph. It is incorrect to treat required `_posixsubprocess` as an absent optional accelerator. Retain the official Python source and required native C unit instead of deleting functional POSIX code.

## Exact source proof

Only complete official Lib/subprocess.py SHA-256 e4049ed91ed101b09b0dc96bbf234f646c1728090d643a474b024276cc2a028c can establish `_mswindows=False`. Verify its actual sole top-level `try: import msvcrt / except ModuleNotFoundError: _mswindows=False / else: _mswindows=True` shape and exactly those two flag stores, plus no deletion or other binding. Verify `msvcrt` is deliberately absent from the finite profile and absent from both the complete available-source names and actual finite builtin table. Unknown, fake, drifted, rebound or changed-guard cases refuse. Do not treat the variable spelling alone as a platform constant. Other modules never inherit this proof.

Preserve functional imports including `_posixsubprocess`, fcntl, select, selectors, pwd and grp. Record the narrow static branch proof separately; dynamic reflection/import closure and runtime reachability remain unverified. Full raw sources remain pinned and unchanged.

## Native inputs

Include the actual official Modules/_posixsubprocess.c as a finite static builtin. Pin its full bytes, directly quoted CPython headers and generated clinic header, then check its `_posixsubprocess` module name, PyInit__posixsubprocess return and SUBPROCESS_FORK_EXEC_METHODDEF relationship. This is a finite direct-input check, not a complete C preprocessor/transitive-header proof. Existing complete source inventories, independently reviewed actual musl pyconfig.h, actual compiler/link closure, image bounds, sealed startup, isolation and lifecycle acceptance are still mandatory. Do not generate pyconfig values or use host headers/interpreters as accepted target evidence.

The concrete recipe independently checks these same pinned native inputs in its own source inventory. A source-closure record cannot silently authorize a missing or replaced native header at the build-consumer boundary.

## Validation plan

Author focused tests for official branch proof, unpinned source/guard/flag drift, fake msvcrt source and builtin, required POSIX imports, actual native source/header/initializer binding, missing native inputs, recipe inventory header drift and all false execution/admission claims. Existing source/config/isolated-runtime negative cases remain required. Package preparation runs AST parsing only, no product imports, pytest, source closure resolution, build, SSH, solver, model or evaluator.

The concrete recipe independently requires the single exact native unit, object,
size, digest and empty extra flags, in addition to every direct input pin. A
re-signed closure cannot substitute or duplicate the POSIX native unit.
