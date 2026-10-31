"""Explicit v2 review of the fixed CPython/Zig configuration shapes.

Original bytes, discovery text and finite adaptations remain separately bound
to external review. This module executes no configure, Make, compiler or
interpreter and never emits an approved manifest or its independent pin. The
unchanged v1 consumer is selected without failure-based fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex

from tools.static_python_fixture.configure_plan import (
    _DISABLED,
    _ENABLED,
    emit_configure_plan_assets,
)
from tools.static_python_fixture.profile import CORE_BUILTINS
from tools.static_python_rsi_fixture import configuration_review as legacy
from tools.static_python_rsi_fixture.runtime_closure import _NATIVE, _SQLITE, canonical

OUTPUTS = ("pyconfig.h", "Makefile", "Makefile.pre", "config.log", "config.status",
           "Modules/Setup.bootstrap", "Modules/Setup.stdlib", "Modules/config.c")
PROFILE = "cpython-3.13.12-zig-0.16.0-x86_64-linux-musl-v2"
SCHEMA = "lunar-cpython-configuration-review-v2"
_ZIG_MANIFEST_SHA256 = "b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90"
_OPTIONAL_ABSENT_VARIABLES = frozenset({"PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ"})
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
    "MODBUILT_NAMES", "MODSHARED_NAMES", "MODDISABLED_NAMES", "LIBRARY_OBJS",
})
_OBJECT_VARIABLES = frozenset({"LIBOBJS", "MACHDEP_OBJS", "DTRACE_OBJS", "PLATFORM_OBJS",
                               "PERF_TRAMPOLINE_OBJ", "MODOBJS"})
_FEATURES = {"WITH_PYMALLOC": "1", "WITH_MIMALLOC": "1", "USE_COMPUTED_GOTOS": "1",
             "SIZEOF_VOID_P": "8", "Py_ENABLE_SHARED": None, "HAVE_DLOPEN": None,
             "ENABLE_IPV6": None}
_KEYS = {"schema", "profile", "target", "source_inventory_sha256", "zig_manifest_sha256",
         "outputs", "header_directives", "make_variables", "setup_rows", "config_modules",
         "recipe_semantics", "concrete_stages_sha256", "make_absences",
         "make_absent_references", "stdlib_discovery_rows", "adaptations"}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEADER_DISABLED = re.compile(r"\s*/\*\s*#\s*undef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\*/\s*")
_HEADER_DIRECTIVE = re.compile(r"\s*#\s*([A-Za-z_][A-Za-z0-9_]*)(.*)$")
_REFERENCE = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*([:+?]?=)\s*(.*?)\s*$")
# Warning-only differences in the fixed direct-compile profile. Other warnings,
# especially -Werror variants, require an actual corresponding recipe option.
_WARNING_DIFFERENCES = frozenset({
    "-Wall", "-Wextra", "-Wsign-compare", "-Wstrict-prototypes", "-Wno-unused-parameter",
    "-Wno-missing-field-initializers", "-Wno-cast-function-type", "-Wno-unknown-warning-option",
    "-Wunreachable-code",
})
_USER_OVERRIDE_PARENTS = {
    "PY_CFLAGS": "$(BASECFLAGS) $(OPT) $(CONFIGURE_CFLAGS) $(CFLAGS) $(EXTRA_CFLAGS)",
    "PY_CFLAGS_NODIST": ("$(CONFIGURE_CFLAGS_NODIST) $(CFLAGS_NODIST) "
                          "-I$(srcdir)/Include/internal -I$(srcdir)/Include/internal/mimalloc"),
    "PY_CPPFLAGS": "$(BASECPPFLAGS) -I. -I$(srcdir)/Include $(CONFIGURE_CPPFLAGS) $(CPPFLAGS)",
    "PY_LDFLAGS": "$(CONFIGURE_LDFLAGS) $(LDFLAGS)",
    "PY_LDFLAGS_NODIST": "$(CONFIGURE_LDFLAGS_NODIST) $(LDFLAGS_NODIST)",
}
_USER_OVERRIDE_REFERENCES = {
    "CFLAGS": "PY_CFLAGS", "EXTRA_CFLAGS": "PY_CFLAGS",
    "CFLAGS_NODIST": "PY_CFLAGS_NODIST", "CPPFLAGS": "PY_CPPFLAGS",
    "LDFLAGS": "PY_LDFLAGS", "LDFLAGS_NODIST": "PY_LDFLAGS_NODIST",
}
_BOOTSTRAP_LINK_REFERENCES = tuple(
    "MODULE_" + name.upper() + "_LDFLAGS" for name, _ in _ENABLED
)
_BOOTSTRAP_LINK_EXPRESSION = " ".join("$(" + name + ")" for name in _BOOTSTRAP_LINK_REFERENCES)


ConfigurationReviewError = legacy.ConfigurationReviewError
ReviewedConfigurationBinding = legacy.ReviewedConfigurationBinding


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


def _pinned_review_facts(raw: bytes, expected_sha256: str) -> dict:
    """Read a canonical review only after validating its independent pin."""
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_MANIFEST_BYTES
            or not _digest(expected_sha256) or _sha(raw) != expected_sha256):
        _fail("manifest_pin")
    try:
        facts = json.loads(raw, object_pairs_hook=_pairs)
        if type(facts) is not dict or canonical(facts) != raw:
            _fail("manifest_schema")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("manifest_schema")
    return facts


def selects_v2_review(*, review_manifest_bytes: bytes, expected_review_manifest_sha256: str) -> bool:
    """Select source-owned v2 vectors only from a pinned, canonical schema."""
    return _pinned_review_facts(review_manifest_bytes, expected_review_manifest_sha256).get("schema") == SCHEMA


def _text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        _fail("text")
    if "\x00" in text or "\r" in text:
        _fail("text")
    return text


def _header_include(body: str) -> None:
    """Accept one literal relative operand, without preprocessing or resolving it."""
    body = body.strip(" \t")
    if not body or (body[0], body[-1]) not in {("<", ">"), ('"', '"')}:
        _fail("header_include")
    relative = body[1:-1]
    if (re.fullmatch(r"[A-Za-z0-9_./+-]+", relative) is None
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        _fail("header_include")


def _header_lexical(text: str) -> None:
    """Refuse unsupported directive prefixes, without preprocessing the header."""
    # Trigraph translation would precede line splicing, comments and quotes.
    # Refuse its spellings everywhere rather than guessing compiler settings.
    if re.search(r"\?\?[=/'()!<>-]", text):
        _fail("header_lexical")
    block = False
    # This classification view is separate from the retained inventory's
    # historical backslash-LF-to-space encoding below.
    classification = text.replace("\\\n", "").split("\n")
    inventory = text.replace("\\\n", " ").split("\n")
    for line, legacy_line in zip(classification, inventory, strict=True):
        if block and (_HEADER_DIRECTIVE.match(legacy_line) or _HEADER_DISABLED.fullmatch(legacy_line)):
            # Do not let comment text satisfy the legacy directive/feature
            # inventory. Its top-level complete-line undef convention stays.
            _fail("header_lexical")
        comment_prefix, directive, quote = block, False, None
        cursor = 0
        while cursor < len(line):
            if block:
                end = line.find("*/", cursor)
                if end < 0:
                    break
                block, cursor = False, end + 2
                continue
            char = line[cursor]
            if quote is not None:
                if char == "\\":
                    cursor += 2
                    continue
                if char == quote:
                    quote = None
            elif line.startswith("//", cursor):
                break
            elif line.startswith("/*", cursor):
                block = True
                comment_prefix = comment_prefix or not directive
                cursor += 2
                continue
            elif not directive:
                if char in " \t":
                    cursor += 1
                    continue
                if char != "#" or comment_prefix:
                    _fail("header_lexical")
                cursor += 1
                while cursor < len(line) and line[cursor] in " \t":
                    cursor += 1
                keyword = _NAME.match(line, cursor)
                if keyword is None:
                    _fail("header_lexical")
                directive, cursor = True, keyword.end()
                if keyword[0] == "include":
                    # Delegate the complete operand to its existing finite
                    # gate, preserving its refusal code for malformed inputs.
                    # A valid literal has no comment or quote state to carry.
                    _header_include(line[cursor:])
                    break
                continue
            elif char in "\"'":
                quote = char
            cursor += 1
        if quote is not None:
            _fail("header_lexical")
    if block:
        _fail("header_lexical")


def _header(raw: bytes) -> list[str]:
    text = _text(raw)
    _header_lexical(text)
    # Preserve every directive, including conditional feature context, in the
    # independently reviewed inventory. Never evaluate a C preprocessor here.
    lines = text.replace("\\\n", " ").split("\n")
    directives, features = [], {}
    conditions = []
    guard_started = guard_defined = guard_closed = False
    for line in lines:
        disabled = _HEADER_DISABLED.fullmatch(line)
        directive = _HEADER_DIRECTIVE.match(line)
        if disabled:
            name, value = disabled[1], None
            directives.append("#undef " + name)
        elif directive:
            operation, body = directive[1], directive[2].strip()
            if operation not in {"define", "undef", "if", "ifdef", "ifndef", "elif", "else", "endif", "include", "error"}:
                _fail("header_directive")
            if operation == "include":
                # No trailing text or comments: the real reviewed header has
                # no include directive needing a lexical comment exception.
                _header_include(directive[2])
            directives.append("#" + operation + (" " + body if body else ""))
            if operation in {"if", "ifdef", "ifndef"}:
                guard = operation == "ifndef" and body == "Py_PYCONFIG_H" and not conditions
                if guard:
                    if guard_started or features:
                        _fail("header_condition")
                    guard_started = True
                conditions.append(guard)
            elif operation == "endif":
                # Only the exact outer guard may carry this fixed lexical
                # comment. Preserve its original directive in the inventory.
                if (not conditions or (body and not (conditions == [True]
                        and re.fullmatch(r"/\*\s*Py_PYCONFIG_H\s*\*/", body)))):
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


def _make_assignments(raw: bytes) -> tuple[dict, set]:
    """Read bounded assignment syntax without interpreting recipe lines."""
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
    return assignments, suspicious


def _make_absences(raw: bytes) -> list[str]:
    """Record the finite absent roots without synthetic empty values."""
    assignments, suspicious = _make_assignments(raw)
    if suspicious & _OPTIONAL_ABSENT_VARIABLES:
        _fail("make_assignment")
    return sorted(_OPTIONAL_ABSENT_VARIABLES - assignments.keys())


def _make_details(raw: bytes) -> tuple[dict[str, dict], list[dict]]:
    """Resolve actual assignments and record only fixed unassigned references.

    Make is never invoked by the direct recipe. Its six optional command-line
    overrides and the fixed bootstrap's nine absent link-flag references may
    contribute no flags only at their original source-owned edges. They remain
    explicit absence facts, not invented assignments or resolved variables.
    """
    assignments, suspicious = _make_assignments(raw)
    absent = set(_make_absences(raw))
    roots = (set(REQUIRED_VARIABLES) - absent) | {
        name for name in assignments if name.startswith("MODULE_")
    }
    resolved: dict[str, dict] = {}
    absent_references: dict[str, dict] = {}
    visiting = set()
    expansion_bytes = expansion_tokens = 0

    def unassigned_reference(name: str, parent: str | None) -> str:
        reason = None
        if name in _USER_OVERRIDE_REFERENCES and _USER_OVERRIDE_REFERENCES[name] == parent:
            expression = _USER_OVERRIDE_PARENTS[parent]
            reason = "unassigned-user-override-not-consumed-by-direct-recipe"
        elif name in _BOOTSTRAP_LINK_REFERENCES and parent == "LOCALMODLIBS":
            expression = _BOOTSTRAP_LINK_EXPRESSION
            reason = "fixed-bootstrap-no-extra-link-flags"
        parent_rows = assignments.get(parent, [])
        if (reason is None or parent in suspicious or len(parent_rows) != 1
                or parent_rows[0][0] != "=" or parent_rows[0][2] != 0
                or " ".join(parent_rows[0][1].split()) != expression):
            _fail("make_assignment")
        record = absent_references.setdefault(name, {"name": name, "referenced_by": [], "semantics": reason})
        if parent not in record["referenced_by"]:
            record["referenced_by"].append(parent)
        return ""

    def expand(name: str, parent: str | None = None) -> str:
        nonlocal expansion_bytes, expansion_tokens
        if name in resolved:
            return resolved[name]["expanded"]
        if name in visiting or len(visiting) >= 64:
            _fail("make_cycle")
        rows = assignments.get(name, [])
        if not rows and name not in suspicious:
            return unassigned_reference(name, parent)
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
            literal, replacement = expression[offset:match.start()], expand(match[1], name)
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
    return ({name: resolved[name] for name in sorted(resolved)},
            [absent_references[name] for name in sorted(absent_references)])


def _make(raw: bytes) -> dict[str, dict]:
    """Resolve the reviewed roots without synthesizing missing assignments."""
    return _make_details(raw)[0]


def _make_absent_references(raw: bytes) -> list[dict]:
    """Inventory finite missing leaves separately from optional absent roots."""
    return _make_details(raw)[1]


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


def _stdlib_discovery(raw: bytes) -> list[dict[str, str]]:
    """Inventory disabled discovery text without expanding or enabling it."""
    rows, names = [], set()
    mode = "static"
    for line in _text(raw).splitlines():
        if len(line) > 16384 or len(rows) >= 512:
            _fail("setup_bounds")
        clean = line.split("#", 1)[0].strip()
        if not clean:
            continue
        if clean in {"*static*", "*shared*", "*disabled*"}:
            mode = clean[1:-1]
            continue
        tokens = clean.split()
        name = tokens[0]
        if (len(name) > 64 or not _NAME.fullmatch(name) or name in names
                or name not in _DISABLED
                or (mode == "disabled" and len(tokens) != 1)
                or (mode != "disabled" and len(tokens) < 2)):
            _fail("stdlib_discovery")
        # The one source-root reference stays inert original text. This adds
        # no Make functions to the effective static Setup grammar.
        lexical = clean.replace("$(srcdir)", "srcdir")
        if (any(c in lexical for c in "$`\\;|&<>@")
                or any(not re.fullmatch(r"[A-Za-z0-9_./=+,-]+", token)
                       or ".." in token.split("/") or token.startswith("/")
                       for token in lexical.split())):
            _fail("stdlib_discovery")
        names.add(name)
        rows.append({"mode": mode, "name": name, "row": line})
    return rows


def _effective_setup(bootstrap: bytes) -> dict[str, list[list[str]]]:
    """Bind the strict bootstrap and fixed local policy as separate facts."""
    return {
        "Modules/Setup.bootstrap": _setup(bootstrap),
        "Modules/Setup.local": _setup(emit_configure_plan_assets()["Modules/Setup.local"]),
    }


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
    for relative in ("Objects", "Python", "Include", "Include/internal", "Include/internal/mimalloc"):
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


def _library_object_relation(variables: dict, semantics: dict) -> tuple[list[dict], dict]:
    """Relate Make's stock list to only the existing role-specific graph."""
    roles = semantics["roles"]
    units = [unit for role in roles.values() for unit in role["units"]]
    objects = {unit["object"].removeprefix("@work/objects/") for unit in units}
    if len({unit["object"] for unit in units}) != len(units):
        _fail("library_object_closure")
    forbidden = {"Modules/getpath.o", "Python/frozen.o", "Programs/python.o",
                 "Programs/_bootstrap_python.o"}
    if forbidden & objects:
        _fail("stock_object")
    archives = {}
    for archive in semantics["archives"]:
        argv = archive["argv"]
        if (argv[:3] != ["@toolchain/zig", "ar", "rcsD"] or len(argv) < 5
                or any(not token.startswith("@work/objects/") for token in argv[4:])
                or len(argv[4:]) != len(set(argv[4:]))):
            _fail("archive_shape")
        archives[argv[3]] = set(argv[4:])
    linked = {}
    for link in semantics["static_links"]:
        stage = link["stage"]
        if stage not in {"freeze", "link"} or stage in linked:
            _fail("library_object_closure")
        members = set()
        for token in link["argv"]:
            if token in archives:
                members.update(archives[token])
            elif token.startswith("@work/objects/"):
                members.add(token)
        linked[stage] = {token.removeprefix("@work/objects/") for token in members}
    if set(linked) != {"freeze", "link"} or any(forbidden & s for s in linked.values()):
        _fail("stock_object")
    library = variables["LIBRARY_OBJS"]["tokens"]
    if not library or len(library) != len(set(library)):
        _fail("library_object_closure")
    additions = _source_owned_additions(roles, semantics["static_links"], set(library), linked)

    def replacement(role: str, obj: str, sources: set[str], stage: str) -> dict:
        matches = [unit for unit in roles[role]["units"]
                   if unit["object"] == "@work/objects/" + obj and unit["source"] in sources]
        if len(matches) != 1 or obj not in linked[stage]:
            _fail("library_object_replacement")
        return {"source": matches[0]["source"], "object": matches[0]["object"], "stage": stage}

    records = []
    for obj in library:
        if obj == "Modules/getpath.o":
            records.append({
                "make_object": obj,
                "freezer": replacement("freezer", "Modules/getpath_noop.o",
                                       {"@source/Modules/getpath_noop.c"}, "freeze"),
                "target": replacement("target", "installation-owned-strict-getpath.o",
                                      {"@source/tools/static_python_fixture/assets/getpath.c"}, "link"),
            })
        elif obj == "Python/frozen.o":
            records.append({
                "make_object": obj,
                "freezer": replacement("freezer", "Programs/_freeze_module.o",
                                       {"@source/Programs/_freeze_module.c"}, "freeze"),
                "target": replacement("target", "installation-owned-finite-frozen.o",
                                      {"@source/generated-sources/Python/frozen.c",
                                       "@source/runtime/Python/frozen.c"}, "link"),
            })
        elif obj not in objects or any(obj not in s for s in linked.values()):
            _fail("library_object_closure")
    return records, additions


