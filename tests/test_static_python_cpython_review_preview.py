"""Pure graph observations, independent fixture reviews and pre-refactor goldens.

The existing fixture factories use synthetic source/configuration identities and
an inert Zig inventory. Their normal v1/v2 binders still run; no binder is
intercepted to invent a positive review. No compiler or target runs here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import fields

import pytest

from tests.test_static_python_concrete_recipe import (
    concrete_inputs,  # noqa: F401 - imported fixture dependency
)
from tests.test_static_python_configuration_review import (
    _arguments as v1_arguments,
)
from tests.test_static_python_configuration_review import (
    review_case,  # noqa: F401 - imported fixture dependency
)
from tests.test_static_python_configuration_review_v2 import (
    _arguments as v2_arguments,
)
from tests.test_static_python_configuration_review_v2 import (
    review_v2_case,  # noqa: F401 - imported fixture dependency
    runtime_review_v2_case,  # noqa: F401 - imported fixture dependency
)
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture.configuration_review import ConfigurationReviewError
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError, _recipe
from tools.static_python_rsi_fixture.runtime_closure import canonical

# Captured by pure calls to the unchanged 5ea6210 tree before refactoring.
# Each tuple hashes recipe bytes, manifest bytes and the ordered descriptor of
# every source's path/length/byte digest. These are compatibility fixtures only.
_LEGACY_GOLDEN = {
    "default": (
        "0aa34007472af82e111cba76e694591669cdad9c7ec57034e684061008c48ace",
        "83fa29513d5b074d7f86b7a1fc8ed202d150578fe8e8c4e8b49672b16cd89f8a",
        "c8cd126abec1c6f638803a92475d51933235bbb27316cf3d49de4065ccdd27fa",
    ),
    "v1": (
        "cb9ee505679f92eb32fd4fc17dbbeca3b2cc1e48aba1ee3101adf3d662eb1463",
        "ad274ac4538aa7137a43df6b832481fa6627acf814d545971d819f6d2521da5e",
        "29f9e19ce05a5fd7a3ae48123282d6206f0e632f270ea7afc3884fa1ae7c32c0",
    ),
    "v2": (
        "5841addf9aff396f9fea166a962e12b63f389cc8edef579c44748006718015b3",
        "44cfae893872d183a5b7bd39629d6f2f90b4f1bdc736f1318fc3acea84288ab9",
        "4bedd8ef7457d7237a73e93e75b20c4b7337e3fae5d5327f2a346935ea025bdb",
    ),
}
_FALSE = (
    "configuration_review_approved", "review_binding_created", "executable_recipe_returned",
    "build_performed", "configured_closure_verified", "installation_accepted",
    "runtime_execution_performed", "production_admission", "immutable_custody_verified",
    "online_publication",
)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _preview(case, **changes):
    arguments = {**case[1], "configuration_outputs": case[2], **changes}
    return concrete.preview_cpython_build_review_v2(case[0], **arguments)


@pytest.mark.parametrize("route", ["default", "v1", "v2"])
def test_preexisting_preparation_bytes_match_independent_old_goldens(
    concrete_inputs, review_case, review_v2_case, route,  # noqa: F811
):
    if route == "default":
        preparation, arguments = concrete_inputs
    else:
        case = review_case if route == "v1" else review_v2_case
        preparation = case[0]
        arguments = (v1_arguments if route == "v1" else v2_arguments)(case)
    recipe = concrete.prepare_cpython_build_recipe(preparation, **arguments)
    sources = [{"path": path, "size": len(raw), "sha256": _sha(raw)}
               for path, raw in recipe.sources]
    assert (_sha(recipe.recipe_bytes), _sha(recipe.manifest_bytes), _sha(canonical(sources))) == (
        _LEGACY_GOLDEN[route]
    )


def test_preview_matches_the_complete_independently_bound_v2_graph(review_v2_case):  # noqa: F811
    case = review_v2_case
    observed = _preview(case)
    approved_fixture = concrete.prepare_cpython_build_recipe(case[0], **v2_arguments(case))
    wire, graph = json.loads(observed.preview_bytes), json.loads(approved_fixture.recipe_bytes)
    assert canonical(wire) == observed.preview_bytes
    assert wire["stages"] == graph["stages"] == case[4]
    assert wire["compile_roles"] == case[5]
    assert wire["observed_concrete_stages_sha256"] == _sha(canonical(case[4]))
    assert wire["source_inputs"] == [row for row in graph["inputs"]["source"]
                                     if row["path"] != "configuration/review.json"]
    assert wire["toolchain_inputs"] == graph["inputs"]["toolchain"]
    assert [stage["stage"] for stage in wire["stages"]] == ["configure", "freeze", "compile", "link"]
    assert [task["output"] for task in wire["freeze_tasks"]] == [
        command["outputs"][0]["path"] for command in wire["stages"][1]["commands"]
        if command["argv"][0] == "@work/bin/lunar-freeze-module"
    ]
    generated = {row["path"]: row for row in wire["generated_sources"]}
    for path, raw in approved_fixture.sources:
        if not path.startswith("configuration/original/") and path != "configuration/review.json":
            assert generated[path] == {"path": path, "size": len(raw), "sha256": _sha(raw),
                                       "executable": False}
    for (path, raw), row in zip(case[2], wire["configuration_outputs"], strict=True):
        assert row == {"path": path, "size": len(raw), "sha256": _sha(raw), "executable": False}
    assert _preview(case).preview_bytes == observed.preview_bytes


def test_runtime_preview_preserves_real_overlay_roles_and_freezer_outputs(runtime_review_v2_case):  # noqa: F811
    case, closure = runtime_review_v2_case
    facts = json.loads(closure.wire_bytes)
    preview = json.loads(_preview(case, runtime_closure=closure).preview_bytes)
    recipe = concrete.prepare_cpython_build_recipe(case[0], **v2_arguments(case), runtime_closure=closure)
    assert preview["stages"] == json.loads(recipe.recipe_bytes)["stages"] == case[4]
    assert preview["compile_roles"] == case[5]
    assert preview["runtime_closure_sha256"] == closure.sha256
    assert preview["freeze_tasks"] == facts["frozen"]
    assert preview["compile_roles"]["@source/Modules/_json.c"] == "builtin"
    assert "@source/runtime/Modules/config.c" in preview["compile_roles"]
    assert "@source/runtime/Python/frozen.c" in preview["compile_roles"]
    sources = {row["path"]: row for row in preview["source_inputs"]}
    names = dict(closure.sources)["runtime/Python/stdlib_module_names.h"]
    assert sources["Python/stdlib_module_names.h"]["sha256"] == _sha(names)
    assert sources["runtime/closure.json"]["sha256"] == _sha(closure.wire_bytes)


def test_preview_is_a_distinct_nonexecuting_dto_and_does_not_satisfy_review(review_v2_case):  # noqa: F811
    case = review_v2_case
    preview = _preview(case)
    wire = json.loads(preview.preview_bytes)
    assert type(preview) is concrete.CPythonBuildReviewPreview
    assert [field.name for field in fields(preview)] == ["preview_bytes"]
    assert not isinstance(preview, concrete.ConcreteBuildRecipe)
    assert all(not hasattr(preview, name) for name in ("recipe_bytes", "sources", "manifest_bytes", "sha256"))
    assert wire["schema"] == "lunar-cpython-build-review-preview-v1"
    assert wire["status"] == "unapproved-review-preview"
    assert wire["configuration_review_version"] == 2
    assert all(wire[name] is False for name in _FALSE)
    assert wire["missing_approval_artifacts"] == ["configuration/review.json"]
    assert "configuration/review.json" not in {row["path"] for row in wire["source_inputs"]}
    assert not {"recipe_sha256", "configuration_review_manifest_sha256",
                "reviewed_concrete_stages_sha256"} & set(wire)
    with pytest.raises(BuildExecutionError):
        _recipe(preview.preview_bytes, _sha(preview.preview_bytes), version3=True)
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_review_incomplete"):
        concrete.prepare_cpython_build_recipe(case[0], **case[1], configuration_outputs=case[2])
    with pytest.raises(ConfigurationReviewError):
        concrete.prepare_cpython_build_recipe(
            case[0], **case[1], configuration_outputs=case[2],
            review_manifest_bytes=preview.preview_bytes,
            expected_review_manifest_sha256=_sha(preview.preview_bytes),
        )


def test_preview_has_no_profile_selector_callback_or_approval_parameter():
    assert list(inspect.signature(concrete.preview_cpython_build_review_v2).parameters) == [
        "preparation", "source_inventory_bytes", "expected_source_inventory_sha256", "zig_manifest_bytes",
        "configuration_header", "expected_configuration_sha256", "configuration_outputs",
        "runtime_closure", "producer_lifecycle_profile",
    ]


@pytest.mark.parametrize("index", range(8))
def test_each_original_output_is_required_before_preview(review_v2_case, index):  # noqa: F811
    outputs = review_v2_case[2]
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_preview_output_set"):
        _preview(review_v2_case, configuration_outputs=outputs[:index] + outputs[index + 1:])


@pytest.mark.parametrize("mutation", ["list", "reorder", "duplicate", "empty", "text", "header"])
def test_original_output_shapes_and_header_identity_are_not_inferred(review_v2_case, mutation):  # noqa: F811
    outputs = review_v2_case[2]
    if mutation == "list":
        outputs = list(outputs)
    elif mutation == "reorder":
        outputs = (outputs[1], outputs[0], *outputs[2:])
    elif mutation == "duplicate":
        outputs = (outputs[0], outputs[0], *outputs[2:])
    elif mutation in {"empty", "text"}:
        outputs = (outputs[0], (outputs[1][0], b"" if mutation == "empty" else "text"), *outputs[2:])
    else:
        outputs = ((outputs[0][0], outputs[0][1] + b"/* different */\n"), *outputs[1:])
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_preview_"):
        _preview(review_v2_case, configuration_outputs=outputs)


@pytest.mark.parametrize("string_subclass", [False, True])
def test_output_key_objects_are_rejected_without_comparison_callbacks(review_v2_case, string_subclass):  # noqa: F811
    called = []

    class ExplosiveKey(str if string_subclass else object):
        def __eq__(self, other):
            called.append(other)
            raise AssertionError("untrusted key comparison")

    key = ExplosiveKey("pyconfig.h") if string_subclass else ExplosiveKey()
    outputs = ((key, review_v2_case[2][0][1]), *review_v2_case[2][1:])
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_preview_output_set"):
        _preview(review_v2_case, configuration_outputs=outputs)
    assert called == []


@pytest.mark.parametrize("field", ["source_inventory_bytes", "configuration_header"])
def test_preview_checks_original_source_and_header_pins(review_v2_case, field):  # noqa: F811
    with pytest.raises(concrete.ConcreteRecipeError, match="input_pin_mismatch"):
        _preview(review_v2_case, **{field: review_v2_case[1][field] + b"changed"})


@pytest.mark.parametrize("path", ["configuration/review.json", "configuration/original/Makefile"])
def test_existing_review_metadata_cannot_be_presented_as_fresh_preview(review_v2_case, path):  # noqa: F811
    inventory = json.loads(review_v2_case[1]["source_inventory_bytes"])
    inventory.append({"path": path, "size": 1, "sha256": _sha(b"x"), "executable": False})
    raw = canonical(sorted(inventory, key=lambda row: row["path"]))
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_review_overlap"):
        _preview(review_v2_case, source_inventory_bytes=raw, expected_source_inventory_sha256=_sha(raw))


def test_partial_review_still_precedes_invalid_build_inputs(review_v2_case):  # noqa: F811
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_review_incomplete"):
        concrete.prepare_cpython_build_recipe(
            review_v2_case[0], **{**review_v2_case[1], "source_inventory_bytes": b"invalid"},
            configuration_outputs=review_v2_case[2],
        )


def test_invalid_completion_profile_cannot_be_previewed(review_v2_case):  # noqa: F811
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_invalid"):
        _preview(review_v2_case, producer_lifecycle_profile="unapproved")
