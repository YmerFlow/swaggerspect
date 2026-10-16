import inspect
import typing
import types
import sys

def get_type_name(obj):
    if obj is None: return None
    if obj is typing.Any: return 'typing.Any'
    return obj.__module__ + "." + obj.__name__

typemap = {
    'builtins.str': {'type':'string'},
    'builtins.int': {'type':'integer'},
    'builtins.float': {'type':'number'},
    'builtins.bool': {'type':'boolean'},
    'builtins.list': {'type':'array'},
    'builtins.dict': {'type':'object'},
    'typing.Any': {},
    'tuple': {'type':'array'},
    'str': {'type':'string'},
    'int': {'type':'integer'},
    'float': {'type':'number'},
    'bool': {'type':'boolean'},
    'list': {'type':'array'},
    'tuple': {'type':'array'},
    'dict': {'type':'object'},
    'pydantic.networks.AnyUrl': {"type": "string", "format": "url"}, # Modern pydantic
    'pydantic_core._pydantic_core.Url': {"type": "string", "format": "url"} # pydantic_core <= 2.23.3 
}

def has_json_form(schema):
    """False for a type with no JSON equivalent, which falls back to a bare object."""
    return not (schema.get("type") == "object"
                and schema.get("x-python-type") not in ("builtins.dict", "dict", "typing.Any")
                and "properties" not in schema
                and "additionalProperties" not in schema)

def typeof(v):
    if v is None: return None
    if v is inspect._empty: return None
    return type(v)

def make_type_schema(*typenames, hasdefault=None):
    for typename in typenames:
        if typename is inspect._empty:
            continue
        if typename is None:
            continue

        orig = repr(typename)
        schema = {}
        args = None
        metadatas = None
        if not isinstance(typename, str):
            if isinstance(typename, typing.TypeVar):
                bound = typename.__bound__
                if isinstance(bound, typing.ForwardRef):
                    module = sys.modules[typename.__module__]
                    bound = bound._evaluate(module.__dict__, {}, set())
                typename = bound
            if isinstance(typename, typing._AnnotatedAlias):
                metadatas = typename.__metadata__
                typename = typename.__args__[0]
            if isinstance(typename, typing._LiteralGenericAlias):
                schema["enum"] = list(typing.get_args(typename))
                typename = get_type_name(type(schema["enum"][0]))
            elif isinstance(typename, (types.UnionType, typing._UnionGenericAlias)):
                # None in a union only says the parameter is optional, which
                # leaving it out of "required" already says. A member with no
                # JSON form, a class nobody can type into a form, is dropped.
                members = [make_type_schema(arg) for arg in typing.get_args(typename)
                           if arg is not type(None)]
                members = [member for member in members if has_json_form(member)]
                if len(members) == 1:
                    schema.update(members[0])
                    typename = members[0]["x-python-type"]
                elif members:
                    schema["anyOf"] = members
                    typename = "types.UnionType"
                else:
                    # Nothing a form can supply: hidden, like an opaque type with a default.
                    schema["hide"] = True
                    typename = repr(typename)
            else:
                if hasattr(typename, "json_schema"):
                    metadatas = [typename]
                args = typing.get_args(typename)
                typename = get_type_name(typename)

        pytypename = typename
        schema.update(typemap.get(typename, {}))

        if schema.get("type", None) is None and typename != "types.UnionType":
            schema["type"] = "object"
            if typeof(hasdefault) is not None:
                schema["hide"] = True
        
        schema["x-python-type"] = pytypename
        #schema["x-python-orig"] = orig
        if schema.get("type") == "array" and args:
            schema["items"] = make_type_schema(args[0])
        elif schema.get("type") == "object" and args:
            schema["propertyNames"] = make_type_schema(args[0])
            schema["additionalProperties"] = make_type_schema(args[1])

        if metadatas:
            for metadata in metadatas:
                if isinstance(metadata, dict):
                    schema.update({key[len("swaggerspect_"):]: value
                                   for key, value in metadata.items()
                                   if key.startswith("swaggerspect_")})
                    if "json_schema" in metadata:
                        schema.update(metadata["json_schema"])
                else:
                    schema.update({key[len("swaggerspect_"):]: getattr(metadata, key)
                                   for key in dir(metadata)
                                   if key.startswith("swaggerspect_")})
                    if hasattr(metadata, "json_schema"):
                        schema.update(metadata.json_schema)
        return schema
    return {}
