# Optional compression in the fixed solver profiles

The fixed OpenEvolve and Shinka profiles exchange JSON and candidate source/diff
text; Shinka also uses its explicitly supplied SQLite database. Neither profile
promises compressed archive operations. Do not add bzip2, xz or zlib native
libraries merely because the conservative source scanner visits the optional
archive helpers in CPython's `shutil` and `tarfile`.

Explicitly omit the four public modules `bz2`, `gzip`, `lzma` and `zlib` from
these finite frozen runtimes. Retain their complete upstream input inventory,
but do not freeze those modules, advertise them as builtins, supply a fake
provider or add their native units. Existing local ImportError handlers then
retain CPython's real unavailable-feature behavior. This is a capability choice
for these two profiles, not a statement about the host Python installation.

Every unguarded import of any omitted module still refuses preparation, even
when its source is present in the input inventory. An unguarded `_bz2`, `_lzma`
or other required native dependency also continues to refuse. No parent-try
propagation, general optional-module resolver or function-body pruning is added.
All other functional import bodies continue to be scanned.

Official CPython 3.13.12 `shutil` has its three compression imports in local
ImportError handlers. `tarfile.gzopen` similarly guards `from gzip import
GzipFile`; omitting only `zlib` would instead visit `gzip`'s required unguarded
`zlib` import and correctly refuse. These source facts explain all four public
omissions; they do not authorize suppressing any unguarded import.

Acceptance checks each omitted public module through both guarded and unguarded
imports, retained input bytes, omitted frozen/builtin entries and unchanged
required-native refusal. A fresh real-source scan must still report the actual
next unresolved edge. Source preparation never proves dynamic import closure,
configured headers, compilation, isolated execution, native lifecycle or
production admission. General Lunar host capabilities remain unchanged.
