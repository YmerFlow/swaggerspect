import inspect
import numpydoc.docscrape
import ast
import typing
import types
import importlib.metadata
import copy
import sys
import warnings
from . import type_schema
from . import value_schema
from . import schema_utils
from . import class_api
from . import function_api

def get_api(obj, name = None):
    """Generate a swagger specification fragment for a single function
    call or class instantiation."""
    if type(obj) is type:
        return class_api.get_class_api(obj, name=name)
    elif inspect.isfunction(obj):
        return function_api.get_function_api(obj, name=name)
    return None

def get_apis_dict(objs, local_names = False):
    return {
        "anyOf": [v
                  for v in [get_api(v, name = k if local_names else None)
                            for k, v in objs.items()]
                  if v]}

def get_apis_entrypoints(group):
    entrypoints = importlib.metadata.entry_points()
    if hasattr(entrypoints, "select"):
        # Python 3.10+. The dict interface below was removed in 3.12, where
        # it silently found no group at all.
        entrypoints = entrypoints.select(group=group)
    elif group in entrypoints:
        entrypoints = entrypoints[group]
    else:
        return {}
    if not entrypoints: return {}
    docs = get_apis_dict({entry.name: entry.load()
                          for entry in entrypoints}, local_names=True)
    docs["title"] = group
    docs["description"] = group
    return docs
    
def get_apis_module(module):
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except:
            return {}
    if not isinstance(module, types.ModuleType):
        return {}
    docs = get_apis_dict({name: getattr(module, name)
                         for name in dir(module)
                         if not name.startswith("__")})
    docs["title"] = module.__name__
    docs["description"] = inspect.getdoc(module) or module.__name__
    return docs

def get_apis_class(cls):
    if isinstance(cls, str):
        try:
            module, name = cls.rsplit(".", 1)
            cls = getattr(importlib.import_module(module), name)
        except:
            return {}
    if not isinstance(cls, type):
        return {}
    docs = get_apis_dict({name: getattr(cls, name)
                          for name in dir(cls)
                          if not name.startswith("__")},
                         local_names=True)
    docs["title"] = type_schema.get_type_name(cls)
    docs["description"] = inspect.getdoc(cls) or cls.__name__
    return docs

# A group's own keys: built here, never taken from a declaration. An x-python-type
# of None is what tells validate.GroupMergingValidator to flatten the group back.
_GROUP_KEYS = ("type", "properties", "x-python-type")

def _is_group(schema):
    """Whether a schema is a group built by _group_parameters (the validator's own test)."""
    return schema.get("x-python-type", True) is None

def _declared(group, declaration):
    """The group with the keys of a parameter declared under the group's own name added."""
    return dict(group, **{k: v for k, v in declaration.items() if k not in _GROUP_KEYS})

def _subgroup(parent, name):
    """The group `name` in `parent`, built if missing, taking the keys of a declaration found there."""
    existing = parent.get(name)
    if existing is None or not _is_group(existing):
        group = {"type": "object", "title": name, "description": name,
                 "properties": {}, "x-python-type": None}
        parent[name] = group if existing is None else _declared(group, existing)
    return parent[name]

def _group_parameters(parameters):
    """Nest ``a__b`` parameters into group objects; see the README.

    A parameter named like a group (``a``, or ``a__b`` for a nested group) declares
    that group's own schema keys, such as ``x-format`` or a description, whether it
    comes before or after the group's members. The group keeps its own ``type``,
    ``properties`` and ``x-python-type``.

    Parameters
    ----------
    parameters : dict
        Parameter name to JSON schema, the names using ``__`` as a path separator.

    Returns
    -------
    dict
        Group or parameter name to JSON schema, in the order of first appearance.
    """
    grouped_by_name = {}
    for name, schema in parameters.items():
        *path, leaf = name.split("__")
        parent = grouped_by_name
        for item in path:
            parent = _subgroup(parent, item)["properties"]
        schema = dict(schema)
        if path and "title" not in schema:
            schema["title"] = leaf
        existing = parent.get(leaf)
        parent[leaf] = _declared(existing, schema) if existing is not None and _is_group(existing) else schema
    return grouped_by_name

def group_apis_parameters(apis):
    apis = copy.deepcopy(apis)
    for api in apis["anyOf"]:
        method = next(iter(api["properties"].values()))
        if "properties" in method:
            method["properties"] = _group_parameters(method["properties"])
    return apis

def get_apis(objs, group_parameters = True, multi=False):
    """Generates a swagger specification for module or entry point group.
    If group_parameters is True, then parameter names are treated as
    "__" separated paths in a tree of dictionaries.
    """
    res = schema_utils.merge(schema_utils.merge(get_apis_module(objs), get_apis_entrypoints(objs)), get_apis_class(objs))
    if group_parameters:
        res = group_apis_parameters(res)
    if multi:
        res = {"type": "array",
               "title": res["title"],
               "description": res["description"],
               "items": res}
    return res
    
def swagger_to_json_schema(api, multi = True):
    warnings.warn("swagger_to_json_schema is deprecated; apis are now json_schemas by default", DeprecationWarning)
    if "items" in api:
        if multi:
            return api
        return api["items"]
    else:
        if multi:
            return {"type": "array",
                    "title": api["title"],
                    "description": api["description"],
                    "items": api}
        return api

def _json_schema_to_swagger_parameter(name, schema):
    return {
        "in": "query",
        "name": name,
        "description": schema.get("description", name) if isinstance(schema, dict) else name,
        "schema": schema
    }
        
def _json_schema_to_swagger_endpoint(schema):
    operation_id, params = next(iter(schema["properties"].items()))
    return {
        "/" + operation_id: {
            "get": {
                "description": schema["description"],
                "operationId": operation_id,
                "parameters": [_json_schema_to_swagger_parameter(name, schema)
                               for name, schema in params["properties"].items()]
            }
        }
    }

def json_schema_to_swagger(api):
    if "items" in api: api = api["items"]
    return {
        "info": {
            "description": api["description"],
            "title": api["title"],
            "version": '1.0'
        },
        "openapi": "3.0.3",
        "paths": [_json_schema_to_swagger_endpoint(schema)
                  for schema in api["anyOf"]]
    }

class JsonSchema(object):
    """Type annotation that accepts any type (like typing.Any), but
    outputs the supplied JSON Schema in swaggerspect.
    """    
    def __new__(cls, schema):
        self = object.__new__(cls)
        self.json_schema = schema
        return typing.Annotated[typing.Any, self]
