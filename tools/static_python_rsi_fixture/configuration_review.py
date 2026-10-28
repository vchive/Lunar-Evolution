"""Bind independently approved configuration bytes to the original recipe.

No configure, Makefile, compiler or interpreter is executed. The supplied
external manifest pin is authority from the caller, not generated observation.
This finite source-owned binder is deliberately not a general Make importer.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass

from tools.static_python_fixture.configure_plan import _DISABLED, _ENABLED
from tools.static_python_fixture.profile import CORE_BUILTINS
from tools.static_python_rsi_fixture.runtime_closure import canonical

OUTPUTS = ("pyconfig.h", "Makefile", "Makefile.pre", "config.log", "config.status",
           "Modules/Setup.bootstrap", "Modules/Setup.stdlib", "Modules/config.c")
PROFILE = "cpython-3.13.12-zig-0.16.0-x86_64-linux-musl-v1"
SCHEMA = "lunar-cpython-configuration-review-v1"
MAX_OUTPUT_BYTES = 16 * 1024**2
MAX_TOTAL_OUTPUT_BYTES = 64 * 1024**2
MAX_MANIFEST_BYTES = 4 * 1024**2
MAX_VARIABLES = 4096
MAX_EXPANSION_BYTES = 1024 * 1024
REQUIRED_VARIABLES = frozenset({
    "PY_CORE_CFLAGS", "PY_BUILTIN_MODULE_CFLAGS", "PY_STDMODULE_CFLAGS",
    "PY_CFLAGS", "PY_CFLAGS_NODIST", "PY_CPPFLAGS", "PY_LDFLAGS", "PY_LDFLAGS_NODIST",
    "LIBOBJS", "MACHDEP_OBJS", "DTRACE_OBJS", "PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ",
    "DYNLOADFILE", "MODOBJS", "MODLIBS", "LIBS", "SYSLIBS", "LINKFORSHARED",
    "MODBUILT_NAMES", "MODSHARED_NAMES", "MODDISABLED_NAMES",
})
_OBJECT_VARIABLES = frozenset({"LIBOBJS", "MACHDEP_OBJS", "DTRACE_OBJS", "PLATFORM_OBJS",
                               "PERF_TRAMPOLINE_OBJ", "MODOBJS"})
_FEATURES = {"WITH_PYMALLOC": "1", "WITH_MIMALLOC": "1", "USE_COMPUTED_GOTOS": "1",
             "SIZEOF_VOID_P": "8", "Py_ENABLE_SHARED": None, "HAVE_DLOPEN": None,
             "ENABLE_IPV6": None}
_KEYS = {"schema", "profile", "target", "source_inventory_sha256", "zig_manifest_sha256",
         "outputs", "header_directives", "make_variables", "setup_rows", "config_modules",
         "recipe_semantics", "concrete_stages_sha256"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REFERENCE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*([:+?]?=)\s*(.*?)\s*$")
# Warning-only differences in the fixed direct-compile profile. Other warnings,
# especially -Werror variants, require an actual corresponding recipe option.
_WARNING_DIFFERENCES = frozenset({
    "-Wall", "-Wextra", "-Wsign-compare", "-Wstrict-prototypes", "-Wno-unused-parameter",
    "-Wno-missing-field-initializers", "-Wno-cast-function-type", "-Wno-unknown-warning-option",
})


class ConfigurationReviewError(ValueError):
    """Fixed refusal without configuration contents or private paths."""


def _fail(reason: str) -> None:
    raise ConfigurationReviewError("static_python_configuration_review_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        _fail("text")
    if "\x00" in text or "\r" in text:
        _fail("text")
    return text


def _header(raw: bytes) -> list[str]:
    text = _text(raw)
    # Preserve every directive, including conditional feature context, in the
    # independently reviewed inventory. Never evaluate a C preprocessor here.
    lines = text.replace("\\\n", " ").splitlines()
    directives, features = [], {}
    conditions = []
    guard_started = guard_defined = guard_closed = False
    for line in lines:
        disabled = re.fullmatch(r"\s*/\*\s*#\s*undef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\*/\s*", line)
        directive = re.match(r"\s*#\s*([A-Za-z_][A-Za-z0-9_]*)(.*)$", line)
        if disabled:
            name, value = disabled[1], None
            directives.append("#undef " + name)
        elif directive:
            operation, body = directive[1], directive[2].strip()
            if operation not in {"define", "undef", "if", "ifdef", "ifndef", "elif", "else", "endif", "include", "error"}:
                _fail("header_directive")
            directives.append("#" + operation + (" " + body if body else ""))
            if operation in {"if", "ifdef", "ifndef"}:
                guard = operation == "ifndef" and body == "Py_PYCONFIG_H" and not conditions
                if guard:
                    if guard_started or features:
                        _fail("header_condition")
                    guard_started = True
                conditions.append(guard)
            elif operation == "endif":
                if not conditions or body:
                    _fail("header_condition")
                if conditions.pop():
                    guard_closed = True
            elif operation in {"else", "elif"}:
                if not conditions or conditions[-1]:
                    _fail("header_condition")
            if operation not in {"define", "undef"}:
                continue
            parsed = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?", body)
            if parsed is None:
                # Function macros are externally pinned, not interpreted.
                if operation == "define" and re.match(r"[A-Za-z_][A-Za-z0-9_]*\(", body):
                    continue
                _fail("header_directive")
            name = parsed[1]
            value = None if operation == "undef" else (parsed[2] or "")
            if name == "Py_PYCONFIG_H":
                if (operation != "define" or conditions != [True] or guard_defined
                        or value not in {"", "1"}):
                    _fail("header_condition")
                guard_defined = True
        else:
            continue
        if name in _FEATURES:
            if (name in features or conditions not in ([], [True])
                    or (conditions == [True] and not guard_defined)
                    or guard_closed):
                _fail("feature_ambiguous")
            features[name] = value
    if conditions or features != _FEATURES or (guard_started and not (guard_defined and guard_closed)):
        _fail("feature_contract")
    return directives


def _make(raw: bytes) -> dict[str, dict]:
    """Read a bounded closure of simple assignments; never interpret recipes."""
    text = _text(raw).replace("\\\n", " ")
    assignments: dict[str, list[tuple[str, str, int]]] = {}
    suspicious = set()
    depth = 0
    for line in text.splitlines():
        if line.startswith("\t"):
            continue
        clean = line.split("#", 1)[0].strip()
        if re.match(r"^(?:ifdef|ifndef|ifeq|ifneq)\b", clean):
            depth += 1
            continue
        if clean == "endif":
            depth -= 1
            if depth < 0:
                _fail("make_condition")
            continue
        match = _ASSIGNMENT.fullmatch(clean)
        if match:
            assignments.setdefault(match[1], []).append((match[2], match[3], depth))
        elif "=" in clean:
            # Detect unsupported modifiers and target-specific assignments of
            # any variable that later enters the reviewed closure.
            before = clean.split("=", 1)[0]
            suspicious.update(_NAME.findall(before))
    if depth or len(assignments) > MAX_VARIABLES:
        _fail("make_bounds")
    roots = set(REQUIRED_VARIABLES) | {name for name in assignments if name.startswith("MODULE_")}
    resolved: dict[str, dict] = {}
    visiting = set()
    expansion_bytes = expansion_tokens = 0

    def expand(name: str) -> str:
        nonlocal expansion_bytes, expansion_tokens
        if name in resolved:
            return resolved[name]["expanded"]
        if name in visiting or len(visiting) >= 64:
            _fail("make_cycle")
        rows = assignments.get(name, [])
        if (name in suspicious or len(rows) != 1 or rows[0][0] not in {"=", ":="}
                or rows[0][2] != 0):
            _fail("make_assignment")
        expression = rows[0][1]
        if rows[0][0] == ":=" and _REFERENCE.search(expression):
            # Immediate expansion depends on assignment order. Supporting its
            # reference form would require a different finite contract.
            _fail("make_expression")
        visiting.add(name)
        pieces, length, offset = [], 0, 0
        for match in _REFERENCE.finditer(expression):
            literal, replacement = expression[offset:match.start()], expand(match[1])
            length += len(literal) + len(replacement)
            if length > MAX_EXPANSION_BYTES:
                _fail("make_bounds")
            pieces.extend((literal, replacement))
            offset = match.end()
        tail = expression[offset:]
        if length + len(tail) > MAX_EXPANSION_BYTES:
            _fail("make_bounds")
        pieces.append(tail)
        expanded = "".join(pieces)
        visiting.remove(name)
        if (len(expanded) > MAX_EXPANSION_BYTES or any(c in expanded for c in "$`\n;|&<>")
                or re.search(r"(?:^|\s)@", expanded)):
            _fail("make_expression")
        try:
            tokens = shlex.split(expanded, posix=True)
        except ValueError:
            _fail("make_expression")
        if (len(tokens) > 16384 or any(token.startswith(("@", "-fplugin", "-specs=", "--sysroot=",
                                                        "-DPy_ENABLE_SHARED", "-DHAVE_DLOPEN"))
                                      or token in {"-shared", "-fPIC", "-fpic"}
                                      for token in tokens)):
            _fail("make_option")
        expansion_bytes += len(expanded)
        expansion_tokens += len(tokens)
        if expansion_bytes > MAX_EXPANSION_BYTES or expansion_tokens > 65536:
            _fail("make_bounds")
        resolved[name] = {"expression": expression, "expanded": expanded, "tokens": tokens}
        return expanded

    for name in sorted(roots):
        expand(name)
    return {name: resolved[name] for name in sorted(resolved)}


def _setup(raw: bytes) -> list[list[str]]:
    rows, names = [], set()
    disabled = False
    for line in _text(raw).replace("\\\n", " ").splitlines():
        if len(line) > 16384 or len(rows) >= 512:
            _fail("setup_bounds")
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        if clean in {"*static*", "*disabled*"}:
            disabled = clean == "*disabled*"
            rows.append([clean])
            continue
        if any(c in clean for c in "$`\\;|&<>@"):
            _fail("setup_expression")
        row = clean.split()
        if (len(row[0]) > 64 or not _NAME.fullmatch(row[0]) or row[0] in names
                or (disabled and len(row) != 1)
                or (not disabled and (len(row) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_./=+,-]+", p)
                                                          or ".." in p.split("/") or p.startswith("/")
                                                          for p in row[1:])))):
            _fail("setup_row")
        names.add(row[0])
        rows.append(row)
    return rows


def _config_modules(raw: bytes) -> list[list[str]]:
    # Pin the whole original file; interpret only its finite initializer table.
    text = re.sub(r"/\*.*?\*/", "", _text(raw), flags=re.DOTALL)
    tables = re.findall(r"\b_PyImport_Inittab\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;", text, re.DOTALL)
    if len(tables) != 1:
        _fail("module_table")
    rows, names = [], set()
    for line in tables[0].splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r"\s*\{\s*(?:0|NULL)\s*,\s*(?:0|NULL)\s*\}\s*,?\s*", line):
            rows.append(["", "NULL"])
            continue
        row = re.fullmatch(r'\s*\{\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*,\s*([A-Za-z_][A-Za-z0-9_]*|0)\s*\}\s*,?\s*', line)
        if row is None or row[1] in names:
            _fail("module_table")
        names.add(row[1])
        rows.append([row[1], row[2]])
    if (names != set(CORE_BUILTINS) | {name for name, _ in _ENABLED}
            or not rows or rows[-1] != ["", "NULL"] or rows.count(["", "NULL"]) != 1):
        _fail("module_contract")
    return rows


def _semantics(stages: list[dict], compile_roles: dict[str, str]) -> dict:
    roles: dict[str, dict] = {}
    links, archives = [], []
    for stage in stages:
        for command in stage["commands"]:
            argv = command["argv"]
            if "-c" in argv:
                if argv.count("-c") != 1 or argv.count("-o") != 1:
                    _fail("compile_shape")
                source, output = argv[argv.index("-c") + 1], argv[argv.index("-o") + 1]
                role = compile_roles.get(source)
                if role not in {"configuration", "core", "builtin", "freezer", "target"}:
                    _fail("compile_role")
                flags = argv[:argv.index("-c")]
                if ("-DPy_BUILD_CORE" not in flags
                        or (("-DPy_BUILD_CORE_BUILTIN" in flags) != (role == "builtin"))):
                    _fail("role_flags")
                record = roles.setdefault(role, {"flags": [], "units": []})
                if flags not in record["flags"]:
                    record["flags"].append(flags)
                record["units"].append({"source": source, "object": output, "stage": stage["stage"]})
            elif argv[:2] == ["@toolchain/zig", "cc"]:
                if "-static" not in argv or "-shared" in argv or "-o" not in argv:
                    _fail("static_link")
                links.append({"stage": stage["stage"], "argv": argv})
            elif argv[:2] == ["@toolchain/zig", "ar"]:
                archives.append({"stage": stage["stage"], "argv": argv})
    if set(roles) != {"configuration", "core", "builtin", "freezer", "target"} or len(links) != 2 or len(archives) != 1:
        _fail("recipe_shape")
    return {"roles": roles, "static_links": links, "archives": archives}


def _argv_flags(tokens: list[str]) -> set[str]:
    result = set()
    offset = 0
    while offset < len(tokens):
        token = tokens[offset]
        if token == "-I":
            offset += 1
            if offset >= len(tokens):
                _fail("include_flag")
            token += tokens[offset]
        result.add(token)
        offset += 1
    return result


def _reviewed_role_flags(tokens: list[str], variables: dict) -> set[str]:
    """Normalize only source-owned adaptations, never caller-proposed aliases."""
    includes = {".": "configuration"}
    for relative in ("Include", "Include/internal", "Include/internal/mimalloc"):
        includes[relative] = relative
        includes["./" + relative] = relative
        for variable in ("srcdir", "abs_srcdir"):
            if variable in variables:
                root = variables[variable]["expanded"].rstrip("/")
                if root:
                    includes[root + "/" + relative] = relative
    result = set()
    optimization = debug = None
    offset = 0
    while offset < len(tokens):
        token = tokens[offset]
        if token == "-I":
            offset += 1
            if offset >= len(tokens):
                _fail("include_flag")
            token += tokens[offset]
        if token.startswith("-I"):
            relative = includes.get(token[2:])
            if relative is None:
                _fail("include_flag")
            token = "-I@source-dir/" + relative
        if token in {"-O2", "-O3"}:
            optimization = token
        elif token in {"-g", "-g0"}:
            debug = token
        elif token == "-fwrapv":
            result.add("-fno-strict-overflow")
        elif token not in _WARNING_DIFFERENCES:
            result.add(token)
        offset += 1
    if optimization is not None:
        if optimization != "-O2":
            _fail("optimization_flag")
        result.add(optimization)
    if debug is not None:
        if debug != "-g0":
            _fail("debug_flag")
        result.add(debug)
    return result


def _role_flag_relation(variables: dict, roles: dict) -> None:
    common = ("PY_CFLAGS", "PY_CFLAGS_NODIST", "PY_CPPFLAGS", "PY_STDMODULE_CFLAGS")
    selections = [(variable, set(roles)) for variable in common]
    selections.extend((("PY_CORE_CFLAGS", {"configuration", "core", "freezer", "target"}),
                       ("PY_BUILTIN_MODULE_CFLAGS", {"builtin"})))
    for variable, selected_roles in selections:
        required = _reviewed_role_flags(variables[variable]["tokens"], variables)
        for role in selected_roles:
            if any(not required.issubset(_argv_flags(vector)) for vector in roles[role]["flags"]):
                _fail("role_flag_relation")


def _closure(variables: dict, setup: dict, semantics: dict) -> None:
    roles = semantics["roles"]
    _role_flag_relation(variables, roles)
    sources = {unit["source"].removeprefix("@source/") for role in roles.values() for unit in role["units"]}
    objects = {unit["object"].removeprefix("@work/objects/") for role in roles.values() for unit in role["units"]}
    archive_inputs = {}
    for archive in semantics["archives"]:
        argv = archive["argv"]
        if argv[:3] != ["@toolchain/zig", "ar", "rcsD"] or len(argv) < 5:
            _fail("archive_shape")
        archive_inputs[argv[3]] = set(argv[4:])
    linked_objects = []
    for link in semantics["static_links"]:
        linked = set()
        for token in link["argv"]:
            if token in archive_inputs:
                linked.update(archive_inputs[token])
            elif token.startswith("@work/objects/"):
                linked.add(token)
        linked_objects.append({token.removeprefix("@work/objects/") for token in linked})
    for name in _OBJECT_VARIABLES:
        if any(token not in objects or any(token not in linked for linked in linked_objects)
               for token in variables[name]["tokens"]):
            _fail("replacement_object")
    dynload = variables["DYNLOADFILE"]["tokens"]
    if (len(dynload) != 1 or "Python/" + dynload[0] not in objects
            or any("Python/" + dynload[0] not in linked for linked in linked_objects)):
        _fail("dynload_object")
    if variables["MODSHARED_NAMES"]["tokens"] or variables["LINKFORSHARED"]["tokens"]:
        _fail("dynamic_module")
    for name, flag in (("PY_CORE_CFLAGS", "-DPy_BUILD_CORE"),
                       ("PY_BUILTIN_MODULE_CFLAGS", "-DPy_BUILD_CORE_BUILTIN")):
        if flag not in variables[name]["tokens"]:
            _fail("make_role_flags")
    link_libraries = [{token for token in link["argv"] if token.startswith("-l")}
                      for link in semantics["static_links"]]
    for name in ("LIBS", "SYSLIBS", "MODLIBS", "PY_LDFLAGS", "PY_LDFLAGS_NODIST"):
        for token in variables[name]["tokens"]:
            equivalent = "-lpthread" if token == "-pthread" else token
            if equivalent == "-static":
                continue
            if not equivalent.startswith("-l") or any(equivalent not in libs for libs in link_libraries):
                _fail("link_closure")
    enabled = {}
    for rows in setup.values():
        disabled = False
        for row in rows:
            if row[0].startswith("*"):
                disabled = row[0] == "*disabled*"
            elif not disabled and row[0] not in _DISABLED:
                if row[0] in enabled or any("Modules/" + path not in sources for path in row[1:]):
                    _fail("module_source")
                enabled[row[0]] = row[1:]
    if enabled != {name: list(paths) for name, paths in _ENABLED}:
        _fail("setup_contract")
    module_objects = variables["MODOBJS"]["tokens"]
    required_objects = {"Modules/" + path.removesuffix(".c") + ".o" for paths in enabled.values() for path in paths}
    builtin_names = variables["MODBUILT_NAMES"]["tokens"]
    if (not required_objects.issubset(module_objects) or len(module_objects) != len(set(module_objects))
            or set(builtin_names) != set(enabled) or len(builtin_names) != len(set(builtin_names))):
        _fail("module_discovery")


@dataclass(frozen=True, slots=True)
class ReviewedConfigurationBinding:
    """Original bytes consumed by the recipe, never build/runtime authority."""

    sources: tuple[tuple[str, bytes], ...]
    manifest_sha256: str
    concrete_stages_sha256: str


def bind_reviewed_cpython_configuration(
    *, configuration_outputs: tuple[tuple[str, bytes], ...], review_manifest_bytes: bytes,
    expected_review_manifest_sha256: str, source_inventory_sha256: str,
    zig_manifest_sha256: str, configuration_header: bytes, stages: list[dict],
    compile_roles: dict[str, str],
) -> ReviewedConfigurationBinding:
    """Check independent approved originals against actual source-owned stages.

    The expected review pin must come from external approval. No observation,
    successful configure, or returned binding establishes accepted custody.
    """
    if (type(review_manifest_bytes) is not bytes or not 0 < len(review_manifest_bytes) <= MAX_MANIFEST_BYTES
            or not _digest(expected_review_manifest_sha256)
            or _sha(review_manifest_bytes) != expected_review_manifest_sha256):
        _fail("manifest_pin")
    try:
        facts = json.loads(review_manifest_bytes, object_pairs_hook=_pairs)
        if canonical(facts) != review_manifest_bytes or type(facts) is not dict or set(facts) != _KEYS:
            _fail("manifest_schema")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("manifest_schema")
    if (facts["schema"] != SCHEMA or facts["profile"] != PROFILE or facts["target"] != "x86_64-linux-musl"
            or not _digest(source_inventory_sha256) or not _digest(zig_manifest_sha256)
            or facts["source_inventory_sha256"] != source_inventory_sha256
            or facts["zig_manifest_sha256"] != zig_manifest_sha256):
        _fail("profile_binding")
    if (type(configuration_outputs) is not tuple or len(configuration_outputs) != len(OUTPUTS)
            or any(type(row) is not tuple or len(row) != 2 for row in configuration_outputs)
            or tuple(row[0] for row in configuration_outputs) != OUTPUTS
            or any(type(row[1]) is not bytes or not 0 < len(row[1]) <= MAX_OUTPUT_BYTES for row in configuration_outputs)
            or sum(len(row[1]) for row in configuration_outputs) > MAX_TOTAL_OUTPUT_BYTES):
        _fail("output_set")
    outputs = dict(configuration_outputs)
    pins = [{"path": path, "size": len(raw), "sha256": _sha(raw)} for path, raw in configuration_outputs]
    if (type(facts["outputs"]) is not list or len(facts["outputs"]) != len(OUTPUTS)
            or any(type(row) is not dict or set(row) != {"path", "size", "sha256"}
                   or type(row["size"]) is not int or not _digest(row["sha256"])
                   for row in facts["outputs"])
            or facts["outputs"] != pins or outputs["pyconfig.h"] != configuration_header):
        _fail("output_pin")
    header = _header(outputs["pyconfig.h"])
    variables = _make(outputs["Makefile"])
    setup = {path: _setup(outputs[path]) for path in ("Modules/Setup.bootstrap", "Modules/Setup.stdlib")}
    modules = _config_modules(outputs["Modules/config.c"])
    semantics = _semantics(stages, compile_roles)
    for name, actual in (("header_directives", header), ("make_variables", variables),
                         ("setup_rows", setup), ("config_modules", modules), ("recipe_semantics", semantics)):
        if facts[name] != actual:
            _fail(name)
    graph_sha256 = _sha(canonical(stages))
    if facts["concrete_stages_sha256"] != graph_sha256:
        _fail("stage_graph")
    _closure(variables, setup, semantics)
    sources = tuple(("configuration/original/" + path, raw) for path, raw in configuration_outputs)
    return ReviewedConfigurationBinding((*sources, ("configuration/review.json", review_manifest_bytes)),
                                        expected_review_manifest_sha256, graph_sha256)
