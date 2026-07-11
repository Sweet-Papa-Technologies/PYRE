"""Versioned, collision-safe stable-key namespaces owned by PYRE."""

from urllib.parse import quote

from pyre import kv


def _component(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty string" % label)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("%s contains control characters" % label)
    return quote(value, safe="-._~")


def framework_prefix(subsystem, schema):
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise ValueError("schema must be a positive integer")
    prefix = "__pyre:%s:%d:" % (_component(subsystem, "subsystem"), schema)
    if len(prefix.encode("utf-8")) > kv.MAX_KEY_SIZE:
        raise ValueError("framework prefix exceeds %d bytes" % kv.MAX_KEY_SIZE)
    return prefix


def framework_key(subsystem, schema, kind, identity=None):
    key = framework_prefix(subsystem, schema) + _component(kind, "kind")
    if identity is not None:
        key += ":" + _component(identity, "identity")
    if len(key.encode("utf-8")) > kv.MAX_KEY_SIZE:
        raise ValueError("framework key exceeds %d bytes" % kv.MAX_KEY_SIZE)
    return key


def list_prefix(subsystem, schema):
    prefix = framework_prefix(subsystem, schema)
    return sorted(key for key in kv.keys() if key.startswith(prefix))


def delete_prefix(subsystem, schema, limit=None):
    if limit is not None and (not isinstance(limit, int) or limit < 0):
        raise ValueError("limit must be a non-negative integer or None")
    keys = list_prefix(subsystem, schema)
    if limit is not None:
        keys = keys[:limit]
    for key in keys:
        kv.delete(key)
    return len(keys)
