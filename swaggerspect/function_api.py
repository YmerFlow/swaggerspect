import inspect
import numpydoc.docscrape
import ast
import functools
import operator
import typing
import types
import importlib.metadata
import copy
import sys
from . import type_schema
from . import value_schema
from . import schema_utils

def split_union(text):
    """The members of a union written as text, splitting only at the top level."""
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "|" and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts

def resolve_annotation(annotation, namespace):
    """The type a text annotation names.

    ``from __future__ import annotations`` leaves every annotation as text, and
    text such as ``"float | None"`` matches no type name. It is evaluated in the
    namespace of the module that defines the function, as typing.get_type_hints
    does. A union member that cannot be resolved there is dropped: it names a
    type that module never imported, which a JSON value cannot be anyway.
    """
    if not isinstance(annotation, str):
        return annotation
    try:
        return eval(annotation, dict(namespace))
    except (NameError, AttributeError, TypeError, SyntaxError):
        pass
    members = []
    for part in split_union(annotation):
        try:
            members.append(eval(part, dict(namespace)))
        except (NameError, AttributeError, TypeError, SyntaxError):
            continue
    if not members:
        return inspect.Parameter.empty
    return functools.reduce(operator.or_, members)

def get_function_api_parameters_inspect(fn):
    namespace = getattr(fn, "__globals__", {})
    return schema_utils.remove_empty(
        {
            "propertyOrder": list(inspect.signature(fn).parameters.keys()),
            "properties": {
                k: schema_utils.merge(
                    type_schema.make_type_schema(
                        resolve_annotation(v.annotation, namespace),
                        type_schema.typeof(v.default),
                        hasdefault = v.default),
                    value_schema.make_value_schema(v.default))
                for k, v in inspect.signature(fn).parameters.items()
            }
        }
    )

def sphinx_parameters(docs):
    """``:param name: text`` entries, for docstrings written in Sphinx style."""
    described, current = {}, None
    for line in docs.splitlines():
        stripped = line.strip()
        if stripped.startswith(":param "):
            name, _, text = stripped[len(":param "):].partition(":")
            current = name.split()[-1]  # ":param int name:" names its type first
            described[current] = text.strip()
        elif current and stripped and not stripped.startswith(":"):
            described[current] += " " + stripped
        else:
            current = None
    return described

def get_function_api_parameters_comments(fn):
    docs = inspect.getdoc(fn)
    if docs is None: return []
    docast = numpydoc.docscrape.NumpyDocString(docs)

    if not docast["Parameters"]:
        described = sphinx_parameters(docs)
        return {
            "propertyOrder": list(described),
            "properties": {name: {"description": text} for name, text in described.items()}}

    return {
         # propertyOrder will never be used, as merge() will prefer the one from inspect, included for completeness
        "propertyOrder": [p.name for p in docast["Parameters"]],
        "properties": {
            p.name: schema_utils.merge(
                {"description": "\n".join(p.desc)},
                type_schema.make_type_schema(p.type))
            for p in docast["Parameters"]}}

def description_lines(lines):
    """Docstring prose up to the first Sphinx field (``:param``, ``:returns``...)."""
    out = []
    for line in lines:
        if line.strip().startswith(":"):
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out

def get_function_api(fn, name = None):
    args = schema_utils.remove_hidden(
        schema_utils.merge(
            {"type": "object",
             "additionalProperties": False},
            schema_utils.merge(get_function_api_parameters_inspect(fn),
                               get_function_api_parameters_comments(fn))))

    docs = inspect.getdoc(fn)
    description = type_schema.get_type_name(fn)
    if docs is not None:
        docast = numpydoc.docscrape.NumpyDocString(docs)
        description = "\n".join(description_lines(docast["Summary"] + docast["Extended Summary"]))

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
