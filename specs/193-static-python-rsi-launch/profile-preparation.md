# RSI marker installation-profile input preparation

Status: implemented and locally verified, final-source CI/audit pending, 2026-10-12.
This extends Feature193 preparation only. It does not accept a new installation.

## Current gap and result

The marker source plan changes two reviewed build inputs: the installation-owned
launcher and expanded `_lunar_static_main` freezer source. Existing Feature189
build input pins correctly refuse those new bytes. Prepare a separately tagged
candidate input overlay with exactly these two record replacements; all other
compilation/freezer/source/header/profile records must remain byte-equivalent.
The production installation parser and accepted argc-one profile stay unchanged.

## Pure API

`prepare_rsi_installation_profile` is implemented in
`tools/static_python_rsi_fixture/installation_profile.py`. Keyword-only inputs:
`reviewed_build_inputs: bytes`, `reviewed_overlay: bytes`, `source_plan: bytes`,
`expected_source_plan_sha256: str`, `source_assets: dict[str, bytes]`.
Return an immutable `RSIProfilePreparation` containing canonical `wire_bytes`
and its digest. No filesystem, process, network, clock or environment accesses
occur in this function. It emits no descriptor accepted by production consumers.

All buffers and map/key/value types must be exact built-ins. Check byte bounds
before parsing/hashing; refuse subclasses, unknown/missing asset names and malformed
caller pins before data callbacks. Expected source-plan digest is separately
supplied by the caller and must match the independently reviewed overlay pin as
well as actual bytes. Fixed size/SHA256 constants bind the old reviewed input file
and the new reviewed overlay. Validate all six supplied source payloads against
the pinned source plan, not merely caller-recomputed digests.

The fixed reviewed overlay uses `lunar-static-python-rsi-profile-overlay-v1`,
contains the original base and source-plan pins, sole `rsi-marker-launch-v1`
profile and two complete before/after records. First parse the pinned base through
the existing build-input validator, then match both exact preimages. Reject
changes to units, imports, flags, modules, target, initialization profile, Python
argv/orig_argv, OS marker policy or any other record. A re-signed mutated manifest
or overlay does not authorize different bytes. Duplicate/invalid JSON, excess
size/depth or non-finite values refuse with the fixed preparation error contract.

## Output and acceptance

The output wrapper schema is
`lunar-static-python-rsi-installation-profile-preparation-v1`. Nested candidate
build inputs use a distinct schema and are source-review facts, not configured
object closure. Retain original and overlay/source-plan pins, fixed launch policy,
unchanged initialization profile and exactly two substitutions. Record all nine
frozen-header tasks as pending with no produced header digest; the changed main
header must never be retagged from the old source. Object/link/ELF/artifact/owner/
lifecycle evidence remains absent. All configured/build/freezer/runtime/
installation/input/admission/protection claims remain false.

Tests cover deterministic output and immutability, exact two-record differences,
all six payloads, strict types/bounds/pins and re-signed mutants, no side effects,
fixed Python vectors, header non-reuse, and production parser refusal of the new
wrapper/candidate. Run focused tests plus Feature193/source/build/installation
compatibility, Ruff, compileall and diff checks. Final-source CI and independent
review are required before merge. Actual profile acceptance, build/runtime and
input consumption remain unchecked follow-on tasks; P2 stays deferred.

## Local verification — 2026-10-12

The new focused module passes 113 cases under Python3.11, with zero failures,
errors or skips. Existing build-input/installation modules pass 101 disjoint cases;
existing marker launcher/source-plan modules pass 82 disjoint cases. Root parses
all three retained JUnit reports and confirms 296 unique passing cases. The
independent semantic review verifies the two substitutions and retained records;
independent strict-type/side-effect review and Python3.13 replay pass the same
113 cases with frozen hashes, as recorded in validation.md. A new 113-case CI gate retains/annotates its XML.
Actual installation acceptance and generated header/build/runtime closure remain
open; this pure API does not perform a configure, freezer, compiler or launch.
