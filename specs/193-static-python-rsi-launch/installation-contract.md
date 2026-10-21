# Bounded RSI marker installation description contract

Status: implemented and locally verified, final-source CI/audit pending, 2026-10-12.
This is a detached description validator for F01, not actual installation
acceptance, build verification, execution or input authority.

## Problem and scope

The existing descriptor validates the original fixed Python initialization and
nine-module inventory, but does not describe its C launcher. The preparation
candidate deliberately leaves generated headers pending. Add a separately tagged
wrapper binding the reviewed marker launcher, source substitutions and complete
generated-header descriptions. Preserve the original parser and all accepted
assets, profiles, overlays and preparation behavior byte-for-byte.

## API and wire

New module `src/lunar_evolution/static_python_rsi_installation.py` exports
`parse_static_python_rsi_installation_descriptor(raw: bytes, *,
expected_contract_sha256: str, expected_descriptor_sha256: str,
expected_installation_version: str, expected_artifact_sha256: str,
expected_frozen_inventory_sha256: str,
expected_main_header_sha256: str) -> StaticPythonRSIInstallationDescriptor`.

All six keyword pins are mandatory and supplied independently of the wire. They
are exact built-in strings; digests are lowercase SHA256 with all-zero/all-f
sentinels refused; the version is an ASCII label of at most128 characters.
The raw argument is exact bytes, nonempty and at most384KiB. Check all types and
bounds before parsing, hashing or caller callback dispatch. Bound decoded
structure to16384 nodes, depth16 and256KiB UTF8 text; reject duplicates,
nonfinite/floating values, null, surrogates and noncanonical JSON.

The exact wrapper fields are `schema`, `profile`, `base_reviewed_inputs`,
`reviewed_overlay`, `source_plan`, `launch_policy`, `launcher`, `descriptor`,
and `claims`. Canonical bytes use sorted keys, compact separators,
ensure_ascii=False and no trailing newline. Schema is
`lunar-static-python-rsi-installation-contract-v1`; profile is
`rsi-marker-launch-v1`. The three input records are exact `{size, sha256}`:

- base80050 / c305d56956b75eda286b0e630ceeeaa0f37db2e9f669879eb30a563f8dd2bb31
- overlay2456 / 31e8e064dc5317b3297140f55f07e81ca1aa9c831a4e4bbbf46cc76db0667b8f
- source-plan6706 / 3399f2f7e8ef9b7c2d6c7ff60985992c0dff1444e463a971ad2560cdbda410ee

Launch policy exactly matches the reviewed source plan: argc3, literal marker
`--lunar-rsi-input-v1` at index1, digest at index2 with syntax `[0-9a-f]{64}`,
entrypoint `_rsi_launch`, case `baseline`, environment_selector=false and
input_reads=[]. It is a policy description, not a recorded actual OS launch.

`launcher` has exactly `source` and `object`, each `{path,size,sha256}`. Source
must match `tools/static_python_rsi_fixture/assets/launcher.c`,1740 bytes,
3a81211b2869727469c1de3bfad79144d11f17c99ccc100c3c48015c0398a0e0.
Object has path `installation-owned-launcher.o`, positive bounded size and digest;
the same complete record must occur exactly once in descriptor.recipe.link_inputs.
No object bytes are read or inferred from the source digest.

Embedded `descriptor` is canonicalized and passed through the unchanged
`parse_static_python_installation_descriptor` with its separate caller pins.
Its frozen inventory digest must also equal the independent inventory pin.
The exact nine source path/size/digests and generated output paths match reviewed
base freeze tasks with only the reviewed expanded-main substitution: main source
`assets/frozen_main.py`,7227 bytes,
2b30f4463db471419df601a0c7640a560d2be95aed08d69cdf0e8e10d6871d28.
All generated records require positive sizes and digests; main generated digest
must equal the separate caller main-header pin. Pending headers, missing modules,
old main source and arbitrary re-signed path/source mutations refuse.

No reviewed actual old-main generated-header digest exists yet. Therefore the
validator cannot prove non-reuse of old bytecode, source-to-object/header
correspondence, or build closure. The external header/inventory pins are mandatory
comparison inputs, not evidence that somebody independently built those bytes.
Synthetic test vectors must be labelled synthetic and cannot establish F02.

Claims contain exactly the nine preparation claims, all exact false:
configured_closure_verified, compilation_performed, freezer_performed,
runtime_execution_performed, installation_accepted, input_consumption_verified,
runtime_load_protection, production_admission, general_code_origin_protection.
The original embedded descriptor also retains its own false claims.

## Result and validation

Return a frozen slots DTO holding canonical wire and comparison digests/version,
with detached to_json/to_dict access. Parsing performs no filesystem, network,
environment, process or runtime operations; it imports no tools/profile modules
as authority. Errors are `StaticPythonRSIInstallationError` with a fixed reason
and no retained parser cause/context or caller material. DTO construction and
successful comparison convey no runtime ownership or admission.

Focused tests independently construct synthetic vectors from reviewed metadata,
exercise all mandatory pin disagreements, strict type/bound ordering, re-signed
mutants, incomplete/pending inventories, launch/argv separation, false claims,
immutability, canonical JSON/error disclosure and absent side effects. Preserve
original installation/preparation/source/report compatibility. Run focused tests,
Ruff, compileall and diff checks; retain a focused CI XML gate. Actual F01–F06
installation/build/runtime/input/handoff/solver/CLI acceptance remains unchecked.

## Local verification

Root Python3.11 passes189 focused and515 disjoint compatibility cases,704 unique
cases with zero failures/errors/skips. Independent Python3.13.12 passes the same
189 cases with final source/test hashes unchanged; this adds no unique cases.
Two independent source reviews confirm all nine source/output records against
reviewed base/overlay, the complete launcher record and three input pins.
All27 baseline parser/preparation/asset files remain unchanged. Whole-source Ruff,
compileall and diff checks pass. The focused CI gate retains189 cases and XML.
Initial test-oracle failures are retained separately, without product changes.
Final-source complete CI/audit and dependency-order merge remain pending.
