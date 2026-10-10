# Detached static artifact byte verification

This narrow P1 slice compares one caller-retained static-image byte string with a
separately pinned `lunar-static-python-installation-v1` descriptor. It is a pure
format and provenance consistency gate. It does not acquire or authenticate a
release, build an image, inspect a path, seal an executable, launch CPython,
observe a process, or grant production admission.

## API and bounds

`verify_static_python_artifact_bytes(image, descriptor_raw, *,
expected_descriptor_sha256, expected_installation_version,
expected_artifact_sha256)` accepts exact built-in `bytes` only. The image must be
between one byte and the existing 134217728-byte (128 MiB) ceiling. The cheap
image type and size checks run before descriptor parsing, hashing, or ELF
inspection. The installation parser retains its own descriptor byte, shape,
canonical, nested-manifest and external-pin checks.

The caller must provide all three independent pins. No digest is inferred from
the bytes or from a parsed descriptor. The descriptor's artifact SHA/size and
its complete `elf_profile` are compared with exactly one pure
`inspect_static_python_elf(image)` observation. The comparison covers every
field owned by that observer: image SHA/size, OSABI, entry point, program and
section header counts, load and executable-load counts, dynamic table and entry
counts, ELF class/byte order/machine/type, PT_INTERP and DT_NEEDED flags, and
the false protection/admission projections.

The returned frozen `StaticPythonArtifactVerification` retains a detached
canonical JSON projection and digest. `format_verified=true` means only that
these supplied bytes and declarations agree. `execution_performed`,
`runtime_load_protection`, `production_admission` and
`general_code_origin_protection` remain false. The result cannot authorize an
owner, FD, runtime, source/toolchain signature, static closure, evaluator or
memory publication.

## Refusal contract

Refusals use fixed `static_python_artifact_*` codes and never include paths,
credentials, stderr or image-controlled strings. Invalid pins, image type or
size fail before descriptor/ELF work. Descriptor parser failures are wrapped as
`descriptor_<parser-code>`; ELF format failures are wrapped as
`elf_<inspector-code>`. Independent SHA/size or complete ELF projection drift
refuses after the one observation. A resigned descriptor cannot turn a byte
mismatch into success.

The DTO's `to_dict()` and `to_json()` return detached data. No filesystem,
network, subprocess, compiler, runtime or evaluator operation is part of this
slice. Synthetic ELF fixtures exercise the protocol only and do not constitute
CPython or release evidence.

## Validation

`tests/test_static_python_artifact.py` covers positive detached evidence,
immutability, exact bytes/type and 128 MiB bounds, independent descriptor and
artifact pins, malformed/canonical/duplicate/unknown descriptors, artifact
size/SHA drift, each observed ELF projection drift, single inspector call,
false runtime claims and external-effect refusal. It reuses the existing
synthetic ELF and installation wire fixture. The focused gate is provider-free
and must run without model credentials, downloads, WebAgent, remote evaluator,
compiler, process launch or real solver campaign.
