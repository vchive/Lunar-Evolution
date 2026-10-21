"""Bounded, provider-free Python AST import observations over pinned bytes.

This module never executes source and never reads or writes a path. Its output
records syntax-level observations only; it is not an exhaustive import graph.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from _codecs import utf_8_decode as _utf_8_decode
from dataclasses import dataclass
from typing import NoReturn

IMPORT_AUDIT_SCHEMA = "lunar-static-python-import-audit-v1"
MAX_SOURCE_MODULES = 256
MAX_SOURCE_BYTES = 256 * 1024
MAX_TOTAL_SOURCE_BYTES = 4 * 1024 * 1024
MAX_AST_NODES_PER_SOURCE = 20_000
MAX_TOTAL_AST_NODES = 100_000
MAX_AST_DEPTH = 128
MAX_IMPORT_SITES = 2_048
MAX_OUTPUT_BYTES = 256 * 1024

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")
_UTF8_CODING_COOKIE = re.compile(
    br"^[ \t\f]*#.*?coding[:=][ \t]*([-_.a-zA-Z0-9]+)", re.ASCII
)
_CLAIMS = {
    "source_graph_verified": False,
    "configured_closure_verified": False,
    "build_performed": False,
    "runtime_startup_performed": False,
    "installation_accepted": False,
    "runtime_load_protection": False,
    "general_code_origin_protection": False,
    "production_admission": False,
}
_REFUSALS = frozenset({
    "invalid", "shape", "module", "digest", "bounds", "budget", "encoding",
    "syntax", "target", "wire",
})


class StaticPythonImportAuditError(ValueError):
    """Fixed context-free refusal code for a caller-supplied source set."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in _REFUSALS:
            reason = "invalid"
        self.reason = "static_python_import_audit_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _module_name(value: object) -> str:
    if (type(value) is not str or not value.isascii() or len(value) > 128
            or _MODULE_NAME.fullmatch(value) is None):
        _fail("module")
    return value


def _digest(value: object) -> str:
    if (type(value) is not str or len(value) != 64 or _SHA.fullmatch(value) is None
            or value in {"0" * 64, "f" * 64}):
        _fail("digest")
    return value


def _decode_source(raw: bytes) -> str:
    """Accept the UTF-8 source subset without consulting codec search hooks."""
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    first_lines = body.splitlines()[:2]
    for line in first_lines:
        match = _UTF8_CODING_COOKIE.match(line)
        if match is not None and match.group(1).lower().replace(b"_", b"-") not in {
            b"utf-8", b"utf8", b"utf-8-sig",
        }:
            _fail("encoding")
    try:
        decoded, consumed = _utf_8_decode(body, "strict", True)
        if consumed != len(body):
            _fail("encoding")
        return decoded
    except (UnicodeError, ValueError):
        _fail("encoding")


def _walk_bounded(tree: ast.AST) -> tuple[list[ast.AST], int]:
    nodes: list[ast.AST] = []
    pending: list[tuple[ast.AST, int]] = [(tree, 0)]
    while pending:
        node, depth = pending.pop()
        nodes.append(node)
        if len(nodes) > MAX_AST_NODES_PER_SOURCE or depth > MAX_AST_DEPTH:
            _fail("budget")
        children = list(ast.iter_child_nodes(node))
        pending.extend((child, depth + 1) for child in reversed(children))
    return nodes, len(nodes)


def _source_import_name(source_name: str) -> str:
    if source_name.endswith(".__init__"):
        return source_name[:-len(".__init__")]
    return source_name


def _package_for_source(source_name: str, package_sources: frozenset[str]) -> str | None:
    if source_name.endswith(".__init__"):
        return _source_import_name(source_name)
    parent = source_name.rpartition(".")[0]
    if parent and parent + ".__init__" in package_sources:
        return parent
    return None


def _relative_target(
    package: str | None, level: int, module: str | None,
    package_sources: frozenset[str],
) -> str | None:
    if package is None or level < 1:
        return None
    if package + ".__init__" not in package_sources:
        return None
    parts = package.split(".")
    if level > len(parts):
        return None
    keep = len(parts) - level + 1
    root = parts[:keep]
    if not root or ".".join(root) + ".__init__" not in package_sources:
        return None
    if module:
        root.extend(module.split("."))
    target = ".".join(root)
    if not target or _MODULE_NAME.fullmatch(target) is None:
        return None
    return target


def _attribute_candidate(base: str, name: str) -> str | None:
    candidate = base + "." + name
    if _MODULE_NAME.fullmatch(candidate) is None:
        return None
    return candidate


def _literal_string(node: ast.AST) -> str | None:
    if type(node) is ast.Constant and type(node.value) is str:
        return node.value
    return None


