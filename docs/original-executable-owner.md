# Original Linux executable ownership

Feature190 preserves `sealed_linux_executable` and its public DTO. The context
holds a private original memfd anchor and a borrowed CLOEXEC executable duplicate;
the anchor never belongs to the child FD grant. Only the exact live factory
handle has an owner. A constructed or copied DTO, public number, detached record
or byte-identical foreign object cannot recreate one.

The internal live check compares original scalar pins, object identity,
executable mode, size, CLOEXEC and four complete seals, then independently hashes
the image with bounded `pread`. It retains the original deadline and clock;
source deletion/replacement after sealing cannot change the held image. The
128 MiB ceiling and legacy positive-infinity helper compatibility remain. Future
static CPython fixtures separately require finite budgets.

The original Linux bootstrap/target pair is checked before control encoding,
immediately before native Popen and before the guardian handoff. The direct
producer caller also verifies its original live handle before spawning. Native
v2 formats, target FD roles, registration and receipt schemas are unchanged.

Cleanup independently attempts every still-owned descriptor, using private
acquisition data. It leaves known foreign reused objects open and never retries
an uncertain close by number. Existing primary exceptions survive, with only a
fixed `linux_execution_cleanup_unknown` note when necessary. Uncertainty without
a primary raises a fixed typed error.

This assumes a trusted controller that does not concurrently close/rebind private
acquisitions or race ownership observation with close. It does not establish FD
generation/open-file-description identity, atomic concurrent rebinding protection
or cross-restart FD authority. An unpublished acquisition interrupted before its
first identity capture supports only a first release under that assumption;
uncertain release can leak a descriptor and is never claimed as clean.

No static CPython image, import/archive/native-loader closure, runtime-load
protection, production Python admission or solver campaign is supplied. Actual
Linux owner acceptance remains pending until this feature's final-source CI and
independent evidence audit finish.
