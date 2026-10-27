"""Real HMAC origin checks; no remote worker, ledger, model or evaluator executes."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest

from lunar_evolution.external_worker_origin import (
    MAX_WORKER_ORIGIN_BYTES,
    MAX_WORKER_ORIGIN_RECEIPT_BYTES,
    WorkerOriginContext,
    WorkerOriginError,
    WorkerOriginKey,
    WorkerOriginRegistry,
    new_worker_origin_challenge,
    sign_worker_origin,
    verify_worker_origin,
)

_SECRET = b"private-worker-origin-key-never-exported-1234567890"
_PROFILE = "a" * 64
_RECEIPT = b'{"receipt":"original exact bytes"}\n'


@pytest.fixture
def key() -> WorkerOriginKey:
    return WorkerOriginKey("worker-1", "host-1", "boot-1", "key-1", _SECRET)


@pytest.fixture
def context() -> WorkerOriginContext:
    return WorkerOriginContext(
        "controller-1", "run-1", "task-1", "episode-1", "native-claim",
        "b" * 64, "c" * 64, 1,
    )


def _wire(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _signed(key: WorkerOriginKey, context: WorkerOriginContext) -> bytes:
    return sign_worker_origin(key=key, context=context, profile_sha256=_PROFILE, receipt=_RECEIPT)


def _verify(raw: bytes, key: WorkerOriginKey, context: WorkerOriginContext, **kwargs):
    options = {
        "registry": WorkerOriginRegistry([key]), "expected_context": context,
        "expected_profile_sha256": _PROFILE, "receipt": _RECEIPT,
    }
    options.update(kwargs)
    return verify_worker_origin(raw, **options)


@pytest.mark.parametrize("kind", ["native-claim", "launch-context"])
def test_real_hmac_binds_exact_canonical_message_and_receipt(key, context, kind):
    context = replace(context, context_kind=kind)
    raw = _signed(key, context)
    payload = json.loads(raw)
    supplied_mac = payload.pop("mac_sha256")
    independent_mac = hmac.new(
        _SECRET, b"lunar-external-worker-origin-v1\x00" + _wire(payload), hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(supplied_mac, independent_mac)
    result = _verify(raw, key, context)
    assert result.context == context
    assert (result.worker_id, result.host_id, result.host_boot_id, result.key_id) == (
        "worker-1", "host-1", "boot-1", "key-1",
    )
    assert result.profile_sha256 == _PROFILE
    assert result.receipt_sha256 == hashlib.sha256(_RECEIPT).hexdigest()
    assert result.wire_sha256 == hashlib.sha256(raw).hexdigest()
    assert _SECRET not in raw
    assert _RECEIPT not in raw
    assert "secret" not in result.to_dict()
    assert "receipt" not in result.to_dict()


def test_stateless_exact_replay_is_explicitly_allowed(key, context):
    raw = _signed(key, context)
    registry = WorkerOriginRegistry([key])
    first = _verify(raw, key, context, registry=registry)
    second = _verify(raw, key, context, registry=registry)
    assert first == second
    assert not hasattr(first, "cleanup_confirmed")
    assert not hasattr(first, "publication_authority")
    assert not hasattr(first, "replay_protected")


def test_challenge_uses_controller_secrets_generator(monkeypatch):
    sizes = []

    def token_hex(size):
        sizes.append(size)
        return "d" * 64

    monkeypatch.setattr("lunar_evolution.external_worker_origin.secrets.token_hex", token_hex)
    assert new_worker_origin_challenge() == "d" * 64
    assert sizes == [32]


def test_context_roundtrip_detaches_the_retained_dict(context):
    plain = context.to_dict()
    restored = WorkerOriginContext.from_dict(plain)
    plain["run_id"] = "foreign-run"
    assert restored == context


@pytest.mark.parametrize("change", [
    {"controller_id": "controller-2"}, {"run_id": "run-2"}, {"task_id": "task-2"},
    {"episode_id": "episode-2"}, {"context_kind": "launch-context"},
    {"context_sha256": "d" * 64}, {"controller_challenge": "e" * 64},
    {"assignment_generation": 2},
])
def test_every_expected_original_context_field_must_match(key, context, change):
    with pytest.raises(WorkerOriginError, match="^worker_origin_context_mismatch$"):
        _verify(_signed(key, context), key, replace(context, **change))


@pytest.mark.parametrize(("field", "value", "error"), [
    ("worker_id", "unknown-worker", "worker_origin_worker_unknown"),
    ("key_id", "foreign-key", "worker_origin_key_mismatch"),
    ("host_id", "foreign-host", "worker_origin_host_mismatch"),
    ("host_boot_id", "foreign-boot", "worker_origin_host_mismatch"),
])
def test_wire_identity_cannot_select_an_unregistered_host_or_key(key, context, field, value, error):
    payload = json.loads(_signed(key, context))
    payload[field] = value
    with pytest.raises(WorkerOriginError, match=f"^{error}$"):
        _verify(_wire(payload), key, context)


def test_wire_cannot_move_to_another_registered_worker(key, context):
    other = WorkerOriginKey("worker-2", "host-2", "boot-2", "key-2", b"x" * 32)
    payload = json.loads(_signed(key, context))
    payload.update(worker_id="worker-2", host_id="host-2", host_boot_id="boot-2", key_id="key-2")
    with pytest.raises(WorkerOriginError, match="^worker_origin_mac_invalid$"):
        _verify(_wire(payload), key, context, registry=WorkerOriginRegistry([key, other]))


def test_wrong_shared_secret_fails_real_hmac(key, context):
    changed = replace(key, secret_key=b"x" * 32)
    with pytest.raises(WorkerOriginError, match="^worker_origin_mac_invalid$"):
        _verify(_signed(key, context), changed, context)


def test_unknown_and_revoked_registry_entries_refuse(key, context):
    raw = _signed(key, context)
    with pytest.raises(WorkerOriginError, match="^worker_origin_worker_unknown$"):
        _verify(raw, key, context, registry=WorkerOriginRegistry([]))
    with pytest.raises(WorkerOriginError, match="^worker_origin_worker_revoked$"):
        _verify(raw, key, context, registry=WorkerOriginRegistry([replace(key, revoked=True)]))
    with pytest.raises(WorkerOriginError, match="^worker_origin_worker_revoked$"):
        _signed(replace(key, revoked=True), context)


@pytest.mark.parametrize("change", [
    {"controller_id": "foreign-controller"}, {"context_sha256": "f" * 64},
    {"controller_challenge": "d" * 64}, {"assignment_generation": 2},
])
def test_context_is_mac_covered_even_if_expected_input_was_wrong(key, context, change):
    payload = json.loads(_signed(key, context))
    payload.update(change)
    with pytest.raises(WorkerOriginError, match="^worker_origin_mac_invalid$"):
        _verify(_wire(payload), key, replace(context, **change))


def test_profile_and_actual_receipt_bytes_must_match(key, context):
    raw = _signed(key, context)
    with pytest.raises(WorkerOriginError, match="^worker_origin_profile_mismatch$"):
        _verify(raw, key, context, expected_profile_sha256="f" * 64)
    with pytest.raises(WorkerOriginError, match="^worker_origin_receipt_mismatch$"):
        _verify(raw, key, context, receipt=_RECEIPT.rstrip(b"\n"))


@pytest.mark.parametrize("field", ["profile_sha256", "receipt_sha256", "mac_sha256"])
def test_digest_fields_are_mac_covered(key, context, field):
    payload = json.loads(_signed(key, context))
    kwargs = {}
    if field == "profile_sha256":
        payload[field] = "f" * 64
        kwargs["expected_profile_sha256"] = "f" * 64
    elif field == "receipt_sha256":
        altered = b"altered receipt"
        payload[field] = hashlib.sha256(altered).hexdigest()
        kwargs["receipt"] = altered
    else:
        payload[field] = ("0" if payload[field][0] != "0" else "1") + payload[field][1:]
    with pytest.raises(WorkerOriginError, match="^worker_origin_mac_invalid$"):
        _verify(_wire(payload), key, context, **kwargs)


def test_mac_comparison_uses_stdlib_constant_time_primitive(key, context, monkeypatch):
    raw = _signed(key, context)
    original = hmac.compare_digest
    calls = []

    def compare(left, right):
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr("lunar_evolution.external_worker_origin.hmac.compare_digest", compare)
    _verify(raw, key, context)
    assert len(calls) == 1
    assert all(type(item) is str and len(item) == 64 for item in calls[0])


@pytest.mark.parametrize("mutation", ["extra", "missing", "version", "algorithm", "nested"])
def test_exact_wire_schema_refuses_extra_missing_or_unsupported_fields(key, context, mutation):
    payload = json.loads(_signed(key, context))
    if mutation == "extra":
        payload["source"] = "trusted because I say so"
    elif mutation == "missing":
        del payload["key_id"]
    elif mutation == "version":
        payload["schema_version"] = "lunar-external-worker-origin-v2"
    elif mutation == "algorithm":
        payload["algorithm"] = "none"
    else:
        payload["worker_id"] = {"name": "worker-1"}
    with pytest.raises(WorkerOriginError):
        _verify(_wire(payload), key, context)


def test_duplicate_keys_are_rejected_before_authentication(key, context):
    raw = _signed(key, context)
    duplicate = b'{"worker_id":"worker-1",' + raw[1:]
    with pytest.raises(WorkerOriginError, match="^worker_origin_wire_duplicate_key$"):
        _verify(duplicate, key, context)


@pytest.mark.parametrize("form", ["newline", "pretty", "unsorted", "escaped_unicode"])
def test_signed_values_require_original_canonical_bytes(key, context, form):
    key = replace(key, host_id="主机-1")
    raw = _signed(key, context)
    if form == "newline":
        altered = raw + b"\n"
    elif form == "pretty":
        altered = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, indent=2).encode()
    elif form == "unsorted":
        altered = _wire(json.loads(raw))
        payload = json.loads(altered)
        payload = dict(reversed(list(payload.items())))
        altered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    else:
        altered = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(WorkerOriginError, match="^worker_origin_wire_noncanonical$"):
        _verify(altered, key, context)


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b"null", b"\xff", b'{"x":NaN}',
    b"[" * 2000 + b"]" * 2000, b" " * (MAX_WORKER_ORIGIN_BYTES + 1),
])
def test_malformed_bounded_wire_refuses(key, context, raw):
    with pytest.raises(WorkerOriginError):
        _verify(raw, key, context)


@pytest.mark.parametrize(("field", "value"), [
    ("assignment_generation", True), ("assignment_generation", 0),
    ("assignment_generation", 1.0), ("assignment_generation", 1 << 63),
    ("controller_challenge", "a" * 63), ("controller_challenge", "A" * 64),
    ("controller_challenge", "not-random"), ("context_sha256", "g" * 64),
    ("context_kind", "source-says-trusted"), ("run_id", ""),
    ("task_id", "bad\nidentity"), ("episode_id", "界" * 86),
])
def test_invalid_context_refuses_before_signing(context, field, value):
    with pytest.raises(WorkerOriginError):
        replace(context, **{field: value})


@pytest.mark.parametrize("value", [None, [], {}, {"run_id": "run-1"}])
def test_context_parser_requires_exact_original_fields(value):
    with pytest.raises(WorkerOriginError, match="^worker_origin_context_fields_invalid$"):
        WorkerOriginContext.from_dict(value)


def test_context_parser_rejects_additional_claimed_authority(context):
    value = context.to_dict()
    value["cleanup_confirmed"] = True
    with pytest.raises(WorkerOriginError, match="^worker_origin_context_fields_invalid$"):
        WorkerOriginContext.from_dict(value)


@pytest.mark.parametrize("secret", [b"", b"x" * 31, b"x" * 4097, "x" * 32, bytearray(b"x" * 32)])
def test_keys_require_bounded_immutable_secret_bytes(secret):
    with pytest.raises(WorkerOriginError, match="^worker_origin_secret_invalid$"):
        WorkerOriginKey("worker-1", "host-1", "boot-1", "key-1", secret)


@pytest.mark.parametrize("kind", ["worker", "key", "secret"])
def test_registry_refuses_duplicate_identity_and_cross_worker_secret_reuse(key, kind):
    if kind == "worker":
        second = replace(key, key_id="key-2", secret_key=b"x" * 32)
        error = "worker_origin_registry_duplicate"
    elif kind == "key":
        second = replace(key, worker_id="worker-2", secret_key=b"x" * 32)
        error = "worker_origin_registry_duplicate"
    else:
        second = replace(key, worker_id="worker-2", key_id="key-2")
        error = "worker_origin_registry_secret_reused"
    with pytest.raises(WorkerOriginError, match=f"^{error}$"):
        WorkerOriginRegistry([key, second])


def test_registry_detaches_caller_key_object(key, context):
    raw = _signed(key, context)
    registry = WorkerOriginRegistry([key])
    object.__setattr__(key, "secret_key", b"x" * 32)
    object.__setattr__(key, "host_id", "foreign-host")
    result = _verify(raw, key, context, registry=registry)
    assert result.host_id == "host-1"


def test_secret_never_enters_repr_wire_projection_or_errors(key, context):
    registry = WorkerOriginRegistry([key])
    raw = _signed(key, context)
    result = _verify(raw, key, context, registry=registry)
    visible = repr(key) + repr(registry) + repr(result) + json.dumps(result.to_dict())
    with pytest.raises(WorkerOriginError) as caught:
        _verify(raw, key, context, registry=WorkerOriginRegistry([replace(key, revoked=True)]))
    visible += repr(caught.value)
    assert _SECRET.decode() not in visible
    assert _SECRET not in raw
    assert "secret_key" not in visible


@pytest.mark.parametrize("receipt", [b"", bytearray(b"receipt"), "receipt", b"x" * (
    MAX_WORKER_ORIGIN_RECEIPT_BYTES + 1
)])
def test_receipt_limit_applies_to_signing_and_verification(key, context, receipt):
    raw = _signed(key, context)
    with pytest.raises(WorkerOriginError, match="^worker_origin_receipt_invalid$"):
        sign_worker_origin(key=key, context=context, profile_sha256=_PROFILE, receipt=receipt)
    with pytest.raises(WorkerOriginError, match="^worker_origin_receipt_invalid$"):
        _verify(raw, key, context, receipt=receipt)


def test_receipt_boundary_accepts_exact_maximum_without_exporting_bytes(key, context):
    receipt = b"x" * MAX_WORKER_ORIGIN_RECEIPT_BYTES
    raw = sign_worker_origin(key=key, context=context, profile_sha256=_PROFILE, receipt=receipt)
    result = _verify(raw, key, context, receipt=receipt)
    assert result.receipt_sha256 == hashlib.sha256(receipt).hexdigest()
    assert len(raw) < MAX_WORKER_ORIGIN_BYTES
