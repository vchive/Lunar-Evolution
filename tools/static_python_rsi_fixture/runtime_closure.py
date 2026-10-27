"""Source-only finite frozen/native closure for the two fixed solver profiles.

No supplied Python source is imported or executed. Caller pins authenticate the
complete staged source inventories separately from build/runtime acceptance.
Dynamic imports and platform-dependent behavior still require sealed execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass

from tools.static_python_fixture.profile import (
    ALIASES,
    CONFIG,
    CORE_BUILTINS,
    FROZEN,
    STATIC_ADDITIONS,
)
from tools.static_python_fixture.tables import _CORE_INITIALIZERS

MAX_MODULES = 256
MAX_SOURCE_FILES = 16384
MAX_SOURCE_BYTES = 256 * 1024 * 1024
_PRODUCER_PINS = {
    "openevolve": "03266224f20d99aaef794cb8c9d8688f9ba8c1d44faf8c46b207c3780d4a6b06",
    "shinka": "5a6e716142cf71d944adbc7e1622cb1a147f7ef9eaba556e9bb1f707680ecffa",
}
# Exact C translation units, not configure's ambient optional-module discovery.
_NATIVE = {
    "_collections": ("_collectionsmodule.c",),
    "_functools": ("_functoolsmodule.c",),
    "_operator": ("_operator.c",),
    "_sre": ("_sre/sre.c",),
    "_stat": ("_stat.c",),
    "_struct": ("_struct.c",),
    "_json": ("_json.c",),
    "_typing": ("_typingmodule.c",),
    # typing/inspect/dis and traceback reach these even through function-local
    # imports. The latter two are CPython bootstrap modules; their supporting
    # implementation (including Python/tracemalloc.c) is already in core units.
    "_opcode": ("_opcode.c",),
    "_suggestions": ("_suggestions.c",),
    "_tracemalloc": ("_tracemalloc.c",),
    "_bisect": ("_bisectmodule.c",),
    "_heapq": ("_heapqmodule.c",),
    "_pickle": ("_pickle.c",),
    "_random": ("_randommodule.c",),
    "_contextvars": ("_contextvarsmodule.c",),
    "_statistics": ("_statisticsmodule.c",),
    "_locale": ("_localemodule.c",),
    "_datetime": ("_datetimemodule.c",),
    "unicodedata": ("unicodedata.c",),
    "pwd": ("pwdmodule.c",),
    "grp": ("grpmodule.c",),
    "fcntl": ("fcntlmodule.c",),
    "itertools": ("itertoolsmodule.c",),
    "errno": ("errnomodule.c",),
    "math": ("mathmodule.c",),
    "time": ("timemodule.c",),
    "select": ("selectmodule.c",),
    "binascii": ("binascii.c",),
    "_sha2": ("sha2module.c", "_hacl/Hacl_Hash_SHA2.c"),
}
_SQLITE = tuple("_sqlite/" + n + ".c" for n in (
    "blob", "connection", "cursor", "microprotocols", "module",
    "prepare_protocol", "row", "statement", "util",
))
# These may occur in guarded platform/accelerator imports. They are deliberately
# absent, never granted a host loader. Their callers must retain fallback paths.
_ABSENT = frozenset({
    "nt", "_winapi", "winreg", "msvcrt", "_overlapped", "_scproxy", "_wmi",
    "_hashlib", "_md5", "_sha1", "_sha3", "_blake2", "_decimal",
    "_posixsubprocess", "_socket", "_ssl",
    "java.lang",
})
# CPython 3.13's parent initializers publish these sys.modules aliases. There
# are no collections/abc.py or os/path.py source files to freeze. Keep their
# actual source module and parent initialization rather than inventing a shim.
_RUNTIME_ALIASES = {"collections.abc": "_collections_abc", "os.path": "posixpath"}
# Complete official Lib/platform.py from the independently pinned 3.13.12
# release above. This reviewed one-source exception is not a general callgraph.
_PLATFORM_JAVA_SOURCE_SHA256 = "75fe9b94662e55b91e19602bb75e6ca6132f7a53fb22844fc44a507a639127e1"
# Exact official imported-module demonstration/self-test/CLI sources only. These
# modules are imported by their canonical frozen names, never executed as main.
# A full source pin binds each sole private helper call to its false main guard.
_IMPORTED_SELFTEST_SOURCE_SHA256 = {
    "pickle": "8140370a0f3f23769cfb5e99546abf7a35bc0e286f2f81acb6e43a3544162302",
    "difflib": "0fc85357cdf45c242079be40245466b7b014b6f5f35064eec3d1b951e00d31ca",
    "pickletools": "bf882fd005a822076a08c1cd3415b96a74d0caab7d69610f31dbe35346917233",
    "heapq": "6d43277e5c76fc0f073cd388fcff852d14d068f6bb6d4886c340f8b75a1229a9",
    "inspect": "ea27c96e5b29fe29de8e3ee8840a50d6ff4b05f47cf911f4ee17cb0d4f953ca8",
}
# Finite reviewed helpers only; no arbitrary function or main-block pruning.
_IMPORTED_SELFTEST_FUNCTIONS = {
    "pickle": "_test", "difflib": "_test", "pickletools": "_test",
    "heapq": None, "inspect": "_main",
}
_INTERPRETER_PROVIDED = {
    "__main__": ("Python/pylifecycle.c", (
        b"status = add_main_module(interp);",
        b"add_main_module(PyInterpreterState *interp)",
        b"m = PyImport_AddModuleObject(&_Py_ID(__main__));",
    )),
}
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z")


class RuntimeClosureError(ValueError):
    """Fixed error without upstream source text or caller paths."""


def _fail(code: str) -> None:
    raise RuntimeClosureError("static_python_runtime_closure_" + code)


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(value: object) -> str:
    if (type(value) is not str or not 0 < len(value) <= 512
            or any(p in {"", ".", ".."} for p in value.split("/"))
            or any(ord(c) < 32 or ord(c) > 126 or c in "\\:" for c in value)):
        _fail("path_invalid")
    return value


def source_inventory(sources: dict[str, bytes]) -> bytes:
    """Return a complete deterministic source identity; not a trusted new pin."""
    if type(sources) is not dict or not 0 < len(sources) <= MAX_SOURCE_FILES:
        _fail("inventory_invalid")
    total = 0
    records = []
    for path, raw in sources.items():
        _path(path)
        if type(raw) is not bytes or len(raw) > 16 * 1024 * 1024:
            _fail("source_invalid")
        total += len(raw)
        if total > MAX_SOURCE_BYTES:
            _fail("source_budget_exceeded")
        records.append({"path": path, "size": len(raw), "sha256": _sha(raw)})
    return canonical(sorted(records, key=lambda r: r["path"]))


def _pinned_sources(sources: dict[str, bytes], expected: str) -> dict[str, bytes]:
    raw = source_inventory(sources)
    if type(expected) is not str or _sha(raw) != expected:
        _fail("inventory_pin_mismatch")
    return sources.copy()


@dataclass(frozen=True, slots=True)
class FixedRuntimeClosure:
    wire_bytes: bytes
    sources: tuple[tuple[str, bytes], ...]

    @property
    def sha256(self) -> str:
        return _sha(self.wire_bytes)


def _producer(solver: str, files: dict[str, bytes], manifest: bytes) -> dict[str, bytes]:
    if (type(solver) is not str or solver not in _PRODUCER_PINS
            or type(manifest) is not bytes or len(manifest) > 64 * 1024
            or _sha(manifest) != _PRODUCER_PINS[solver]):
        _fail("producer_pin_mismatch")
    facts = json.loads(manifest)
    records = facts["sources"]
    expected = {r["path"] for r in records} | {"LICENSE", "LICENSE.lunar"}
    if type(files) is not dict or set(files) != expected:
        _fail("producer_inventory_invalid")
    result = {}
    for record in records:
        raw = files[record["path"]]
        if (type(raw) is not bytes or len(raw) != record["result"]["bytes"]
                or _sha(raw) != record["result"]["sha256"]):
            _fail("producer_source_drift")
        result[record["module"]] = raw
    for key, path in (("upstream", "LICENSE"), ("lunar", "LICENSE.lunar")):
        expected = facts["license"][key]["result"]
        raw = files[path]
        if type(raw) is not bytes or len(raw) != expected["bytes"] or _sha(raw) != expected["sha256"]:
            _fail("producer_license_drift")
    return result


def _platform_java_guard(tree: ast.Module, module: str, raw: bytes) -> dict | None:
    """Prove only CPython platform.py's private Jython helper import guard.

    Literal external references fail closed across every selected source module.
    Dynamic reflection is not proved here and remains explicitly unverified.
    """
    helper = "_java_getprop"
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == helper
                or isinstance(node, ast.Constant) and node.value == helper
                or isinstance(node, ast.ImportFrom) and node.module == "platform"
                and any(alias.name == helper for alias in node.names)):
            _fail("platform_helper_reference_invalid")
    if module != "platform":
        if any(isinstance(node, ast.Name) and node.id == helper for node in ast.walk(tree)):
            _fail("platform_helper_reference_invalid")
        return None
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == helper]
    if not helpers:
        return None
    if _sha(raw) != _PLATFORM_JAVA_SOURCE_SHA256:
        _fail("platform_helper_source_drift")
    # The full source pin binds the reviewed sole caller, no alias/rebinding or
    # module-level call, exact helper import and preceding returning guard.
    # AST below locates evidence only; it does not authorize a different source.
    caller = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "java_ver")
    guards = [node for node in caller.body if isinstance(node, ast.Try)
              and len(node.body) == len(node.handlers) == 1 and not node.orelse and not node.finalbody
              and isinstance(node.body[0], ast.Import)
              and [(alias.name, alias.asname) for alias in node.body[0].names] == [("java.lang", None)]
              and isinstance(node.handlers[0].type, ast.Name)
              and node.handlers[0].type.id == "ImportError" and node.handlers[0].name is None
              and len(node.handlers[0].body) == 1 and isinstance(node.handlers[0].body[0], ast.Return)]
    if len(guards) != 1:
        return None
    guard = guards[0]
    calls = sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == helper
                for node in ast.walk(caller))
    return {"module": "platform", "function": helper, "caller": "java_ver", "import": "java.lang",
            "guard": "prior-try-import-except-ImportError-return", "guard_lineno": guard.lineno,
            "literal_call_count": calls, "dynamic_reflection_verified": False}


def _imported_selftest_guard(
    tree: ast.Module, module: str, raw: bytes,
) -> tuple[set[int], dict | None]:
    """Exclude five exact imported-only demos/CLI, not arbitrary functions.

    Source identity binds the finite call/reference inventory. Every selected
    module is also checked for literal external private-helper references.
    Dynamic reflection and complete runtime reachability remain unverified.
    """
    private_helpers = {name for name in _IMPORTED_SELFTEST_FUNCTIONS.values() if name is not None}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr in private_helpers
                or isinstance(node, ast.Constant) and type(node.value) is str
                and node.value in private_helpers
                or isinstance(node, ast.ImportFrom) and node.module in _IMPORTED_SELFTEST_SOURCE_SHA256
                and any(alias.name in private_helpers | {"*"} for alias in node.names)):
            _fail("selftest_helper_reference_invalid")
    if module not in _IMPORTED_SELFTEST_SOURCE_SHA256:
        return set(), None
    function = _IMPORTED_SELFTEST_FUNCTIONS[module]
    helpers = [node for node in tree.body
               if isinstance(node, ast.FunctionDef)
               and (node.name == function if function is not None else node.name in private_helpers)]
    guards = [node for node in tree.body if isinstance(node, ast.If)
              and isinstance(node.test, ast.Compare)
              and len(node.test.ops) == len(node.test.comparators) == 1
              and isinstance(node.test.ops[0], ast.Eq)
              and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
              and isinstance(node.test.comparators[0], ast.Constant)
              and node.test.comparators[0].value == "__main__"]
    if not helpers and not guards:
        return set(), None
    if _sha(raw) != _IMPORTED_SELFTEST_SOURCE_SHA256[module]:
        _fail("selftest_source_drift")
    if len(guards) != 1 or guards[0].orelse:
        _fail("selftest_main_guard_invalid")
    guard = guards[0]
    excluded = {id(guard)}
    call_line = None
    if function is not None:
        if len(helpers) != 1:
            _fail("selftest_helper_invalid")
        helper = helpers[0]
        references = [node for node in ast.walk(tree)
                      if isinstance(node, ast.Name) and node.id == function]
        calls = [node for node in ast.walk(guard) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == function]
        if (len(references) != 1 or len(calls) != 1 or references[0] is not calls[0].func
                or not isinstance(references[0].ctx, ast.Load)
                or helper.decorator_list or helper.args.args or helper.args.posonlyargs
                or helper.args.kwonlyargs or helper.args.vararg or helper.args.kwarg):
            _fail("selftest_helper_reference_invalid")
        excluded.add(id(helper))
        call_line = calls[0].lineno
    elif helpers:
        _fail("selftest_helper_invalid")
    return excluded, {"module": module, "module_source_sha256": _sha(raw),
                      "guard": "canonical-imported-module-not-main", "guard_lineno": guard.lineno,
                      "function": function,
                      "literal_call_count": 1 if call_line is not None else 0,
                      "call_lineno": call_line, "dynamic_reflection_verified": False}


def _imports(raw: bytes, module: str, package: bool, available: set[str],
             builtin: set[str], guarded_calls: list[dict], excluded_selftests: list[dict]) -> set[str]:
    try:
        tree = ast.parse(raw)
    except (ValueError, SyntaxError, UnicodeError, RecursionError):
        _fail("source_syntax_invalid")
    result = set()
    excluded_nodes, selftest_guard = _imported_selftest_guard(tree, module, raw)
    if selftest_guard is not None:
        excluded_selftests.append(selftest_guard)
    java_guard = _platform_java_guard(tree, module, raw)
    if java_guard is not None:
        guarded_calls.append({**java_guard, "module_source_sha256": _sha(raw)})
    # os.py selects posix/nt using `_names = sys.builtin_module_names`, not a
    # sys.platform comparison. Recognize only that actual single binding; an
    # unknown/rebound `_names` never grants platform-branch pruning.
    os_builtin_names = module == "os" and sum(
        isinstance(node, ast.Name) and node.id == "_names" and isinstance(node.ctx, ast.Store)
        for node in ast.walk(tree)
    ) == 1 and any(
        isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_names"
        and isinstance(node.value, ast.Attribute) and node.value.attr == "builtin_module_names"
        and isinstance(node.value.value, ast.Name) and node.value.value.id == "sys"
        for node in tree.body
    )
    module_nodes = []

    def module_walk(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        module_nodes.append(node)
        for child in ast.iter_child_nodes(node):
            module_walk(child)

    module_walk(tree)
    name_stores = {id(node) for node in module_nodes if isinstance(node, ast.Name)
                   and node.id == "name" and isinstance(node.ctx, (ast.Store, ast.Del))}

    def branch_name_store(body, value):
        stores = [node.targets[0] for node in body
                  if isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "name"
                  and isinstance(node.value, ast.Constant) and node.value.value == value]
        return stores[0] if len(stores) == 1 else None

    def builtin_branch(node, value):
        return (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
                and isinstance(node.ops[0], ast.In) and isinstance(node.left, ast.Constant)
                and node.left.value == value and isinstance(node.comparators[0], ast.Name)
                and node.comparators[0].id == "_names")

    os_posix_name_line = None
    if os_builtin_names and "posix" in builtin and "nt" not in builtin:
        for node in tree.body:
            if (not isinstance(node, ast.If) or not builtin_branch(node.test, "posix")
                    or len(node.orelse) != 1 or not isinstance(node.orelse[0], ast.If)
                    or not builtin_branch(node.orelse[0].test, "nt")):
                continue
            posix_store = branch_name_store(node.body, "posix")
            nt_store = branch_name_store(node.orelse[0].body, "nt")
            if (posix_store is not None and nt_store is not None
                    and name_stores == {id(posix_store), id(nt_store)}):
                os_posix_name_line = node.lineno
    top_level_tests = {id(node.test) for node in tree.body if isinstance(node, ast.If)}

    def platform_test(node):
        if isinstance(node, ast.Name) and node.id in {"_MS_WINDOWS", "_WINDOWS"}:
            return False
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = platform_test(node.operand)
            return None if value is None else not value
        if (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
                and os_posix_name_line is not None and node.lineno > os_posix_name_line
                and id(node) in top_level_tests and isinstance(node.left, ast.Name)
                and node.left.id == "name" and isinstance(node.comparators[0], ast.Constant)
                and type(node.comparators[0].value) is str):
            if isinstance(node.ops[0], ast.Eq):
                return "posix" == node.comparators[0].value
            if isinstance(node.ops[0], ast.NotEq):
                return "posix" != node.comparators[0].value
        if (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
                and os_builtin_names and isinstance(node.left, ast.Constant)
                and type(node.left.value) is str and isinstance(node.comparators[0], ast.Name)
                and node.comparators[0].id == "_names"):
            if isinstance(node.ops[0], ast.In):
                return node.left.value in builtin
            if isinstance(node.ops[0], ast.NotIn):
                return node.left.value not in builtin
        if (isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1
                and isinstance(node.left, ast.Attribute) and isinstance(node.left.value, ast.Name)
                and isinstance(node.comparators[0], ast.Constant)):
            key = (node.left.value.id, node.left.attr)
            values = {("sys", "platform"): "linux", ("_sys", "platform"): "linux",
                      ("os", "name"): "posix", ("_os", "name"): "posix"}
            if key in values and type(node.comparators[0].value) is str:
                if isinstance(node.ops[0], ast.Eq):
                    return values[key] == node.comparators[0].value
                if isinstance(node.ops[0], ast.NotEq):
                    return values[key] != node.comparators[0].value
        return None

    def visit(node, guarded=False):
        if id(node) in excluded_nodes:
            return
        if (java_guard is not None and isinstance(node, ast.FunctionDef)
                and node.name == java_guard["function"]):
            for child in node.body:
                visit(child, True)
            return
        if isinstance(node, ast.If):
            verdict = platform_test(node.test)
            for child in (node.body if verdict is True else node.orelse if verdict is False
                          else node.body + node.orelse):
                visit(child, guarded)
            return
        if isinstance(node, ast.Try):
            catches_import = any(
                isinstance(handler.type, ast.Name)
                and handler.type.id in {"ImportError", "ModuleNotFoundError", "Exception"}
                or isinstance(handler.type, ast.Tuple) and any(
                    isinstance(t, ast.Name) and t.id in {"ImportError", "ModuleNotFoundError", "Exception"}
                    for t in handler.type.elts
                ) for handler in node.handlers
            )
            for child in node.body:
                visit(child, guarded or catches_import)
            for child in node.handlers + node.orelse + node.finalbody:
                visit(child, guarded)
            return
        imports = set()
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".") if package else module.split(".")[:-1]
                if node.level > len(base):
                    _fail("relative_import_invalid")
                stem = ".".join(base[:len(base) - node.level + 1])
                stem += ("." + node.module) if node.module else ""
            else:
                stem = node.module or ""
            if stem:
                imports.add(stem)
                imports.update(stem + "." + a.name for a in node.names
                               if stem + "." + a.name in available)
        for name in imports:
            if name in _ABSENT and not guarded:
                _fail("unguarded_absent_import")
        result.update(imports)
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree)
    return result


def _tables(frozen: list[dict], native: dict[str, tuple[str, ...]]) -> dict[str, bytes]:
    names = [(n, i) for n, i, _ in _CORE_INITIALIZERS]
    names += [(n, "PyInit_" + n) for n in STATIC_ADDITIONS]
    names += [(n, "PyInit_" + n) for n in native]
    config = ['#include "Python.h"',
              *(f"extern PyObject *{i}(void);" for _, i in names if i != "NULL"),
              "struct _inittab _PyImport_Inittab[] = {",
              *(f'{{"{n}", {i}}},' for n, i in names), "{NULL,NULL}};", ""]
    lines = ['#include "Python.h"', '#include "pycore_import.h"', '#include <stdbool.h>',
             *(f'#include "frozen_modules/{r["generator_id"]}.h"' for r in frozen)]
    for table, records in (
        ("bootstrap", [r for r in frozen if r["name"] in {"_frozen_importlib", "_frozen_importlib_external"}]),
        ("stdlib", [r for r in frozen if r["name"] not in {"_frozen_importlib", "_frozen_importlib_external"}]),
        ("empty", []),
    ):
        lines.append(f"static const struct _frozen {table}[] = {{")
        for r in records:
            sym = "_Py_M__" + r["generator_id"].replace(".", "_")
            lines.append(f'{{"{r["name"]}",{sym},(int)sizeof({sym}),'
                         + ("true" if r["package"] else "false") + "},")
        lines.append("{NULL,NULL,0,false}};")
    lines += ["const struct _frozen *_PyImport_FrozenBootstrap=bootstrap;",
              "const struct _frozen *_PyImport_FrozenStdlib=stdlib;",
              "const struct _frozen *_PyImport_FrozenTest=empty;",
              "const struct _frozen *PyImport_FrozenModules=empty;",
              "static const struct _module_alias aliases[]={",
              *(f'{{"{a}","{b}"}},' for a, b in ALIASES), "{NULL,NULL}};",
              "const struct _module_alias *_PyImport_FrozenAliases=aliases;", ""]
    stdlib = sorted(({n.split('.')[0] for n in (r["name"] for r in frozen)}
                     | set(CORE_BUILTINS) | set(STATIC_ADDITIONS) | set(native))
                    - {"_lunar_static_main", "_lunar_fixture_pipe", "openevolve", "shinka"})
    metadata = ['static const char *_Py_stdlib_module_names[]={',
                *(f'"{n}",' for n in stdlib), "};", ""]
    return {"runtime/Modules/config.c": "\n".join(config).encode("ascii"),
            "runtime/Python/frozen.c": "\n".join(lines).encode("ascii"),
            "runtime/Python/stdlib_module_names.h": "\n".join(metadata).encode("ascii")}


def prepare_fixed_runtime_closure(
    *, solver: str, cpython_sources: dict[str, bytes], expected_cpython_inventory_sha256: str,
    producer_files: dict[str, bytes], producer_manifest: bytes,
    sqlite_sources: dict[str, bytes] | None = None,
    expected_sqlite_inventory_sha256: str | None = None,
) -> FixedRuntimeClosure:
    """Resolve supplied source imports and emit real C tables/pending freezer jobs.

    The independently pinned CPython map must be the reviewed, patched source
    tree. SQLite is an explicit extra source input, never host libsqlite3. The
    returned new profile is not accepted by legacy nine-header DTOs implicitly.
    """
    cpython = _pinned_sources(cpython_sources, expected_cpython_inventory_sha256)
    modules = _producer(solver, producer_files, producer_manifest)
    paths = {}
    packages = set()
    for path, raw in cpython.items():
        if not path.startswith("Lib/") or not path.endswith(".py"):
            continue
        relative = path[4:-3]
        package = relative.endswith("/__init__")
        name = relative.removesuffix("/__init__").replace("/", ".")
        if _NAME.fullmatch(name) is None or name.startswith(("test.", "idlelib.", "tkinter.")):
            continue
        if package:
            packages.add(name)
        paths[name] = path
    for name in modules:
        paths[name] = "producer/" + name.replace(".", "/") + ("/__init__.py" if name in {
            solver, solver + ".utils", solver + ".prompt", solver + ".prompts", solver + ".edit",
        } else ".py")
        if paths[name].endswith("/__init__.py"):
            packages.add(name)
    native = dict(_NATIVE)
    extra = {}
    sqlite_pin = None
    if solver == "shinka":
        native.update({"_datetime": ("_datetimemodule.c",), "_sqlite3": _SQLITE})
        sql = _pinned_sources(sqlite_sources, expected_sqlite_inventory_sha256)
        if set(sql) != {"sqlite3.c", "sqlite3.h"}:
            _fail("sqlite_inventory_invalid")
        version = re.search(rb"#define\s+SQLITE_VERSION_NUMBER\s+(\d+)", sql["sqlite3.h"])
        if (version is None or not 3035000 <= int(version[1]) < 4000000
                or b"sqlite3_serialize(" not in sql["sqlite3.h"]
                or b"sqlite3_deserialize(" not in sql["sqlite3.h"]):
            _fail("sqlite_serialization_required")
        extra = {"sqlite/" + p: raw for p, raw in sql.items()}
        sqlite_pin = expected_sqlite_inventory_sha256
    elif sqlite_sources is not None or expected_sqlite_inventory_sha256 is not None:
        _fail("sqlite_not_required")
    builtin = set(CORE_BUILTINS) | set(STATIC_ADDITIONS) | set(native)
    selected = {}
    absent = set()
    pending = {solver + ".lunar_fixed", "importlib", "encodings", "encodings.utf_8"}
    pending.update(generator for _name, generator, _path, _package in FROZEN
                   if generator != "_lunar_static_main")
    # Native datetime imports this helper by name; UTF-8 is explicitly fixed.
    if solver == "shinka":
        pending.update({"sqlite3", "datetime", "_strptime"})
    aliases = {"importlib._bootstrap": "_frozen_importlib",
               "importlib._bootstrap_external": "_frozen_importlib_external"}
    reverse_aliases = {value: key for key, value in aliases.items()}
    runtime_aliases = set()
    interpreter_modules = {}
    guarded_calls = []
    excluded_selftests = []
    while pending:
        pending_name = min(pending)
        pending.remove(pending_name)
        name = reverse_aliases.get(pending_name, pending_name)
        if name in _RUNTIME_ALIASES:
            if name in paths:
                _fail("runtime_alias_source_conflict")
            runtime_aliases.add(name)
            pending.add(name.rpartition(".")[0])
            name = _RUNTIME_ALIASES[name]
        if name in selected or name in builtin:
            continue
        if name in _INTERPRETER_PROVIDED:
            if name in paths:
                _fail("interpreter_module_source_conflict")
            path, anchors = _INTERPRETER_PROVIDED[name]
            raw = cpython.get(path)
            if (type(raw) is not bytes or any(anchor not in raw for anchor in anchors)
                    or CONFIG.get("_init_main") != 1):
                _fail("interpreter_module_source_invalid")
            interpreter_modules[name] = {
                "name": name, "kind": "interpreter-lifecycle", "source": path,
                "source_size": len(raw), "source_sha256": _sha(raw),
                "creation_function": "add_main_module", "startup_api": "Py_InitializeFromConfig",
                "required_init_main": 1,
            }
            continue
        if name in _ABSENT:
            absent.add(name)
            continue
        if name not in paths:
            _fail("unresolved_import")
        path = paths[name]
        raw = modules[name] if name in modules else cpython[path]
        selected[name] = (path, raw)
        if len(selected) > MAX_MODULES:
            _fail("module_budget_exceeded")
        pending.update(_imports(raw, name, name in packages, set(paths) | set(_RUNTIME_ALIASES),
                                builtin, guarded_calls, excluded_selftests))
        parent = name.rpartition(".")[0]
        if parent:
            pending.add(parent)
    generated = dict(extra)
    for name, (path, raw) in selected.items():
        if name in modules:
            generated[path] = raw
    launcher = (
        'def _rsi_launch(manifest_sha256):\n'
        '    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64\n'
        '            or any(c not in "0123456789abcdef" for c in manifest_sha256)):\n'
        '        raise ValueError("invalid RSI manifest digest syntax")\n'
        f'    from {solver}.lunar_fixed import main\n'
        '    return main(["--lunar-rsi-input-v1", manifest_sha256])\n'
    ).encode("ascii")
    generated["runtime/frozen_main.py"] = launcher
    selected["_lunar_static_main"] = ("runtime/frozen_main.py", launcher)
    # Preserve the original nine logical jobs, with the new version's main.
    for name, generator, path, package in FROZEN:
        canonical_name = {v: k for k, v in aliases.items()}.get(name, name)
        if name == "_lunar_static_main":
            continue
        if path not in cpython:
            _fail("bootstrap_source_missing")
        selected[canonical_name] = (path, cpython[path])
        if package:
            packages.add(canonical_name)
    frozen = []
    symbols = set()
    for name, (path, raw) in sorted(selected.items()):
        generator = name
        symbol = generator.replace(".", "_")
        if symbol in symbols:
            _fail("frozen_symbol_collision")
        symbols.add(symbol)
        frozen.append({"name": aliases.get(name, name), "generator_id": generator,
                       "source": path, "source_size": len(raw), "source_sha256": _sha(raw),
                       "output": "generated-sources/Python/frozen_modules/" + generator + ".h",
                       "package": name in packages})
    units = []
    for name, sources in native.items():
        for path in sources:
            path = "Modules/" + path
            if path not in cpython:
                _fail("native_source_missing")
            raw = cpython[path]
            flags = ["-DPY_SQLITE_HAVE_SERIALIZE=1"] if name == "_sqlite3" else []
            if name == "_sha2":
                flags += ["-D_BSD_SOURCE", "-D_DEFAULT_SOURCE"]
            units.append({"module": name, "source": path, "object": path[:-2] + ".o",
                          "source_size": len(raw), "source_sha256": _sha(raw), "extra_flags": flags})
    if solver == "shinka":
        units.append({"module": "sqlite-library", "source": "sqlite/sqlite3.c",
                      "object": "sqlite/sqlite3.o", "source_size": len(extra["sqlite/sqlite3.c"]),
                      "source_sha256": _sha(extra["sqlite/sqlite3.c"]),
                      "extra_flags": ["-DSQLITE_THREADSAFE=1", "-DSQLITE_OMIT_LOAD_EXTENSION=1",
                                      "-DSQLITE_ENABLE_DESERIALIZE=1"]})
    generated.update(_tables(frozen, native))
    wire = canonical({"schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": solver,
                      "cpython_inventory_sha256": expected_cpython_inventory_sha256,
                      "producer_manifest_sha256": _sha(producer_manifest),
                      "sqlite_inventory_sha256": sqlite_pin, "frozen": frozen, "native_units": units,
                      "sources": json.loads(source_inventory(generated)),
                      "runtime_module_aliases": [
                          {"name": name, "source_module": _RUNTIME_ALIASES[name],
                           "parent_module": name.rpartition(".")[0]}
                          for name in sorted(runtime_aliases)
                      ],
                      "interpreter_provided_modules": [interpreter_modules[name]
                                                       for name in sorted(interpreter_modules)],
                      "guarded_call_imports": sorted(guarded_calls, key=lambda record: record["module"]),
                      "excluded_imported_selftests": sorted(excluded_selftests,
                                                           key=lambda record: record["module"]),
                      "guarded_absent_imports": sorted(absent), "dynamic_import_closure_verified": False,
                      "runtime_execution_performed": False, "production_admission": False})
    return FixedRuntimeClosure(wire, tuple(sorted(generated.items())))
