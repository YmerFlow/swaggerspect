import importlib.metadata
import typing

import pytest

import swaggerspect
import swaggerspect.validate


def properties(api):
    """The parameter schemas of one function or class API (none: no key)."""
    return next(iter(api["properties"].values())).get("properties", {})


# ── Order ────────────────────────────────────────────────────────────────────

def written_in_this_order(zeta: int = 1, alpha: str = "a", mid: float = 0.5, beta: bool = False):
    pass


def test_parameters_keep_their_signature_order():
    """A form lists fields in the order its schema does, so a merge through a
    set showed them in a different order on every run."""
    api = swaggerspect.get_api(written_in_this_order)
    assert list(properties(api)) == ["zeta", "alpha", "mid", "beta"]


class Base:
    zeta = 1
    "Declared first."
    alpha = "a"


class Child(Base):
    mid = 0.5
    beta = False
    "Documented, unlike mid."


def test_class_attributes_keep_their_declaration_order():
    """Bases first, then the class's own, as written; not alphabetical."""
    api = swaggerspect.get_api(Child)
    assert list(properties(api)) == ["zeta", "alpha", "mid", "beta"]


# ── Annotations ──────────────────────────────────────────────────────────────

def annotated(dataset, optional: float | None = None, count: int = 0,
              names: list[str] | None = None, per_channel: float | dict[str, float] = 1.0):
    pass


def test_optional_is_its_type_not_an_object():
    """None in a union only says the parameter may be left out."""
    field = properties(swaggerspect.get_api(annotated))["optional"]
    assert field["type"] == "number"
    assert "anyOf" not in field


def test_generic_annotations_become_typed_fields():
    fields = properties(swaggerspect.get_api(annotated))
    assert fields["count"]["type"] == "integer" and fields["count"]["default"] == 0
    assert fields["names"]["type"] == "array"
    assert fields["names"]["items"]["type"] == "string"


def test_a_scalar_or_mapping_offers_both():
    field = properties(swaggerspect.get_api(annotated))["per_channel"]
    assert [member["type"] for member in field["anyOf"]] == ["number", "object"]
    assert field["anyOf"][1]["additionalProperties"]["type"] == "number"


def test_an_unannotated_parameter_without_default_is_left_out():
    assert "dataset" not in properties(swaggerspect.get_api(annotated))


# ── Required ─────────────────────────────────────────────────────────────────

class Survey:
    """A data object: something the caller passes, not something typed into a form."""


def needs_thresholds(dataset, good_max: float, marginal_max: float, unit: str = "m", **extra):
    pass


def takes_an_object(data: Survey, window: int):
    pass


def arguments(api):
    return next(iter(api["properties"].values()))


def test_a_parameter_without_a_default_is_required():
    assert arguments(swaggerspect.get_api(needs_thresholds))["required"] == [
        "good_max", "marginal_max"]


def test_a_data_object_the_caller_passes_is_not_required():
    """It has no JSON form, so requiring it would make the form unsubmittable."""
    assert arguments(swaggerspect.get_api(takes_an_object))["required"] == ["window"]


def test_nothing_required_means_no_required_list():
    assert "required" not in arguments(swaggerspect.get_api(written_in_this_order))


# ── Docstrings ───────────────────────────────────────────────────────────────

def numpy_style(x: int = 1):
    """Summary.

    Parameters
    ----------
    x : int
        The x.
    """


def test_numpydoc_parameters_are_read():
    assert properties(swaggerspect.get_api(numpy_style))["x"]["description"] == "The x."


# ── Groups ───────────────────────────────────────────────────────────────────

LENGTH_SCALE = {"json_schema": {"x-format": "length-scale"}}


class Undeclared:
    regularization__alpha_s = 1e-4
    regularization__L_r = 500.
    other = 1


class DeclaredFirst:
    regularization: typing.Annotated[typing.Any, LENGTH_SCALE]
    "Smallness and smoothness weights."
    regularization__alpha_s = 1e-4
    regularization__L_r = 500.
    other = 1


class DeclaredAfter:
    regularization__alpha_s = 1e-4
    regularization__L_r = 500.
    other = 1
    regularization: typing.Annotated[typing.Any, LENGTH_SCALE]
    "Smallness and smoothness weights."


class DeclaredNested:
    outer__inner: typing.Annotated[typing.Any, LENGTH_SCALE]
    outer__inner__alpha_s = 1e-4
    outer__other = 1


def grouped(cls):
    return properties(swaggerspect.group_apis_parameters({"anyOf": [swaggerspect.get_api(cls)]})["anyOf"][0])


def test_parameters_sharing_a_prefix_form_a_group():
    fields = grouped(Undeclared)
    assert list(fields) == ["regularization", "other"]
    group = fields["regularization"]
    assert group["type"] == "object" and group["x-python-type"] is None
    assert group["description"] == "regularization"
    assert list(group["properties"]) == ["alpha_s", "L_r"]
    assert group["properties"]["L_r"]["title"] == "L_r"


@pytest.mark.parametrize("cls", [DeclaredFirst, DeclaredAfter])
def test_a_parameter_named_like_a_group_declares_its_keys(cls):
    """Before or after its members; the group stays a group the validator flattens."""
    group = grouped(cls)["regularization"]
    assert group["x-format"] == "length-scale"
    assert group["description"] == "Smallness and smoothness weights."
    assert group["type"] == "object" and group["x-python-type"] is None
    assert list(group["properties"]) == ["alpha_s", "L_r"]


def test_a_declaration_keeps_the_group_where_its_name_first_appears():
    assert list(grouped(DeclaredFirst)) == ["regularization", "other"]
    assert list(grouped(DeclaredAfter)) == ["regularization", "other"]


def test_a_nested_group_can_be_declared():
    outer = grouped(DeclaredNested)["outer"]
    inner = outer["properties"]["inner"]
    assert inner["x-format"] == "length-scale" and inner["x-python-type"] is None
    assert list(inner["properties"]) == ["alpha_s"]
    assert list(outer["properties"]) == ["inner", "other"]


def test_a_declared_group_is_flattened_back_on_validation():
    schema = {"type": "object", "properties": grouped(DeclaredFirst)}
    data = {"regularization": {"alpha_s": 1e-3, "L_r": 200.}, "other": 2}
    swaggerspect.validate.GroupMergingValidator(schema).validate(data)
    assert data == {"other": 2, "regularization__alpha_s": 1e-3, "regularization__L_r": 200.}


# ── Entry points ─────────────────────────────────────────────────────────────

def test_an_entry_point_group_is_found(monkeypatch):
    """The dict interface to entry_points() is gone in Python 3.12, where the
    old lookup silently found nothing."""
    point = importlib.metadata.EntryPoint(
        name="written_in_this_order", value=f"{__name__}:written_in_this_order",
        group="swaggerspect_tests.steps")
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda: importlib.metadata.EntryPoints([point]))
    apis = swaggerspect.get_apis("swaggerspect_tests.steps")
    assert [api["title"] for api in apis["anyOf"]] == ["written_in_this_order"]


def test_an_unknown_group_gives_nothing():
    assert swaggerspect.get_apis_entrypoints("swaggerspect.no-such-group") == {}