def _source_owned_additions(roles: dict, links: list[dict], library: set[str], linked: dict) -> dict:
    """Cover original baseline objects, allowing only fixed direct additions."""
    pipe_source = "@source/tools/static_python_fixture/assets/pipe.c"
    pipe_object = "@work/objects/Modules/lunar_fixture_pipe.o"
    pipe, native = None, []
    native_sources = {name: tuple("@source/Modules/" + path for path in paths)
                      for name, paths in _NATIVE.items()}
    native_sources["_sqlite3"] = tuple("@source/Modules/" + path for path in _SQLITE)
    native_sources["sqlite-library"] = ("@source/sqlite/sqlite3.c",)
    source_modules = {source: name for name, sources in native_sources.items() for source in sources}
    missing_native = set()
    for role in ("core", "builtin"):
        for unit in roles[role]["units"]:
            obj = unit["object"].removeprefix("@work/objects/")
            if obj in library:
                continue
            # Every exception still reaches both original static links.
            if role != "builtin" or any(obj not in objects for objects in linked.values()):
                _fail("library_object_closure")
            record = {"source": unit["source"], "object": unit["object"],
                      "role": role, "links": ["freeze", "link"]}
            if unit["source"] == pipe_source and unit["object"] == pipe_object:
                pipe = record
                continue
            module = source_modules.get(unit["source"])
            expected_object = "@work/objects/" + unit["source"].removeprefix("@source/")[:-2] + ".o"
            if module is None or unit["object"] != expected_object:
                _fail("library_object_closure")
            native.append({"module": module, **record})
            missing_native.add(module)
    if native:
        link_by_stage = {link["stage"]: link["argv"] for link in links}
        target = link_by_stage["link"][6]
        if (link_by_stage["freeze"][6] != "@work/bin/lunar-freeze-module"
                or target not in {"@work/bin/lunar-openevolve", "@work/bin/lunar-shinka"}):
            _fail("runtime_native_profile")

        def actual_unit(role: str, source: str, obj: str, stages: tuple[str, ...]) -> None:
            rows = [unit for unit in roles[role]["units"]
                    if unit["source"] == source and unit["object"] == "@work/objects/" + obj]
            if len(rows) != 1 or any(obj not in linked[stage] for stage in stages):
                _fail("runtime_native_profile")

        # Output names cannot substitute for the actual fixed runtime tables.
        actual_unit("core", "@source/runtime/Modules/config.c", "Modules/config.o", ("freeze", "link"))
        actual_unit("target", "@source/runtime/Python/frozen.c",
                    "installation-owned-finite-frozen.o", ("link",))
        if missing_native & {"_sqlite3", "sqlite-library"}:
            if target != "@work/bin/lunar-shinka":
                _fail("runtime_native_profile")
            missing_native.update({"_sqlite3", "sqlite-library"})
        # Multi-unit modules are the source-owned complete group, never a
        # caller-selected subset of one module's implementation.
        for module in missing_native:
            for source in native_sources[module]:
                obj = source.removeprefix("@source/")[:-2] + ".o"
                actual_unit("builtin", source, obj, ("freeze", "link"))
    return {"fixture_pipe_addition": pipe,
            "runtime_native_additions": sorted(native, key=lambda row: row["source"])}


