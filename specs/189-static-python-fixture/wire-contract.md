# G1 pure installation wire contract

This contract is for an externally pinned installation description, not a live
owner, builder, runtime observation or production admission. Its four capability
booleans are always false. No real artifact or source signature is established
by the synthetic parser fixtures.

Only canonical UTF-8 JSON bytes are accepted: sorted object keys, compact comma/
colon separators, no duplicate keys, floats, null, custom objects or noncanonical
encoding. Bytes must be exact built-in bytes, at most262144. Independent expected
descriptor SHA256, installation version and artifact SHA256 are mandatory; no
self-pinning default is available. Names/versions are bounded ASCII, paths are
canonical relative paths (no traversal, backslash or control characters).
Aggregate nodes<=8192, depth<=12 and text<=196608 UTF-8 bytes are checked before
manifest hashing. Artifact size is1..134217728 and installation mode is0555.

The scalar top-level fields are those in data-model.md. Every key is required;
unknown keys refuse. Fixed source CPython3.13.12/GIL and Zig0.16.0 Linux x86_64
profile values cannot be substituted. The source Git tree OID is retained in
source_provenance; source_tree_sha256 refers to a separately retained canonical
sorted file inventory. Signature verification is explicitly not-performed for
this first preparation profile; descriptor parsing does not attest authenticity.

All source/object/archive records have exact fields path, sha256 and size.
Their sizes are bounded to1GiB. Vectors are unique and sorted by path/name;
patches<=32, toolchain executables<=16/archives<=256, link inputs<=256,
embedded startup arrays<=32, frozen/builtin/alias inventories<=128. Nonempty
input vectors are required. The first candidate has exactly9 frozen modules,
19 builtin names and2 aliases from the source closure report. Module source and
generated/object records are independent, mandatory, nonempty byte hashes.

Nested records have these exact fields:

- source_provenance: upstream_url, source_tag, source_commit, source_git_tree,
  annotated_tag_object, archive_url, acquisition, signature_verification,
  source_archive_sha256, source_tree_sha256, patches.
- toolchain: profile, archive_url, archive_sha256, version, target, llvm_version,
  musl_version, libc_disposition, executables, sysroot_manifest_sha256, archives,
  patch_manifest_sha256. The libc disposition states musl backports and Zig-libc
  replacements, rather than claiming a pure upstream musl distribution.
- recipe: configure_flags, compile_flags, link_flags, environment, generated_config_sha256,
  module_config_sha256, link_inputs, link_map_sha256, reproducibility. Environment
  entries contain name/value and only explicitly named build variables are allowed.
  No runtime build or subprocess API is part of the parser.
- generator: python_version, host_architecture, source_sha256, recipe_sha256,
  executable_sha256, marshal_version, generated_manifest_sha256.
- embedded_startup_arrays: a list of name/source/generated/disposition records;
  empty for the candidate that removes embedded getpath Python code.
- frozen_modules: name, is_package, table, source, generated. Only encodings is
  a package; bootstrap/stdlib/custom table assignments are fixed.
- builtin_modules: name, init_symbol, source, object. NULL is an explicit string
  symbol for the C-created builtins/sys entries, not a missing record.
- aliases: alias/name records for the two fixed importlib aliases.
- initialization_profile: preconfig, config, expected_startup_modules,
  external_loader_policy, dynamic_loader_policy, separate_startup_code.
  Full public Linux GIL PyPreConfig/PyConfig fields are frozen in the parser;
  NULL pointers use the literal string NULL. Startup names remain expectations
  until actual runtime acceptance. No ambient path or locale fills a value.
- elf_profile: the complete immutable projection returned by the pure ELF
  inspector, including artifact hash/size, finite table counts and false claims.
  These declarations must later be compared with actual image bytes, rather than
  treating the JSON as an ELF inspection result.

Top-level patch_set_sha256 hashes canonical patches; recipe/toolchain/initialization/
frozen/builtin/alias digests hash their exact canonical nested records; link_manifest_sha256
hashes canonical link_inputs. Source archive/tree and artifact digests are cross
checked with their repeated nested projections. The parser cannot prove bytes
that are not provided, and never fabricates a generated/executable digest.
