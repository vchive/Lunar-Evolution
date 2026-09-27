"""Keep the documented producer lifecycle matrix tied to real provider-free fixtures."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "specs/156-producer-process-lifecycle/acceptance-matrix.md"
_REF = re.compile(r"`(tests/[A-Za-z0-9_./-]+\.py)::(test_[A-Za-z0-9_]+)`")
_ROW = re.compile(r"^\| (L(?:156|157|158)-\d{2}) \| [^|]+ \| .* \| (offline-verified|supporting-only|integration-open) \|", re.MULTILINE)


def _test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    }


def test_lifecycle_matrix_is_canonical_and_references_real_fixtures() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    rows = _ROW.findall(text)
    assert len(rows) >= 18
    assert len({case_id for case_id, _status in rows}) == len(rows)
    assert {status for _case_id, status in rows} == {
        "offline-verified", "supporting-only", "integration-open",
    }

    references_by_case: dict[str, list[tuple[str, str]]] = {}
    for line in text.splitlines():
        match = re.match(r"^\| (L(?:156|157|158)-\d{2}) \|", line)
        if not match:
            continue
        references_by_case[match.group(1)] = _REF.findall(line)

    assert set(references_by_case) == {case_id for case_id, _status in rows}
    discovered: dict[str, set[str]] = {}
    for case_id, references in references_by_case.items():
        for relative, function in references:
            path = ROOT / relative
            assert path.is_file(), f"{case_id} references missing fixture file {relative}"
            discovered.setdefault(relative, _test_names(path))
            assert function in discovered[relative], f"{case_id} references missing {relative}::{function}"

    # Open rows are allowed to point only at design/task evidence; they must not accidentally
    # claim a provider-free test has already closed a production integration gate.
    for case_id, status in rows:
        if status == "integration-open":
            assert not references_by_case[case_id], f"{case_id} must remain design-only"
