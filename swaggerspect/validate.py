"""Validation tools"""


import jsonschema

__all__ = ["GroupMergingValidator"]

validate_properties = jsonschema.Draft202012Validator.VALIDATORS["properties"]


class GroupMergingValidator(object):
    """jsonchema validator class that validates
data against a schema, but also transforms your data ungrouping any
parameters grouped by `get_apis(objs, group_parameters = True)`.
"""
    def __init__(self, *arg, **kw):
        self.renames = []
        self.cls = jsonschema.validators.extend(
            jsonschema.Draft202012Validator, {"properties" : self._merge_groups}) 
        self.inst = self.cls(*arg, **kw)

    def _merge_groups(self, validator, properties, instance, schema):
        """Validate `properties`, then queue the instance's groups for flattening."""
        for error in validate_properties(validator, properties, instance, schema):
            yield error

        # Like "properties" itself, say nothing about an instance that is not an object.
        if not validator.is_type(instance, "object"):
            return
        for property, subschema in properties.items():
            if subschema.get("x-python-type", True) is None:
                self.renames.append((instance, property))

    def __getattr__(self, name):
        return getattr(self.inst, name)

    def validate(self, data):
        """Validate `data` against the schema, then flatten its groups in place.

        A group ``a`` holding ``{"b": 1}`` becomes the parameter ``a__b``.
        A group the data leaves out is skipped, so the function's own
        defaults for its members apply; ``required`` has already been
        enforced by then.

        Parameters
        ----------
        data : dict
            Parameters in the grouped form of the schema; changed in place.

        Raises
        ------
        jsonschema.ValidationError
            If `data` does not validate against the schema.
        """
        self.renames = []
        self.inst.validate(data)
        for instance, prop in self.renames:
            # Absent, or queued twice (anyOf / oneOf can visit one instance
            # more than once) and already flattened: nothing to do.
            if prop not in instance:
                continue
            for key, value in instance.pop(prop).items():
                instance[prop + "__" + key] = value
