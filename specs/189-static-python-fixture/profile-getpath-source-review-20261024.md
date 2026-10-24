# Candidate configuration and path API source review

Status: source/header compatibility reviewed against the official CPython
3.13.12 archive. No field or API incompatibility was found. This is not a
configured build, compiler check or observation of effective runtime settings.

The independent review reads ten C/header members from the locally retained
archive into memory. Each member matches the previously pinned complete
extraction manifest. No archive member is extracted, imported or executed.
For the candidate Linux GIL/nondebug/nonstats profile, all ten PreConfig and
66 PyConfig fields exist with the expected types; the C literal assignments
match the repository's `profile.py`. Conditional fields for other target
profiles are explicitly outside this review.

The reviewed candidate files are:

| Candidate | Bytes | SHA-256 |
| --- | ---: | --- |
| `assets/profile.c` | 3,452 | `3a4b2cbdb57322820aef04aaf55b92a9e085db52818f7cee4e48c33bb5ae98db` |
| `assets/getpath.c` | 1,288 | `a067fe6dc9a2bd63d5847e29b14c9b7c30d42432dcf1f505bb461feae6b2d722` |
| `profile.py` | 6,432 | `6af684014adb22b2619e51bfcae68a5ffb87e56006f965fca3f0fd1f5f1695b4` |

## API semantics checked

The report retains 28 source anchors, each with member size/hash, exact line
range and snippet hash. The principal checks are:

- `Include/internal/pycore_initconfig.h:149–154` defines isolated initialization
  kind as 3. `Python/preconfig.c:333–345` and `Python/initconfig.c:896–916`
  implement the two isolated initializers used by the candidate.
- `Python/initconfig.c:921–940` handles `PyConfig_SetString(..., NULL)` by
  freeing the old value and installing NULL. The candidate's explicit clears
  are supported by this source.
- `Python/initconfig.c:517–547` clears a zero-length wide-string list and
  duplicates nonempty list elements. The public setter at 3016–3029 uses those
  semantics; the candidate's local argv array does not become a retained
  pointer to stack storage.
- `Python/pylifecycle.c:1055–1057` and 1112–1119 cover prior preinitialization
  and copying the supplied configuration before reading it.
- `Python/initconfig.c:2156–2204` contains both path-hook phases and the
  frozen-module flag handling. `Python/pathconfig.c:173–195` handles an
  explicitly empty search list. The custom hook's signature matches its
  internal declaration.

These are source-level relationships. They do not prove that any candidate
binary uses these functions or attains the proposed path, UTF-8, locale or
stdio state.

## Configuration requirements still open

`PYMEM_ALLOCATOR_PYMALLOC` and its implementation require `WITH_PYMALLOC`.
The candidate configure argv contains `--with-pymalloc`; the actual generated
`pyconfig.h` and role flags have not been checked. The custom getpath's
internal include also requires `Py_BUILD_CORE` and the correct include roots.
Actual target GIL/debug/stats flags remain configured-build evidence obligations.

The path-hook declaration is in `pycore_initconfig.h`; the current custom file
includes `pycore_pathconfig.h` and defines the matching function directly. This
is not a demonstrated C error, so the review makes no source change. The
eventual compiler's missing-prototype/warning policy must be checked.

The configured recipe must consume these exact candidate bytes, exclude stock
`Modules/getpath.o`, resolve all symbols and generated inputs, and retain
compiler/linker/freezer/ELF evidence. Effective preconfig/config, module/path
inventory and negative behavior must then be observed on the actual image.
None of those build/runtime gates is closed by this review.

## Retained review

The ignored local evidence directory is
`.lunar-evolution/validation/feature189-20261024/profile-getpath-source-review-1sq96wwj/`.
The report includes all ten member pins, 28 anchors, field coverage and the
separate configured/runtime requirements. Archive SHA-256 is
`2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593`.

| Evidence | SHA-256 |
| --- | --- |
| `source-compatibility-review.json` (46,214 bytes) | `1cc3302117205d9b5a5df072b91e640889860bada8a90ea1781db576cc1c92b8` |
| Independent `review.py` | `37c05a1e3238ee777550fad279d742fd6563e1ec7efe4e4a1a2a4f6e53d4115f` |

No new execution, build, runtime, protection or admission claim is enabled.
