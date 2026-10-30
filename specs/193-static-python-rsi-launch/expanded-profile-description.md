# Expanded fixed-solver installation and startup descriptions

Status: implemented and focused-tested in the 828-node concentrated batch.
Actual build/runtime and production acceptance remain open.

This continuation closes the software gap between the fixed solver source
closure and an installation/startup description. It does not close actual
installation, configured build, immutable custody or production admission. The
old nine-module APIs and their accepted wires stay unchanged. In particular,
an expanded description never passes through the old installation parser.

`static_python_fixed_profile.py` provides a separate, bounded pure parser
`parse_fixed_python_installation` for
`lunar-static-python-fixed-profile-installation-v1`. The exact profile versions
are `fixed-openevolve-v1` and `fixed-shinka-v1`. Mandatory independent caller
pins bind the description, installation version, existing source closure,
complete CPython inventory, configured header, image, generated frozen-header
inventory and native object inventory. The source closure still carries its
fixed producer-manifest pin. Source/header/object descriptions are compared
exactly; a caller must supply every positive generated record. There is no
pending-header placeholder or automatic conversion from a source digest.

The wire contains `schema`, `profile_version`, `installation_version`,
`runtime_closure_sha256`, `source_inventory_sha256`, `configuration`, `image`,
`frozen_modules`, `native_units`, `initialization`, `claims`. Configuration is
the exact `configuration/pyconfig.h` record; image is the exact
`bin/lunar-<solver>` record plus executable mode. Frozen records use
`name,generator_id,package,source,generated`; native records use
`module,source,object,extra_flags`. Source and generated/object records have
`path,size,sha256`. Source size may be zero, as in the official
`Lib/urllib/__init__.py`; generated headers and objects must have positive sizes.
Every native translation unit is retained, including the
separate SQLite amalgamation; it is not treated as a builtin module. Frozen
ordering follows the original closure and native ordering follows its unit
vector. The independently pinned inventory digests cover those complete wire
vectors. The unchanged reviewed isolated preconfig/config values are compared
with exact types. These pins compare descriptions; none is generated from the
current input and then presented as independent authority.

`verify_fixed_python_image` compares supplied actual bytes with the description
and uses the existing bounded static ELF inspector. This observes byte identity
and ELF format only. It does not establish how an image was built or sealed.

`compare_fixed_python_startup` consumes the parsed installation, independently
pinned original startup-v1 bytes and a separately pinned sorted module-origin
inventory. It invokes the existing startup parser, then compares installation
version, executable path/digest/size/mode and independently expected sealed
material. It requires the exact independently reviewed startup-module inventory;
that inventory must use the expanded available frozen/builtin/alias roster.
The supplied inventory is a separately pinned subset of available module-origin
descriptions. This comparison does not establish that a live collector observed
it, nor that it is a complete runtime snapshot. Available modules are never
assumed to have been imported. `__main__` is the
interpreter-created startup module already required by the original profile.
The result exposes immutable installation and module projections for later
accepted-custody/controller/CLI composition; it grants no process ownership.

All nine original preparation/admission claims remain false. Parsing uses only
bounded canonical JSON and performs no filesystem, process, environment,
tool/source import, build or network operation. Errors are fixed context-free
codes. Existing closure JSON uses canonical ASCII plus LF; the new description
and startup module inventory use canonical UTF-8 without a trailing newline,
matching the original startup comparator. Unknown/duplicate fields in the consumed schema and records, mismatched
pins, changed sources, incomplete/duplicate inventories, source/header reuse,
profile mixing and new non-false claims refuse.

This slice explicitly does not emit a build-consumption receipt. Feature189
`candidate-build-provenance.md:110–135` still requires actual enforced immutable
custody and configured input closure before such a receipt can be designed.
No `pyconfig.h` is fabricated, no host Python supplies an accepted runtime, and
production CLI fallback is not enabled. Focused tests use labelled synthetic
header/object/image descriptions; they do not constitute generated build output.

Remaining development is the accepted build/custody consumer, actual generated
header/object/configuration/image evidence, live module-origin collection,
owner/lifecycle/loader-negative acceptance and production controller/CLI wiring.
This parser can represent the independently reviewed 93/103-module inventories;
that capability is separate from executing them successfully.

The six source-analysis annotation lists are opaque here: their list lengths and
aggregate JSON bounds are checked and their exact bytes are bound by the mandatory
closure SHA. This consumer does not revalidate their internal record schemas or
repeat source analysis; successful parsing never asserts complete build closure.
