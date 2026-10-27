# Narrow SDD: exact imported inspect CLI exclusion

## Status and scope

Implementation continuation after retaining the failed d152 execution. Focused validation passed in the concentrated407-node union; no complete source or runtime acceptance is claimed. This slice extends the already reviewed imported-only demo source mechanism to one exact official CLI helper; it does not implement a transitive optional initialization graph.

## Observed source contract

The independent CPython3.13.12 original archive SHA256 is 2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593. Lib/inspect.py is128803bytes, SHA256 ea27c96e5b29fe29de8e3ee8840a50d6ff4b05f47cf911f4ee17cb0d4f953ca8. Its only top-level `_main` definition is line3412, no arguments/decorators; its only Name reference is line3471, a direct Load/Call inside the canonical sole top-level if __name__ == '__main__' guard at3470. No alias, rebinding, extra call, literal helper-string/attribute or helper import occurs in that file. The helper contains CLI-only imports argparse/importlib.

The retained Shinka diagnostic route traversed inspect._main -> argparse -> shutil -> bz2 -> missing _bz2. Under the fixed canonical imported inspect module, the sole main guard is false. Excluding the exact original CLI helper/main block from the conservative dependency scan is the smaller reviewed source refinement; it adds no native capability or compression implementation. It does not establish that all other possible bz2 routes are absent.

## Functional requirements

1. Retain the exact five module full-source pins: pickle/difflib/pickletools/heapq plus inspect. The finite helper mapping is `_test` for the first three, None for heapq, `_main` for inspect. Do not prune arbitrary `_main`/`_test` functions or unrelated module main blocks.
2. Require the complete pinned source whenever an exclusion is applied, one canonical main guard without else, a sole no-argument undecorated helper, and exactly one Name Load which is that helper's direct call inside the guard. Any helper alias, store/delete, second caller, changed signature/decorator, altered source or main guard refuses.
3. Selected sources must reject literal attributes/string reflection/from-helper/star import references to the finite private helper names. Dynamic reflection stays unverified. Keep the original source bytes unchanged in the frozen closure; exclusion is dependency-analysis evidence only.
4. Record inspect's specific full source hash, guard/call lines, function `_main`, one literal call and false dynamic-reflection flag through the existing `excluded_imported_selftests` field. Keep existing evidence keys compatible; do not claim runtime execution, complete import closure, production admission, or acceptance.
5. Keep functional bodies conservatively scanned, including a real required argparse/shutil/bz2 import outside the excluded helper. No `_bz2`/`_posixsubprocess` availability, blanket absent entry, fake source/config, native roster expansion or optional graph framework.

## Three-file implementation

Implementation changes runtime_closure.py, its focused tests, and concrete-build-recipe.md. Add the independent inspect source pin and finite helper mapping; reuse existing proof checks with module-specific helper name; extend artificial tests and evidence checks. Do not modify upstream source files.

## Validation planned for parent

Focused tests must cover inspect plus all four original modules; official-pin drift; helper aliases/rebindings/calls/deletes; literal external helper references; argument/decorator signatures; main guard else; unrelated module bodies remain scanned; required functional imports remain; exact raw source preservation and wire evidence with false runtime claims. The author performed AST parsing only. Root owns the concentrated focused/static validation after this development batch freezes; no upstream code or SSH is executed by this source slice.

No test or source-closure success is claimed by this SDD. The prior OpenEvolve subprocess/profile decision, possible other Shinka bz2 edges, missing reviewed target pyconfig.h, approved isolation/build/freezer/ELF/sealed-startup and CLI acceptance remain open.


## Actual source check

One new archive check of each solver completed without upstream execution. Both
still refuse: OpenEvolve at exact subprocess:81 `_winapi`; Shinka at `_bz2`,
with another observed path calendar:700 -> argparse -> shutil -> bz2. This proves
that excluding inspect CLI alone does not close either graph. No compression,
process helper, fake module or blanket absence was added. The next source/profile
work remains separate from reviewed target configuration and isolated runtime
acceptance. See the latest repository batch acceptance record for actual reports.
