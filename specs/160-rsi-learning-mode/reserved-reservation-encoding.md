# Reserved reservation baseline encoding

## Scope

The `be7776bf8aed873f681800887837f82d58bd70e9` Linux three-child mixed
fixture reached the third rejection completion observation but exceeded its
original 600-second limit. This is a failed fixture run, without JUnit or a final
loaded-module report. Its stack samples show reservation observation in the
completion chain; they do not measure that function's elapsed-time share.

This change reduces repeated pure canonical encoding inside one reservation
history walk. It does not change scheduling, observation frequency, deadlines,
row limits, ownership, or production admission.

## Contract

`_observe_reserved_brs_reservation` freshly decodes every retained controller
state. For each state it compares the 14 `_FIXED` fields with the first decoded
state. Previously both operands were encoded for every comparison, including
the identical baseline field for each later row.

The walk now retains only the first state's canonical field bytes in a local
dictionary. A baseline field is encoded lazily when its first comparison reaches
that field. The current state's field is encoded first, just as before. This
keeps the original control and attempt shape gates, field ordering, short-circuit
behavior, exception boundary, and finalization-specific field exclusion.

Every actual state field is still encoded independently. The dictionary is not
stored on the ledger, returned in an observation, shared with another invocation,
or populated from a caller-owned state. No parsed DTO, SQLite observation,
filesystem observation, or successful validation outcome is cached. Existing
ledger observations, their independent raw snapshots, file and inode checks,
and final observation comparison remain unchanged.

For a successful ordinary walk with `H` rows, fixed-field encoding calls change
from `28H` to `14H + 14`. This is a static work count, not a measured end-to-end
speedup. Existing reserved policy coverage includes the reservation module and
therefore the enclosing function's changed code and its nested helper.

## Validation

New focused coverage uses the existing local, provider-free reservation fixture:

- one baseline encoding per field after its original first actual comparison;
- each later actual value still encoded and checked;
- separate observations construct separate decoded baselines;
- both ledger observations retain both raw snapshot reads;
- earlier control, shape, and field drift failures precede later invalid UTF-8
  encoding failures.

Run the new encoding-reuse tests with the existing reserved reservation, ledger,
finalization, and reserved policy suites. No WebAgent, model, remote evaluator,
company platform, or failed mixed-source replay is part of this validation.
