# Active native subprocess cancellation and deadline enforcement

## Gap and scope

The shared producer control already narrows launch timeouts and checks every stage. The native
selector loop currently observes only its launch timeout, so parent cancellation waits for the
candidate or evaluator to finish. A typed stop raised before result publication can also leave only
a launch intent, without the supervisor's cleanup observation.

This slice extends the existing native process supervisor. It polls the same continuation callback
at most every 50 ms while candidate/evaluator subprocesses are running, narrows its absolute process
deadline, and kills the owned process group on cancellation, elapsed shared deadline, or a failed
control callback. It never creates a new control or deadline. Normal successful receipts keep their
existing schema. No scheduler, remote evaluation, external campaign, or model request is introduced.

## Stop evidence and recovery boundary

After cleanup, the original typed cancellation/timeout is re-raised. Before that exception leaves
the recorded candidate/evaluator boundary, the caller writes an exclusive canonical
`interrupted.json` containing the pinned request, stop reason, observed process identity, actual
exit code, whether ownership release was observed, and verified/unknown/failed cleanup. Public
reason is cancellation, timeout, or control failure; stdout and private reasoning are excluded.

Stopped candidates retain their launch intent and interruption receipt without a successful result
or completion marker. Their read-only inspector remains uncertain and cannot grant evaluation or
publication authority; it treats `interrupted.json` as diagnostic evidence rather than a completion
receipt. An interruption file coexisting with result/completion files is rejected. Stopped evaluators retain their frozen request plus interruption evidence,
without `evaluation.json` or an authoritative score. A retry must reconcile these incomplete
attempts and must not silently rerun them. Failure to persist stop evidence remains uncertain.

The supervisor can confirm its private process group. Detached descendants that escape that group
are outside this native boundary; absence of complete cleanup evidence never becomes a successful
publication. This change does not turn subprocess execution into a sandbox.

## Validation tasks

- [x] Candidate loop promptly stops on cancellation and shared deadline while a child holds pipes.
- [x] Evaluator loop uses the same control and writes bound interruption/cleanup evidence.
- [x] Verified cleanup requires an absent owned group and matching release; failure remains unknown.
- [x] Transaction publishes no result and does not admit another draft after an active stop.
- [x] Retained deadline bytes remain unchanged, and exact retry never gets a fresh allowance.
- [x] Existing normal candidate/evaluator and producer receipt regressions remain compatible.
