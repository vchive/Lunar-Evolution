# Project runtime profile continuation

Status: executable-profile design only. No dependency closure, image or runtime
is accepted by this document. The source/declaration portion of step1 now has
an independently reviewed OpenEvolve v0.4.0 baseline in
`openevolve-source-profile-review-20261025.md`; the complete step remains open.
`production_admission=false`.

## Current executable boundary

The `rsi-marker-launch-v1` preparation in Feature193 substitutes exactly two
reviewed source records. Its candidate nine-module inventory is intended for
startup and encoding; the complete closure remains unverified.
`assets/frozen_main.py::_rsi_launch` checks digest syntax and calls the fixed
baseline computation. It does not read the authoritative RSI input, import
OpenEvolve/Shinka or dispatch an SDK. `run_pinned_build` can execute independently
reviewed commands; its successful report does not establish any of those missing
behaviors.

The existing local producer exporter reads completed wrapper/SQLite/source
material, and the single-episode gateway composes a pre-staged native context.
Neither supplies a runnable project closure. A continuous DRS launch mechanism
must retain this distinction even after per-episode proof wiring is implemented.

## Outcome and reuse

Specify a separate, finite runtime profile for each supported project before
implementing its executable entrypoint. Keep the current fixture profile and its
pins unchanged. Reuse Feature177 runtime inventories, Feature188 sealed material,
Feature189 source/toolchain/build acceptance, Feature190 executable ownership,
and Feature191 binding, sidecar, broker, scheduler and result-export interfaces.
Do not introduce another launch protocol, claim ledger or evaluator.

Each project profile must independently retain:

- Exact project release/commit, source archive/tree bytes and patch provenance.
- The complete Python and native dependency closure, including generated code,
  package resources, codec/import requirements and platform-specific libraries.
- The controlled entrypoint and its complete, finite module inventory. Changes
  to loader policy or the frozen inventory require a new reviewed profile.
- The exact image, target/ABI, initialization policy, toolchain, build recipe and
  independently audited generated/static-link closure.
- The project configuration, request/memory mapping, output contract and local
  export selection. These are bound to each episode's original launch evidence.

Names and version strings alone are insufficient. The separately reviewed
OpenEvolve source baseline is not a selected executable or dependency identity;
current host packages cannot fill a missing entry. Do not widen the nine-module
fixture and claim SDK support.

## Entrypoint and lifecycle

One profile provides one reviewed project entrypoint. The request selects
bounded supported settings, never a module/factory import, code string, host
interpreter, package installation or arbitrary command. Authoritative inputs
come from the existing native marker and original request/memory grants; the
entrypoint must actually consume them instead of returning the fixture baseline.

Use the existing host broker for model/request accounting. Credentials and
endpoint secrets remain host-only; no SDK may bypass the broker using an ambient
environment or a second network client. This is an interface requirement, not a
claim that the present fixture restricts all network access.

Keep the original absolute deadline and parent budget throughout startup,
project work, export and settlement. Bound stdout/stderr, broker exchanges and
result material. Reuse the existing native terminal, cleanup and unknown rules.
A project exit or external score does not authorize evaluation or publication.
The exporter retains untrusted provenance; only the existing local exact
evaluator and prepared/publication boundary can settle a candidate.

## Implementation order and acceptance

1. Freeze one project's actual source and dependency bytes, enumerate its required
   imports/resources, and review the resulting finite entrypoint/loader policy.
   Select the first project only from reviewed material; no upstream campaign is
   run during this step.
2. Implement that profile using the existing image/installation pipeline. Keep
   the fixture profile available as a compatibility baseline. No host Python,
   `pip`, dynamic factory loader or executable metadata substitute is admitted.
3. After source/toolchain/static-image acceptance, validate sealed startup and
   actual authoritative input consumption with local inert broker responses.
4. Exercise the real project's bounded lifecycle and retained export on the
   accepted runtime, including timeout, cancellation, parent loss, missing
   terminal, callback failure, cleanup uncertainty and source/result drift.
5. Compose the accepted profile with durable per-episode staging, native claims,
   retained recovery and controller prepared admission. Then validate the
   explicit local producer CLI on a dedicated Linux matrix, retaining original
   receipts and independently checking source/tree/runtime identity.

Provider-free tests may verify wiring and refusal behavior. They do not close
steps 1–5, prove an SDK can execute, or grant production admission. Actual model
or effect campaigns remain separately authorized work after runtime acceptance.
BRS multi-child authority, remote evaluator, distributed ownership and service
APIs remain outside this continuation.