def _canonical_bytes(value: dict) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail("wire")


@dataclass(frozen=True, slots=True)
class StaticPythonImportAudit:
    """Immutable canonical AST-observation record with no source text."""

    wire_bytes: bytes
    source_count: int
    import_count: int
    unresolved_count: int
    unsupported_count: int

    def to_dict(self) -> dict:
        """Return a detached copy of the canonical wire."""
        return json.loads(self.wire_bytes)


def audit_static_python_imports(
    sources: dict[str, bytes],
    *,
    expected_source_sha256: dict[str, str],
) -> StaticPythonImportAudit:
    """Observe imports from caller-supplied, independently pinned UTF-8 bytes.

    Package initializer bytes use the explicit source key ``pkg.__init__``;
    this is the only input that establishes package context for relative imports.
    The function does not inspect an installation inventory or require imported
    targets to be in ``sources``. Targets absent from the supplied bytes can still
    be unambiguously named by a static import statement.
    """
    try:
        if type(sources) is not dict or type(expected_source_sha256) is not dict:
            _fail("shape")
        if not 1 <= len(sources) <= MAX_SOURCE_MODULES:
            _fail("bounds")
        if len(expected_source_sha256) != len(sources):
            _fail("shape")

        normalized: dict[str, bytes] = {}
        import_names: dict[str, str] = {}
        packages: set[str] = set()
        total_bytes = 0
        for raw_name, raw_source in sources.items():
            name = _module_name(raw_name)
            if type(raw_source) is not bytes:
                _fail("shape")
            if len(raw_source) > MAX_SOURCE_BYTES:
                _fail("budget")
            total_bytes += len(raw_source)
            if total_bytes > MAX_TOTAL_SOURCE_BYTES:
                _fail("budget")
            normalized[name] = raw_source
            import_name = _source_import_name(name)
            if not import_name:
                _fail("module")
            if import_name in import_names:
                _fail("module")
            import_names[import_name] = name
            if name.endswith(".__init__"):
                packages.add(name)

        pins: dict[str, str] = {}
        for raw_name, raw_digest in expected_source_sha256.items():
            name = _module_name(raw_name)
            if name not in normalized:
                _fail("shape")
            pins[name] = _digest(raw_digest)
        if set(pins) != set(normalized):
            _fail("shape")

        for name in sorted(normalized):
            if hashlib.sha256(normalized[name]).hexdigest() != pins[name]:
                _fail("digest")

        edge_set: set[tuple[str, str, str]] = set()
        unresolved: set[tuple[str, int, int, str]] = set()
        unsupported: set[tuple[str, int, int, str]] = set()
        total_nodes = 0
        total_sites = 0
        package_set = frozenset(packages)

        for source_key in sorted(normalized):
            source_module = _source_import_name(source_key)
            package = _package_for_source(source_key, package_set)
            text = _decode_source(normalized[source_key])
            try:
                tree = ast.parse(text, filename="<pinned-source>", mode="exec")
            except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError):
                _fail("syntax")
            nodes, node_count = _walk_bounded(tree)
            total_nodes += node_count
            if total_nodes > MAX_TOTAL_AST_NODES:
                _fail("budget")

            importlib_aliases: set[str] = {"importlib"}
            import_module_aliases: set[str] = {"import_module"}
            builtin_import_aliases: set[str] = {"__import__"}
            builtin_module_aliases: set[str] = {"builtins"}
            for node in nodes:
                if isinstance(node, ast.Import):
                    for item in node.names:
                        if item.name == "builtins":
                            builtin_module_aliases.add(item.asname or "builtins")
                        if item.name == "importlib" or item.name.startswith("importlib."):
                            importlib_aliases.add(
                                item.asname or ("importlib" if item.name != "importlib" else item.name)
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module == "importlib":
                        for item in node.names:
                            if item.name == "import_module":
                                import_module_aliases.add(item.asname or item.name)
                    if node.level == 0 and node.module == "builtins":
                        for item in node.names:
                            if item.name == "__import__":
                                builtin_import_aliases.add(item.asname or item.name)

            for node in nodes:
                if isinstance(node, ast.Import):
                    total_sites += 1
                    if total_sites > MAX_IMPORT_SITES:
                        _fail("budget")
                    for item in node.names:
                        target = item.name
                        if _MODULE_NAME.fullmatch(target) is None:
                            unresolved.add((source_module, node.lineno, node.col_offset,
                                            "invalid-import-target"))
                        else:
                            edge_set.add((source_module, target, "import"))
                elif isinstance(node, ast.ImportFrom):
                    total_sites += 1
                    if total_sites > MAX_IMPORT_SITES:
                        _fail("budget")
                    if node.level == 0:
                        base = node.module or ""
                    else:
                        base = _relative_target(package, node.level, node.module, package_set)
                    if not base or _MODULE_NAME.fullmatch(base) is None:
                        unresolved.add((source_module, node.lineno, node.col_offset,
                                        "relative-import-unresolved"))
                        continue
                    edge_set.add((source_module, base, "from-import"))
                    for item in node.names:
                        if item.name == "*":
                            unsupported.add((source_module, node.lineno, node.col_offset,
                                             "star-import"))
                            continue
                        candidate = _attribute_candidate(base, item.name)
                        if candidate in import_names:
                            edge_set.add((source_module, candidate, "from-import"))

                if not isinstance(node, ast.Call):
                    continue
                total_sites += 1
                if total_sites > MAX_IMPORT_SITES:
                    _fail("budget")
                function = node.func
                is_builtin_import = (
                    isinstance(function, ast.Name)
                    and function.id in builtin_import_aliases
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr == "__import__"
                    and isinstance(function.value, ast.Name)
                    and function.value.id in builtin_module_aliases
                )
                is_import_module = (
                    isinstance(function, ast.Name)
                    and function.id in import_module_aliases
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr == "import_module"
                )
                if is_builtin_import:
                    literal = _literal_string(node.args[0]) if node.args else None
                    if literal is None or len(node.args) != 1 or node.keywords:
                        unsupported.add((source_module, node.lineno, node.col_offset,
                                         "dynamic-import"))
                    elif _MODULE_NAME.fullmatch(literal) is None:
                        unresolved.add((source_module, node.lineno, node.col_offset,
                                        "invalid-import-target"))
                    else:
                        edge_set.add((source_module, literal, "literal-import"))
                elif is_import_module:
                    recognized_receiver = isinstance(function, ast.Name) or (
                        isinstance(function, ast.Attribute)
                        and isinstance(function.value, ast.Name)
                        and function.value.id in importlib_aliases
                    )
                    literal = _literal_string(node.args[0]) if node.args else None
                    package_arg = None
                    if len(node.args) >= 2:
                        package_arg = _literal_string(node.args[1])
                    keyword_shape_ok = True
                    for keyword in node.keywords:
                        if keyword.arg == "package" and len(node.args) < 2:
                            package_arg = _literal_string(keyword.value)
                        else:
                            keyword_shape_ok = False
                    if (not recognized_receiver or literal is None or len(node.args) > 2
                            or not keyword_shape_ok):
                        unsupported.add((source_module, node.lineno, node.col_offset,
                                         "dynamic-import"))
                    elif literal.startswith("."):
                        target = _relative_target(
                            package_arg,
                            len(literal) - len(literal.lstrip(".")),
                            literal.lstrip("."),
                            package_set,
                        )
                        if target is None:
                            unresolved.add((source_module, node.lineno, node.col_offset,
                                            "relative-import-unresolved"))
                        else:
                            edge_set.add((source_module, target, "literal-import"))
                    elif _MODULE_NAME.fullmatch(literal) is None:
                        unresolved.add((source_module, node.lineno, node.col_offset,
                                        "invalid-import-target"))
                    else:
                        edge_set.add((source_module, literal, "literal-import"))
                elif isinstance(function, ast.Name) and function.id in {"eval", "exec", "compile"}:
                    unsupported.add((source_module, node.lineno, node.col_offset,
                                     "dynamic-code-execution"))

        edge_records = [
            {"source": source, "target": target, "kind": kind}
            for source, target, kind in sorted(edge_set)
        ]
        unresolved_records = [
            {"source": source, "line": line, "column": column, "reason": reason}
            for source, line, column, reason in sorted(unresolved)
        ]
        unsupported_records = [
            {"source": source, "line": line, "column": column, "reason": reason}
            for source, line, column, reason in sorted(unsupported)
        ]
        payload = {
            "schema": IMPORT_AUDIT_SCHEMA,
            "evidence_scope": "source-ast-import-observations-only",
            "sources": [
                {"name": name, "source_sha256": pins[name]}
                for name in sorted(normalized)
            ],
            "imports": edge_records,
            "unresolved_imports": unresolved_records,
            "unsupported_import_sites": unsupported_records,
            "claims": dict(_CLAIMS),
        }
        wire = _canonical_bytes(payload)
        if len(wire) > MAX_OUTPUT_BYTES:
            _fail("budget")
        return StaticPythonImportAudit(
            wire_bytes=wire,
            source_count=len(normalized),
            import_count=len(edge_records),
            unresolved_count=len(unresolved_records),
            unsupported_count=len(unsupported_records),
        )
    except _Refusal as exc:
        raise StaticPythonImportAuditError(exc.reason) from None
