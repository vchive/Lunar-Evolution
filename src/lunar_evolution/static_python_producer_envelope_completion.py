"""Pure, separately versioned comparison for target-side generic envelopes.

The original reader, envelope capture, broker and native custody remain separate
owner checks. Matching public bytes never creates original execution authority.
"""

from __future__ import annotations

import hashlib
import json

from .static_python_producer_completion import (
    COMPLETION_PROFILE,
    COMPLETION_PROTOCOL,
    MAX_COMPLETION_BYTES,
    FixedProducerCompletionBinding,
    FixedProducerCompletionComparison,
    FixedProducerCompletionError,
    _canonical,
    _same_material,
    _unique_object,
    compare_fixed_producer_completion,
)
from .static_python_producer_envelope_source import (
    FIXED_PRODUCER_ENVELOPE_PROFILE,
    FIXED_PRODUCER_ENVELOPE_PROTOCOL,
)

MAX_ENVELOPE_BYTES = 128 * 1024


def compare_fixed_producer_envelope_completion(
    raw: bytes, *, binding: FixedProducerCompletionBinding,
    request_bytes: bytes, memory_bytes: bytes, request_body_bytes: bytes,
    reply_bytes: bytes, artifacts: tuple[tuple[str, bytes], ...], envelope_bytes: bytes,
) -> FixedProducerCompletionComparison:
    """Join v2 records to the exact separately retained original envelope bytes.

    Only a local pure projection reuses the strict v1 material comparison. The
    v1 wire parser remains unchanged and cannot accept this v2 record shape.
    This function does not read paths, accept a supplied digest as material or
    upgrade its comparison result to an original acquisition.
    """
    try:
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_COMPLETION_BYTES
                or raw.count(b"\n") != 2 or not raw.endswith(b"\n")
                or type(envelope_bytes) is not bytes or not 0 < len(envelope_bytes) <= MAX_ENVELOPE_BYTES):
            raise ValueError
        records = []
        for line in raw[:-1].split(b"\n"):
            record = json.loads(line.decode("ascii"), object_pairs_hook=_unique_object)
            if (type(record) is not dict or _canonical(record) != line
                    or record.get("profile") != FIXED_PRODUCER_ENVELOPE_PROFILE
                    or record.get("protocol") != FIXED_PRODUCER_ENVELOPE_PROTOCOL):
                raise ValueError
            records.append(record)
        envelope = records[1].get("envelope")
        if (type(envelope) is not dict or set(envelope) != {"path", "size", "sha256"}
                or type(envelope["path"]) is not str or envelope["path"] != "producer-result.json"
                or not _same_material({key: envelope[key] for key in ("size", "sha256")}, envelope_bytes)):
            raise ValueError
        # This is an internal value projection, never an accepted v1 input.
        projected = []
        for index, record in enumerate(records):
            copy = dict(record)
            copy["profile"], copy["protocol"] = COMPLETION_PROFILE, COMPLETION_PROTOCOL
            if index == 1:
                del copy["envelope"]
            projected.append(copy)
        legacy = compare_fixed_producer_completion(
            b"".join(_canonical(record) + b"\n" for record in projected), binding=binding,
            request_bytes=request_bytes, memory_bytes=memory_bytes,
            request_body_bytes=request_body_bytes, reply_bytes=reply_bytes, artifacts=artifacts,
        )
        return FixedProducerCompletionComparison(
            binding, raw, hashlib.sha256(raw).hexdigest(), legacy.artifact_sha256s,
        )
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise FixedProducerCompletionError("fixed_producer_envelope_completion_refused") from None
