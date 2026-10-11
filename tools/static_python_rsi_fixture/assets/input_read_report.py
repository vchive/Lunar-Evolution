"""Uninstalled fixed two-path prototype; bytes are not launch or result authority."""


def read_input_report(manifest_sha256):
    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64
            or any(character not in "0123456789abcdef" for character in manifest_sha256)):
        raise ValueError("static_python_rsi_input_report_marker_invalid")
    with open("../.rsi-input/request.json", "rb") as source:
        request = source.read(131073)
    if type(request) is not bytes or not 0 < len(request) <= 131072:
        raise ValueError("static_python_rsi_input_report_request_invalid")
    with open("../.rsi-input/memory.json", "rb") as source:
        memory = source.read(131073)
    if type(memory) is not bytes or not 0 < len(memory) <= 131072:
        raise ValueError("static_python_rsi_input_report_memory_invalid")
    computed = sum(number * number for number in range(1, 10))
    if computed != 285:
        raise RuntimeError("static_python_rsi_input_report_computation_invalid")
    # Fixed keys and hex-only dynamic fields need no external JSON module. No
    # input text is interpolated directly and nothing is written or dispatched.
    return (
        '{"claims":{"input_authority_verified":false,"memory_use_verified":false,'
        '"production_admission":false,"runtime_execution_verified":false,'
        '"solver_result_accepted":false},"computed":285,"manifest_sha256":"'
        + manifest_sha256 + '","memory_hex":"' + memory.hex()
        + '","request_hex":"' + request.hex()
        + '","schema":"lunar-static-python-rsi-input-read-report-v1"}\n'
    ).encode("ascii")
