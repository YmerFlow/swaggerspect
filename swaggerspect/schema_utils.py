def merge(a, b):
    if a is None: return b
    if b is None: return a
    if type(a) is not type(b): return a
    if isinstance(a, dict):
        # a's keys first, then b's new ones, in the order they were written:
        # a form lists fields in the order its schema does.
        keys = list(a) + [k for k in b if k not in a]
        return {k: merge(a.get(k), b.get(k)) for k in keys}
    return a

def remove_empty(obj):
    if not isinstance(obj, dict): return obj
    return {k: v for
            k, v in [(k, remove_empty(v))
                     for k, v in obj.items()]
            if v != {}}

def remove_hidden(api):
    api = dict(api)
    if "properties" in api:
        api["properties"] = {
            key: value
            for key, value in api["properties"].items()
            if not value.get("hide", False)}
    if "propertyOrder" in api:
        if "properties" in api:
            api["propertyOrder"] = [prop for prop in api["propertyOrder"] if prop in api["properties"]]
        else:
            del api["propertyOrder"]
    return api
