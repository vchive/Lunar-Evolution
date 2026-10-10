# Retained handoff file identity — provider-free implementation slice

## Outcome and scope

An admission handoff must keep its original file identity across independent reads.
Byte-identical replacement, touch, permission/link changes or batch-directory replacement
must refuse before evaluation/publication acknowledgement. This slice implements the
write-derived pin and its existing standalone publication-journal propagation. It does
not launch Python, grant production admission, or add a controller admission attempt:
the controller currently retains the earlier producer binding, not a live admission flow.
Controller admission-attempt anchoring remains required when that flow is connected.

## Frozen API and wire

`PythonProducerAdmissionHandoffFilePin` has this exact closed wire:

```
schema_version: "1"
protocol: "lunar-python-producer-admission-handoff-file-pin-v1"
run_id, journal_id, parent_task_id, task_id
handoff_sha256, raw_sha256, raw_size
file_device, file_inode, file_mode, file_nlink
file_mtime_ns, file_ctime_ns
parent_device, parent_inode
pin_sha256
```

The pin uses canonical JSON and a SHA-256 of its fields excluding `pin_sha256`.
Its raw digest covers the complete canonical handoff file, distinct from the handoff
self-digest. File mode is permission bits `0600`, nlink is exactly one, sizes are
positive and bounded by the existing handoff limit. Device IDs are nonnegative;
inode IDs are positive; all integer fields reject booleans and are bounded at
`2**64 - 1`. The parent pin retains only device/inode because journal creation
legitimately changes directory times and size. No path or FD is a wire authority.

`PythonProducerAdmissionHandoffSidecar` contains `handoff` and `file_pin`.

```
persist_python_producer_admission_handoff_pinned(
    path, *, handoff, expected_file_pin=None
) -> PythonProducerAdmissionHandoffSidecar
read_python_producer_admission_handoff_pinned(
    path, *, expected_file_pin
) -> PythonProducerAdmissionHandoffSidecar
parse_python_producer_admission_handoff_file_pin(value)
```

Only original exclusive creation, write/fsync, stable named/held-FD verification,
same-inode readback and final stat comparison may create a pin. If a retained pin
is supplied, persistence is read-only exact replay; missing/replaced bytes refuse.
Without a retained pin an existing file cannot be adopted, even with identical bytes.
Validate supplied pins before filesystem I/O. Pinned reads compare the original pin
to pre/open/post/named file metadata and held parent identity, without refreshing it.
Partial writes and orphan handoffs remain intact and inspectable.

Existing unpinned persistence/read APIs retain compatibility as limited inspection
surfaces. Protected Python publication requires the new pin; digest-only legacy
Python journals remain parseable but cannot resume/publish through protected APIs.

## Publication anchor and boundaries

`ProducerBundlePublicationJournal.python_handoff_file_pin` is an optional full pin,
omitted for non-Python journals to preserve their canonical bytes. Presence requires
matching handoff digest and run/journal/parent/task IDs and the native receipt link.
The journal self-digest covers the full pin. The explicit transaction receives the
original pin and persists it unchanged in `journal.prepared.json` before evaluation.
Later projections must match that prepared anchor as well as the live pinned handoff.

Revalidate at existing continuation/timeout callbacks, evaluator return, direct staging,
commit/unknown boundaries, terminal acknowledgement and read-only recovery/replay.
No capture of current stat may repair missing original proof. Refusals preserve
budgets, original deadlines and unknown markers and never rerun an evaluator.

This local retained evidence does not protect against coherent replacement of every
trusted journal/ledger and does not authenticate a remote worker or an executable.

## Validation

Use inert fixtures. Cover original creation and exact pinned replay; malformed or
forged pins before I/O; same-byte inode replacement; touch/chmod/link/symlink and
batch replacement; replacement during write/fsync/readback; unknown partial writes;
missing prepared anchor or retrofitted pin; evaluator/guard/timeout replacement with
no archive/state/marker effects; direct staging and terminal recovery/replay refusal;
and non-Python byte compatibility. Run focused tests, ruff, compileall and diff check,
then final-source three-version Ubuntu CI before merge.
