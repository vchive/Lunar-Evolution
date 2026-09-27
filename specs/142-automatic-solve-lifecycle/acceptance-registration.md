# Acceptance registration manifest and seal

This document defines the provider-free registration contract used before the next automatic
multi-file acceptance attempt. It extends the existing Feature 142 plan without opening a provider,
campaign, candidate, evaluator, or generated source. The registration is one fresh
`attempt-001`; the historical Feature 139 slot remains immutable.

## Canonical manifest

`build_acceptance_registration` accepts exactly one JSON object with
`schema_version="1"` and `scope="acceptance_registration"`. The object is canonical UTF-8 JSON
(sorted keys, compact separators, no non-finite numbers) and is bounded to 128 KiB. Its
`registration_sha256` is SHA-256 over the canonical object without that field.

The manifest freezes the new registration/campaign/attempt identities, product checkpoint commit,
provider/model/runtime/API mode, entrypoint, fixed Feature 142 budgets, and the single-island
population (`islands=1`, population/offspring/rounds all `1`, exactly `12` candidate tool steps).
`attempt_id` is exactly `attempt-001`.

`product_files` is a sorted, non-empty list of `{path,size,sha256}` entries for the controlled
product source/configuration files. These entries are checked against both the pinned product
commit and the checkout during preflight; registration and seal files cannot be listed as product
files.

Task, input, independent evaluator criteria and profile criteria are each declared as
`{path,size,sha256}`. Paths are relative, bounded, and free of traversal, control characters,
backslashes and colons. The declared material digest must equal its corresponding top-level task,
input, evaluator or profile digest. Material paths are unique. The existing JSON field names
`evaluator_material`, `evaluator_profile_material`, `evaluator_sha256`, and
`evaluator_profile_sha256` refer to these **preregistered criteria**, not the Python evaluator
or bundle profile generated during native preparation. The criteria describe the required result,
score, source-file count and probe behavior; they cannot be substituted for executable artifacts.

The historical case used `openai-compatible`, requested model `glm-5.2`, and native wire API
`chat_completions`. Its task SHA-256 is
`2c015edee8cac2c0a36a02acb9de86cc741e2bce60e340f5dfd4c3f1e67b3028`; its input bytes
are exactly `{"limit":3}\n`, SHA-256
`a87f29f60db7ebd0d5269a34a8be49b964bb77e62ee38f77987aced80accb5c7`. The actual eight
historical probes, in order as `(limit, value)`, are `(1,-1)`, `(1,0)`, `(1,1)`, `(1,2)`,
`(3,0)`, `(3,2)`, `(3,3)`, `(3,4)`. The shortened list in the old manifest is not the executed
probe set. These facts identify the case; they do not reuse the old campaign root or evidence.

`holdout_pins` contains exactly eight ordered entries. Each entry has a unique safe `holdout_id`,
its integer `ordinal`, nested `input` and `expected` material declarations, and
`max_duration_ms <= 5000`. The eight inputs and expected bytes are therefore frozen in the
registration rather than represented by bare digests.

`frozen_identities` is required and contains three non-empty, duplicate-free arrays:
`registration_id`, `campaign_id`, and `campaign_root`. Its canonical SHA-256 is stored as
`frozen_identities_sha256`; the preflight rejects any new identity that appears in these arrays.
No caller may omit this denylist or supply it later as an optional admission condition.

## Seal

`build_registration_seal` creates a canonical `acceptance_registration_seal` object that binds the
registration digest, all three new identities, the product checkpoint and the campaign root. Its
`seal_sha256` covers the seal payload. The seal deliberately does not include a preflight digest,
Git status, timestamps or mutable observations, so committing the manifest and seal cannot form a
circular dependency. The manifest and seal must be committed before launch preflight.

## Read-only preflight boundary

The filesystem/Git preflight reads the committed manifest and seal with no-follow regular-file
access, verifies their exact tracked bytes, checks product files against both the pinned product
checkpoint and `HEAD`, and checks all four primary materials and sixteen holdout materials against
their declared bytes and committed `HEAD` blobs. Material and product files may be up to 8 MiB;
the manifest and seal remain limited to 128 KiB. It requires a clean checkout whose `HEAD` equals the verified
`origin/main`, and confirms the campaign root is absent. It rejects symlinks, FIFOs, dirty or
unpushed checkouts, missing/untracked material files, byte drift, reused identities, and a
pre-existing root. It does not create the root or write a report as an admission side effect.

The separate observation manifest's `evaluator_sha256` continues to mean the **runtime-generated
Python evaluator harness digest**. The existing semantic auditor compares that digest to the
prepared bundle profile. A future launch runner must retain both identities and prove that the
generated evaluator/profile implement the preregistered criteria before the attempt can claim
preparation or scoring success. A mismatch is a failed/unknown preparation boundary, never a
reason to rewrite the registration. This two-layer binding does not exist merely because the
registration preflight returns `ready`.

A `ready` observation permits a separate caller to retain the preflight record and then launch the
sole attempt. The API itself never launches, retries, resumes, repairs, increments acceptance
counters or treats a provider-free fixture as a real result.
