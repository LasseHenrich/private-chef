"""Validate tool input against the same bounded schemas sent to the model."""

import math


class ChefError(ValueError):
    """An actionable, safe-to-display application error."""


def validate(value, schema: dict, path: str = "input") -> None:
    kind = schema["type"]
    types = {"object": dict, "array": list, "string": str, "number": (int, float),
             "integer": int, "boolean": bool}
    if not isinstance(value, types[kind]) or (kind in {"number", "integer"}
                                             and isinstance(value, bool)):
        raise ChefError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ChefError(f"{path} must be one of {schema['enum']}")
    if kind == "object":
        properties = schema["properties"]
        if set(value) - set(properties):
            raise ChefError(f"{path} contains unknown fields")
        if set(schema.get("required", [])) - set(value):
            raise ChefError(f"{path} is missing required fields")
        for key, item in value.items():
            validate(item, properties[key], f"{path}.{key}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ChefError(f"{path} has an invalid number of items")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if not schema.get("minLength", 0) <= len(value.strip()) <= schema.get("maxLength", 2000):
            raise ChefError(f"{path} has an invalid length")
    elif kind in {"number", "integer"}:
        if not math.isfinite(value) or not schema.get("minimum", -1e12) <= value <= schema.get(
            "maximum", 1e12
        ):
            raise ChefError(f"{path} is outside the allowed range")
