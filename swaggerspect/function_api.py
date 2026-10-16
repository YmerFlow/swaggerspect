import inspect
import numpydoc.docscrape
import ast
import typing
import types
import importlib.metadata
import copy
import sys
from . import type_schema
from . import value_schema
from . import schema_utils

def check_annotations(fn):
    """Annotations must be types. ``from __future__ import annotations`` turns
    them into text, which no field can be built from."""
    signature = inspect.signature(fn)
    annotations = {name: p.annotation for name, p in signature.parameters.items()}
    annotations["return"] = signature.return_annotation
    for name, annotation in annotations.items():
        if isinstance(annotation, str):
            raise TypeError(
                f"{fn.__module__}.{fn.__qualname__}: {name!r} is annotated with "
                f"the text {annotation!r}, not a type. Remove "
                f"`from __future__ import annotations` from {fn.__module__}.")

def get_function_api_parameters_inspect(fn):
    check_annotations(fn)
    return schema_utils.remove_empty(
        {
            "propertyOrder": list(inspect.signature(fn).parameters.keys()),
            "properties": {
                k: schema_utils.merge(
                    type_schema.make_type_schema(
                        v.annotation,
                        type_schema.typeof(v.default),
                        hasdefault = v.default),
                    value_schema.make_value_schema(v.default))
                for k, v in inspect.signature(fn).parameters.items()
            }
        }
    )

def get_function_api_parameters_comments(fn):
    docs = inspect.getdoc(fn)
    if docs is None: return []
    docast = numpydoc.docscrape.NumpyDocString(docs)

    return {
         # propertyOrder will never be used, as merge() will prefer the one from inspect, included for completeness
        "propertyOrder": [p.name for p in docast["Parameters"]],
        "properties": {
            p.name: schema_utils.merge(
                {"description": "\n".join(p.desc)},
                type_schema.make_type_schema(p.type))
            for p in docast["Parameters"]}}

def get_function_api(fn, name = None):
    args = schema_utils.remove_hidden(
        schema_utils.merge(
            {"type": "object",
             "additionalProperties": False},
            schema_utils.merge(get_function_api_parameters_inspect(fn),
                               get_function_api_parameters_comments(fn))))

    # A parameter with no default has to be given, so a form should catch the
    # omission rather than the call. Only fields a form can supply count: an
    # argument the caller passes itself, such as a data object, has no JSON form.
    required = [name for name, p in inspect.signature(fn).parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                and name in args.get("properties", {})
                and type_schema.has_json_form(args["properties"][name])]
    if required:
        args["required"] = required

    docs = inspect.getdoc(fn)
    description = type_schema.get_type_name(fn)
    if docs is not None:
        docast = numpydoc.docscrape.NumpyDocString(docs)
        description = "\n".join(docast["Summary"] + docast["Extended Summary"])

    returntype = inspect.signature(fn).return_annotation

    operation_id = name or type_schema.get_type_name(fn)
    return schema_utils.remove_empty(
        {
            "type": "object",
            "title": operation_id.split(".")[-1],
            "description": description,
            "required": [operation_id],
            "additionalProperties": False,
            "properties": {operation_id: args},
            "x-returntype": type_schema.make_type_schema(returntype)
        })
