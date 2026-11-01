# Ordinary direct-evaluation public contract

Status: provider-free interface check passed once, 2026-11-02.
No real model or evaluator has run with this additional contract.

## Problem and existing implementation

The unchanged train-delay public instruction describes a complete schedule but
does not specify an answer filename or JSON field names. The existing ordinary
subject prompt asks for `_agent_summary.md` to identify an answer file for an
independent extractor. The registered long-run helper instead selects only
`schedule.json` or `output/schedule.json` and invokes the local evaluator
directly. That evaluator expects numeric arrival/departure matrices.

The resulting interface mismatch can reject an answer because of its format.
An absent fixed-name submission alone does not prove that no semantic answer
was produced. It also does not explain the earlier response-header stalls.
The ongoing [unchanged-input long run](ordinary-model-long-run-acceptance.md)
must retain its original inputs, helper, limits and outcome.

The existing `PublicFile` ledger, `entrypoint` and `run_subject_adapter` already
support an explicitly published task contract. No provider protocol, runtime
module, answer repair or automatic extractor is needed for this correction.
The existing full harness uses a separate model-assisted extractor; connecting
it here could add model requests and cannot be done inside the active attempt.

## Independent case variant

Prepare a separate public case variant with a new identity. Preserve the
original eleven-file copied case and benchmark unchanged. The variant keeps
the two original public files byte-identical and adds `public-task.md` as its
entrypoint, containing the original instruction verbatim plus only:

- Save the final schedule as UTF-8 JSON in `schedule.json` in the attempt's
  working directory.
- Include numeric two-dimensional `arrival` and `departure` arrays, with rows
  indexed by train and columns by station.
- Use the public instance's `n_trains` and `n_stations` dimensions and minutes
  as the time unit.

Do not add answers, algorithms, ground truth, evaluator code or private score
logic. The original task's other requested schedule information remains part
of the task. Pin the new entrypoint in the public ledger and record the old
eleven-file inventory, old public-two inventory and new public-three inventory
separately. Never reuse the old public-input identity or describe this as the
unchanged reference case or a matched-budget comparison.

## Provider-free interface validation

Before any real attempt, review a small isolated check against frozen product
`5c62ca270d78c605ca189399c8b8caadcd11e1b7`. Use temporary toy instance data
and an injected fake runtime with no tool calls. The check must establish:

1. The existing adapter includes the entire new entrypoint and format contract
   in the fake model's prompt, and produces its ordinary completed receipt.
2. A missing entrypoint, changed entrypoint bytes or entrypoint absent from the
   public ledger is rejected before any fake model call or receipt creation.
3. Real provider construction, network connection, subprocess creation and
   command-tool execution are guarded against in the check. No credentials,
   evaluator or real inference are used.

Keep the script, exact hashes, original outcome and any necessary preparation
correction distinct. This verifies the existing input interface only: it is
neither a benchmark score nor real model acceptance, and it grants no isolation,
runtime or publication authority. Do not rerun the full product regression for
this documentation and isolated fixture preparation.

## Later real acceptance

A real direct-contract attempt requires its own frozen public identity,
manifest, profile, limits and exact helper review before dispatch. It must not
modify or resume the active unchanged-input attempt, reuse its authorization,
repair its answer or add requests to its denominator. Preserve both historical
600-second failures and the current long-run result independently.

Use the existing original-receipt completion gate before a single local score
invocation. Report finite validity/quality/overall values separately and require
`validity_score == 1` for functional completion. A passing variant cannot close
the original unchanged-input reference result or establish WebAgent parity.
This preview does not register or execute a real variant run.

## Tasks

- [x] Identify the public-instruction/direct-evaluator mismatch without changing
  the active long run.
- [x] Specify a separately identified public contract using existing APIs.
- [x] Prepare the public-contract preview and provider-free check for review.
- [x] Complete exact-byte independent review and the single offline interface
  check; retain its actual result.
- [ ] Separately register, review and execute any real variant acceptance.

The preview is retained under the primary workspace's ignored
`.lunar-evolution/validation/ordinary-direct-contract-20261102/preview-Z7Oce8/`.
The derived task is 1,311 bytes with SHA256
`2da1a7b6ffa1a58c2d32d580235591eb2543e3f52ecd3d69d1a995eba95ee75e`.
The initial check script was never executed. Independent review found a wrong
import path and the need to disable bytecode writes before importing the frozen
product. Both preparation issues were corrected in a separate v2 script;
the original v1 bytes and exact two-change diff are retained.

The independently reviewed v2 is 5,834 bytes, SHA256
`d95e07657e9d31cc36e22f5da53a7c067784c516a45d3a40616c0b6889130d6c`.
Its only execution used Python 3.13 with `-I -S -B`, returned rc0 in
0.642141666 seconds and passed all four fixture cases: one intact prompt with
one fake call, and three rejections with zero fake calls. Real model requests,
tool executions and evaluator calls were all zero; no score was produced.
`offline-original-result-v1.json` retains the original tool result separately
from the preparation-only provenance. These observations validate the existing
entrypoint/ledger interface, not the real scheduling task.

Preparation does not change `production_admission=false` or
`online_publication=false`.