def _adaptations(variables: dict, semantics: dict) -> dict:
    """Describe only finite source-owned differences from the original Make."""
    linkforshared = variables["LINKFORSHARED"]
    if linkforshared["tokens"] not in ([], ["-Xlinker", "-export-dynamic"]):
        _fail("dynamic_module")
    literal = "-Xlinker -export-dynamic" if linkforshared["tokens"] else ""
    if linkforshared["expression"] != literal or linkforshared["expanded"] != literal:
        _fail("dynamic_module")
    # The review binds the original cc graph. Direct-LLD successors still need
    # their separately pinned support profile and actual dependency gate.
    for link in semantics["static_links"]:
        argv = link["argv"]
        if (len(argv) < 11
                or argv[:6] != ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o"]
                or not argv[6].startswith("@work/")
                or argv[-3:] != ["-lm", "-lpthread", "-lc"]
                or not argv[7:-3]
                or any(not token.startswith(("@work/objects/", "@work/libraries/"))
                       for token in argv[7:-3])):
            _fail("static_link_vector")
    warning_roots = ("PY_CFLAGS", "PY_CFLAGS_NODIST", "PY_CPPFLAGS",
                     "PY_STDMODULE_CFLAGS", "PY_CORE_CFLAGS", "PY_BUILTIN_MODULE_CFLAGS")
    warnings = sorted({token for name in warning_roots for token in variables[name]["tokens"]
                       if token in _WARNING_DIFFERENCES})
    libdl = None
    if "-ldl" in variables["LIBS"]["tokens"]:
        if variables["LIBS"]["tokens"].count("-ldl") != 1:
            _fail("link_closure")
        # Fixed target.zig classifies c and dl as libc on Musl targets;
        # main.zig sets the same link_libc bit for both. This relation grants
        # neither dynamic loading nor custody of a selected archive.
        libdl = {
            "variable": "LIBS", "declared_token": "-ldl", "actual_cc_token": "-lc",
            "basis": "zig-0.16.0-musl-libc-classification",
            "zig_target_source_sha256": "2aca0d267df23ab3194ea64ace57097db3f5a1b371fde626806d7b7d7402bde9",
            "zig_main_source_sha256": "dd931f83eb6c4747b185185dc8c76e0bc07f7b14361b435c1f1bec212539551b",
            "independent_explicit_libc_support_pin_required": True,
            "dynamic_loading_supported": False,
        }
    replacements, additions = _library_object_relation(variables, semantics)
    return {
        "warning_only_flags": warnings,
        "unconsumed_linkforshared": None if not linkforshared["tokens"] else {
            "expression": linkforshared["expression"],
            "expanded": linkforshared["expanded"],
            "tokens": linkforshared["tokens"],
            "scope": "stock-make-executable-only-not-consumed-by-static-recipe",
        },
        "musl_libdl": libdl,
        "library_object_replacements": replacements,
        **additions,
    }


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
        if name not in variables:
            if name not in _OPTIONAL_ABSENT_VARIABLES:
                _fail("make_assignment")
            continue
        if any(token not in objects or any(token not in linked for linked in linked_objects)
               for token in variables[name]["tokens"]):
            _fail("replacement_object")
    dynload = variables["DYNLOADFILE"]["tokens"]
    if (len(dynload) != 1 or "Python/" + dynload[0] not in objects
            or any("Python/" + dynload[0] not in linked for linked in linked_objects)):
        _fail("dynload_object")
    if variables["MODSHARED_NAMES"]["tokens"]:
        _fail("dynamic_module")
    _adaptations(variables, semantics)
    for name, flag in (("PY_CORE_CFLAGS", "-DPy_BUILD_CORE"),
                       ("PY_BUILTIN_MODULE_CFLAGS", "-DPy_BUILD_CORE_BUILTIN")):
        if flag not in variables[name]["tokens"]:
            _fail("make_role_flags")
    link_libraries = [{token for token in link["argv"] if token.startswith("-l")}
                      for link in semantics["static_links"]]
    for name in ("LIBS", "SYSLIBS", "MODLIBS", "PY_LDFLAGS", "PY_LDFLAGS_NODIST"):
        for token in variables[name]["tokens"]:
            equivalent = "-lpthread" if token == "-pthread" else token
            if name == "LIBS" and token == "-ldl":
                equivalent = "-lc"
            if equivalent == "-static":
                continue
            if not equivalent.startswith("-l") or any(equivalent not in libs for libs in link_libraries):
                _fail("link_closure")
    enabled = {}
    # The fixed local policy is separately bound, not a second copy of
    # bootstrap module discovery that could double-count enabled sources.
    for rows in (setup["Modules/Setup.bootstrap"],):
        disabled = False
        for row in rows:
            if row[0].startswith("*"):
                disabled = row[0] == "*disabled*"
            elif not disabled and row[0] not in _DISABLED:
                if row[0] in enabled or any("Modules/" + path not in sources for path in row[1:]):
                    _fail("module_source")
                enabled[row[0]] = row[1:]
    if (enabled != {name: list(paths) for name, paths in _ENABLED}
            or setup["Modules/Setup.local"] != _setup(
                emit_configure_plan_assets()["Modules/Setup.local"])):
        _fail("setup_contract")
    module_objects = variables["MODOBJS"]["tokens"]
    required_objects = {"Modules/" + path.removesuffix(".c") + ".o" for paths in enabled.values() for path in paths}
    builtin_names = variables["MODBUILT_NAMES"]["tokens"]
    if (not required_objects.issubset(module_objects) or len(module_objects) != len(set(module_objects))
            or set(builtin_names) != set(enabled) or len(builtin_names) != len(set(builtin_names))
            or len(variables["MODDISABLED_NAMES"]["tokens"]) != len(_DISABLED)
            or set(variables["MODDISABLED_NAMES"]["tokens"]) != set(_DISABLED)):
        _fail("module_discovery")


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
    facts = _pinned_review_facts(review_manifest_bytes, expected_review_manifest_sha256)
    if set(facts) != _KEYS:
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
            or facts["outputs"] != pins or type(configuration_header) is not bytes
            or outputs["pyconfig.h"] != configuration_header):
        _fail("output_pin")
    header = _header(outputs["pyconfig.h"])
    variables, absent_references = _make_details(outputs["Makefile"])
    setup = _effective_setup(outputs["Modules/Setup.bootstrap"])
    discovery = _stdlib_discovery(outputs["Modules/Setup.stdlib"])
    absences = _make_absences(outputs["Makefile"])
    modules = _config_modules(outputs["Modules/config.c"])
    semantics = _semantics(stages, compile_roles)
    adaptations = _adaptations(variables, semantics)
    if adaptations["musl_libdl"] is not None and zig_manifest_sha256 != _ZIG_MANIFEST_SHA256:
        _fail("musl_libdl_profile")
    for name, actual in (("header_directives", header), ("make_variables", variables),
                         ("setup_rows", setup), ("config_modules", modules), ("recipe_semantics", semantics),
                         ("make_absences", absences), ("make_absent_references", absent_references),
                         ("stdlib_discovery_rows", discovery),
                         ("adaptations", adaptations)):
        if canonical(facts[name]) != canonical(actual):
            _fail(name)
    graph_sha256 = _sha(canonical(stages))
    if facts["concrete_stages_sha256"] != graph_sha256:
        _fail("stage_graph")
    _closure(variables, setup, semantics)
    sources = tuple(("configuration/original/" + path, raw) for path, raw in configuration_outputs)
    return ReviewedConfigurationBinding((*sources, ("configuration/review.json", review_manifest_bytes)),
                                        expected_review_manifest_sha256, graph_sha256)


def bind_selected_cpython_configuration(
    *, configuration_outputs: tuple[tuple[str, bytes], ...], review_manifest_bytes: bytes,
    expected_review_manifest_sha256: str, source_inventory_sha256: str,
    zig_manifest_sha256: str, configuration_header: bytes, stages: list[dict],
    compile_roles: dict[str, str],
) -> ReviewedConfigurationBinding:
    """Choose v2 by independently pinned schema, never after a v1 refusal."""
    facts = _pinned_review_facts(review_manifest_bytes, expected_review_manifest_sha256)
    binder = (bind_reviewed_cpython_configuration
              if facts.get("schema") == SCHEMA
              else legacy.bind_reviewed_cpython_configuration)
    return binder(
        configuration_outputs=configuration_outputs, review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
        source_inventory_sha256=source_inventory_sha256, zig_manifest_sha256=zig_manifest_sha256,
        configuration_header=configuration_header, stages=stages, compile_roles=compile_roles,
    )
