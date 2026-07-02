"""Dict-schema request validation (WS-A). Deliberately not Pydantic.

    from pyre import validate, ValidationError

    schema = {
        "id": str,                # required string
        "qty": int,               # required int (bool is NOT an int here)
        "note": (str, ""),        # optional with default
        "tags": [str],            # list of strings
        "meta": {"unit": str},    # nested object
    }
    clean = validate(req.json(), schema)

Failures raise ValidationError; the dispatcher converts it to a 400 JSON
response listing every offending field:

    {"error": "validation failed", "fields": {"qty": "expected int, got str"}}
"""

from pyre.errors import PyreError

_TYPE_NAMES = {str: "str", int: "int", float: "float", bool: "bool", dict: "object", list: "list"}


class ValidationError(PyreError):
    def __init__(self, fields):
        super().__init__("validation failed: %s" % ", ".join(sorted(fields)))
        self.fields = fields


def _type_name(expected):
    return _TYPE_NAMES.get(expected, getattr(expected, "__name__", str(expected)))


def _check(value, expected, path, errors):
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            errors[path] = "expected object, got %s" % type(value).__name__
            return None
        return _validate_dict(value, expected, path, errors)
    if isinstance(expected, list):
        item_schema = expected[0]
        if not isinstance(value, list):
            errors[path] = "expected list, got %s" % type(value).__name__
            return None
        cleaned = []
        for i, item in enumerate(value):
            cleaned.append(_check(item, item_schema, "%s[%d]" % (path, i), errors))
        return cleaned
    if expected is float:
        # ints are acceptable floats; bools are not numbers
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors[path] = "expected float, got %s" % type(value).__name__
            return None
        return float(value)
    if expected is int and isinstance(value, bool):
        errors[path] = "expected int, got bool"
        return None
    if not isinstance(value, expected):
        errors[path] = "expected %s, got %s" % (_type_name(expected), type(value).__name__)
        return None
    return value


def _validate_dict(data, schema, prefix, errors):
    clean = {}
    for field, spec in schema.items():
        path = "%s.%s" % (prefix, field) if prefix else field
        optional = isinstance(spec, tuple)
        expected, default = (spec[0], spec[1]) if optional else (spec, None)
        if field not in data:
            if optional:
                clean[field] = default
            else:
                errors[path] = "required field is missing"
            continue
        clean[field] = _check(data[field], expected, path, errors)
    return clean


def validate(data, schema):
    """Validate `data` (a dict, e.g. req.json()) against `schema`.

    Returns a cleaned dict containing exactly the schema's fields (extra
    input fields are dropped; optional fields get their defaults). Raises
    ValidationError listing every problem.
    """
    if not isinstance(data, dict):
        raise ValidationError({"": "expected a JSON object, got %s" % type(data).__name__})
    errors = {}
    clean = _validate_dict(data, schema, "", errors)
    if errors:
        raise ValidationError(errors)
    return clean
