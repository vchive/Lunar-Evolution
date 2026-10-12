# Controlled build-driver continuation

This continuation consumes one `RSIProfilePreparation` from
`prepare_rsi_installation_profile`. The preparation wire is checked as exact
ASCII canonical JSON, against its independently pinned size/SHA256, source-plan
pins, false claims, candidate role inventory, and nine pending frozen headers
before any backend method is called. The driver never re-emits source assets or
uses a caller-supplied plan as a substitute for that preparation.

`run_controlled_build(preparation, backend=..., mode="mock", ...)` uses the
fixed graph `configure -> freeze -> compile -> link`. Every backend receives a
fresh detached copy of the candidate plan. Only the trusted in-process mock
backend seam is accepted; real mode and explicit execution environment opt-ins
refuse before stage dispatch. The mock's `simulated_closure` can exercise the
closure gate, but it never sets a real configured/build/installation claim.

The absolute monotonic deadline and optional interruption callback are checked
around each stage. Callback objects are trusted test seams and do not provide a
security boundary around an arbitrary callback or a real process. Partial
stages are retained as evidence and are excluded from `completed_stages`.
Reports recursively detach and freeze evidence; all actual configured,
compilation, freezer, link, installation, startup, and production claims stay
false. Backend and callback exceptions are normalized to fixed codes without
retaining their cause, context, paths, or messages.
