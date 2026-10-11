"""Appended to the original reviewed encoder; metadata syntax only, no input read."""


def _rsi_launch(manifest_sha256):
    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64
            or any(character not in "0123456789abcdef" for character in manifest_sha256)):
        raise ValueError("invalid RSI manifest digest syntax")
    return _main("baseline")  # noqa: F821 -- original reviewed encoder is prepended
