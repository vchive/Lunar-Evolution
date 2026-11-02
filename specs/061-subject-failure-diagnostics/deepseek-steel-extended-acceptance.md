# Independently budgeted DeepSeek steel attempt

Status: specification before preparation, not dispatched (2026-11-02).

The original steel attempt ended as schema2 runtime/budget_exceeded after
22 HTTP200 completed requests; no evaluator ran. Preserve that failure and the
previous train/hospital failures. The user authorized DeepSeek/local copied
cases and long runs. Use one additional independently registered budget profile
to test whether the original ordinary tool loop can finish this same public
task within a larger, explicit ceiling. This is a separate experiment with a
different profile, not a retry/resume or replacement of the previous result.

Fixed new profile: deepseek-chat, 80 tool calls, 1,000,000 observed cumulative
tokens, 3,000 subject seconds and max_completion_tokens=16,384. Exactly one
fresh attempt, zero inference retries or fallback. The observed-token threshold
is not a hard remote billing cap. No further budget escalation is included in
this experiment; publish its actual outcome.

Keep frozen product source f3257898/tree dfb61885, the exact same case/public
contract and original evaluator, plus the existing independently registered
hash-locked evaluation venv. Neither fixed-profile producer preparer is used;
PR217's pin integration correction and final CI are separate. Copy only prepared
inputs into a new root, never previous requests, history, answers or results.

Reuse common and the steel evaluator launcher exactly. The new subject child
may change only its exact profile guard, registered max-steps assertion and CLI
max-steps argument to require 80 / 1,000,000, preserving all other fields, cap,
timeout, secret handling, runtime MODEL-only override and receipt validation.
Use the preceding original DeepSeek profile as an opaque comparison input;
allow only max_steps and max_total_tokens to change. Bind the exact new profile
and request digest and assign a fresh manifest/attempt identity.

Independently review exact helper deltas, copied source/case/profile/venv and
fresh roots; push registration before authorization/dispatch. Preserve the
existing 3,020-second subject watchdog plus five seconds each TERM/KILL,
1 MiB captures, and actual imported-module provenance. Only an original valid
completed receipt and declared root solution.csv permit the unchanged local
evaluator once (30 seconds plus five KILL/reap), with no model credentials.
Verify the evaluation environment at launch, immediately before evaluation and
afterwards. No answer repair, substitution or score-driven parameter changes.
Require evaluator rc0, finite scores and validity 1 for this functional smoke;
report quality separately. Review original evidence without repeating scoring.

No product code change, new software regression, WebAgent, remote evaluator or
native RSI execution. Preserve all historical denominators and unknown fees.
No same-budget parity, general reliability or evolution-benefit claim.
production_admission=false and online_publication=false remain unchanged.

## Tasks

- [x] Declare the new budget, inputs, boundaries and single-attempt rule.
- [x] Prepare and independently review the exact new profile/helper/manifest.
- [ ] Push registration, authorize and launch once.
- [ ] Review original outcome and publish results without escalation.

## Prepared identities

Fresh root: primary workspace ignored
`.lunar-evolution/validation/deepseek-steel-extended-20261102/steel_coil_cutting/`.
Manifest SHA256:
`7a65468b35efc79427af3ffe95774584bf27675ae182232b14d9543d8796d714`.
New profile raw212-byte SHA256:
`a84a457b72f181cae593aa98b62156b3566e0d26df5de5273377ceed2e4052b1`;
child9,919-byte SHA256:
`23cb55a982eb265689856bc20108771ab4ad483c9d3b94f4b15ea61d8610f591`.
Common/launcher retain exact prior steel hashes. Full source2,826/308,
case14/public5=6,873bytes and evaluator venv4,586/434 are unchanged.
The independent preparation/code/artifact review found no blocker, report SHA256
`734345af53425b4026267fe8ed3e2745c88c61921c12270d59da60f96a75afff`.

The first local preparation refused before creating a run directory because
its inventory used Path ordering instead of the reference's relative-string
ordering. Original preparer/logs and the ordering-only correction remain
separate; the corrected preparation completed without configuration/model/
evaluator calls. This was not an inference attempt or retry.
